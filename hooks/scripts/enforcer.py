#!/usr/bin/env python3
"""
skill-concierge — semantic skill-first enforcer (UserPromptSubmit hook).

Supersedes the lexical ~/.claude/hooks/skill_first_nudge.py. On a non-trivial
prompt it embeds the query via the warm embed shim, retrieves the top-k semantic
candidates from the SAME Qdrant index skill-search serves, and injects an
enforcement mandate + those candidates (name · desc · score). It surfaces
semantically-relevant skills the old token-overlap scorer missed (e.g. an EN
prompt finding a VN-described skill with zero lexical overlap).

Design contract (mirrors the sibling ledger hook):
  • FAIL-SILENT — any error exits 0; a hook must never break or block a turn.
  • ADDITIVE-ONLY — only ever emits hookSpecificOutput.additionalContext.
  • NEVER BLOCKS — no exit-2, no "decision":"block".
  • STDLIB-ONLY + lazy — no heavy imports; the trivial-getaway path does no I/O.

Resilience / budget (Phase 3). The embed POST has a HARD client-side socket
timeout (default 200ms within a ≲300ms total per-turn budget — see EMBED_TIMEOUT_S
for the calibration history). On ANY of (a) embed unreachable, (b) Qdrant unreachable, (c)
embed exceeds the timeout, the hook falls back to MANDATE-ONLY — never silent,
never crashing — and stays within the per-turn budget regardless of shim health.
(c) is load-bearing: a reachability check misses an up-but-slow shim that would
otherwise silently tax every prompt.

Telemetry. Emits an `offer` event to the shared invocation ledger so analyze.py
can compute hit@k and fallback rate:
  {t, sid, ev:"offer", band, offered:[[name,score]...], fallback, q:<≤120c>}
"""
import sys
import os
import json
import time
import re
import socket
import urllib.request
from pathlib import Path

# ── endpoints ────────────────────────────────────────────────────────────────
EMBED_PORT = os.environ.get("EMBED_SHIM_PORT", "6363")
EMBED_HOST = os.environ.get("EMBED_SHIM_HOST", "127.0.0.1")
EMBED_URL = f"http://{EMBED_HOST}:{EMBED_PORT}/embed"
QDRANT_URL = os.environ.get("SKILL_QDRANT_URL", "http://localhost:6333").rstrip("/")
COLLECTION = os.environ.get("SKILL_COLLECTION", "claude_skills")
QUERY_URL = f"{QDRANT_URL}/collections/{COLLECTION}/points/query"

# ── tuning (calibrated on the live mpnet index, 2026-06-26) ───────────────────
# mpnet multilingual cosines are compressed into a narrow band: pure trivia
# ("thanks, that worked") tops ~0.11; real tasks land ~0.22-0.40. A single LOW
# getaway floor cleanly drops trivia while still surfacing modest-but-real
# semantic-jump matches (the whole point of going semantic). The score is a
# RANK signal, not absolute confidence — so we show top-k above the floor rather
# than gating hard on a high threshold. Tune from the ledger's offered-but-never-
# taken rollups once data accrues.
# HARD embed cap. History: design nominal ~120ms → tuned to 90ms to fit a ≲150ms
# total budget. But LIVE dogfooding showed ~60% of turns hit embed_timeout: the
# single-threaded shim's inference, under real in-turn CPU contention (concurrent
# UserPromptSubmit hooks + overlapping sessions), exceeded 90ms even though it's
# ~18ms idle. Fix (owner-approved): threaded shim (embed_server.py) + relax the
# budget to ≲300ms total → 200ms embed cap. Worst slow-path ≈ 50ms cold-start +
# 200ms cap ≈ 250ms ≲ 300ms; happy path stays ~100ms. Raise/lower via env.
EMBED_TIMEOUT_S = float(os.environ.get("ENFORCER_EMBED_TIMEOUT", "0.20"))
QDRANT_TIMEOUT_S = float(os.environ.get("ENFORCER_QDRANT_TIMEOUT", "0.1"))
TOP_K = int(os.environ.get("ENFORCER_TOP_K", "5"))
GETAWAY_FLOOR = float(os.environ.get("ENFORCER_GETAWAY_FLOOR", "0.45"))  # top<this → silent. OPERATOR-SET 0.45 (2026-06-29, ADR-0009) raised from 0.40 on perceived behaviour; the ledger/corpus analysis argued AGAINST it (taken offers score LOWER than dodged, so a higher floor cuts the better-converting offers first). Do NOT change without re-opening ADR-0009 (data-backed alternative: 0.40 / env ENFORCER_GETAWAY_FLOOR).
ITEM_FLOOR = float(os.environ.get("ENFORCER_ITEM_FLOOR", "0.18"))       # per-candidate cutoff
MAX_SHORT_WORDS = 5   # ≤ this many words → trivial getaway, skip embed entirely. OPERATOR-SET 5 (2026-06-29, ADR-0009) raised from 2 on perceived behaviour; analysis argued AGAINST it (~93% of conversational noise is >5 words so this misses it; the 3-5w band is ~2:1 actionable:conversational and this runs BEFORE the imperative-veto that protects short commands). Do NOT change without re-opening ADR-0009 (data-backed alternative: 2).
_DESC_CHARS = 96

