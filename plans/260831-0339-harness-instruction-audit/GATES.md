# Gates: harness instruction-prose audit (260831-0339)

OWNS: plans/**

Scope: exhaustive read-only audit of all deployed instruction prose on this machine's Claude Code harness — hooks wired in ~/.claude/settings.json and their emitted prose, the 371 personal skills' SKILL.md corpus, global config prose (CLAUDE.md, RULES.md, rules/*.md), 34 agent definitions, 7 output styles — producing cited findings on writing quality, overlap, and contradiction, independently validated. All writes confined to plans/**; zero edits to audited surfaces; zero git ops.

- [x] G1: hooks inventory — hooks-audit report on disk covering every hook script wired in ~/.claude/settings.json
  CHECK: /Users/thinhkhuat/.claude/skills/.venv/bin/python3 plans/260831-0339-harness-instruction-audit/verify_audit.py g1
  EXPECT: HOOKS-REPORT-VERIFIED
  CWD: /Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge; path=1efb2b9abc4c/88 entries; EXPECT=matched; output-sha256=07c1645109d504d40c6c9ccfcf9a35ee3c0a8a19e1745a9d654975cb864eb1c7; output-bytes=51

- [x] G2: skills census — analyzer + cleaner reports on disk; independent SKILL.md count grounded
  CHECK: /Users/thinhkhuat/.claude/skills/.venv/bin/python3 plans/260831-0339-harness-instruction-audit/verify_audit.py g2
  EXPECT: SKILLS-CENSUS-VERIFIED
  CWD: /Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge; path=1efb2b9abc4c/88 entries; EXPECT=matched; output-sha256=71611b1f66de5f7e4c9051710ee4a95a1031acb582bb4f2eeaa2d30039d33712; output-bytes=41

- [x] G3: config-prose audit — CLAUDE.md, RULES.md, and all 10 rules/*.md reviewed with cited findings
  CHECK: /Users/thinhkhuat/.claude/skills/.venv/bin/python3 plans/260831-0339-harness-instruction-audit/verify_audit.py g3
  EXPECT: CONFIG-PROSE-VERIFIED
  CWD: /Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge; path=1efb2b9abc4c/88 entries; EXPECT=matched; output-sha256=ca606b2fb2d6bc7e1f97c66fbdbafe100612b3352e39618fcd1c0e66f5b432d9; output-bytes=22

- [x] G4: agents + output-styles audit — all 34 agents/*.md and 7 output-styles/*.md covered with findings
  CHECK: /Users/thinhkhuat/.claude/skills/.venv/bin/python3 plans/260831-0339-harness-instruction-audit/verify_audit.py g4
  EXPECT: AGENTS-STYLES-VERIFIED
  CWD: /Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge; path=1efb2b9abc4c/88 entries; EXPECT=matched; output-sha256=19ee9ab3bda1777cdf1e7917722de8a2c8026cd721f5e643ef234737f8cfbd84; output-bytes=42

- [x] G5: cross-surface contradiction matrix — pairwise synthesis with pairs-checked count ≥ 40 and dual citations per row
  CHECK: /Users/thinhkhuat/.claude/skills/.venv/bin/python3 plans/260831-0339-harness-instruction-audit/verify_audit.py g5
  EXPECT: CONTRADICTION-MATRIX-VERIFIED
  CWD: /Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge; path=1efb2b9abc4c/88 entries; EXPECT=matched; output-sha256=76f13e184cbc589b7c40a540ac96cc9966324144756c46a055bd02ecd22036fe; output-bytes=47

- [x] G6: independent validation — blind validator verdict on the assembled audit, on disk
  CHECK: /Users/thinhkhuat/.claude/skills/.venv/bin/python3 plans/260831-0339-harness-instruction-audit/verify_audit.py g6
  EXPECT: VALIDATION-VERIFIED
  CWD: /Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge; path=1efb2b9abc4c/88 entries; EXPECT=matched; output-sha256=3d589263efa72db913fc72321b1d60019d565c5cfb5c7b0e1db4bfc107b2e553; output-bytes=20

- [x] G7: final report — single audit report with all sections and unresolved-questions list
  CHECK: /Users/thinhkhuat/.claude/skills/.venv/bin/python3 plans/260831-0339-harness-instruction-audit/verify_audit.py g7
  EXPECT: FINAL-REPORT-VERIFIED
  CWD: /Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge; path=1efb2b9abc4c/88 entries; EXPECT=matched; output-sha256=f12190b5cfc1fe24de055894688bc2fd32e34d25c3eaa9332505e5c5a8bab2d2; output-bytes=22
