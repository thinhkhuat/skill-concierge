# skill-search — trial setup & evaluation (260625)

Semantic on-demand skill retrieval for Claude Code. Replaces the native per-turn
skill-listing token tax with a vector retriever; skills set to `name-only` (name
stays invocable, description leaves the budget). Source: https://github.com/sowhan/skill-search

## The prize (measured on YOUR set, real BPE tokenizer)

| | tokens/turn | % of 200K |
|---|---:|---:|
| native listing (name+desc) | 42,293 | 21.15% |
| name-only | 3,314 | 1.66% |
| **saved/turn** | **38,979** | **19.49%** |

507 skills. Heaviest descriptions: vn-editor 439, vn-author 414, vn-comm 411 tok.
~6× the saving of the author's 117-skill reference case — extreme tail-scale.

## What was installed

- **pkg**: `pipx install --python python3.12 .` from cloned source → console scripts
  `skill-search`, `skill-search-overrides` at `~/.local/bin/`. tiktoken injected.
- **index**: embedded Qdrant + fastembed `bge-small-en-v1.5` (384-dim) at
  `~/.cache/skill-search/`. Full build 37s (incl. model dl); incremental skip ~3.5s.
  508 points (507 skills + router). `health` → ok, 0 dark, 0 stale.
- **MCP**: registered stdio `skill-search`, **local/project scope** in
  `~/.claude.json` (project: skills-dev). `claude mcp list` → ✔ Connected.
- **router skill**: `~/.claude/skills/skill-search/SKILL.md` (global, always-on).
- **budget flip**: `skillOverrides` in `skills-dev/.claude/settings.local.json`
  → 507 name-only, 1 on (skill-search). Backup: `settings.local.json.bak-pre-skillsearch`.
  **Project scope only** — does NOT touch other projects yet.

## Retrieval quality (12 real-domain queries, eyeballed)

~11/12 nail the right skill top-3: VN gov briefing, vn-comm, create-skill,
hook debug, recall, supabase, code-review, PDF→md, news+FB all ✓.
**Soft spot**: English query → Vietnamese-described skill (vn-editor missed for
"rewrite Vietnamese so it doesn't sound AI") — `bge-small-en` is English-only.

## ⚠ Requires a Claude Code RESTART to take full effect

- MCP servers load at session start → `search_skills` not callable until restart.
- skillOverrides shrink the listing on prefix rebuild / new session.
- Current session already cached the full listing; nothing breaks (names stay
  invocable, skill-first hook still suggests), but the win/discovery path is
  post-restart.

## Personalization levers (your stated interest)

1. **Multilingual embedder** (fixes the VN soft spot): `docker run -p 6333:6333
   qdrant/qdrant`; install Ollama + `ollama pull embeddinggemma`;
   `export SKILL_EMBED_BACKEND=ollama SKILL_QDRANT_URL=http://localhost:6333`;
   `skill-search --rebuild`. Pin as `--env` on `claude mcp add`. embeddinggemma
   is multilingual (768-dim) → English queries match Vietnamese skills.
2. **Go system-wide**: `skill-search-overrides --global` (writes
   `~/.claude/settings.local.json`) + re-register MCP `--scope user`.
3. **Keep more skills always-on**: `skill-search-overrides --keep <a> <b>` (e.g.
   workflow/hook skills you want auto-matched without a search round-trip).
4. **Recall tuning**: `SKILL_TOP_K` (default 6) up if recall feels thin.
5. **Custom eval**: build a labeled `*.jsonl` of YOUR query→skill pairs and run
   `python eval/run_eval.py yours.jsonl` for a real recall@k on your set.

## Update 260625-2323 — promoted SYSTEM-WIDE

- **global overrides**: `skill-search-overrides --global` → `~/.claude/settings.local.json`
  (fresh file, only key: skillOverrides) = 507 name-only + 1 on (skill-search).
- **MCP moved to user scope**: removed project/local reg; `claude mcp add --scope user`
  → top-level `mcpServers.skill-search` in `~/.claude.json` (embedded tier, env {}).
- **backups**: `~/.claude.json.bak-skillsearch-260625-232335` (111.7K, valid),
  project `settings.local.json.bak-pre-skillsearch` (216B).
- Project-scope override in skills-dev is now redundant (global covers it) — harmless,
  identical values; revert it if you want a single source.