# ── actionability gate (prior-independent class-margin over the prompt_intent corpus) ─
# A relevant skill clearing the floor is NOT enough: most "dodged" offers land on
# conversational/status/meta turns that match a skill topically but want none. The gate
# suppresses an offer ONLY when the prompt is non-imperative AND sits closer to
# CONVERSATIONAL space than ACTIONABLE space by a margin (mean top-K cosine to each class).
# A class-MARGIN, not an absolute neighbour count, is used because conversational is the
# minority (~30%) of the ~1.7k-prompt corpus — an absolute count is biased by that prior
# and went inert on novel phrasing. Tuned M=0.03 -> ~2% false-suppression on a held-out
# backtest; validated to fire on out-of-distribution prompts. Fail-OPEN everywhere
# (missing collection / empty class / any error / imperative prompt -> offer).
PROMPT_INTENT_COLLECTION = os.environ.get("SKILL_PROMPT_INTENT_COLLECTION", "prompt_intent")
INTENT_QUERY_URL = f"{QDRANT_URL}/collections/{PROMPT_INTENT_COLLECTION}/points/query"
INTENT_K = int(os.environ.get("ENFORCER_INTENT_K", "10"))                # neighbours per class for the mean-similarity
INTENT_MARGIN = float(os.environ.get("ENFORCER_INTENT_MARGIN", "0.03"))  # suppress iff (conv_sim - act_sim) > this
_IMPERATIVE_VERBS = frozenset(
    "fix build create add write implement refactor update integrate decouple run test debug "
    "remove delete rename convert migrate deploy generate make set install check verify review "
    "analyze analyse scan audit do apply enrich wire patch revert merge commit push save extract "
    "port draft design optimize optimise configure investigate trace diagnose produce render "
    "compile lint format sort filter parse split trash drop kill start stop restart clean tidy "
    "bump tag release clone pull fetch mine label embed".split())
_FILLER = frozenset(
    "now ok okay so well then please alright also and but lets let's pls just next first go right "
    "cool good great yes yeah sure hey actually".split())

LOG_DIR = Path(os.environ.get(
    "SKILL_CONCIERGE_LOG", Path.home() / ".claude" / "skill-telemetry" / "logs"))
LEDGER = LOG_DIR / "skill-invocation-ledger.log"

# Per-turn GATE TRIGGER — the cheap re-assert. The full SKILL-FIRST standing order
# is injected once at SessionStart (doctrine.py); this keeps it live in attention
# every turn without re-paying the rich version. Pre-commitment, not persuasion: it
# forces a line-1 token and turns "the few don't fit" into an order to SEARCH, never
# a skip. In-generation only — no post-turn detection.
# (EFFORT was decoupled to the standalone effort-gate plugin in v0.4.0; this hook
# now governs which/whether a skill only.)
MANDATE = (
    "SKILL-FIRST — line 1 of your reply = one of: "
    "USING <skill> | SEARCH <query> | SKIPPING none.\n"
    "The skills shown each turn are a top-few PREVIEW, not the ~500-skill inventory. "
    "\"Few don't fit\" / \"I'm confident\" / \"I can handle it\" are NOT skips — they order "
    "you to SEARCH the full index (search_skills) before any SKIPPING; show the query. "
    "SKIPPING is lawful only after a search returns nothing usable. "
    "[full standing order: session start]"
)


