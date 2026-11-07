---
title: A force rebuild of the shared skill index silently deletes the points other directories own
author: Thinh
date: 2026-11-07
branch: main
id: l-8fd2a2f2
scope: repo
status: active
src: agent
---

## Decided
A `force=True` index rebuild is NOT a safe way to refresh skill-concierge's index.
`build_index` deletes the collection and then rewrites only what `discover_skills()`
finds from the CURRENT working directory — and skill scopes are CWD-relative
(`skills_discovery.visible_scopes()`). One Qdrant collection is shared by every
session on the machine, so it carries points from several roots at once.

Measured on this machine: rebuilding from the plugin root alone produced 45,857
points against a live 46,560 — **703 points silently gone** (655 from
`VGP/.claude/skills`, 48 from `skills-dev/.opencode/skills`). Nothing errors. The
count just comes out lower.

Refresh by running the ordinary incremental `build_index(force=False)` from EVERY
root that owns points — plugin root, `VGP`, `skills-dev` — or accept that a force
rebuild drops the others.

## Tried and ruled out
- **Trusting the point count from the build's own receipt as proof of success.**
  `{"indexed": 2959, "points": 45857}` reads like a clean build; the missing 703
  only appear when diffed against the live collection by point id.
- **Reading a shortfall as a discovery bug.** It is not: discovery is correct for
  its CWD by design, which is what stops one session pruning another's points.

## Watch out
- **Verify a rebuild by set-difference, not by count.** Scroll both collections,
  diff the point ids, and bucket what is missing by `scope` — the scope name is
  what tells you which root has to run next. A matching total is the only proof
  that nothing was lost; a plausible total is not.
- **A backup collection must be built the same multi-root way.** A staging
  collection built from one root looks complete and is not, so "the backup is
  ready" is a false claim until the diff is empty in both directions.
- **The CWD trap also applies to `SKILL_COLLECTION` overrides** used for staging:
  a staging build inherits the same single-root blindness.

In the code:
- `skill_search/server.py` — `build_index(force)`: `delete_collection` then rewrite
- `skills_discovery.visible_scopes()` — CWD-relative ownership
- the three roots to run from: `skill-concierge`, `in-PROD/MY-WORKBENCH/VGP`,
  `in-PROD/MY-WORKBENCH/skills-dev`
- numbers: 45,857 vs 46,560 live = 703 short; per-root deltas 655 and 48
