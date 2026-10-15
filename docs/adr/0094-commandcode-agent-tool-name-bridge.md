# 0094 — The Command Code agent bridge (a mirror of the Claude agent corpus, tool ids translated)

- Status: accepted
- Date: 2026-10-16
- Deciders: Thinh: "my `~/.commandcode/agents/*.md` files use Claude-style tools names (Write, Edit, Bash…) that Command
  Code silently drops, so every spawned subagent here gets only glob+grep (proved: the fullstack-developer delegate was
  blocked mid-port). Fix the agent definitions, with a similar approach, as a new mod in our concierge … `~/.commandcode/agents/`
  is the symlink of the `~/.claude/agents/` … any direct edits are not allowed strictly, or making copies that would loose
  the 'sync' and destroy the portability I need." On the seam being absent, the approved shape: **bridge owns the directory** —
  replace the symlink with a real, bridge-written mirror, **frontmatter + body** rewrites, **preserve and report** any
  Command-Code-native file.
- Relates to: ADR-0038 (Command Code adapter), ADR-0092 (the package manifest), ADR-0093 (the sibling colon-name skill
  bridge — the shape reused here). Implementation: `scripts/cmd_agent_bridge.py` (builder + verify + clean),
  `hooks/scripts/auto_agent_bridge.py` (SessionStart refresh), the §4b step of `adapters/commandcode/install.sh`, and
  `tests/test_commandcode_agent_bridge.py`.

## Context

Command Code reads a subagent definition from `~/.commandcode/agents/*.md` and resolves its frontmatter `tools:` line
against its own tool ids. The corpus on this machine is written for Claude Code, whose ids differ (`Read`, `Write`,
`Edit`, `Bash`, `TodoWrite`, `Task(<agent>)`). Command Code has no translation for those names, so each one is dropped
**in silence** and the subagent launches with whatever happened to resolve.

Four facts, each read out of the shipped CLI (1.82.3) rather than assumed, shaped the design:

1. **Only `glob` and `grep` survive by luck.** `resolveSubagentTools` resolves a token by (a) an exact match against a
   display-name map derived from Command Code's own snake-case ids (`read_file` → `Read File`), or (b) a small built-in
   alias table containing exactly `bash`/`Bash → shell_command`, `read_multiple_files → read_file`, and
   `bash_output`/`task_output → shell_output`. So `Glob`/`Grep` match (Command Code's single-word ids capitalize to the
   same spelling) and `Read`/`Write`/`Edit`/`WebFetch`/`TodoWrite`/`SendMessage`/`Task(...)` do not. A delegate that must
   write files and run builds starts unable to do either.
2. **Omission is not inheritance.** Claude Code reads a missing `tools:` key as "this agent inherits the caller's tools";
   Command Code reads it as **no tools at all**. Five agents in the corpus (both validators, the vn author/editor, the
   tk validator) had no `tools:` key and were launching with an empty tool set.
3. **There is no agent-path seam.** The ModApi exposes `cmd.addSkillsPath()` for skills and nothing equivalent for
   agents; discovery is a flat top-level scan of `$HOME/.commandcode/agents` plus `<cwd>` and repo-root
   `.commandcode/agents`, with **first definition of a name winning** in order bundled → personal → project, and
   `$HOME` is the only input to the personal path. So the sibling bridge's shape (materialize a shelf, register it with a
   mod) has nothing to register: the mirror must be written where Command Code already looks, and a same-named copy in a
   project directory can never shadow the personal file it needs to replace.
4. **`~/.commandcode/agents` is a symlink to `~/.claude/agents`** — one corpus every harness reads, kept in sync by
   design. Writing through it would edit the Claude Code originals, so the builder refuses a symlinked destination
   outright.

## Decision

1. **Mirror into the scanned directory; never edit a source.** `scripts/cmd_agent_bridge.py build` writes one translated
   copy per agent into `~/.commandcode/agents` (the destination the harness reads), hashing every source into
   `_agent_bridge.json` so `verify` can prove no source changed. `clean` removes only files that manifest names, so an
   agent created inside Command Code itself is never touched.
2. **The installer owns the directory.** `adapters/commandcode/install.sh` replaces the symlink with a real directory and
   then builds the mirror — with the target path recorded, and a rollback that drops the mirror's own files, removes the
   directory and re-links if the build or the check fails. It runs last, after every config write, so a failure leaves a
   fully working unmirrored install rather than a half-wired one.
3. **Translate, and report every translation.** `tools:`/`disallowedTools:` ids map through one explicit table
   (including `MultiEdit → edit_file` and `NotebookEdit → write_file`, each with its caveat stated); an id with no
   counterpart is **dropped from the allowlist and named** — never kept (Command Code drops it anyway) and never invented.
   An omitted `tools:` key is written out as `"*"` (quoted: a bare `*` is a YAML alias, which is why Command Code patches
   that exact shape). A `model:` that is not a Command Code `/model` id — a Claude alias like `sonnet` is not one — resets
   to `inherit` with a warning, because the harness would otherwise drop it silently and change the model.
4. **The body keeps its author.** Tool ids written as unambiguous camel-case tokens (`TaskCreate` → `task_create`,
   `WebFetch` → `web_fetch`) are renamed; single-word names that are also ordinary English (`Read`, `Write`, `Edit`,
   `Bash`) are left alone, because the prompt says "Read the file" as often as it names the tool. Delegation and
   peer-messaging idioms (`Task(<agent>)`, `SendMessage`, `shutdown_request`) cannot be mechanically re-expressed —
   Command Code subagents cannot spawn subagents and have no peer-messaging tool — so the copy gets ONE explicit
   adapter note saying that work happens inline, and the author's sentences are left intact.
5. **Fail-open at session start.** `hooks/scripts/auto_agent_bridge.py` refreshes the mirror at SessionStart, throttled
   by a stamp seeded in `scripts/smoke.py`'s `SELF_HEAL_STAMPS`; it does nothing while the destination is still the
   symlink, so an uninstalled machine fills no log.

## Consequences

- Subagents now launch with the tools their author declared; the five agents that declared none launch with `"*"`, which
  is what Claude Code's omission meant.
- The mirror is derived data: edit the source in `~/.claude/agents`, never the copy, and the next session-start refresh
  (or an explicit `build`) carries the change over.
- `~/.commandcode/agents` is no longer a symlink on this machine. The shared corpus is unchanged and every other harness
  still reads it, but a Command-Code-native agent file now lives beside the mirror instead of beside the sources; the
  builder reports those files instead of managing them, and collisions are reported, never overwritten.
- The bridge is Command Code-specific by construction: the rewrite table names Command Code tool ids, and nothing else
  consumes its output. Rejected alternatives, recorded: a project-scoped copy (cannot shadow the personal definition),
  a mod (no agent seam exists), and an in-place edit (rewrites the shared corpus).
- **Supersede this ADR when Command Code ships an agent-path seam** (`addAgentsPath` or equivalent): the shelf-and-register
  shape of ADR-0093 is strictly better because it needs no symlink change, and this bridge should be rewritten onto it.
