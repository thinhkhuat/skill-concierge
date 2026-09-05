---
title: ADR-0052 plugin-skills first-class fixes shipped (v0.45.0)
date: 2026-09-05
summary: "Three validated plugin-skill defects fixed end-to-end and pushed (62ce8bc): layered enablement UNION at index time (~/.claude.json projects registry; agent-skills 25 skills recovered), root-relative plugin scan with registry-derived ids (examples:workflow phantom + temp_git hits dead structurally), ENFORCER_PLUGIN_GATE session subtraction (ponytail). Plus: hermetic conftest pins close the 12 pre-existing ZCode/DSH/Cline isolation failures (suite 12F/71P -> 90P). Verified: engine 90 green, root 19, selftest + driftcheck 0, live probe 83 names exact, APPROVE-WITH-NITS review, blind-validator PASS with 5 advisories applied pre-commit. Runtime pickup pending owner: /plugin marketplace update, then doctor --fix. Epoch boundary for offer metrics at v0.45.0."
---

# ADR-0052 plugin-skills first-class fixes shipped (v0.45.0)

Three validated plugin-skill defects fixed end-to-end and pushed (62ce8bc): layered enablement UNION at index time (~/.claude.json projects registry; agent-skills 25 skills recovered), root-relative plugin scan with registry-derived ids (examples:workflow phantom + temp_git hits dead structurally), ENFORCER_PLUGIN_GATE session subtraction (ponytail). Plus: hermetic conftest pins close the 12 pre-existing ZCode/DSH/Cline isolation failures (suite 12F/71P -> 90P). Verified: engine 90 green, root 19, selftest + driftcheck 0, live probe 83 names exact, APPROVE-WITH-NITS review, blind-validator PASS with 5 advisories applied pre-commit. Runtime pickup pending owner: /plugin marketplace update, then doctor --fix. Epoch boundary for offer metrics at v0.45.0.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
