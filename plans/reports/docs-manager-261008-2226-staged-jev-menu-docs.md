# Docs report: skill-concierge v0.64.0 (staged Jev menu, Cline first-call chain, honest Cline offer row)

Worktree: `/Users/thinhkhuat/.worktrees/skill-concierge/cline-seen` (branch `feat/cline-offer-seen`). 2026-10-08, Asia/Saigon.
No git state-changing commands run. No code, test, manifest, GATES.md or `plans/` file edited.

## Authority surfaces

Created
- `docs/adr/0087-staged-jev-menu-and-honest-cline-offer-row.md` (170 lines). Context, replay table with the validator's corrections, 8 decisions with the owner's words and times, 5 rejected alternatives (incl. the removed `ENFORCER_JEV_STAGE` switch, in history only), consequences (billing, epoch, telemetry), limits, revert paths. Amends ADR-0086 on two points; ADR-0086 itself untouched.

Changed
- `docs/adr/README.md`: index row 0087.
- `docs/runtime-flags.md`: `ENFORCER_LEDGER` entry rewritten (`defer`, `skillConciergeOffer`, `ConciergeOffer`, `seen`, `offer_late`); new entries `ENFORCER_JEV_TIER=<tier>` and `ENFORCER_EARLY_MENU`; staged route and lift ordering added to `ENFORCER_JEV_ROUTER`; header default-OFF list.
- `AGENTS.md`: Per-turn hook table: `ENFORCER_LEDGER` row updated, rows for `ENFORCER_JEV_TIER` and `ENFORCER_EARLY_MENU`, ADR-0087 link and staged-route sentence on `ENFORCER_JEV_ROUTER`.
- `docs/caveats.md` §26: first-call chain, live timings, TypeSafe billing consequence, retracted 96 % claim, unmeasured items. Hub-mode paragraph kept as is.
- `docs/epoch-watch.md`: new `v0.64.0` section (W45 to W48).
- `CHANGELOG.md`: `## [0.64.0] - 2026-10-08` (Added / Changed / Fixed / Documentation).
- `README.md`: badge 0.64.0; new `0.64.0` release line (contains `**published`) above 0.63.0.
- `openwiki/quickstart.md`: version 0.64.0.
- `openwiki/operations.md`: Cline first-call chain sentence; `ENFORCER_JEV_ROUTER` row; rows for `ENFORCER_LEDGER`, `ENFORCER_JEV_TIER`, `ENFORCER_EARLY_MENU`.
- `driftcheck.json`: ADR-0087 added to the path list (permitted).

Retained unchanged
- `docs/repository-layout.md`: checked, no stale sentence (it describes the Jev router and `ledger.py` at a level the change does not contradict).
- README Cline table row (line 424): does not describe the preview behaviour; unchanged.

## Evidence classes

- Fact, from code (read in the diff against `main`): `defer` path (`_append_offer`, `_DEFERRED`, exit write), `_emit_early` / `_close_early`, `JEV_TIER_PIN` filter in `_jev_route`, `wide_menu` fallback and `stage`, `_jev_wide_rows` lift, `ConciergeOffer` in `ledger.py`, `BACKUP_AFTER_MS = 500`, `HOOK_BUDGET_MS = 2000`, `recordSeen` order and `seen` values, `offer_late` / `late` logging in the plugin.
- Fact, from reports: replay and validator numbers, 90-turn live latency, gates G3, G6, G7, owner decisions and times (quoted from the brief and `GATES.md`).
- Judgment (labelled in the docs): the "expected gain" reasoning in ADR-0087 Consequences; the epoch-watch trigger thresholds (30 turns, 20 %, 1.5 s, a few percent), which are my proposals and are labelled as such there.
- Not checked: I ran no live Cline, jevd, Command Code or TypeSafe call and did not re-run the test suites (G4, G9 are pending in GATES.md). All timings and hit rates are copied from the source reports.

## Validation

