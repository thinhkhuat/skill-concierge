# Architecture Decision Records

Decision records for **skill-concierge** — the *why* behind the design, captured so a
future maintainer (or agent) does not have to reverse-engineer intent from code comments.

> These ADRs exist because the intent *wasn't* loud enough once: an agent read the
> injected skill-catalogue, assumed built-in commands were indexable, ran the vendored
> eval, and drew wrong conclusions about retrieval quality. ADR-0001 + `../caveats.md`
> are the fix. Read them before judging the engine.

## Index

| ADR | Title | Status | Date |
|-----|-------|--------|------|
| [0001](0001-index-model-invocable-skills-only.md) | Index model-invocable `SKILL.md` only — exclude built-in/user-only commands | Accepted | 2026-06-26 |
| [0002](0002-fusion-which-plus-whether.md) | Fusion architecture — skill-search (WHICH) × skill-first (WHETHER) | Accepted | 2026-06-26 |
| [0003](0003-embedder-and-vector-store.md) | Multilingual mpnet-768 embedder + Qdrant server tier | Accepted | 2026-06-26 |
| [0004](0004-bundled-mcp-launcher-stable-venv.md) | Bundled MCP via launcher + stable venv (survive cache wipes) | Accepted | 2026-06-26 |
| [0005](0005-overrides-target-and-applier.md) | Keep-on overrides → `~/.claude/settings.json`, atomic applier (not upstream generator) | Accepted | 2026-06-26 |
| [0006](0006-compounding-invocation-ledger.md) | Compounding, never-rotated invocation ledger (logman `RETENTION_DAYS=0`) | Accepted | 2026-06-26 |
| [0007](0007-maintenance-skills-setup-doctor.md) | Maintenance skills (`setup` + `doctor`) — delegate health to the engine, fix only what is safe | Accepted | 2026-06-26 |
| [0008](0008-warm-embed-shim-timeout-calibration.md) | Warm embed shim Docker sidecar + timeout calibration (90ms → later relaxed to 200ms; see ADR note) | Accepted | 2026-06-26 |
| [0009](0009-operator-set-gate-thresholds.md) | Operator-set gate thresholds over data-backed defaults (word floor 2→5, score floor 0.40→0.45) | Superseded by 0017 (word floor by 0010) | 2026-06-29 |
| [0010](0010-word-floor-5-to-3.md) | Word floor 5→3 — let the language-aware imperative-veto see 4–5-word commands | Accepted | 2026-06-29 |
| [0011](0011-ledger-derived-offer-suppression.md) | Ledger-derived offer-suppression (`keep-off.json`) — auto-drop chronic never-take skills from the menu | Accepted | 2026-06-29 |
| [0012](0012-multi-vector-max-pool-retrieval.md) | Multi-vector MAX-pool retrieval (trigger layer) — score each skill by its best phrase point | Accepted | 2026-06-30 |
| [0013](0013-doctor-engine-freshness-check.md) | doctor `Engine freshness` check — detect a stale MCP venv engine after `/plugin update` | Accepted (amended by 0018) | 2026-07-01 |
| [0014](0014-sessionstart-index-self-heal.md) | SessionStart index self-heal (`auto_reindex.py`) — detached/throttled incremental reindex | Accepted | 2026-07-01 |
| [0015](0015-authorized-skip-tier-and-library-doctrine.md) | AUTHORIZED-SKIP tier + library doctrine — enforcer emits a `SKILL-CHECK:` authorization on its silent verdict legs | Accepted | 2026-07-04 |
| [0016](0016-body-derived-trigger-points.md) | Body-derived trigger points — mine each skill body's labeled decision-sections into the MAX-pool trigger layer | Accepted | 2026-07-04 |
| [0017](0017-enforcer-gate-thresholds-v2-widen-offer-menu.md) | Enforcer gate thresholds v2 — retain score floor 0.45, widen offer-menu TOP_K 5→8 (+ companion `search_skills` query fanout) | Accepted (supersedes 0009) | 2026-07-05 |
| [0018](0018-self-healing-launcher-engine-resync.md) | Self-healing launcher — auto-resync the venv engine on plugin-version change (no more stale MCP after `/plugin update`) | Accepted (amends 0013) | 2026-07-05 |
| [0019](0019-over-fire-lane-and-gate-legibility.md) | H5 over-fire authorized-skip lane — narrow self-referential lane + whole-prompt task-verb veto (gate legibility deferred) | Accepted | 2026-07-06 |
| [0020](0020-subagent-session-scoping.md) | H3 subagent session-scoping — suppress doctrine injection inside subagents (hook `agent_id`) + audit-side exclusion | Accepted | 2026-07-06 |
| [0021](0021-rationalization-harvest-loop.md) | H1 rationalization harvest loop — capture verbatim false-skip excuses (scrubbed, gitignored) to feed doctrine | Accepted | 2026-07-06 |
| [0022](0022-red-flags-rationalization-table.md) | H2 Red Flags table — rule-6/4 rationalizations as a symptom→refutation table | Accepted | 2026-07-06 |
| [0023](0023-trigger-purity-lint.md) | H4 trigger-purity lint — reject workflow-summary phrases from the MAX-pool triggers (shadow-first) | Accepted | 2026-07-06 |
| [0024](0024-staleness-detector-content-not-mtime.md) | Staleness detector fingerprints content, not mtime — fixes chronic false "disk changed since last index" | Accepted | 2026-07-06 |
| [0025](0025-autonomous-override-freshness-and-keep-on-management.md) | Autonomous `skillOverrides` freshness (SessionStart self-heal + doctor drift detection) + seamless keep-on management | Accepted | 2026-07-06 |
| [0026](0026-llm-utterance-trigger-layer.md) | LLM-utterance trigger layer — offline flywheel-generated natural-utterance phrases (EN+VN) as MAX-pool trigger points, utterances-first, gated `SKILL_LLM_TRIGGERS` | Accepted | 2026-07-08 |
| [0027](0027-flywheel-first-class-multi-provider.md) | Flywheel promoted to first-class — multi-provider LLM routing (LM-Studio/Ollama/gateway), `doctor` visibility, `skill-concierge:flywheel` skill; auto-hook deferred to Phase 2 | Accepted | 2026-07-08 |
| [0028](0028-multi-session-index-scoping-and-installed-plugin-filter.md) | Scope-tagged points so concurrent sessions stop pruning each other's project skills; index only the installed+enabled plugin version; per-project manifest; flywheel defers on a stale index; utterance prompt v2 (vocabulary distance, not sentence-likeness) | Accepted | 2026-07-09 |
| [0029](0029-next-skill-chain-hints.md) | Next-skill chain hints — optional `next-skills:` frontmatter, scope-keyed atomic sidecar + ledger tail-read (zero new state files, zero hot-path network), `CHAIN-HINT:` on all inject-bearing legs with keep-off/scope filters; gated `ENFORCER_CHAIN_HINT` | Accepted | 2026-08-19 |
| [0030](0030-operator-owned-chain-overrides.md) | Operator-owned chain overrides — `next-skills-overrides.json` merged reader-side in the enforcer; third-party chain curation survives upstream upgrades (override-wins, fail-open, no engine patch) | Accepted | 2026-08-20 |
| [0031](0031-external-catalog-roots.md) | External catalog roots — multi-catalog retrieval without import; operator-owned `catalog-roots.json`, alias-namespaced `catalog:<alias>` scope, search-only tier with provenance markers, read-inline via `get_skill` + explicit symlink promotion | Accepted (impl. pending) | 2026-08-23 |
| [0032](0032-external-catalogs-first-class-annex.md) | External catalogs first-class in the offer — additive external annex (installed offer byte-identical, ≤`ENFORCER_EXTERNAL_SLOTS` externals ≥`ENFORCER_EXTERNAL_FLOOR` via a separate query, get_skill read-inline, kill-switch) + usage-promotion (repeat external-takes auto-graduate to installed); supersedes ADR-0031's search-only tier | Accepted | 2026-08-23 |
| [0033](0033-dual-harness-codex-parity.md) | Dual-harness parity — Codex skill discovery: index `~/.codex/skills` + `~/.codex/plugins/cache/**` under distinct `codex-*` scopes (one shared collection, no cross-harness pruning); Codex-native plugin manifest (no hooks field — auto-discovered); chain-hint mirror reads codex scopes; kill-switch `SKILL_CODEX_ROOTS`; revives the abandoned July attempt with hermetic test fixtures | Accepted | 2026-08-24 |
| [0034](0034-cross-harness-offer-isolation.md) | Cross-harness offer isolation — the installed offer holds only skills THIS harness can invoke: `_retrieve` over-fetches and POST-filters (scope records where a copy lives, not invocability — a project-enabled plugin's Codex twin is invocable anyway), a separate query re-surfaces the rest as a marked `[codex]`/`[claude]` annex consumed via `get_skill`; derived foreign-scope set; precedence-based harness detection; kill-switch `ENFORCER_CROSS_HARNESS`; companion fixes glob both plugin caches at `skills/<category>/<skill>/` and index `scope`+`tier` | Accepted | 2026-08-24 |
| [0035](0035-codex-mcp-relative-cwd-wiring.md) | Codex MCP wiring — relative `cwd`, not `${CLAUDE_PLUGIN_ROOT}`: Codex never expands the variable in plugin MCP command/args (openai/codex#35762), so skill-search was dead in every Codex session; new `.codex-plugin/mcp.json` with `./bin/skill-search-mcp` + `\"cwd\": \".\"` (native plugin-root resolution, #28145), env parity with `.mcp.json` enforced via driftcheck; corrects ADR-0033's \"reads .mcp.json the same way\" | Accepted | 2026-08-24 |
| [0036](0036-dynamic-annex-sizing.md) | Dynamic annex sizing — competitive margin replaces the fixed 2-row annexes: annex floor = `max(pool floor, top_installed − `ENFORCER_ANNEX_MARGIN`)`, caps 4 external / 2 foreign; strong inventory shrinks annexes to 0–1, thin inventory widens to cap; TOP_K + zero-displacement untouched; `ENFORCER_ANNEX_DYNAMIC=0` reverts | Accepted | 2026-08-24 |
| [0037](0037-borrowed-manifest-freshness.md) | Borrowed-manifest freshness — a server whose cwd is not a project (Codex, ADR-0035) borrows the newest other root's manifest for freshness instead of reporting `never indexed` forever; staleness stays `None` (unknowable, not false); genuinely manifest-less machines still degrade | Accepted | 2026-08-24 |
| [0038](0038-command-code-triple-harness-parity.md) | Command Code triple-harness parity — Command Code (`cmd`) added as third first-class citizen: mod-based `transformInput` enforcer, tool/prompt telemetry, `commandcode-*` discovery scopes, native doctrine tool naming, `install.sh` adapter | Accepted | 2026-08-24 |
| [0039](0039-omp-quadruple-harness-parity.md) | OMP quadruple-harness parity — Oh My Pi as the fourth first-class citizen: extension-module enforcement (`before_agent_start`; OMP ignores Claude-format hooks), native `${CLAUDE_PLUGIN_ROOT}` expansion (no per-harness MCP descriptor, manual fallback only), `omp` identity via `OMPCODE=1` (CLAUDECODE alone is not claude), `SKILL_OMP_ROOTS` kill-switch, `codex-plugin` foreign under omp | Accepted | 2026-08-25 |
| [0040](0040-behavior-mined-skill-chains.md) | Behavior-mined skill chains — the ledger's real per-session sequences mined offline (`build_chains.py`, support × lift; closure skills die on lift) into `mined-chains.json`, merged as the lowest layer under ADR-0030 overrides and ADR-0029 declared frontmatter (fills empty entries only; visible-catalogue filtered; `ENFORCER_MINED_CHAINS` kill-switch) | Accepted | 2026-08-28 |
| [0041](0041-multi-intent-offers-and-route-projection.md) | Multi-intent offer shaping + route projection — deterministic lexical intent clustering of the shown candidates (leads-first render when ≥2 comparable clusters) and a bounded cycle-safe 4-node ROUTE line for the top candidate from the merged chain map, both context-only (no gate/floor/slot change, locked literals untouched, single-intent-no-route renders byte-identical); `ENFORCER_MULTI_INTENT` / `ENFORCER_CHAIN_PROJECTION` kill-switches; offer events gain `n_intents`/`route` | Accepted | 2026-08-28 |
| [0042](0042-zcode-quintuple-harness-parity.md) | ZCode quintuple-harness parity — ZCode as fifth first-class citizen with FULL native Claude-plugin parity (no adapter vehicle): `zcode` identity via `ZCODE_PLUGIN_ROOT`/`.zcode` marker, shared-shelf-aware foreign scopes (`personal` invocable iff `~/.agents/skills` resolves to `~/.claude/skills`), registry+filesystem twin rescues, `SKILL_ZCODE_ROOTS` registry-enumerated discovery scopes, interpreter-form `.mcp.json` (exec-bit-proof `/bin/bash` + absolute `SKILL_SERVER_RECORDS`), one-directional launcher self-heal (a stale cache never downgrades the shared venv), `check_zcode` doctor row | Accepted | 2026-08-28 |

## Status values

`Proposed` → `Accepted` → `Deprecated` / `Superseded` (or `Rejected`).
Accepted ADRs are immutable — supersede with a new one rather than editing.

## See also

- [`../caveats.md`](../caveats.md) — operational landmines (the loud gotchas list).
- [`../plan.md`](../plan.md) — the fusion build plan + dated build log (the journal; ADRs extract the *decisions* from it).
