# Opus Validation Report — ADR-0047 annex restore (v0.40.0)

**Subject:** implementation (revert of ADR-0045 tier parity; restore of ADR-0032 external annex)
**Scope:** uncommitted working tree on `main` at HEAD 0b871ef, per the 8-point blind checklist
**Verdict:** PASS
**Date:** 2026-08-29
**Evidence Files Examined:** 15+ source/doc files, 4 selftests, 2 full pytest runs (working tree + HEAD extract), 2 live subprocess probe sets, 6 e2e probe runs

## Executive Summary

The revert is faithful and complete: the merged-pool parity mechanism is gone, the ADR-0032
annex is back with the two tuned defaults, the ADR-0046 blocklist survives intact (and now also
covers annex rows), the flag alias works live, and pull-mining is removed from build_chains.py
byte-identically to the pre-0.38.1 state. Zero blocking defects found in the change itself.
One significant advisory: the G6 probe `e2e_probe.py` is FLAKY — it failed 3 of 6 runs on a
tied-score ordering artifact, so "must print E2E ANNEX-RESTORE OK" is not deterministically true;
the underlying zero-displacement invariant was independently verified sound.

## Observable Truths

| # | Claim | Status | Evidence |
|---|-------|--------|----------|
| 1 | `_retrieve` ALWAYS sends `must_not tier=external`, no conditional | ✓ | `hooks/scripts/enforcer.py:1156-1157` (unconditional in the request body); selftest case 10 pins it (`enforcer.py:2153-2154`) |
| 2 | `_retrieve_external` exists as separate query with EXTERNAL_SLOTS + `_annex_floor` | ✓ | `enforcer.py:1178-1209`; matches pre-parity source `git show 4322bc7^` line-for-line except the added `_blocked` filter |
| 3 | Annex renders as "External catalog matches" block; no `[external:*]` in primary list | ✓ | `enforcer.py:1475-1480` (marker only inside annex block); live probe: 8 primary rows unmarked, 4-row marked annex; selftest line 2203 pins no-marker-in-primary |
| 4 | No `_ext_tag`/`_EXT_HINT_ALIASES` parity residue | ✓ | `grep` over enforcer.py: zero hits; "EXTERNAL_OFFER" appears only as alias read (line 89) + comments |
| 5 | Chain-hint/sidecar scopes exclude `catalog:*` | ✓ | `enforcer.py:777-788` — scopes list is personal/plugin/project + codex-*/zcode-* only |
| 6 | Blocklist preserved: all HEAD call sites survive | ✓ | HEAD sites (chain-hint seed+successors, deterministic, foreign, route, main `_drop_blocklisted`) all present at `enforcer.py:869,877,975,1247,1407,1636`; NEW site in `_retrieve_external` at 1205; selftest 4b intact at 1803 |
| 7 | EXTERNAL_FLOOR default 0.32; ANNEX_MARGIN default 0.08 | ✓ | `enforcer.py:90` (`"0.32"`), `enforcer.py:115` (`"0.08"`) |
| 8 | `ENFORCER_EXTERNAL_OFFER` honored as alias of `ENFORCER_EXTERNAL_ANNEX` | ✓ | `enforcer.py:87-89` (nested env read); LIVE-PROBED: default renders annex, `OFFER=0` and `ANNEX=0` both remove it, installed rows byte-identical across all three runs |
| 9 | All four selftests pass | ✓ | enforcer / build_chains / analyze / flywheel_manifest all exit 0 under the concierge venv |
| 10 | MINE_PULLS/_MINABLE_EV/CHAIN_MINE_PULLS GONE; event filter back to auto/manual | ✓ | zero grep hits in `scripts/build_chains.py`; filter at line 111; file is byte-identical to `git show 2a66d45^:scripts/build_chains.py` |
| 11 | e2e_probe.py prints E2E ANNEX-RESTORE OK | ⚠ | FLAKY: 3/6 runs OK, 3/6 FAIL on leg3 — see Advisory 1. Underlying invariant verified sound by other means |
| 12 | Engine sidecar skips `catalog:*`; deployed venv matches source | ✓ | `vendor/skill-search/skill_search/server.py:302`; `diff -r -x __pycache__` vs `venv/lib/python3.12/site-packages/skill_search` exit 0 |
| 13 | Engine `_blocked` in search_skills + get_skill | ✓ | `server.py:813` (fused rows filter), `server.py:828` (get_skill refusal) |
| 14 | driftcheck exit 0; all manifests 0.40.0 | ✓ | IN SYNC; plugin.json ×2, codex plugin.json, marketplace.json ×2, package.json, quickstart all 0.40.0 |
| 15 | No stale ADR-0045-as-current doc references | ✓ | grep sweep over README/AGENTS/CLAUDE/caveats/openwiki/skills: all mentions are historical or revert-framed; CLAUDE.md:14 + AGENTS.md:72 rewritten to the annex mechanism |
| 16 | flywheel `--generate` default installed-only | ✓ | `scripts/flywheel.py:320` (`catalog=None`) → `else: coverage()` installed branch at 358-360; `--installed-only` flag removed from argparse |
| 17 | auto_flywheel per-alias loop restored | ✓ | `hooks/scripts/auto_flywheel.py:224-233` — installed first, then `--catalog <alias> --limit` per configured alias |
| 18 | Vendor test failures same set, not grown | ✓ | 12 failed / 90 passed on working tree; IDENTICAL 12-test set (11 test_discovery + test_indexing::test_disk_signature) on HEAD's code extracted via `git archive` to /tmp — environmental (real plugin dirs leak, e.g. `assert 22 == 1`) |
| 19 | No post-0.38.0 fix clobbered by the reverse-apply | ✓ | Commit-range audit 4322bc7^..HEAD: only b792f2a (blocklist — verified preserved) and b3fe3e4 (`bin/skill-search-mcp` — untouched by this diff) carry non-reverted work overlapping the tree; skills_discovery.py revert is comment-only |
| 20 | Live sidecar catalog keys pruned, backup kept | ✓ | `next-skills.json` has zero `catalog*` keys; `next-skills.json.bak-adr0047-20260829-145743` exists |

