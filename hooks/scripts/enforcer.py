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
GETAWAY_FLOOR = float(os.environ.get("ENFORCER_GETAWAY_FLOOR", "0.20"))  # top<this → silent
ITEM_FLOOR = float(os.environ.get("ENFORCER_ITEM_FLOOR", "0.18"))       # per-candidate cutoff
MAX_SHORT_WORDS = 2   # ≤ this many words → trivial getaway, skip embed entirely
_DESC_CHARS = 96

LOG_DIR = Path(os.environ.get(
    "SKILL_CONCIERGE_LOG", Path.home() / ".claude" / "skill-telemetry" / "logs"))
LEDGER = LOG_DIR / "skill-invocation-ledger.log"

# Per-turn GATE TRIGGER — the cheap re-assert. The full standing order is injected
# once at SessionStart (doctrine.py); this keeps it live in attention every turn
# without re-paying the rich version. Pre-commitment, not persuasion: it forces a
# line-1 token and turns "the few don't fit" into an order to SEARCH, never a skip.
# Injected alone on fallback (shim/Qdrant down), or above the candidate preview.
MANDATE = (
    "SKILL-FIRST — line 1 of your reply = one of: "
    "USING <skill> | SEARCH <query> | SKIPPING none.\n"
    "The skills shown each turn are a top-few PREVIEW, not the ~500-skill inventory. "
    "\"Few don't fit\" / \"I'm confident\" / \"I can handle it\" are NOT skips — they order "
    "you to SEARCH the full index (search_skills) before any SKIPPING; show the query. "
    "SKIPPING is lawful only after a search returns nothing usable.\n"
    "Terse words, full work — not the cheap stop. [full standing order: session start]"
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
    lines = []
    for name, desc, score in cands:
        blurb = _clean(desc)
        if len(blurb) > _DESC_CHARS:
            blurb = blurb[:_DESC_CHARS].rsplit(" ", 1)[0] + "…"
        lines.append(f"  • {name} (match {score:.2f}) — {blurb}")
    return (
        "SKILL-FIRST — line 1 of your reply = one of: "
        "USING <skill> | SEARCH <query> | SKIPPING none.\n"
        "Top-few PREVIEW for this request (NOT the full ~500-skill shelf):\n"
        + "\n".join(lines) + "\n"
        "None fit? That is not a skip — SEARCH the full index (search_skills) before any "
        "SKIPPING; show the query. Closest fit, adapted, is the standard; perfect is not the bar.\n"
        "Terse words, full work — not the cheap stop. [full standing order: session start]"
    )


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

        shown = [(n, d, s) for (n, d, s) in cands if s >= ITEM_FLOOR] or cands[:1]
        _inject(_ranked_mandate(shown))
        _append_offer(sid, "offer",
                      [[n, round(s, 4)] for (n, _d, s) in shown], None, prompt)
    except Exception:
        return 0  # fail-silent, never block
    return 0


if __name__ == "__main__":
    sys.exit(main())
