# ADR-0058 — Off-list doctrine rule, exclusion echo, row provenance, and account-synced skills (default OFF)

Status: Accepted (2026-09-25)
Relates to: ADR-0011 (keep-off), ADR-0015 (library doctrine), ADR-0026 (LLM-utterance trigger layer — the env-forwarding class this release unifies), ADR-0030 (operator-owned overrides — the "no doctor row" precedent), ADR-0032/ADR-0048 (external annex — the exclusion pattern reused for `claude-synced`), ADR-0033/ADR-0039/ADR-0042/ADR-0050/ADR-0051 (per-harness discovery scopes — the origin families this release names), ADR-0034 (cross-harness offer isolation — partially superseded, see below), ADR-0046 (blocklist — the read-live-at-call-time pattern reused for row provenance and the curated layer), ADR-0054 (harness-message lane — precedent for landing several related fixes as one ADR), ADR-0056 (doctrine rewrite — rule 5 partially superseded, see below).
Evidence: a local user session's SKILL-FIRST trail (incident specifics withheld — transcript path, session id and prompt text are not reproduced here per the privacy rule in `AGENTS.md` → *Guardrails*); the code diff, selftests, and unit/behaviour test suites landed in this release.

## Context

A session picked a skill by name outside that turn's search hits, the skill's own body said what
it was not for, and the agent kept going anyway — the doctrine had no rule for "outside the hits"
and no mechanism forced the excluding line back in front of the agent once the body was loaded.
Closing that traced into four adjacent gaps, all discovered from the same incident and landing in
the same release:

1. **No route for a name picked outside the hits.** Rule 3 only covered hits already shown; a
   skill chosen by name alone had no lawful path, so the agent skipped straight to `USING:` without
   reading the body it was about to run.
2. **A loaded body's own exclusions were silent.** The doctrine trusted the agent to notice and act
   on a "Don't use for" section it had just read. It didn't, here.
3. **Search rows claimed invocability the server cannot know.** Every row carried a slash
   `command`, implying the agent's own harness could fire it — true only for `personal`/`plugin`/
   `project` scopes. A `zcode-plugin` row named `skill-creator:skill-creator` rendered `command:
   "/skill-creator:skill-creator"` in every harness, including ones where that plugin does not
   exist and is, separately, switched off in Claude Code's own settings. The twin example
   (`agent-skills:*`, 25 rows) is `plugin` scope, not `zcode-plugin` — corrected here after an
   earlier draft of this work misstated it.
4. **Claude account-synced skills were not indexed at all**, so a skill the user has only through
   claude.ai sync was invisible to search, to the doctrine, and to the enforcer — a discovery gap,
   not a governance one, but one that had to be closed harness-aware from the first line of code
   given how synced skills interact with the namespace a spoofed plugin could also claim.

## Decision

### 1. Doctrine: the off-list route, the re-rule duty, rule 5

`hooks/doctrine/skill-first.md` gains two rule-3 paragraphs and a rule-5 rewrite, line-1-compatible
(no new token, no new `get_skill` literal beyond the one rule 5 already names):

- **Picking outside the hits** now has a route: line 1 `SEARCH:` → the search → load the body (the
  way rule 5 already loads a hit) → quote the line that covers the task → `USING: <name>` on its
  own line. A name is a label, not a fit — the Red Flags table gains a row for exactly that
  rationalization.
- **A loaded body that excludes the task — a hit's or not — is re-ruled in the same reply**: a new
  `USING:` or `SEARCH:` line, one sentence quoting the excluding line, and telling the user the
  agent switched. This duty is unconditional on how the skill was reached.
- **Rule 5** drops "cannot be invoked by name here" (ADR-0056's wording, now stale under row
  provenance) for: a hit your harness does not list still counts — whatever its `origin` or
  `external` marker — while it stays switched on for you; a hit whose `disabled_in` names your
  harness, or that your harness has switched off, is not a hit. `USING:` for a counted hit still
  means `get_skill("<name>")`, then follow that SKILL.md inline — same take-bar as installed
  skills.

Stated cost: the injected body grows 4,217 → 5,011 chars (measured; the test bound is ≤900 chars
of growth), once per session, zero per turn. No `RETRACT` token, and `get_skill("<name>")` still
appears exactly once — `doctrine.py`'s OMP rewrite depends on that.

### 2. The exclusion echo — deterministic, not self-reported

