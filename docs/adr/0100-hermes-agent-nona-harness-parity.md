# 0100 — Hermes Agent as the ninth harness (nona-harness parity)

- Status: accepted
- Date: 2026-11-08
- Deciders: Thinh
- Supersedes: none (extends ADR-0033/0038/0039/0042/0050/0051/0085 — the per-harness adapter series)

## Context

skill-concierge runs on eight harnesses (Claude Code, Codex, Command Code, OMP, ZCode, DSH, Cline,
OpenCode). Hermes Agent (Nous Research, v0.23.0 on this machine) is the harness Thinh actually
operates day to day, and it was the only one with **no** skill governance: no SKILL-FIRST order, no
per-turn offer, no ledger rows, no blocklist enforcement, and its own skills (`~/.hermes/skills`,
83 of them here) were invisible to retrieval.

Hermes offers four extension systems. Only one covers every gate:

| System | Registered via | Where it runs | Verdict |
| --- | --- | --- | --- |
| Gateway hooks | `~/.hermes/hooks/HOOK.yaml` + `handler.py` | gateway only | CLI/desktop modes get nothing |
| **Plugin hooks** | `ctx.register_hook()` in a user plugin | **CLI + gateway** | **the vehicle** |
| Shell hooks | `hooks:` block in `config.yaml` | CLI + gateway + desktop | no return channel for a block verdict, and a shell parse of every payload |
| Outbound webhooks | `hooks.outbound:` | CLI + gateway | push-only observability |

A **user plugin** (`~/.hermes/plugins/<name>/` with `plugin.yaml` + `__init__.py` exposing
`register(ctx)`) is therefore the only surface that carries all four Claude Code gates. Its hook set
is documented in `website/docs/user-guide/features/hooks.md` and enumerated in
`hermes_cli/plugins.py:109-204` (`VALID_HOOKS`); every payload used below is the documented one.

## Decision

Hermes Agent becomes the ninth supported harness, at Claude Code parity, through
`adapters/hermes/` — a Hermes user plugin plus an installer, with the shared hook scripts unchanged.

### 1. Hook mapping (the parity contract)

| Claude Code | Hermes | Script |
| --- | --- | --- |
| `SessionStart` → doctrine | `pre_llm_call` when `is_first_turn` | `doctrine.py` |
| `SessionStart` self-heal | `on_session_start` | `auto_reindex/overrides/flywheel/promote.py`, detached |
| `UserPromptSubmit` → mandate | `pre_llm_call` every turn | `enforcer.py` |
| `UserPromptSubmit` → ledger | `pre_llm_call` every turn | `ledger.py` |
| `PreToolUse(Skill)` → deny | `pre_tool_call` on `skill_view` | `skill_guard.py` |
| `PostToolUse` → ledger | `post_tool_call` | `ledger.py` |
| `PostToolUse` → exclusion echo | `transform_tool_result` | `skill_exclusions.py` |

Two mappings are not one-to-one and are the load-bearing part of this ADR:

- **`pre_llm_call` returns context, not a transcript append.** A string return is appended to the
  current turn's user message — Claude Code's `additionalContext` under another name, and cache-safe
  (the system prompt is never touched; Hermes's own invariant is that changing it mid-conversation
  breaks prompt caching).
- **`post_tool_call` is an observer and its return is discarded**, so it cannot carry the exclusion
  echo. `transform_tool_result` runs *after* it and may replace the model-bound result, which is the
  same ordering Claude Code gives PostToolUse context. The echo is appended to the body, never
  substituted for it.

`pre_tool_call` is the one Hermes hook that fails **closed** on a raise or a timeout
(`hermes_cli/plugins.py` dispatch, hooks.md "fails closed"), which is why the guard's subprocess is
bounded at 2 s and every exception returns "no directive": a broken adapter must degrade to "no
governance", never to "every skill load blocked".

### 2. Skill discovery: two new roots, one enable filter

Hermes resolves skills through `agent/skill_utils.py::get_skill_search_roots`: trusted project dirs
(`<project>/.hermes/skills`, `<project>/.agents/skills`), the profile shelf (`$HERMES_HOME/skills`),
`skills.create_dir` and `skills.external_dirs`. The `.agents` twin is already the cross-harness
convention root (ADR-0042); the two Hermes-only sources are:

| Scope | Root | Why it is new |
| --- | --- | --- |
| `hermes-personal` | `$HERMES_HOME/skills` | its own tree — **not** a symlink to `~/.claude/skills` on this machine |
| `hermes-plugin` | `$HERMES_HOME/plugins/<plugin>/skills/<name>/SKILL.md` | `ctx.register_skill` serves these as `<plugin>:<name>` without copying them into the shelf |

Hermes's shelf groups skills into **category directories** (`<category>/<skill>/SKILL.md`, exactly
the shape that made `_nested_glob` necessary for plugin caches), so those two roots get the
two-depth pass; every other harness shelf stays flat.

Hermes loads only plugins named in `config.yaml`'s `plugins.enabled`, so `_hermes_plugin_paths()`
reads that list with a tolerant stdlib scanner (there is no YAML dependency in the engine) and
indexes a disabled plugin's skills no more than `SKILL_PLUGIN_FILTER` indexes a disabled Claude
plugin's. An unreadable block means **no filter** — the fail-open direction, so a config shape the
scanner misses costs a few stale entries instead of an invisible shelf.

`SKILL_HERMES_ROOTS=0` is the one-var revert: both roots and both scopes disappear, and a reindex
prunes the `hermes-*` points, byte-identical to the pre-Hermes engine.

### 3. Cross-harness isolation

