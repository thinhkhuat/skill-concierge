---
title: v0.47.0 — ADR-0054 harness-message lane + usage-audit fixes
date: 2026-09-15
summary: "First epoch-scoped usage audit turned into a release: harness text no longer gets previews, named skills lead, timeouts widened, keep-off activated; commit a44d356"
---

# v0.47.0 — ADR-0054 harness-message lane + usage-audit fixes

## What happened
An epoch-scoped audit (v0.46.0, 2026-09-06 → 09-14; `plans/reports/audit-260914-2325-concierge-usage-strengthen.md`, two independent reviews) showed 344 of 581 enforcer decisions were on harness-generated text (task notifications, OMP `omp-msum` summaries, cross-session messages) and 168 of those got a full preview; the deterministic-route and keep-off layers were inert; every "outage" fallback was censoring at the timeout cap; `dsh-personal` re-roots leaked into Claude offers as bare twins; `analyze.py` inflated the fallback rate 3×.

## Root cause
No shape check for harness prompts existed in `hooks/scripts/enforcer.py`; routes were default-OFF and ran after embed; keep-off had never been regenerated since 2026-06-29 and was not wired into doctor; Claude's foreign-scope tuple omitted `dsh-*`/`cline-*`; `analyze.py` counted the `fallback` field truthy.

## Changes (commit a44d356, ADR-0054)
- Harness-message lane before any I/O (`ENFORCER_HARNESS_SKIP`, band `harness_skip`, 4th SKILL-CHECK leg, no chain hint; selftest 14).
- Routes config-driven, default ON, computed before embed; named skill leads at 1.0 and survives a timeout; honours keep-off/blocklist and the ADR-0034 invocability filter (selftests 6/6b/6c).
- Timeouts 0.5 s / 0.25 s. Keep-off in the durable home with doctor check + `--fix` refresh + `setup.sh` build, harness offers excluded, keep-on exempt.
- `dsh-personal`/`cline-personal` foreign everywhere; foreign annex skips re-rooted twins. `OUTAGE_FALLBACKS` in analyze.py. keep-on +8; `ENFORCER_ANNEX_MARGIN=0.0` Claude trial.

## Verification
enforcer + analyze selftests, pytest 21, doctor, live stdin probes, 4 adversarial probes; tester PASS; code review APPROVE-WITH-FIXES (2 MAJOR, 4 MINOR, 3 NIT — all applied). Unlazy gates G1–G8 met. Adapters omp/dsh/cline/commandcode/zcode installed at 0.47.0.

## Lessons
- Harness-injected prompts were the single largest source of enforcer noise and of every "chronic never-taken" skill; segment them out of every ledger rate.
- A selftest `global` statement must precede every use of the name in the function — the new 6c block had to move to the end of `_selftest`.
- Ledger-only keep-off penalizes skills taken inline (USING without the Skill tool); exempt keep-on members.

## Next steps
Owner: `/plugin marketplace update` (Claude Code, Codex), restart, `doctor --fix` once. After ~1 week: epoch-watch v0.47.0 W1–W6, then the R9 decision on ROUTE projection / multi-intent.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
