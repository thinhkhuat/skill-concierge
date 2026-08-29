# Gates — annex restore (ADR-0047)

| Gate | What proves it | Status |
|---|---|---|
| G1 | plan.md + this file on disk | DONE |
| G2 | `enforcer.py --selftest` green with restored cases (10 annex, 9d installed-only hints, 12 shape) | DONE — selftest green post reverse-apply + tune; blocklist call-sites verified; `_retrieve_external` gained `_blocked` filter |
| G3 | server.py + skills_discovery reverted; VENDORED.md note; venv copy diff-clean vs source | DONE — reverse-applied clean; VENDORED.md ADR-0047 entry; venv re-copied (pip force-reinstall exit 0) |
| G4 | flywheel/auto_flywheel/build_chains/analyze selftests green | DONE — build_chains PASS, analyze OK, flywheel_manifest PASS; `--installed-only` flag gone (default restored), `--catalog` retained |
| G5 | driftcheck exit 0; 4 manifests + package.json at 0.40.0; ADR-0047 present; ADR statuses swept | DONE — driftcheck IN SYNC; ADR-0045 Superseded, 0032/0036/0043 reinstatement notes; README/AGENTS/CLAUDE/openwiki swept |
| G6 | pytest green; live probe shows annex block, installed rows undisplaced | DONE — 90 passed / 12 pre-existing env failures (same set reproduced at HEAD in a scratch worktree); e2e_probe OK — hardened post-validator (set-compare for tied scores, hard annex-present assert), 6/6 deterministic runs; sidecar catalog key pruned (backup kept); mined-chains regenerated invocations-only (464 events) |
| G7 | blind validator report PASS in plans/reports/ | DONE — verdict PASS, 0 blockers, 3 advisories (probe flake FIXED + re-run 6/6; annex-at-cap is the ADR-0047 watch item for the v0.40.0 epoch) — plans/reports/validator-260829-1500-annex-restore.md |
| G8 | commit pushed, `git status` clean | DONE — see git log |
