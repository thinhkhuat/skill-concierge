# Opus Validation Report — ADR-0052 / v0.45.0 pending changes

**Subject:** implementation + completion — pending uncommitted changes for v0.45.0 (ADR-0052), branch `main` @ `614b61ea`
**Scope:** claims C1–C8 re-verified from the repo, the tests, and the live machine; adversarial checks (over-engineering, unreported behavior changes, staleness, false-drops)
**Verdict:** **PASS** (zero blocking issues; 5 advisory findings)
**Date:** 2026-09-05
**Validator:** independent (did not author the work; work-tree untouched — all revert experiments ran in `/tmp/val-adr0052/` copies)

## Executive Summary

All eight implementer claims are CONFIRMED against code, tests, and the live machine, including the arithmetic (pre-change 59 names incl. exactly 1 phantom → post-change 83 = 58 + 25 agent-skills; name-set delta measured byte-exactly as −`examples:workflow` +25 agent-skills rows, zero collateral renames). The live enforcer merged view behaves as claimed (`agent-skills` in, `ponytail` out, RUNNING_HARNESS=claude). Five advisory findings, all documentation-accuracy or hardening nits; none blocks ship.

## Observable Truths

| # | Claim | Status | Evidence |
|---|-------|--------|----------|
| C1 | Layered enablement: exclude iff user-false AND no project layer true; project-false alone never excludes; fail-open; `SKILL_PLUGIN_LAYERED_ENABLEMENT=0` → user-file-only | CONFIRMED | `vendor/skill-search/skill_search/skills_discovery.py:269-297` (`user_false - any_true`; project loop reads only `v is True` into `any_true`; `if not SKILL_PLUGIN_LAYERED_ENABLEMENT: return user_false` at :281; `_read_json` returns None on any read error). Live machine: user file has `agent-skills@addy-agent-skills: false`; `skill-concierge/.claude/settings.local.json` has it `true` → indexed (probe shows 25 rows). |
| C2 | `_installed_plugin_entries` None only when registry unreadable; {} = positive empty; `_plugin_paths` falls back to whole cache ONLY on None | CONFIRMED | `skills_discovery.py:299-324` (None guard `not isinstance(installed, dict) or "plugins" not in installed`); `:815-821` `if entries is not None: return _claude_plugin_skill_paths(entries) + …` — no emptiness check; whole-cache glob only in the `None` branch at :823-826. Positive-empty is pinned by `test_user_disable_without_reenable_excluded` (a readable registry whose only plugin is excluded must NOT resurrect via fallback). |
| C3 | Root-relative scan: per-installPath, 2 depths, phantom guard, names from REGISTRY KEY; `examples/` and `temp_git_*` structurally unreachable | CONFIRMED | `skills_discovery.py:757-784`: globs `<root>/skills/*/SKILL.md` + `<root>/skills/*/*/SKILL.md`, guard `os.path.dirname(os.path.dirname(n)) in skill_dirs`; `forced[h] = f"{pid}:{Path(h).parent.name}"` with `pid = key.split("@",1)[0]`. `examples/…` under the live phantom dir exists on disk (`…/superpowers-developing-for-claude-code/0.3.1/examples/full-featured-plugin/skills/workflow`) and post-change names contain no `examples:*`; probe: zero `temp_git_` paths. |
| C4 | `_plugin_gate_ok` gates plugin rows + chain/ROUTE successors, claude sessions only; None filters nothing; flag=0 filters nothing; non-namespaced pass; selftest section + marker | CONFIRMED | `hooks/scripts/enforcer.py:650-665` (flag/harness/None/no-colon short-circuits); applied at `:1035` (`_chain_hint_data`), `:1330` (`_retrieve`), `:1579` (`_route_of`). Selftest section `:2989-3011` with marker `"+ plugin-enablement gate (ADR-0052) "` in the success line. Live: `python3 hooks/scripts/enforcer.py --selftest` exit 0 printing the marker; live import shows `INVOCABLE_PLUGIN_IDS` = 10 ids incl. `agent-skills`, excl. `ponytail`, `RUNNING_HARNESS='claude'`. |
| C5 | Engine suite green from clean run; 6+ new tests fail on pre-change code; no existing test weakened | CONFIRMED (nuance noted) | Clean run: `cd vendor/skill-search && venv python -m pytest tests -q` → **90 passed**, 1 warning (262s). Revert experiment in `/tmp/val-adr0052/mixed` (only `skills_discovery.py` at HEAD): all 7 new tests ERROR (`AttributeError: … has no attribute 'CLAUDE_PROJECTS_FILE'`, conftest.py:82). HEAD suite in `/tmp/val-adr0052/head`: **12 failed, 71 passed** — the "12 pre-existing failures" claim is exact; 71+12=83 old tests, +7 new = 90. No test deleted or assertion weakened: 4 pre-existing tests swapped the monkeypatched seam (`_installed_plugin_roots` set → `_installed_plugin_entries` single-entry map, same semantics); conftest only ADDS pins. Nuance: new tests fail on old code via fixture AttributeError (missing seam), not semantic assertion — but they do pin the new behavior through real `discover_skills()` fixtures. |
| C6 | Probe GATE6-OK; 25 agent-skills rows; zero `examples:`; zero `temp_git_`; ponytail retained; 83 = 59 − 1 + 25 | CONFIRMED | Probe run: exit 0, `GATE6-OK`, exactly 25 `agent-skills:*` rows, 6 `ponytail:*` rows, total 83. Independent pre-change baseline (HEAD engine, live machine): **59 names incl. exactly `['examples:workflow']`, 0 agent-skills rows** → 59 − 1 + 25 = 83. Name-set diff old→new: removed = {`examples:workflow`}, added = 25 agent-skills, nothing else. |
| C7 | driftcheck 0; version 0.45.0 in 4 manifests; CHANGELOG/README/quickstart name 0.45.0; ADR-0052 exists + indexed | CONFIRMED | `python3 scripts/driftcheck.py driftcheck.json` exit 0 ("IN SYNC"), SSOT 0.45.0 matched in marketplace.json (2×), CHANGELOG, README, quickstart, codex plugin.json; `package.json:4`, `.claude-plugin/plugin.json:3`, `.codex-plugin/plugin.json:3` all `0.45.0`; `docs/adr/0052-plugin-enablement-layering-and-root-relative-scan.md` exists and has an index row in `docs/adr/README.md` (diff). |
| C8 | Deployed runtime untouched by diff; `python3 hooks/scripts/enforcer.py --selftest` exit 0; root tests pass | CONFIRMED | `git status --porcelain` + `git diff --name-only`: 12 tracked repo files + untracked repo files only; no reference anywhere in the diff to `~/.claude/plugins/cache/skill-concierge/…` or `~/.claude/skill-concierge/venv` (the `0.44.1` strings in the diff are version-bump lines inside repo manifests). Selftest exit 0 (pyenv python3 3.12.11). Root `python3 -m pytest tests/ -q` → **19 passed**. |

