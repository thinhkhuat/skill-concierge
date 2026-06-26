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

The only file added under `vendor/` beyond the upstream source is `eval/README-LOCAL.md` (a
local caveat note); the engine code is untouched.

If upstream changes, re-vendor from the same source and re-apply the customization layer.
