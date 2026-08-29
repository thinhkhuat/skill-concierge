# Opus Validation Report

**Subject:** implementation — v0.41.0 ADR-0048 "complement annex" (uncommitted working-tree changes at HEAD b780d81)
**Scope:** enforcer beat gate + usage ranking, auto_promote takes digest, annex-shape invariants, selftests, live e2e probe, docs/version, pytest
**Verdict:** PASS
**Date:** 2026-08-29
**Evidence Files Examined:** 16 (enforcer.py, auto_promote.py, ADR-0048/0047/0036, docs/adr/README.md, plan.md, e2e_probe.py, README.md, AGENTS.md, CLAUDE.md, CHANGELOG.md, openwiki ×2, manifests ×4, live digest)

## Executive Summary

The mechanism is implemented exactly as claimed and survives adversarial probing: the beat gate, thin-intent widening, proven-first ranking, used-N× marker, and kill-switch all verified by code inspection, live probes, and my own fault-injection. Selftest 11c's assertions are live (proven by mutation: `ENFORCER_GETAWAY_FLOOR=0.90` flips it to FAIL exactly as designed). Zero displacement held under live set-comparison. No blocking defects; six advisories, chiefly a "byte-identically" overstatement on the kill-switch and a stale `ENFORCER_ANNEX_DYNAMIC` claim in AGENTS.md/CLAUDE.md.

## Observable Truths

