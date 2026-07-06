# Autonomous skillOverrides freshness + seamless keep-on management

**Date:** 2026-07-06 · **Target version:** 0.15.0 (MINOR, additive) · **Owner:** lead

## Goal (two user asks)

1. **Autonomous freshness** — keep `~/.claude/settings.json` `skillOverrides` always in sync
   with the installed skill catalogue, the same self-healing way the index already refreshes.
   Kills the recurring "name-only leak" (new skills inject full descriptions until someone
   remembers to re-run apply-overrides — the 42-skill leak found in the 2026-07-06 audit).
2. **Seamless keep-on management** — an easy way to view + add + remove the always-ON list.

## Root cause being closed

- The index self-heals (`hooks/scripts/auto_reindex.py`, ADR-0014) but `skillOverrides`
  never did — it was a one-shot snapshot written at setup. New/removed skills drifted silently.
- `doctor check_overrides()` only checked existence + counts, never **drift** — so the leak
  was invisible in the normal health workflow.
- `config/keep-on.json` was hand-edit-only; no track/add/remove surface.

## Design — reuse existing seams, mirror existing patterns

### A. Autonomous override freshness
- **`scripts/apply-overrides.py`** gains two modes (shared compute-diff core, all existing
  safety preserved — backup, atomic write, refuse-empty):
  - `--check` — report drift, exit 1 if drifted, **never writes** (doctor's read-only detector).
  - `--if-changed` — reconcile **only** when drifted (no backup churn on no-op sessions) —
    what the hook runs.
- **`hooks/scripts/auto_overrides.py`** — NEW SessionStart hook mirroring `auto_reindex.py`:
  fail-silent, throttled (own stamp, `AUTO_OVERRIDES_THROTTLE_S`=1800), detached, spawns
  `apply-overrides.py --if-changed` via the venv python. No Qdrant check needed — skill
  discovery is offline SKILL.md parsing.
- **`hooks/hooks.json`** — wire `auto_overrides.py` into SessionStart (beside doctrine + auto_reindex).
- **`scripts/doctor.py` `check_overrides()`** — shell `apply-overrides.py --check`; WARN on
  drift (`fix="overrides"` already re-applies). Closes the blind spot.

### B. Seamless keep-on management
- **`scripts/keep-on.py`** — CLI: `list` (view; marks present/absent on this machine),
  `add <name>…`, `remove <name>…`. add/remove edit `keep-on.json` (dedup, sorted) then
  auto re-apply overrides so the change lands immediately.
- **`skills/keep-on/SKILL.md`** — NEW thin skill so it's conversational ("add X to always-on")
  — the "seamless" surface the user asked for.

## Decisions (defaults chosen; reversible, deploy-gated)

- **Silent** reconcile (mirror auto_reindex; doctor + logfile give visibility) — not a per-session notice.
- **SessionStart-only** trigger (KISS; a new install is caught next session) — no PostToolUse watcher.
- **keep-on skill wrapper: yes** — the explicit "seamless" ask; a bare CLI isn't seamless.

## Non-goals (YAGNI)

- No live file-watcher / daemon. SessionStart + throttle is enough (matches auto_reindex).
- No GUI. CLI + skill.
- No search-to-add. `list` then add-by-name.

## Deploy / versioning

- Additive → **MINOR: 0.14.1 → 0.15.0**. Bump `plugin.json` + `marketplace.json` +
  `CHANGELOG.md` + `README.md` (badge + status) + `openwiki` version refs + new SKILL.md version.
- **ADR-0025** documents the autonomous override-reconcile + keep-on management.
- `driftcheck.py` version-triple must pass.
- Does NOT touch retrieval scoring / gate thresholds → does **NOT** reset the H1 epoch anchor
  (same reasoning as 0.14.1's server.py staleness-only change).

## Phases

1. `apply-overrides.py` `--check`/`--if-changed` + test.        ← building now
2. `auto_overrides.py` hook + `hooks.json` wiring.
3. `doctor.py check_overrides()` drift detection.
4. `keep-on.py` CLI + test.
5. `keep-on` SKILL.md.
6. ADR-0025 + version bump + CHANGELOG/README/openwiki + driftcheck.
7. Verify: vendor + repo tests green, `doctor` OK, driftcheck in sync.

## Test plan

- **apply-overrides:** identical map → no drift (exit 0, no write); added / removed / flipped →
  drift (exit 1 on `--check`; writes on `--if-changed`). Uses existing env seams
  (`SKILL_CONCIERGE_SKILLS_FILE` / `SETTINGS` / `KEEPON`).
- **keep-on:** `add` dedups + sorts + reapplies; `remove`; `list`.
- **doctor:** `check_overrides()` WARN on drift.