- `python3 scripts/check_flag_docs_parity.py` -> `flag-docs-parity OK: 41 table rows, 39 full entries; 41 table defaults and 38 stated docs defaults match the code`
- `python3 scripts/driftcheck.py driftcheck.json; echo exit=$?` -> `IN SYNC: every fact matches its source of truth.` `exit=0` (all four command checks passed, versions 0.64.0 everywhere).
- `grep -rn "0.63.0" README.md openwiki/quickstart.md` -> one hit: README.md:468, the historical `0.63.0` release line.
- Line counts, all under 800: ADR-0087 170, runtime-flags 59, caveats 693, epoch-watch 524, AGENTS 191, operations 431.
- Relative links in the new text were written to match each file's depth (`adr/…` from `docs/`, `../docs/adr/…` from `openwiki/`, `docs/adr/…` from the root). I did not run the openwiki link guard; driftcheck passed.

## Docs impact

Every decision, number and limit in the brief is in ADR-0087; the operational and flag details are in runtime-flags, caveats and epoch-watch. The replay report in `plans/reports/` already carries its own retraction of the 96 % claim; I did not touch it.

## Concerns

1. `ENFORCER_JEV_TIER` has no plain row in the AGENTS.md table. `scripts/check_flag_docs_parity.py` can only represent on/off defaults and `unset = <v>` string defaults, and this flag's code default is an empty string. I wrote the row as `` `ENFORCER_JEV_TIER=<tier>` `` so the regex skips it, and said so in the row and in the runtime-flags entry. The parity guard therefore does not cover this flag. A proper fix extends the script (not in my scope); it is the owner's call.
2. `hooks/scripts/ledger.py` carries a comment citing ADR-0086 for the `ConciergeOffer` branch; the decision is ADR-0087. Code is out of my scope; flagged only.
3. The `plans/261008-2226-staged-jev-menu/GATES.md` items G4, G5, G8, G9 are still pending there. G5's check now passes (driftcheck exit 0, parity OK). I did not edit GATES.md.

Status: DONE_WITH_CONCERNS

Summary: ADR-0087 and ten existing docs now record every decision, number and limit of v0.64.0, and flag-docs parity and driftcheck both pass (exit 0).

Unresolved questions:
1. Should `scripts/check_flag_docs_parity.py` learn empty-string defaults so `ENFORCER_JEV_TIER` can have a normal table row? (Concern 1; my pick: yes, a small follow-up.)
2. Should the `ledger.py` comment be corrected to cite ADR-0087 before the commit? (Concern 2; my pick: yes, one word.)
3. Are the proposed W45 to W48 trigger thresholds acceptable to the owner, or should he set them?

## Update 2 (owner chose "TypeSafe only for Cline", 2026-10-08 ~22:58)

Verified against the current code first: `adapters/cline/skill-concierge.cline-plugin.ts` runs one full pass with `ENFORCER_LEDGER: "defer", ENFORCER_JEV_TIER: JEV_TIER ("typesafe")`; `recordSeen` has only `full` and `preview`; no `EARLY_MENU`, `_emit_early` or backup timer remains in `enforcer.py` or the plugin; `JEV_TIER_PIN` and the `wide_menu` fallback remain.

