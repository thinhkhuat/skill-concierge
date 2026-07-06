---
title: "Superpowers anti-dodge integration (v0.14.0): H1-H5"
description: "Fold 5 superpowers-derived anti-skip ideas (H1-H5) into skill-concierge's doctrine/enforcement/index layer as v0.14.0 (MINOR, additive). Closes the 'doctrine is the whole bet but unmeasured' gap. All 5 net-new vs live 0.13.1; each ships default-ON behind a one-var env revert + selftest + ADR."
status: pending
priority: P1
branch: "main"
tags: [enforcer, doctrine, index, anti-dodge, telemetry, superpowers, adr]
blockedBy: []
blocks: []
relatesTo: ["260628-0215-retrieval-enrichment-rollout"]
created: "2026-07-06T06:24:46.837Z"
createdBy: "ck:plan"
source: skill
---

# Superpowers anti-dodge integration (v0.14.0): H1-H5

## Overview

Integrate 5 anti-skip ideas extracted from **superpowers v6.1.1** (Jesse Vincent / Prime Radiant, MIT — adapted, not copied) into skill-concierge as **v0.14.0** (MINOR: additive flags/lanes/lint, no breaking surface).

**Thesis.** skill-concierge is retrieval-strong but doctrine-underinvested — its own docs call in-generation governance *"the whole bet"* and *"unmeasured, not solved"* (`docs/skill-first-enforcement-mental-model.md:288-293`), and record that offering better skills didn't move usage (*"~14-18% uptake, flat"*, `openwiki/architecture/three-organs.md:23-24`). Superpowers has zero retrieval and spent all its craft on doctrine — the ideal donor for concierge's admitted weak layer. Source: `plans/reports/study-extract-superpowers-novelty-260706-1210-skill-concierge-anti-dodge-report.md`.

**The loop (H1-H2-H3).** H3 cleans the measurement → H1 measures dodges + harvests the verbatim rationalizations → H2 encodes the refutations into doctrine → re-measure. **H5** (over-fire lane + gate legibility) and **H4** (trigger-purity lint) are parallel tracks. H5 was added from a live dogfood datapoint this session: the gate forced a pointless `search_skills` on a trivially self-referential turn — the *over-fire* failure the doctrine has no symmetric guard against (`plans/reports/...anti-dodge-report.md` §H5).

**Verified net-new vs 0.13.1** (each extends a shipped foundation, none duplicates): H1 adds harvest→authoring on top of the existing false-skip *detector*; H2 converts shipped prose doctrine → symptom table; H3 adds session-scoping to unconditional `doctrine.py`; H4 adds a purity gate the shipped body-triggers (ADR-0016) lack; H5 adds a 3rd lane + legibility to the shipped 2-leg AUTHORIZED-SKIP tier (ADR-0015).

## Phases

| Phase | Name | Status | Depends on |
|-------|------|--------|-----------|
| 1 | [Spikes and Design Locks](./phase-01-spikes-and-design-locks.md) | Pending | — |
| 2 | [H3 Subagent Session Scoping](./phase-02-h3-subagent-session-scoping.md) | Pending | 1 |
| 3 | [H1 Rationalization Harvest Loop](./phase-03-h1-rationalization-harvest-loop.md) | Pending | 2 |
| 4 | [H2 Red Flags Table](./phase-04-h2-red-flags-table.md) | Pending | 1 (v1), 3 (v2) |
| 5 | [H5 Over-fire Lane and Gate Legibility](./phase-05-h5-over-fire-lane-and-gate-legibility.md) | Pending | 1 (parallel) |
| 6 | [H4 Trigger Purity Lint](./phase-06-h4-trigger-purity-lint.md) | Pending | 1 (parallel) |
| 7 | [Release and Verify](./phase-07-release-and-verify.md) | Pending | 2,3,4,5,6 |

Critical path: **1 → 2 → 3 → 4(v2) → 7**. Parallel after 1: **5**, **6**.

## Cross-cutting contracts (the traps — every phase honors these)

