# Session Handoff — skill-search: study → system-wide deploy (Qdrant server + multilingual) + keep-on tuning

## Where it started
User asked to study `github.com/sowhan/skill-search` and learn its novel ideas. It escalated into a full personal deployment against the operator's ~507-skill catalogue: trial it, install system-wide, then optimize/personalize (server tier, multilingual embedder, curated always-on set). The deployment is system-global config (not a code project); the documentation artifacts live in `skills-dev/`.

## Decisions locked + what shipped
- **Studied source** (~1,068 LOC), briefed novel ideas: name-only + retriever pair, single-source discovery, fail-loud staleness, incremental content-hash reindex, embedder-swap guard, router skill.
- **Package install** — `pipx` on Python 3.12, **repointed to PyPI** (`skill-search-mcp` 0.1.0). Console scripts `skill-search`, `skill-search-overrides` at `~/.local/bin/`. tiktoken injected. (Gotcha learned: `pipx install --force <name>` does NOT repoint an existing local-path venv; needs `uninstall`+`install`.)
- **Vector store** — upgraded embedded → **Qdrant server** (Docker container `skill-search-qdrant`, image `qdrant/qdrant` 1.18.2, ports 6333/6334, `--restart unless-stopped`, volume `~/.cache/skill-search/qdrant-server`). Kills the embedded single-process lock → concurrent sessions OK.
- **Embedder** — upgraded `bge-small-en` (384-dim, English-only) → **`sentence-transformers/paraphrase-multilingual-mpnet-base-v2`** (768-dim, in-process fastembed, NO Ollama daemon). Fixed the EN-query→VN-skill miss (`vn-editor` now #1 for Vietnamese queries). Index = 508 skills.
- **MCP** — registered **user scope** in `~/.claude.json` (`mcpServers.skill-search`) with env `SKILL_QDRANT_URL=http://localhost:6333`, `SKILL_EMBED_BACKEND=fastembed`, `SKILL_EMBED_MODEL=...mpnet-base-v2`.
- **Router skill** — installed global at `~/.claude/skills/skill-search/SKILL.md`.
- **Budget flip** — `skillOverrides` consolidated into **`~/.claude/settings.json`** (global single source; moved off `settings.local.json` per user). Final: **31 `on` / 477 `name-only`**. On = 20 core `ck:*` + 6 core `vn-*` (author/editor/comm/bctt-report/canu-reporting/deep-dive-report) + `skill-search` + 4 guardrails (`verify-as-claimed`, `come-clean`, `requirements-clarity`, `Verification Before Completion`). `ck:review-pr` demoted; `vn-ares-research-report`, `grill-me`, `grill-with-docs` held name-only (user-triggered ⇒ search surfaces them).
- **Token result** — native listing 42,293 tok/turn (21.15% of 200K) → name-only; net reclaim **~37,823 tok/turn (~18.9%)** after the 27 keep-ons.
- **Live-verified post-restart** — in-session MCP `health` ok, `search_skills` (VN query → `vn-editor` #1 @ 0.70), `get_skill` deep-pull works.
- **Ops README** authored + kept in sync every change: `docs/skill-search-deployment-readme.md`.

## Key files for next session

| File | Why |
|------|-----|
| `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skills-dev/docs/skill-search-deployment-readme.md` | THE ops doc — full state, arc/decision log, runbook, config reference, troubleshooting, reverse/uninstall, backups, path map. Read first. |
| `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skills-dev/plans/reports/skill-search-trial-setup-260625-2233-report.md` | Chronological setup report (trial → system-wide → server+multilingual). |
| `/Users/thinhkhuat/.claude/settings.json` | Global `skillOverrides` (31 on / 477 name-only). The keep-on allowlist is hand-maintained here — do NOT use `skill-search-overrides` to edit it (writes settings.local.json, reverts keep-ons). |
| `/Users/thinhkhuat/.claude.json` | `mcpServers.skill-search` (user scope) + env. |
| `/Users/thinhkhuat/.claude/skills/skill-search/SKILL.md` | Router skill (always-on entry point). |

- Backups (rollback points): `~/.claude.json.bak-skillsearch-260625-232335`, `~/.claude.json.bak-skillsearch-server-260625-233755`, `~/.claude/settings.json.bak-*` (skillsearch / ckon / ckcore / vncore / tweak), `skills-dev/.claude/settings.local.json.bak-pre-skillsearch`.
- Memory touched: none (no file-memory or agentmemory lessons written this session).
- Source clone (now disposable after PyPI repoint): `/Users/thinhkhuat/.tmp/claude-501/-Users-thinhkhuat-in-PROD-MY-WORKBENCH-skills-dev/2cbe2e43-3372-49eb-b17c-59e433ef00c9/scratchpad/skill-search`.

## Running state
- Background processes: none (no `run_in_background` shells/subagents spawned).
- Dev servers / ports: **Qdrant** container `skill-search-qdrant` on `localhost:6333` (REST) + `6334` (gRPC), `--restart unless-stopped` via Docker/OrbStack (OrbStack is a login item). Stop: `docker stop skill-search-qdrant`. The skill-search MCP stdio server is spawned/managed per Claude session by Claude Code, not a manual process.
- Open worktrees / branches: none.

## Verification — how to confirm things still work
- In-session: call `mcp__skill-search__health` → `status: ok`, store `http://localhost:6333`, dim 768, indexed 508.
- CLI (needs env): `export SKILL_QDRANT_URL=http://localhost:6333 SKILL_EMBED_BACKEND=fastembed SKILL_EMBED_MODEL="sentence-transformers/paraphrase-multilingual-mpnet-base-v2"; skill-search --health` → ok.
- `docker ps --filter name=skill-search-qdrant` → `Up`.
- Override counts: `python3 -c "import json,os;from collections import Counter;print(Counter(json.load(open(os.path.expanduser('~/.claude/settings.json')))['skillOverrides'].values()))"` → `{'name-only':477,'on':31}`.
- Install origin: `python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/.local/pipx/venvs/skill-search-mcp/pipx_metadata.json')))['main_package']['package_or_url'])"` → `skill-search-mcp`.
- After adding/editing skills: call `mcp__skill-search__reindex` (env baked into the MCP) — or CLI `skill-search --reindex` with the env above. A cosmetic `degraded: disk changed since last index` after reloads/restarts clears with one incremental reindex (0 re-embedded).

## Deferred + open questions
- Deferred: **custom recall@k eval** — a labeled `query→skill` set for this machine's skills (only eyeball-validated so far). Needs the user's judgment on expected matches.
- Open: **`research-grounding`** promotion (recommended HOLD — heavy/tool-specific) and **`grill-me`** always-on (held; user could flip if they want the model to offer grilling unprompted). `grill-with-docs` recommended stay name-only regardless.

## Pick up here
Deployment is live and verified — next agent's most likely task is either building the optional labeled recall@k eval for a hard quality number, or simply using the system; nothing is blocking.
