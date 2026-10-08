# Gates: the four owner-approved maintenance changes (v0.65.0)

Owner order (2026-10-09 ~03:03): "do 1, 2, 3, 4" — the four decisions in
`plans/reports/chisle-audit-261009-0102-whole-concierge.md` § "Left for the owner":
(1) move the enforcer's and doctor's built-in self-tests into tests/; (2) delete dominance collapse and per-skill tau;
(3) one shared installer helper; (4) one shared harness detector.

Baseline (main aa6d7c2): `compile()` of hooks/scripts/enforcer.py, median of 30, five runs: 17.8 / 17.2 / 17.0 / 18.3 / 17.1 ms.

OWNS: hooks/scripts/{enforcer,doctrine,ledger,harness}.py, scripts/doctor.py, adapters/lib/**, adapters/*/install.sh,
tests/**, docs (ADR-0088, runtime-flags, caveats, openwiki, AGENTS, README), CHANGELOG.md, the five manifests,
plans/261009-0305-maintenance-four/**.

- [x] G1: The enforcer's and doctor's self-test bodies live in tests/, and `--selftest` on both still passes.
  CHECK: python3 hooks/scripts/enforcer.py --selftest && python3 scripts/doctor.py --selftest && ! grep -q "def _selftest" hooks/scripts/enforcer.py scripts/doctor.py && echo SELFTEST_MOVED_OK
  EXPECT: SELFTEST_MOVED_OK
  EVIDENCE: automatic-evidence=v1; definition-sha256=be54de871e903fd241c0fff903c3c4a14a902a591672616b0bc4f5cf88e141bb; exit=0; EXPECT=matched; output-sha256=6995a51ebd675ec966a379441003201057683614a8e0a55483b8e4b1b53fab1b; output-bytes=549; shell=/bin/sh; cwd=/Users/thinhkhuat/.worktrees/skill-concierge/maint-int; path=1eab24f392dd/82 entries

- [x] G2: Dominance collapse and per-skill tau are gone from code, tests and the live docs.
  CHECK: ! grep -rqE "DOMINANCE_RATIO|PER_SKILL_TAU|_apply_dominance|_floor_for" hooks scripts tests AGENTS.md docs/runtime-flags.md openwiki && echo FEATURES_GONE_OK
  EXPECT: FEATURES_GONE_OK
  EVIDENCE: automatic-evidence=v1; definition-sha256=e6f9317a7cd80477a9ae9161b425a8c60fee7556ccbf9e10396f09b9c0ddc71b; exit=0; EXPECT=matched; output-sha256=c9131c63e227a7cd850213bba5c2da613f811f21cb698ae3e42af10e5bc85d17; output-bytes=17; shell=/bin/sh; cwd=/Users/thinhkhuat/.worktrees/skill-concierge/maint-int; path=1eab24f392dd/82 entries

- [x] G3: The five installers source one `adapters/lib/sync.sh`; none still defines the shared helpers itself.
  CHECK: python3 -m pytest -q -p no:cacheprovider tests/test_installer_shared_lib.py && echo SHARED_LIB_OK
  EXPECT: SHARED_LIB_OK
  EVIDENCE: automatic-evidence=v1; definition-sha256=0643f7f73414b00da6d21d9a992dd24fac573c096ae821fa270a0653b3b1b783; exit=0; EXPECT=matched; output-sha256=e124d922a6ffcacdd38d360b8e320cb97e0cbf611f12edd79bf7621ba4763a6a; output-bytes=113; shell=/bin/sh; cwd=/Users/thinhkhuat/.worktrees/skill-concierge/maint-int; path=1eab24f392dd/82 entries

- [x] G4: One harness detector serves enforcer, doctrine and ledger, with the same answers as before.
  CHECK: python3 -m pytest -q -p no:cacheprovider tests/test_harness_detector.py && echo HARNESS_ONE_OK
  EXPECT: HARNESS_ONE_OK
  EVIDENCE: automatic-evidence=v1; definition-sha256=e9254db38c8c560f1c03971d3432a297a9784c24b9e83a9be454e9690cc2864f; exit=0; EXPECT=matched; output-sha256=6bda7cff2cf4f6a4602ca17605e2b4b572c5567913c002418b9861efdee852da; output-bytes=435; shell=/bin/sh; cwd=/Users/thinhkhuat/.worktrees/skill-concierge/maint-int; path=1eab24f392dd/82 entries

- [x] G5: The full suite passes on the merged branch.
  CHECK: python3 -m pytest -q -p no:cacheprovider tests/ && echo SUITE_OK
  EXPECT: SUITE_OK
  EVIDENCE: automatic-evidence=v1; definition-sha256=5fe53c32dc5523b69cc1d8914c3e2764411d86328fa5a07d2c1c03bf51dc0b0e; exit=0; EXPECT=matched; output-sha256=1f6311d9b1e7c6706539fd61ae6e973385d6d67b8ae22760def7d2f93ec38029; output-bytes=1722; shell=/bin/sh; cwd=/Users/thinhkhuat/.worktrees/skill-concierge/maint-int; path=1eab24f392dd/82 entries

- [x] G6: Docs, versions and flag tables agree with the code.
  CHECK: python3 scripts/driftcheck.py driftcheck.json && echo DRIFT_OK
  EXPECT: DRIFT_OK
  EVIDENCE: automatic-evidence=v1; definition-sha256=3b14165758a59cea2faee857355aea67a324569a79e290d4212788c200685cc6; exit=0; EXPECT=matched; output-sha256=9a477b9d486c750218cd7f71499f325192b18561b1fda0631d9f66006e56eea9; output-bytes=4302; shell=/bin/sh; cwd=/Users/thinhkhuat/.worktrees/skill-concierge/maint-int; path=1eab24f392dd/82 entries

- [x] G7: The per-prompt compile cost of enforcer.py drops (same method as the baseline above).
  EVIDENCE: 2026-10-09 ~03:45, maint/integrate (3,221 lines, was 4,592): medians 12.1 / 11.7 / 11.7 / 11.6 / 11.5 ms
  vs baseline 17.8 / 17.2 / 17.0 / 18.3 / 17.1 ms — about 5.8 ms (33 %) less compile on every prompt. Measured by the
  main session, same script, same machine, Python 3.12.

- [x] G8: An independent reviewer finds no undeclared behaviour change (or every finding is fixed and re-checked).
  EVIDENCE: Review 1 (`plans/reports/code-reviewer-261009-0335-v0650-review.md`) found one CRITICAL: the getaway
  (low-fit) leg read the deleted `floor` and crashed every low-fit turn the Jev router does not take (NameError,
  exit 1; reproduced). Fixed in fa487f4 with failing-first `tests/test_getaway_leg.py` and a class guard
  `tests/test_no_undefined_names.py` (proven to fire on the reverted line), plus its Low items (symlinked installers,
  importer SystemExit, ADR/CHANGELOG wording, doctor comment). Review 2, a fresh reviewer on fa487f4
  (`plans/reports/code-reviewer-261009-0359-v0650-fix-recheck.md`): all fixes correct, 14/14 hook outputs byte-
  identical to main on Python 3.12 and 3.9, 100/100 installer runs identical on /bin/bash 3.2, full suite 1,467/1,467;
  its Medium (guard skipped without pyflakes, missed vendor/) fixed in a94cae3; its Low items: comment wording fixed;
  lone-copy `--root`/OMP `safe_write` symlink cases match main (not regressions); the audit report's "shipped" wording
  becomes true at G9. G1-G6 re-verified on a94cae3 after both rounds.

- [ ] G9: Shipped: on origin/main, every installer re-run, doctor status OK with all integration rows green.
  EVIDENCE: pending