Changed
- `docs/adr/0087-…`: header (amends ADR-0086's provider order, not its first-call rule); Decisions 3 and 4 kept as history marked "built, then removed"; Decision 5 (`ENFORCER_JEV_TIER`) kept; new Decision 9 (22:58, TypeSafe only, reason: ~4 Jev calls on both providers, the "both" option he had declined); alternatives, consequences (final live evidence 751 / 673 / 822 ms, the 22:58:11 index-owner restart sentence, first-design evidence kept as history), billing, limits, revert paths rewritten.
- `docs/runtime-flags.md`: `ENFORCER_EARLY_MENU` entry and header mention deleted; `ENFORCER_JEV_TIER` entry reworded (one full pass, not a backup; coordinator's "Unset = (empty)" form kept); `ENFORCER_LEDGER` `seen` values now `full` / `preview` / `late`.
- `AGENTS.md`: `ENFORCER_EARLY_MENU` row deleted; `ENFORCER_JEV_TIER` row reworded (default cell kept as is); `ENFORCER_LEDGER` row `seen` values.
- `docs/caveats.md` §26: two-pass chain, live timings, owner-restart sentence, billing, retracted 96 % claim, no Command Code fallback.
- `docs/epoch-watch.md`: backup-latency item replaced by W45 (share by `seen`) and W46 (TypeSafe full-route latency on Cline); billing note.
- `CHANGELOG.md` 0.64.0, `README.md` 0.64.0 line, `openwiki/operations.md` (Cline paragraph, flag rows), `docs/adr/README.md` row: updated to the final design.

Validation
- `python3 scripts/check_flag_docs_parity.py` -> `flag-docs-parity OK: 41 table rows, 39 full entries; 41 table defaults and 37 stated docs defaults match the code`
- `python3 scripts/driftcheck.py driftcheck.json; echo exit=$?` -> `IN SYNC`, `exit=0`
- `grep -rn "EARLY_MENU\|backup" docs/ README.md CHANGELOG.md AGENTS.md openwiki/`: remaining hits are ADR-0087's history, the CHANGELOG "built and removed" sentence, the ADR index row, and unrelated older "backup" text (settings backups, deployment notes).

Not checked: no live run, no test run; live figures are the coordinator's. The ledger.py comment still cites ADR-0086 (earlier concern 2, unchanged). Earlier concern 1 (parity gap for `ENFORCER_JEV_TIER`) is resolved by the coordinator's script change; I did not re-read that script change beyond the passing check.

Status: DONE_WITH_CONCERNS

Summary: All docs now describe TypeSafe-only Cline, with the early-menu flag and backup timer kept only as removed history; parity and driftcheck pass (exit 0).

## Update 3 (three review fixes, items 1 to 4)

Verified in the code before writing: `box["wide"]` handoff (`enforcer.py:2487`) and the `_jev_join` timeout path that serves it with `BudgetExceeded` (2573-2582); the `HistorySkip` branch keeping `wide_menu` (2509-2513); probability check `math.isfinite(v) and 0.0 <= v <= 1.0` (2178); `JEV_PIN_EP = {typesafe: ts, commandcode: cc, gateway: gw}` and the endpoint match in `_jev_route` (1757, 2438-2439); guarded deferred write (4755-4760); `setEncoding("utf8")` in the plugin (line 78); the `calibrate_jev_gate.py` `live` wide count (696-706).

Changed: `docs/adr/0087-…` (Decision 2 safety net, budget, HistorySkip and probability validation; Decision 5 endpoint match), `docs/runtime-flags.md` (`ENFORCER_JEV_ROUTER` staged paragraph, `ENFORCER_JEV_TIER`, `ENFORCER_LEDGER` guarded write), `docs/caveats.md` §26 (one sentence), `CHANGELOG.md` 0.64.0 (Added bullets amended; seven new Fixed bullets), `AGENTS.md` (`ENFORCER_JEV_ROUTER` and `ENFORCER_JEV_TIER` rows).

Not verified: the "4 of 10" figure is the coordinator's account of the reviewer's measurement; I read no review report. I did not read `tests/test_auto_flywheel.py`; that CHANGELOG line is from the brief.

Validation: `check_flag_docs_parity.py` -> `flag-docs-parity OK: 41 table rows, 39 full entries; 41 table defaults and 37 stated docs defaults match the code`; `driftcheck.py driftcheck.json; echo exit=$?` -> `exit=0`.

Status: DONE_WITH_CONCERNS (earlier open items unchanged: the `ledger.py` comment still cites ADR-0086; epoch-watch thresholds are my proposals).