1. **`SKILL-CHECK:` cross-file literal contract.** The enforcer emits the marker (`enforcer.py:81`, messages `:314-324`); the audit matches **marker + a distinctive substring** — `"full-catalogue retrieval ran"` / `"intent-margin classifier"` (`audit_skill_usage.py:176-178`), deliberately NOT the bare marker (which also appears in doctrine prose, `:170-172`); the enforcer selftest asserts **EXACTLY 2** authorized-skip injects (`enforcer.py:679-713`, `:694`). H5 adds a 3rd lane → it **MUST** (a) give the new SELFREF message a **unique, prose-unlikely signature phrase**, (b) add THAT phrase to the audit marker-match, (c) bump the selftest 2→3, AND (d) add a parity selftest asserting the new anchor does NOT match the getaway/intent messages or the H2 doctrine-table row. A too-generic anchor (e.g. `"self-referential"`) collides with the H2 table (Phase 4) → the audit miscounts real false-skips as authorized, masking the exact dodges H1 measures. [Red-Team F8, quad-convergent]
2. **Governance-flag one-var revert.** New flags follow `os.environ.get("NAME","1") != "0"` (default-ON) — mirror `ENFORCER_AUTHORIZED_SKIP` (`enforcer.py:78`) / `SKILL_BODY_TRIGGERS` (`server.py:88`). New: `SKILL_SUBAGENT_STOP` (H3), `ENFORCER_SELFREF_SKIP` (H5), `SKILL_TRIGGER_PURITY` (H4). Document each inline + in `skill-concierge/CLAUDE.md` governance list.
3. **Epoch-scoped measurement (HARD).** H1's re-measure windows on the deploy commit via `scripts/analyze.py --since/--until` (repo-root path, windowing at `:233-235` / parser `:90` — NOT co-located with the audit script, NOT `:248-254`). NEVER pool a rate across config epochs (`AGENTS.md:73-92`). **Honesty caveat [Red-Team F6]:** shipping v0.14.0 opens a NEW epoch, and this repo changes ledger inputs ~daily → the post-deploy window may be "insufficient data" before the next config change resets it. The **harvest** leg of H1 is epoch-independent and keeps its value; the **re-measure** leg is contingent on a config-freeze window (see Phase 3). Exclusion of subagent/self/meta requires the sid-join fix (Phase 3), which is NOT free with current turn segmentation.
4. **Deploy triple-bump + doc gate.** `plugin.json` + `marketplace.json` + `CHANGELOG.md` bump together → 0.14.0; `/plugin-scaffold` + `/working-with-claude-code` are MANDATORY first stops before editing manifests (ENFORCED `claude-code-component-building.md` Rule B.0).
5. **H4 reindex dependency.** Trigger-purity takes effect only after the vendored engine is re-copied into the stable venv + a reindex + MCP restart (ADR-0016 deploy dep; `docs/adr/0016...md:53-55`).

## Dependencies (cross-plan)

- **`260628-0215-retrieval-enrichment-rollout` (in-progress, P2) — OVERLAP.** Its Phase 2 "doctrine re-injection" and Phase 4 "clean-window compliance measurement" overlap this plan's H2/H1/H3; it also moved `GETAWAY_FLOOR` (H5's file). Its Phase 1 (enrichment) already shipped live, so nothing live conflicts. **OPEN — owner call:** does this plan *supersede* 260628-0215's remaining compliance-side phases, or run coordinated? Not silently decided (see Open Questions). Marked `relatesTo`, not `blockedBy`.
- Predecessor (shipped, not blocking): `260704-...usefulness-rate-upgrades` shipped the AUTHORIZED-SKIP tier + library doctrine (ADR-0015) that H5/H2 extend.

## Open questions

**RESOLVED — Owner decision 2026-07-06: Option B locked.** All 5 (H1-H5) ship in **v0.14.0**, every red-team *correctness* fix applied, caveats documented loudly in **[`docs/anti-dodge-integration-v0.14.md`](../../docs/anti-dodge-integration-v0.14.md)**. Owner rationale: rich lived experience with this plugin's real behavior outweighs 4 stateless cold-boot reviewers on the *scope/value* call — their correctness findings are accepted and applied; only their scope-cut recommendation (F11/F13) is overruled. **Accepted knowingly:** the epoch/measurability caveat (H1 re-measure may be "insufficient data" this epoch — the harvest leg still delivers), the reindex on the critical deploy path (H4), and H4's subjective heuristic (shadow-first).

1. **Cross-plan coordination [F14] — PRECONDITION, not a blocker:** only ONE config-touching plan ships per epoch. Coordinate with `260628-0215-retrieval-enrichment-rollout` so its compliance phases and this plan's H1 re-measure never open overlapping T0 windows on the shared ledger. Hard release precondition (Phase 7).
2. **H3 mechanism (Phase-1 spike):** does the SessionStart hook payload expose a subagent/dispatch signal? If subagents don't fire the plugin SessionStart at all, H3 collapses to an audit-side exclusion only.
3. **H4 purity precision:** the "workflow-summary vs trigger-condition" heuristic is net-new + subjective → ship SHADOW-first, measure the false-drop rate before activating.
4. **ADR numbering:** confirm next-free on `main` — the archived bge-m3 plan created a `0019` on a *feat* branch; verify no collision before claiming 0019-0023.

## Red Team Review

### Session — 2026-07-06
4 hostile reviewers (Security Adversary, Failure Mode Analyst, Assumption Destroyer, Scope & Complexity Critic), each verifying claims against live code. **Verdict: REQUEST CHANGES.** Anchors verified accurate; findings are real design bugs in the 3 core mechanisms + over-scoping. `⚑` = ≥2 reviewers converged.

**Findings: 14 accepted / 2 minor.** Severity: 5 Critical, 6 High, 3 Medium.

