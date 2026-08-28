# Vendored: skill-search

This directory is a **vendored copy** of the upstream skill-search MCP engine, carried
into `skill-concierge` so the plugin is self-contained and portable.

- **Upstream:** <https://github.com/sowhan/skill-search>  (PyPI: `skill-search-mcp` 0.1.0)
- **Author / © :** Sowhan Mohammed — **MIT License** (preserved at `./LICENSE`)
- **Vendored:** 2026-06-26, from the local study clone (`CLONED/skill-search-tools`).

## What this provides
The semantic retriever: `skill_search/server.py` (MCP tools `search_skills`, `get_skill`,
`reindex`, `health`), `skills_discovery.py` (single discovery source of truth),
`generate_overrides.py` (name-only budget overrides). Deps (`mcp[cli]`, `qdrant-client`,
`fastembed`, `requests`) are NOT vendored — `setup.sh` installs them into a **stable** venv
at `~/.claude/skill-concierge/venv` (outside the plugin cache, so it survives reinstalls
— see `docs/adr/0004-bundled-mcp-launcher-stable-venv.md`).

> ⚠ **The `eval/` here is calibrated to the upstream author's environment** — its recall@k
> measures a skill universe this deployment deliberately excludes. See
> `eval/README-LOCAL.md` and `docs/adr/0001-index-model-invocable-skills-only.md`.

## Local customizations (layered at the plugin level, NOT changes to this source)
- **Embedder:** `sentence-transformers/paraphrase-multilingual-mpnet-base-v2` (768-dim,
  multilingual) instead of the upstream default `bge-small-en` — fixes EN-query→VN-skill misses.
- **Vector store:** Qdrant **server** tier (Docker `skill-search-qdrant` @ localhost:6333),
  not the embedded single-process store — allows concurrent Claude sessions.
- **Budget overrides:** curated keep-on set written to `~/.claude/settings.json` (global
  single source). NOTE: do **not** run upstream `skill-search-overrides` — it writes
  `settings.local.json` and reverts the hand-curated keep-on allowlist (see deployment readme).
- These are applied via the plugin's own `.mcp.json` env + `setup.sh` + `scripts/apply-overrides.py`,
  keeping this vendored source unmodified for clean upstream diffs.

## Engine-code patches (DIRECT edits to the vendored source — re-apply after re-vendoring)
Unlike the plugin-level layer above, these modify the vendored engine and must be re-applied if
upstream is re-vendored:
- **Multi-vector MAX-pool retrieval (v0.10.0, ADR-0012):** `server.py` (`search_skills` groups query;
  `build_index` base + per-trigger layer) and `skills_discovery.py`. Gated by `SKILL_MULTIVECTOR`.
- **Plugin self-prefix guard (v0.10.2):** `skills_discovery._namespaced_name` skips the plugin-id prefix
  when a skill's frontmatter `name:` already starts with `<plugin_id>:` (prevents `ck:ck:…` for plugins
  like ClaudeKit that self-namespace).
