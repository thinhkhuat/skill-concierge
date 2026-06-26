#!/usr/bin/env python3
"""
skill-concierge — skill-invocation ledger (append-only telemetry).

Registered for two events (see ../hooks.json):
  • UserPromptSubmit → logs a `turn` per substantive prompt, or `manual` when the
    user typed a `/skill` (captured here because the slash path never reaches
    PostToolUse as a tool call).
  • PostToolUse (matcher Skill|mcp__skill-search__search_skills) → logs `auto`
    (Claude invoked a skill) or `search` (Claude called the semantic retriever).

Design contract (mirrors the sibling enforcement hooks):
  • FAIL-SILENT — any error exits 0; telemetry must never break or block a turn.
  • ADDITIVE-ONLY — never writes hook-decision output; just appends to the ledger.
  • COMPOUNDING — one append-only JSONL `.log`; no rotation/cap/delete here
    (lifecycle is logman's job downstream; run it with RETENTION_DAYS=0).

The PostToolUse `tool_input` schema is tool-dependent and the Skill tool's field
name is NOT documented, so we DO NOT assume one: we record the input KEYS (to learn
the real field from live data) plus a best-effort name from likely candidates —
without logging arbitrary input values.
"""
import sys
import os
import json
import time
from pathlib import Path

LOG_DIR = Path(os.environ.get(
    "SKILL_CONCIERGE_LOG", Path.home() / ".claude" / "skill-telemetry" / "logs"))
LEDGER = LOG_DIR / "skill-invocation-ledger.log"
SEARCH_TOOL = "mcp__skill-search__search_skills"
_NAME_KEYS = ("skill", "command", "name", "skill_name", "subagent_type")


def _append(ev: dict) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with LEDGER.open("a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    except Exception:
        pass  # fail-silent: a telemetry write must never surface to the turn


def main() -> int:
    try:
        raw = sys.stdin.read()
        d = json.loads(raw) if raw.strip() else {}
        if not isinstance(d, dict):
            return 0
        evt = d.get("hook_event_name", "")
        sid = d.get("session_id", "")
        t = round(time.time(), 3)

        if evt == "UserPromptSubmit":
            prompt = d.get("prompt") or ""
            s = prompt.strip()
            if not s:
                return 0  # empty prompt is not a turn — don't log noise
            if s.startswith("/"):
                # user-typed slash = manual /skill (or a built-in command)
                name = s[1:].split()[0] if len(s) > 1 else ""
                _append({"t": t, "sid": sid, "ev": "manual", "name": name})
            else:
                # turn boundary — lets the analyzer segment uptake per prompt.
                # Log the STRIPPED prompt so analyze.py can join this `turn` to
                # the enforcer's `offer` event by (sid, q) — the enforcer logs q
                # stripped, so an unstripped q here would break the join for any
                # whitespace-bearing prompt and silently undercount hit@k.
                _append({"t": t, "sid": sid, "ev": "turn", "q": s[:120]})

        elif evt == "PostToolUse":
            tool = d.get("tool_name", "")
            if tool == "Skill":
                ti = d.get("tool_input", {})
                name, keys = "", []
                if isinstance(ti, dict):
                    keys = list(ti.keys())
                    for k in _NAME_KEYS:
                        if isinstance(ti.get(k), str):
                            name = ti[k]
                            break
                _append({"t": t, "sid": sid, "ev": "auto",
                         "name": name, "input_keys": keys})
            elif tool == SEARCH_TOOL:
                _append({"t": t, "sid": sid, "ev": "search"})
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