## Key Dependency Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `parse_skill` | `_FORCED_PLUGIN_NAMES` | population-precedes-parse | PASS | `discover_skills` calls `discover_skill_paths()` (→`_plugin_paths` → `_claude_plugin_skill_paths` assigns the global) before any `parse_skill` (`skills_discovery.py:942-943`). Repo-wide, `parse_skill(` has exactly two production callers, both inside `skills_discovery.py` (:253 catalog, :943 main); server.py imports only `discover_skills` (server.py:57) and computes names via full passes (server.py:974). |
| `_retrieve` offer rows | `INVOCABLE_PLUGIN_IDS` | enforcer merged view | PASS | enforcer.py:560-579 merges user + `Path.cwd()/.claude/settings{.local,}.json` last-writer-wins — the per-session view; live values verified (10 ids; agent-skills in, ponytail out). |
| Catalog/external rows | `_plugin_gate_ok` | excluded upstream | PASS | Installed query carries `must_not tier=external` (enforcer.py:1314); `_visible_sidecar_names` (enforcer.py:907-945) unions only personal/plugin/project/codex/zcode/commandcode/omp scopes — no catalog scopes — so chain/ROUTE successors are never external names. |
| Overrides/keep-on | skill names | name-key stability | PASS | `scripts/apply-overrides.py:52-56` regenerates names from the same `discover_skills()`; measured name-set delta is exactly −phantom +25, so no existing key can drift on this machine. All 39 registry keys' installPath dirnames equal the registry id part (checked programmatically). |

## Blocking Issues (FAIL)

No blocking issues found.

## Advisory Suggestions (WARN)

