---
phase: 1
title: "Test-isolation repair (green baseline)"
status: completed
priority: P1
effort: "1h"
dependencies: []
---

# Phase 1: Test-isolation repair

## Overview

The hermetic conftest pins Codex/OMP harness seams but not ZCode/DSH/Cline, so the live machine's `~/.zcode/cli/plugins/cache/**` (and potentially `~/.ohdsh`, `~/.cline`) leak into discovery and disk-signature tests. 12 engine-suite failures pre-date any change. Fix the fixture, prove the suite green BEFORE the real fixes land.

## Requirements
- Functional: every engine-suite test passes in isolation from live machine state.
- Non-functional: tests that deliberately exercise a harness seam still opt in explicitly (fixture docstring contract preserved).

## Architecture

`vendor/skill-search/tests/conftest.py::_isolate_harness_roots` (autouse) gains pins for every seam added by ADR-0042/0050/0051: `ZCODE_PERSONAL_ROOT`, `ZCODE_PROJECT_ROOT`, `ZCODE_AGENTS_PROJECT_ROOT`, `ZCODE_PLUGIN_CACHE`, `ZCODE_INSTALLED_PLUGINS_JSON`, `ZCODE_CONFIG_JSON`, `DSH_PERSONAL_ROOT`, `DSH_PROJECT_ROOT` (+ `DSH_HOME` if needed), `CLINE_PERSONAL_ROOT`, `CLINE_PROJECT_ROOT` — all to `tmp_path` children, mirroring the existing Codex/OMP pin style.

## Related Code Files
- Modify: `vendor/skill-search/tests/conftest.py`

## Implementation Steps
1. Add the missing monkeypatch pins to the autouse fixture.
2. Run the full engine suite; expect the 12 baseline failures green.
3. Run root tests + enforcer selftest; expect unchanged green.

## Success Criteria
- [ ] Full engine suite: 0 failed (G1)
- [ ] Root tests green (G2)

## Risk Assessment
Over-pinning could hide a real regression where a test SHOULD see a harness seam — mitigated by the fixture's opt-in pattern: tests needing real seams already monkeypatch them explicitly (existing Codex/OMP tests do exactly this).