# Explicit skill-refusal pattern (Phase A / C3, verified 2026-06-28). mpnet cosine
# does NOT encode negation: an affirmed vs negated prompt embeds ~0.65-0.87 cosine,
# so a refusal like "do not use the <X> skill" still retrieves <X> at full score. A
# BROAD any-negation rule (the bm25 hook's approach) over-suppresses — bug-report
# prompts ("tests are not passing", "never finishes") carry a negation token yet
# genuinely need skills (3/4 wrongly suppressed in testing). So anchor on negation +
# an explicit INVOCATION-META verb (use/invoke/apply/call/rely-on/trigger/activate),
# NOT action verbs that recur in bug reports. High precision, low recall by design;
# a leaked offer is additive + low-blast (the agent reads the real prompt and won't
# act on a refused skill). Contract pinned in `--selftest`.
_REFUSAL_RE = re.compile(
    r"\b(?:do\s+not|do\s*n['\u2019]?t|don['\u2019]?t|never|please\s+do\s*n['\u2019]?t)\s+"
    r"(?:use|using|invoke|invoking|apply|applying|call|calling|trigger|activate|rely\s+on)\b"
    r"|\bwithout\s+(?:use|using|invoking|applying|calling)\b"
    r"|\bskip\s+\w+ing\b",
    re.IGNORECASE,
)


def _clean(s: str) -> str:
    return " ".join((s or "").split())


