# Opus Validation Report

**Subject:** implementation (skill-concierge usefulness-rate upgrades, branch `feat/usefulness-rate-upgrades-0.12.0`)
**Scope:** the 6-commit diff `main...HEAD` — AUTHORIZED-SKIP enforcer tier, library doctrine, audit SKILL-CHECK patch, body-derived trigger points — against plan `260704-0415-usefulness-rate-upgrades/`, ADR-0015/0016, and the AGENTS.md hook/fail-silence + vendored-engine guardrails.
**Verdict:** PASS
**Date:** 2026-07-04
**Evidence Files Examined:** 12 (4 source, doctrine, 4 ADR/VENDORED/decisions, README/AGENTS/CHANGELOG, 2 test files) + 3 selftests + vendor pytest + live transcript scan

## Executive Summary
All four claimed behaviors are implemented as specified and every adversarial check passes: the marker literal is byte-identical across the two files, both feature legs are fail-silent and default-ON with a one-var revert, the flag-off paths are byte-identical to prior behavior (verified from code and by running the selftests both ways), and body triggers are separate MAX-pool points with the base vector untouched. Zero blocking issues. Three advisories, none affecting shipped runtime behavior: the audit's marker-join is over-broad (the identical `SKILL-CHECK:` literal also lives in the always-injected doctrine and in feature-discussion prose the audit scans), a stale "(flat point-count)" label survives in a decision-log heading, and the version bump is still pending (deferred to Phase-8 go-live).

## Observable Truths
| # | Claim | Status | Evidence |
|---|-------|--------|----------|
| 1 | AUTHORIZED-SKIP: getaway + intent_skip legs inject a `SKILL-CHECK:` line, gated ON by `ENFORCER_AUTHORIZED_SKIP` (default ON) | ✓ | `enforcer.py:78,325-335,515-522,528-531`; selftest §7 asserts 2 injects ON / silent OFF |
| 2 | Getaway line carries find-skills escalation + get_skill nudge + interpolated top/floor | ✓ | `enforcer.py:312-318`; selftest asserts `find-skills`, `get_skill(`, `0.30`/`0.45` present |
| 3 | Marker constant `AUTHORIZED_SKIP_MARKER = "SKILL-CHECK:"` | ✓ | `enforcer.py:81` |
| 4 | Library doctrine: asymmetric skip cost, burden-of-proof on SKIP, find-skills escalation, consistent with the marker | ✓ | `skill-first.md:73-92` |
| 5 | Audit: a `SKILL-CHECK:`-carrying turn is `authorized_skip`, excluded from false-SKIPPING; same literal | ✓ | `audit_skill_usage.py:55,106-126,171,234`; selftest OK; marker byte-identical (rg) |
| 6 | Body triggers: `_extract_body_triggers` mines labeled sections; `_trigger_phrases` folds into MAX-pool, deduped, capped COMBINED at `_TRIG_MAX`; gated by `SKILL_BODY_TRIGGERS` (default ON); recorded in VENDORED.md | ✓ | `skills_discovery.py:66-104,145`; `server.py:88,276-293,385`; `VENDORED.md:41-51` |
| 7 | Hook fail-silence: the `.format()` + `_inject` on both new legs cannot raise out of the hook | ✓ | `enforcer.py:328-335` (inner try/except) nested in `main()` `456-540` (outer) |
| 8 | Cross-file marker byte-for-byte identical in enforcer + audit | ✓ | `rg -o` → both `"SKILL-CHECK:"` |
| 9 | `ENFORCER_AUTHORIZED_SKIP=0` restores prior silence exactly; `SKILL_BODY_TRIGGERS=0` yields byte-identical description-only triggers | ✓ | code (`enforcer.py:329-330`; `server.py:285-293` re-slices already-capped list) + both selftests pass OFF; unit test `test_trigger_phrases_body_off_is_description_only` |
| 10 | No base-vector blending: `_skill_text` untouched; body triggers feed only the trigger-point path | ✓ | diff shows `_skill_text` (`server.py:296-298`) unchanged; `body_triggers` feeds `_trigger_phrases` → separate points only |
| 11 | Incremental-reindex safe: stable per-(skill,slot) ids + per-phrase content-hash refresh on body edit, orphaned slots deleted | ✓ | `server.py:237-245,377-406` (`changed`/`removed` on content_hash) |
| 12 | Combined cap: dedupes body vs description (case-insensitive), caps COMBINED at `_TRIG_MAX`, drops no description phrase | ✓ | `server.py:276-293`; unit tests dedup + combined-cap; description phrases occupy first ≤12 slots |
| 13 | Point-count stated as bounded growth 2231→3570 (+60%), NOT "flat" | ✓ (1 stale label) | ADR-0016:41-46, VENDORED.md:47, CHANGELOG:28, journal, `server.py:276-284` all state +60%; **stale exception:** `decisions-audit-log.md:81` heading still reads "(flat point-count)" |
| 14 | All-ON override documented honestly with under-gating risk (D1, ADR-0015) | ✓ | `decisions-audit-log.md:23-42`; ADR-0015:42-50,65-71 |
| 15 | Integration test failure is pre-existing on `main`, not caused by this change | ✓ (by construction) | test byte-unchanged in diff; `main` has `MULTIVECTOR` ON, no `_trigger_phrases` → `embedded`(points)≠`indexed`(skills) → assertion already false on `main` |

