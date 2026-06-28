---
phase: 2
title: "Doctrine decay reinjection"
status: pending
effort: ""
priority: P2
dependencies: []
effort: "1d"
---

# Phase 2: Doctrine decay re-injection (compliance side, parallel track)

## Overview
Re-assert the SKILL-FIRST doctrine when the session transcript shows it has decayed
(e.g. after a `/compact`). `doctrine.py` injects the rich standing order ONCE at
SessionStart; over a long session it falls out of context and only the cheap per-turn
trigger remains. Borrowed from `identity-reinjection.sh`. Attacks the compliance half
of the dodge — independent of Phase 1.

## Requirements
- Functional: if the doctrine marker is absent from recent assistant context, re-inject
  the doctrine on the next UserPromptSubmit; do nothing if it is still present.
- Non-functional: additive-only, fail-silent, never blocks; cheap on large transcripts.

## Architecture
New `hooks/scripts/redoctrine.py` (UserPromptSubmit), or fold into `doctrine.py`:
read `transcript_path`, scan the last N assistant turns for the doctrine MARKER; if
absent → inject the doctrine via `additionalContext`. Marker = a stable sentinel
already present in the SessionStart doctrine text.

**The known trap (from the analysis):** `identity-reinjection.sh`'s jq selector assumes
the transcript is a JSON ARRAY. Claude Code transcripts are **JSONL** (one JSON object
per line). The parser MUST read line-by-line (stream), not `json.load` the whole file.
Verify against a real `~/.claude/projects/**/<session>.jsonl` before wiring.

## Related Code Files
- Create: `hooks/scripts/redoctrine.py`
- Modify: `hooks/hooks.json` (register UserPromptSubmit), `hooks/doctrine/skill-first.md` (ensure a stable marker)
- Reference: `hooks/scripts/doctrine.py` (reuse its doctrine-loading), `hooks/scripts/enforcer.py` (fail-silent/additive contract)

## Implementation Steps
1. Pick/confirm a stable doctrine MARKER string present in the SessionStart injection.
2. Write `redoctrine.py`: stream-parse the JSONL transcript, extract the last N assistant text blocks, test for the marker.
3. If absent → inject doctrine (additive); if present → exit 0 silently.
4. Test on a REAL transcript (a long/compacted session) — confirm correct JSONL parse, correct re-inject/skip decision.
5. Register the hook; verify end-to-end (fail-silent on missing/garbage transcript).

## Success Criteria
- [ ] On a transcript MISSING the marker → doctrine re-injected exactly once that turn.
- [ ] On a transcript WITH the marker → no injection.
- [ ] JSONL parse verified against a real Claude Code transcript (not the upstream array assumption).
- [ ] Fail-silent: missing/unreadable/huge transcript never errors or blocks the turn.

## Risk Assessment
- **Transcript format drift** → parse defensively, fail-silent on any shape mismatch.
- **Double-injection / nagging** → only fire when marker truly absent; consider a per-session cooldown.
- **Perf on huge transcripts** → read only the tail (last K lines), not the whole file.
- **Measuring its effect** depends on Phase 4 (clean-window) — can't prove compliance lift without it.
