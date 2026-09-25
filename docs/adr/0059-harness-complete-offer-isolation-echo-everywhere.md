# ADR-0059 — Harness-complete offer isolation, project isolation, the exclusion echo on every harness, and the ADR-0058 follow-ups

Status: Accepted (2026-09-25)
Relates to: ADR-0034 (cross-harness offer isolation — completed here), ADR-0036 (dynamic annex sizing), ADR-0039 (OMP parity — its tool-name shape corrected here), ADR-0042/ADR-0050/ADR-0051/ADR-0057 (ZCode/DSH/Cline/Command Code shelf rules — extended here), ADR-0052 (per-session plugin gate), ADR-0054 (the DSH/Cline foreign scopes this release finally enforces), ADR-0058 (the follow-ups closed here; two of its statements corrected).
Evidence: installed harness sources (OMP `@oh-my-pi/pi-coding-agent` src, Command Code `dist/bundled/mod-builder` reference, the Cline binary, DSH `@deepseek-ai/*` packages), live Qdrant facets and scrolls, a base-vs-work offer probe over the live index, a 15-case mutation run, and two independent plan reviews (`plans/reports/review-260925-2224-v0490-plan-{adversarial,overengineering}.md`, local).

## Context

ADR-0058 shipped with a follow-up list: the Codex/OMP foreign-scope tuples missed `zcode-*` (Codex also
`omp-*`); the Command Code annex label omitted two harnesses; the exclusion echo reached only Claude
Code and ZCode; the usage audit credited a re-ruled (retracted) `USING:`; the engine honoured
`SKILL_CLAUDE_SETTINGS` while the hook read `$HOME`; and two open questions — OMP's `read("skill://…")`
consumption hint (OQ3) and `disabled_in` outside Claude-launched servers (OQ5).

Working the list exposed the class behind the first item, in four places:

1. **Claude's tuple had the same gap** (not only Codex's and OMP's). The live index held 42
   `omp-managed` and 13 `zcode-plugin` skills that entered the Claude, Codex and OMP installed offers
   as if invocable.
2. **Project scopes were never foreign anywhere.** A project scope carries a path
   (`project:<dir>/.claude/skills`, `codex-project:…`), and the post-filter is an exact tuple match. From
   an unrelated directory the Claude offer listed skills that exist only in another project's
   `.claude/skills` (`ak-marketing-planning` 0.767, `ak-logo-design`).
3. **Under DSH and Cline the whole foreign filter was off.** `_invocable_plugin_ids()` returns `None`
   there by design (no skill-plugin registry), and `_retrieve` treated `None` as "unknown — drop
   nothing". The DSH/Cline tuples of ADR-0054 never ran.
4. **The annex label was hand-typed per harness** and disagreed with the tuples; every annex row
   repeated the whole label instead of naming where it lives.

A before/after probe from `/tmp` over six queries and all seven harnesses counted **96** offered rows
the session could not invoke on the v0.48.0 build and **0** on this one.

## Decision

### 1. One rule for which rows an offer may hold

- **Tuples completed.** Claude, Codex and OMP now list the `omp-*`/`zcode-*` scopes they cannot read.
  A new test (`tests/test_foreign_scope_completeness.py`) walks every machine-wide scope the engine
  can emit (`skills_discovery.visible_scopes()`, all harness flags on) and asserts that, for each
  harness, the scope is its own, on a short documented native-read list, or foreign — a new discovery
  root that forgets the tuples now fails a test instead of leaking. The tuples stay explicit because
  they encode shelf rules; the other-harness annex query needs a positive scope list anyway.
- **DSH and Cline read the shared shelf.** Both read `~/.agents/skills` (DSH `dsh-skill-filesystem`
  `roots()`: `user-agents` + `project-agents`; Cline: its skills-dir list and marketplace install
  target, found in the installed binary). `personal` is foreign there only when `~/.agents/skills`
  does not resolve to `~/.claude/skills` (`_agents_shares_personal_shelf()`, the ZCode rule); their
  filesystem twin rescue adds `~/.agents/skills`. The `None` registry no longer switches their filter
  off — for them the verdict is scope + filesystem twin. Turning the filter on without the shelf rule
  would have hidden all 394 indexed personal skills from DSH.