`hooks/scripts/skill_exclusions.py` (new, wired `PostToolUse(Skill|get_skill)` in `hooks.json`)
reads the just-loaded skill's own body and echoes its "not for" lines back as `additionalContext`:
a description sentence opening "Not for…"/"Don't use…", or the bullets under a "Don't use for" /
"Do not use for" / "When not to use" / "Not for" header (bold-label form included). This is
deterministic prevention, not a self-report the agent could omit under pressure — it reads the
file; it never asks the agent what the file said. Resolution: the index payload path (Qdrant
retrieve by the engine's point id), else a bare-name fallback under `~/.claude/skills` /
`<cwd>/.claude/skills`; silent on every miss and every error, capped at 6 lines × 200 chars.

The hook fires wherever `hooks/hooks.json` fires: Claude Code and ZCode (which natively runs the
plugin's Claude-format hooks, ADR-0042). Command Code, OMP, DSH, and Cline each have their own
enforcement vehicle that does not read `hooks.json` — an exclusion echo for those is a follow-up,
not shipped here.

### 3. Row provenance: `origin`, `disabled_in`, one response note, no `command`

`search_skills` / `consult_candidates` rows drop the slash `command` field on every non-catalog
row (catalog rows are unchanged) and gain:

- **`origin`** — which harness's skill roots hold the indexed copy, one of 8 families:
  `claude` (personal/plugin/project scopes), `codex`, `commandcode`, `omp`, `zcode`, `dsh`,
  `cline`, `claude-synced`. A test maps every scope `skills_discovery.visible_scopes()` can emit
  through `_ORIGIN_HEADS`, so a new scope family that forgets to extend it fails a test rather
  than silently defaulting.
- **`disabled_in`** — `["claude"]` on a `:`-namespaced row whose plugin id is INSTALLED for
  Claude Code (`installed_plugins.json`) with every installed `<id>@<marketplace>` key switched off
  in the merged `enabledPlugins` layers (user → `<cwd>/.claude/settings.json` →
  `<cwd>/.claude/settings.local.json`, later layer wins per key). That is the per-turn hook's own
  invocability rule (`enforcer._invocable_plugin_ids`), so a stale `false` key for an uninstalled
  marketplace never marks a plugin Claude can run, and an unreadable registry gives no signal.
  An independent review caught the first draft reading settings alone — the exact false claim
  ADR-0034 forbids. On an account-synced row, `disabled_in` names every non-Claude harness, so
  rule 5 and the note keep synced bodies out of harnesses that would read them unsanitized.
- **One response-level `note`** (`ROW_NOTE`) on both tools, present exactly once per response, not
  per row: *"origin = which harness's skill roots hold the indexed copy. Invoke a hit by name only
  if your harness lists it; otherwise load it with get_skill(name) and follow its SKILL.md inline —
  unless disabled_in names your harness or your harness has it switched off: then it is not a
  hit."*

**Why the server cannot reuse the enforcer's own gate.** The enforcer's `_plugin_gate_ok` /
`_invocable_twin` machinery already answers "can THIS session invoke this row" — but it runs inside
a per-harness hook process that knows which harness launched it. The MCP server does not: Claude
Code, OMP, and ZCode all spawn it from one shared `.mcp.json` whose env carries no harness key, so
a row can state only facts the server itself holds — where the copy lives, and whether Claude's own
settings switch it off — never a per-harness invocability verdict. `SKILL_ROW_ORIGIN=0` (read per
call, not forwarded through `engine_env.py` — this is a query-time flag, not an index-shaping one)
restores the exact pre-provenance row shape.

### 4. Account-synced skills — indexed, gated on scope, shipped default OFF

`skills_discovery.py` adds `SYNCED_ROOT` (`~/.claude/skills/synced/`) and, gated on
`SKILL_SYNCED_ROOTS` (default `0`), discovers `<bucket>/<name>/SKILL.md` at **exactly** that depth,
**only** for names the bucket's own `manifest.json` lists, and **only** when the file's real path
resolves inside the real synced root (a symlink escape is rejected). A hit is namespaced
`anthropic-skills:<name>`, scoped `claude-synced`, and carries `creatorType`/`source` from the
manifest as payload — never sent to third-party utterance/capsule generation
(`build_triggers.py` excludes the scope; `apply-overrides.py` excludes it from `skillOverrides`,
whose treatment of synced skills is undocumented upstream).

`claude-synced` is foreign to every harness but Claude Code — appended to every non-claude tuple in
`_foreign_scopes()` — and is deliberately **excluded from the cross-harness foreign annex**
(`_retrieve_foreign`'s scope filter drops it): Claude Code sanitizes synced skill bodies before
serving them (Claude Code's own CHANGELOG, 2.1.228); a harness whose own loader never sanitizes
that content should not receive it as a labeled "consume via get_skill" recommendation either.

**The gate keys on scope, never on the name.** `_plugin_gate_ok(name, scope)` passes a
`claude-synced` row only when `RUNNING_HARNESS == "claude"`; a `plugin`/`zcode-plugin`/`omp-plugin`
row that happens to be named `anthropic-skills:x` is rejected regardless of harness (selftest
spoofs all three and asserts the reject). This is deliberate, not defensive-in-depth: Claude Code's
own CHANGELOG (2.1.282) states plainly that "a plugin so named still loads but yields name ties to
synced skills" — a plugin can be published under this namespace, so the name alone is a spoofable
signal and the scope, which discovery derives from the real filesystem path, is not. The chain
sidecar mirror (`next-skills.json`'s `claude-synced` bucket) is written unconditionally at index
time but **read only under the Claude lane** — the one place a hinted `anthropic-skills:` name is
trustworthy without a payload scope to check.

**Default OFF.** A harness whose cache predates this release would offer a synced row as installed
(it has no concept of the scope), so the flag ships `0` until `doctor` shows every harness cache at
≥0.48.0 — flipping it on is a separate, reviewed step (`SKILL_SYNCED_ROOTS=1` in `.mcp.json`,
forwarded like every other engine-shaping flag through `scripts/engine_env.py`), not part of this
release.

**Partial supersession of ADR-0034 and ADR-0056.** ADR-0034's consequence "`search_skills` and
chain hints are untouched" stays true for every pre-existing scope; this release adds one narrow
exception — the chain-hint sidecar mirror now reads the `claude-synced` bucket only under the
Claude lane, by design, because that scope did not exist when ADR-0034 was written. ADR-0056's rule
5 wording ("cannot be invoked by name here") is superseded by the rewrite in Decision §1 above; both
ADRs stay immutable and carry an index status note pointing here.

### 5. The curated trigger layer

`triggers-curated.json`, beside the canonical utterance corpus (no new env var — its location is
derived from `SKILL_TRIGGERS`'s directory), holds `{"<skill>": ["phrase", ...]}`: operator-authored
phrases replayed from real routing misses, not generated. `_trigger_phrases()` takes them **first**
— ahead of the LLM-utterance layer — within the existing combined `TRIGGERS_MAX` cap; phrases are
filtered to the same length/word bounds as every other trigger source. A malformed file writes one
stderr line (visible in the detached reindex log) and the layer is simply off; the cache is reset at
the top of every `build_index()` so an edit applies on the next reindex without a restart. Keys
starting `_` are documentation, not phrases. No doctor row — the same choice ADR-0030 made for
operator-owned chain overrides: a curated file the operator edits directly needs no health check of
its own.

### 6. One engine-env forwarding class

`scripts/engine_env.py` (new) holds `ENGINE_ENV_KEYS` — the single list of `.mcp.json`-pinned
index-shaping engine settings every reindex path must forward — store and embedder, trigger
layers, discovery roots (now including `SKILL_SYNCED_ROOTS`), plugin-enablement seams, and the
chain sidecar path. All five
builders (`auto_reindex.py`, `auto_flywheel.py` — including its disk-count subprocess env —,
`flywheel.py`, `doctor.py`, `setup.sh`'s `env_run()`) call `engine_env.engine_env()` instead of
each keeping its own copy of the key tuple; a real process-env value still wins, and an empty
`.mcp.json` value is never forwarded (an empty string would read as "on" downstream). This closes
the ADR-0026 forwarding-gap class structurally — a new engine-side flag now needs adding to one
list, not five — rather than by another one-off patch.

## Consequences

- **EPOCH v0.48.0** for the search row contract, the curated-trigger targets, and the doctrine
  trail metrics (USING/SEARCH/false-SKIPPING shares, the `authorized_skip` tally). Retrieval
  ranking and gate floors are unchanged, so the v0.47.x ledger watches (W1–W8) continue.
- **Offer composition does not reset** — `SKILL_SYNCED_ROOTS` ships `0`, so the index gains no new
  points and the per-turn offer is byte-identical until the flag is flipped on as a later, separate
  step.
- **A re-ruled reply carries two `USING:`/`SEARCH:` lines** (the original and the re-rule). The
  `skill-usage-audit` script counts both toward its uptake tally — a re-rule is not double-counted
  as a defect, but a reader of the trail should expect the pair.
- **Measured: the curated layer fixes the replayed miss, not new wordings.** On a scratch copy of
  the live index, the seeded editing skills rank first for the seeded phrasings (true by
  construction), while on two held-out phrasings far from the seed (max cosine 0.588 / 0.556) no
  invocable editing skill reached the top 6 in any configuration. The primary guard against the
  incident pattern is therefore the doctrine rule plus the exclusion echo, not retrieval.
- **Known pre-existing gap, not fixed here.** Codex's and OMP's `_foreign_scopes()` tuples still
  omit the `zcode-*` scopes (and Codex additionally omits `omp-*`), so e.g. a `zcode-plugin`
  `skill-creator:skill-creator` row can still appear in Codex's installed offer. `claude-synced`
  joins every tuple correctly in this release; the older gap is unrelated and stays open for a
  follow-up.
- **Open, not resolved here:** `disabled_in` reads Claude Code's settings layers from the MCP
  server's own cwd — under a Codex/OMP/ZCode-launched server it still reports Claude's disables
  (correctly labelled `claude`, so nothing it states is false), because the server cannot tell
  which harness launched it. Whether that is the wanted scope, or whether it should be omitted
  outside Claude-launched servers, is left for a follow-up decision.
- Revert paths, one-var each: `SKILL_ROW_ORIGIN=0` restores the pre-provenance row shape in every
  `.mcp.json`-equivalent descriptor; `claude-synced` needs no revert while it ships OFF (after a flip-on, turning it off means the flag
  plus a Qdrant filter delete on `scope=claude-synced` and dropping that sidecar key — a reindex
  alone only hides the points from `search_skills`); deleting
  `triggers-curated.json` + a reindex removes the curated layer; removing the `hooks.json` entry
  removes the exclusion echo (cached harnesses need a patch release); the doctrine and row-shape
  code changes revert with the release commit.
