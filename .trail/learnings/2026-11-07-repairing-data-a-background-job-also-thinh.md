---
title: "Repairing data a background job also writes: fix and install the writer before the repair, not after"
author: Thinh
date: 2026-11-07
branch: main
id: l-89a54f45
scope: repo
status: active
src: agent
touches:
  - hooks/scripts/selfheal.py
---

## Decided
When repairing data that a background job also writes, stop the writer first — and
"stopped" means the INSTALLED artifact carries the fix, not the working tree.

Sequence that works, in order: commit -> push -> reinstall the plugin -> prove the
installed copy resolves correctly -> only then repair the data.

Sequence that failed here: edit the source, run a 19,881-point repair immediately,
then watch the wrong-embedder count rise from 19,873 to 28,800. The SessionStart
auto-reindex imports `engine_env` from the plugin cache, so it kept running the old
code and overwrote the repair as it landed. Each verification I ran was honest and
each was meaningless, because the thing that writes the data had not changed.

Proof that the fix reached the writer, run before any repair:
`env -i HOME=$HOME PATH=/usr/bin:/bin python3 <plugin-cache>/scripts/engine_env.py --exec python3 -c "import os; print(os.environ.get('SKILL_OLLAMA_URL'))"`
— it must print the configured endpoint, not the localhost default. Only then repair.

## Tried and ruled out
- **Repairing first and verifying after.** The repair looks successful in its own
  receipt (`embedded: 19881`) while being undone concurrently. A receipt proves what
  a process wrote, never what a collection ends up containing.
- **Trusting `doctor`'s green rows as proof the running code is fixed.** Doctor
  reports what is on disk; five live MCP processes still held the old build in memory
  and it said so in a row I was reading past.
- **Blaming the repair script.** Its output was correct. The defect was sequencing.

## Watch out
- **A data repair against a concurrently-writing service needs the writer changed
  in the SAME artifact the writer executes.** Source-level verification proves
  nothing about a long-lived process.
- **A distribution that gets worse after a fix is the signature of two writers, not a
  failed fix.** Count the parts before re-running the repair.
- **Long-running processes pin old code.** Doctor's "Running engine" row names the
  pids; a restart is required before that process can honour any fix.

In the code:
- `hooks/scripts/selfheal.py` — `mcp_env()`, the hook's env source (`os.environ` +
  `.mcp.json` as it was before this session's fix)
- installed engine path: `~/.claude/plugins/cache/skill-concierge/skill-concierge/<version>/`
- observed: 19,873 wrong -> 28,800 wrong after one repair; 29,180 re-embedded and a
  single token across 46,564 points after the writer was fixed
