# Gates: consult sieve recall — work until a fix is proven

OWNS: scripts/sieve_recall.py, tests/test_sieve_recall.py, vendor/skill-search/skill_search/server.py, vendor/skill-search/tests/**, skills/consult/**, plans/261003-1907-consult-sieve-recall-fixes/**, AGENTS.md, CLAUDE.md, README.md, CHANGELOG.md, docs/adr/**, docs/epoch-watch.md, .claude-plugin/**, .codex-plugin/**, package.json, openwiki/quickstart.md

Scope: Thinh's order (2026-10-04 09:18): "I WANT THE PLAN TO BE WORKED ON, CONTINOUSLY UNTIL IT IS PROVEN." Proven = a consult sieve-recall fix passes a pre-registered gate on held-out data that no tuning step has seen, and that fix is shipped. The 83-case set from the 05:09 gate is spent: it may be used for diagnosis only, never as proof.

- [x] G1: Diagnosis on the spent set measures every candidate fix and names the hypotheses for the next held-out run
  CHECK: python3 -c "import pathlib,sys; t=pathlib.Path('plans/261003-1907-consult-sieve-recall-fixes/reports/iter2-diagnosis.md').read_text(); sys.exit(0 if 'HYPOTHESES-FOR-HELDOUT:' in t and 'recall@' in t else 1); print('diag-ok')" && echo DIAGNOSIS-WRITTEN
  EXPECT: DIAGNOSIS-WRITTEN
  EVIDENCE: automatic-evidence=v1; definition-sha256=bad2d586bb1709311e485736439c8e8641c73c4fc7c059dd8907ce5983529e90; exit=0; EXPECT=matched; output-sha256=a76dcbc5357e00dc5c9ed379bbc6cd01b27f8a836607f7ea7cb88c5b11a1853c; output-bytes=18; shell=/bin/sh; cwd=/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge; path=af1f965b1c2e/81 entries

- [x] G2: A fresh held-out case set is frozen: built from turns after the spent corpus, no session shared with the spent cases, at least 30 cases after the leak check
  CHECK: ~/.claude/skill-concierge/venv/bin/python3 scripts/sieve_recall.py --iter 2 check-fresh
  EXPECT: FRESH-HELDOUT-OK
  EVIDENCE: automatic-evidence=v1; definition-sha256=7cd0ee0e0ce54f8825ca7700bf907068b7ba11260a69630a76ada9b106cdcfdf; exit=0; EXPECT=matched; output-sha256=b1d30a586db282bdc3ca82126666fa11dee8ceebcc66d466e8347a2b11677855; output-bytes=119; shell=/bin/sh; cwd=/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge; path=af1f965b1c2e/81 entries

- [x] G3: The decisions and rules for the fresh run are written down and hashed before the run, and the run's output carries that hash
  CHECK: ~/.claude/skill-concierge/venv/bin/python3 scripts/sieve_recall.py --iter 2 check-prereg
  EXPECT: PREREG-MATCHES-RUN
  EVIDENCE: automatic-evidence=v1; definition-sha256=85344f8200fb3dba8746c8bc02d898501434d8c45c8238dd0882ce4424ba164d; exit=0; EXPECT=matched; output-sha256=5e6b2b7b0697675cf33e906d06c8893ab4bbb0f4d076c6da91f122d7df2c51a9; output-bytes=19; shell=/bin/sh; cwd=/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge; path=af1f965b1c2e/81 entries

- [x] G4: At least one decision prints PASS on the fresh held-out run
  CHECK: python3 -c "import pathlib,re,sys; t=pathlib.Path('plans/261003-1907-consult-sieve-recall-fixes/reports/iter2-gate-raw.txt').read_text(); sys.exit(0 if re.search(r'^VERDICT: \S+ PASS', t, re.M) else 1)" && echo FIX-PROVEN
  EXPECT: FIX-PROVEN
  EVIDENCE: automatic-evidence=v1; definition-sha256=faeb96ac40eddcf66c4f9a080912a8027ee0fe606976bbafc3274f9698b3dc31; exit=0; EXPECT=matched; output-sha256=290c320563b31ba819f25aeb96fe8d31fdc2359aa415c60e50241cf666b27793; output-bytes=11; shell=/bin/sh; cwd=/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge; path=af1f965b1c2e/81 entries

- [ ] G5: The proven fix (J20: Jev top 10 + sieve rows, cut to 20) is switched on by default in consult, tested, released as a new version, pushed, and installed in Claude Code
  CHECK: python3 plans/261003-1907-consult-sieve-recall-fixes/verify_shipped.py
  EXPECT: J20-SHIPPED-AND-LIVE
  EVIDENCE: pending
