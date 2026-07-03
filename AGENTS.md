# AGENTS.md

Agent-contributor instructions for **skill-concierge** — a skill-governance layer for
Claude Code: semantic retrieval (*which* skill) + use-enforcement (*whether* a skill is
used at all) + a compounding invocation ledger (*what* actually got used).

This file follows the open [AGENTS.md](https://agents.md/) convention and is the **canonical**
agent-instruction surface; platform adapters (e.g. [`CLAUDE.md`](CLAUDE.md)) point here. For
the full product overview see [`README.md`](README.md); for the *why* behind each decision see
[`docs/adr/`](docs/adr/README.md).

## Orientation — read before changing anything

| Source | For |
|--------|-----|
| [`README.md`](README.md) | what the plugin is, install/setup, usage, architecture |
| [`docs/adr/`](docs/adr/README.md) | accepted design decisions + rationale (immutable) |
| [`docs/caveats.md`](docs/caveats.md) | operational landmines — read before judging the engine |
| [`docs/plan.md`](docs/plan.md) | fusion build plan + dated build log |

## Repository layout

The full tree is in the README's *Architecture* section. The parts you will touch most:

- `skills/{skill-search,setup,doctor,skill-usage-audit}/SKILL.md` — the four plugin skills (router + maintenance + usage-audit)
- `scripts/` — `doctor.py` (health check), `analyze.py` (ledger; `--since`/`--until` window it by event time for before/after compares — don't split the ledger by hand), `apply-overrides.py` (keep-on writer), `embed_server.py` (warm embed sidecar)
- `hooks/` — the in-generation governance layer: `enforcer.py` (per-turn SKILL-FIRST gate: embed→retrieve→floors/intent→ranked mandate, plus the AUTHORIZED-SKIP tier on its two silent legs — ADR-0015), `ledger.py` (invocation capture), `doctrine.py` (SessionStart standing-order injection), `doctrine/skill-first.md` (the library doctrine text — burden of proof on SKIP, escalate to `find-skills`)
- `vendor/skill-search/` — vendored MCP engine (MIT · sowhan/skill-search) — **do not diverge silently**; the body-derived trigger points (`_extract_body_triggers`/`_trigger_phrases`, ADR-0016) are a direct engine-code patch, logged in [`VENDORED.md`](vendor/skill-search/VENDORED.md) — re-apply it if the engine is ever re-vendored from upstream
- `.claude-plugin/{plugin,marketplace}.json` — plugin manifests
- `config/keep-on.json` — curated always-on allowlist

## Setup & verification

```bash
./setup.sh                  # idempotent: venv + Qdrant + reindex + apply-overrides
python3 scripts/doctor.py   # read-only health check (add --fix for safe repairs)
```

Run `doctor.py` (or the `skill-concierge:doctor` skill) before **and** after any change that
touches the engine, MCP wiring, or overrides. A green `status: OK` is the bar — claim "done"
only with that proof in hand.

**Doc/version drift guard:** `python3 scripts/driftcheck.py driftcheck.json` (exit 0 = synced). It
checks the version triple (`plugin.json` ↔ `marketplace.json` ↔ latest `CHANGELOG.md` heading), that
every doc-referenced path exists, and that this file and `CLAUDE.md` name the same scratch dirs. Run it
after a version bump or after editing a fact shared between these docs.

## Conventions

- **Python:** 3.10–3.12, `snake_case`. `analyze.py` and `doctor.py` are **stdlib-only** — keep them dependency-free.
- **Shell:** `setup.sh` and the `bin/` launchers target POSIX `sh`/`bash`; keep them portable and idempotent.
- **Versioning:** bump **both** `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` together, plus a `CHANGELOG.md` entry. Never bump one alone.
- **ADRs are immutable.** Don't edit an accepted ADR — supersede it with a new one.
- **Vendored engine:** never patch `vendor/skill-search/` to diverge from upstream silently; record any customization in [`vendor/skill-search/VENDORED.md`](vendor/skill-search/VENDORED.md).
- **Tool state is not source.** `.ijfw/`, `ijfw/`, `.handoff/`, and `logs/` are session/runtime scratch — gitignored, never committed.

## Runtime flags

Both **default ON**; each is a one-var revert to the prior behavior:

- `ENFORCER_AUTHORIZED_SKIP` (`hooks/scripts/enforcer.py`) — injects a `SKILL-CHECK:` line on the enforcer's two previously-silent verdicts (getaway score-floor miss, conversational-intent skip) so the agent knows the hook already cleared the turn. `=0` restores the old silence. [ADR-0015](docs/adr/0015-authorized-skip-tier-and-library-doctrine.md).
- `SKILL_BODY_TRIGGERS` (`vendor/skill-search/skill_search/server.py`) — folds each skill body's labeled decision-section phrases into the MAX-pool trigger layer alongside the description-derived ones. `=0` + a reindex reverts to description-only. [ADR-0016](docs/adr/0016-body-derived-trigger-points.md).

`skills/skill-usage-audit/scripts/audit_skill_usage.py` recognizes the `SKILL-CHECK:` marker: a
hook-authorized skip is tallied separately as `authorized_skip` and excluded from the false-SKIPPING
count, so the doctrine's hardest-rule metric doesn't get inflated by lawful, hook-cleared skips.

## Guardrails

- The index holds **model-invocable `SKILL.md` skills only** — built-in slash-commands are excluded by design ([ADR-0001](docs/adr/0001-index-model-invocable-skills-only.md)). Don't "fix" their absence.
- The vendored `eval/` recall@k is calibrated to a *different* skill universe; a near-zero score is a wrong-universe artifact, not a weak retriever ([caveats §1](docs/caveats.md)).
- Hooks are **fail-silent and additive-only** — a telemetry failure must never block a turn.
