# ADR-0098 — Embedder provenance is stamped on every point, not recorded in the manifest

**Status:** Accepted
**Date:** 2026-11-07

## Context

A skill-concierge index is a pile of vectors, and a vector is only comparable
against vectors made by *the same embedder*. The engine's only guard was a
dimension check: `build_index` compares `_collection_dim()` to `vector_size()`
and raises when they differ.

On 2026-11-07 the query path moved to a GPU host serving
`embeddinggemma-2:270m` (Q8_0) while the stored vectors had been built by the
same model name on a Mac (nvfp4). Both produce 768 floats, so the guard never
fired. Every search after the cutover embedded the query on one engine and
scored it against vectors built by another; `cos` between the two is ~0.985, not
1.0.

Nothing noticed. Retrieval returned sensible results and `_health()` reported
`embedder.reachable: true, dim: 768`, because health probes the **query**
backend. Query reachability and stored provenance are different questions, and
only the first was being asked.

Anyone swapping an embedder, changing a model, moving to a gateway, or restoring
a backup hits the same silent break.

## Decision

**Stamp every point with the identity of the embedder that produced its vector,
and repair a mismatch through the ordinary incremental reindex.**

`embedder_identity(backend, model, endpoint, dim)` hashes those four fields into
a 12-hex token (`EMBED_IDENTITY`, computed lazily by `current_embed_identity()`).
Every point payload carries `"provenance": <token>`. `_existing_points()` reads
it back and `_point_changed()` grows a third arm: re-embed when the stored token
differs from the current one. A legacy point carries `None` and is re-embedded
exactly once.

`_health()` gains `embedder_provenance: {current, stale_points, total_points, ok}`
by asking the store for a filtered `count` — one numpy mask pass in the owner, so
the cost is O(1) at the call site and independent of collection size.

### Why stamping beats a manifest token

Two designs were built as sketches (`sketch-a` and `sketch-b` in the trial
record).

**Sketch A — a manifest token plus an explicit `ensure_provenance()` migration**
stores the token once, in `META_PATH`, and adds a migration verb that walks the
store and re-embeds on mismatch. Small surface, but it creates a **second repair
path** that runs only on the day someone remembers it. That path has to answer a
question the ordinary code never asks — "which points do I own" — and a wrong
answer prunes. A migrated index and a freshly built one would then differ only in
how they got there, while the code carries both stories forever.

**Sketch B — the stamp** makes a backend swap an ordinary content change. There is
no new verb and no migration state to get wrong: whoever swaps an embedder next
runs the `reindex()` they already run, and it is correct. A change that looks
right from `_point_changed()` is right for the whole repo.

Also rejected: recording the token only in the collection name
(`claude_skills__<token>`). The index owner exposes no rename or alias route
(verified: `GET|PUT|DELETE /collections/{c}` only), so every swap would mean
delete-and-rebuild — and a from-one-CWD rebuild is silent data loss, because
scopes are CWD-relative and one collection carries points from several roots.
Measured on this machine: rebuilding from the plugin directory alone came up
**703 points short**.

## Consequences

- Every point grows by one short string; the first reindex after this ships
  re-embeds the whole index once (46,560 points, ~20 min at 43 ms/doc through the
  GPU host). After that, a swap re-embeds only the points it needs to.
- `health()` now answers "is the stored index from the embedder serving queries",
  which is the question whose absence let the 2026-11-07 cutover pass unnoticed.
- The dimension guard stays. It catches an incompatible collection before any
  embed call; provenance covers the case it cannot see.

## The blind spot this does not close

The token covers everything that changes the numbers **and that the engine can
observe**. Quantization is the case that started this and it is *not* detected:
ollama reports `quantization_level` in `/api/tags`, but a gateway can hide it, a
non-ollama backend has no equivalent, and a proxy can swap the model behind a
stable URL. Hashing only observable fields keeps the token honest rather than
pretending to a detection it cannot make.

A quantization change behind an unchanged URL therefore still drifts silently.
It is recorded as a manual caveat in `docs/caveats.md`: after changing the
quantization or precision of the embedder *without* changing its URL, model id or
dimension, force a rebuild by hand.

## Re-apply note

This is a direct edit to `vendor/skill-search/skill_search/server.py`, not a
plugin-level layering. It must be recorded in `vendor/skill-search/VENDORED.md`
so a re-vendor does not silently drop it.