## Key Dependency Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| enforcer main() | _retrieve_external | annex query after gates | ✓ | `enforcer.py:1687`, try/except degrade-to-no-annex |
| _retrieve_external | _blocked | ADR-0046 filter | ✓ | `enforcer.py:1205` (new vs 0.23.0 code, as claimed) |
| _ranked_mandate | annex block | `annex=` kwarg | ✓ | `enforcer.py:1697` + render at 1473-1480 |
| ledger | ext field | `_append_offer(ext=...)` | ✓ | `enforcer.py:1708` — annex rows only, primary offer external-free |
| vendored source | deployed venv | pip re-copy | ✓ | recursive diff clean |
| alias flag | live behavior | subprocess env probe | ✓ | 3-way probe: annex present/absent/absent, primaries byte-identical |

## Blocking Issues (FAIL)

No blocking issues found.

## Advisory Suggestions (WARN)

1. **`plans/260829-1434-annex-restore/e2e_probe.py` leg3 is flaky (~50% observed fail rate: 3 of 6 runs).**
   Two installed rows with tied scores (`kit-builder` / `ak-kit-builder`, both 0.73, both 13%)
   swap order between the annex-on and annex-off subprocess runs — two independent live Qdrant
   queries have no tie-order guarantee. Every failure diff was this swap; no external row ever
   entered the primary list (verified in the failing logs). The displacement INVARIANT holds;
   the probe's byte-compare of tied orderings across separate live queries does not. GATES.md
   G6 records "e2e_probe OK" from a passing run — true for that run, but the probe is not
   reproducible evidence as written. Fix: compare the primary rows as a set (or sort tied
   rows), or pick a tie-free prompt.
2. **The probe's annex-present check is conditional** (`e2e_probe.py:106-108` — `has_annex`
   False still passes with "no annex this turn"), so the probe could print OK on a turn where
   the annex never rendered anywhere. Leg1 partially covers this but also tolerates an empty
   annex. Not rigged — all other assertions are real and falsifiable — but the headline
   assertion of the restore is soft. My independent probe confirmed the annex renders live.
3. **Both live probes showed the annex at its cap of 4.** Consistent with ADR-0047's own
   recorded caveat (0.08 margin is a reasoned pick, not re-measured; "if live annexes run at
   cap on most offer-bearing turns, drop back toward 0.05"). Two probes are not a measurement
   — flagging only that the caveat's trigger condition is worth watching in the v0.40.0 epoch.

## Validation Dimensions

- [x] 1. Mechanism revert fidelity — PASS (truths 1-5; restored `_retrieve_external` matches `4322bc7^` source exactly + `_blocked`)
- [x] 2. Blocklist preservation — PASS (truth 6; no HEAD call site lost, one gained; selftest 4b intact; engine filters at server.py:813,828; `scripts/apply-overrides.py` and `skill_guard.py` untouched by this diff)
- [x] 3. Tuned defaults + alias — PASS (truths 7-8; alias probed live in subprocess, both names kill the annex)
- [x] 4. Selftests + pull-mining removal — PASS (truths 9-10; removal verified byte-identical to pre-2a66d45)
- [x] 5. Live probe — PASS on mechanism, WARN on apparatus (truth 11; Advisories 1-2)
- [x] 6. Engine side — PASS (truths 12-13)
- [x] 7. Docs/version coherence — PASS (truths 14-15)
- [x] 8. Regression hunt — PASS (truths 16-19; vendor failure set identical at HEAD via git-archive extract, no git mutation)

## Unverifiable Items

- Whether the 12 vendor failures at HEAD were the same set *in the shipper's environment at ship time* — I reproduced the identical set against HEAD's code in this environment, which is the strongest non-mutating check available.
- The ADR-0047 tuning rationale's underlying measurements (0.05 measured, 0.10 saturation) — historical claims from prior epochs, taken as recorded; the ADR itself flags 0.08 as un-re-measured.

## Context Gaps

No context gaps.
