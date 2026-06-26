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
timeout (default 90ms — see EMBED_TIMEOUT_S for why it's tuned below the plan's
nominal ~120ms). On ANY of (a) embed unreachable, (b) Qdrant unreachable, (c)
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
# HARD embed cap. Plan nominal was ~120ms, but measured python3 cold-start +
# imports is ~50ms, so a 120ms cap pushes the slow-shim fallback path to ~180ms
# — breaching the co-equal ≲150ms total-budget criterion. 90ms keeps the slow
# path at ~140ms (measured) while leaving 3.75x headroom over the warm p95 of
# 24ms, so real candidates always clear it. Raise via env if cold-start drops.
EMBED_TIMEOUT_S = float(os.environ.get("ENFORCER_EMBED_TIMEOUT", "0.09"))
QDRANT_TIMEOUT_S = float(os.environ.get("ENFORCER_QDRANT_TIMEOUT", "0.1"))
TOP_K = int(os.environ.get("ENFORCER_TOP_K", "5"))
GETAWAY_FLOOR = float(os.environ.get("ENFORCER_GETAWAY_FLOOR", "0.20"))  # top<this → silent
ITEM_FLOOR = float(os.environ.get("ENFORCER_ITEM_FLOOR", "0.18"))       # per-candidate cutoff
MAX_SHORT_WORDS = 2   # ≤ this many words → trivial getaway, skip embed entirely
_DESC_CHARS = 96

LOG_DIR = Path(os.environ.get(
    "SKILL_CONCIERGE_LOG", Path.home() / ".claude" / "skill-telemetry" / "logs"))
LEDGER = LOG_DIR / "skill-invocation-ledger.log"

# Generic standing mandate — injected with the candidates, and alone on fallback.
MANDATE = (
    "SKILL-FIRST (standing mandate). Before acting on this request: scan your "
    "available skill catalogue. If ANY available skill genuinely fits this task, "
    "you MUST invoke it — skills encode a better, structured approach and "
    "consistently raise output quality over improvising. This is not optional for "
    "substantive work. The ONLY getaway is a genuinely trivial ask (a quick fact, "
    "a yes/no, a one-line edit, a pure conversational reply, or work the user "
    "scoped to \"no skill\"). When in doubt, invoke. Prefer the most specific "
    "skill; chain when the task spans domains. Announce the skill you're using in "
    "one line, then proceed."
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
        "SKILL-FIRST (standing mandate). For THIS request, your top-ranked "
        "installed skills (semantic match against the skill index):\n"
        + "\n".join(lines) + "\n"
        "You MUST invoke the best-fitting one before improvising — skills encode a "
        "better, structured approach and consistently raise quality. Chain them if "
        "the task spans domains. Skip ONLY if this is genuinely trivial. Announce "
        "the skill in one line, then proceed."
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

        # Embed (HARD ~90ms timeout, EMBED_TIMEOUT_S) → mandate-only on down/slow.
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
