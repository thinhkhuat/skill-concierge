# ADR-0028 — Multi-session index scoping + installed/enabled plugin filter

Status: Accepted (2026-07-09)
Relates to: ADR-0001 (index model-invocable skills only — this extends "invocable" to mean *by this
session*), ADR-0018 (self-healing launcher / stale-engine trap — the venv is a copy install, so any
engine change needs a re-copy + a reindex from a fresh process), ADR-0024 (staleness detector:
content, not mtime — the manifest this ADR re-keys), ADR-0026 (the utterance layer whose prompt is
rewritten here). Source: `plans/260709-1310-skill-concierge-multi-session-index-split-brain/`.

## Context

Claude Code spawns **one `skill-search` MCP server per session**. All of them read and write a single
Qdrant collection (`claude_skills`). Meanwhile `skills_discovery.SKILL_DIRS[1]` is
`Path.cwd()/.claude/skills` — evaluated at import, so it differs per session.

Observed live on 2026-07-09, four concurrent sessions:

| MCP pid | Session CWD | Project skills | Its view |
|---|---|---|---|
| 51626 | `in-PROD/MY-WORKBENCH` | 54 | 552 |
| 476 | `LANDING_ZONE/CONTENT-HUB/Content-Hub` | 0 | 548 |
| 34460 | `MY-WORKBENCH/skill-concierge` | 0 | 548 |
| 97268 | `MY-WORKBENCH/skill-concierge` | 0 | 548 |

`build_index()` pruned with `removed = [pid for pid in existing if pid not in desired]` — no notion of
ownership. So a reindex from any session deleted whatever another session's project contributed.
`logs/auto-reindex.log` shows the flip-flop, ending in a run that reported `"deleted": 32` and wiped
the project points a reindex four minutes earlier had written. Last writer wins, forever, on a
30-minute hook throttle.

Three further defects surfaced from the same root — *the index describes a world nobody actually
lives in*:

1. **`PLUGIN_GLOB` indexed every cached plugin version and every disabled plugin.** The cache is
   append-only. 587 `SKILL.md` collapsed to 256 unique `(plugin, skill)` pairs, **89 served by more
   than one version**, resolved by first-writer-wins over arbitrary glob order. `skill-concierge` had
   **31 versions** cached, and the live index scored `skill-concierge:doctor` and `:skill-search`
   against their **0.3.0** descriptions while **0.18.1** was installed. `superpowers:*` was being
   recommended while `enabledPlugins` had it `false` — a skill Claude Code cannot invoke.

2. **`health()` diffed a CWD-scoped disk view against a globally shared index**, so it reported another
   project's skills as `dark_skills` ("on disk but not indexed — run reindex()"). That false alarm is
   precisely what invites the destructive reindex in (0).

3. **The index manifest was one global file storing a CWD-scoped signature** (`_disk_signature()`), so
   sessions overwrote each other and every one of them reported a permanent
   `skills changed on disk since last index`.

Precedent: v0.16.1 already closed this bug class on the **env** axis — `auto_reindex._mcp_env()`
forwards the engine flags, "without it, a background reindex rebuilt at engine defaults and pruned the
utterance points every run" (`AGENTS.md`). The concurrency hazard was patched once and left
structurally open on the **CWD** axis.

## Decision

**Every point carries the scope that owns it**, and no process may act outside the scopes it can see.

- `skills_discovery._scope_for(path)` → `personal` | `plugin` | `project:<root>`;
  `visible_scopes()` names what this process owns.
- `build_index` writes `scope` into every point payload (base and trigger).
- `_existing_points()` returns `(content_hash, scope)`. `_point_changed()` re-embeds when the text
  **or the scope** changed — the scope arm is what migrates legacy scope-less points; a description
  that never changed would otherwise keep a scope-less payload forever and be filtered out of every
  search.
- `_prunable()` deletes only ids that are gone from disk **and** owned by a visible scope. Another
  project's points are *not mine*, not *deleted*. Legacy scope-less points stay prunable so the
  migration can clear them.
- `search_skills` and `_indexed_names` apply `_scope_filter()` = visible scopes ∪ `scope is null`.
  The null arm keeps legacy points searchable in the window between deploying the code and running
  the migrating reindex.
