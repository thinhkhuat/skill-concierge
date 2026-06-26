# Session Handoff — skill-concierge SKILL-FIRST gate shipped + EFFORT extracted to standalone effort-gate plugin

## Where it started
Resumed from the enforcement-redesign handoff (`.handoff/handoff-2026-06-27-0328-skill-concierge-enforcement-gate-redesign-mental-model.md`), which *designed but did not build* a caveman-anchored GATE to replace the soft skill-first nudge. This session **built and shipped** it — then course-corrected hard: the user explicitly rejected the doc's P2 Stop/PostToolUse detection gate ("anti-caveman — it polices spent tokens"), so enforcement is **in-generation only**, exactly like caveman. The session then integrated an EFFORT companion gate, and finally **extracted EFFORT into its own standalone universal plugin** (`effort-gate`). Along the way, diagnosed a `.git`⇄`git/` toggle confusion and propagated the convention to memory + rules.

## Decisions locked + what shipped
- **SKILL-FIRST gate — skill-concierge v0.3.0** (caveman-mirrored split, NO detection): SessionStart hook `doctrine.py` injects the full doctrine read at runtime from `hooks/doctrine/skill-first.md`; per-turn `enforcer.py` message reworded from soft persuasion → forced line-1 token gate (`USING | SEARCH | SKIPPING`). The forced token is a *pre-commitment* lever (no checker) — its force is in-generation, the way caveman's pattern forces terseness. Commit `b5207f3`, pushed.
- **P2 stop-gate rejected by design** — the mental-model doc (`docs/skill-first-enforcement-mental-model.md`) was synced to record the rejection (§4/§8/§9/§11, TL;DR). Next agent: do NOT rebuild a Stop/PostToolUse detection layer.
- **EFFORT integrated into skill-concierge per-turn — v0.3.1** — shared `EFFORT_TRIGGER` added to `enforcer.py` (commit `254c7ca`). **Later removed** — see decouple below.
- **git-dir toggle convention learned + propagated** — the user renames `.git/`→`git/` (drop dot) to lift a read-only restriction so agents can write git internals; renaming back restores normal ops. Symptom: plain `git` fails `fatal: not a git repository (...): .git`. NOT a deleted repo. Propagated to: file-memory `git-dir-toggle-convention.md` (+ `MEMORY.md`), agentmemory lesson `lsn_b8b529e357c944ef`, workbench `CLAUDE.md` (artifact-detection updated + "Git-dir toggle" block).
- **effort-gate — NEW standalone plugin v0.1.0** at `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/effort-gate`, repo `github.com/thinhkhuat/effort-gate` (commit `3ae1ea5`, pushed, installed). Universal EFFORT standing-order, caveman-exact: SessionStart `activate.py` injects full doctrine from `skills/effort/SKILL.md`; per-turn `tracker.py` re-asserts + handles `/effort on|off`; `effort_config.py` = symlink-safe flag. NO detection. Doctrine encodes the user's WHY (follow the trails, work to done-and-proven, refuse slop/average-mean exits) with a **legit-stop enumeration** (done+proven / real external blocker / user-ordered) so "relentless" can't go pathological.
- **Decoupled EFFORT from skill-concierge — v0.4.0** (commit `17b5dad`, pushed): removed the EFFORT section from `skill-first.md` and `EFFORT_TRIGGER` from `enforcer.py`; annotated the mental-model doc (§4, §10.2). Division of labor: **skill-concierge governs which/whether a skill; effort-gate governs how much work.**
- **Both installed + dogfooded live** — a real fresh session fired both SessionStart doctrines; verified deployed clones (effort-gate `0.1.0`/`3ae1ea5`, skill-concierge `0.4.0`/`17b5dad`), `EFFORT_TRIGGER` count in enforcer = 0, the injection split is clean (one EFFORT source, no dup, no gap), reindex picked up the new `effort-gate:effort` skill (517→518), and it is retrievable (rank 1 for an effort query).

## Key files for next session

