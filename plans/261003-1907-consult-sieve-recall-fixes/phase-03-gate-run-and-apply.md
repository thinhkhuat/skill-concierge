---
title: "Phase 3: Held-out gate run and apply"
status: todo
---

# Phase 3: Held-out gate run and apply

<!-- Updated: Red Team + Validation Session 1 - old phases 4 and 5 merged; flip on pass (D3); SKILL.md edited only for passing parts, no write-then-revert (F1); combination gate (F10); conditional release (F1) -->

## Goal

This phase does four things, in order:
1. Runs the frozen held-out gate once.
2. Applies the results. Every flag whose decision passes, and that the combination rule supports, is turned on by default in the same run (Thinh's D3). Only the doctrine parts that passed are written into SKILL.md.
3. Documents both flags whatever the outcome.
4. Releases 0.58.0 with ADR-0078, but only if at least one default flips.

Commit, push and the redeploy wait for Thinh's order.

## Context (re-checked 2026-10-04)

**Version and numbering:**
- The current version is 0.57.1 (`.claude-plugin/plugin.json:3`; `CHANGELOG.md:6`).
- The next free ADR number is 0078 (`docs/adr/` ends at `0077-keep-off-map-is-consent-only.md`).
- The newest epoch-watch section is v0.57.0 (`docs/epoch-watch.md:16`).

**Where query-time flags are documented today.** `SKILL_SEARCH_COMPLEMENT` is described in `AGENTS.md`, `CLAUDE.md` and `README.md` (grep, 2026-10-04). The repo rule is that every runtime flag is listed in AGENTS.md *Runtime flags* and in the CLAUDE.md governance-flags line, so both new flags are documented even if they stay OFF.

**W34's baseline.** W34 measures the consult fit matrix against "sieve order" (`scripts/consult_fit.py:309`, `"b": [c["name"] for c in inp["candidates"]]`). A default flip changes that order, so the flip time becomes a W34 epoch boundary.

**SKILL.md steps 1-2** are `skills/consult/SKILL.md:24-44`. The doctrine texts that may be inserted are the constants `PART_TASK`, `PART_HOW`, `PART_SPLIT` and `CAP_NOTE` in `scripts/sieve_recall.py`, fixed in phase 1. There is also a fifth line, the `blocks` note, which is a fixed string. It is inserted only if `SKILL_CONSULT_SLOTS` flips ON: "When the response carries `blocks`, the first `blocks.installed` rows are installed skills and the rest are externals; rank both on fit."

**Deployment facts:**
- A code default reaches the live engine through the shared-venv resync on a newer plugin version (`bin/skill-search-mcp:55-116`).
- Doctor's "Engine freshness" row (`scripts/doctor.py:470-495`) WARNs until then.
- `doctor --fix` and `./setup.sh` stay forbidden until release.

## Files to Create / Modify

| File | When | Owner |
|---|---|---|
| `plans/261003-1907-consult-sieve-recall-fixes/reports/phase-03-gate-raw.txt`, `phase-03-gate-verdict.md` | Always | Phase 3 |
| `AGENTS.md`, `CLAUDE.md`, `README.md` | Always: the two flags, their default after this run, "read per call; a running server needs an env edit and restart; not in `ENGINE_ENV_KEYS`" | Phase 3 |
| `vendor/skill-search/skill_search/server.py` | Only the default string of a flag that flips | Phase 3 (after phase 2) |
| `skills/consult/SKILL.md` | Only the passing doctrine parts (plus `CAP_NOTE` with task or how, plus the `blocks` line if slots flip) | Phase 3 |
| `tests/test_consult_doctrine.py` | Only if a doctrine part ships | Phase 3 |
| `docs/adr/0078-consult-sieve-recall.md`, `docs/adr/README.md`, `docs/epoch-watch.md`, `CHANGELOG.md`, `openwiki/quickstart.md`, `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `.codex-plugin/plugin.json`, `package.json` | Only if at least one default flips | Phase 3 |

This phase runs alone, after phases 1 and 2.

## Requirements

1. **Preconditions:**
   - `gate --check-freeze` passes: every sha256 in the manifest matches its file.
   - Phase 2's tests pass.
   - `python3 -m pytest tests/ -q` has been recorded before any change in this phase, as the comparison point.
2. **One run.** The held-out gate runs once, in the background, with its output written to `phase-03-gate-raw.txt`. The report records the `HEAD` hash, `git diff --stat` and the sha256 of `server.py`. An aborted run, for example an index-lock abort, is repeated and logged as a new attempt with its reason. A completed run stands.
3. **Combination (F10).** If more than one decision passes, the harness runs `gate --combine <passing flags and parts>` once and applies the combination rule from phase 1 R5. Only what the combination supports is applied.
4. **Flip on pass (D3).** For each supported flag, the default string in its reader changes from `"0"` to `"1"`, without a further question. FAIL and INSUFFICIENT keep it `"0"`.
5. **SKILL.md, write only what passed (F1):**
   - Supported doctrine parts are inserted verbatim into steps 1-2, in this order: task sentence, then process query, then sub-goals.
   - `CAP_NOTE` goes in if the task or how part ships.
   - The `blocks` line goes in if slots flip ON.
   - The step-2 example call is updated to match.
   - Nothing else changes, and nothing is written and later reverted.
   - `metadata.version` (`:8`, `0.1.0`) becomes `0.2.0` only if a doctrine part ships.
6. **The one doctrine test.** If a doctrine part ships, `tests/test_consult_doctrine.py` holds one test, `test_shipped_doctrine_text_equals_evaluated_text`. It asserts that each shipped constant from `scripts/sieve_recall.py` appears verbatim in SKILL.md.
7. **Conditional release (F1).** Only if at least one default flips:
   - version 0.58.0 in the four manifests, README and openwiki quickstart, plus a CHANGELOG entry;
   - ADR-0078 with the evidence, the pre-registered rules, the raw verdicts (doctrine marked "proxy"), the fidelity table, what flipped, the deployment path and the rollback;
   - an index row in `docs/adr/README.md`;
   - an epoch-watch v0.58.0 section that states the epoch start and names the flip time as W34's epoch boundary. It adds no new watch items.

   If nothing flips, there is no version bump and no ADR. The verdict report is the record.
8. **Docs sweep (RULES [75]).** If RRF flips, update ADR-0049's sieve description through ADR-0078 (ADRs are immutable), the `consult_candidates` docstring (already done in phase 2), and any page `rg -n "MAX-pool" skills/consult openwiki docs AGENTS.md CLAUDE.md README.md` shows describing the consult sieve.

## Implementation Steps

1. Check the preconditions (requirement 1).
   Check: `gate --check-freeze` prints `manifest OK` and both constants (0.7, 60).
2. Run `~/.claude/skill-concierge/venv/bin/python3 scripts/sieve_recall.py gate --composites > plans/261003-1907-consult-sieve-recall-fixes/reports/phase-03-gate-raw.txt 2>&1` in the background, with a timeout, and watch the file (RULES [17]).
   Check: the file holds two identical index-lock lines, five `VERDICT:` lines (doctrine ones marked `proxy`) and the fidelity table.
3. If two or more decisions pass, run `gate --combine …` and append its output to the same file.
   Check: one `COMBINED:` line.
4. Write `phase-03-gate-verdict.md`:
   - the raw lines, quoted;
   - the decisions and what is applied;
   - every lost case, by label, for review;
   - the reported-only numbers: recall@40, English-only, process-skill group, offered and unknown groups, fidelity.

   Check: every number in the verdict report appears in `phase-03-gate-raw.txt`.
5. Apply requirements 4-6.
   Check: `grep -n 'os.environ.get("SKILL_CONSULT_' vendor/skill-search/skill_search/server.py` shows `"1"` exactly for the applied flags. `python3 -m pytest tests/test_consult_doctrine.py -q` passes when it exists.
6. Document both flags in AGENTS.md, CLAUDE.md and README.md.
   Check: `grep -c "SKILL_CONSULT_SLOTS" AGENTS.md CLAUDE.md README.md` is at least 1 in each.
7. If a default flipped, do requirement 7 and the sweep in requirement 8.
   Check: `python3 scripts/driftcheck.py driftcheck.json` exits 0.
8. Run the verification block below. Then stop: commit, push, the redeploy and the restart wait for Thinh.

## Tests

- `tests/test_consult_doctrine.py::test_shipped_doctrine_text_equals_evaluated_text` (only if a doctrine part ships). It fails if SKILL.md drifts from the text the gate measured.
- Every test from phases 1 and 2 runs again here.

## Verification

```bash
cd /Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge
python3 -m pytest tests/ -q                     # compare with the run recorded in step 1
(cd vendor/skill-search && ~/.claude/skill-concierge/venv/bin/python3 -m pytest tests/ -q)
python3 scripts/driftcheck.py driftcheck.json
python3 scripts/doctor.py                       # Engine freshness WARN expected until the redeploy; nothing else new
```

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Temptation to re-run after a FAIL | Medium | High | A completed run stands; only aborted runs repeat, logged with their reason |
| The root suite has unrelated failures (the last release saw 20 from the Codex installer's uncommitted-version guard) | Medium | Low | Compared against the run recorded in step 1 |
| A flipped default does not reach live servers until the resync and a restart | High | Low | Expected; the verdict report and ADR state the path |
| A doctrine part ships on a proxy verdict that real agents do not reproduce | Medium | Medium | Verdict labelled "proxy"; the fidelity table shows how far the generator tracks real queries |
| Shipping doctrine without a release leaves it unreleased (plan.md, unresolved question 1) | Medium | Low | Recorded in the verdict report |

## Rollback

- **A flipped default:** set the variable to `0` in each harness's MCP env and restart that server, or revert the one default line and release.
- **SKILL.md:** back up first, then remove the inserted lines, delete `tests/test_consult_doctrine.py`, and restore `metadata.version`.
- **Release files:** revert the version bump and the CHANGELOG entry together, because driftcheck checks them as a set.
- **ADR-0078:** it is not deleted. A later ADR supersedes it.
