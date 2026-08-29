# Plan — Revert catalog tier parity, restore the external annex (ADR-0047, v0.40.0)

Owner order (2026-08-29): the ADR-0045 merged-pool parity is a regression, not an
enhancement. Return the offer mechanism to the pre-parity state — the ADR-0032
bounded external annex — but with floors/margins tuned to be more helpful than the
ADR-0032-era values. Also revert the same-day follow-up that let mined chains learn
from get_skill pulls (2a66d45, `CHAIN_MINE_PULLS`).

## Outcome

- Externals never displace installed offer rows (zero-displacement invariant back).
- Externals appear only in a separate, marked annex block: floor `EXTERNAL_FLOOR`
  (tuned 0.32, was 0.40), dynamic sizing (`_annex_floor`, margin tuned 0.08, was
  0.05), cap 4 dynamic / 2 fixed.
- Chain hints / ROUTE / sidecar are installed-only again (catalog scopes excluded).
- Flywheel `--generate` defaults to installed-only; catalogs stay covered by the
  auto-flywheel per-alias loop (v0.35.1 shape) and by explicit `--catalog`.
- Mined chains read invocations only (auto/manual); pull-mining reverted.
- ADR-0046 blocklist filtering is preserved and also applied to annex rows.

## Non-goals

- No substrate change: ADR-0031 catalog roots, indexing, `search_skills` fusion,
  `get_skill` lane, promotion valve all stay as-is.
- No change to the foreign (cross-harness) annex beyond the shared margin tune.
- Not a `git revert` — ADR-0046 landed on top of the same files; this is a forward
  port of the pre-parity mechanism (source: `git show 4322bc7^:...`).

## Constraints

- `ENFORCER_EXTERNAL_ANNEX` returns as the primary flag name; `ENFORCER_EXTERNAL_OFFER`
  stays honored as an alias. `=0` still means the ADR-0031 search-only tier.
- openwiki commit guard: quickstart version must match plugin.json; driftcheck exit 0.
- Epoch boundary: offer-composition and external offer→take rates reset at v0.40.0.

## Steps (gates G1–G8 in the session ledger)

1. G1 this plan + GATES.md.
2. G2 enforcer.py: restore flag block + `_retrieve_external` + tier filter +
   annex render + ledger ext + installed-only chain reads; tune values; adapt
   selftest cases 10/9d/12; keep blocklist drops (incl. annex rows). Selftest green.
3. G3 vendor engine: server.py sidecar re-excludes `catalog:*`; skills_discovery
   parity hunk reverted; VENDORED.md updated; venv re-copy.
4. G4 flywheel.py default installed-only (+ keep `--catalog`, keep manifest scope
   tag); auto_flywheel per-alias loop restored; build_chains pull-mining reverted;
   analyze.py annex stats wording/selftest restored. All selftests green.
5. G5 docs: ADR-0047 (supersedes ADR-0045; tuned values + revert path), status
   sweeps (0032 reinstated, 0036, 0040, 0043, 0045), README, AGENTS.md, CLAUDE.md,
   openwiki, CHANGELOG, 4 manifests + package.json → 0.40.0. driftcheck exit 0.
6. G6 pytest + live probe: annex block renders on a catalog-flavored intent,
   installed rows byte-stable vs annex-off.
7. G7 independent blind validator; fix findings; re-verify.
8. G8 conventional commit + push; clean tree.

## Tuned values (recorded per revert-path rule)

| Var | ADR-0032 era | Now | Why | Revert |
|---|---|---|---|---|
| `ENFORCER_EXTERNAL_FLOOR` | 0.40 | 0.32 | 2.2× installed floor starved the annex (audit asymmetry #2); 0.32 ≈ 1.8× still demands a strong match | env var, or ADR-0047 |
| `ENFORCER_ANNEX_MARGIN` | 0.05 | 0.08 | externals within 8 pts of installed top are genuinely competitive; 5 pts starved catalog-heavy intents | env var, or ADR-0047 |
| `ENFORCER_EXTERNAL_SLOTS` | 4 dyn / 2 fixed | unchanged | cap was never the complaint | — |

## Risk / rollback

- Highest-risk file is enforcer.py (480-line parity rewrite + blocklist on top).
  Mitigation: port from the exact pre-parity source, selftest pins, blind validator.
- Rollback: single revert commit; flags allow behavioral rollback without code
  (`ENFORCER_EXTERNAL_ANNEX=0` → search-only).