| File | Why |
|------|-----|
| `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/.handoff/handoff-2026-06-27-0328-skill-concierge-enforcement-gate-redesign-mental-model.md` | the prior (design) handoff this session implemented |
| `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/docs/skill-first-enforcement-mental-model.md` | canonical model — P2 rejected, EFFORT extracted; READ before touching enforcement |
| `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/hooks/doctrine/skill-first.md` | SKILL-FIRST doctrine source (SessionStart single source) |
| `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/hooks/scripts/doctrine.py` | skill-concierge SessionStart injector |
| `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/hooks/scripts/enforcer.py` | skill-concierge per-turn SKILL-FIRST trigger (EFFORT removed) |
| `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/effort-gate/skills/effort/SKILL.md` | EFFORT doctrine source (the heart of effort-gate) |
| `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/effort-gate/hooks/scripts/activate.py` | effort-gate SessionStart injector (caveman-activate analog) |
| `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/effort-gate/hooks/scripts/tracker.py` | effort-gate per-turn re-assert + `/effort` toggle |
| `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/effort-gate/hooks/scripts/effort_config.py` | shared symlink-safe flag helpers |
| `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/effort-gate/README.md` | what/why/how + layout |

- Memory touched: `/Users/thinhkhuat/.claude/projects/-Users-thinhkhuat-in-PROD-MY-WORKBENCH-skills-dev/memory/git-dir-toggle-convention.md` (+ `MEMORY.md` index); agentmemory lesson `lsn_b8b529e357c944ef`; rule edit in `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/CLAUDE.md` (Git-dir toggle block).

## Running state
- Background processes: none.
- Dev servers / ports: Docker `skill-concierge-embed-shim` → `127.0.0.1:6363` (warm embed shim); `skill-search-qdrant` → `localhost:6333`. Both up. Stop: `docker stop skill-concierge-embed-shim skill-search-qdrant`.
- Open worktrees / branches: `skill-concierge` `main` @ `17b5dad` (pushed, clean); `effort-gate` `main` @ `3ae1ea5` (pushed, clean). Both plugins installed from GitHub and reloaded. NOTE: both repos use the `.git`⇄`git/` toggle — if `git` reports "not a repository," see `lsn_b8b529e357c944ef`.

## Verification — how to confirm things still work
- `claude plugin list | grep -A2 'effort-gate@\|skill-concierge@'` → `0.1.0` enabled / `0.4.0` enabled.
- `echo '{"hook_event_name":"SessionStart","source":"startup"}' | python3 ~/.claude/plugins/marketplaces/effort-gate/hooks/scripts/activate.py` → JSON with the EFFORT doctrine.
- `echo '{"hook_event_name":"SessionStart","source":"startup"}' | python3 ~/.claude/plugins/marketplaces/skill-concierge/hooks/scripts/doctrine.py` → SKILL-FIRST only (no `EFFORT — STANDING ORDER`).
- `grep -c EFFORT_TRIGGER ~/.claude/plugins/marketplaces/skill-concierge/hooks/scripts/enforcer.py` → `0`.
- `search_skills("relentless effort work to done refuse slop")` (MCP) → `effort-gate:effort` rank 1.
- `cat ~/.claude/.effort-active` → `full` (effort-gate active; `/effort off` clears it).
- `curl -s http://127.0.0.1:6363/health` → ok/mpnet/768; `curl -s http://localhost:6333/collections/claude_skills` → ok.

## Deferred + open questions
- Deferred: effort-gate **intensity levels** (caveman lite/full/ultra) — built single-level (`full` + `off`); not requested.
- Deferred: effort-gate **statusline badge** (caveman-style `[EFFORT]`) — not built.
- Deferred: skill-concierge **stale-index hygiene** — `reindex()` is manual after any skill change; auto-trigger / doctor wiring not done.
- Open: the **EFFORT gate has no forced line-1 token** (effort is continuous, not a discrete decision; its force is "name the cut + halt, never silent"). Flagged to the user; they did not ask to add a token. Revisit only if a token is wanted.
- Open: **compliance lift is unmeasured** for both gates — the ledger is contaminated; `scripts/analyze.py` on a clean workload window is the honest measurement, still pending.

## Pick up here
Both plugins are live, decoupled, and dogfooded — the most likely next action is either a clean-window compliance measurement (`skill-concierge/scripts/analyze.py`) or building effort-gate's deferred caveman-parity polish (intensity levels / statusline) if the user wants it.