## Key Dependency Verification
| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `enforcer.py` getaway/intent legs | `_authorized_skip_inject` | `SKILL-CHECK:` line | ✓ WIRED | called at `515-522`/`528-531`; helper `325-335` |
| `enforcer.py` | `audit_skill_usage.py` | literal `"SKILL-CHECK:"` | ✓ IDENTICAL | byte-for-byte (rg) |
| `skills_discovery.parse_skill` | `server._trigger_phrases` | `body_triggers` field | ✓ WIRED | `skills_discovery.py:145` → `server.py:285`; used at `build_index` `385` |
| `server._skill_text` (base vector) | body triggers | — | ✓ ISOLATED | untouched; no blend path |
| vendor source | installed engine venv | `pip install vendor/skill-search` | ✓ IDENTICAL | `diff site-packages/skill_search/server.py vendor/...` → identical (so selftests + live reindex ran the new code) |
| `hooks/doctrine/skill-first.md:88` | audit `saw_marker` | `~/.claude/projects/**/*.jsonl` | ⚠ SEE ADVISORY 1 | doctrine (injected every session) contains the identical literal → contaminates the join |

## Blocking Issues (FAIL)
No blocking issues found.

## Advisory Suggestions (WARN)
1. **Audit `saw_marker` join is over-broad (measurement precision, not runtime correctness).** `audit_skill_usage.py:171` sets `saw_marker=True` for **any** transcript line containing `SKILL-CHECK:`, independent of role/record-shape. But the identical literal also appears in (a) the SessionStart doctrine `hooks/doctrine/skill-first.md:88` (injected into **every** session by `doctrine.py`), and (b) any assistant prose / tool-result / file-read that discusses the feature. Empirically confirmed: all 8 transcript files carrying the marker are this project's dev/meta sessions, and 41 marker-lines co-occur with doctrine/feature-discussion text — i.e. the current hits are overwhelmingly NON-enforcer sources. Consequence: a turn that declared `SKIPPING` without a real search can be misclassified as `authorized_skip` (lawful) instead of `false_skip`, biasing the hardest-rule metric in the favorable direction — worst in the meta/dogfood sessions used to judge the feature. **Bounding:** the SessionStart-doctrine source specifically is neutralized because `saw_marker` resets at each user-prompt boundary (`audit_skill_usage.py:160`) and that injection precedes turn 1; mid-turn prose/tool-result sources are NOT neutralized. This was a **deliberate, documented** choice (comment at `169-170`: "Raw-line check … robust to exactly where the enforcer's additionalContext lands"). Shipped enforcer/doctrine/behavior are unaffected — this is diagnostic-tool precision only. Recommend anchoring the match to the enforcer's UserPromptSubmit additionalContext record shape (or excluding the doctrine-dump line), or documenting the limitation in the audit SKILL.md.
2. **Stale "(flat point-count)" label survives in one heading.** `decisions-audit-log.md:81` heading still reads "D6 … (flat point-count)" though the same entry's D8 correction (`88-91`) and ADR-0016/VENDORED/CHANGELOG/journal all correctly retract "flat" and state bounded +60%. The substantive claim is correct everywhere it matters; only the heading label is stale. Cosmetic.
3. **Version bump still pending (go-live prerequisite).** CHANGELOG entry is under `[Unreleased]` and `.claude-plugin/plugin.json` + `marketplace.json` remain at `0.11.1` (untouched on this branch). This is consistent with validating **pre-merge** — D2/D5 defer the bump to Phase-8 go-live (local main, hold push, operator pushes). Flagged so the repo's HARD versioning rule (bump `plugin.json` **and** `marketplace.json` together + promote the CHANGELOG header to `[0.12.0]`) is honored at merge and not forgotten.

## Validation Dimensions
- [x] Claim conformance (4 claimed behaviors) — PASS
  - Evidence: Observable Truths 1-6; all four implemented as specified.
- [x] Hook fail-silence (AGENTS.md guardrail) — PASS
  - Evidence: `enforcer.py:328-335` wraps `.format()`+`_inject` in try/except, nested inside `main()` outer try (`456-540`); no new path can raise or block.
- [x] Cross-file marker contract — PASS
  - Evidence: `rg -o` → `"SKILL-CHECK:"` byte-identical in both files.
