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
import unicodedata
import urllib.request
from pathlib import Path

# ── endpoints ────────────────────────────────────────────────────────────────
EMBED_PORT = os.environ.get("EMBED_SHIM_PORT", "6363")
EMBED_HOST = os.environ.get("EMBED_SHIM_HOST", "127.0.0.1")
EMBED_URL = f"http://{EMBED_HOST}:{EMBED_PORT}/embed"
QDRANT_URL = os.environ.get("SKILL_QDRANT_URL", "http://localhost:6333").rstrip("/")
COLLECTION = os.environ.get("SKILL_COLLECTION", "claude_skills")
QUERY_GROUPS_URL = f"{QDRANT_URL}/collections/{COLLECTION}/points/query/groups"

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
MAX_SHORT_WORDS = 3   # ≤ this many words → trivial getaway, skip embed entirely. OPERATOR-SET 3 (2026-06-29, ADR-0010 supersedes ADR-0009 word floor) lowered from 5 so the now-language-aware imperative-veto sees 4-5w commands (incl. Vietnamese) the old floor dropped pre-veto; ≤3w ultra-short trivia still skipped. (data-backed analysis favored 2; operator chose 3.) Do NOT change without a superseding ADR.
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
    "cool good great yes yeah sure hey actually hãy xin".split())

# ── Vietnamese imperative lexicon (mirrors _IMPERATIVE_VERBS for VN task prompts) ──
# The English veto was blind to Vietnamese; the tokenizer now keeps diacritics, and these sets give
# the leading-token check Vietnamese verbs. Vietnamese is analytic — many task verbs are two
# syllables ("kiểm tra", "cài đặt") — so we test the leading token against _VN_VERBS AND the
# leading bigram against _VN_VERB_BIGRAMS. High-precision core; the kNN gate catches the long tail.
# ponytail: core lexicon — widen from real VN prompts if recall proves short.
_VN_VERBS = frozenset(
    "sửa viết tạo chạy xóa xoá thêm dịch gỡ vá soạn lưu quét gộp tách mở đóng kéo đẩy tải "
    "đọc tìm lọc gọi dựng đổi thử dán nén bỏ cài vẽ".split())
_VN_VERB_BIGRAMS = frozenset([
    ("kiểm", "tra"), ("rà", "soát"), ("cài", "đặt"), ("phân", "tích"), ("tối", "ưu"),
    ("triển", "khai"), ("xử", "lý"), ("cập", "nhật"), ("sửa", "lỗi"), ("chỉnh", "sửa"),
    ("thiết", "kế"), ("tích", "hợp"), ("gỡ", "lỗi"), ("kiểm", "thử"), ("biên", "dịch"),
    ("định", "dạng"), ("khởi", "động"), ("xác", "minh"), ("tái", "cấu"), ("dọn", "dẹp"),
    ("sao", "chép"), ("rà", "lại"),
])


LOG_DIR = Path(os.environ.get(
    "SKILL_CONCIERGE_LOG", Path.home() / ".claude" / "skill-telemetry" / "logs"))
LEDGER = LOG_DIR / "skill-invocation-ledger.log"

# ── offer-suppression keep-off map (ADR-0011) ────────────────────────────
# Hard-drop chronic never-take skills from the OFFER MENU only (still catalogue-reachable
# via search_skills). Generated by scripts/build_keep_off.py from a post-enrichment clean
# window. FAIL-OPEN: missing/empty/bad file -> empty set -> no suppression.
_KEEPOFF_PATH = Path(os.environ.get(
    "SKILL_CONCIERGE_KEEPOFF",
    Path(__file__).resolve().parents[2] / "config" / "keep-off.json"))


def _load_keepoff() -> frozenset:
    try:
        data = json.loads(_KEEPOFF_PATH.read_text(encoding="utf-8"))
        return frozenset(n for n in data.get("keep_off", []) if isinstance(n, str))
    except Exception:
        return frozenset()  # fail-open: suppression-config must never break a turn


