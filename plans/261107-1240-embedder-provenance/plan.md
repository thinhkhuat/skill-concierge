# Embedder provenance — blueprint and implementation plan

Date: 2026-11-07
Status: sketch chosen, pre-implementation
Supersedes nothing. Related ADR to be written: ADR-0098.

## The problem, stated for the next person

A skill-concierge index is a pile of vectors. Each vector is only meaningful
against vectors made by *the same embedder*. The engine checks dimensions and
stops there. Two embedders that both produce 768 floats are treated as
interchangeable, and the failure is invisible: search still returns sensible
results, health stays green, and the only symptom is a silent loss of ranking
precision.

We hit exactly this on 2026-11-07. The query path moved to a GPU host
(`embeddinggemma-2:270m`, Q8_0), the stored vectors had been built by the same
model name on this Mac (`nvfp4`). Cosine between them measures ~0.985 instead of
1.0. Every search served since the cutover crossed engines.

Anyone who swaps an embedder, changes a model, moves to a gateway, or restores a
backup will hit this. The engine must make it impossible to miss.

## Ground truth on the current code

Verified by reading `vendor/skill-search/skill_search/server.py`:

| Fact | Where |
|---|---|
| Dimension guard only | `build_index()`, `_collection_dim() != vector_size()` |
| Manifest records `backend`, `model`, `dim`, `engine`, `signature` — **not the endpoint** | `_write_manifest()`, line ~414 |
| Every point payload carries `path`, `name`, `scope`, `content_hash` | `build_index()` desired-point construction |
| Changed-detection compares `(content_hash, scope)` only | `_point_changed()`, line ~987 |
| `_existing_points()` scrolls `with_payload=["content_hash","scope"]` | line ~969 |
| Store client has `create_collection`, `delete_collection`, `upsert`, `scroll` — **no rename** | `_Store`, line ~240 |
| Owner's `count` honours a filter in one pass over a numpy mask | `index_owner.py:508` |
| Scopes are CWD-relative (`visible_scopes()`), and the live collection carries points from three different roots | `skills_discovery.py` |
| Health probes the **query** backend, not stored provenance | `_health()`, line ~1522 |

Two consequences that constrain every design:

1. **A force rebuild from one CWD is data loss.** `build_index(force=True)`
   deletes the collection, then rewrites only what `discover_skills()` finds from
   the current directory. Rebuilding from `skill-concierge/` would permanently
   drop the 655 VGP points and 48 `skills-dev` points that exist only because
   other sessions indexed from other roots. Verified by experiment: the first
   staging build was 703 points short for exactly this reason.
2. **A store-walk migration is CWD-independent.** Because `path` is on every
   point, any point can be re-embedded without knowing which session created it.
   This is what makes a correct migration possible at all.

## Two sketches

### Sketch A — manifest token plus an explicit migration

`embedder_identity()` hashes `(backend, model, endpoint, dim)` into a 12-char
token. The manifest stores it. `ensure_provenance()` compares manifest to current
and, on mismatch, walks the store and re-embeds every point it owns.
`build_index()` calls it. Health reads the manifest.

Small surface: one function, one field, one migration verb.

**Rejected because:** the migration is a *second* code path that must be kept
correct beside the ordinary incremental one, and it is the one that runs least
often. It also has to answer a question the existing code never asks — "which
points do I own" — and a wrong answer prunes. Finally, a migrated index and a
freshly built one differ only in how they got there, but the code has to carry
both stories forever.

### Sketch B — provenance stamped on each point, repaired by the ordinary path

`embedder_identity()` is the same token. The difference is where it lives: in
every point's payload, recording which embedder produced *that* vector.
`_point_changed()` grows one arm — re-embed when the stored identity differs from
the current one. There is no migration verb at all: a backend swap becomes an
ordinary content change, and the incremental reindex already knows how to fix
content changes, at `EMBED_BATCH` size, resumably, touching only what is wrong.

Health derives its answer by asking the store for a filtered count of points
whose identity is not the current one — O(1) in the owner, no manifest field.

**Chosen.** The reason is the one that matters for the next person: there is
nothing extra to remember. Whoever swaps an embedder next runs the same
`reindex()` they always run, and it is correct. No new verb, no new receipt, no
"did you migrate?" state, no second code path to keep in step. A change that
looks right from `_point_changed()` is right for the whole repo.

**Cost, stated honestly:** every point grows by one short string, and a legacy
point re-embeds once. Health's stale count costs one filtered `count` call.

### Sketches considered and dropped

