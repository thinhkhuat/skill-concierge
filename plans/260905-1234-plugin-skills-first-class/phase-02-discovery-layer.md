---
phase: 2
title: "Discovery layer: union enablement + root-relative scan"
status: completed
priority: P1
effort: "4h"
dependencies: [1]
---

# Phase 2: Discovery layer

## Overview

Two structural fixes to `skills_discovery.py`: (A) plugin enablement becomes a machine-wide union across every readable `enabledPlugins` layer file, and (B) Claude plugin skills are enumerated per install root with registry-derived plugin ids instead of whole-cache globbing + path arithmetic.

## Requirements
- Functional: project-enabled plugins (agent-skills class) are indexed; user-disabled-with-no-re-enable plugins stay out; `examples/` payload trees and `temp_git_*` clones are structurally unreachable; manifest-unreadable fallback unchanged (fail-open).
- Non-functional: kill-switches (`SKILL_PLUGIN_LAYERED_ENABLEMENT`, `SKILL_CLAUDE_PROJECTS_FILE`); no schema change to Qdrant payloads; reindex cost bounded (~62 projects × 2 small JSON reads).

## Architecture

- New seam `CLAUDE_PROJECTS_FILE` (default `~/.claude.json`), env-overridable for hermetic tests.
- New `_layered_plugin_exclusions()`: reads the user settings file + `<project>/.claude/settings.json` + `<project>/.claude/settings.local.json` for every key of the projects map; returns the set of registry keys to EXCLUDE = {user-explicit-false} − {any-explicit-true-anywhere}. Absent/true/anywhere-true → included. Every read fails open (unreadable file = no signal from it; all-unreadable = no exclusions = today's fail-open posture).
- Refactor `_installed_plugin_roots()` into `_installed_plugin_entries() -> dict[registry_key, installPath] | None` (None = manifests unreadable → whole-cache fallback). The old name survives as a thin wrapper (set of paths) for existing callers/tests.
- New `_claude_plugin_skill_paths(entries)`: per entry, glob `root/skills/*/SKILL.md` + `root/skills/*/*/SKILL.md` with the existing phantom guard; names built as `f"{key.split('@',1)[0]}:{dirname}"` — registry-derived, no `sub[si-2]`.
- `_plugin_paths()` prefers entries (root-relative paths + explicit ids threaded into `parse_skill` via a name-override param or equivalent mechanism chosen at implementation); falls back to today's whole-cache glob + `_namespaced_name` heuristic when entries is None or `SKILL_PLUGIN_FILTER=0` / `SKILL_PLUGIN_LAYERED_ENABLEMENT=0` (the `=0` flag narrows exclusions to the user file only, byte-compatible with pre-change behavior for the user-file dimension).
- Docstring updates carry the ADR-0028/0034 rationale inline (repo style: load-bearing comments at the decision site).

## Related Code Files
- Modify: `vendor/skill-search/skill_search/skills_discovery.py`
- Modify: `vendor/skill-search/tests/test_discovery.py`, `vendor/skill-search/tests/conftest.py` (new seam pin + new tests monkeypatch the new entries seam)

## Implementation Steps
1. Add `CLAUDE_PROJECTS_FILE` seam + `_layered_plugin_exclusions()` with unit tests (user-false+project-true → keep; false-everywhere → drop; absent → keep; unreadable projects file → user-file-only semantics).
2. Refactor roots→entries; rewire `_plugin_paths()` to root-relative enumeration + registry ids; keep fallback byte-identical.
3. Update affected existing tests to the new seam; add root-relative tests (examples tree excluded, registry id naming, fallback intact, temp-dir unreachable).
4. Grep-sweep the class: any other consumer of `_installed_plugin_roots`/`_namespaced_name` that needs the entries view (apply-overrides, keep-on) — report, change only if broken.

## Success Criteria
- [ ] G4: layered-enablement tests pass
- [ ] G5: root-relative scan tests pass
- [ ] G1 stays green

## Risk Assessment
- Registry id ≠ path-derived id for some plugin → name drift vs existing index rows (stale points until reindex prune). Mitigation: reindex after deploy; ids come from the same registry Claude Code uses, so drift means the OLD name was wrong.
- `~/.claude.json` grows huge on some machines → read cost. Mitigation: single read, keys-only use, reindex-time only (not hot path).
- A project enables a plugin the owner forgot about → broader index. Mitigation: enforcer gate (Phase 3) keeps per-session offers precise; search surface is machine-wide by design.