- **Body-derived trigger points (v0.12.0, ADR-0016):** `skills_discovery.py` adds `_extract_body_triggers`
  + a `body_triggers` field on the parsed dict — short phrases mined from the body's LABELED decision
  sections (`## When to Use`, `Triggers:`, `Use when:`, `Examples:`, …; a `Do NOT use` block ends the
  section so exclusions don't leak). `server.py` adds `_trigger_phrases`, which folds those into the SAME
  MAX-pool trigger layer as the description phrases — deduped against the description and capped COMBINED at
  `_TRIG_MAX` (per-skill triggers never exceed the same 12-slot ceiling as before; growth is bounded, though
  the total point count does rise as body phrases fill previously-empty slots — measured 2231→3570, +60%, far
  under full-body chunking's 2-4×). Gated by `SKILL_BODY_TRIGGERS` (default on;
  `=0` + reindex reverts to description-only, byte-identical to before). Extends ADR-0012's trigger layer;
  base vectors are untouched (no MEAN/centroid). **Requires re-copy into the stable venv
  (`pip install vendor/skill-search`) + a reindex to deploy.**

- **Trigger-purity lint (v0.14.0, ADR-0023):** `skills_discovery.py` adds a purity predicate
  (`_is_impure_trigger`) at the body-trigger EXTRACTION site — it flags workflow-SUMMARY phrases
  (numbered-step leads; `runs|generates|produces|creates … pipeline|workflow|report|steps`) that embed
  near generic process-prose instead of user intent, so they don't pollute the MAX-pool trigger surface
  and bury the skill. Applies superpowers' SDO law (a trigger must be a trigger-CONDITION). Gated by
  `SKILL_TRIGGER_PURITY` (states `shadow|active|off`, default **`shadow`**). `shadow` LOGS would-drops
  `(skill, phrase)` and drops nothing — the index is **byte-identical** to pre-H4; `off` skips the
  predicate (also byte-identical); `active` drops impure phrases. Deliberately conservative (only
  unambiguous summaries flag). **ACTIVATION (`active`) needs a FULL reindex** (`--reindex --force`), NOT
  the incremental path: the per-phrase `content_hash` reindex is correct for body edits but WRONG for a
  filter-logic change — unchanged skills would keep their old unfiltered phrases, leaving a mixed-purity
  index. Extends ADR-0016's body-trigger layer; base vectors untouched. **Requires re-copy into the
  stable venv (`pip install vendor/skill-search`) + reindex + MCP restart to take effect.**

- **Staleness signal = content, not mtime (v0.14.1, ADR-0024):** `server.py` `_disk_signature` now
  fingerprints each skill's CONTENT (`_content_hash(_skill_text(s))`, keyed by deduped skill name) — the
  SAME signal `build_index` skips on — instead of `(path, mtime)`. Root-cause fix for the chronic false
  `disk changed since last index` FAIL: a mtime-only event (`/plugin update` re-materializing cache dirs,
  a re-clone, `touch`, a formatting-only save) no longer moves the signature, so the detector and the
  reindex skip logic finally agree on "changed"; it also collapses the all-cached-versions path churn
  (measured 852 paths) to the deduped indexed set (~530). Removed the now-unused `discover_skill_paths`
  import. **Requires re-copy into the stable venv + a reindex to deploy** (the reindex rewrites the
  manifest signature into the new content format).

- **LLM-utterance trigger points (v0.16.0, ADR-0026):** `server.py` adds a third source to the SAME MAX-pool
  trigger layer — the offline-generated per-skill utterance phrases (`eval/triggers.json` `llm_triggers`
  block, produced by `scripts/llm_triggers.py`). New `SKILL_LLM_TRIGGERS` flag (default **OFF** =
  byte-identical to today) + `_llm_utterance_phrases(name)` loader (cached; keyed on the SAME `name` the
  index/`build_triggers.py` use) + a rewritten `_trigger_phrases` that layers sources in QUALITY order:
  utterances FIRST, then description, then (`SKILL_BODY_TRIGGERS`) body — deduped case-insensitively and
  capped COMBINED at `_TRIG_MAX`. Utterances-first means the best phrases win the capped slots; raise
  `TRIGGERS_MAX` (e.g. 16) to add slots instead of evicting. Loader default path is a dev-tree
  convenience — the DEPLOYED venv copy must be given `SKILL_TRIGGERS=<repo>/eval/triggers.json`
  explicitly at reindex. **Mirror status:** engine-only, like ADR-0016's body-trigger fold. `build_triggers.py`
  is a *producer* (writes the base prose-phrase block) with no `_trigger_phrases` twin to sync; its only
  overlapping twin is `split_phrases`≡`_split_phrases`, left UNCHANGED. Extends ADR-0012/0016's trigger
  layer; base vectors untouched. **Requires re-copy into the stable venv (`pip install vendor/skill-search`)
  + `SKILL_LLM_TRIGGERS=1` reindex (shadow first) to deploy.**

- **Installed + enabled plugin scoping (`skills_discovery.py`):** `PLUGIN_GLOB`'s `**` matched *every*
  version directory the plugin cache has ever held, and every plugin regardless of whether the user still
  has it enabled. Measured on a live install: 587 `SKILL.md` collapsed to 256 unique `(plugin, skill)`
  pairs, 89 of them served by more than one version; dedup is first-writer-wins over glob order, which
  pinned `skill-concierge:doctor` and `:skill-search` to **0.3.0** while **0.18.1** was installed (31
  versions cached). Disabled plugins were indexed too — `superpowers:systematic-debugging` was being
  offered while `enabledPlugins` had it `False`, i.e. a result Claude Code cannot invoke. Both are the
  same class of pollution `PLUGIN_GLOB` already avoids for `marketplaces/`.
  Fix: new `_installed_plugin_roots()` reads Claude Code's own manifests —
  `~/.claude/plugins/installed_plugins.json` (`plugins[<id>@<mkt>][].installPath`) and
  `~/.claude/settings.json` (`enabledPlugins[<id>@<mkt>]`, absent ⇒ enabled) — and `_plugin_paths()`
  keeps only cache paths under an installed **and** enabled root. **Fails open**: unreadable manifests, or
  a filter that matches nothing, fall back to the unfiltered cache and log a warning — an index with no
  plugin skills is worse than a stale one. Escape hatch `SKILL_PLUGIN_FILTER=0` restores prior behaviour.
  Test seams: `SKILL_INSTALLED_PLUGINS`, `SKILL_CLAUDE_SETTINGS`. Deployed result: 548 → 427 indexed
  skills, 206 points pruned, zero in-use skills lost. **Requires re-copy into the stable venv
  (`pip install --force-reinstall --no-deps vendor/skill-search`) + a reindex from a fresh process** —
  long-lived MCP servers hold the old module in memory (ADR-0018).
  Also hardened the `SKILL_DIRS` comment: those globs are deliberately **one level deep**. A `**` there
  would walk the whole project tree (on the dev machine: 6,334 `SKILL.md` under `CLONED/`, 8,163
  workbench-wide). Guarded by `test_project_glob_is_not_recursive`.

- **Scope-tagged points + scope-bounded prune + scope-filtered query (`skills_discovery.py`,
  `server.py`):** Claude Code spawns one MCP server per session, each with its own CWD, and they all
  write ONE Qdrant collection — while `SKILL_DIRS[1]` is `Path.cwd()/.claude/skills`. So each session
  saw a different skill set, and `build_index`'s `removed = [pid for pid in existing if pid not in
  desired]` deleted whatever the *other* session's project contributed. Observed live: a reindex from
  `LANDING_ZONE/...` reported `deleted: 32`, wiping the project points a reindex from `MY-WORKBENCH`
  had just written; last writer won, forever, on a 30-minute hook throttle.
  Fix: `_scope_for(path)` tags every skill `personal` | `plugin` | `project:<root>`; `visible_scopes()`
  names what this process owns. `build_index` writes `scope` into every point payload;
  `_existing_points()` returns `(content_hash, scope)`; `_point_changed()` re-embeds when the text OR
  the scope changed (this is what migrates legacy scope-less points — a description that never changed
  would otherwise keep a scope-less payload forever and be filtered out of every search); `_prunable()`
  deletes only ids that are gone from disk **and** owned by a visible scope, so a foreign project's
  points are "not mine", not "deleted". `search_skills` and `_indexed_names` apply `_scope_filter()`
  (visible scopes ∪ `scope is null`, the null arm keeping legacy points searchable until the migrating
  reindex lands). Filtering `_indexed_names` is also what killed the chronic false
  `4 skill(s) on disk but not indexed` — `health()` was diffing a CWD-scoped disk view against a
  globally shared index, and that false alarm is what invited a destructive reindex in the first place.
  Verified live: reindex from the owning CWD → `deleted: 0`, 27 project points written; reindex from a
  foreign CWD → `deleted: 0`, all 27 survive; `health()` from the owner → `status: ok, dark: none`;
  a project-scoped skill ranks #1 for its own query in the owning session and is absent in a foreign one.

- **Per-project index manifest (`server.py` `META_PATH`, `skills_discovery.manifest_key()`):** the
  manifest stores `_disk_signature()`, which is CWD-scoped, but the file was global. Two sessions with
  different project roots therefore overwrote each other's signature and both reported a permanent
  `skills changed on disk since last index`. `META_PATH` now defaults to
  `~/.cache/skill-search/index_meta-<md5(PROJECT_ROOT)[:8]>.json`. `SKILL_META_PATH` still overrides.
  `hooks/scripts/auto_flywheel.py::_meta_path()` mirrors the derivation (same CWD ⇒ same file).

- **YAML scalar unwrapping (v0.20.6):** `skills_discovery.py` adds `_unwrap_scalar`, applied to both
  `description:` and `when_to_use:`. The regex capture returns a frontmatter value exactly as authored,
  scalar syntax included — so `description: >-` kept the literal `">-"` plus every continuation line's
  newline and indent, and `description: "…"` kept its surrounding quotes. All of that went into the
  embedded base vector, so the retriever scored skills partly on punctuation. Measured 210 of 416 skills
  affected, 25 of them in the always-on set; after the fix, 0. Handles the three shapes frontmatter
  actually uses — block scalars (`|`/`>` with chomping and indent indicators; literal keeps line breaks,
  folded folds them to spaces on paragraph boundaries), quoted flow scalars (quotes stripped, `\"` and
  `''` unescaped), and plain wrapped scalars (newline+indent folded to one space). Deliberately not a
  YAML parser — this module is dependency-free by contract. Distinct from the v0.20.4 terminator fix,
  which stopped hyphenated NEXT KEYS being swallowed; this one cleans the value's own syntax. Pinned by
  `tests/test_discovery.py::test_parse_skill_description_unwraps_yaml_scalars`. **Requires re-copy into
  the stable venv + a FORCED reindex** (`--reindex --force`): the parsed text changes while the file
  content hash does not, so the incremental path would skip every skill.

