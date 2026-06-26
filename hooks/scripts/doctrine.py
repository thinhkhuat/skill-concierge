#!/usr/bin/env python3
"""
skill-concierge — SKILL-FIRST doctrine injector (SessionStart hook).

The caveman-proven half of the split the enforcer was missing. caveman governs by
injecting its FULL ruleset at SessionStart (not a 2-sentence summary — the summary
drifts away mid-conversation, especially after compaction) and re-asserting a cheap
trigger per turn (the enforcer's job). This hook is the SessionStart half: it reads
the rich standing order from hooks/doctrine/skill-first.md AT RUNTIME and emits it as
session context, so editing the doctrine propagates with no code change.

There is NO detection here and NO post-turn gate anywhere in skill-concierge: the
doctrine shapes generation by being present in the model's context as it writes, the
way caveman shapes terseness. Prevention, not policing.

Design contract (mirrors the sibling enforcer/ledger hooks):
  • FAIL-SILENT — any error exits 0; a hook must never break or block session start.
  • ADDITIVE-ONLY — only ever emits hookSpecificOutput.additionalContext.
  • STDLIB-ONLY — no heavy imports, no network, no I/O beyond the one doctrine read.

Per ~/.claude docs (working-with-claude-code/hooks.md): SessionStart stdout is added
to the context; exit 0. We use the structured hookSpecificOutput form for clarity.
"""
import sys
import json
from pathlib import Path

# Doctrine lives two levels up from this script: hooks/scripts/doctrine.py →
# hooks/doctrine/skill-first.md. Resolved from __file__ so it is install-location
# independent (the plugin cache path differs from the dev repo path).
DOCTRINE_PATH = Path(__file__).resolve().parent.parent / "doctrine" / "skill-first.md"

# Only the body between these markers is injected — the file's own header/usage note
# is for human maintainers, not the model's context.
_START = "<!-- DOCTRINE-START -->"
_END = "<!-- DOCTRINE-END -->"


def _body(text: str) -> str:
    """Return the doctrine body between the markers, or the whole file if markers
    are absent (so a malformed edit degrades to over-injecting, never to silence)."""
    i = text.find(_START)
    j = text.find(_END)
    if i != -1 and j != -1 and j > i:
        return text[i + len(_START):j].strip()
    return text.strip()


def main() -> int:
    try:
        text = DOCTRINE_PATH.read_text(encoding="utf-8")
        doctrine = _body(text)
        if not doctrine:
            return 0
        sys.stdout.write(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": doctrine,
            }
        }))
    except Exception:
        return 0  # fail-silent — never block session start
    return 0


if __name__ == "__main__":
    sys.exit(main())
