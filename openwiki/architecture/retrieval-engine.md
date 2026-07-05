# Architecture — the retrieval engine (Retrieve)

The **Retrieve** organ answers *which skill fits*. It is the vendored MIT engine
[`sowhan/skill-search`](https://github.com/sowhan/skill-search), living under
[`vendor/skill-search/`](../../vendor/skill-search/), with a handful of deliberate local
patches logged in [`vendor/skill-search/VENDORED.md`](../../vendor/skill-search/VENDORED.md).

> **Read `VENDORED.md` before touching the engine.** The local customizations (multi-vector
> retrieval, plugin-namespace self-prefix guard, body-derived triggers) are **direct edits to
> vendored source**. If upstream is ever re-vendored, they must be re-applied — the file is the
> checklist.

## Code default vs deployed config — do not confuse them

The engine's *code* defaults are upstream values; this *deployment* overrides all of them via
[`.mcp.json`](../../.mcp.json), the `bin/embed-shim` launcher, and `setup.sh`. Both are stated
here so the wrong default doesn't propagate:

| Knob | Engine code default | **Deployed value** | Set by |
|------|---------------------|--------------------|--------|
| Embedding model | `BAAI/bge-small-en-v1.5` (384-dim, EN) | **`paraphrase-multilingual-mpnet-base-v2` (768-dim, multilingual)** | `.mcp.json`, embed-shim, setup.sh |
| Vector store | embedded on-disk Qdrant (`~/.cache/skill-search/qdrant`) | **Qdrant server** (Docker `skill-search-qdrant` @ `localhost:6333`) | `.mcp.json` |
| `TOP_K` | 6 | **10** (`SKILL_TOP_K`) | `.mcp.json` |
| Multi-vector, body-triggers | both ON in code | ON (not overridden) | code defaults |

The multilingual model was chosen to fix EN-query → VN-skill misses (`VENDORED.md`); the server
tier replaces the embedded store so concurrent Claude sessions don't fight a single-process lock.
See [ADR-0003](../../docs/adr/0003-embedder-and-vector-store.md).

## What gets indexed — model-invocable `SKILL.md` only

Discovery is [`vendor/skill-search/skill_search/skills_discovery.py`](../../vendor/skill-search/skill_search/skills_discovery.py):

- `discover_skill_paths()` globs three roots: personal `~/.claude/skills/*/SKILL.md`, project
  `$CWD/.claude/skills/*/SKILL.md`, and installed plugin skills at
  `~/.claude/plugins/cache/**/skills/*/SKILL.md`. It deliberately scopes plugins to `cache/`
  (installed, invocable copies), **not** `marketplaces/**` (catalog checkouts would pollute the
  index with un-invokable skills).
- `parse_skill()` requires valid `---` frontmatter, so **only model-invocable `SKILL.md` files
  are indexed** — built-in slash-commands are structurally excluded. This is [ADR-0001](../../docs/adr/0001-index-model-invocable-skills-only.md),
  and the reason the vendored eval scores near-zero here ([caveats §1](../../docs/caveats.md)).
- Dedup is first-writer-wins with personal → project → plugin precedence.
- The embedded text per skill is `name \n description \n body`, with the body capped at 4000 chars.

### Plugin namespacing (`ck:worktree`, not `worktree`)

`_namespaced_name()` prefixes installed plugin skills with the plugin id derived from the cache
path (`cache/<marketplace>/<plugin>/<version>/skills/<skill>/`) → e.g. `ck:worktree`,
`skill-concierge:skill-search`. A **self-prefix guard** avoids `ck:ck:plan` when a skill's
frontmatter `name:` already carries the prefix (ClaudeKit ships `name: ck:plan`). Look skills up
**with** the prefix: `get_skill('ck:worktree')`. Personal/project skills keep their bare name.
See [caveats §5](../../docs/caveats.md).

## How `search_skills` ranks — three layers

All in [`vendor/skill-search/skill_search/server.py`](../../vendor/skill-search/skill_search/server.py).

### 1. Multi-vector MAX-pool trigger layer (ADR-0012)

Every skill gets **one `base` point** (name+desc+body) **plus one `trigger` point per intent
phrase**. At query time the engine calls Qdrant `query_points_groups(group_by="name",
group_size=1)`, so each skill collapses to its **single best-matching point** — a MAX-pool over
its phrase points. A skill scores by its *closest* phrasing to the query, not a blurred average.
This was validated at ~2.2× rank-1 separation with flat false-fire. See
[ADR-0012](../../docs/adr/0012-multi-vector-max-pool-retrieval.md).

### 2. Trigger phrases — description + body (ADR-0016)

`_trigger_phrases()` builds each skill's phrase set:

- **Description-derived** first: split the description on sentence/clause boundaries, strip label
  prefixes (`Triggers:`, `Use when:`), keep phrases ≥ 3 words / 12 chars, dedup, cap at 12.
- **Body-derived** next (when `SKILL_BODY_TRIGGERS` is on — the default): phrases mined by
  `skills_discovery._extract_body_triggers()` from the skill body's **labeled decision sections**
  (`## When to Use`, `Triggers:`, `Use when:`, `Examples:`…). A section is read until the next
  header **or** a `Do NOT use`-style exclusion line, so negative bullets naming *other* skills
  don't leak in. Body triggers are mined from the **full** body (not the 4000-char-capped copy),
  deduped against the description phrases, and the **combined** set is capped at 12.

Effect on index size: total points rose **2231 → 3570 (+60%)** when body triggers landed — body
phrases fill slots the median description left empty (descriptions used ~3 of 12). See
[ADR-0016](../../docs/adr/0016-body-derived-trigger-points.md). Revert with `SKILL_BODY_TRIGGERS=0`
**and a reindex** (byte-identical to description-only).

### 3. Query fanout / `extra_queries` fusion (ADR-0017 companion)

`search_skills(query, extra_queries=None)` lets the **caller** pass 2–3 phrasings of the same
intent. The server embeds `[query] + extra_queries`, runs one grouped query per phrasing, then
MAX-pools **across the query sets** — each skill keeps its single best score across all phrasings.
A skill that one phrasing buries can be surfaced by another. With a single query this is identical
to plain top-k. This is the pull-side companion to the enforcer's widened offer menu
([ADR-0017](../../docs/adr/0017-enforcer-gate-thresholds-v2-widen-offer-menu.md)).

## The index itself — incremental, drift-aware

`build_index()` is **incremental by default**: each point stores a `content_hash`; only changed
skills re-embed and orphaned points are deleted. `force=True` (`reindex(force=True)` / `--rebuild`)
drops and recreates the `claude_skills` collection (COSINE distance). Embed+upsert runs in batches
(`EMBED_BATCH=64`) because a single upsert of the full multi-vector point set overflows Qdrant's
33 MB request limit. A manifest at `~/.cache/skill-search/index_meta.json` records the
signature/model/dim so `health` can detect an embedder swap or a stale index.

**Staleness is surfaced, never silent:** when skills change on disk after the last index build,
`search_skills` returns an in-band `warning` and `health` reports `degraded`. This matters because
once skills are set to `name-only` (see [operations.md](../operations.md#configuration-files)),
the retriever is the **sole** discovery path — a stale index hides skills. Staleness now self-heals
via the SessionStart `auto_reindex` hook ([ADR-0014](../../docs/adr/0014-sessionstart-index-self-heal.md),
[caveats §6](../../docs/caveats.md)).

## The four MCP tools (exact behavior)

| Tool | Signature | Returns |
|------|-----------|---------|
| `search_skills` | `(query, extra_queries=None)` | JSON `{query, results:[{name, command, description, score}], queries?, warning?}` |
| `get_skill` | `(name)` | the skill's full SKILL.md text; O(1) lookup via index payload, disk-walk fallback for skills added since last reindex; `{"error":…}` if absent |
| `reindex` | `(force=False)` | `{indexed, points, embedded, deleted, skipped, collection}` — incremental unless `force` |
| `health` | `()` | embed probe + Qdrant reachability + indexed count + `dark_skills` (on disk, not indexed) + `stale_points` (indexed, deleted from disk) + dim guard + manifest freshness; `status: ok|degraded` |

CLI entrypoint `skill-search` (`server.main()`): no args → MCP stdio server; `--reindex`
(`--force`) / `--rebuild` / `--health` for ops.

## What to watch when changing this area

- **Switching the embedding model requires a full rebuild** — a collection built at one dim can't
  accept another dim's vectors; `build_index` raises telling you to `force=True`.
- **fastembed must stay pinned at 0.8.0** across the shim and the index build — 0.5.1 switches to
  CLS pooling and silently mismatches the 0.8.0-built index (retrieval degrades with no error).
- **Never run the upstream `generate_overrides.py`** — it targets the wrong settings file with a
  2-item keep-on default and nukes the curated allowlist ([caveats §2](../../docs/caveats.md)).
- **The vendored `eval/` is a smoke-test, not a quality bar** ([caveats §1](../../docs/caveats.md)).
- **Engine patches are direct source edits** — re-apply from `VENDORED.md` if re-vendored, and
  redeploy by rebuilding the stable venv (`setup.sh`) + a reindex, not just editing the source.
  This is the **stale-engine trap** — see [operations.md](../operations.md#the-stale-engine-trap-post-update).

Related tests: [`vendor/skill-search/tests/`](../../vendor/skill-search/tests/) (`test_discovery.py`,
`test_indexing.py`, `test_fusion.py`). Run them after any engine edit.