- **Engine-build identity (v0.20.6, extended v0.20.7):** `server.py` adds `_engine_build()` and the
  module-level `_ENGINE_BUILD` — an md5 over `server.py` + `skills_discovery.py`, computed **at import
  on purpose**. A long-lived MCP server keeps executing the bytes it imported at start, so when the venv
  engine is replaced underneath it, that server and every fresh process parse the same `SKILL.md` files
  with different parsers and derive different `_disk_signature()` values from an UNCHANGED disk;
  whichever writes the manifest last hands the other a permanent false `disk changed since last index`.
  Computing the id lazily would hash the NEW bytes the process is not running, making the whole
  mechanism inert. `_write_manifest` stamps it as `engine`; `_engine_drift()` compares, treating a
  missing key or an `"unknown"` sentinel on either side as "cannot tell", never as drift. On a mismatch
  `_health()` sets `stale` to `None` (unknowable across builds, not false) and names the remedy —
  **restart**, not reindex.
  *(This entry was missing for v0.20.6 and is recorded here retroactively; re-vendoring would have
  silently dropped the mechanism.)*
  **v0.20.7 extends it two ways.** (1) `_health()` now emits `engine_build {running, index_written_by}`
  on **every** report rather than only under drift — which build a process runs is a fact about that
  process, and the one reader that needs a *healthy* process's build could not otherwise get it without
  re-deriving `_engine_build()`'s hashing rule in a second copy free to stop agreeing. Consumers key on
  `index_written_by` being non-null; mere presence no longer means drift. (2) New `SERVER_RECORDS`
  (seam `SKILL_SERVER_RECORDS`, default `~/.cache/skill-search/servers/`) and `_record_server_build()`,
  called only from `main()`'s `mcp.run()` branch: each live server writes `<pid>.json` = `{pid, build,
  started_at}` so an external reader can look up which build a running server executes instead of
  inferring it from file timestamps — which cannot work, because `setup.sh` re-copies the engine on
  every run and moves those timestamps without moving the bytes (see `docs/caveats.md` §17).
  Best-effort and exception-swallowing by contract: it sits on the server's startup path, where losing
  a diagnostic is acceptable and failing to start is not. The write is write-then-`os.replace` because
  the file is read by a concurrent process by design — a truncating write would let a reader see a torn
  file and report the build as unknown. It prints nothing (stdout would corrupt the stdio handshake)
  and catches `Exception`, not `BaseException`, so `KeyboardInterrupt` still propagates. Pinned by
  `tests/test_indexing.py::test_health_reports_drift_not_false_disk_changed`,
  `::test_health_always_reports_running_engine_build`,
  `::test_health_reports_running_build_even_without_a_manifest`,
  `::test_server_records_its_own_build_for_live_lookup`, `::test_server_build_record_never_raises`,
  `::test_cli_paths_write_no_server_record`. The seam is pinned in `.mcp.json` so the reader
  resolves the same directory the writer used — see `docs/caveats.md` §17.
  **v0.20.8 reworded both drift emitters** (`_staleness_warning`, `_health`). One symptom hides two
  causes with opposite remedies — a server still live on the old build (restart; a reindex hands the
  mismatch back) versus a manifest merely left over from the previous release (reindex; it re-stamps
  and clears) — and an engine process can see neither, since it knows its own build and nothing about
  other processes. The earlier text asserted the first while **every** engine upgrade lands in the
  second, because `_ENGINE_BUILD` hashes these two modules and so changes whenever either does. Both
  emitters now state the observation, name **no** remedy, and route to doctor, whose `_drift_remedy`
  holds the live-server evidence and decides. They must not offer one either: both strings are read
  by the MODEL, and `reindex()` runs INSIDE the process whose build is in question — if that build is
  the older one, reindexing there re-stamps the manifest backward and fights the session-start
  rebuild. Do not re-add a remedy here, unconditional or conditional — see `docs/caveats.md` §18.
  Pinned by `::test_drift_text_never_rules_out_a_reindex`,
  `::test_drift_text_never_orders_a_reindex_from_the_suspect_process`, and
  `::test_drift_text_never_asserts_a_live_old_server`.
  **`_write_manifest` is write-then-`os.replace`** for the same reason the records are: the
  SessionStart reindex rewrites it while a live server reads it, and a truncating write let that
  reader parse nothing and report "never indexed" on a healthy index.

- **Next-skills chain-hint sidecar (ADR-0029):** `skills_discovery.parse_skill` reads an optional
  `next-skills:` frontmatter value (comma/space separated successor names — must match catalogue
  ids exactly, namespaced for plugin skills) into a `next_skills` list on the parsed dict; unauthored
  skills carry `[]`, never a missing key, because the READER (the plugin's `enforcer.py` hook) uses
  key presence as catalogue membership. `server.build_index` calls `_write_next_skills_sidecar`
  unconditionally: it writes `~/.claude/skill-concierge/next-skills.json`
  (seam `SKILL_CONCIERGE_NEXT_SKILLS`) as `{scope: {name: [successors]}}` with EVERY indexed skill
  keyed — a per-scope MERGE, not replace (each session writes only `skills_discovery.visible_scopes()`,
  the same ownership rule `_prunable` enforces for points, so concurrent sessions with different CWDs
  cannot last-writer-wins each other — ADR-0028's incident class), write-then-`os.replace`, best-effort
  (a sidecar failure logs and never fails the index). No Qdrant payload carriage and nothing embedded:
  `_fuse_ranked` renders `{name,command,description,score}` only and `get_skill` already returns the
  full SKILL.md frontmatter, so the sidecar is the single delivery surface. The consumer flag
  `ENFORCER_CHAIN_HINT` lives plugin-side and gates only the hook's read — the sidecar content is
  flag-independent, so there is no producer/consumer drift to forward (contrast the ADR-0026
  `.mcp.json` gap). Pinned by `tests/test_discovery.py::test_parse_skill_next_skills_list` and the
  enforcer selftest §9. **Requires re-copy into the stable venv
  (`pip install --force-reinstall --no-deps vendor/skill-search`) + a reindex to deploy** (the
  sidecar is written by the index path, so it appears only after the new engine rebuilds).

- **External catalog roots (ADR-0031, v0.22.0):** `skills_discovery.py` adds `CATALOG_ROOTS_PATH`
  (seam `SKILL_CONCIERGE_CATALOG_ROOTS`, default `~/.claude/skill-concierge/catalog-roots.json`),
  `catalog_roots()` (validated, fail-open `{}` — absence IS the off-switch), `_catalog_skills()`
  (one-level glob per root, per-root include/exclude dirname globs, name minted `<alias>:<dirname>`,
  scope `catalog:<alias>`), and folds catalogs into `discover_skills()` LAST (installed name always
  wins; a catalog SKILL.md whose realpath equals an already-found skill — a promoted symlink — is
  suppressed) and into `visible_scopes()` (machine-wide config → every session sees the same set, so
  the existing scope-visibility prune handles root removal). `server.build_index` stamps
  `tier: "external"` on every catalog point (base + trigger) — the plugin-side enforcer excludes the
  tier with one `must_not` (search-only tier) — and `_write_next_skills_sidecar` SKIPS catalog scopes
  (chain hints are preview-layer; externals are search-only). `_fuse_ranked` marks catalog hits with
  `external: <alias>` + a get_skill consumption note and drops the `/command` field (not installed).
  `generate_overrides.py` excludes catalog scopes (no dead skillOverrides). Pinned by
  `tests/test_discovery.py` catalog cases + enforcer selftest case 10. **Requires re-copy into the
  stable venv + a reindex to deploy.**

- **Dual-harness Codex discovery (ADR-0033, v0.24.0):** `skills_discovery.py` adds
  `CODEX_PERSONAL_ROOT` (`~/.codex/skills`), `CODEX_PROJECT_ROOT` (`{cwd}/.codex/skills`), and
  `CODEX_PLUGIN_GLOB` (`~/.codex/plugins/cache/**/skills/*/SKILL.md`), folded into `SKILL_DIRS`
  and `_plugin_paths()` — both harnesses' skills index into ONE shared Qdrant collection under
  DISTINCT scopes (`codex-personal` | `codex-plugin` | `codex-project:{root}`) so neither
  harness's reindex prunes the other's points (extends ADR-0028's scope system). Codex cache hits
  are UNFILTERED (Codex tracks enablement in config.toml — TOML, not stdlib-parseable on the
  3.10 floor). One-var revert: `SKILL_CODEX_ROOTS=0` (default on) drops every Codex path + scope,
  byte-identical to the pre-dual-harness engine; a reindex prunes the codex points.
  `tests/conftest.py` gains an autouse fixture pinning the Codex seams to a temp path — imported
  only AFTER the env-pinning block, because this module reads its env seams at import time (an
  early import captures the operator's live catalog-roots config). Plugin-side companion:
  `enforcer.py` chain-hint scope mirror reads the codex scopes under the same flag. Pinned by
  the existing discovery suite running green on a machine with a populated `~/.codex`.
  **Requires re-copy into the stable venv
  (`pip install --force-reinstall --no-deps vendor/skill-search`) + a reindex to deploy.**

- **ZCode quintuple-harness discovery (ADR-0042, v0.34.0):** `skills_discovery.py` adds
  `ZCODE_*` roots — `~/.zcode/skills` (`zcode-personal`), `{cwd}/.zcode/skills` +
  `{cwd}/.agents/skills` (`zcode-project:{root}`), and ZCode plugin-cache paths
  (`zcode-plugin`) — folded into `SKILL_DIRS`, `_plugin_paths()`, `_scope_for()` (the
  `.zcode` check sits INSIDE the shared `/plugins/cache/` block BEFORE the generic
  `plugin` fallthrough, so a ZCode plugin skill can never land in Claude's scope), and
  `visible_scopes()`. ZCode plugin paths are REGISTRY-ENUMERATED (`_zcode_plugin_roots()`
  reads the LIST-shaped `~/.zcode/cli/plugins/installed_plugins.json` installPaths plus
  newest builtin version dirs, enablement-filtered via `~/.zcode/cli/config.json`
  `plugins.enabledPlugins`/`suppressedBuiltins`), never a wholesale cache glob — the
  append-only-cache pollution class. `~/.agents/skills` is deliberately NOT a root (it
  symlinks to `~/.claude/skills` on the reference machine and would dedup into
  `personal`; per-session invocability is the enforcer's twin check). One-var revert:
  `SKILL_ZCODE_ROOTS=0` (default on) drops every ZCode path + scope, byte-identical;
  a reindex prunes the zcode points. Plugin-side companions: `enforcer.py` zcode identity
  + twin tests + chain-hint scope mirror under the same flag; `auto_reindex._mcp_env()`
  forwards the flag defensively. **Requires re-copy into the stable venv
  (`pip install --force-reinstall --no-deps vendor/skill-search`) + a reindex to deploy.**

- **Durable-home default for `_LLM_TRIG_PATH` (v0.37.0, utterance-canonicalization):** `server.py`
  `_LLM_TRIG_PATH` default moves from `<cwd4>/eval/triggers.json` (never populated in deployed
  copies — the plugin-cache tree has no `eval/`) to `~/.claude/skill-concierge/triggers.json`, the
  operator-owned canonical corpus. Env `SKILL_TRIGGERS` still wins when set. The old default made a
  bare env-less `skill-search --reindex` silently rebuild the trigger layer WITHOUT utterances
  (pruning the layer); the durable-home default makes the bare path safe by construction. Mirrors
  the script-side defaults (`build_triggers.py`/`enrich_index.py`/`llm_triggers.py`/`flywheel.py`)
  and doctor's durable-home-first seam. **Requires re-copy into the stable venv
  (`pip install --force-reinstall --no-deps vendor/skill-search`) + a reindex to deploy.**

- **Blocklist query-time filter (ADR-0046, v0.39.0):** `server.py` adds `_BLOCKLIST_PATH`
  (seam `SKILL_CONCIERGE_BLOCKLIST`, default `~/.claude/skill-concierge/blocklist.json`) and
  `_blocked(name)` — read LIVE at each call because this server is long-lived (the hook
  processes are per-turn), so `blocklist.py` edits apply with no restart of the CLI and no
  reindex; absent file = empty = no-op; `SKILL_BLOCKLIST=0` is the shared kill-switch
  (guard + enforcer + engine). `search_skills` filters blocked rows from the fused results;
  `get_skill` refuses to serve a blocked skill's body (external-catalog deep pulls included —
  search-filtering without body-refusal would leak the skill through the other lane).
  Matching mirrors the guard/enforcer: exact entry, or a BARE entry catching every qualified
  twin (`origin:name`). INDEX-NEUTRAL by design — the blocklist never touches points, so
  unlike every patch above there is **no reindex step**; unblocking is instant and leaves
  the index untouched. **Requires re-copy into the stable venv
  (`pip install --force-reinstall --no-deps vendor/skill-search`) to deploy; long-lived MCP
  servers keep executing the old bytes until restarted (ADR-0018 class).**

The only non-code file added under `vendor/` beyond the upstream source is `eval/README-LOCAL.md`
(a local caveat note). If upstream changes, re-vendor from the same source and re-apply BOTH the
plugin-level customization layer and these engine patches.
