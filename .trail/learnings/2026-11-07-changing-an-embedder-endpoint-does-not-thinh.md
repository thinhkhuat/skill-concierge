---
title: Changing an embedder endpoint does not re-embed what is already stored
author: Thinh
date: 2026-11-07
branch: main
id: l-d9bb0266
scope: repo
status: active
src: agent
touches:
  - vendor/skill-search/skill_search/server.py
---

## Decided
Treat "the service answers with the new engine" and "the stored vectors were built by the new engine" as two separate facts. I proved the first one, called the migration verified, and was wrong about the second. The stored index in the live collection was built by the old engine, so queries embedded by the new one were compared against vectors it never produced.

Detection that worked: take the same logical records from two collections, one built by each engine, match them by a stable key, and compare the raw vectors. Byte-identical means same engine. Here 0 of 400 matched, cosines clustered at 0.985-0.991 — the quantization gap between the two hosts.

## Tried and ruled out
- Reconstructing stored vectors by re-embedding source documents through `skills_discovery.discover_skills()`. Failed: cosines landed at 0.75-0.85 rather than near 1.0, so the rebuilt document text was not byte-identical to what was embedded. Discarded rather than reported as a result.
- Matching stored points by the recorded `content_hash` in the payload. Failed: zero exact-hash matches against my reconstruction, meaning the hash covers something other than the text I rebuilt. Stopped guessing.
- Trusting the peer session's numbers. Rejected: reproduced the comparison from the stored data, which is why the finding stands on my own evidence too.
- Comparing dimensions as a proxy for engine identity. Rejected: both hosts serve the same model name at 768 dims, so dimension is exactly the signal that cannot distinguish them.

## Watch out
A health check that probes the serving backend stays green through an index built by a different backend, because it answers a different question than the one that matters.

Same model name plus same dimension is not evidence of the same vectors. Quantization differs per host even when the model is identical, so the guard must key on an embedder identity, not a shape.

In the code:
- `build_index` in `vendor/skill-search/skill_search/server.py` guards dimension only; identical model names at 768 dims pass it
- live collection and the rtx-built staging collection: 46,560 points each, 0 of 400 sampled pairs byte-identical
- the staged replacement is complete and point-for-point identical to live; swapping needs a delete of the live collection first
- current state is a mismatched index still serving — a working system with a quality defect, not an outage