1. **CHANGELOG/ADR cite a suite number that matches no real state.** CHANGELOG.md says "Full engine suite green: 77 passed"; measured: 71 passed pre-change (12 failed), 90 passed post-change. The ADR's "the suite is green before and after" is also misleading — the pre-change suite had 12 failures by the change's own account, and the new conftest is atomic with the engine change (old engine + new conftest = 83 fixture errors, measured). Fix the two figures/phrases before commit.
2. **Unreported edit to a historical release record.** The diff rewrites README.md's 0.44.1 line "args **direct**" → "args **hot path**" while CHANGELOG.md's 0.44.1 entry still says "args direct" — the two records now disagree, and the edit is not mentioned in the 0.45.0 changelog entry.
3. **Multi-entry registry keys: only the first entry's installPath is scanned.** `_installed_plugin_entries` does `entries[key] = …; break` after the first entry. Live case: `agent-skills@addy-agent-skills` has a user-scope 0.6.9 entry AND a project-local 0.6.8 entry (this repo); pre-change scanned both roots, post-change only 0.6.9. Verified harmless today (0.6.8/0.6.9 `skills/` sets byte-identical, diff empty), but the first-entry-is-authoritative assumption is undocumented — if Claude Code ever orders entries differently, a stale version could win silently. Worth one line in the ADR (and ideally: pick the entry whose version sorts highest, or all entries deduped by name).
4. **Stale cross-reference left inside the same diff.** enforcer.py:501-502 still says a plugin is disabled by "an explicit `false` in the merged settings `enabledPlugins` layers (absent key = enabled, matching Claude Code and `skills_discovery._installed_plugin_roots`)" — discovery now uses the union rule (user-false AND no re-enable anywhere), not the per-cwd last-writer-wins merge that sentence describes. One-line docstring fix.
5. **Dead shim + module-global notes.** `_installed_plugin_roots` (skills_discovery.py:326-332) now has zero production callers (only the stale enforcer.py:501 comment mentions it) — candidate for deletion or an explicit "kept for external callers" note. `_FORCED_PLUGIN_NAMES` staleness was audited and is bounded: wholly reassigned each pass, keyed by absolute path, and no production `parse_skill` call happens outside a discovery pass; worst case (registry unreadable mid-process) reuses the last known-good naming for paths that still exist — benign. A future caller parsing ad-hoc paths would silently get last-pass names; the contract comment at skills_discovery.py:744-753 covers this — keep it accurate if callers change.

## Validation Dimensions

- [x] Correctness — PASS. Every seam re-read in full; live-machine behavior measured (probe, enforcer import, name-set diffs).
- [x] Completeness — PASS. All 8 claims verified; every gate site (offer/chain/route) covered; selftest marker prints.
- [x] Tests — PASS. 90 engine + 19 root + selftest + driftcheck all green from clean runs; revert experiment proves the new tests bind to the new seams; HEAD baseline reproduces the claimed 12 failures exactly.
- [x] Regression safety — PASS. Deployed runtime untouched; non-Claude harness lanes (codex/omp/zcode) code paths unchanged (`_plugin_paths` keeps their globs verbatim); no name drift possible on this machine (measured).
- [x] Over-engineering — PASS with nits. The union scan is the minimal machine-global semantics ADR-0028 permits; the gate flag and kill-switches are house-style one-var reverts (~15 lines); layer reads are 62 projects × 2 files per discovery pass (reindex-time, not per-search). Nits: dead `_installed_plugin_roots` shim (#5), `Path()`-wrapping fix for codex/omp glob strings is a small bundled robustness fix (documented in-line, acceptable).
- [x] False-drop audit (`_plugin_gate_ok`) — PASS. Rows reaching the gate with a colon are plugin-scope (prefix = registry id), foreign rows already twin-gated by the SAME id set, catalog rows excluded upstream (must_not tier=external; sidecar scopes exclude catalog). A personal/project skill whose directory name literally contains ":" would false-drop, but personal names are plain dirnames and such dirs are effectively unreachable on this harness.
- [x] Unreported behavior changes — 4 found, all advisory (#1–#4 above plus the multi-entry scan #3).

## Unverifiable Items

- The intended reading of the ADR sentence "the suite is green before and after" (advisory #1) — under the only two readings I could construct, one is false (pre-change suite had 12 failures) and the other (conftest-fix independence) is false because conftest+engine are atomic. Asked-for clarification, not a defect in code.
- Claude Code's guarantee that the first registry entry per key is the authoritative install — not documented anywhere I could read; flagged as assumption (#3).

## Context Gaps

No context gaps. All experiments ran against the live machine and a full HEAD copy of the vendored engine under `/tmp/val-adr0052/` (no working-tree modification).

**VERDICT: PASS**
