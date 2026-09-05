# Gates: audit-arc closeout — handoff + lane-consolidation decision map (260901-0331)

OWNS: plans/**

Scope: document the entire 2026-08-31→09-01 harness instruction-prose audit arc as a session handoff (written to the workbench-level `MY-WORKBENCH/.handoff/` per the owner convention — outside this repo's OWNS), then deliver the item-5 lane-consolidation decision map — per-agent keep/merge/retire recommendation with caller-mapping evidence for every consolidation candidate (8 agents + 6 output styles) — and record post-map state. Read-only on audited surfaces except reports/handoff.

- [x] G1: arc handoff on disk covering the complete arc with required sections (What was accomplished / Decisions locked / Key files / Memory touched / Running state / Pick up here)
  CHECK: /Users/thinhkhuat/.claude/skills/.venv/bin/python3 plans/260901-0331-audit-closeout/verify_closeout.py g1
  EXPECT: HANDOFF-VERIFIED
  CWD: /Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge; path=e9bec3818b2c/88 entries; EXPECT=matched; output-sha256=04cf6d4c906956f6f2d845b6a780d8f5ce983dc6e01f849471d4eb5bd0d0ebcb; output-bytes=85

- [x] G2: item-5 decision map on disk — every named candidate (explore, goal-scout, goal-judge, librarian-cataloger, researcher, agent-validator, tk-validator, vn-validator, brainstormer, planner, code-reviewer, code-simplifier + 6 coding-level styles) covered with a recommendation and caller evidence
  CHECK: /Users/thinhkhuat/.claude/skills/.venv/bin/python3 plans/260901-0331-audit-closeout/verify_closeout.py g2
  EXPECT: DECISION-MAP-VERIFIED
  CWD: /Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge; path=e9bec3818b2c/88 entries; EXPECT=matched; output-sha256=07fdb2f021d4ee62f9eca644fd5cda03a03cf20f4202d92c909b7e313e946436; output-bytes=22

- [x] G3: post-map state recorded — synthesis roadmap item 5 updated with map pointer, memory updated, open decisions surfaced
  CHECK: /Users/thinhkhuat/.claude/skills/.venv/bin/python3 plans/260901-0331-audit-closeout/verify_closeout.py g3
  EXPECT: CLOSEOUT-RECORDED
  CWD: /Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge; path=e9bec3818b2c/88 entries; EXPECT=matched; output-sha256=daa34420335c4c03a95af4396cc5a7942847bbb8120328c6cf0e5e4519294c00; output-bytes=18