- **⚠ concurrency**: embedded Qdrant is single-process (`portalocker BlockingIOError`
  when a 2nd instance opens the store). One Claude session = fine. CONCURRENT sessions
  across projects (true system-wide) → 2nd+ session's search_skills goes dark. Robust
  fix = Qdrant **server tier** (Docker): `docker run -d -p 6333:6333 qdrant/qdrant`,
  re-add MCP with `--env SKILL_QDRANT_URL=http://localhost:6333`, `skill-search --rebuild`.
- `claude mcp list` shows "✘ Failed" while a session's embedded server holds the lock —
  false negative (the probe is a 2nd instance). Verify after restart instead.

## Update 260625-2336 — Qdrant SERVER tier + MULTILINGUAL embedder

Fixes both the concurrency lock AND the English-only retrieval miss.

- **Qdrant server**: Docker (OrbStack provider) container `skill-search-qdrant`,
  `qdrant/qdrant` 1.18.2, ports 6333/6334, `--restart unless-stopped`, volume
  `~/.cache/skill-search/qdrant-server`. Kills the single-process embedded lock →
  concurrent Claude sessions OK.
- **Multilingual embedder**: chose `fastembed` (in-process, NO extra daemon) with
  `sentence-transformers/paraphrase-multilingual-mpnet-base-v2` (768-dim) instead of
  the Ollama tier — same multilingual win, one fewer always-on service. Symmetric
  model (no query/passage prefixes) → clean drop-in for the repo's raw-text embedding.
- **Index**: rebuilt into the server, 508 skills @ 768-dim (2m44s incl. model dl).
  health → ok, store http://localhost:6333, dim 768, 0 dark/stale.
- **MCP**: user-scope re-registered with `-e SKILL_QDRANT_URL=http://localhost:6333
  -e SKILL_EMBED_BACKEND=fastembed -e SKILL_EMBED_MODEL=...mpnet-base-v2`.
  Verified in `~/.claude.json` mcpServers.skill-search.env.
- **backup**: `~/.claude.json.bak-skillsearch-server-260625-233755`.

**Validation (retrieval, env-set CLI trial):**
- EN→VN "rewrite Vietnamese so it doesn't sound AI" → vn-editor now **#1** (0.647);
  was absent from top-6 under bge-small-en.
- VN-language "gỡ giọng AI trong văn bản tiếng Việt" → vn-editor **#1** (0.700) —
  true cross-lingual retrieval works now.
- VN gov-report / casual queries → correct vn-* clusters. EN queries: no regression
  (create-skill, hook-sync-cc-pi, supabase all still top).
- Note: mpnet score scale is lower/compressed vs bge — non-comparable across models;
  ranking is what matters.

**Operational gotchas (server tier):**
- Qdrant container MUST be running (Docker/OrbStack up) or search → dark → at
  name-only, skills invisible. `--restart unless-stopped` survives reboots IF the
  Docker provider auto-starts.
- **CLI `--reindex`/`--rebuild` now need the env** (`SKILL_QDRANT_URL`,
  `SKILL_EMBED_MODEL`) exported, else they hit the default embedded+bge store. Prefer
  the **`reindex` MCP tool** (runs in the server process, env already baked in).
- Old embedded index `~/.cache/skill-search/qdrant` (bge-small, 384-dim) is now
  orphaned + still lock-held by the pre-restart session MCP — harmless; `rm -rf` it
  after restart if you want.

## Reverse / uninstall

Server-tier reversal:
```
cp ~/.claude.json.bak-skillsearch-server-260625-233755 ~/.claude.json   # restore MCP env
docker rm -f skill-search-qdrant                                        # stop+remove qdrant
rm -rf ~/.cache/skill-search/qdrant-server                              # server data (optional)
```

System-wide reversal:
```
cp ~/.claude.json.bak-skillsearch-260625-232335 ~/.claude.json   # restore MCP registry
rm ~/.claude/settings.local.json                                 # drop global overrides (was fresh)
```

Original (project-scope) reverse:

```
cp .claude/settings.local.json.bak-pre-skillsearch .claude/settings.local.json   # undo budget flip
claude mcp remove skill-search                                                    # unregister
rm -rf ~/.claude/skills/skill-search ~/.cache/skill-search                        # router + index
pipx uninstall skill-search-mcp
```

## Notes / open

- Source installed from scratchpad (session-temp). For durable updates:
  `pipx install skill-search-mcp` from PyPI instead.
- Index built with cwd=skills-dev; launching `claude` from another project may
  show a transient staleness warning for project-scoped skills (self-heals on reindex).
- Re-run `skill-search --reindex` after adding/editing skills (incremental, cheap).
- Benign `ImportError: Python is likely shutting down` on CLI exit = Qdrant
  client teardown noise, not a failure.
