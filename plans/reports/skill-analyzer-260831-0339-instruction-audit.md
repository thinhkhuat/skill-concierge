# Skill Analysis: skills

## Overview
**Grade:** B (85/100)  |  **Size:** 100 lines  |  **Sub-skills:** 366

> Session Handoff

Produce a repeatable end-of-session summary so the user can /clear and start a fresh agent without losing continuity. The next agent should be able to pick up by reading this summary alone. This is a context-handoff artifact, not a status report.

## What It Does
Session Handoff

Produce a repeatable end-of-session summary so the user can /clear and start a fresh agent without losing continuity. The next agent should be able to pick up by reading this summary alone. This is a context-handoff artifact, not a status report.

**Activates on:** `
- Dev servers / ports: <url + port> — or `, `
- Open worktrees / branches: <paths> — or `, `+%Y-%m-%d-%H%M`, `<home>/.handoff`, `Decisions locked + what shipped`, `Key files`, `Memory files touched`, `Pick up here`

## How to Use

1. Pull state from these sources (in order):: Plan files referenced this session (check `./plans/` under the active project root if a plan was mentioned — see Environment).
1. Do NOT audit the filesystem.: This is synthesis of what happened in THIS session. No `git log`, no broad `Glob` sweeps. If you didn't touch it this session, it doesn't belong here.
1. Save to disk only. Do NOT echo the full handoff content to inline chat.: Write the handoff to the work's proper home — decided per "Where to save" below, **NOT defaulted to the CWD** — as `<home>/.handoff/handoff-YYYY-MM-DD-HHMM-<slug>.md`; create `.handoff/` if it does not exist. After writing, state the saved absolute path on one line in chat. Do not update agentmemory from this skill — the `.handoff/` file is the persisted artifact.
1. CWD is never the default.: The working directory is where the terminal launched, not what the session worked on. It wins ONLY if it is also where the touched files live (rule 1). A CWD the session never wrote into is a coincidence — ignore it.
1. One project / area.: All touched files cluster under a single project (one git root, or one self-contained top-level dir) → that project's `.handoff/`. The common case.
1. Established home for this KIND of work.: If work of this kind already has a conventional handoff home, follow it even when the touched files sit elsewhere — **discover** it from what is already on disk (look for an existing sibling `.handoff/` that the same kind of work was handed off to before) and reuse that, rather than inventing a new spot or assuming a fixed kind→directory mapping. Convention beats cleverness; the next session looks where the last one looked.
1. Several areas under a common parent (monorepo / workbench).: Work spans multiple areas that share a natural parent and none dominates → the **most specific common parent's** `.handoff/` (the monorepo root, or the dev-area that contains them all), slug naming each area. Not the filesystem root — the tightest parent that still holds all the work.
1. Truly cross-project, no shared home.: Unrelated projects with no sensible common parent → one copy in the most central project's `.handoff/`, and name the other projects + their absolute paths in the body so a future session in either finds the thread. Never scatter copies.
1. Always save the file.: Write the handoff to the home decided per "Where to save" (`<home>/.handoff/handoff-YYYY-MM-DD-HHMM-<slug>.md`; create `.handoff/` if missing) — decided from the work, never defaulted to the CWD. Do NOT echo the content to inline chat — report only the saved path. Never update agentmemory from this skill — the `.handoff/` file is the only persisted artifact.
1. Never invent state.: If a section has nothing to report, write "none" — do not omit the section. Structure stability is the whole point.
1. Absolute paths always.: The next agent may have a different working directory.
1. If a plan file drove the session, name it first: in "Key files" so the next agent reads it before anything else.
1. No emojis, no hype, no "great job" summaries.: Terse and concrete — paths, commands, shell IDs, decisions. Match the tone of a seasoned engineer handing off at end-of-shift.
1. Background process IDs are critical.: If you started any `run_in_background` shells, their IDs must appear in "Running state" with the kill command — the next agent cannot find them otherwise.
1. "Decisions locked + what shipped": must list EVERY major decision and deliverable across ALL sessions, organized by phase or module — not just this session's contributions.
1. "Key files": must list the COMPLETE module/file set for the project — every file a fresh agent would need to read to understand the codebase, not just the ones touched today.
1. Self-check before finalizing:: Would a fresh agent who reads only this handoff understand the full project scope, or would they be missing entire phases/modules? If the latter, expand.

**Documentation:** `README.md` (99 lines)

## Integrations
**Invokes:** `/clear`, `/directory`, `/one`, `/proactively`, `/slug`, `/that`, `/the`

## Pairs Well With
- `/clear` — complementary workflow
- `/directory` — complementary workflow
- `/one` — complementary workflow
- `/proactively` — complementary workflow
- `/slug` — complementary workflow
- `/that` — complementary workflow
- `/the` — complementary workflow

## Quality Issues
- WARN: Description too long (508 chars, max 200)
- WARN: No security policy

---
*Analyzed 2026-08-31 03:43 from `/Users/thinhkhuat/.claude/skills`*