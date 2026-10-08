# Gates: whole-concierge chisle audit, then the worth-fixing cuts (AFK)

Owner order (2026-10-09 01:02): "/chisle-audit the whole concierge and report findings then autonomously
proceed to fixing the worth fixing issues while i went on AFK mode now". AFK = decide and finish (RULES [2]);
commit and push are authorized by that order. Irreversible deletions of user data are not in scope.

OWNS: plans/261009-0102-chisle-audit/**, plans/reports/chisle-audit-261009-0102-*.md, and in the fix worktree
only the files a kept finding names, plus CHANGELOG.md and the four manifests for the patch release.

- [x] G1: The audit report covers all six areas (enforcer; hooks/bin/skills; big scripts; other scripts;
  adapters; docs) and gives every finding a disposition: fixed, or skipped with a reason.
  EVIDENCE: 2026-10-09 ~02:05: six findings files `findings/{A-enforcer,B-hooks-bin-skills,C-scripts-big,
  D-scripts-rest,E-adapters,F-docs}.md` and six disposition files `findings/{A..F}-dispositions.md`; counted
  disposition lines: A 23 fixed / 10 skipped, B 11/11, C 20/13, D 25/4, E 13/13, F 36/5 (each SKIPPED line
  carries its reason). Synthesis: `plans/reports/chisle-audit-261009-0102-whole-concierge.md`.

- [x] G2: The full test suite passes on the committed fix branch.
  CHECK: python3 -m pytest -q -p no:cacheprovider tests/ && echo SUITE_OK
  EXPECT: SUITE_OK
  EVIDENCE: automatic-evidence=v1; definition-sha256=5fe53c32dc5523b69cc1d8914c3e2764411d86328fa5a07d2c1c03bf51dc0b0e; exit=0; EXPECT=matched; output-sha256=a579ee488472b039d03c0aaa906c25ee8a6e53134e87e32f3ddc8726457568a2; output-bytes=1322; shell=/bin/sh; cwd=/Users/thinhkhuat/.worktrees/skill-concierge/chisle-cuts; path=1eab24f392dd/82 entries

- [x] G3: Docs, versions and flag tables agree with the code.
  CHECK: python3 scripts/driftcheck.py driftcheck.json && echo DRIFT_OK
  EXPECT: DRIFT_OK
  EVIDENCE: automatic-evidence=v1; definition-sha256=3b14165758a59cea2faee857355aea67a324569a79e290d4212788c200685cc6; exit=0; EXPECT=matched; output-sha256=62484105f99b8d1d7d279f1f97ad002a649f5c9b368433861241cbb078d9a41b; output-bytes=4304; shell=/bin/sh; cwd=/Users/thinhkhuat/.worktrees/skill-concierge/chisle-cuts; path=1eab24f392dd/82 entries

- [x] G4: The enforcer's built-in self-test passes.
  CHECK: python3 hooks/scripts/enforcer.py --selftest && echo SELFTEST_OK
  EXPECT: SELFTEST_OK
  EVIDENCE: automatic-evidence=v1; definition-sha256=0f6fe0b4ebec24ae6d5d23aa8a8d7dd5dd668b2fc4699ef0789e62efec7b8adc; exit=0; EXPECT=matched; output-sha256=bf42a3b843193f58c78dcb5eac7b86a72c48ac2ecca9b03ccbd4c6908e84bb1d; output-bytes=570; shell=/bin/sh; cwd=/Users/thinhkhuat/.worktrees/skill-concierge/chisle-cuts; path=1eab24f392dd/82 entries

- [ ] G5: An independent reviewer, who did not make the cuts, finds no behaviour change in the fix diff
  (or every finding it raises is fixed and re-checked).
  EVIDENCE: pending

- [ ] G6: The fixes are on origin/main and every harness runs them (doctor status OK, all integration rows green).
  EVIDENCE: pending