| # | Finding | Sev | Disp | Applied |
|---|---------|-----|------|---------|
| 1 ⚑ | **H5 lane = real-work bypass.** Enforcer sees only the user prompt (`enforcer.py:463`); a self-ref opener + tail task verb slips the lead-token-only `_is_imperative` check (`:408-430`); outright-skip is scored *authorized* → invisible to H1 | Crit | Accept | Phase 5 ✅ |
| 2 ⚑ | **H5 subject confusion.** Spec is 1st-person ("my output"); detector sees 2nd-person user prompt ("your answer") → misfires either way | High | Accept | Phase 5 ✅ |
| 3 ⚑ | **H3 fail-direction inverted + signal absent.** `doctrine.py` is fail-SILENT (`except→return 0` = SUPPRESS, `:61-62`); naive wrapper fails CLOSED, drops doctrine on real sessions. SessionStart payload carries NO subagent signal (`source ∈ startup/resume/clear/compact`) → only audit-side exclusion survives | Crit | Accept | Phase 1+2 ✅ |
| 4 ⚑ | **H1 "clean denominator" impossible.** Turn dicts carry no `sid` (`audit:158-159,236-237`); `false_skip` computed (`:240`) before `meta_sessions` exists (`:247`); no join key | Crit | Accept | Phase 3 ✅ |
| 5 | **H1 capture reads wrong `txt`.** `txt` is loop-local to the inner block loop (`:220`); at flush it's stale/unbound → garbage corpus | High | Accept | Phase 3 ✅ |
| 6 ⚑ | **H1 re-measure may be UNMEASURABLE this epoch** (`AGENTS.md:84` "insufficient data"; config churns ~daily) | Crit | Accept | Phase 3 + xcut#3 ✅ |
| 7 | **H1 harvest = new data-exposure surface.** Emits verbatim transcript text (may hold secrets/paths), no sink/scrub/gitignore | High | Accept | Phase 3 ✅ |
| 8 ⚑ | **SKILL-CHECK anchor must be a UNIQUE signature** — audit matches marker+substring, not bare marker (`:170-178`); generic anchor collides w/ H2 row | High | Accept | Phase 5 + xcut#1 ✅ |
| 9 | **Deploy freshness gate.** H2/H5 go live on `/plugin update`; engine stays stale until `setup.sh`. Make engine-freshness (content-hash, ADR-0013), not `venv ✓`, a HARD gate | High | Accept | Phase 7 ✅ |
| 10 | **H4 mixed-purity index.** Incremental content-hash reindex only re-touches CHANGED phrases; a filter-logic change needs a FULL reindex | Med | Accept | Phase 6 ✅ |
| 11 ⚑ | **SCOPE: cut H4 to its own plan.** Ships inert (shadow), drags the whole engine-deploy chain | Crit | **OVERRULED (owner)** | H4 ships in v0.14.0; caveat documented |
| 12 ⚑ | **SCOPE: H5 legibility is gold-plating** + risks the anchor contract → ship lane only, defer legibility | High | Accept | Phase 5 ✅ |
| 13 ⚑ | **SCOPE: MVP = H3 + H5-lane; defer H1/H2-v2/H4** | High | **OVERRULED (owner)** | all 5 ship (Option B) |
| 14 ⚑ | **Cross-plan: resolve `260628-0215` before H1** — two T0 windows = unattributable delta (its own red-team M7b) | Crit | Accept → coordinate | Phase 7 precondition ✅ |
| M1 | `analyze.py` is at `scripts/analyze.py` (root), windowing `:233-235` not `:248-254` | Med | Accept | xcut#3 ✅ |
| M2 | "I already searched last turn" already exists (`skill-first.md:54`) — a reformat, not a new row | Low | Accept | Phase 4 (on scope-lock) |

**Design compass (all 4 reviewers):** the 3 core bugs point AWAY from the plan's own "burden of proof on SKIP / more governance" doctrine (`skill-first.md:89`). Correct direction — H5: don't blanket-bless, narrow hard + fall through on any task tail; H3: fail TOWARD injection, audit-side primary; H1: keep raw text local, be honest that this-epoch measurement may not close.

**What "Reject" would look like:** none rejected — all 14 passed the evidence filter with `file:line`. Two (M2) are trivial reformat notes.

### Whole-Plan Consistency Sweep
- Applied now (scope-independent, correct regardless of ship-timing): F1/F2/F8/F12 → Phase 5; F3 → Phases 1+2; F4/F5/F6/F7 → Phase 3; F6/M1 → xcut#3; F8 → xcut#1.
- **Owner decision 2026-07-06 (Option B):** F9/F10 now APPLIED (Phase 7 freshness gate, Phase 6 full-reindex). F11/F13 (scope-cut) OVERRULED — all 5 ship in v0.14.0; accepted caveats documented loudly in `docs/anti-dodge-integration-v0.14.md`. F14 becomes a hard release precondition (one config-touching plan per epoch).
- No contradictions remain. The plan is Phase-1-ready (spikes); F14 cross-plan coordination is confirmed as a Phase-7 precondition, not a blocker.

## Attribution

Anti-skip ideas adapted (not copied) from **superpowers v6.1.1** — Jesse Vincent (jesse@fsck.com) / Prime Radiant — MIT — https://github.com/obra/superpowers. Concepts carried into concierge's own design; no text lifted.