- **Project isolation** (`ENFORCER_PROJECT_ISOLATION`, default ON). A project-scoped row is dropped
  when its project root is neither the cwd nor an ancestor/descendant of it (the root is taken from
  the scope path as recorded and only then resolved for the comparison — resolving first would follow
  a symlinked `.claude/skills` to its target and misplace the project; nested layouts are kept, never
  guessed at) **and** no same-named copy exists at the same relative path in
  the session dir or any parent. The second clause is load-bearing: the index keeps ONE point per
  skill name, so a skill installed in two projects is scoped to whichever reindexed last (live case:
  `graft` in two projects, indexed under one). A same-project harness row takes the verdict of that
  harness's personal scope (OMP reads `<cwd>/.codex/skills`, Claude does not), except the
  `<project>/.agents/skills` convention root — indexed under `zcode-project` but read by ZCode, OMP,
  Codex, DSH and Cline — which is foreign only under Claude. `project:<cwd>` stays never-foreign (the
  existing rule). `=0` restores the pre-0.49.0 behaviour.
- **Each annex row names its own harness.** `_retrieve_foreign` fetches `scope` and returns
  `(name, desc, score, harness)`; the render marks each row (`[omp]`) and the header lists only the
  harnesses shown. The hand-typed `_foreign_harness_label()`/`FOREIGN_HARNESS` are deleted — nothing
  reads them — ending that drift class. The scope→harness rule is the engine's own head rule
  (`server._origin_head`), duplicated stdlib-only and pinned to it by a test. Because `main()` swallows
  exceptions, a missed unpack site would inject NO offer silently; a test drives `main()` end to end
  and asserts the offer arrives and the ledger `xh` field is written.

### 2. Settings-path parity

The hook's USER settings layer honours `SKILL_CLAUDE_SETTINGS` like the engine
(`skills_discovery.CLAUDE_SETTINGS_JSON`), pinned by a subprocess test that loads both with the
variable set. `scripts/apply-overrides.py` keeps its own `SKILL_CONCIERGE_SETTINGS`: it names the file
the overrides WRITER targets, a different role from the readers' test seam.

### 3. OMP tool names in the doctrine (OQ3, and the adjacent defect)

