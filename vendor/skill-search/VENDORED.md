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
at `~/.local/share/skill-concierge/venv` (outside the plugin cache, so it survives reinstalls
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

The only non-code file added under `vendor/` beyond the upstream source is `eval/README-LOCAL.md`
(a local caveat note). If upstream changes, re-vendor from the same source and re-apply BOTH the
plugin-level customization layer and these engine patches.
