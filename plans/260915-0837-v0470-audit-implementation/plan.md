# v0.47.0 — implement the usage-audit recommendations

Source: `plans/reports/audit-260914-2325-concierge-usage-strengthen.md` (reviewed: adversarial PASS-WITH-CORRECTIONS, over-engineering 8/10 KEEP + R2/R7 simplified). Status: IN PROGRESS.

## Phases

| # | Scope | Files | Status |
|---|---|---|---|
| P1 | Enforcer: R1 harness-message lane (`ENFORCER_HARNESS_SKIP`, band `harness_skip`, 4th SKILL-CHECK leg, no chain hint); R2 routes default ON, `_route_hits` runs before embed and survives fallback, named skill leads even when retrieved; R3 defaults 0.5 s / 0.25 s with calibration note; R7 `dsh-personal`/`cline-personal` in every harness's foreign tuple, compound labels, foreign annex skips bare↔namespaced twins; selftests (6)(6b)(7)(12)+(14) | `hooks/scripts/enforcer.py`, `config/deterministic-routes.json` | [x] selftest OK (10 fire / 6 off) |
| P2 | Telemetry + keep-off: R6 outage allow-list in `analyze.py` (two sites); R4 keep-off reads the durable home first, generator writes there, excludes harness-shaped offers, exempts keep-on members, window default = v0.47.0 day; `doctor` check + `--fix` regeneration | `scripts/analyze.py`, `scripts/build_keep_off.py`, `scripts/doctor.py`, `hooks/scripts/enforcer.py` (`_keepoff_path`) | [x] fallback line 74/582; backtest 0 drops; doctor Keep-off WARN+fix |
| P3 | Config: R5 keep-on add 8 names via `scripts/keep-on.py` (7 from ledger takes + `vn-doc-complete` from inline USING); R8 `ENFORCER_ANNEX_MARGIN=0.0` in `~/.claude/settings.json` env (trial, revert = delete; backup `.bak-annexmargin-20260915-085417`) | durable home, settings.json | [x] 50 on / 671 name-only |
| P4 | Docs + version: 0.47.0 in 4 manifests + quickstart + README; CHANGELOG; ADR-0054 + index; epoch-watch v0.47.0; CLAUDE.md/AGENTS.md/README flag rows; openwiki operations rows; multivector-arc note; audit skill signature + SKILL.md wording; doctrine rule-4 clause | see files | [x] driftcheck IN SYNC |
| P5 | Verify: enforcer/analyze selftests, pytest (21), doctor, keep-off dry-run, driftcheck, live stdin probes (`/tmp/sc_audit/live_probe.py`); tester + code-reviewer subagents | — | [x] tester PASS (`plans/reports/test-260915-v0470.md`); code review APPROVE-WITH-FIXES (`plans/reports/review-260915-code-review-v0470.md`) — all 9 findings applied: routes respect the ADR-0034 invocability filter (+ selftest 6c), `doctor --fix` refreshes keep-off via `REFRESH_FIXERS` + `setup.sh` builds it, dead `<command-name>` shape dropped with ledger-evidence comment, blocklist-vs-route pinned, `tests/test_harness_regex_parity.py`, comment/doc corrections; 4 extra probes run by the lead (kill-switch, blocklisted route, 1 ms embed timeout, empty keep-on backtest) |
| P6 | Ship: commit (openwiki guard), push, adapter installers (omp/dsh/cline/commandcode/zcode); handoff, journal, memory | — | [x] commit `a44d356` pushed (origin/main == HEAD, tree clean); all 5 adapter installers exit 0 at 0.47.0; handoff `.handoff/handoff-2026-09-15-0930-v0470-shipped.md` |

Source: `plans/reports/audit-260914-2325-concierge-usage-strengthen.md` — Status: **SHIPPED as v0.47.0** (2026-09-15).

## Acceptance

Gates in `.unlazy/v0470-impl/GATES.md` (G1–G8) — all 8 met. R9 deferred by design; `/plugin marketplace update` (Claude Code, Codex) stays the owner's step, so this Claude Code session and Codex still run the 0.45.0 hook until then.
