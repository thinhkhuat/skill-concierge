# Opus Validation Report — SKILL-FIRST Gate Upgrade

**Subject:** implementation (SKILL-FIRST prompt-gate upgrade — 3 prompt surfaces + telemetry)
**Scope:** `hooks/doctrine/skill-first.md`, `hooks/scripts/enforcer.py`, `scripts/analyze.py`, `skills/skill-usage-audit/scripts/audit_skill_usage.py` (applied, uncommitted working-tree changes)
**Verdict:** PASS_WITH_CONCERNS
**Date:** 2026-07-01
**Evidence examined:** 4 changed files + 2 context reports + `doctrine.py` + 40 live transcripts (1,976 user records)

---

## Executive Summary

The upgrade is correctly applied, internally consistent across all three prompt surfaces, and backed by data: all three selftests pass, the false-SKIPPING metric reproduces the independent 68% diagnostic, and the design philosophy held (no runtime post-turn detector added — the changes are additive context plus offline measurement only). The one substantive concern is the deliberately-accepted D1 concession: point 4 opens a search-free `SKIPPING: none` for a "no-task" class. The closure is reasonably tight, but two residual seams remain. Neither is a blocking defect; both are the named cost of the owner-locked concession.

---

## Observable Truths

| # | Claim | Status | Evidence |
|---|-------|--------|----------|
| 1 | Point 4 makes `SKIPPING: none` lawful for a CLOSED no-task class | VERIFIED | `skill-first.md:39-48` |
| 2 | "Candidates present → task present → exemption void" link exists | VERIFIED | `skill-first.md:43` |
| 3 | Three named dodge-classes still forbidden | VERIFIED | `skill-first.md:46-48` |
| 4 | MANDATE agrees with doctrine | VERIFIED | `enforcer.py:242-248` |
| 5 | `_ranked_mandate()` agrees with doctrine | VERIFIED | `enforcer.py:354-362` |
| 6 | NO post-turn detector added | VERIFIED | 4 files changed, none a Stop/PostToolUse hook; enforcer is UserPromptSubmit; analyze/audit are offline scripts |
| 7 | Three `--selftest` assertions updated `"Multiple candidates"`→`"RELATIVE rank"` | VERIFIED | `enforcer.py:529-533,588`; diff shows exactly 3 sites |
| 8 | `analyze.py` adds "substantive" compliance line | VERIFIED | `analyze.py:274-275` |
| 9 | `audit` adds false-SKIPPING detector | VERIFIED | `audit_skill_usage.py:101-116,140-204,236-243` |
| 10 | search_skills pre-filter bug fixed | VERIFIED | `audit_skill_usage.py:150` + block handler `:185` |
| 11 | False-SKIPPING ~68% (matches independent diagnostic) | VERIFIED | `audit --since 2026-06-26` → 64/94 68%; diagnostic 65/96 68% |
| 12 | keep-off generator yields `keep_off: []` post-enrichment | VERIFIED | `build_keep_off.py` → 0 suppressed, data_sufficient true, 121 offered-turns |

---

## Key Dependency Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `skill-first.md` body | model context | `doctrine.py` SessionStart | WIRED | emits 4,486 chars between markers; new "no task to skill" / "this class does NOT apply" / "USING never takes none" all present in emitted output |
| MANDATE / `_ranked_mandate` | model context | `enforcer.py` UserPromptSubmit | WIRED | injected via `_inject()`; main() paths verified |
| `_skip_verdicts` | audit report | `audit()` turn loop | WIRED | false_skip/lawful_skip flow to print `:260-263` |
| turn-boundary heuristic | per-turn flags | raw-line substring | VERIFIED | 0 mismatches vs JSON truth across 1,976 user records / 40 files |

---

## Blocking Issues (FAIL)

No blocking issues found.

---

## Advisory Suggestions (WARN)

1. **No-candidate turns lack the mechanical backstop for point 4.** The "candidates present → task present → exemption void" link (`skill-first.md:43`) only fires when the enforcer injected candidates. On getaway (~16%) and fallback (~19%) turns the enforcer is silent or injects MANDATE with no candidate list (`enforcer.py:476-477, 441-447`), so the partition rests entirely on the content-based class definition. A motivated model has more self-judgment room there than under the original "always search before any skip" rule. This is the inherent, owner-accepted cost of the D1 concession (named in `craft-review.md:87-93` as "Philosophy-risk"). The class is content-defined ("no task content" / "no work to do"), so a genuine task still does not honestly fit — the seam requires self-deception, which the original design could not prevent either. No fix recommended (fixing it re-imposes the absolute rule D1 deliberately relaxed).

