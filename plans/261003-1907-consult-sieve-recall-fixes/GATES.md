# Gates: consult sieve recall — work until a fix is proven

OWNS: scripts/sieve_recall.py, tests/test_sieve_recall.py, vendor/skill-search/skill_search/server.py, vendor/skill-search/tests/**, skills/consult/**, plans/261003-1907-consult-sieve-recall-fixes/**, AGENTS.md, CLAUDE.md, README.md, CHANGELOG.md, docs/adr/**, docs/epoch-watch.md, .claude-plugin/**, .codex-plugin/**, package.json, openwiki/quickstart.md

Scope: Thinh's order (2026-10-04 09:18): "I WANT THE PLAN TO BE WORKED ON, CONTINOUSLY UNTIL IT IS PROVEN." Proven = a consult sieve-recall fix passes a pre-registered gate on held-out data that no tuning step has seen, and that fix is shipped. The 83-case set from the 05:09 gate is spent: it may be used for diagnosis only, never as proof.

- [ ] G1: Diagnosis on the spent set measures every candidate fix and names the hypotheses for the next held-out run
  CHECK: python3 -c "import pathlib,sys; t=pathlib.Path('plans/261003-1907-consult-sieve-recall-fixes/reports/iter2-diagnosis.md').read_text(); sys.exit(0 if 'HYPOTHESES-FOR-HELDOUT:' in t and 'recall@' in t else 1); print('diag-ok')" && echo DIAGNOSIS-WRITTEN
  EXPECT: DIAGNOSIS-WRITTEN
  EVIDENCE: pending

- [ ] G2: A fresh held-out case set is frozen: built from turns after the spent corpus, no session shared with the spent cases, at least 30 cases after the leak check
  CHECK: ~/.claude/skill-concierge/venv/bin/python3 scripts/sieve_recall.py --iter 2 check-fresh
  EXPECT: FRESH-HELDOUT-OK
  EVIDENCE: pending

- [ ] G3: The decisions and rules for the fresh run are written down and hashed before the run, and the run's output carries that hash
  CHECK: ~/.claude/skill-concierge/venv/bin/python3 scripts/sieve_recall.py --iter 2 check-prereg
  EXPECT: PREREG-MATCHES-RUN
  EVIDENCE: pending

- [ ] G4: At least one decision prints PASS on the fresh held-out run
  CHECK: python3 -c "import pathlib,re,sys; t=pathlib.Path('plans/261003-1907-consult-sieve-recall-fixes/reports/iter2-gate-raw.txt').read_text(); sys.exit(0 if re.search(r'^VERDICT: \S+ PASS', t, re.M) else 1)" && echo FIX-PROVEN
  EXPECT: FIX-PROVEN
  EVIDENCE: pending

- [ ] G5: The proven fix is switched on, tested, released and pushed (local HEAD equals origin/main, full suite green)
  CHECK: python3 -m pytest tests/ -q -p no:randomly 2>&1 | tail -1 | grep -q " passed" && test "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" && git log -1 --format=%s | grep -qi "consult" && echo SHIPPED
  EXPECT: SHIPPED
  EVIDENCE: pending
