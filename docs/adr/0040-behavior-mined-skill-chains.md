# ADR-0040: Behavior-Mined Skill Chains

- **Status**: Accepted
- **Date**: 2026-08-28
- **Plan**: `plans/260828-0004-skill-chain-intelligence/plan.md` (Phase 1 of 4)

## Context

58% of sessions that invoke any skill invoke two or more (ledger, all-time: 110/191;
current epoch 17/34) — real work is chained work (`ak-brainstorm → ak-plan`,
`ak-cook → ak-docs`, `plugin-scaffold → working-with-claude-code`, observed 8-deep).
The ADR-0029 CHAIN-HINT layer exists to surface continuations, but its only knowledge
sources are `next-skills:` frontmatter — which **3 of 757 skills declare (0.4%)** —
and the operator's ADR-0030 override file (~8 entries). Meanwhile the append-only
invocation ledger records ground-truth per-session sequences and nothing reads them
back. The chain layer is data-starved next to the richest signal the system owns.

## Decision

1. **Mine the ledger offline.** `scripts/build_chains.py` turns per-session ordered
   `auto`/`manual` sequences into a successor map `~/.claude/skill-concierge/mined-chains.json`
   (durable home; survives plugin updates). Stdlib-only, deterministic, selftested.
2. **Score by support × lift, not raw counts.** A pair survives at support ≥ 2 AND
   `lift = P(B|A-step) / P(B) ≥ 1.5`. Lift is the load-bearing filter: closure skills
   (`session-handoff`) follow nearly every predecessor, so their baseline P(B) is huge
   and lift ≈ 1 — follows-everything dies as a semantic successor without any
   hand-maintained drop-list. Adjacency is session-bounded (≤ 2 h gap per step),
   subagent lanes are excluded (ADR-0020), names resolve against the reindex sidecar
   so built-in slashes and file-path artifacts never enter.
3. **Merge as the lowest layer.** At the enforcer's read seam (`_visible_sidecar_names`):
   declared sidecar → mined **fills empty entries only** → operator overrides applied
   last (win per-name, `[]` deliberately suppresses). The ordering encodes the trust
   hierarchy: what the operator curated > what an author declared > what was merely
   observed. The sidecar's `[]` is absent authoring (the 99.6% default), not
   suppression — only the override file's `[]` is deliberate (ADR-0030 semantics).
   Keys and successors must be members of the catalogue VISIBLE from the cwd (same
   scope rule as the declared layer).
4. **Same blast radius as ADR-0029.** Mined successors ride the existing
   context-only CHAIN-HINT line — no gate, no floor, no candidate-list entry,
   keep-off still drops successors, one line per turn, TTL-bounded.
   Kill-switch: `ENFORCER_MINED_CHAINS=0`; path override
   `SKILL_CONCIERGE_MINED_CHAINS`. Fail-open on absent/malformed file.

## Consequences

- The chain layer's coverage jumps from 11 names to 23 on day one (3 declared + 8
  curated + mined fills), and **compounds automatically as the ledger grows** — the
  flywheel property the ledger was built for, finally feeding the decision layer.
- Sparse-data honesty: at 623 lifetime invocations the deepest pair support is 4; the
  support floor keeps anecdotes out, accepting a thin map now for a trustworthy one
  later. `--since` gives epoch hygiene (config-era mixing stays out).
- Mined chains carry no authoring trust: a name the operator or an author has spoken
  on is never overwritten by observation.
- Rebuild is manual (`python3 scripts/build_chains.py`) in Phase 1; cadence/automation
  moves to a later phase if the map proves load-bearing (measured via the Phase-4
  chain-continuation metric).
- Non-goals (later phases, designed in the plan): proactive chain projection at offer
  time (L2), multi-intent offer shaping (L3), continuation-rate telemetry (L4).
