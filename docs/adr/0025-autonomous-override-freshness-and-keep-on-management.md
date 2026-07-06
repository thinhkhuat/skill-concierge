# ADR-0025 — Autonomous `skillOverrides` freshness + seamless keep-on management

- **Status:** Accepted
- **Date:** 2026-07-06
- **Related:** [ADR-0005](0005-overrides-target-and-applier.md) (the applier),
  [ADR-0014](0014-sessionstart-index-self-heal.md) (the index self-heal this mirrors),
  [ADR-0013](0013-doctor-engine-freshness-check.md) / [ADR-0018](0018-self-healing-launcher-engine-resync.md)
  (sibling freshness guards); **supersedes the storage paths of**
  [ADR-0004](0004-bundled-mcp-launcher-stable-venv.md) (venv) and
  [ADR-0006](0006-compounding-invocation-ledger.md) (ledger)

## Context

The retrieval **index** self-heals on session start (ADR-0014, `auto_reindex.py`), but the
`~/.claude/settings.json` `skillOverrides` **budget** did not — it was a one-shot snapshot
written at setup (ADR-0005). When skills are installed or removed, or `config/keep-on.json` is
edited, the override map drifts silently: a newly installed skill has no override entry, so
Claude Code injects its **full description on every turn** ("name-only leak") until a human
remembers to re-run `apply-overrides.py`. The 2026-07-06 name-only audit found **42 skills
leaking + 11 dead override keys** accumulated exactly this way.

Two blind spots let it accumulate unseen:

1. **No autonomous reconcile** — every other freshness concern self-healed; overrides didn't.
2. **`doctor` couldn't see it** — `check_overrides()` only checked that `skillOverrides` *existed*
   and counted on/name-only; it never compared against the installed catalogue, so the leak never
   surfaced in the health workflow.

Separately, the always-ON allowlist (`config/keep-on.json`) was **hand-edit-only** — no surface
to view, add, or remove entries.

## Decision

1. **Autonomous override self-heal.** New SessionStart hook `hooks/scripts/auto_overrides.py`,
   mirroring `auto_reindex.py`'s contract exactly — fail-silent, throttled
   (`AUTO_OVERRIDES_THROTTLE_S`, default 1800s, own stamp), detached, silent/additive. It spawns
   `apply-overrides.py --if-changed`. Skill discovery is offline SKILL.md parsing, so (unlike the
   index heal) it needs no Qdrant reachability gate — only the engine venv python.

2. **`apply-overrides.py` gains two drift-aware modes** over a shared compute-diff core, with all
   existing safety preserved (backup, atomic write, refuse-empty):
   - `--check` — report drift (added / stale / flipped), exit 1 if drifted, **never write**. The
     read-only detector `doctor` calls.
   - `--if-changed` — reconcile **only** when drifted, so a no-op session never rewrites settings
     or churns a backup. The hook path.

3. **`doctor check_overrides()` detects drift.** It now runs `apply-overrides.py --check` and
   reports `WARN` (already auto-fixable via the existing `overrides` fixer) when the override map
   has drifted from the installed catalogue — keying off the `drift:` stdout marker so an applier
   error can't masquerade as drift. Closes blind spot #2.

4. **Seamless keep-on management.** `scripts/keep-on.py` (`list` / `add <name>…` / `remove
   <name>…`) edits the user's allowlist (deduped, sorted) and re-applies the overrides
   immediately; the `keep-on` skill is the conversational wrapper.

5. **One canonical durable home — `~/.claude/skill-concierge/` (`SKILL_CONCIERGE_HOME`).**
   Everything skill-concierge must persist across a `/plugin update` lives under a single
   user-owned directory, resolved in one place (`scripts/_keepon.py`): the keep-on allowlist
   (`keep-on.json`, seeded once from the shipped `config/keep-on.json`), the engine venv
   (`venv/`, was `~/.local/share/skill-concierge/venv` — ADR-0004), and the ledger + logs +
   throttle stamps (`logs/`, was `~/.claude/skill-telemetry/logs` — ADR-0006). This **supersedes
   the storage locations** in ADR-0004 / ADR-0006 / ADR-0013 / ADR-0018 — the launcher-resync and
   freshness logic is unchanged, only the paths move. `setup.sh` runs a one-time migration: it
   copies the old ledger into the new home and rebuilds the venv at the new path (a venv can't be
   relocated — absolute paths bake in), so the update carrying this change needs a single `setup`
   run, after which the self-heal works normally at the new home. The Qdrant vector-store volume
   (`~/.cache/skill-search/`) is deliberately **excluded** — it is regenerable index data
   (`reindex` rebuilds it from the skill files), not durable user/config state, so it stays in
   the XDG cache dir where regenerable data belongs.

## Consequences

- The name-only budget stays fresh with **zero human discipline** — the recurring leak cannot
  silently recur; it heals on the next session and is visible in `doctor` meanwhile.
- The always-ON allowlist is curatable in one command (or one sentence, via the skill).
- **Cost:** one detached, throttled `apply-overrides` spawn per session; offline discovery only.
- **No retrieval-scoring or gate-threshold change** → this does **not** reset the anti-dodge epoch
  anchor (same reasoning as 0.14.1's staleness-only `server.py` change).
- **Non-goals (YAGNI):** no live file-watcher/daemon (SessionStart + throttle suffices); no GUI;
  no search-to-add — `list` then add by exact catalogue-namespaced name.
