# Gates: staged Jev menu (wide menu safety net, Cline first-call chain, honest offer row)

Owner decisions (2026-10-08): 22:05 "1+2" (honest ledger row; test a wide-only first menu); 22:17 "A"
(the full pass emits the wide menu early); 22:26 "keep-full for the 10-second harnesses is locked-in";
22:37 Plan A with a TypeSafe call as the fallback before the embedding menu; 22:52 the TypeSafe backup runs
the full route (Thinh asked "lets consider these, should we?"; recommended and proceeded); ~22:56 FINAL, via
AskUserQuestion: "TypeSafe only for Cline" — the design as built billed both providers on most Cline turns
(~4 Jev calls), the "Both" option he had declined. ENFORCER_EARLY_MENU and the backup timer were removed. Command Code and DSH
already get the full Jev menu through the TypeSafe tier (probe 22:33), so they keep it.

OWNS: hooks/scripts/enforcer.py, hooks/scripts/ledger.py, adapters/cline/skill-concierge.cline-plugin.ts,
tests/test_cline_plugin.py, tests/test_jev_staged_menu.py, docs/adr/0087-*.md, docs/adr/README.md,
docs/runtime-flags.md, AGENTS.md, docs/caveats.md, CHANGELOG.md, README.md, openwiki/**, the four manifests,
plans/261008-2151-cline-first-menu-replay/**, plans/261008-2226-staged-jev-menu/**, plans/reports/*-2151-*, *-2226-*

- [x] G1: Cline's turn writes one offer row, for the menu its first model call carried (`seen`), and a later
  full row only as `offer_late`.
  CHECK: pytest -q -p no:cacheprovider tests/test_cline_plugin.py && echo CLINE_PLUGIN_OK
  EXPECT: CLINE_PLUGIN_OK
  EVIDENCE: 2026-10-08 ~22:40 (+07): "23 passed" three runs in a row (and 15/15 clean runs of the earlier 20-test
  file). Final TypeSafe-only design, ~22:57: "21 passed" twice. Failing-before: the 6 ledger tests failed with `assert 1 == 0` (defer still wrote a row), `{None, '0'}
  == {'defer'}`, and `[] == [('offer','preview'),…]` before the fix.

- [x] G2: The enforcer's staged route: a failed or late rerank keeps the wide menu (every harness);
  ENFORCER_JEV_TIER pins one jevd provider; wide rows are ordered by the order the ordering replay chose.
  (Definition amended twice: the ENFORCER_JEV_STAGE=wide clause dropped when the TypeSafe backup became a full
  route, and the ENFORCER_EARLY_MENU clause dropped with the owner's "TypeSafe only for Cline".)
  CHECK: pytest -q -p no:cacheprovider tests/test_jev_staged_menu.py && echo STAGED_OK
  EXPECT: STAGED_OK
  EVIDENCE: failing-before: 7 failed (`'NoneType' object is not subscriptable`, `KeyError: 'stage'`, no
  `_jev_wide_rows` / `_emit_early`, unexpected kwarg `on_wide`). After: the 6 kept tests pass (the
  ENFORCER_JEV_STAGE=wide test was deleted with the switch once the TypeSafe backup became a full route,
  Thinh 22:52 "lets consider these, should we?" → recommended, proceeded). All Jev test files: 93 passed; after the early-menu removal, 91 passed.

- [x] G3: The wide-row ordering is chosen on evidence (raw vs lift, same answers, 233 reachable turns).
  EVIDENCE: `first_menu_replay.py ordering` (312/313 wide answers, Command Code): raw hit@1 36.1 % hit@3 63.9 %
  hit@5 71.2 %, top-5 rows by chunk 31/34/36 %; lift hit@1 36.5 % hit@3 60.1 % hit@5 70.8 %, rows 44/44/13 %
  (the 49-skill chunk holds 8.9 % of the shelf and 18.5 % of used skills). Equal quality; lift chosen because
  raw order puts a one-option chunk's skill first on every turn (its probability is always 1.0).

- [x] G4: The whole tests/ suite passes.
  CHECK: pytest -q -p no:cacheprovider tests/ && echo ALL_TESTS_OK
  EXPECT: ALL_TESTS_OK
  EVIDENCE: 2026-10-08 ~23:15 (+07), final code after the review fixes, committed in a throwaway clone (so the
  Codex installer tests see the version bump as committed): "1103 passed in 305.33s", exit=0. An earlier run
  (22:47-22:52) had 3 failures in tests/test_auto_flywheel.py, traced to a live flywheel run holding the machine's
  real lock (lock touched 22:46:56); the tests now stub `_flywheel_locked`.

- [x] G5: driftcheck (versions, paths, flag table/docs/code parity) is in sync.
  CHECK: python3 scripts/driftcheck.py driftcheck.json && echo DRIFT_OK
  EXPECT: DRIFT_OK
  EVIDENCE: "IN SYNC: every fact matches its source of truth." after the last docs pass (~23:16); flag-docs
  parity OK (41 table rows, 39 full entries).

- [x] G6: A live Cline turn's first model call carries a Jev menu, and the ledger's offer row names which
  (`seen`). Amended for the final design: the full pass runs on TypeSafe only, and Command Code is never called.
  EVIDENCE: live, Cline 3.0.70, `-P openai-codex`, CLINE_SESSION_BACKEND_MODE=local, plugin loaded from this
  worktree, 3 task prompts (pytest regression test / conventional commit / GitHub Actions): each offer row
  `seen=typesafe band=offer stage=full prov=typesafe` at 941 / 706 / 679 ms, then `offer_late seen=later
  prov=commandcode stage=full` at 2171 / 2008 / 2498 ms, same lead skill both times (ak-test,
  conventional-commit, ak-github). Two earlier prompts ending "stop without calling tools" hit the refusal
  lane (band negation, seen full), as designed. That was the superseded backup design. FINAL design, live
  22:57-22:59: `seen=full prov=typesafe stage=full` at 751 / 673 / 822 ms, no Command Code call, no offer_late.
  One more turn at 22:58:11 fell to the embedding fallback (`embed_down`, Jev `HTTPError` on the catalogue
  read): index-owner.log shows the shared venv stamp moving 0.63.0 → 0.64.0 at 22:57:40 and the owner ready again
  at 22:58:11, a pre-merge side effect of testing the version bump.

- [x] G7: The 10-second harnesses keep the full route: a live Claude Code-harness enforcer run still
  returns the full (reranked) menu, and Command Code / DSH runs still answer through the TypeSafe full route.
  EVIDENCE: enforcer run per harness from this worktree, same prompt, ENFORCER_LEDGER=defer: claude / omp /
  opencode / codex / zcode → 1 output line, no early line, stage=full prov=commandcode (1.7–2.3 s);
  commandcode / dsh (ENFORCER_JEV_BUDGET=1.6) → stage=full prov=typesafe (618 / 639 ms).

- [x] G8: Docs record every decision, number and limit (ADR-0087, runtime-flags + AGENTS table, caveats,
  CHANGELOG, README, openwiki, the replay report corrected for the 96% claim).
  EVIDENCE: docs-manager report plans/reports/docs-manager-261008-2226-staged-jev-menu-docs.md (three passes:
  first design, "TypeSafe only for Cline", review fixes): ADR-0087 new; docs/adr/README.md, runtime-flags.md,
  AGENTS.md table, caveats §26, epoch-watch W45/W46 (thresholds labelled as proposals, not owner decisions),
  CHANGELOG 0.64.0, README, openwiki quickstart + operations. Replay report corrected (96 % retracted, validator
  corrections, decisions incl. the final one). `check_flag_docs_parity.py` OK (41 rows); driftcheck IN SYNC.

- [x] G9: An independent reviewer finds no unresolved correctness defect in the diff.
  EVIDENCE: plans/reports/code-reviewer-261008-2226-staged-jev-menu-review.md (blind, re-read after the
  TypeSafe-only change). Confirmed: other harnesses byte-identical to main apart from `jev.stage`; one Cline offer
  row per turn in every timing order. H1 (wide menu lost at the join deadline), H2 (NaN wide answer emptied the
  turn), H3 (typesafe pin matched nothing without jevd) fixed, each with a test that failed first
  (`'NoneType' object is not subscriptable`, `KeyError: 'fell'`, `set() == {'jev-1.13.0'}`). M1 resolved by the
  docs pass; M2 (calibrate live counts stage-wide rows apart, new test); M3 (guarded deferred write). L1 history
  skip keeps the wide menu (test updated), L2 dead code removed, L3 UTF-8 stdout decoding. L4 kept (the replay
  settled lift vs raw as equal; lift removes the one-option-chunk case). L5 not applicable: only the Cline plugin
  sets ENFORCER_LEDGER=defer. After fixes: 140 tests passed across the Jev, Cline, calibration, parity and
  flywheel files.