`_hermes_shares_personal_shelf()` asks whether `$HERMES_HOME/skills` resolves to
`~/.claude/skills`; on this machine it does not (measured: `readlink` on it is empty while
`~/.hermes/skills/claude-code-skills` is the symlink), so `personal` is **foreign** to Hermes and a
`personal` row survives only through `_invocable_twin`, which reads Hermes's own roots. Hermes has
no documented compatibility read of Claude's shelf (unlike OpenCode), so `~/.claude/skills` is
deliberately not in its twin set.

`plugin` (Claude's plugin cache) is foreign too: Hermes reads no cache. `hermes-personal` and
`hermes-plugin` are foreign to every other harness, pinned by
`tests/test_foreign_scope_completeness.py`.

### 4. MCP: a registered server is not a visible tool

Hermes namespaces MCP tools `mcp_<server>_<tool>` (hyphens folded to `_`), so the server named
`skill-search` exposes `mcp_skill_search_search_skills` / `mcp_skill_search_get_skill`; the doctrine
rewrite names that tool and drops the slash form (skill-concierge registers no Hermes skill, so
`/skill-concierge:skill-search` names nothing).

**The defect this ADR records:** registering the server in `mcp_servers` is not enough on a profile
that enumerates a surface's tools. Measured live 2026-11-08: `hermes mcp test skill-search` connected
and discovered 5 tools, while a real `hermes chat` turn reported "`mcp_skill_search_search_skills`
… is not available" and flailed for 44 s. The tools stayed invisible until `mcp-skill-search` joined
`platform_toolsets.cli`. The installer therefore extends every `platform_toolsets` surface that
already carries an `mcp-<server>` entry (a surface whose owner never opted into MCP there is left
alone), and doctor fails the row when no surface carries it.

### 5. Installation

Hermes has no marketplace install for a local checkout: `adapters/hermes/install.sh` symlinks
`$HERMES_HOME/plugins/skill-concierge` at `adapters/hermes/plugin` (RULES [52]: dev → global by
symlink, never `cp`; a previous real copy is archived under `~/_ARCHIVE/`, never deleted), runs
`hermes plugins enable skill-concierge` (idempotent, hot-reloads the hooks into a running gateway),
and writes the two config values through **`hermes config set`** rather than editing `config.yaml` —
Hermes's own invariant is that a stray indent breaks the live gateway. `config set` re-serializes the
file, so each write is skipped when the value already matches (verified lossless on this machine:
71 top-level keys before and after, `moa.presets` and `plugins.enabled` intact).

## Consequences

- Hermes turns produce the same ledger rows as every other harness (`turn`, `offer`, `auto`,
  `search`, all stamped `"harness": "hermes"`), so `scripts/analyze.py` windows it like any other
  epoch. **New epoch:** the first Hermes row is the epoch start for Hermes metrics; no earlier
  Hermes figure exists to pool with.
- `scripts/smoke.py` gains a `hermes` row (`hermes chat -q`), and it is the release proof like every
  other harness (ADR-0090).
- `adapters/install-all.sh` picks the installer up by glob; the release order is unchanged.
- Accepted caveats, recorded rather than hidden:
  1. **Doctrine cannot use `register_system_prompt_section`.** That seam is the Hermes-native home
     for standing orders (cache-safe, frozen per session) but caps a plugin at 4,000 characters and
     the doctrine body is 6,485 — so it rides `pre_llm_call` on the first turn, once per session,
     tracked per session id in the plugin process.
  2. **`apply-overrides.py` has no Hermes target.** The keep-on allowlist exists to free Claude
     Code's skill-description budget; Hermes has no such mechanism, so there is nothing to write.
     `auto_overrides.py` still runs and correctly reports no drift for Hermes.
  3. **The plugin-enable scanner is a tolerant reader, not a YAML parser.** It reads the exact block
     shape `hermes config set` writes. A future Hermes re-serializes into flow style and the filter
     silently disables itself (indexing a disabled plugin's skills) rather than dropping the shelf.
  4. **Deferred tools.** Hermes defers MCP tools behind `tool_search` on some surfaces; the smoke
     prompt names the tool outright (`search_skills`) so it is reachable either way.
  5. **Hermes is ADVISORY in the live smoke** (`smoke.DEFAULT_ADVISORY`, Thinh 2026-11-08). `hermes`
     is a client of the running gateway daemon: the turn executes there, and the gateway's
     environment is fixed at launch, so the plugin's hook subprocesses never inherit the run's
     `SKILL_CONCIERGE_LOG` and every row lands in the live ledger instead of the run's own folder.
     The enforcement is proven live (a real turn wrote `turn`, `offer` with band `offer` and the
     Jev whole-shelf ranking n=504, `auto` and `search`, all stamped `harness: hermes`); what does
     not transfer is the per-run ledger isolation the check is built on. It stops being advisory
     when the check can drive a dedicated gateway profile.

## Alternatives rejected

- **A `~/.hermes/hooks/` gateway hook pair.** Gateway-only: the CLI, the desktop app and cron would
  stay ungoverned, which is a partial harness rather than a supported one.
- **A shell-hook wiring in `config.yaml`.** Shell hooks have no directive channel for a block
  verdict that survives into the model's tool result, and parsing every payload through a shell
  process per turn is more surface, not less.
- **Copying the plugin into `~/.hermes/plugins/`.** A copy drifts from the checkout and is deleted
  by nothing, so the two silently disagree; the symlink keeps one source of truth.
- **Indexing `~/.claude/skills` under a `hermes-` scope because Hermes can read `~/.agents/skills`.**
  Hermes does not read Claude's shelf; the `.agents` convention root is already indexed and the twin
  test settles per-row survival without minting a duplicate scope.
