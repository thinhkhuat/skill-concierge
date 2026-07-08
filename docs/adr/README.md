# Architecture Decision Records

Decision records for **skill-concierge** — the *why* behind the design, captured so a
future maintainer (or agent) does not have to reverse-engineer intent from code comments.

> These ADRs exist because the intent *wasn't* loud enough once: an agent read the
> injected skill-catalogue, assumed built-in commands were indexable, ran the vendored
> eval, and drew wrong conclusions about retrieval quality. ADR-0001 + `../caveats.md`
> are the fix. Read them before judging the engine.

## Index

| ADR | Title | Status | Date |
|-----|-------|--------|------|
| [0001](0001-index-model-invocable-skills-only.md) | Index model-invocable `SKILL.md` only — exclude built-in/user-only commands | Accepted | 2026-06-26 |
| [0002](0002-fusion-which-plus-whether.md) | Fusion architecture — skill-search (WHICH) × skill-first (WHETHER) | Accepted | 2026-06-26 |
| [0003](0003-embedder-and-vector-store.md) | Multilingual mpnet-768 embedder + Qdrant server tier | Accepted | 2026-06-26 |
| [0004](0004-bundled-mcp-launcher-stable-venv.md) | Bundled MCP via launcher + stable venv (survive cache wipes) | Accepted | 2026-06-26 |
| [0005](0005-overrides-target-and-applier.md) | Keep-on overrides → `~/.claude/settings.json`, atomic applier (not upstream generator) | Accepted | 2026-06-26 |
| [0006](0006-compounding-invocation-ledger.md) | Compounding, never-rotated invocation ledger (logman `RETENTION_DAYS=0`) | Accepted | 2026-06-26 |
| [0007](0007-maintenance-skills-setup-doctor.md) | Maintenance skills (`setup` + `doctor`) — delegate health to the engine, fix only what is safe | Accepted | 2026-06-26 |
| [0008](0008-warm-embed-shim-timeout-calibration.md) | Warm embed shim Docker sidecar + timeout calibration (90ms → later relaxed to 200ms; see ADR note) | Accepted | 2026-06-26 |
| [0009](0009-operator-set-gate-thresholds.md) | Operator-set gate thresholds over data-backed defaults (word floor 2→5, score floor 0.40→0.45) | Superseded by 0017 (word floor by 0010) | 2026-06-29 |
| [0010](0010-word-floor-5-to-3.md) | Word floor 5→3 — let the language-aware imperative-veto see 4–5-word commands | Accepted | 2026-06-29 |
| [0011](0011-ledger-derived-offer-suppression.md) | Ledger-derived offer-suppression (`keep-off.json`) — auto-drop chronic never-take skills from the menu | Accepted | 2026-06-29 |
| [0012](0012-multi-vector-max-pool-retrieval.md) | Multi-vector MAX-pool retrieval (trigger layer) — score each skill by its best phrase point | Accepted | 2026-06-30 |
| [0013](0013-doctor-engine-freshness-check.md) | doctor `Engine freshness` check — detect a stale MCP venv engine after `/plugin update` | Accepted (amended by 0018) | 2026-07-01 |
| [0014](0014-sessionstart-index-self-heal.md) | SessionStart index self-heal (`auto_reindex.py`) — detached/throttled incremental reindex | Accepted | 2026-07-01 |
| [0015](0015-authorized-skip-tier-and-library-doctrine.md) | AUTHORIZED-SKIP tier + library doctrine — enforcer emits a `SKILL-CHECK:` authorization on its silent verdict legs | Accepted | 2026-07-04 |
| [0016](0016-body-derived-trigger-points.md) | Body-derived trigger points — mine each skill body's labeled decision-sections into the MAX-pool trigger layer | Accepted | 2026-07-04 |
| [0017](0017-enforcer-gate-thresholds-v2-widen-offer-menu.md) | Enforcer gate thresholds v2 — retain score floor 0.45, widen offer-menu TOP_K 5→8 (+ companion `search_skills` query fanout) | Accepted (supersedes 0009) | 2026-07-05 |
| [0018](0018-self-healing-launcher-engine-resync.md) | Self-healing launcher — auto-resync the venv engine on plugin-version change (no more stale MCP after `/plugin update`) | Accepted (amends 0013) | 2026-07-05 |
| [0019](0019-over-fire-lane-and-gate-legibility.md) | H5 over-fire authorized-skip lane — narrow self-referential lane + whole-prompt task-verb veto (gate legibility deferred) | Accepted | 2026-07-06 |
| [0020](0020-subagent-session-scoping.md) | H3 subagent session-scoping — suppress doctrine injection inside subagents (hook `agent_id`) + audit-side exclusion | Accepted | 2026-07-06 |
| [0021](0021-rationalization-harvest-loop.md) | H1 rationalization harvest loop — capture verbatim false-skip excuses (scrubbed, gitignored) to feed doctrine | Accepted | 2026-07-06 |
| [0022](0022-red-flags-rationalization-table.md) | H2 Red Flags table — rule-6/4 rationalizations as a symptom→refutation table | Accepted | 2026-07-06 |
| [0023](0023-trigger-purity-lint.md) | H4 trigger-purity lint — reject workflow-summary phrases from the MAX-pool triggers (shadow-first) | Accepted | 2026-07-06 |
| [0024](0024-staleness-detector-content-not-mtime.md) | Staleness detector fingerprints content, not mtime — fixes chronic false "disk changed since last index" | Accepted | 2026-07-06 |
| [0025](0025-autonomous-override-freshness-and-keep-on-management.md) | Autonomous `skillOverrides` freshness (SessionStart self-heal + doctor drift detection) + seamless keep-on management | Accepted | 2026-07-06 |
| [0026](0026-llm-utterance-trigger-layer.md) | LLM-utterance trigger layer — offline flywheel-generated natural-utterance phrases (EN+VN) as MAX-pool trigger points, utterances-first, gated `SKILL_LLM_TRIGGERS` | Accepted | 2026-07-08 |

## Status values

`Proposed` → `Accepted` → `Deprecated` / `Superseded` (or `Rejected`).
Accepted ADRs are immutable — supersede with a new one rather than editing.

## See also

- [`../caveats.md`](../caveats.md) — operational landmines (the loud gotchas list).
- [`../plan.md`](../plan.md) — the fusion build plan + dated build log (the journal; ADRs extract the *decisions* from it).
