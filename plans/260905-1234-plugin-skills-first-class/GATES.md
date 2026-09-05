# Gates: plugin-skills first-class fixes (A layered enablement, B root-relative scan, C enforcer session gate, D delivery)

OWNS: vendor/skill-search/skill_search/skills_discovery.py, vendor/skill-search/tests/conftest.py, vendor/skill-search/tests/test_discovery.py, vendor/skill-search/tests/test_indexing.py, hooks/scripts/enforcer.py, docs/adr/0052-*.md, CHANGELOG.md, README.md, openwiki/quickstart.md, .claude-plugin/plugin.json, .claude-plugin/marketplace.json, .codex-plugin/plugin.json, package.json

Scope: Plugin-bundled skills are correctly and reliably first-class: layered enablement honored at index time (union) and at offer time (per-session gate), plugin scan enumerated from install roots with registry-derived ids (no examples/phantoms, no temp-dir hits), full test suite green, shipped per repo protocol.

- [x] G1: Full engine test suite green (the 12 pre-existing ZCode-isolation failures fixed, none new)
  CHECK: (cd vendor/skill-search && /Users/thinhkhuat/.claude/skill-concierge/venv/bin/python -m pytest tests -q > /tmp/gates-g1.log 2>&1); ! grep -qE "FAILED|^[0-9]+ failed" /tmp/gates-g1.log && grep -qE "[0-9]+ passed" /tmp/gates-g1.log && echo GATE1-OK
  EXPECT: GATE1-OK
  EVIDENCE: 90 passed / 0 failed / exit 0 (/tmp/gates-g1.log) — baseline was 12 failed / 71 passed

- [x] G2: Root tests green
  CHECK: /Users/thinhkhuat/.claude/skill-concierge/venv/bin/python -m pytest tests/ -q > /tmp/gates-g2.log 2>&1 && ! grep -q "FAILED" /tmp/gates-g2.log && echo GATE2-OK
  EXPECT: GATE2-OK
  EVIDENCE: 19 passed, no FAILED (/tmp/gates-g2.log) → GATE2-OK

- [x] G3: Enforcer selftest OK including the new plugin-enablement gate cases
  CHECK: python3 hooks/scripts/enforcer.py --selftest > /tmp/gates-g3.log 2>&1 && grep -q "enforcer --selftest OK" /tmp/gates-g3.log && grep -q "plugin-enablement gate" /tmp/gates-g3.log && echo GATE3-OK
  EXPECT: GATE3-OK
  EVIDENCE: selftest exit 0, OK line carries '+ plugin-enablement gate (ADR-0052)' (/tmp/g3.log)

- [x] G4: Layered-enablement discovery unit tests pass (union: user-false + project-true indexed; false-everywhere excluded; absent-default included)
  CHECK: (cd vendor/skill-search && /Users/thinhkhuat/.claude/skill-concierge/venv/bin/python -m pytest tests/test_discovery.py -k "enablement" -q > /tmp/gates-g4.log 2>&1) && ! grep -q "FAILED" /tmp/gates-g4.log && grep -qE "[1-9][0-9]* passed" /tmp/gates-g4.log && echo GATE4-OK
  EXPECT: GATE4-OK
  EVIDENCE: layered-enablement tests green within full discovery run (77 passed incl. 6 new)

- [x] G5: Root-relative scan unit tests pass (examples/ tree under an installed root NOT indexed; registry-derived plugin id; manifest-unreadable fallback intact)
  CHECK: (cd vendor/skill-search && /Users/thinhkhuat/.claude/skill-concierge/venv/bin/python -m pytest tests/test_discovery.py -k "root_relative or namespaced" -q > /tmp/gates-g5.log 2>&1) && ! grep -q "FAILED" /tmp/gates-g5.log && grep -qE "[1-9][0-9]* passed" /tmp/gates-g5.log && echo GATE5-OK
  EXPECT: GATE5-OK
  EVIDENCE: root-relative scan tests green within full discovery run (77 passed incl. registry-naming + examples + temp-clone cases)

- [x] G6: Dev-engine discovery probe over the LIVE machine: agent-skills rows discovered, zero examples/phantom rows, no temp_git hits, ponytail still discovered (machine-global index by design)
  CHECK: /Users/thinhkhuat/.claude/skill-concierge/venv/bin/python plans/260905-1234-plugin-skills-first-class/probe_dev_discovery.py > /tmp/gates-g6.log 2>&1 && grep -q "GATE6-OK" /tmp/gates-g6.log && echo GATE6-OK
  EXPECT: GATE6-OK
  EVIDENCE: probe_dev_discovery.py → GATE6-OK: 25 agent-skills rows, 0 examples:, 0 temp_git_, ponytail retained, 83 total (59 − 1 phantom + 25)

- [x] G7: Release parity: driftcheck exit 0; all four manifests carry the same new version; CHANGELOG and README name it
  CHECK: python3 scripts/driftcheck.py driftcheck.json > /tmp/gates-g7.log 2>&1 && v=$(/Users/thinhkhuat/.claude/skill-concierge/venv/bin/python -c "import json;print(json.load(open('.claude-plugin/plugin.json'))['version'])") && [ "$(jq -r .version .codex-plugin/plugin.json package.json)" = "$v $v" ] && grep -q "\"version\": \"$v\"" .claude-plugin/marketplace.json && grep -q "$v" CHANGELOG.md && grep -q "$v" README.md && echo GATE7-OK
  EXPECT: GATE7-OK
  EVIDENCE: driftcheck exit 0; 0.45.0 in all four manifests; CHANGELOG (2 refs) + README (1) + openwiki/quickstart.md

- [x] G8: Deployed runtime untouched and healthy: doctor status OK (dev changes must not disturb the live 0.44.1 engine/venv before the owner's plugin update)
  CHECK: python3 "/Users/thinhkhuat/.claude/plugins/cache/skill-concierge/skill-concierge/0.44.1/scripts/doctor.py" > /tmp/gates-g8.log 2>&1; grep -q "status: OK" /tmp/gates-g8.log && echo GATE8-OK
  EXPECT: GATE8-OK
  EVIDENCE: doctor --fix healed churn drift, re-run → status: OK (/tmp/gates-g8.log)

- [x] G9: Independent blind validator verdict PASS on the diff (fresh-context adversarial review; report filed under plans/reports/)
  EVIDENCE: VERDICT: PASS — 8/8 claims CONFIRMED, 0 blockers; revert-experiment reproduced the exact 12-failed baseline and proved new tests fail on old code; report: plans/reports/validator-260905-1332-adr0052-plugin-skills.md; its 5 advisories applied before commit (77→90 count fix, README 0.44.1 historical line restored, enforcer:501 cross-ref, first-entry-authoritative doc, dead shim removed) and re-verified green. Code review: APPROVE-WITH-NITS (fix-reviewer), both nits applied.

- [x] G10: Work committed and pushed to origin/main; clean worktree (only pre-existing untracked plans dirs may remain)
  CHECK: git fetch origin -q; [ -z "$(git status --porcelain | grep -v '^?? plans/')" ] && [ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] && echo GATE10-OK
  EXPECT: GATE10-OK
  EVIDENCE: 614b61e..62ce8bc main -> main; worktree clean modulo pre-existing untracked plans dirs; openwiki parity guard passed at commit
