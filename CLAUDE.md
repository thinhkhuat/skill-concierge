# CLAUDE.md

Claude Code reads this file automatically. The **canonical** agent-contributor instructions
for this repository live in **[`AGENTS.md`](AGENTS.md)** (open AGENTS.md spec) — read that first.

Claude-specific quick reference:

- **Verify before "done":** run the `skill-concierge:doctor` skill (or `python3 scripts/doctor.py`); a green `status: OK` is the bar.
- **Bootstrap / repair:** the `skill-concierge:setup` skill, or `./setup.sh` (idempotent).
- **Versioning:** bump `.claude-plugin/plugin.json` **and** `.claude-plugin/marketplace.json` together, plus a `CHANGELOG.md` entry.
- **Don't commit tool state:** `.ijfw/`, `ijfw/`, `.handoff/`, and `logs/` are gitignored scratch, not source.
- **Governance flags (both default ON, one-var revert):** `ENFORCER_AUTHORIZED_SKIP` (enforcer's `SKILL-CHECK:` authorization on its two silent verdict legs — [ADR-0015](docs/adr/0015-authorized-skip-tier-and-library-doctrine.md)) and `SKILL_BODY_TRIGGERS` (body-derived MAX-pool trigger points, engine-side — [ADR-0016](docs/adr/0016-body-derived-trigger-points.md)).
- **Telemetry is EPOCH-SCOPED (HARD — a prior multi-agent analysis got this fatally wrong):** NEVER cite a ledger rate (fallback / conversion / dodge / hit@k) pooled across config changes. This repo changes what the ledger measures ~daily, so the all-time number describes no real config. Window `analyze.py --since "<last commit to enforcer.py / skill-first.md / server.py / embed_server.py>"`, **exclude subagent + self-session traffic**, and if the current epoch is too small say **"insufficient data"** — do not pool backward. A metric shift not aligned to a config commit is **environmental**, not a design flaw. An epoch-pooled or tiny-sample rate is **UNMEASURED**, never "measured". Full rule + checklist: [`AGENTS.md`](AGENTS.md) → *Guardrails*.

Repo layout, full conventions, and guardrails are all in [`AGENTS.md`](AGENTS.md).

## OpenWiki

This repository has documentation located in the /openwiki directory.

Start here:
- [OpenWiki quickstart](openwiki/quickstart.md)

OpenWiki includes repository overview, architecture notes, workflows, domain concepts, operations, integrations, testing guidance, and source maps.

When working in this repository, read the OpenWiki quickstart first, then follow its links to the relevant architecture, workflow, domain, operation, and testing notes.