def _append_offer(sid: str, band: str, offered: list, fallback, q: str) -> None:
    """Append the offer event. Fail-silent: telemetry must never surface."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        ev = {"t": round(time.time(), 3), "sid": sid, "ev": "offer",
              "band": band, "offered": offered, "fallback": fallback, "q": q[:120]}
        with LEDGER.open("a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _inject(text: str) -> None:
    sys.stdout.write(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": text,
        }
    }))


def _post_json(url: str, payload: dict, timeout: float) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _embed(text: str) -> list:
    """Embed via the warm shim under a HARD timeout. Raises on down/slow so the
    caller falls back to mandate-only."""
    return _post_json(EMBED_URL, {"text": text}, EMBED_TIMEOUT_S)["vector"]


def _retrieve(vector: list) -> list:
    """Top-k from Qdrant via raw REST (stdlib only). Returns [(name, desc, score)]."""
    res = _post_json(QUERY_URL,
                     {"query": vector, "limit": TOP_K, "with_payload": True},
                     QDRANT_TIMEOUT_S)
    out = []
    for p in res.get("result", {}).get("points", []):
        pl = p.get("payload", {}) or {}
        out.append((pl.get("name", "?"), pl.get("description", ""), float(p.get("score", 0.0))))
    return out


def _ranked_mandate(cands: list) -> str:
    # Confidence as %-SHARE of the shown candidates' score mass (Phase A2), not the
    # raw cosine. mpnet cosines sit in a compressed ~0.18-0.40 band that reads as
    # noise to the agent; relative share ("58%" vs "31%") disambiguates WHICH
    # candidate fits far more legibly. Absolute relevance is already guaranteed
    # upstream (GETAWAY_FLOOR + ITEM_FLOOR gate before this runs), and raw scores
    # are still logged to the ledger — so dropping them from the DISPLAY loses no
    # signal. Share is shown only with 2+ candidates (a lone candidate is always
    # 100% → meaningless), and the disambiguation note rides the same condition.
    total = sum(s for (_n, _d, s) in cands) or 1.0
    multi = len(cands) > 1
    lines = []
    for name, desc, score in cands:
        blurb = _clean(desc)
        if len(blurb) > _DESC_CHARS:
            blurb = blurb[:_DESC_CHARS].rsplit(" ", 1)[0] + "…"
        pct = f" ({round(score / total * 100)}%)" if multi else ""
        lines.append(f"  • {name}{pct} — {blurb}")
    note = "\nMultiple candidates — pick the one matching the actual intent." if multi else ""
    return (
        "SKILL-FIRST — line 1 of your reply = one of: "
        "USING <skill> | SEARCH <query> | SKIPPING none.\n"
        "Top-few PREVIEW for this request (NOT the full ~500-skill shelf):\n"
        + "\n".join(lines) + note + "\n"
        "None fit? That is not a skip — SEARCH the full index (search_skills) before any "
        "SKIPPING; show the query. Closest fit, adapted, is the standard; perfect is not the bar. "
        "[full standing order: session start]"
    )


def _is_imperative(prompt: str) -> bool:
    """Veto signal for the actionability gate: does the prompt OPEN with a task verb
    (after skipping leading fillers and 'can you'-style openers)? Imperative turns are
    NEVER suppressed — they are the actionable turns the gate must protect, since a
    false-suppressed offer is the costly error. High precision on the open, low recall by
    design (most real tasks don't open with a clean verb — the kNN catches those)."""
    toks = re.findall(r"[a-z']+", prompt.lower())
    i = 0
    skips = {("can", "you"), ("could", "you"), ("would", "you"), ("i", "want"), ("i", "need")}
    while i < len(toks):
        if toks[i] in _FILLER:
            i += 1
            continue
        if i + 1 < len(toks) and (toks[i], toks[i + 1]) in skips:
            i += 2
            continue
        break
    return i < len(toks) and toks[i] in _IMPERATIVE_VERBS


def _intent_conversational(vector: list) -> bool:
    """Prior-independent actionability gate: True only when the prompt sits closer to
    CONVERSATIONAL space than ACTIONABLE space by a margin. Two label-filtered kNN queries
    over prompt_intent; mean cosine of the top-INTENT_K per class; suppress iff
    (conv_mean - act_mean) > INTENT_MARGIN. Reuses the embedding the enforcer already
    computed. Fail-OPEN: missing collection / empty class / any error -> False (offer)."""
    def _class_sim(label):
        res = _post_json(INTENT_QUERY_URL,
                         {"query": vector,
                          "filter": {"must": [{"key": "label", "match": {"value": label}}]},
                          "limit": INTENT_K},
                         QDRANT_TIMEOUT_S)
        pts = res.get("result", {}).get("points", []) or []
        return (sum(float(p.get("score", 0.0)) for p in pts) / len(pts)) if pts else None
    try:
        conv_sim = _class_sim("conversational")
        act_sim = _class_sim("actionable")
        if conv_sim is None or act_sim is None:
            return False
        return (conv_sim - act_sim) > INTENT_MARGIN
    except Exception:
        return False


def main() -> int:
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
        if not isinstance(data, dict):
            return 0
        prompt = (data.get("prompt") or "").strip()
        sid = data.get("session_id", "")

        # Cheap pre-gate (no I/O): empty, explicit slash-command (user already
        # chose a route), or an ultra-short acknowledgement. These never embed.
        if not prompt or prompt.startswith("/"):
            return 0
        if len(prompt.split()) <= MAX_SHORT_WORDS:
            return 0

        # Explicit skill-refusal -> MANDATE-ONLY (never surface the skill the user
        # just refused; keep the SKILL-FIRST discipline live). See _REFUSAL_RE.
        if _REFUSAL_RE.search(prompt):
            _inject(MANDATE)
            _append_offer(sid, "negation", [], "skill_refusal", prompt)
            return 0

        # Embed (HARD ~200ms timeout, EMBED_TIMEOUT_S) → mandate-only on down/slow.
        try:
            vector = _embed(prompt)
        except (socket.timeout, TimeoutError):
            _inject(MANDATE)
            _append_offer(sid, "fallback", [], "embed_timeout", prompt)
            return 0
        except Exception:
            _inject(MANDATE)
            _append_offer(sid, "fallback", [], "embed_down", prompt)
            return 0

        # Retrieve → mandate-only fallback if Qdrant is unreachable.
        try:
            cands = _retrieve(vector)
        except Exception:
            _inject(MANDATE)
            _append_offer(sid, "fallback", [], "qdrant_down", prompt)
            return 0

        top = cands[0][2] if cands else 0.0
        offered = [[n, round(s, 4)] for (n, _d, s) in cands]

        if top < GETAWAY_FLOOR:
            # No semantic fit → trivial/out-of-catalogue. Stay silent (getaway),
            # but log the consideration so coverage/fallback stats stay honest.
            _append_offer(sid, "getaway", offered, None, prompt)
            return 0

        # Actionability gate (prior-independent class-margin). A relevant skill cleared the
        # floor — but if this is a NON-imperative turn that leans conversational over
        # actionable, the offer is noise the agent reliably dodges. Suppress it. Fail toward
        # offering (imperative OR any error -> offer). Backtest ~2% false-suppression; fires on novel input.
        if not _is_imperative(prompt) and _intent_conversational(vector):
            _append_offer(sid, "intent_skip", offered, "conversational", prompt)
            return 0

        shown = [(n, d, s) for (n, d, s) in cands if s >= ITEM_FLOOR] or cands[:1]
        _inject(_ranked_mandate(shown))
        _append_offer(sid, "offer",
                      [[n, round(s, 4)] for (n, _d, s) in shown], None, prompt)
    except Exception:
        return 0  # fail-silent, never block
    return 0


def _selftest() -> int:
    """Pin two contracts: (1) the refusal guard fires on explicit skill-refusal and
    stays silent on affirmations + bug-report negations; (2) _ranked_mandate renders
    %-share + a disambiguation note for 2+ candidates, and neither for a lone one.
    Run: python3 enforcer.py --selftest"""
    must_fire = [
        "do not use the <skill> here",
        "please don't invoke that skill",
        "without using the test skill, just patch it",
        "skip reviewing this file",
        "never apply the formatter",
    ]
    must_not_fire = [
        "use the test skill to check this",                # affirmation
        "fix the bug where login does not work",           # bug report
        "the tests are not passing, help me debug",        # bug report
        "this deploy never finishes, investigate why",     # bug report
        "this function does not return the right value",   # bug report
        "ship this application to production",             # affirmation
    ]
    bad = []
    for t in must_fire:
        if not _REFUSAL_RE.search(t):
            bad.append("MISS (should fire): " + repr(t))
    for t in must_not_fire:
        if _REFUSAL_RE.search(t):
            bad.append("FALSE-FIRE (should stay silent): " + repr(t))
    # (2) ranked-mandate %-share + disambiguation note
    multi = _ranked_mandate([("alpha", "desc alpha", 0.30), ("beta", "desc beta", 0.10)])
    if "(75%)" not in multi or "(25%)" not in multi:
        bad.append("ranked_mandate: expected 75%/25% shares")
    if "Multiple candidates" not in multi:
        bad.append("ranked_mandate: missing disambiguation note for 2+ candidates")
    lone = _ranked_mandate([("alpha", "desc alpha", 0.25)])
    if "%" in lone or "Multiple candidates" in lone:
        bad.append("ranked_mandate: lone candidate must show no share and no note")
    if "• alpha — desc alpha" not in lone:
        bad.append("ranked_mandate: lone candidate line malformed")

    # (3) actionability gate — the imperative VETO fires on task-verb openers and stays
    # off for conversational/question/approval turns (the gate suppresses ONLY non-imperatives).
    imp_fire = ["fix the typo on line 12", "now, write the handoff", "please run the tests",
                "can you refactor this", "delete the cloned copy", "integrate the EFFORT gate"]
    imp_off = ["how's the documentation status?", "good direction we're heading",
               "what does this function do", "i think we should reconsider",
               "thanks that worked", "yes please"]
    for t in imp_fire:
        if not _is_imperative(t):
            bad.append("imperative MISS (should fire): " + repr(t))
    for t in imp_off:
        if _is_imperative(t):
            bad.append("imperative FALSE-FIRE (should stay off): " + repr(t))

    if bad:
        print("enforcer --selftest FAIL:")
        for b in bad:
            print("  " + b)
        return 1
    print("enforcer --selftest OK: refusal guard (%d fire / %d silent) + ranked-mandate %%-share "
          "+ actionability imperative-veto (%d fire / %d off)"
          % (len(must_fire), len(must_not_fire), len(imp_fire), len(imp_off)))
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    sys.exit(main())
