---
title: "plugin-skills-first-class"
description: "Make plugin-bundled skills correctly and reliably first-class: layered enablement at index+offer time, root-relative plugin scan, delivery per repo protocol"
status: completed
priority: P1
effort: "~0.5d"
tags: [discovery, enforcer, plugin-skills, delivery]
created: 2026-09-05
---

# plugin-skills-first-class

## Overview

Validation (2026-09-05 session) proved plugin skills are first-class by design but found three defects that cause or contribute to their failure, plus a red test baseline that hides regressions. This plan fixes all four, then ships per the repo protocol. Out of scope by owner decree: command-style plugin entries (ADR-0001 doctrine, owner reaffirmed 2026-09-05).

## Goals

| # | Goal | Priority |
|---|------|----------|
| 1 | Fix test isolation: pin ZCode/DSH/Cline harness seams in the hermetic conftest (12 pre-existing engine-suite failures) | P1 |
| 2 | Fix A — layered enablement at index time: union across user + all registered project layer files; user-false alone no longer erases project-enabled plugins (agent-skills class) | P1 |
| 3 | Fix B — root-relative plugin scan: enumerate skills per install root with registry-derived ids; kill `examples:workflow` phantom + temp_git hits | P1 |
| 4 | Fix C — enforcer per-session gate: `plugin` rows offered in Claude sessions must pass the already-layer-merged `INVOCABLE_PLUGIN_IDS` (ponytail class) | P1 |
| 5 | Ship: ADR-0052, CHANGELOG/README, 4-manifest version bump, openwiki parity, push; runtime pickup documented as owner's `/plugin marketplace update` | P1 |

## Phases

| # | Phase | Status |
|---|-------|--------|
| 1 | [Phase 1: Test-isolation repair](./phase-01-start.md) | Completed |
| 2 | [Phase 2: Discovery layer](./phase-02-discovery-layer.md) | Completed |
| 3 | [Phase 3: Enforcer session gate](./phase-03-enforcer-session-gate.md) | Completed |
| 4 | [Phase 4: Delivery and ship](./phase-04-delivery-and-ship.md) | Completed |

## Evidence (validated this session, 2026-09-05)

- Discovery reads enablement from `~/.claude/settings.json` only: `vendor/skill-search/skill_search/skills_discovery.py:166-168, :263`. Live casualties: `agent-skills@addy-agent-skills` user-false + `.claude/settings.local.json` true → 25 invocable skills indexed nowhere; `ponytail` user-absent + local-false → indexed and offered.
- The enforcer already merges all three layers: `hooks/scripts/enforcer.py` `_invocable_plugin_ids` (user + cwd project + cwd local). Its offer post-filter (`:1302`) gates only `FOREIGN_SCOPES` rows; `plugin` scope is not foreign in Claude sessions (`:378`).
- Phantom: `examples:workflow` indexed — nested glob admits `<plugin>/examples/*/skills/*/SKILL.md`, `sub[si-2]` misreads `examples` as plugin id (`skills_discovery.py:305-306`). Temp-dir hits: `temp_git_*` clones inside `PLUGIN_GLOB`'s `**`.
- Baseline: full engine suite 12 failed / 71 passed; root tests 19 passed; enforcer + build_chains + analyze selftests OK; driftcheck 0. All 12 = one class: ADR-0042/0050/0051 added ZCode/DSH/Cline seams without extending `vendor/skill-search/tests/conftest.py::_isolate_harness_roots` (which pins Codex/OMP only).
- Machine-wide enablement union source verified live: `~/.claude.json` `.projects` = 62 registered roots incl. this repo (jq-verified).
- Deployment topology: real versioned copies under `~/.claude/plugins/cache/`, marketplace checkout at `~/.claude/plugins/marketplaces/skill-concierge`; no symlink. Runtime pickup = owner's `/plugin marketplace update` (RULES.md [26] reserves it).

## Design decisions

- **Union, not last-writer-wins, at index time.** The Qdrant collection is machine-global (ADR-0028 forbids baking cwd views into it). Index a plugin iff installed AND NOT (user-false AND no explicit true in any readable layer). Per-session precision lives at the session layer (enforcer gate), matching the ADR-0034 pattern. Rejected: per-project indexes (redesign); cwd-layer merge at discovery (reintroduces the ADR-0028 prune fight).
- **Registry-derived ids and roots.** Enumerate skills from each `installPath` (kills old versions, `examples/` payload trees, temp_git clones structurally) and take the plugin id from the registry KEY, not path arithmetic. Whole-cache glob + `_namespaced_name` heuristic survives only as the manifest-unreadable fallback (fail-open preserved).
- **Kill-switches per repo convention:** `SKILL_PLUGIN_LAYERED_ENABLEMENT=0` (restores user-file-only enablement), `SKILL_CLAUDE_PROJECTS_FILE` env (hermetic tests), `ENFORCER_PLUGIN_GATE=0` (restores ungated plugin offers).
- **Epoch note:** the enforcer gate changes what the offer ledger measures — new epoch for offer-composition metrics; no rates may be pooled across it (AGENTS.md Guardrails).

## Success Criteria

- [x] Full engine suite green (was 12 failed / 71 passed → 90 passed / 0 failed)
- [x] `agent-skills:*` discovered by the dev engine against the live machine; `examples:*` and temp_git hits gone; `ponytail:*` still indexed (union semantics)
- [x] Enforcer offers drop plugin rows disabled in the session's merged layers (selftest-proven)
- [x] driftcheck 0; version parity across 4 manifests + CHANGELOG + README + openwiki
- [x] Independent blind validator PASS (plans/reports/validator-260905-1332-adr0052-plugin-skills.md); committed 62ce8bc and pushed to origin/main

## Unresolved questions

- None blocking. Runtime pickup (`/plugin marketplace update`) is owner-owned and documented as the single post-ship manual step.
