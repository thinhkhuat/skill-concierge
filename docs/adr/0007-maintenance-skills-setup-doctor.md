# ADR-0007: Maintenance skills (`setup` + `doctor`) — delegate health to the engine, fix only what is safe

**Status:** Accepted
**Date:** 2026-06-26
**Deciders:** owner (thinhkhuat)

## Context

A new user installs the plugin and hits the failure surface the deployment layer creates:
the MCP won't connect (venv missing — ADR-0004), Qdrant isn't up, the index is dark/stale,
or the curated overrides (ADR-0005) never applied. The fixes existed (`setup.sh`, the engine's
`skill-search --health`/`--reindex`, `apply-overrides.py`) but were tribal knowledge scattered
across the README and caveats. First-run friction is the most common reason a self-hosted
plugin gets abandoned, so the bootstrap + healthcheck path needs to be a first-class,
model-invocable surface — not a docs treasure hunt.

## Decision

Ship two model-invocable skills (`skills/{setup,doctor}/SKILL.md`, namespaced
`skill-concierge:setup` / `skill-concierge:doctor`) plus one diagnostic engine,
`scripts/doctor.py`:

- **`setup`** wraps the idempotent `setup.sh` (the single bootstrap source of truth) for
  first-install and post-update refresh, then verifies with doctor. It does **not** duplicate
  any bootstrap logic.
- **`doctor` checks only the deployment layer** it owns — venv, MCP wiring, Qdrant
  reachability, settings overrides, ledger dir — and **delegates the retrieval diagnostic**
  (embedder, indexed vs dark/stale skills, freshness) to the engine's own `skill-search
  --health`. The engine already computes this and is the source of truth; reimplementing it in
  doctor would drift. (Same DRY principle as `apply-overrides.py` reusing the vendored
  `discover_skills`.)
- **`--fix` is bounded to fast, safe, idempotent repairs:** start a stopped Qdrant container
  (with a readiness poll so the follow-on reindex doesn't race a booting server), `--reindex`
  a stale/dark index, re-apply the curated overrides. The **heavy bootstrap** (building the
  venv, creating the container) is deliberately NOT auto-run — that stays in `setup.sh`;
  doctor points the user there.
- `doctor.py` is **pure stdlib, read-only by default** (matching `analyze.py` /
  `apply-overrides.py` house style) and exits non-zero on FAIL (cron/CI usable).

The two `SKILL.md` files declare `name:` matching their directory — the registration pattern
proven by `skill-search` in this deployment (158/159 installed plugin skills use it); the
nameless-fallback path is doc-asserted only, so it was the wrong risk posture for a surface
whose entire job is to resolve. Descriptions are single-line because the vendored engine parses
frontmatter with a regex, not a YAML parser (a `>-` block scalar would leak into the index).

## Consequences

### Positive
- First-run + post-update bootstrap and recovery are one skill invocation each.
- Retrieval-health truth lives in exactly one place (the engine); doctor can't report a
  different answer than the live MCP.
- `--fix`'s safe-only boundary means a user can run it blindly without risking a long,
  surprising rebuild or a half-written state.

### Negative / caveats
- `--fix` mutates `~/.claude/settings.json` (via `apply-overrides.py`, backed up first) and the
  live index (reindex). The user invoking doctor is consent; the doctor `SKILL.md` says so.
- doctor diagnoses but does not bootstrap: a missing venv is a FAIL that routes to `setup`,
  not an auto-repair.

## Related

- ADR-0004 (stable venv — the thing `setup` builds and `doctor` checks).
- ADR-0005 (overrides applier — doctor's `--fix` re-runs it).
- ADR-0001 / `../caveats.md` §1 (the engine `--health` doctor delegates to reports dark/stale
  against the model-invocable-only index).