OMP registers MCP tools as `mcp__<server>_<tool>` with every run of non-alphanumerics folded to one
`_` (`src/mcp/tool-bridge.ts` `mintMCPToolName`); `skill-concierge:skill-search/search_skills` is only
the display label (`src/sdk.ts`). The OMP doctrine told the model to call that label — a tool that does
not exist — and rewrote rule 5's `get_skill("<name>")` to `read("skill://<name>")`, which resolves only
skills OMP itself loaded (`src/internal-urls/skill-protocol.ts`: `getActiveSkills()`, else "Unknown
skill") — i.e. never the hits rule 5 governs. The OMP rewrite now names
`mcp__skill_concierge_skill_search_search_skills` and leaves rule 5's `get_skill("<name>")` alone.
ADR-0039's "OMP tool names take the `skill-concierge:skill-search/search_skills` shape" is corrected by
this section.

### 4. The exclusion echo on OMP, Command Code, Cline and DSH

Each adapter sends `hooks/scripts/skill_exclusions.py` the same Claude-format payload it builds for
`ledger.py`, plus the tool result, and returns the echo through its host's own post-tool channel:

| Harness | Vehicle (installed source) | Load shapes echoed |
|---|---|---|
| OMP | `tool_result` handler returns replacement `content` (`shared-events.d.ts` `ToolResultEventResult`); the original blocks are kept and the echo appended | `read` on a `skill://<name>` root (never a sub-resource), the minted get_skill tool |
| Command Code | `cmd.hooks({afterToolCall})` returns `additionalContext`, appended as a separate text block (`mod-builder/reference/hooks-and-events.md`) | `activate_skill {name, arguments}`, get_skill |
| Cline | the PostToolUse file hook returns `contextModification` (hook-output schema in the binary) | `skills`/`use_skill {skill}`, flattened get_skill, `use_mcp_tool` |
| DSH | `ctx.on("tools/post-execute")` returns `{...downstream, additionalContexts}` (the shape of DSH's own `dsh-hooks-claude-code` bridge) | `skill {name}`, get_skill |

`skill_exclusions.py` now reads the loaded text from `tool_response` when it is a SKILL.md (a
get_skill body; an OMP `read` too if its text starts with the frontmatter rather than line numbers — unverified, otherwise it resolves by name), so the echo quotes the copy the
agent actually read; Command Code's `activate_skill` result is a wrapper without frontmatter, so there
it resolves by name. Name resolution (index path, then every harness's personal root and the matching
`<cwd>` roots) is the fallback; a refused load (get_skill's `{"error": …}`) echoes nothing. Every
vehicle filters by tool name — and OMP by skill root — before spawning, and is bounded (3 s) and
fail-open. OMP and DSH spawn asynchronously: both hosts await the handler (OMP
`runner.ts` `emitToolResult`, 30 s handler timeout; DSH's `post-execute` handlers are async), and a
blind drive of the OMP handler measured a synchronous spawn freezing the host's event loop for a
~270 ms median per skill load. Command Code keeps a bounded synchronous spawn (whether its mod runner
awaits `afterToolCall` is unverified), and Cline's bridge is its own short-lived process. DSH messages carry the `id` and `plugin` source DSH's `Message`
contract requires (its own bridge builds them with `createUserMessage`).
The DSH handler also writes the load to the ledger — the post-tool surface ADR-0050 §7 left for
"Phase 2" is now the verified `tools/post-execute`.

**DSH is wired by this release (operator's decision), and the DSH installer is fixed.** Wiring
exposed that `adapters/dsh/install.sh` had never produced a loadable patch layer: it appended list
items after a pristine profile's `[]` line — invalid YAML, so DSH's js-yaml rejected the file and the
profile failed to boot ("failed to parse overlay … cordis.patch.yml"); and every entry was a bare
`- id:`, which DSH's patch layer treats as an override of an EXISTING entry (warned "entry … not
found", skipped) — adding a plugin takes `- insert: [ {id, name, config} ]` (dsh-app-boot
`applyEntryPatches`). So on DSH neither the skill-search MCP row nor the unlazy stop-hook ever loaded.
The installer now drops the top-level `[]` line (column 0 only — an operator's indented `[]` value is
left alone), writes all three entries (MCP server, unlazy stop-hook, and the enforcement plugin
`adapters/dsh/skill-concierge.dsh.ts`) as insert patches, builds the result as `<patch>.new`,
validates it under DSH's own parse rules (DSH's js-yaml, DSH's `JSON_SCHEMA` + `!!js` schema, a
top-level array of mappings), and only then swaps it in with a timestamped backup — a result DSH could
not load (an operator entry in flow style) leaves the original untouched and fails the installer;
`doctor`'s DSH row flags both broken shapes and a missing enforcer entry. Verified: DSH's
`--dump-config` (the same patch code DSH boots with) composes the live `tui` profile with all three
entries; Oh-DSH's bundled Node v26 imports both `.dsh.ts` plugins natively and the enforcement
plugin's `tools/post-execute` handler returns the echo. The plugin takes each event's session from the
`agent` DSH passes (`agent.session.header.id`; DSH sets `DSH_SESSION_ID` only for tool subprocesses,
never in the host), gives a subagent session (`header.parentSession`) no doctrine, mandate or turn row
— DSH stamps a subagent's task prompt `kind: "user"` too, so the source filter alone cannot tell —
injects the doctrine once per session rather than once per process, reads only `kind: "user"`
messages as a prompt (never context another plugin injected), and never rewrites a non-`enter`
decision. `/goal` with attachments sends a fixed `kind: "user"` line the enforcer will see — noise, not
harm. Not yet observed: a live DSH session with the plugin loaded.

### 5. The re-rule marker and the audit

The doctrine's re-rule line ends `(re-rule: <old>)`, and the echo names that exact form with the loaded
skill's name. `skill-usage-audit` moves a retracted skill's `USING:` out of uptake into a `re-rules`
tally (per session, floor 0 — a re-rule never erases another session's `USING:` of the same skill,
whatever the transcript order; a `SEARCH:` re-rule counts too; an unmarked second `USING:` is a
multi-intent reply and retracts nothing). Replies without the marker count exactly as before. The
audit reads Claude Code transcripts only, so re-rules in other harnesses are not counted.

### 6. `disabled_in` outside Claude-launched servers (OQ5) — kept as is

`disabled_in` names the harness it describes, so it is true under every launcher; a per-harness verdict
would duplicate the enforcer's gate for no new truth. ADR-0058's "the server cannot tell which harness
launched it" is corrected to the precise claim: the shared `.mcp.json` carries no harness key. Claude
Code does pass `CLAUDECODE=1` into the server's environment (observed on five live servers), but that
cannot distinguish Claude from a harness started inside a Claude shell; OMP's MCP spawn passes no OMP
marker (its `OMPCODE` is set only for the bash tool's shell); DSH's row sets `SKILL_CONCIERGE_HARNESS=dsh`
explicitly. None of it is needed for a row that names its own harness.

## Consequences

- **EPOCH v0.49.0 for offer composition** under every harness: rows that were never invocable leave the
  installed offer (Claude and Codex lose OMP/ZCode-only and other-project rows; DSH and Cline gain a
  working filter). The v0.48.0 doctrine and row-contract watches continue; offer-level rates
  (hit@k, take, fallback) must not be pooled across the deploy time.
- The annex header and markers change text (`[omp]` per row, lowercase harness ids). No repo parser
  reads that block beyond its `Other-harness matches` prefix.
- The exclusion echo reaches Command Code (after its copied mod is reinstalled) and Cline (its bridge
  runs from the repo) immediately; OMP after its plugin cache updates; DSH at its next start (the
  plugin is now wired, see §4).
- **Known gaps, recorded not fixed:** `project:<cwd>` is still never-foreign under harnesses that do
  not read `.claude/skills` (DSH, Cline, Codex); from a very broad cwd (e.g. `~`) every project is a
  descendant, so project isolation keeps them all — it fails toward keeping, and the 96 → 0 probe was
  measured from `/tmp`; Codex's `personal` is never foreign, which is right only while
  `~/.agents/skills` (which Codex reads) is the Claude shelf — on a machine without it, Claude-only
  personal skills can reach Codex offers (pre-existing; the DSH/Cline shelf rule plus a
  `~/.codex/skills` twin would close it); `doctor`'s new stale-mod check compares against its own
  checkout, so run from a plugin cache it reports cache-vs-install skew; the enforcer still reads
  `Path.cwd()` at import and does not import under a 3.9 `python3` (both pre-existing — every adapter
  spawns `python3`, which is 3.12 here); the OMP adapter's ledger row (pre-existing) counts every
  `skill://` read — sub-resources, errored reads, unknown names — as a skill invocation, and its
  detached ledger child stamps the time it runs, not the call time (blind drive; ledger semantics
  are out of this release's scope); skill dirs a Claude session adds with `--add-dir` or
  `/cd` are invisible to the hook, so their project rows can be dropped as "other"; whether Command
  Code reads `<project>/.agents/skills` is unverified (kept); OMP's personal skills may reach it through
  the agents provider's `~/.agents/skills` link rather than the claude provider (unverified; the
  current rule keeps them); no live run of the OMP, DSH or Command Code adapters was made — the echo is
  verified by driving each handler with its host's documented event shape, and end to end through the
  real Cline bridge process.
- Revert paths: `ENFORCER_PROJECT_ISOLATION=0` (project rule); `ENFORCER_CROSS_HARNESS=0` (the whole
  cross-harness filter, as before); the adapter echoes revert with the release commit (each is one
  handler); the doctrine marker and the audit's re-rule tally revert together with the release commit.
