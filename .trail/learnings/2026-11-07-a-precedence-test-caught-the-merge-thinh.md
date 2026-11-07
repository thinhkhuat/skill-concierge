---
title: A precedence test caught the merge order being backwards in the fix it covered
author: Thinh
date: 2026-11-07
branch: main
id: l-69038ddb
scope: repo
status: active
src: agent
touches:
  - scripts/engine_env.py
  - vendor/skill-search/tests/test_engine_env_local.py
---

## Decided
A test I wrote to pin precedence caught a wrong precedence order in the very fix
it was covering, so the fix shipped with the opposite order from the one first
written.

`scripts/engine_env.py` merges three sources into the engine's environment. The
first version merged the shipped descriptor (`.mcp.json`) and then the
machine-local `~/.claude/skill-concierge/engine-env.json`, so the descriptor won
any key both carried. That is backwards: `.mcp.json` is a SHIPPED DEFAULT that must
be identical on every install, while the machine file is deployment truth. A
reindex would have used the plugin's default embedder over the operator's
configured one — the same class of silent wrong-embedder bug the change exists to
fix.

Correct order, most authoritative first: the process environment, then the
machine-local file, then `.mcp.json`.

## Tried and ruled out
- **Merging descriptor-first and relying on "setdefault" semantics.** That is
  exactly what the original code did and why the local file had no effect until
  the order was flipped.
- **Letting a malformed machine file raise, so a bad config is loud.** Rejected:
  this code runs inside a SessionStart hook, where raising means the hook breaks.
  It degrades to "no overrides" instead, and a test pins that for missing,
  non-JSON and non-dict inputs.
- **Accepting any key from the machine file.** Rejected: only keys in
  `ENGINE_ENV_KEYS`, and never an empty string, because an empty flag reads as ON.

## Watch out
- **When merging config layers, decide precedence as a rule before writing code.**
  The failure is silent — both orders produce a working system that resolves a
  different embedder.
- **Write the precedence test even when the merge looks obvious.** It cost one
  assertion and caught the bug that four other passing tests did not.
- **A fix in the working tree does not reach a hook.** Hooks import from the
  installed plugin cache, so source-level verification proves nothing until the
  plugin is reinstalled.

In the code:
- `scripts/engine_env.py` — `engine_env()`, the `for source in (...)` merge loop
- `scripts/engine_env.py` — `local_engine_env()`, `LOCAL_ENV_PATH`,
  `SKILL_CONCIERGE_ENGINE_ENV` (test seam)
- machine file: `~/.claude/skill-concierge/engine-env.json`, chmod 600
- `vendor/skill-search/tests/test_engine_env_local.py` — the precedence test that
  failed on the first order
