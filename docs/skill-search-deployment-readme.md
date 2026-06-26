# skill-search — Personal Deployment

Semantic, on-demand skill retrieval for Claude Code, deployed system-wide on this
machine with a Qdrant server backend and a multilingual embedder. This README
documents **what was built across the full arc** (study → trial → system-wide →
server+multilingual), the **running architecture**, and the **runbook** to operate,
maintain, and reverse it.

> Upstream: <https://github.com/sowhan/skill-search> (MIT, Sowhan Mohammed).
> This is a personal deployment + operations doc, not a fork of that repo.

---

## Table of Contents

- [Why this exists](#why-this-exists)
- [Results (measured on this machine)](#results-measured-on-this-machine)
- [How it works](#how-it-works)
- [This deployment — current state](#this-deployment--current-state)
- [Architecture of the running system](#architecture-of-the-running-system)
- [The arc & decision log](#the-arc--decision-log)
- [Runbook (operations)](#runbook-operations)
- [Configuration reference](#configuration-reference)
- [Maintenance](#maintenance)
- [Troubleshooting](#troubleshooting)
- [Reverse / uninstall](#reverse--uninstall)
- [Backups inventory](#backups-inventory)
- [File & path map](#file--path-map)

---

## Why this exists

Claude Code injects **name + description for every installed skill into context on
every turn** so it can decide which to use. With a large skill set that becomes a
recurring token tax, and because the native match is essentially name/description
keyword overlap, a skill whose name doesn't echo the user's words quietly never fires.

skill-search replaces that with a **vector retriever over the full skill
descriptions**. Skills are set to `name-only` (name stays visible and invocable, the
description leaves the per-turn budget), and an MCP tool returns just the few skills
that semantically match the task at hand.

This machine runs **507 skills** — squarely the "tail-scale" case where the payoff is
largest.

## Results (measured on this machine)

Counted with a real BPE tokenizer (`tiktoken cl100k_base`), 507 skills, modeled as
each appears in the native listing (`- name: description`):

| | Tokens injected / turn | % of 200K window |
|---|---:|---:|
| Native full listing (name + description) | **42,293** | 21.15% |
| `name-only` + skill-search | 3,314 | 1.66% |
| **Reclaimed, every turn** | **38,979** | **19.49%** |

~a fifth of the entire context window, back on every turn. Heaviest descriptions were
the `vn-*` skills (`vn-editor` 439 tok, `vn-author` 414, `vn-comm` 411).

**Keep-on adjustment:** the **21 core `ck:*` workflow/routing skills** + the **6 core
`vn-*` skills** (authoring + main report generators) are deliberately held `"on"`
(always-matched, no search round-trip); the other 59 `ck:*` and 6 `vn-*` domain-specific
skills are `name-only` (retrieved on demand). The 27 keep-ons cost ~3,292 tok/turn
(1.65%), so the **net saving is ~35,687 tok/turn (~17.8%)** — most of the full 38,979,
while the core lifecycle + core Vietnamese stack stay natively discoverable. (The 6
`vn-*` are description-heavy: `vn-editor`/`vn-author`/`vn-comm` ~410–440 tok each.)

**Retrieval quality** after the multilingual upgrade (ranking, not absolute score):

| Query | Top result |
|---|---|
| EN: "rewrite Vietnamese so it doesn't sound AI" | `vn-editor` #1 (was absent pre-upgrade) |
| VN: "gỡ giọng AI trong văn bản tiếng Việt" | `vn-editor` #1 — cross-lingual works |
| "create a new Claude Code skill" | `create-skill` #1 |
| "debug a hook in settings.json" | `hook-sync-cc-pi` #1 |

## How it works

Two pieces, **useless apart**:

1. **Budget override** — set ~all skills to `name-only` in `settings.local.json`. Frees
   the description budget. A tiny allowlist (the router skill) stays fully `"on"`.
2. **MCP retriever** — embeds full skill text into a vector store; `search_skills`
   returns the top-k relevant skills; Claude invokes them **by name** (works at
   `name-only`).

Skip the override and you pay the native tax *and* the retriever. Both are required.

The bridge is the **router skill** (`~/.claude/skills/skill-search/SKILL.md`): a tiny
always-`"on"` skill whose only job is "on a new task, call `search_skills` first, then
invoke the 2–4 relevant results by name." It's the always-visible seed that makes the
indirection fire.

## This deployment — current state

| Aspect | Value |
|---|---|
| Package | `skill-search-mcp` 0.1.0 via `pipx` on **Python 3.12.11** (console scripts `skill-search`, `skill-search-overrides`) |
| Vector store | **Qdrant server** (Docker container `skill-search-qdrant`, image `qdrant/qdrant` 1.18.2) at `http://localhost:6333` |
| Embedder | **`fastembed`** (in-process, no daemon) · `sentence-transformers/paraphrase-multilingual-mpnet-base-v2` · **768-dim** |
| Index | 508 points (507 skills + router), `health` ok, 0 dark / 0 stale |
| Budget override | **global** `~/.claude/settings.json` (`skillOverrides`) → **477 `name-only`, 31 `on`** (20 core `ck:*` + 6 core `vn-*` + 4 discipline guardrails + `skill-search`) |
| MCP scope | **user** (`~/.claude.json` → `mcpServers.skill-search`), env points to server + multilingual model |
| Router skill | `~/.claude/skills/skill-search/SKILL.md` (global, always-on) |

Discovery scans: `~/.claude/skills/*/SKILL.md` (personal), `<cwd>/.claude/skills/*`
(project), and `~/.claude/plugins/cache/**/skills/*/SKILL.md` (installed plugin skills,
namespaced `plugin:skill`).

## Architecture of the running system

```
 New task in Claude Code
        │
        ▼
 router skill (always "on")  ──►  calls MCP tool: search_skills(query)
                                          │
                                          ▼
                              skill-search MCP server (stdio, user scope)
                                  │                         │
                       embed query (fastembed,      query top-k vectors
                       mpnet 768-dim, in-process)   ──────────────► Qdrant server
                                  │                         (Docker :6333)
                                  ▼
                       returns top-k {name, command, description, score}
                                  │
                                  ▼
                  Claude invokes 2–4 relevant skills BY NAME
                  (they are name-only → name stays invocable)
```

Two persistent processes matter: the **MCP server** (spawned per Claude session) and
the **Qdrant container** (shared, long-lived). Because the store is a *server* (not the
embedded single-process file), multiple concurrent Claude sessions can all query it.

## The arc & decision log

Why the deployment looks the way it does — kept because these are the decisions easiest
to forget.

| Step | Decision | Why |
|---|---|---|
| Study | Read full source (~1,068 LOC) before acting | Briefing must cite real code, not the README |
| Install | `pipx --python python3.12` from source | Repo needs ≥3.10; macOS system Python is 3.9; pipx default (3.14) risks missing `onnxruntime`/`fastembed` wheels |
| First trial | **project-scope** overrides + **embedded** Qdrant | Contained, reversible — prove value before touching the whole system |
| Promote | overrides `--global` + MCP `--scope user` | "System-wide" — applies in every project, not just the workbench |
| **Concurrency fix** | embedded → **Qdrant server (Docker)** | Embedded Qdrant locks its dir to ONE process; concurrent sessions would make the 2nd+ session's search go dark |
| **Quality fix** | `bge-small-en` → **multilingual mpnet (fastembed)**, NOT Ollama | English-only embedder missed Vietnamese-described skills. Chose fastembed-multilingual over the Ollama `embeddinggemma` tier to avoid a *second* always-on daemon — same multilingual win, one less failure point. `mpnet-base-v2` is symmetric (no query/passage prefixes) → clean drop-in for the repo's raw-text embedding. |

## Runbook (operations)

### Normal use
After a Claude Code restart, it just works: the router skill calls `search_skills`,
relevant skills come back ranked, Claude invokes them by name. Nothing to do per-turn.

**Prerequisite every session:** the Qdrant container must be running (Docker/OrbStack
up). If it's down, search returns nothing → at `name-only`, skills are invisible.

### After adding / editing / removing skills
The index must be refreshed or new skills aren't searchable.

- **Preferred — from inside Claude:** call the **`reindex` MCP tool** (incremental). It
  runs in the server process, which already has the right env baked in.
- **From the shell** (must export env, or it hits the wrong store):
  ```bash
  export SKILL_QDRANT_URL=http://localhost:6333
  export SKILL_EMBED_BACKEND=fastembed
  export SKILL_EMBED_MODEL=sentence-transformers/paraphrase-multilingual-mpnet-base-v2
  skill-search --reindex     # incremental; --rebuild for a full clean rebuild
  ```
Drift is also surfaced automatically: `search_skills` appends a `warning` when disk
changed since the last index.

### Health check
```bash
export SKILL_QDRANT_URL=http://localhost:6333 SKILL_EMBED_BACKEND=fastembed \
       SKILL_EMBED_MODEL=sentence-transformers/paraphrase-multilingual-mpnet-base-v2
skill-search --health      # exits non-zero when degraded (cron/CI-safe)
```
Reports embedder + Qdrant reachability, indexed-vs-disk counts, and lists **dark**
(on-disk but unindexed) and **stale** (indexed but deleted) skills.

### Reboot behavior
The container is `--restart unless-stopped`, so it returns after a reboot **provided the
Docker provider (OrbStack) auto-starts**. Verify after a reboot:
```bash
docker ps --filter name=skill-search-qdrant      # should show "Up"
orb start                                         # if OrbStack isn't running
```

### Re-measure the token savings
```bash
~/.local/pipx/venvs/skill-search-mcp/bin/python \
  <path-to-source>/scripts/measure_tokens.py      # needs tiktoken (injected)
```

## Configuration reference

All config is env-var overridable (`SKILL_*`). The live values are baked into the MCP
registration (`~/.claude.json` → `mcpServers.skill-search.env`).

| Env var | This deployment | Meaning |
|---|---|---|
| `SKILL_QDRANT_URL` | `http://localhost:6333` | Set → Qdrant **server** mode (unset → embedded file) |
| `SKILL_EMBED_BACKEND` | `fastembed` | `fastembed` (in-process ONNX) or `ollama` |
| `SKILL_EMBED_MODEL` | `sentence-transformers/paraphrase-multilingual-mpnet-base-v2` | Embedding model (768-dim) |
| `SKILL_TOP_K` | `6` (default) | Results returned by `search_skills` |
| `SKILL_COLLECTION` | `claude_skills` (default) | Qdrant collection name |
| `SKILL_QDRANT_PATH` | _unused_ | Embedded store location (only when URL unset) |

### Config scopes

| Concern | Scope | File |
|---|---|---|
| Budget overrides (`skillOverrides`) | global/user | `~/.claude/settings.json` (moved here from `settings.local.json` — single global source) |
| Budget overrides (trial leftover) | project | `skills-dev/.claude/settings.local.json` (redundant with global; identical values — safe to remove for single-source) |
| MCP registration | user | `~/.claude.json` → `mcpServers.skill-search` |
| Router skill | global | `~/.claude/skills/skill-search/SKILL.md` |

## Maintenance

**Keep-on allowlist (always-`on`).** Currently `skill-search` + the **20 core `ck:*`
workflow/routing skills**: `plan`, `cook`, `fix`, `debug`, `code-review`, `test`,
`ship`, `scout`, `research`, `brainstorm`, `ask`, `predict`, `scenario`,
`sequential-thinking`, `problem-solving`, `context-engineering`, `project-management`,
`team`, `loop`, `git`. (`ck:review-pr` demoted — `ck:code-review` covers review.) The
other 60 `ck:*` skills are domain-specific → `name-only`. Plus **4 self-triggered
discipline guardrails**: `verify-as-claimed` (verify completed NON-code work with
evidence), `Verification Before Completion` (run verification + confirm output before
claiming code/commands done), `requirements-clarity` (clarify ambiguous asks via
Why/Simpler before building), and `come-clean` (self-correct a caught rule-dodge). All
kept on because the user never *asks* for them by name, so semantic search can't surface
them at the moment they're needed — they must be visible to self-fire.

> **Why grill-me / grill-with-docs are NOT here:** they're *user-triggered* (their
> trigger literally is "grill me" / "stress-test this"), so `search_skills` surfaces
> them on demand — always-on would spend budget for no self-trigger benefit. The bar for
> a keep-on guardrail is: the model must self-fire it because your words won't route to it.

Plus the **6 core `vn-*` skills**: `vn-author`, `vn-editor`, `vn-comm`, `vn-bctt-report`,
`vn-canu-reporting`, `vn-deep-dive-report`. The other 6 `vn-*` (format transformers +
narrow tools: `vn-ares-research-report`, `vn-b3-format-report`, `vn-baleba-report`,
`vn-bctt-concise`, `vn-news-coverage-tracker`, `vn-news-signals`) stay `name-only`.

This set is **hand-maintained directly in `~/.claude/settings.json`** (`skillOverrides`),
flipping a key between `"on"` and `"name-only"`. Every kept-on skill pays its full
description tax again (the 27 keep-ons ≈ 3,292 tok/turn), so keep the list intentional.

> ⚠ **Do NOT re-run `skill-search-overrides` to manage this.** That tool (a) writes
> `~/.claude/settings.local.json`, re-introducing the split we collapsed into
> `settings.json`, and (b) only preserves its own default keep-on (`skill-search`,
> `skill-finder`) — it would silently revert the 80 `ck:*` back to `name-only`. Edit
> `settings.json` by hand for keep-on changes. The tool is fine for the *initial* flip
> on a fresh machine only.

**Swap the embedder.** Changing the model changes the vector dimension; an existing
collection can't take a different dim. The build guards this (`reindex` raises "run
`--rebuild`"; `health` flags the mismatch). To switch: update
`SKILL_EMBED_MODEL` in the MCP env (re-register), then `skill-search --rebuild` with the
new env. Multilingual alternatives in this `fastembed` build: `multilingual-e5-large`
(1024-dim, higher ceiling but expects query/passage prefixes the code doesn't add),
`paraphrase-multilingual-MiniLM-L12-v2` (384-dim, lighter).

**Switch to the Ollama tier** (if ever wanted): install Ollama, `ollama pull
embeddinggemma`, set `SKILL_EMBED_BACKEND=ollama SKILL_EMBED_MODEL=embeddinggemma`, and
rebuild. Cost: a second always-on daemon.

**Revert to embedded store** (drop the container dependency, lose concurrency): remove
`SKILL_QDRANT_URL` from the MCP env, re-register, `skill-search --rebuild`.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `claude mcp list` shows `✘ Failed to connect` while a session is live (embedded mode only) | `list` spawns a 2nd probe that can't grab the embedded single-process lock | False negative; verify with `/mcp` inside a session. N/A on the server tier. |
| `RuntimeError: Storage folder ... already accessed by another instance` | Embedded Qdrant is single-process | This is why we run the **server**; don't point CLI at the embedded store while a session MCP holds it |
| Search returns nothing / skills invisible | Qdrant container down | `docker ps`; `orb start`; `docker start skill-search-qdrant` |
| CLI `--reindex` wrote to the wrong store / wrong dim | Env not exported for the CLI | Export `SKILL_QDRANT_URL` + `SKILL_EMBED_MODEL`, or use the `reindex` MCP tool |
| `embedding dimension changed (X -> Y)` | Embedder swapped under an existing collection | `skill-search --rebuild` |
| `pipx install` fails on wheels | Python too new/old | Pin `--python python3.12` |
| Benign `ImportError: Python is likely shutting down` on CLI exit | Qdrant client teardown noise | Ignore; the result prints before it |
| New skill not found by search | Index stale | `reindex` (MCP tool) or CLI `--reindex` with env |

## Reverse / uninstall

Layered — undo only what you want. **Restart Claude Code after config changes.**

```bash
# 1. Budget flip (restore full native listing)
cp ~/.claude/settings.json.bak-skillsearch-260626-002529 \
   ~/.claude/settings.json                                         # global: restore pre-override settings.json
cp skills-dev/.claude/settings.local.json.bak-pre-skillsearch \
   skills-dev/.claude/settings.local.json                          # project trial leftover

# 2. MCP registration (restore pre-change ~/.claude.json)
cp ~/.claude.json.bak-skillsearch-server-260625-233755 ~/.claude.json
#   or unregister directly:
claude mcp remove skill-search -s user

# 3. Qdrant server
docker rm -f skill-search-qdrant
rm -rf ~/.cache/skill-search/qdrant-server                         # server data (optional)

# 4. Router skill + embedded index + package
rm -rf ~/.claude/skills/skill-search ~/.cache/skill-search/qdrant
pipx uninstall skill-search-mcp
```

## Backups inventory

| Backup | Of | When |
|---|---|---|
| `skills-dev/.claude/settings.local.json.bak-pre-skillsearch` | project settings before first override | trial |
| `~/.claude.json.bak-skillsearch-260625-232335` | full Claude config before user-scope MCP | system-wide promotion |
| `~/.claude.json.bak-skillsearch-server-260625-233755` | full Claude config before server-tier MCP env | server+multilingual upgrade |
| `~/.claude/settings.json.bak-skillsearch-260626-002529` | global settings.json before overrides moved in | settings.json relocation |
| `~/.claude/settings.local.json.bak-skillsearch-260626-002529` | global settings.local.json before overrides removed | settings.json relocation |
| `skills-dev/.claude/settings.local.json.bak-skilloverrides-removed-*` | project settings before redundant overrides stripped | single-source cleanup |
| `~/.claude/settings.json.bak-ckon-260626-002831` | settings.json before 80 `ck:*` flipped to `on` | ck keep-on |
| `~/.claude/settings.json.bak-ckcore-260626-003339` | settings.json before narrowing to 21 core `ck:*` | ck core trim |
| `~/.claude/settings.json.bak-vncore-260626-003723` | settings.json before flipping 6 core `vn-*` to `on` | vn core keep-on |
| `~/.claude/settings.json.bak-tweak-*` | settings.json before per-skill keep-on tweaks (e.g. `review-pr` demote, `verify-as-claimed` promote) | incremental tuning |

(`~/.claude.json` is ~112 KB and holds far more than MCP config — restoring a backup
rolls back everything in it to that timestamp. Prefer `claude mcp remove/add` for
targeted MCP changes.)

## File & path map

| Path | Role |
|---|---|
| `~/.local/bin/skill-search`, `skill-search-overrides` | console scripts (pipx) |
| `~/.local/pipx/venvs/skill-search-mcp/` | the pipx venv (Python 3.12) |
| `~/.cache/skill-search/qdrant-server/` | Qdrant **server** data volume (active) |
| `~/.cache/skill-search/qdrant/` | old **embedded** index (orphaned; safe to delete) |
| `~/.cache/skill-search/index_meta.json` | drift-detection manifest |
| `~/.claude/skills/skill-search/SKILL.md` | router skill |
| `~/.claude/settings.json` | global `skillOverrides` (+ all other user settings) |
| `~/.claude.json` | user-scope MCP registration (+ much else) |

### Upstream source files (reference)

| File | Role |
|---|---|
| `skill_search/server.py` | MCP server: `search_skills`, `get_skill`, `reindex`, `health` |
| `skill_search/skills_discovery.py` | single source of truth for skill discovery (both halves) |
| `skill_search/generate_overrides.py` | writes `name-only` overrides (`skill-search-overrides`) |
| `scripts/measure_tokens.py` | token-savings measurement (tiktoken) |
| `eval/run_eval.py` | recall@k eval harness |

---

## Open items

- ✅ **Source durability — RESOLVED:** repointed to PyPI via `pipx uninstall` +
  `pipx install --python python3.12 skill-search-mcp`. `pipx_metadata.json`
  `package_or_url` is now `skill-search-mcp` (was the session-temp clone path). Note:
  plain `pipx install --force <name>` does NOT repoint an existing local-path venv — it
  reuses the recorded source; the uninstall+install is required.
- ✅ **OrbStack auto-start — CONFIRMED:** OrbStack is a macOS login item, so the Qdrant
  container returns on boot.
- ✅ **Restart + live verification — DONE:** post-restart, in-session MCP `health` ok,
  `search_skills` returns (Vietnamese query → `vn-editor` #1), `get_skill` deep-pull works.
- **No custom recall eval yet:** retrieval validated by eyeballing real queries. A
  labeled `query→skill` set for this machine's skills would give a real recall@k number.
  (Still open — genuinely deferred.)
