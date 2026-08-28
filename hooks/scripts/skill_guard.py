#!/usr/bin/env python3
"""
skill_guard.py — PreToolUse(Skill) gate: deny the invocation of any skill on the
user-ordered blocklist (ADR-0046).

WHY THIS EXISTS
    The concierge governs OFFERS (enforcer) and RETRIEVAL (search_skills/get_skill),
    but the agent can still reach for a skill it remembers or that the harness lists —
    including command-files surfaced as skills (~/.claude/commands/*.md), which ADR-0001
    deliberately keeps OUT of the index and therefore out of every retrieval-side filter.
    The only layer that catches every origin deterministically is the invocation itself:
    this guard denies the Skill tool call before it executes.

    It is the repo's SECOND deliberate denying gate (the first is the openwiki commit
    guard). A user-ordered disable is a gate, not telemetry — honoring it "usually" is
    not honoring it.

WHAT IT DOES
    Fires on PreToolUse for the Skill tool. Loads the blocklist
    (~/.claude/skill-concierge/blocklist.json, {"blocked": [...]}) and denies the call
    when the invoked name matches:

      • EXACT match — bare or qualified entry equals the invoked name.
      • BARE entry blocks every qualified twin: blocking `keep-on` also blocks
        `skill-concierge:keep-on` and any other `origin:keep-on`. A qualified entry
        (`skill-concierge:keep-on`) blocks only itself.

    The deny reason names the entry and the unblock command.

ESCAPE HATCH
    SKILL_BLOCKLIST=0 -> the whole feature is off everywhere (this guard passes,
    the enforcer stops filtering, the engine stops filtering). One-var revert.
    SKILL_CONCIERGE_BLOCKLIST -> exact blocklist file (tests / advanced override).

FAIL-OPEN
    Unreadable stdin, missing/corrupt blocklist file, or any internal error -> allow.
    A broken guard must never wedge skill invocation; the blocklist file is tiny,
    user-owned, and doctor checks it.
"""
import json
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

SKILL_TOOL_INPUT_KEY = "skill"   # the Skill tool's name parameter


def _blocklist_entries():
    path = Path(os.environ.get(
        "SKILL_CONCIERGE_BLOCKLIST",
        Path.home() / ".claude" / "skill-concierge" / "blocklist.json"))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        lst = data.get("blocked", []) if isinstance(data, dict) else []
        if not isinstance(lst, list):
            return frozenset()  # wrong-typed value = total fail-open, not char-iterated noise
        return frozenset(n for n in lst if isinstance(n, str))
    except (OSError, UnicodeError, ValueError, AttributeError, TypeError):
        return frozenset()  # fail-open: missing/corrupt file = empty list = allow all


def _matches(entry: str, name: str) -> bool:
    """Exact, or a BARE entry catching every qualified twin (`origin:name`)."""
    if entry == name:
        return True
    return ":" not in entry and ":" in name and name.rsplit(":", 1)[1] == entry


def _blocked_entry(name: str, entries: frozenset):
    return next((e for e in entries if _matches(e, name)), None)


def _emit_deny(reason):
    """PreToolUse decision control: hookSpecificOutput.permissionDecision (hooks spec)."""
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))


def main():
    if os.environ.get("SKILL_BLOCKLIST") == "0":
        return 0

    try:
        payload = json.load(sys.stdin)
    except (OSError, ValueError):
        return 0  # unreadable stdin or invalid JSON: not our business, allow

    if payload.get("tool_name") != "Skill":
        return 0

    name = str((payload.get("tool_input") or {}).get(SKILL_TOOL_INPUT_KEY) or "").strip().lstrip("/")
    if not name:
        return 0

    entry = _blocked_entry(name, _blocklist_entries())
    if entry is None:
        return 0

    _emit_deny(
        f"Skill '{name}' is disabled by the skill-concierge blocklist"
        f" (entry: '{entry}').\n\n"
        "The user ordered this skill off — do not retry it, and do not route around it.\n"
        "If that is wrong, the user re-enables it with:\n"
        "  python3 scripts/blocklist.py remove " + entry + "\n"
        "(or the skill-concierge:blocklist skill)\n\n"
        "Kill-switch for the whole feature: SKILL_BLOCKLIST=0."
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        logger.exception("skill_guard: internal error — failing open")
        sys.exit(0)  # fail-open: a broken guard must never wedge skill invocation
