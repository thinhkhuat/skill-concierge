# Gates: the four owner-approved maintenance changes (v0.65.0)

Owner order (2026-10-09 ~03:03): "do 1, 2, 3, 4" — the four decisions in
`plans/reports/chisle-audit-261009-0102-whole-concierge.md` § "Left for the owner":
(1) move the enforcer's and doctor's built-in self-tests into tests/; (2) delete dominance collapse and per-skill tau;
(3) one shared installer helper; (4) one shared harness detector.

Baseline (main aa6d7c2): `compile()` of hooks/scripts/enforcer.py, median of 30, five runs: 17.8 / 17.2 / 17.0 / 18.3 / 17.1 ms.

OWNS: hooks/scripts/{enforcer,doctrine,ledger,harness}.py, scripts/doctor.py, adapters/lib/**, adapters/*/install.sh,
tests/**, docs (ADR-0088, runtime-flags, caveats, openwiki, AGENTS, README), CHANGELOG.md, the five manifests,
plans/261009-0305-maintenance-four/**.

- [ ] G1: The enforcer's and doctor's self-test bodies live in tests/, and `--selftest` on both still passes.
  CHECK: python3 hooks/scripts/enforcer.py --selftest && python3 scripts/doctor.py --selftest && ! grep -q "def _selftest" hooks/scripts/enforcer.py scripts/doctor.py && echo SELFTEST_MOVED_OK
  EXPECT: SELFTEST_MOVED_OK
  EVIDENCE: pending

- [ ] G2: Dominance collapse and per-skill tau are gone from code, tests and the live docs.
  CHECK: ! grep -rqE "DOMINANCE_RATIO|PER_SKILL_TAU|_apply_dominance|_floor_for" hooks scripts tests AGENTS.md docs/runtime-flags.md openwiki && echo FEATURES_GONE_OK
  EXPECT: FEATURES_GONE_OK
  EVIDENCE: pending

- [ ] G3: The five installers source one `adapters/lib/sync.sh`; none still defines the shared helpers itself.
  CHECK: python3 -m pytest -q -p no:cacheprovider tests/test_installer_shared_lib.py && echo SHARED_LIB_OK
  EXPECT: SHARED_LIB_OK
  EVIDENCE: pending

- [ ] G4: One harness detector serves enforcer, doctrine and ledger, with the same answers as before.
  CHECK: python3 -m pytest -q -p no:cacheprovider tests/test_harness_detector.py && echo HARNESS_ONE_OK
  EXPECT: HARNESS_ONE_OK
  EVIDENCE: pending

- [ ] G5: The full suite passes on the merged branch.
  CHECK: python3 -m pytest -q -p no:cacheprovider tests/ && echo SUITE_OK
  EXPECT: SUITE_OK
  EVIDENCE: pending

- [ ] G6: Docs, versions and flag tables agree with the code.
  CHECK: python3 scripts/driftcheck.py driftcheck.json && echo DRIFT_OK
  EXPECT: DRIFT_OK
  EVIDENCE: pending

- [ ] G7: The per-prompt compile cost of enforcer.py drops (same method as the baseline above).
  EVIDENCE: pending

- [ ] G8: An independent reviewer finds no undeclared behaviour change (or every finding is fixed and re-checked).
  EVIDENCE: pending

- [ ] G9: Shipped: on origin/main, every installer re-run, doctor status OK with all integration rows green.
  EVIDENCE: pending
