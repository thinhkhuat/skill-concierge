---
phase: 4
title: "Delivery: ADR, release parity, ship"
status: completed
priority: P1
effort: "2h"
dependencies: [3]
---

# Phase 4: Delivery and ship

## Overview

Record the decision (ADR-0052), ship per the repo protocol (4-manifest version bump, CHANGELOG, README, openwiki parity, driftcheck), verify the dev engine against the live machine, run the independent blind validator, commit and push. Runtime pickup is owner-owned (`/plugin marketplace update`, RULES.md [26]) and is documented as the single post-ship manual step with its verification recipe.

## Requirements
- Functional: every ship gate green; the dev engine's live-machine probe shows the fixed behavior; validator verdict PASS.
- Non-functional: no in-place patching of the deployed plugin cache or venv (versioned copies stay consistent; doctor freshness untouched).

## Architecture

Ship sequence (repo protocol): ADR-0052 → CHANGELOG + README version entries → bump `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `.codex-plugin/plugin.json`, `package.json` (0.45.0 — behavior change, minor bump) → `openwiki/quickstart.md` version line → `driftcheck.py` exit 0 → dev-engine live probe (G6) + engine health (G8) → blind validator (G9) → conventional commit → push (G10). Post-ship handoff text for the owner: run `/plugin marketplace update`, then reinstall if version-pinned, then `doctor --fix` (reindex) and re-run the probe expectation against the deployed engine.

## Related Code Files
- Create: `docs/adr/0052-plugin-enablement-layering-and-root-relative-scan.md`
- Modify: `CHANGELOG.md`, `README.md`, `openwiki/quickstart.md`, `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `.codex-plugin/plugin.json`, `package.json`
- Create: `plans/260905-1234-plugin-skills-first-class/probe_dev_discovery.py` (probe script; plan-local scratch, also serves G6)

## Implementation Steps
1. Write ADR-0052 (decision, evidence, union rationale, kill-switches, epoch boundary).
2. Version bump + CHANGELOG + README + openwiki version line; driftcheck to 0.
3. Write + run the dev-engine probe (G6) and health check (G8).
4. Spawn the blind validator with the diff; file its verdict under `plans/reports/` (G9).
5. Conventional commit (no AI attribution) covering the fix set + docs + plan; push origin main (G10).
6. Journal entry (ak:journal) + handoff text with the owner's post-update recipe.

## Success Criteria
- [ ] G6, G7, G8, G9, G10 all met with evidence

## Risk Assessment
- Push is irreversible-ish (public repo) — mitigated by full gate chain + validator PASS before the commit; owner rule [26] defines push as the go-live step.
- Owner forgets the post-update step → fixes stay unlive. Mitigation: final report leads with the one manual step + exact verification commands.
