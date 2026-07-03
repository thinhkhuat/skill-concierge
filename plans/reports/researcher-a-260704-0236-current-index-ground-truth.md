# Ground truth: what skill-concierge actually indexes today

> **Correction (Opus-validated 2026-07-04):** Q5 below overstates the enrich overlay. Its claim that the
> live `claude_skills` collection's base vectors are a "steady-state trigger-blended MEAN" is **FALSE**
> under the default multi-vector index. The MEAN overlay is superseded and inert: `setup.sh:76-78` runs
> `enrich_index.py --reapply` only when `SKILL_MULTIVECTOR=0`, `doctor.py:306-308` treats 0 enriched
> points as OK, and the live index has **0 enriched points** — base vectors are pure `embed(_skill_text)`.
> Everything else in this report verified. See `opus-validation-260704-0320-...` and the proposal Layer 3.

Scope: `vendor/skill-search/skill_search/{skills_discovery,server}.py` (confirmed live source —
`vendor/skill-search/pyproject.toml:29` wires console script `skill-search = "skill_search.server:main"`;
`vendor/skill-search/build/lib/skill_search/*` is a stale build artifact, not read at runtime),
plus `scripts/{embed_server,enrich_index,analyze}.py` and the deployed `.mcp.json`.

## Field → embedded? / payload? / on-demand? (compact table)