| # | Claim | Status | Evidence |
|---|-------|--------|----------|
| a1 | Beat gate: top ≥ 0.45 → external must score ≥ top + 0.04 | ✓ | `hooks/scripts/enforcer.py:1223-1224`; live e2e leg1 (top 0.75, both annex rows ≥ 0.79) |
| a2 | top < 0.45 → plain EXTERNAL_FLOOR 0.32 | ✓ | `enforcer.py:1225-1226`; selftest 11c thin leg; floor is inclusive (`score < floor` drops, verified 0.55-at-floor admitted / 0.5499 dropped) |
| a3 | `ENFORCER_ANNEX_COMPLEMENT=0` restores `_annex_floor` margin rule | ✓ | `enforcer.py:1227-1228`; live leg3: OFF → 4 margin rows vs ON → 2 on the same prompt |
| a4 | "byte-identically" (ADR-0048 §3, README:389, CHANGELOG) | ⚠ | floor rule + order + no-marker identical, but the legacy query keeps `limit: EXTERNAL_SLOTS*3` (`enforcer.py:1230`) and the unconditional slice (`:1252`) — true 0.40.0 used `limit: EXTERNAL_SLOTS` with no slice (`git show HEAD`, verified) |
| b1 | Proven rows rank first (takes desc, score desc) | ✓ | `enforcer.py:1249-1251`; fault-injection: proven rows at query rank 9-10 of 12 surfaced into slots, ranked 1-2 |
| b2 | `used N×` render | ✓ | `enforcer.py:1520`; per-row verified (proven row carries marker, unproven row in same annex does not); leg2 live: `used 2x` |
| b3 | Provenness reorders, never admits below gate | ✓ | fault-injection: proven row (9 takes) at 0.60 vs floor 0.84 → excluded (`[]`); also pinned by 11c's well-served leg |
| c | External query over-fetches EXTERNAL_SLOTS*3 | ✓ | `enforcer.py:1230`; asserted by selftest case 11 (`:2234`); asserted limit==12 in my fault-injection |
| d1 | auto_promote dumps {name: distinct-session count} on every unthrottled pass | ✓ | `auto_promote.py:120` (before promotion loop), `:135-150`; throttle gate `:159` |
| d2 | Seam `SKILL_CONCIERGE_TAKES_DIGEST`, atomic write, advisory, fail-open | ✓ | `auto_promote.py:135-137,146-148` (tmp + os.replace); enforcer `:133-147` (env seam, OSError/UnicodeError/ValueError → {}); corrupt/absent/list/string/bad-value digests all degrade correctly (fault-injection, 6 cases) |
| d3 | Enforcer reads the live operator digest | ✓ | `_external_takes()` returned exactly the 4 antigravity entries (counts 1/1/2/2, none at threshold 3) |
| e1 | Zero displacement: `must_not tier=external` in `_retrieve` unchanged | ✓ | `enforcer.py:1187`; selftest case 10 (`:2198-2201`); live: primary rows set-identical annex ON vs OFF |
| e2 | Separate annex block render + get_skill footer unchanged | ✓ | `enforcer.py:1517-1525` |
| e3 | Blocklist filtering of annex rows | ✓ | `enforcer.py:1245` (pre-sort, so filtered rows can't consume ranked slots) |
| e4 | Foreign annex untouched (ADR-0034/0036) | ✓ | `_retrieve_foreign` `:1273` still `_annex_floor(FOREIGN_FLOOR, ...)`; not in diff |
| e5 | Promotion valve untouched (PROMOTE_MIN_TAKES=3) | ✓ | diff touches only digest write + selftest in auto_promote.py |
| s1 | enforcer --selftest passes, 11c exists and pins all five behaviors | ✓ | exit 0; 11c `:2274-2325`; mutation test below proves assertions live |
| s2 | auto_promote --selftest passes with digest pin + module-global rebind | ✓ | exit 0; `auto_promote.py:209-221` |
| v1 | driftcheck exit 0; all manifests + package.json 0.41.0 | ✓ | `python3 scripts/driftcheck.py` → "IN SYNC", exit 0; 4 manifests + package.json all `"version": "0.41.0"` |
| v2 | Docs describe complement annex as CURRENT; no stale 0.40.0-as-current | ✓ (with ⚠ below) | README:298, AGENTS.md:72, CLAUDE.md:14, openwiki ×2, CHANGELOG:9; all "0.40.0" hits are historical or kill-switch references; ⚠ ANNEX_DYNAMIC staleness (Advisory 2) |
| v3 | ADR-0048 exists; 0047/0036 statuses read correctly after amendment | ⚠ | 0048 exists + indexed (`docs/adr/README.md:61`); 0047/0036 statuses still "Accepted" (not wrong — neither superseded), but carry no amended-by back-reference (Advisory 3) |
| t1 | pytest tests/ passes | ✓ | 19 passed in 0.61s |
| t2 | Digest refreshes only on unthrottled passes; enforcer safe with stale/absent digest | ✓ | fail-open verified by fault-injection; stale = old counts (advisory ranking only, by design) |
| t3 | `_write_takes_digest` called BEFORE the promotion loop | ✓ | `auto_promote.py:120` precedes `:122` |
| t4 | Selftests never write the real operator digest | ✓ | both rebind to tempdirs with finally-restore; empirically: digest mtime 16:05:45 predates my 16:07 session, unchanged after both selftest runs |

## Key Dependency Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| auto_promote `run_once` | `external-takes.json` | `_write_takes_digest` (`auto_promote.py:120`) | ✓ wired | called before promote loop; atomic tmp+replace |
| enforcer `_retrieve_external` | digest | `_external_takes()` (`enforcer.py:1250`) | ✓ wired | module-global path, call-time read |
| enforcer `main` | digest | `_external_takes()` (`enforcer.py:1742`) | ✓ wired | gated on `(ANNEX_COMPLEMENT and _external)` |
| enforcer render | takes dict | `_ranked_mandate(takes=...)` (`:1743`, `:1519-1520`) | ✓ wired | `takes or {}` → no marker in legacy mode |
| selftest 11c | all gate branches | rebinding ANNEX_COMPLEMENT/ANNEX_BEAT/EXTERNAL_SLOTS/_TAKES_DIGEST_PATH | ✓ wired | saves/restores correctly; no state leak between 11/11b/11c (EXTERNAL_FLOOR=0.40 set at `:2305` equals the value already in force from `:2227`) |

## Blocking Issues (FAIL)

None found.

## Advisory Suggestions (WARN)

1. **"byte-identically" overstates the kill-switch.** In legacy mode (`ANNEX_COMPLEMENT=0`) the query still over-fetches (`limit: EXTERNAL_SLOTS*3`, `enforcer.py:1230`) and the unconditional slice (`:1252`) applies, whereas true 0.40.0 queried `limit: EXTERNAL_SLOTS` with no slice (verified against `git show HEAD:hooks/scripts/enforcer.py`). Floor rule, ordering, and no-marker are identical; the observable difference is that legacy mode can now return a FULL annex when blocklist/floor filtering drops some of the top groups (0.40.0 would have returned short). Strictly better behavior, but the ADR/README/CHANGELOG word "byte-identically" is not literally true of the wire request. Suggest "restores the margin-rule floor and score-only order" wording, or note the over-fetch is mode-independent.
2. **Stale `ENFORCER_ANNEX_DYNAMIC` claim in two governing docs.** AGENTS.md:73 and CLAUDE.md:14 still say the margin rule sizes "BOTH annexes" — under the 0.41.0 default the external annex ignores ANNEX_DYNAMIC/ANNEX_MARGIN entirely (only the foreign annex and the external SLOTS default 4-vs-2 use it). The enforcer's own comment (`enforcer.py:129-130`) states it correctly; the docs lag. Both files are part of this change's diff, so the staleness was introduced by it.
3. **No amended-by back-references on ADR-0047/0036.** ADR-0048 names what it amends, but neither 0047 nor 0036 (nor their docs/adr/README.md rows, lines 50/60) points forward; 0036's row "reinstated for BOTH annexes by 0047" reads as current behavior to a reader landing on it. The repo's own convention records such relationships (0045's row carries "Superseded by 0047").
4. **11c kill-switch comment arithmetic is wrong.** `enforcer.py:2315` says "floor 0.80-0.08=0.72" but ANNEX_MARGIN in force is 0.05 (set at `:2228`) → actual floor 0.75. The assertion is correct either way (cat:hi 0.75 and cat:beat 0.99 pass, cat:mid 0.71 drops under both margins); only the comment misleads.
5. **Live reordering-above-a-higher-scorer only demonstrated in unit test.** e2e leg2's proven row (apple-container 0.75) happened to also be the top scorer, so the live probe shows proven-first but not proven-overtaking; the overtake itself is pinned deterministically by 11c (proven 0.75 floats above unproven 0.99). The coverage substitution (documented in leg2's docstring) is judged honest and sound: the thin-widening branch is two lines of arithmetic pinned by 11c, while the parts needing live verification (cross-tier score comparability, embedder, marker against real rows, kill-switch delta) all ran live. Residual gap: no live intent on this 2,676-skill index exercises top < 0.45, so the thin branch never ran against live Qdrant data in validation.
6. **Digest read twice per offer turn** (`enforcer.py:1250` and `:1742`). If the atomic replace lands between the two reads, sort order and rendered marker could transiently disagree (row sorted unproven but marked used-N×, or vice versa). Cosmetic, one turn max, bounded by the 6h auto_promote cadence. Noting for completeness, not requesting a change.

## Validation Dimensions

- [x] Gate logic (direct inspection, all three modes) — PASS
  - Evidence: `enforcer.py:1223-1228`; `_annex_floor` at `:150-157` governs legacy-external and foreign (`:1273`) only; env seams `ENFORCER_ANNEX_COMPLEMENT`/`ENFORCER_ANNEX_BEAT` at `:131-132`; sort `(-takes, -score)` + slice after sorting at `:1251-1252`.
  - Notes: edge top_installed ≤ 0 → thin branch (plain floor), matching `_annex_floor`'s empty-inventory semantics.
- [x] Selftests run + assertion liveness — PASS
  - Evidence: both exit 0; mutation test `ENFORCER_GETAWAY_FLOOR=0.90` → `enforcer --selftest FAIL: complement: well-served intent must keep ONLY the beater` + exit 1, proving 11c executes with live assertions (11c rebinds BEAT/COMPLEMENT but deliberately not GETAWAY_FLOOR).
  - Notes: 11c's fakes are not rigged — fake group order is deliberately non-score-sorted, which makes the proven-first assertion meaningful; the proven-below-gate exclusion is pinned by the well-served leg (proven cat:hi dropped at floor 0.84).
- [x] Live e2e probe — PASS
  - Evidence: `E2E COMPLEMENT-ANNEX OK`, exit 0; leg1 top 0.75 with 2 beat-gated rows; leg2 annex filled, proven row first with used 2×; leg3 OFF=4 ≥ ON=2 (non-vacuous).
- [x] Digest round-trip + fault injection — PASS
  - Evidence: 6 digest-shape cases + absence all degrade correctly; live read matches the operator file exactly; see Observable Truths d1-d3.
- [x] Zero-displacement regression — PASS
  - Evidence: live `_retrieve` primary rows set-identical ON vs OFF; the order difference in one run was between `ak-kit-builder`/`kit-builder`, exactly score-tied at 0.729187 (re-queried twice, stable) — the tie-flake the checklist warned about, not displacement. ANNEX_COMPLEMENT is not read anywhere in `_retrieve`.
- [x] Docs/version — PASS (with Advisories 2-3)
  - Evidence: driftcheck exit 0; all five version surfaces 0.41.0; complement annex described as current in README/AGENTS/CLAUDE/openwiki ×2.
- [x] Regression hunt (stale digest mid-session, ordering, pytest) — PASS
  - Evidence: pytest 19/19; `_external_takes` catches OSError/UnicodeError/ValueError (JSONDecodeError ⊂ ValueError); IsADirectoryError ⊂ OSError; `main()` wraps `_retrieve_external` in try/except (`:1731-1734`).
- [x] Own adversarial probes — PASS
  - Over-fetch efficacy: proven rows at query ranks 9-10 surfaced into the 4 slots (verified). Proven-below-gate: excluded (verified). leg3 off≥on: 4≥2 (verified). Blocklist filter precedes sort so a blocked row cannot consume a ranked slot (`:1245` before `:1251`). Sort is stable → deterministic ties. Digest keys match index payload names (live leg2 matched `antigravity:apple-container`).

## Unverifiable Items

- Live behavior of the thin-intent branch (top < 0.45) against real Qdrant data — no reliably-thin intent exists on this index (probe leg2 measured top 0.64 on the thin-domain prompt). Covered deterministically by selftest 11c only. See Advisory 5.
- The builder's ledger evidence (410/2656 offers, 6 pulls) — cited in ADR-0048/plan as pre-design evidence; I did not re-derive it (it motivates the design but the mechanism does not depend on it).

## Context Gaps

- None material. (docs/caveats.md carries a pre-existing uncommitted edit, excluded from scope per instructions.)