- `PLUGIN_GLOB` results are narrowed by `_installed_plugin_roots()`, which reads Claude Code's own
  manifests — `installed_plugins.json` → `plugins[<id>@<mkt>][].installPath`, and
  `settings.json` → `enabledPlugins[<id>@<mkt>]` (absent ⇒ enabled; verified: `caveman` is absent yet
  demonstrably active). **Fails open**: unreadable manifests, or a filter matching nothing, fall back
  to the unfiltered cache and log a warning. An index with no plugin skills is worse than a stale one.
  `SKILL_PLUGIN_FILTER=0` restores prior behaviour.
- `META_PATH` is keyed per project root: `index_meta-<md5(PROJECT_ROOT)[:8]>.json`.
  `hooks/scripts/auto_flywheel.py::_meta_path()` mirrors the derivation.

Two flywheel fixes ride along, both rooted in the same "measure the wrong world" theme:

- **`auto_flywheel` defers without stamping when the index lags disk.** It and `auto_reindex` fire
  detached and unordered from the same SessionStart batch. Measuring utterance coverage before the
  reindex lands yields a false `0 missing`; stamping on that lie silenced the flywheel for
  `THROTTLE_S` (6h). Observed: a dozen freshly installed skills got no utterances all morning while
  the hook ran exactly as designed. An index *larger* than disk is normal on a shared collection and
  is not a reason to defer. Unknown counts fail open.

- **The utterance prompt (ADR-0026) is rewritten, and its cache key is versioned.** v1 asked for
  "short intent phrases a user might type **to invoke this skill**", priming the model to restate the
  description. Measured against the live embedder
  (`paraphrase-multilingual-mpnet-base-v2`), best-trigger similarity to
  *"turn a messy pile of incoming bug reports into prioritized work"*:

  | prompt | score | outcome |
  |---|---|---|
  | v1 — short phrases echoing the description | 0.5731 | absent from top-10 |
  | v1a — long first-person "frustrated user" sentences | 0.6473 | each sentence scored 0.34–0.50 |
  | **v2 — short phrases, deliberately different vocabulary** | **0.7558** | **rank 1** |

  Long natural sentences **lose** on this embedder; it rewards short topical phrases. The lever is not
  sentence-likeness, it is **vocabulary distance from the description**. The cache key hashed only the
  skill description, so a prompt rewrite would have regenerated nothing — `PROMPT_VERSION` now
  namespaces the cache prefix.

## Consequences

- Sessions coexist. A reindex from any CWD reports `deleted: 0` for foreign project scopes; a
  project skill ranks in its owning session and is invisible elsewhere.
- `health()` stops false-alarming: `dark: none`, `stale: none`, `status: ok` from the owning CWD.
- The index shrank 548 → 427 skills. Every dropped entry is a stale plugin version or a disabled
  plugin — i.e. was never invocable. Nothing in use was lost.
- `PROMPT_VERSION = 2` invalidates all cached utterances. `auto_flywheel` regenerates
  `AUTO_FLYWHEEL_MAX_PER_RUN` (25) per session, so the catalogue heals over ~17 sessions rather than
  one long GPU burn.
- **Deploy discipline (ADR-0018 applies):** the venv is a copy install. Changing `vendor/` requires
  `pip install --force-reinstall --no-deps vendor/skill-search` **and** a reindex from a *fresh*
  process — long-lived MCP servers hold the old module in memory.
- **Operational landmine:** `skill-search --reindex` from a plain shell has no `SKILL_QDRANT_URL` and
  silently reindexes an *embedded* store at `~/.cache/skill-search/qdrant`, not the live `:6333`; it
  also defaults to a 384-dim embedder against a 768-dim index. Pull the env from a live MCP process:
  `env $(ps eww <mcp_pid> | tr ' ' '\n' | grep '^SKILL_') skill-search --reindex`.

## Alternatives rejected

- **Per-project Qdrant collection** (`SKILL_COLLECTION` already exists as an unused seam). N
  collections, N× embedding cost, and no cross-project retrieval.
- **Drop `PROJECT_ROOT` from `SKILL_DIRS`.** Deterministic and one line, but silently kills
  project-scoped skills (54 on the dev machine).
- **A single shared MCP server.** Not in skill-concierge's control — Claude Code spawns one per
  session. The engine must be safe under concurrency regardless.
- **Prune stale versions from the plugin cache.** Destructive to data the tool does not own;
  discovery ignoring them is sufficient and reversible.
