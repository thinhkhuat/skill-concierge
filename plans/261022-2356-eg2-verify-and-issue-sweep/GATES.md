# Gates: verify 0.72.0 live, then clear the three leftover doctor warnings and the commandcode search-row defect

OWNS: plans/261022-2356-eg2-verify-and-issue-sweep/**, ~/.claude/settings.json (via the repo's own apply-overrides.py), adapters/**, scripts/**

Scope: prove the embeddinggemma-2 cutover actually works in the restarted session, then make doctor green by fixing each of the three remaining warnings and the commandcode smoke defect that blocks a real search row.

- [x] G1: The restarted session is running skill-concierge 0.72.0 at the pushed commit, the index owner serves embeddinggemma-2:270m at 768 dims, and a real retrieval round-trip through the live engine returns ranked skills.
  CHECK: /Users/thinhkhuat/.claude/skill-concierge/venv/bin/python3 plans/261022-2356-eg2-verify-and-issue-sweep/check.py live
  EXPECT: PASS:live
  CWD: /Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge
  EVIDENCE: automatic-evidence=v1; definition-sha256=0202bcce4b3783f19e0f80a580237d2fd69ec2ad1fa609b17cf35932cd305943; exit=0; EXPECT=matched; output-sha256=9a4408082ebee2bb9406f9c43a5b71678ecf1602b7e9c778f4c890e8564de260; output-bytes=273; shell=/bin/sh; cwd=/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge; path=4b7ff6210f4b/82 entries

- [x] G2: doctor reports the Settings overrides row green — the +4 added / -11 stale drift is gone, not merely expected to self-heal.
  CHECK: /Users/thinhkhuat/.claude/skill-concierge/venv/bin/python3 plans/261022-2356-eg2-verify-and-issue-sweep/check.py doctor "Settings overrides"
  EXPECT: PASS:doctor:Settings overrides
  CWD: /Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge
  EVIDENCE: automatic-evidence=v1; definition-sha256=be42ec28ad5faeb646627978a6ffb61e5e4233864ce8d308b39781fe74beb310; exit=0; EXPECT=matched; output-sha256=3b375971cf6042bcdcd01f30b83d78a800ec5ff094f4f22ea96d14b8f346f56b; output-bytes=85; shell=/bin/sh; cwd=/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge; path=4b7ff6210f4b/82 entries

- [x] G3: doctor reports OMP integration green — the marketplace catalog matches SSOT 0.72.0 instead of the stale 0.71.3.
  CHECK: /Users/thinhkhuat/.claude/skill-concierge/venv/bin/python3 plans/261022-2356-eg2-verify-and-issue-sweep/check.py doctor "OMP integration"
  EXPECT: PASS:doctor:OMP integration
  CWD: /Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge
  EVIDENCE: automatic-evidence=v1; definition-sha256=9911743fd646aa47dfdc0b8a1141671ef87ec73976f66fcb6b75e4f260584e6e; exit=0; EXPECT=matched; output-sha256=eb131125e8e90f28091736c8a2960de334da7208beb2bf5c90689d3273b9507e; output-bytes=141; shell=/bin/sh; cwd=/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge; path=4b7ff6210f4b/82 entries

- [x] G4: doctor reports Command Code integration green — the package registry clone matches SSOT 0.72.0 instead of the stale 0.71.3.
  CHECK: /Users/thinhkhuat/.claude/skill-concierge/venv/bin/python3 plans/261022-2356-eg2-verify-and-issue-sweep/check.py doctor "Command Code integration"
  EXPECT: PASS:doctor:Command Code integration
  CWD: /Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge
  EVIDENCE: automatic-evidence=v1; definition-sha256=be41542c2ae95310c0702d3743f5b4a1fde74344d12a5cba9d9c789c382ac15d; exit=0; EXPECT=matched; output-sha256=92818021b782935a8163ccdd6410cb8064e898abc223d3ded89a00f20b002c7c; output-bytes=144; shell=/bin/sh; cwd=/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge; path=4b7ff6210f4b/82 entries

- [x] G5: A commandcode live smoke turn logs at least one search row in skill-invocation-ledger.log, proving search_skills was actually called rather than merely reported as called.
  CHECK: /Users/thinhkhuat/.claude/skill-concierge/venv/bin/python3 plans/261022-2356-eg2-verify-and-issue-sweep/check.py smoke-commandcode
  EXPECT: PASS:smoke-commandcode
  CWD: /Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge
  EVIDENCE: automatic-evidence=v1; definition-sha256=a92a2cd238520404f828559f605724eb41b029e7ba4aba7d66c8f49b7445047f; exit=0; EXPECT=matched; output-sha256=a0e8a42ca068b23a409534b0f74622a45af11bdf71b3a446741a37e37dc1f05f; output-bytes=77; shell=/bin/sh; cwd=/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge; path=4b7ff6210f4b/82 entries
