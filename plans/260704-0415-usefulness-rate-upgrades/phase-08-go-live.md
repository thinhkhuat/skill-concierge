---
phase: 8
title: Go-live
status: in-progress
effort: S
---

# Phase 8: Go-live — LOCAL only, HOLD the push

## Overview
Stage the release locally per the plugin convention, but stop before the remote push. The user reviews the
diff, pushes, and runs `/plugin update` + restart.

## Requirements
- Version bumped in BOTH manifests together (never one alone — repo rule).
- Merge to `main` locally; **NO `git push`**.

## Related Code Files
- Modify: `.claude-plugin/plugin.json` (0.11.1 → 0.12.0)
- Modify: `.claude-plugin/marketplace.json` (0.11.1 → 0.12.0)
- Modify: `CHANGELOG.md` (`[Unreleased]` → `[0.12.0] — 2026-07-04`)

## Implementation Steps
1. Bump `version` to `0.12.0` in `plugin.json` AND `marketplace.json` (verified today both at 0.11.1).
2. Finalize CHANGELOG: move the Unreleased entries under `## [0.12.0] — 2026-07-04`.
3. Stage + commit on `feat/usefulness-rate-upgrades-0.12.0` with a conventional message (no AI attribution).
4. `git switch main` → `git merge --no-ff feat/usefulness-rate-upgrades-0.12.0`. Resolve any conflict (lead
   owns shared files). Confirm `git log --oneline --graph -8`.
5. **DO NOT push.** Leave the remote untouched.
6. Emit the user handoff: exact commands to finish go-live themselves —
   `git push origin main`, then `/plugin update` + restart (runtime reads a version-pinned cache; a repo edit
   is not live until pushed + updated).

## Success Criteria
- [ ] `plugin.json` + `marketplace.json` both `0.12.0`; CHANGELOG finalized as `[0.12.0]`.
- [ ] Feature branch merged to `main` locally (`--no-ff`); working tree clean.
- [ ] `git status` shows `main` AHEAD of origin (un-pushed); **no push performed**.
- [ ] User handed the exact `git push` + `/plugin update` + restart commands.

## Risk Assessment
- Accidental push. Mitigate: explicit HOLD; no `git push` in any step; final report states "not pushed".
- Version drift between manifests. Mitigate: bump both in the same step; grep-verify equal.