KEEPOFF = _load_keepoff()


def _drop_keepoff(cands: list, keepoff: frozenset):
    """Split retrieved cands into (survivors, dropped-names) by the keep-off set. Pure +
    order-preserving so P6's later gap-collapse runs over the POST-suppression set."""
    survivors = [c for c in cands if c[0] not in keepoff]
    dropped = [c[0] for c in cands if c[0] in keepoff]
    return survivors, dropped


# ── per-skill calibrated tau (Phase D wiring, default-INERT) ───────────────
# Wire eval/thresholds.json so an `ok`-calibrated skill gates on ITS OWN tau instead of the
# single global GETAWAY_FLOOR. DEFAULT OFF (ENFORCER_PER_SKILL_TAU unset) -> _PER_SKILL_TAU is
# empty -> _floor_for() returns the global floor -> behaviour byte-identical to today.
# WHY OFF BY DEFAULT (data, 2026-06-30): all 5 current `ok` skills calibrate to tau < 0.45 (one
# negative), so arming this LOWERS their bar and ADDS the false-offers ADR-0009 tuned against.
# On the compressed-cosine band the lever is index CONTENT (multi-vector), not thresholds —
# calibrate_thresholds.py says the same. Mechanism shipped + tested; arm only after a substrate
# change lifts separation. Opt in: export ENFORCER_PER_SKILL_TAU=1.  FAIL-OPEN on a bad file.
_THRESHOLDS_PATH = Path(os.environ.get(
    "SKILL_THRESHOLDS",
    Path(__file__).resolve().parents[2] / "eval" / "thresholds.json"))


def _load_per_skill_tau() -> dict:
    if not os.environ.get("ENFORCER_PER_SKILL_TAU", "").strip():
        return {}  # default-inert
    try:
        data = json.loads(_THRESHOLDS_PATH.read_text(encoding="utf-8"))
        return {k: float(v["tau"]) for k, v in data.items()
                if v.get("status") == "ok" and isinstance(v.get("tau"), (int, float))}
    except Exception:
        return {}  # fail-open: a bad thresholds file must never break a turn


_PER_SKILL_TAU = _load_per_skill_tau()


def _floor_for(name: str) -> float:
    """Getaway floor for a candidate: its calibrated per-skill tau when armed AND `ok`,
    else the global floor. Inert by default (_PER_SKILL_TAU empty)."""
    return _PER_SKILL_TAU.get(name, GETAWAY_FLOOR)


# ── deterministic route overrides (default-INERT) ──────────────────────────
# A tiny, high-precision exact-substring -> skill map for intents where semantic ranking is
# unreliable but the intent is unambiguous. GUARANTEES the mapped skill in the menu (prepended,
# deduped) — additive, never blocks, and a hit bypasses getaway + the actionability gate.
# DEFAULT OFF: loaded only when ENFORCER_DETERMINISTIC is set; missing/empty config -> no-op.
# CURATE SPARINGLY — this system's dodge is dominated by FALSE offers, so every route must be
# near-zero false-positive. config/deterministic-routes.json: {"routes":[{"contains":"<lower
# substring>","skill":"<exact name>"}]}.  Opt in: export ENFORCER_DETERMINISTIC=1.
_ROUTES_PATH = Path(os.environ.get(
    "SKILL_CONCIERGE_ROUTES",
    Path(__file__).resolve().parents[2] / "config" / "deterministic-routes.json"))


def _load_routes() -> list:
    if not os.environ.get("ENFORCER_DETERMINISTIC", "").strip():
        return []  # default-inert
    try:
        data = json.loads(_ROUTES_PATH.read_text(encoding="utf-8"))
        return [(r["contains"].lower(), r["skill"]) for r in data.get("routes", [])
                if isinstance(r.get("contains"), str) and isinstance(r.get("skill"), str)
                and r["contains"].strip()]
    except Exception:
        return []  # fail-open


_ROUTES = _load_routes()


