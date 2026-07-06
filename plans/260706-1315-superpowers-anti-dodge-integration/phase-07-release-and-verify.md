---
phase: 7
title: "Release and Verify"
status: pending
effort: "S"
---

# Phase 7: Release and Verify

## Overview

Cut **v0.14.0**: doc-gated manifest edits, triple-bump, all selftests + vendor pytest green, deploy live, doctor green, and record the epoch boundary for H1's clean-window re-measure. Depends on: Phases 2,3,4,5,6.

## Requirements

- Functional: version bump + CHANGELOG; all tests green; deploy live; `doctor status: OK`; epoch anchor recorded.
- Non-functional: **MINOR** bump — additive flags/lanes/lint, no removed/renamed surface, no breaking hook/schema change.

## Architecture (release gate)

- **Rule B.0 (ENFORCED) FIRST:** before editing manifests, invoke `/plugin-scaffold` + `/working-with-claude-code` and cite the relevant sections verbatim (manifest fields, update flow, version-bump signaling).
- **Triple-bump 0.13.1 → 0.14.0:** `.claude-plugin/plugin.json:3`, `.claude-plugin/marketplace.json:8` (`metadata.version`), `CHANGELOG.md` (new section under `## [Unreleased]`, group `### Added` / `### Changed`, link ADRs 0019-0023). Preserve UTF-8 (`ensure_ascii=False`; grep the `—` glyphs after any JSON re-dump).
- **Index the ADRs:** `docs/adr/README.md`.
- **Tests (the bar):** `enforcer.py --selftest` (now asserts **3** injects), `audit_skill_usage.py --selftest` (harvest case), `analyze.py --selftest`, and `vendor/skill-search/tests/` pytest (discovery/indexing). All green.
- **Deploy:** push → `/plugin update` (or `/plugin marketplace update`) + restart → H4 needs engine re-copy into the stable venv + reindex (`setup.sh`) → `skill-concierge:doctor` green `status: OK`.
- **Engine-freshness HARD gate [Red-Team F9, High].** H2/H5 go live on `/plugin update` alone (cache path), but the MCP runs the OLD venv engine until `setup.sh` reruns. `doctor "Engine venv ✓"` proves existence, NOT currency (`caveats.md:164-176`). Release is NOT done until engine freshness is verified by content-hash (ADR-0013), not just the venv-exists check — else v0.14.0 ships new doctrine/enforcer against a stale 0.13.1 engine.
- **F14 precondition:** confirm no other config-touching plan (`260628-0215`) ships between this epoch anchor and the H1 re-measure.
- **Epoch:** the deploy commit is the `--since` anchor for H1's re-measure. Record it in the ADR + plan.

## Related Code Files

- Modify: `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `CHANGELOG.md`, `docs/adr/README.md`

## Implementation Steps

1. `/plugin-scaffold` + `/working-with-claude-code` → cite manifest + version-bump specs verbatim.
2. Triple-bump → 0.14.0; CHANGELOG entry linking ADRs 0019-0023; UTF-8 safe.
3. Run all 4 selftest/pytest suites → all green (paste output).
4. Deploy: push, `/plugin update` + restart, engine re-copy + reindex (H4), `doctor` OK.
5. Record the deploy commit as the epoch boundary; schedule the H1 clean-window re-measure.

## Success Criteria

- [ ] `/plugin-scaffold` + `/working-with-claude-code` cited before any manifest edit.
- [ ] `plugin.json` + `marketplace.json` + `CHANGELOG.md` all at 0.14.0 (UTF-8 intact).
- [ ] `enforcer` / `audit` / `analyze` selftests + vendor pytest ALL green (output shown).
- [ ] `doctor status: OK` after deploy (engine freshness verified, not just venv-exists).
- [ ] Epoch boundary (deploy commit) recorded for the H1 re-measure.

## Risk Assessment

- **Stale-engine trap** (`docs/caveats.md:164-176`): `/plugin update` ships the cache but the MCP runs the OLD venv copy until `setup.sh` reruns; `doctor "Engine venv ✓"` proves existence, not currency. → force engine re-copy + reindex + verify freshness.
- **Asymmetric bump** (manifest moved, a touched `SKILL.md` didn't) → include any skill-frontmatter bumps in lock-step.
- **H4 shipped inert** — release ships H4 in SHADOW (or off); it does not activate at release, per Phase 6.
