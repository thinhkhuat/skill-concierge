---
phase: 4
title: "ADR-0032 + docs + ship"
status: completed
priority: P1
effort: "1.5h"
dependencies: [1, 2, 3]
---

# Phase 4: ADR-0032 + docs + ship

## Overview
Record the decision, sweep docs, version, validate, ship.

## Requirements
- Functional: ADR-0032 supersedes ADR-0031's search-only stance (annex + usage-
  promotion); README/CHANGELOG/AGENTS/openwiki reflect first-class externals;
  version 0.23.0 across plugin.json + marketplace.json; driftcheck exit 0.
- Non-functional: blind validation before commit; doctor green (modulo restart
  drift); openwiki parity guard passes.

## Architecture
- ADR-0032 marks ADR-0031 "Superseded in part" (search-only tier → annex); keeps
  ADR-0031's catalog-roots/scope/tier mechanics (still the substrate).
- Doctrine `skill-first.md`: the offer can carry an external annex; `USING:` an
  annex row = get_skill read-inline (already documented; reinforce).

## Related Code Files
- Create: `docs/adr/0032-external-catalogs-first-class-annex.md`.
- Modify: `docs/adr/README.md`, `docs/adr/0031-*.md` (Superseded-in-part note),
  `README.md`, `CHANGELOG.md`, `AGENTS.md`, `openwiki/quickstart.md`,
  `openwiki/architecture/enforcement-gate.md`, `.claude-plugin/*.json`,
  `hooks/doctrine/skill-first.md`.

## Implementation Steps
1. Write ADR-0032 with Evidence section (filled from live proof).
2. ADR-0031 header: "Superseded in part by ADR-0032 (search-only → annex)".
3. Docs sweep + version bump 0.23.0 + CHANGELOG + roadmap entry.
4. driftcheck exit 0; full selftests + engine suite; doctor.
5. Blind validator (fresh agent) over the whole diff; fix any real findings.
6. Conventional commit + push.

## Success Criteria
- [x] ADR-0032 accepted + ADR-0031 cross-linked.
- [x] driftcheck exit 0; all selftests + engine suite green; doctor OK-modulo-drift.
- [x] Blind validation: no unaddressed real findings.
- [x] Committed + pushed; worktree clean.

## Risk Assessment
- Doc drift (the ADR-0031 experience): run driftcheck before commit; the openwiki
  parity guard blocks a mismatched version at commit time.