| Field | Embedded into vector? | Qdrant payload? | Fetchable on demand? |
|---|---|---|---|
| `name` | Yes — part of base text (`server.py:270-272`) | Yes (`server.py:355`) | — |
| `description` (+ `when_to_use` folded in) | Yes — part of base text; **also** re-embedded per-phrase as separate trigger points when multivector is on | Yes (`server.py:355`) | — |
| `body` (frontmatter-stripped, capped **4000 chars**) | Yes — part of base text (`skills_discovery.py:91`, `server.py:270-272`) | **No** — payload dict has no `body` key (`server.py:354-356`) | Indirectly: full uncapped body is re-read fresh from disk by `get_skill` (not from this cached slice) |
| Trigger phrases (description split into ≤12 intent phrases) | Yes — each phrase is its own Qdrant point/vector (`server.py:357-362`) | Phrase text itself is **not** stored; payload only carries parent `name`/`description`/`content_hash`/`kind:"trigger"` | — |
| `path` | No | Yes (`server.py:356`) | Used internally to resolve `get_skill` |
| `content_hash` | No (it's a hash *of* the embedded text) | Yes (`server.py:356`) | Used for incremental-reindex diffing |
| `kind` (`"base"` / `"trigger"`) | No | Yes | — |
| `enriched`, `enrich_source_hash` (set by `scripts/enrich_index.py`) | No | Yes (`enrich_index.py:158-167`) | — |
| Full raw `SKILL.md` text | No (only the first 4000 chars of body ever get embedded) | No | **Yes** — `get_skill` reads the whole file from disk, uncapped |

## The 6 questions

**1. What string is fed to the embedding model per skill?**
Three layers, not one:
- Base point: `name + "\n" + description + "\n" + body[:4000]` — `server.py:270-272` (`_skill_text`), where `description` is frontmatter `description:` with `when_to_use:` appended if present (`skills_discovery.py:79-86`), and `body` is the post-frontmatter text capped at 4000 chars (`skills_discovery.py:91`).
- Trigger points (multivector layer, default ON via `MULTIVECTOR = os.environ.get("SKILL_MULTIVECTOR","1") != "0"`, `server.py:82`): each intent-bearing phrase extracted from `description` alone (not body) via `_split_phrases` (`server.py:252-267`) is embedded as its own separate point (`server.py:357-362`).
- Post-hoc overlay (`scripts/enrich_index.py`, wired into the live pipeline via `setup.sh:77` and `scripts/doctor.py:489` auto-fix): the *stored vector* for the base point is later overwritten to `MEAN(base_vector, trigger_phrase_vectors)` where the trigger phrases come from `eval/triggers.json`, not from `_split_phrases` — see Q5.

**2. Which fields are stored as payload but NOT embedded?**
`path`, `content_hash`, `kind`, `enriched`, `enrich_source_hash`. (`name` and `description` are both embedded *and* stored — they aren't payload-only.)

**3. Is the 4000-char body embedded, or only stored as payload?**
Embedded only. The payload dict built at `server.py:354-356` has no `body` key at all — once the vector is computed, that capped body text is discarded; it cannot be read back out of Qdrant.

**4. Does `get_skill` return the full body on demand (progressive disclosure already present)?**
Yes. `server.py:439-457`: it resolves the point's `path` from the payload via an O(1) id lookup, then does `Path(path).read_text(encoding="utf-8")` — the entire raw `SKILL.md`, uncapped, straight from disk (fallback path at `server.py:454-456` does the same via `discover_skills()` if the index is stale/missing). So yes — full-body retrieval on demand already exists independent of whatever was embedded.

**5. Does `enrich_index.py` already alter/expand the indexed text? What does it do?**
It does not change the *text* used to compute the base vector — its own parity gate (`enrich_index.py:100-124`) re-derives `txt` via the same `server._skill_text()` and asserts cosine ≥ 0.999 against the currently-stored (un-enriched) vector, i.e. confirms the base vector still equals `embed(name+description+body[:4000])`.
What it *does* do is post-process the **vector**: `enriched = mean_vecs([S] + trigger_phrase_vectors)` (`enrich_index.py:151`), where `S` is the base vector and the trigger phrases are pulled from `eval/triggers.json` (curated separately from the live `_split_phrases` multivector logic) and embedded via the same engine path (`enrich_index.py:94-97,146-147`). The result is written back **vector-only** (`PUT .../points/vectors`, never `upsert`, so payload incl. `description`/`path` survives — `enrich_index.py:22-25,154-157`), and the point is marked `enriched:true`.
This is not a one-off experiment: `setup.sh:77` runs `enrich_index.py --reapply` as a standard setup step, and `scripts/doctor.py:295-314` treats un-enriched points after a reindex as a WARN-level, auto-fixable staleness condition. So the live `claude_skills` collection's vectors are, in steady state, this trigger-blended mean — not a pure `embed(_skill_text)` output.

**6. Which embedding model + vector dimension + distance metric is configured?**
- Distance metric: `Distance.COSINE`, set at collection creation (`server.py:293`).
- Backend: `fastembed`, pinned to version `0.8.0` in `vendor/skill-search/pyproject.toml:24-27` (explicitly *not* 0.5.1 — that version silently flips mpnet from mean- to CLS-pooling and would desync query vs. indexed vectors, per the same comment and `scripts/embed_server.py:15-16`).
- Model: the code's own default (`server.py:73`) is `BAAI/bge-small-en-v1.5` (384-dim), but the **actually deployed** value overrides that default — `.mcp.json:8` sets `SKILL_EMBED_MODEL=sentence-transformers/paraphrase-multilingual-mpnet-base-v2`, and `setup.sh:33` reads that same `.mcp.json` value to drive index builds. `scripts/embed_server.py:5,13,22` corroborates this is the live model, calling it "mpnet-768" and documenting `GET /health` as returning `"dim":768`.
- Vector dim: 768, auto-probed at runtime from the live backend (`vector_size()`, `server.py:216-224`) rather than hardcoded, guarded against silent embedder-swap mismatches by `_collection_dim()` (`server.py:275-286`) and the `health()` tool (`server.py:503-510`).
- Store mode: `.mcp.json:6` sets `SKILL_QDRANT_URL=http://localhost:6333` — deployed as a Qdrant **server**, not the code's embedded-file fallback (`server.py:92-99`).

## Unresolved / ambiguous

- The literal text of each trigger phrase (multivector layer, `server.py:357-362`) is embedded but never stored in its own payload — only re-derivable by re-running `_split_phrases(description)` against the *current* description. If the description changes, the historical phrase that produced an old point isn't recoverable from Qdrant alone; this wasn't asked but is adjacent to Q2 and worth flagging.
- Did not independently verify against a live Qdrant instance (report is static-code-only, as scoped: read-only, no `mcp__plugin_skill-concierge_skill-search__*` calls made). All claims are `file:line`-sourced from source, not runtime-probed.
