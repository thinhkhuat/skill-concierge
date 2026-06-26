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

- `skills/{skill-search,setup,doctor}/SKILL.md` — the three plugin skills (router + maintenance)
- `scripts/` — `doctor.py` (health check), `analyze.py` (ledger), `apply-overrides.py` (keep-on writer), `embed_server.py` (warm embed sidecar)
- `hooks/` — ledger capture (`hooks.json` + scripts) and enforcement doctrine
- `vendor/skill-search/` — vendored MCP engine (MIT · sowhan/skill-search) — **do not diverge silently**
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

## Conventions

- **Python:** 3.10–3.12, `snake_case`. `analyze.py` and `doctor.py` are **stdlib-only** — keep them dependency-free.
- **Shell:** `setup.sh` and the `bin/` launchers target POSIX `sh`/`bash`; keep them portable and idempotent.
- **Versioning:** bump **both** `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` together, plus a `CHANGELOG.md` entry. Never bump one alone.
- **ADRs are immutable.** Don't edit an accepted ADR — supersede it with a new one.
- **Vendored engine:** never patch `vendor/skill-search/` to diverge from upstream silently; record any customization in [`vendor/skill-search/VENDORED.md`](vendor/skill-search/VENDORED.md).
- **Tool state is not source.** `.ijfw/`, `ijfw/`, `.handoff/`, and `logs/` are session/runtime scratch — gitignored, never committed.

## Guardrails

- The index holds **model-invocable `SKILL.md` skills only** — built-in slash-commands are excluded by design ([ADR-0001](docs/adr/0001-index-model-invocable-skills-only.md)). Don't "fix" their absence.
- The vendored `eval/` recall@k is calibrated to a *different* skill universe; a near-zero score is a wrong-universe artifact, not a weak retriever ([caveats §1](docs/caveats.md)).
- Hooks are **fail-silent and additive-only** — a telemetry failure must never block a turn.
