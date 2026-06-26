# ADR-0006: Compounding, never-rotated invocation ledger (logman `RETENTION_DAYS=0`)

**Status:** Accepted
**Date:** 2026-06-26
**Deciders:** owner (thinhkhuat)

## Context

The always-on curation (ADR-0005) was hand-picked by judgment. To make it **data-backed** —
and to prove the fusion (ADR-0002) actually raised skill uptake — the system needs to record
what skills actually get used, by whom (the model autonomously vs the owner by hand), over
time. This data is only valuable if it **accumulates**; a rotated/capped log destroys the
long-horizon signal that drives "promote to always-on / demote to name-only".

## Decision

A lightweight, append-only **skill-invocation ledger** — `hooks/scripts/ledger.py`, stdlib
only, fail-silent, additive-only (never writes hook-decision output):

- `UserPromptSubmit` → logs `turn` per substantive prompt, or `manual` when the owner typed
  a `/skill` (captured **before** the early-return on `/`).
- `PostToolUse` (matcher `Skill|mcp__skill-search__search_skills`) → logs `auto` (model fired
  a skill) / `search` (model queried the index).
- **Tagging keeps the metric honest:** `auto` = the doorman worked; `manual` = the owner
  drove it. `manual` must never inflate the hook-effectiveness number.

`scripts/analyze.py` computes uptake / dodge / search-rate + per-skill rollups (and `hit@k`
once the enforcer emits `offer` events), splitting `manual` into real-skill vs built-in via
the **live catalogue** (not a log-time denylist).

**Storage = compounding, never discarded.** ONE append-only
`~/.claude/skill-telemetry/logs/skill-invocation-ledger.log` (JSONL content). **No
self-rotation, no cap, no deletion** in this code.

## Consequences

### Positive
- Always-on membership recomputes from evidence on a cadence, not a one-off guess.
- The fusion's lift (uptake↑ / dodge↓) is measured before/after, not asserted.

### Negative / caveats (LOUD)
- **Downstream archival = logman (github.com/thinhkhuat/logman).** logman auto-detects
  `logs/*.log` — but its **default `RETENTION_DAYS=90` DELETES old archives.** For this
  ledger logman MUST run **`RETENTION_DAYS=0`** (unlimited), or the compounding data is lost
  after 90 days. The `.log` / `logs/` shape is deliberately logman-drop-in; the wiring is a
  later step. (`../caveats.md` §8.)
- The file is `.log` (JSONL content), matching both `ledger.py` and `analyze.py` (path
  `SKILL_CONCIERGE_LOG` env or the default above) — don't expect a `.jsonl` extension.
- Prompts are truncated to ≤120 chars (not hashed) for context.

## Related

- ADR-0002 (the ledger decides whether the fusion worked; gates the P2 classifier).
- ADR-0005 (ledger evidence drives the keep-on curation).
- `../plan.md` §"What the ledger decides".