def _deterministic_hits(prompt: str, cands: list) -> list:
    """Skills whose exact-substring route matches the prompt but retrieval missed. Returns
    [(name, desc, score)] to PREPEND (score=1.0 so it leads + clears every floor). Order-
    preserving, de-duped against cands. Inert by default (_ROUTES empty)."""
    if not _ROUTES:
        return []
    low = prompt.lower()
    have = {n for (n, _d, _s) in cands}
    out = []
    for sub, skill in _ROUTES:
        if sub in low and skill not in have:
            out.append((skill, "deterministic route", 1.0))
            have.add(skill)
    return out


# ── P6: runner-up-gap menu collapse (default-INERT) ──────────────────
# Collapse the menu to the top skill when it is clearly ahead of the runner-up by RAW-score
# gap (NOT %-share, which never concentrates: top-share maxes ~0.285 on the live ledger).
# Default OFF — no evidence collapsing improves conversion; gap>=1.25 fires only ~5%. Opt in
# by exporting ENFORCER_DOMINANCE_RATIO=<ratio>.
_DR = os.environ.get("ENFORCER_DOMINANCE_RATIO", "").strip()
try:
    DOMINANCE_RATIO = float(_DR) if _DR else None
except ValueError:
    DOMINANCE_RATIO = None  # fail-silent on a malformed opt-in value (hook contract)

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


