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
| [`docs/anti-dodge-integration-v0.14.md`](docs/anti-dodge-integration-v0.14.md) | the v0.14.0 anti-dodge work: 5 mechanisms, decision arc, accepted caveats |

## Repository layout

The full tree is in the README's *Architecture* section. The parts you will touch most:

- `skills/{skill-search,setup,doctor,skill-usage-audit,keep-on,flywheel}/SKILL.md` — the plugin skills (router + maintenance + usage-audit + keep-on allowlist manager + flywheel utterance coverage/generation, ADR-0027)
- `scripts/` — `doctor.py` (health check), `analyze.py` (ledger; `--since`/`--until` window it by event time for before/after compares — don't split the ledger by hand), `apply-overrides.py` (keep-on writer; `--check`/`--if-changed` drift modes), `keep-on.py` (view/add/remove the always-on allowlist), `embed_server.py` (warm embed sidecar)
- `hooks/` — the in-generation governance layer: `enforcer.py` (per-turn SKILL-FIRST gate: embed→retrieve→floors/intent→ranked mandate, plus the AUTHORIZED-SKIP tier on its two silent legs — ADR-0015), `ledger.py` (invocation capture), `doctrine.py` (SessionStart standing-order injection), `auto_reindex.py` + `auto_overrides.py` (SessionStart self-heal: index + settings-override drift), `doctrine/skill-first.md` (the library doctrine text — burden of proof on SKIP, escalate to `find-skills`)
- `vendor/skill-search/` — vendored MCP engine (MIT · sowhan/skill-search) — **do not diverge silently**; the body-derived trigger points (`_extract_body_triggers`/`_trigger_phrases`, ADR-0016) are a direct engine-code patch, logged in [`VENDORED.md`](vendor/skill-search/VENDORED.md) — re-apply it if the engine is ever re-vendored from upstream
- `.claude-plugin/{plugin,marketplace}.json` — plugin manifests
- `config/keep-on.json` — the shipped SEED for the curated always-on allowlist (runtime copy seeded once into `~/.claude/skill-concierge/keep-on.json`, the canonical durable home; ADR-0025)

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

Each is a one-var revert to the prior behavior (`ENFORCER_AUTHORIZED_SKIP` and `SKILL_BODY_TRIGGERS` default ON; `SKILL_LLM_TRIGGERS` default OFF):

- `ENFORCER_AUTHORIZED_SKIP` (`hooks/scripts/enforcer.py`) — injects a `SKILL-CHECK:` line on the enforcer's two previously-silent verdicts (getaway score-floor miss, conversational-intent skip) so the agent knows the hook already cleared the turn. `=0` restores the old silence. [ADR-0015](docs/adr/0015-authorized-skip-tier-and-library-doctrine.md).
- `SKILL_BODY_TRIGGERS` (`vendor/skill-search/skill_search/server.py`) — folds each skill body's labeled decision-section phrases into the MAX-pool trigger layer alongside the description-derived ones. `=0` + a reindex reverts to description-only. [ADR-0016](docs/adr/0016-body-derived-trigger-points.md).
- `SKILL_LLM_TRIGGERS` (`vendor/skill-search/skill_search/server.py`) — default **OFF**; layers the offline flywheel-generated natural-utterance phrases (`eval/triggers.json` `llm_triggers` block, EN+VN) FIRST in the MAX-pool trigger layer, ahead of description/body, capped COMBINED at `TRIGGERS_MAX` (live deploy uses `16` so utterances add slots rather than evict). Reads `SKILL_TRIGGERS` (path to the gitignored `eval/triggers.json`; absent → no utterances, graceful). `=1` + a reindex enables. [ADR-0026](docs/adr/0026-llm-utterance-trigger-layer.md). **All three engine flags above are forwarded by `auto_reindex._mcp_env()` to the detached SessionStart reindex (v0.16.1)** — without it, a background reindex rebuilt at engine defaults and pruned the utterance points every run.

`skills/skill-usage-audit/scripts/audit_skill_usage.py` recognizes the `SKILL-CHECK:` marker: a
hook-authorized skip is tallied separately as `authorized_skip` and excluded from the false-SKIPPING
count, so the doctrine's hardest-rule metric doesn't get inflated by lawful, hook-cleared skips.

## Guardrails

- The index holds **model-invocable `SKILL.md` skills only** — built-in slash-commands are excluded by design ([ADR-0001](docs/adr/0001-index-model-invocable-skills-only.md)). Don't "fix" their absence.
- The vendored `eval/` recall@k is calibrated to a *different* skill universe; a near-zero score is a wrong-universe artifact, not a weak retriever ([caveats §1](docs/caveats.md)).
- Hooks are **fail-silent and additive-only** — a telemetry failure must never block a turn.
- **Ledger metrics are EPOCH-SCOPED — NEVER pool them across config changes.** This is the load-bearing
  trap: this repo changes the very things the ledger measures (gate floors, retrieval engine, doctrine,
  the embed shim) *almost daily*, so the invocation-ledger is a **sequence of short config epochs, not one
  dataset**. A rate pooled across them describes *no real configuration* and manufactures a false "measured"
  signal. Before citing ANY ledger rate (fallback / conversion / dodge / hit@k):
  1. **Find the current epoch start** — the last commit touching `hooks/scripts/enforcer.py` (thresholds/gates),
     `hooks/doctrine/skill-first.md`, `vendor/skill-search/skill_search/server.py` (retrieval), or
     `scripts/embed_server.py`: `git log --date=format:'%Y-%m-%d %H:%M' --pretty='%cd %h %s' -- <those paths>`.
  2. **Window to it:** `python3 scripts/analyze.py --since "<that datetime>"`. Never quote the all-time number.
  3. **Exclude contamination:** subagent / harness / `<task-notification>` traffic and your *own* meta/self-session
     turns are NOT representative (a heavy multi-agent session alone can swing the fallback rate 30+ points).
  4. **Respect sample size:** a fresh epoch may be too small to conclude — say **"insufficient data"** rather than
     pool backward to inflate n.
  5. **Design vs environment:** a metric shift that does NOT line up with a config commit (e.g. a per-day spike
     *between* releases) is **environmental** (shim/Docker/load), not a property of the code — do not attribute it
     to a design decision.
  This exact mistake — pooling ~15 epochs (v0.2→v0.12) and reading the aggregate as a current-state signal —
  already invalidated a full multi-agent analysis once (see the *Data-validity note* in
  `plans/reports/from-audit-and-openspace-syntheses-…-integrated-final-…-report.md`). Calibrate confidence to
  data-validity: an epoch-pooled or tiny-sample rate is **UNMEASURED**, never "measured".

## OpenWiki

This repository has documentation located in the /openwiki directory.

Start here:
- [OpenWiki quickstart](openwiki/quickstart.md)

OpenWiki includes repository overview, architecture notes, workflows, domain concepts, operations, integrations, testing guidance, and source maps.

When working in this repository, read the OpenWiki quickstart first, then follow its links to the relevant architecture, workflow, domain, operation, and testing notes.