2. **The "agent-to-agent dispatch" bullet shares surface vocabulary with a documented dodge.** `skill-first.md:42` exempts "an agent-to-agent dispatch that hands you no work to do." The transcript diagnostic (`transcript-analysis.md:87`) shows a real false-skip from a *dispatching* agent ("direct subagent dispatch (Agent tool)... no skill governs 'hand this prompt to a tester'"). The qualifier "hands **you** no work" correctly scopes to the **receiving** side and excludes the dispatcher, and clause 2 catches the common case (substantive dispatch prompts → candidates offered → exemption void). But a motivated model could anchor on "agent-to-agent dispatch" and underweight the qualifier on a no-candidate turn. Optional minimal hardening: add the dispatcher case to the named dodges — "*Dispatching* work to a subagent is a task you perform → SEARCH; this bullet is only the *receiving* side."

3. **False-SKIPPING metric is self/meta-inclusive (already disclosed).** The 68% is computed before meta-session exclusion (`audit_skill_usage.py:266` says so; report "Honest Unknowns #1/#2" flag it). Quoted-doctrine contamination is empirically negligible (see below). No action needed.

---

## Validation Dimensions

- [x] **NEW-LOOPHOLE CHECK** — PASS_WITH_CONCERNS. The closed class is narrow and content-defined; the "candidates present → exemption void" link genuinely closes the candidate-bearing case; the four observed taxonomy buckets (`transcript-analysis.md:96-99`) are all mapped (system/harness ~25% is now the lawful class; the other three named forbidden). No 4th obvious rationalization is left wide open; residuals are the two advisories. **No contradiction** between point 4 and points 2/3 — they partition on task-presence, wired to the enforcer signal. Evidence: `skill-first.md:39-48`.

- [x] **Cross-surface consistency** — PASS. No rule stated one way in doctrine and differently per-turn. `_ranked_mandate` correctly omits the no-task escape (only fires when candidates present, where the exemption is void — a consistency strength). Both per-turn strings cross-ref "[full order: session start]". Evidence: `skill-first.md:39-65`, `enforcer.py:242-248`, `enforcer.py:354-362`.

- [x] **Selftest integrity** — PASS. Ran all three: enforcer/analyze/audit all OK. `(75%)`/`(25%)` preserved and reflect real math; share computation unchanged. The `"RELATIVE rank"` checks are meaningful, not vacuous: the 2-candidate case requires the phrase present, both lone cases require it absent — breaking the note text or multi-gating fails them. Audit verdict pins all three branches.

- [x] **Telemetry correctness** — PASS. (a) pre-filter fix verified — `"search_skills" in line` (`:150`) lets the MCP tool_use record through (it was dropped before: lowercase name matched no case-sensitive marker); handler `:185` sets `saw_search`. (b) turn-boundary heuristic: 0 mismatches / 1,976 user records / 40 files vs parsed JSON truth. (c) doctrine-echo: of 51 assistant blocks with a line-start SKIPPING, 0 also carried line-start USING+SEARCH; regexes scan only assistant text, not injected additionalContext. Independent convergence (64/94 vs 65/96) confirms the metric. Trustworthy, caveated only as self/meta-inclusive.

- [x] **keep-off decision** — PASS (no real fix skipped). Generator (ADR-0011 mechanism; "DO NOT hand-edit") yields `keep_off: []`, data_sufficient true, 121 offered-turns. In the post-enrichment window the 0-take offenders (opus-validate 0/12, ctx-doctor 0/12, hooks-audit 0/11, session-history 0/10, caveman-stats 0/9) all sit below the 15-offer threshold; review-docs/skill-search dropped out of top offers. F4's counts (24/23/22) spanned the pre-enrichment window. Hand-editing would violate the contract and suppress skills that no longer chronically over-trigger. F4's other levers (GETAWAY_FLOOR/ADR-0009, ITEM_FLOOR, intent retrain) are ADR-gated and out of this pass's scope — correctly untouched.

---

## Unverifiable Items

- **Behavioral effect** — whether the rewrite actually lowers the 68%/91% in future sessions is unmeasured (no post-change transcript window exists; the change is uncommitted). Design is sound; outcome pending data.
- **Organic-only false-SKIPPING rate** — not separable without a `project_path` ledger field (report T2 / Honest-Unknown #1); the 68% is all-sessions.

## Context Gaps

- The four changed files are uncommitted working-tree changes (git status `M`), not yet released; no version bump / CHANGELOG entry for this specific edit. Consistent with validating an applied-but-unshipped change.

---

## Commands Run (evidence)

```
python3 hooks/scripts/enforcer.py --selftest                              → OK
python3 scripts/analyze.py --selftest                                     → OK
python3 skills/skill-usage-audit/scripts/audit_skill_usage.py --selftest  → OK: false-SKIPPING verdict
python3 skills/skill-usage-audit/scripts/audit_skill_usage.py --since "2026-06-26"  → 64/94 68%
python3 scripts/build_keep_off.py --out /tmp/ko.json                      → 0 suppressed, keep_off: []
python3 scripts/analyze.py --since "2026-06-28 16:05:00"                  → offered-turn dodge 89%, offenders <15 offers
```