- [x] Flag off-paths byte-identical — PASS
  - Evidence: code review + `enforcer.py --selftest` OK exit 0 under ON and `ENFORCER_AUTHORIZED_SKIP=0`; `SKILL_BODY_TRIGGERS=0` path re-slices an already-`_TRIG_MAX`-capped list → identical list/ids/hashes; unit test confirms.
- [x] No base-vector blending (ADR-0012 anti-pattern) — PASS
  - Evidence: diff shows `_skill_text` unchanged; `body_triggers` reaches only `_trigger_phrases` → separate trigger points.
- [x] Incremental-reindex safety — PASS
  - Evidence: `_point_id("{name}::trig::{i}")` stable; `_content_hash(ph)` per phrase; `changed` re-embeds on hash change, `removed` deletes orphaned slots (`server.py:391-406`); body_triggers extracted from FULL body so late sections still refresh (`skills_discovery.py:141-145`).
- [x] Combined-cap correctness — PASS
  - Evidence: `server.py:285-293` — description phrases first (≤12), body deduped case-insensitively, `[:_TRIG_MAX]`; description phrases never dropped by the combined logic; unit test `test_trigger_phrases_combined_cap_respects_trig_max`.
- [x] Doc↔code / measured-facts consistency — PASS (advisory 2)
  - Evidence: point-count +60% consistent across ADR-0016/VENDORED/CHANGELOG/journal/code; arithmetic checks (2231+1339=3570; 3570−488=3082 trigger pts); README/AGENTS flag defaults + revert semantics match code. Lone stale heading label noted.
- [x] All-ON override disclosure — PASS
  - Evidence: D1 + ADR-0015 disclose proposal-recommended-OFF, operator override to ON, under-gating risk, and 5 mitigations (kill-switches, find-skills escalation, audit split, Phase-7 smoke).
- [x] Pre-existing-test attribution (D7) — PASS
  - Evidence: established by construction (see Observable Truth 15); avoided a `main` checkout under read-only constraint.
- [x] Selftests / unit gate executed — PASS
  - Evidence: enforcer selftest OK (ON + OFF, exit 0); audit selftest OK; vendor `pytest -m "not integration"` → **29 passed, 1 deselected**.

## Test / Command Outputs (run by this validator)
```
$ python3 hooks/scripts/enforcer.py --selftest
enforcer --selftest OK: refusal guard (5 fire / 6 silent) + ranked-mandate %-share
+ actionability imperative-veto (17 fire / 12 off) + keepoff-drop + gap-collapse
+ per-skill-tau/deterministic-routes (default-inert) + authorized-skip tier (inject-on/silent-off)
EXIT=0

$ ENFORCER_AUTHORIZED_SKIP=0 python3 hooks/scripts/enforcer.py --selftest
enforcer --selftest OK: ... + authorized-skip tier (inject-on/silent-off)
EXIT=0

$ python3 skills/skill-usage-audit/scripts/audit_skill_usage.py --selftest
audit --selftest OK: false-SKIPPING verdict
EXIT=0

$ ~/.local/share/skill-concierge/venv/bin/python -m pytest vendor/skill-search/tests/ -m "not integration" -q
29 passed, 1 deselected in 0.79s

$ rg -o 'AUTHORIZED_SKIP_MARKER = "[^"]+"' hooks/scripts/enforcer.py skills/skill-usage-audit/scripts/audit_skill_usage.py
hooks/scripts/enforcer.py:AUTHORIZED_SKIP_MARKER = "SKILL-CHECK:"
skills/skill-usage-audit/scripts/audit_skill_usage.py:AUTHORIZED_SKIP_MARKER = "SKILL-CHECK:"

$ diff <installed site-packages>/skill_search/server.py vendor/skill-search/skill_search/server.py
IDENTICAL

$ ~/.local/share/skill-concierge/venv/bin/python -m pytest vendor/skill-search/tests/ -m "integration" -q
1 failed  —  assert (488 > 0 and 3570 == 488)   # embedded(points)=3570 != indexed(skills)=488
# PRE-EXISTING: main has MULTIVECTOR ON + no _trigger_phrases -> same embedded!=indexed on main (2231!=488)

$ rg "SKILL-CHECK:" ~/.claude/projects/ -g '*.jsonl' | rg -c 'AUTHORIZED-SKIP tier|library doctrine|burden of proof on SKIP'
41   # marker lines co-occurring with doctrine/feature-discussion text (advisory 1)
```

## Unverifiable Items
- **Live offered-turn adoption A/B** for either feature — requires a post-deploy organic-traffic window; ADR-0015:57 and D1(e) already record this as an open post-ship follow-up. Not a defect of this change; the eval-universe caveat (AGENTS.md/`docs/caveats.md`) makes a quantitative body-trigger recall A/B non-meaningful here, as the task noted.

## Context Gaps
No context gaps. All four source files, the doctrine, both ADRs, the decisions-audit log, VENDORED.md, README/AGENTS/CHANGELOG diffs, and both new test files were read directly; all required commands were executed against the live engine venv and index.