- **Store the token only in the collection name** (`claude_skills__<token>`).
  Zero new payload. Dropped: a rename is not available on the owner (no alias
  route, verified), so every swap would need delete-and-rebuild — reintroducing
  the CWD data-loss problem and a dark window.
- **Refuse to search on mismatch.** Dropped: turning a precision degradation into
  an outage punishes the user for the engine's blind spot. Report and self-heal.

## The design

New in `vendor/skill-search/skill_search/server.py`:

```python
PROVENANCE_FIELDS = ("backend", "model", "endpoint", "dim")

def embedder_identity() -> str:
    """12-hex sha256 of PROVENANCE_FIELDS at their current values."""
```

- `endpoint` is `OLLAMA_URL` for the ollama backend and `"local"` for fastembed,
  normalised (trailing slash stripped, lowercased) so cosmetic differences do not
  fake a swap.
- The token is computed once at import into `EMBED_IDENTITY`, beside the existing
  `EMBED_BACKEND` / `EMBED_MODEL` constants.

Changed:

- Every point payload gains `"provenance": EMBED_IDENTITY` — base points and
  trigger points alike.
- `_existing_points()` scrolls `provenance` alongside `content_hash` and `scope`.
- `_point_changed(stored, want_hash, want_scope, want_identity)` gains the third
  arm. A stored `None` identity (legacy point) is always changed, so the first
  incremental reindex after this ships migrates the whole index exactly once.
- `_write_manifest()` records `endpoint` and `provenance` beside `backend` /
  `model` / `dim`, for humans and for doctor.
- `_health()` gains `embedder_provenance: {current, stale_points, total, ok}` and
  an issue line when `stale_points > 0`, naming the remedy (`reindex()`).

Not changed: the dimension guard stays. It catches a genuinely incompatible
collection before any embed call; provenance covers the case it cannot see.

### Why the quantization is not in the token

It is the actual cause of today's drift, and the engine cannot see it through
the interface it has. Ollama reports `quantization_level` in `/api/tags`, but a
gateway can hide it, a non-ollama backend has no equivalent, and a proxy can swap
the model behind a stable URL. Hashing only what the engine controls keeps the
token honest: it detects every swap the engine can observe. A quantization change
behind an unchanged URL is documented in the ADR and in `docs/caveats.md` as a
manual step, not pretended to be detected.

## Phases

**Phase 1 — the token and the stamp.** Add `PROVENANCE_FIELDS`,
`embedder_identity()`, `EMBED_IDENTITY`; stamp payloads; extend `_existing_points`
and `_point_changed`; record `endpoint`/`provenance` in the manifest; extend
`_health()`.
*Check:* unit tests for the token's stability and for `_point_changed`'s new arm;
`python3 -m pyflakes` clean.

**Phase 2 — tests that fail on the defect.** A test that a point stamped with a
different identity is re-embedded; a test that a point with no identity is
re-embedded once; a health test that a mixed collection reports `stale_points > 0`.
Each must fail against the unpatched engine.
*Check:* revert the arm, confirm red; restore, confirm green.

**Phase 3 — the live migration.** Run the incremental reindex from a session,
then from `VGP` and `skills-dev` so no scope is missed. Confirm `stale_points`
reaches 0 and the point count is unchanged at 46,560.
*Check:* `stale_points == 0`, point count identical, per-scope sample verifies at
`cos = 1.000000` against rtx.

**Phase 4 — documentation.** ADR-0098 (the decision and the two rejected
sketches), a `docs/caveats.md` entry for the quantization blind spot, a
`CHANGELOG.md` entry, and `VENDORED.md` (this is a direct edit to vendored
source, so it must be recorded as a re-apply-after-revendoring patch).
*Check:* `python3 scripts/driftcheck.py driftcheck.json` exits 0.

**Phase 5 — retire the staging collection.** After the live index verifies,
delete `claude_skills__rtx_staging` and the staging manifest/sidecar files.
*Check:* doctor green, one collection remains.

## Done when

- A swap of any provenance field causes the next `reindex()` to repair the index
  with no operator action, and `health()` reports it before and after.
- The live index is 46,560 points, all at `cos = 1.000000` against rtx.
- The defect is covered by tests that fail without the fix.
- The record exists in ADR, caveats, changelog and VENDORED.

## Open questions

- Whether option 1 (in-place rebuild) means a `force=True` wipe or the incremental
  migration above. The wipe loses the 703 cross-root points unless run three
  times; the incremental path gets to the same end state without a dark window.
  Recommended: incremental. Flagged because the user said "do the #1".
