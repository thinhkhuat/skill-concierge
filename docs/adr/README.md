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
| [0008](0008-warm-embed-shim-timeout-calibration.md) | Warm embed shim Docker sidecar + 90ms timeout calibration (client-side hard gate) | Accepted | 2026-06-26 |

## Status values

`Proposed` → `Accepted` → `Deprecated` / `Superseded` (or `Rejected`).
Accepted ADRs are immutable — supersede with a new one rather than editing.

## See also

- [`../caveats.md`](../caveats.md) — operational landmines (the loud gotchas list).
- [`../plan.md`](../plan.md) — the fusion build plan + dated build log (the journal; ADRs extract the *decisions* from it).
