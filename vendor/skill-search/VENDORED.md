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
`fastembed`, `requests`) are NOT vendored — the setup step installs them into a
plugin-local venv (`vendor/.venv/`).

## Local customizations (layered at the plugin level, NOT changes to this source)
- **Embedder:** `sentence-transformers/paraphrase-multilingual-mpnet-base-v2` (768-dim,
  multilingual) instead of the upstream default `bge-small-en` — fixes EN-query→VN-skill misses.
- **Vector store:** Qdrant **server** tier (Docker `skill-search-qdrant` @ localhost:6333),
  not the embedded single-process store — allows concurrent Claude sessions.
- **Budget overrides:** curated keep-on set written to `~/.claude/settings.json` (global
  single source). NOTE: do **not** run upstream `skill-search-overrides` — it writes
  `settings.local.json` and reverts the hand-curated keep-on allowlist (see deployment readme).
- These are applied via the plugin's own `.mcp.json` env + setup/override-policy (next build
  slice), keeping this vendored source unmodified for clean upstream diffs.

If upstream changes, re-vendor from the same source and re-apply the customization layer.