def _append_offer(sid: str, band: str, offered: list, fallback, q: str, dropped=None) -> None:
    """Append the offer event. Fail-silent: telemetry must never surface."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        ev = {"t": round(time.time(), 3), "sid": sid, "ev": "offer",
              "band": band, "offered": offered, "fallback": fallback, "q": q[:120]}
        if dropped:
            ev["dropped"] = dropped
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
    """Top-k SKILLS from Qdrant via raw REST (stdlib only), MAX-pooled: group_by name with one
    best point per skill (group_size=1). Identical to a plain top-k on a single-vector index; on
    the multi-vector index each skill is scored by its single best phrase point. Returns
    [(name, desc, score)]."""
    res = _post_json(QUERY_GROUPS_URL,
                     {"query": vector, "group_by": "name", "limit": TOP_K,
                      "group_size": 1, "with_payload": ["name", "description"]},
                     QDRANT_TIMEOUT_S)
    out = []
    for g in res.get("result", {}).get("groups", []):
        hits = g.get("hits", [])
        if not hits:
            continue
        pl = hits[0].get("payload", {}) or {}
        out.append((pl.get("name", g.get("id", "?")), pl.get("description", ""),
                    float(hits[0].get("score", 0.0))))
    return out


def _apply_dominance(cands: list) -> list:
    """P6 (default-inert): collapse to the top skill when it is clearly ahead of the runner-up by
    RAW-score gap. Decided HERE (not in _ranked_mandate) so the CALLER logs the post-collapse menu —
    agent and ledger see the same set. Off unless ENFORCER_DOMINANCE_RATIO is set."""
    if (DOMINANCE_RATIO and len(cands) >= 2 and cands[1][2] > 0
            and cands[0][2] / cands[1][2] >= DOMINANCE_RATIO):
        return [cands[0]]
    return cands


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
    toks = re.findall(r"[^\W\d_]+(?:'[^\W\d_]+)*", unicodedata.normalize("NFC", prompt).lower())
    i = 0
    skips = {("can", "you"), ("could", "you"), ("would", "you"), ("i", "want"), ("i", "need"),
             ("làm", "ơn"), ("vui", "lòng")}
    while i < len(toks):
        if toks[i] in _FILLER:
            i += 1
            continue
        if i + 1 < len(toks) and (toks[i], toks[i + 1]) in skips:
            i += 2
            continue
        break
    if i >= len(toks):
        return False
    if toks[i] in _IMPERATIVE_VERBS or toks[i] in _VN_VERBS:
        return True
    return i + 1 < len(toks) and (toks[i], toks[i + 1]) in _VN_VERB_BIGRAMS


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

        # P5 (ADR-0011): hard-drop chronic never-take skills BEFORE floors/gate/rank, so they
        # vanish from the menu and from P6's collapse set. Fail-open (KEEPOFF empty -> no-op).
        cands, _dropped = _drop_keepoff(cands, KEEPOFF)

        # Deterministic routes (default-inert): guarantee an unambiguously-intended skill in
        # the menu even when semantic ranking missed it. A hit leads (score 1.0) and bypasses
        # both the getaway and the actionability gate (the intent is explicit).
        det = _deterministic_hits(prompt, cands)
        if det:
            cands = det + cands

        top = cands[0][2] if cands else 0.0
        offered = [[n, round(s, 4)] for (n, _d, s) in cands]

        # Getaway: top candidate below its floor (per-skill tau when armed+`ok`, else the
        # global floor). A deterministic hit always clears — it IS the intent.
        if not det and top < (_floor_for(cands[0][0]) if cands else GETAWAY_FLOOR):
            # No semantic fit → trivial/out-of-catalogue. Stay silent (getaway),
            # but log the consideration so coverage/fallback stats stay honest.
            _append_offer(sid, "getaway", offered, None, prompt, dropped=_dropped or None)
            return 0

        # Actionability gate (prior-independent class-margin). A relevant skill cleared the
        # floor — but if this is a NON-imperative turn that leans conversational over
        # actionable, the offer is noise the agent reliably dodges. Suppress it. Fail toward
        # offering (imperative OR any error -> offer). Backtest ~2% false-suppression; fires on novel input.
        if not det and not _is_imperative(prompt) and _intent_conversational(vector):
            _append_offer(sid, "intent_skip", offered, "conversational", prompt, dropped=_dropped or None)
            return 0

        shown = [(n, d, s) for (n, d, s) in cands if s >= ITEM_FLOOR] or cands[:1]
        shown = _apply_dominance(shown)   # P6 collapse decided once: agent + ledger see the same set
        _inject(_ranked_mandate(shown))
        _append_offer(sid, "offer",
                      [[n, round(s, 4)] for (n, _d, s) in shown], None, prompt,
                      dropped=_dropped or None)
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
    # NOTE: production main() drops prompts with <= MAX_SHORT_WORDS (3) words BEFORE _is_imperative
    # runs, so the veto only matters for >5-word prompts. The >5-word VN cases below represent that
    # production-reachable population; the <=5-word cases pin the function's correctness directly.
    imp_fire = ["fix the typo on line 12", "now, write the handoff", "please run the tests",
                "can you refactor this", "delete the cloned copy", "integrate the EFFORT gate",
                "let's run the tests",
                "sửa lỗi ở dòng 12", "hãy viết báo cáo", "chạy test giúp mình",
                "kiểm tra file này", "cài đặt thư viện", "phân tích log lỗi",
                "làm ơn dịch đoạn này", "tối ưu hàm này",
                "hãy sửa giúp mình cái lỗi đăng nhập ở trang chủ",
                "phân tích các log lỗi trong thư mục build hôm nay"]
    imp_off = ["how's the documentation status?", "good direction we're heading",
               "what does this function do", "i think we should reconsider",
               "thanks that worked", "yes please",
               "tài liệu thế nào rồi", "hàm này làm gì vậy",
               "mình nghĩ nên xem lại", "cảm ơn nhé",
               "cái hàm xử lý đăng nhập này hoạt động như thế nào vậy",
               "theo bạn thì mình có nên viết lại phần này không"]
    for t in imp_fire:
        if not _is_imperative(t):
            bad.append("imperative MISS (should fire): " + repr(t))
    for t in imp_off:
        if _is_imperative(t):
            bad.append("imperative FALSE-FIRE (should stay off): " + repr(t))

    # (4) keep-off hard-drop: listed names removed, order preserved, fail-open on empty set.
    surv, drp = _drop_keepoff([("a", "", 0.3), ("bad", "", 0.2), ("c", "", 0.1)], frozenset({"bad"}))
    if [n for n, _, _ in surv] != ["a", "c"] or drp != ["bad"]:
        bad.append("keepoff drop wrong: survivors=%s dropped=%s" % ([n for n, _, _ in surv], drp))
    s2, d2 = _drop_keepoff([("a", "", 0.3)], frozenset())
    if [n for n, _, _ in s2] != ["a"] or d2 != []:
        bad.append("keepoff empty-set must pass everything through")

    # (5) P6 gap-collapse: decided in _apply_dominance (so the CALLER logs the post-collapse menu),
    # default-inert. Plus a collapsed input must render as a lone candidate (no %-share, no note).
    global DOMINANCE_RATIO
    _saved = DOMINANCE_RATIO
    try:
        DOMINANCE_RATIO = 1.25
        if _apply_dominance([("a", "da", 0.30), ("b", "db", 0.20)]) != [("a", "da", 0.30)]:
            bad.append("dominance: should collapse to top when gap >= ratio")
        if len(_apply_dominance([("a", "da", 0.30), ("b", "db", 0.28)])) != 2:
            bad.append("dominance: should NOT collapse a flat menu (gap < ratio)")
        DOMINANCE_RATIO = None
        if len(_apply_dominance([("a", "da", 0.30), ("b", "db", 0.20)])) != 2:
            bad.append("dominance: default-inert must not collapse")
    finally:
        DOMINANCE_RATIO = _saved
    lone_collapsed = _ranked_mandate([("a", "da", 0.30)])
    if "%" in lone_collapsed or "Multiple candidates" in lone_collapsed:
        bad.append("collapsed render must be lone (no %-share / note)")

    # (6) per-skill tau + deterministic routes — BOTH default-INERT (no env set in this test).
    global _PER_SKILL_TAU, _ROUTES
    if _PER_SKILL_TAU != {}:
        bad.append("per-skill tau must be empty/inert by default (ENFORCER_PER_SKILL_TAU unset)")
    if _ROUTES != []:
        bad.append("deterministic routes must be empty/inert by default (ENFORCER_DETERMINISTIC unset)")
    if _floor_for("whatever") != GETAWAY_FLOOR:
        bad.append("floor_for must return the global floor when inert")
    _saved_tau, _saved_routes = _PER_SKILL_TAU, _ROUTES
    try:
        _PER_SKILL_TAU = {"vn-author": 0.30}
        if _floor_for("vn-author") != 0.30:
            bad.append("floor_for must use per-skill tau for an armed `ok` skill")
        if _floor_for("uncalibrated") != GETAWAY_FLOOR:
            bad.append("floor_for must fall back to the global floor for an uncalibrated skill")
        _ROUTES = [("open a pull request", "ck:git")]
        hit = [n for n, _d, _s in _deterministic_hits("please open a pull request now", [("o", "", 0.3)])]
        if hit != ["ck:git"]:
            bad.append("deterministic route must fire on a substring match: %s" % hit)
        if _deterministic_hits("an unrelated prompt", [("o", "", 0.3)]) != []:
            bad.append("deterministic route must not fire without a match")
        if _deterministic_hits("open a pull request", [("ck:git", "", 0.3)]) != []:
            bad.append("deterministic route must not duplicate an already-present skill")
    finally:
        _PER_SKILL_TAU, _ROUTES = _saved_tau, _saved_routes

    if bad:
        print("enforcer --selftest FAIL:")
        for b in bad:
            print("  " + b)
        return 1
    print("enforcer --selftest OK: refusal guard (%d fire / %d silent) + ranked-mandate %%-share "
          "+ actionability imperative-veto (%d fire / %d off) + keepoff-drop + gap-collapse "
          "+ per-skill-tau/deterministic-routes (default-inert)"
          % (len(must_fire), len(must_not_fire), len(imp_fire), len(imp_off)))
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    sys.exit(main())
