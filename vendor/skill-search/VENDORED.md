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

The only non-code file added under `vendor/` beyond the upstream source is `eval/README-LOCAL.md`
(a local caveat note). If upstream changes, re-vendor from the same source and re-apply BOTH the
plugin-level customization layer and these engine patches.
