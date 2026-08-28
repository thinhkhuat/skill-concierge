# Gates: catalog tier parity (v0.38.0)

OWNS: hooks/scripts/enforcer.py, vendor/skill-search/skill_search/server.py, vendor/skill-search/skill_search/skills_discovery.py, scripts/flywheel.py, docs/adr/**, README.md, CLAUDE.md, AGENTS.md, openwiki/**, CHANGELOG.md, .claude-plugin/**, .codex-plugin/**, package.json, skills/*/SKILL.md, docs/skill-first-enforcement-mental-model.md, plans/260828-2115-catalog-tier-parity/**

Scope: built-in and external catalog skills compete at parity in the per-turn offer (one merged pool, one floor), chain hints can name externals, flywheel default covers all scopes — documented, released 0.38.0, pushed.

- [x] G1: Enforcer selftest green with rewritten parity cases (merged query without tier filter when on; filter restored when off; externals render inline with marker + shared share; getaway accepts external top; sidecar read admits catalog scopes with marker).
  CHECK: python3 hooks/scripts/enforcer.py --selftest
  EXPECT: enforcer --selftest OK
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge; path=e30d09cfba2e/88 entries; EXPECT=matched; output-sha256=1c650ea7c243c7c08270bbcafd7fd905f488e9b525910888c2943b96bae846cd; output-bytes=465

- [x] G2: No residual bias code in live paths — zero references to EXTERNAL_FLOOR / EXTERNAL_SLOTS / annex-block rendering in enforcer.py, server.py, flywheel.py.
  CHECK: sh -c 'if grep -rn "EXTERNAL_FLOOR\|EXTERNAL_SLOTS" hooks/scripts/enforcer.py vendor/skill-search/skill_search/server.py scripts/flywheel.py scripts/flywheel_manifest.py 2>/dev/null; then echo RESIDUAL_FOUND; else echo PARITY_CLEAN; fi'
  EXPECT: PARITY_CLEAN
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge; path=e30d09cfba2e/88 entries; EXPECT=matched; output-sha256=225f97172c4185fb2fa98c99d0f303d28065608213cdb6c6ee12e14214e75e4c; output-bytes=13

- [x] G3: Live end-to-end hook run emits a valid tier-parity offer (exit 0, JSON additionalContext, SKILL-FIRST preview present).
  CHECK: python3 plans/260828-2115-catalog-tier-parity/e2e_probe.py
  EXPECT: E2E PARITY OK
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge; path=e30d09cfba2e/88 entries; EXPECT=matched; output-sha256=afe25468483b5c085eb01159319e5db340ee8dc241337a9ceacad5e7088a1c0b; output-bytes=490

- [x] G4: Sidecar write admits catalog scopes (server.py compiles; catalog skip gone; enforcer read-side case covered by G1).
  CHECK: sh -c 'python3 -m py_compile vendor/skill-search/skill_search/server.py && if grep -n "catalog skills stay OUT of the sidecar" vendor/skill-search/skill_search/server.py; then echo SIDECAR_STILL_EXCLUDES; else echo SIDECAR_PARITY; fi'
  EXPECT: SIDECAR_PARITY
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge; path=e30d09cfba2e/88 entries; EXPECT=matched; output-sha256=e378f6fdce4db6fcd20bb1da4e9b03b7c0b65cc1faa1118a887fc699ef071594; output-bytes=15

- [x] G5: Flywheel default covers all configured scopes; --installed-only opt-out exists.
  CHECK: sh -c '$HOME/.claude/skill-concierge/venv/bin/python3 scripts/flywheel.py --help 2>&1 | grep -q -- "--installed-only" && echo FW_ALL_SCOPE || echo FW_MISSING_FLAG'
  EXPECT: FW_ALL_SCOPE
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge; path=e30d09cfba2e/88 entries; EXPECT=matched; output-sha256=7fcfca8c5f69cd2f649f03022a85e2052d5c5350c6cd55c5c68ef1156c77de69; output-bytes=13

- [x] G6: Docs sweep complete — ADR-0045 exists; 0032/0036/0043 carry supersede notes; CLAUDE.md + AGENTS.md flag lists updated; CHANGELOG has 0.38.0; openwiki updated.
  CHECK: python3 plans/260828-2115-catalog-tier-parity/docs_probe.py
  EXPECT: DOCS SWEEP OK
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge; path=e30d09cfba2e/88 entries; EXPECT=matched; output-sha256=c598d39545b97910490907bb7c146df64dd0ee6b65d058a223d34af8420481d3; output-bytes=729

- [x] G7: Release integrity — four manifests at 0.38.0, driftcheck exit 0, doctor offers-row green.
  CHECK: python3 plans/260828-2115-catalog-tier-parity/release_probe.py
  EXPECT: RELEASE OK
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge; path=e30d09cfba2e/88 entries; EXPECT=matched; output-sha256=705de5a1486293621c249febc3fbac81a6d20358f2b56e8d97b82c21472065ee; output-bytes=11

- [x] G8: Independent blind validator confirms parity on the live system and files a report under plans/reports/.
  EVIDENCE: plans/reports/validator-260828-2200-catalog-tier-parity.md — VERDICT: PASS (independent agent, read-only, all five asymmetries refuted with file:line evidence; C1 stale ADR cross-ref fixed in-turn in CLAUDE.md:14 + AGENTS.md:73; C3 driftcheck run by committer via G7 release probe — exit 0)

- [x] G9: Shipped — release commit pushed, worktree clean.
  CHECK: sh -c 'test -z "$(git status --porcelain)" && test -z "$(git log origin/main..HEAD --oneline)" && echo SHIPPED_CLEAN || echo NOT_SHIPPED'
  EXPECT: SHIPPED_CLEAN
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge; path=e30d09cfba2e/88 entries; EXPECT=matched; output-sha256=fc768bb29769eec801a047f1c78adbfc839b15bbfd0d8a0483569299ac900177; output-bytes=14
