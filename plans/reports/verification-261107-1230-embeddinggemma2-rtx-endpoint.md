# embeddinggemma-2 via rtx endpoint — verification report

Date: 2026-11-07 · Session: new session after the concierge cutover restart
Scope: verify that skill-concierge's embedder (embeddinggemma-2:270m through the rtx HTTPS endpoint) works on every live path, and that indexing runs correctly through it.

## Verdict

The rtx embedder setup is correct and working on every live path. Query embedding, ingestion embedding, and retrieval all pass. One real defect was found and is not fixed: the 46,560 stored index vectors were built by this Mac's local Ollama, not by rtx, so queries are scored against vectors from a different quantization.

## What was verified

| Check | Result | Evidence |
|---|---|---|
| Endpoint authenticates | PASS | `/api/tags` and `/api/embed` return 200 with the bearer token, 401 without |
| Index owner embeds via rtx | PASS | `cos(owner, rtx) = 1.000000000`, vectors byte-identical; `cos(owner, local) = 0.989413` |
| Ingestion path (`embed_batch`) | PASS | 128 real skill documents embedded, 43.2 ms/doc, all 768 dims |
| Query retrieval through rtx | PASS | correct top hits, scores 0.77–0.85, 1.0–1.7 s per query |
| MCP server on current engine build | PASS | pid 98194, build `20eca552a566`, matches deployed disk build |
| Incremental reindex | RAN | 0 embedded / 45,857 skipped — index was already current, so this exercised no embedding |
| Stored index provenance | **FAIL** | 6/6 hash-verified points: `cos(stored, local) = 1.000000`, `cos(stored, rtx) = 0.984998` |

## The defect

A backend swap does not rewrite stored vectors. `skill_search/server.py` guards only the dimension: `build_index` compares `_collection_dim()` to `vector_size()` and raises when they differ. Both hosts serve 768 dimensions, with identical model names, differing only in quantization — local Ollama runs `nvfp4`, rtx runs `Q8_0`. The guard never fires, and `_health()` reports `embedder.reachable: true, dim: 768` because it probes the query backend, not stored-vector provenance.

Symptom: retrieval works and returns sensible hits, but query and stored vectors come from two different numeric formats.

**This is live right now, not a historical note.** The index owner is still answering queries from the Mac-built collection. Every search served today crosses engines: the query embeds on rtx, the candidate vectors were built locally. The hits are sane and the scores look normal, but nobody should read current hit quality as a clean rtx measurement. A clean measurement requires the swap, or querying `claude_skills__rtx_staging` directly.

## What was built

A full rebuild into a separate collection, with the live collection untouched throughout:

- `claude_skills__rtx_staging` — 46,560 points, all embedded through rtx
- Full build: 45,857 points in 1,211 s (20.2 min), 0 errors
- VGP project scope filled from its own CWD: 655 points
- `skills-dev/.opencode` project scope filled from its own CWD: 48 points
- Final: staging and live both hold 46,560 points, zero difference in either direction

Provenance verified at 8 points spanning all sampled scopes (personal, plugin, codex-plugin, dsh-personal, omp-managed, zcode-plugin, project, opencode-project): every one is `cos(stored, rtx) = 1.000000` and `cos(stored, local) ≈ 0.985`. Retrieval against staging returns the same correct top hits as the live index.

## Collateral change I caused

My staging script set `NEXT_SKILLS_PATH`, but the engine reads `SKILL_CONCIERGE_NEXT_SKILLS` — the override silently missed and the staging build rewrote the live `~/.claude/skill-concierge/next-skills.json` (59.6 KB, valid JSON, 43 scopes, 1,836 skills). This is what every reindex writes anyway, so it is benign. Backed up to `next-skills.json.bak-261107-1230`. The manifest was NOT touched (`SKILL_META_PATH` is the correct name); the staging manifest went to its own file.

## Open decision — the swap

Staging cannot be swapped in by me. The index owner's HTTP surface has `GET|PUT|DELETE /collections/{c}` and no rename/alias route, so the only available swap is `DELETE claude_skills` then rename staging's name — and the owner has no rename. That is a destructive operation and the user was AFK when asked.

Paths forward, for the user's call:

1. **Accept a short dark window.** `build_index(force=True)` on the live collection: deletes and rebuilds, ~20 min with no index.
2. **Script the swap at the SQLite/store layer.** The owner keeps collections in `index.sqlite` (`collections` table, name/dim/distance). A rename there plus a process restart would swap without a rebuild — needs careful verification the store has no other name-keyed state.
3. **Leave it mixed.** Retrieval works today; the mismatch is silent and permanent.

## Unresolved questions

- Whether to swap staging in, and by which of the three routes above.
- Whether to commit the trail learning at `skill-concierge/.trail/learnings/2026-11-07-an-embedder-swap-leaves-the-stored-thinh.md`. No commit order was given in this session.
- The doctor WARN about 4 MCP servers on the old engine build (pids 99240, 42732, 69168, 56656) needs a Claude Code restart. Not caused by this work; the peer session reported it first.

## Artifacts

Verification scripts and receipts, `~/.cache/skill-search/trials/`:

- `embed-route-verify.py` — owner vs rtx vs local, byte-identity check
- `ingest-path-verify.py` — real `embed_batch` over 128 skill documents
- `index-provenance.py` — which backend built the stored vectors
- `staging-rebuild.py`, `staging-rebuild.log` — the full staging build
- `staging-vs-live.py`, `staging-vs-live.json` — point-level collection diff
- `staging-scope-provenance.py` — per-scope provenance inside staging
- `staging-rebuild-1794028117.json` — build receipt
