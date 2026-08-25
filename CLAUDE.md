# CLAUDE.md

Claude Code reads this file automatically. The **canonical** agent-contributor instructions
for this repository live in **[`AGENTS.md`](AGENTS.md)** (open AGENTS.md spec) — read that first.

Claude-specific quick reference:

- **Verify before "done":** run the `skill-concierge:doctor` skill (or `python3 scripts/doctor.py`); a green `status: OK` is the bar.
- **Bootstrap / repair:** the `skill-concierge:setup` skill, or `./setup.sh` (idempotent).
- **Versioning:** bump `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `.codex-plugin/plugin.json`, and root `package.json` together, plus a `CHANGELOG.md` entry.
- **Don't commit tool state:** `.ijfw/`, `ijfw/`, `.handoff/`, `logs/`, and `graphify-out/` are gitignored scratch, not source.
- **Commits are gated on openwiki parity:** a `PreToolUse(Bash)` hook (`scripts/openwiki_parity_guard.py`, wired in `.claude/settings.json`) denies `git commit` when `openwiki/quickstart.md` names a different version than `.claude-plugin/plugin.json`, or when any relative link under `openwiki/` is broken. Fix with `/openwiki:wiki update`; verify with `python3 scripts/driftcheck.py driftcheck.json` (exit 0). Fails open on internal error; `OPENWIKI_GUARD=0` overrides. Full rule: [`AGENTS.md`](AGENTS.md) → *Guardrails*.
- **Graph staleness is a NOTICE, not a gate:** a second `PreToolUse(Bash)` hook (`scripts/graph_staleness_notice.py`) warns on `git commit` when git-tracked files have moved ahead of `graphify-out/manifest.json`. It **never blocks** and never emits `permissionDecision` — `graphify-out/` is gitignored, so a stale graph harms only the local session, and doc refreshes cost LLM calls. Code drift self-heals via graphify's post-commit hook; docs need `/graphify . --update`. Override: `GRAPH_NOTICE=0`. Full rule: [`AGENTS.md`](AGENTS.md) → *Guardrails*.
- **Governance flags (one-var reverts):** `ENFORCER_AUTHORIZED_SKIP` (default ON — enforcer's `SKILL-CHECK:` authorization on its two silent verdict legs — [ADR-0015](docs/adr/0015-authorized-skip-tier-and-library-doctrine.md)), `ENFORCER_CHAIN_HINT` (default ON — `CHAIN-HINT:` candidate line on every inject-bearing leg when the session's last-used skill declares `next-skills:`, ledger tail-read + sidecar, no hot-path network — [ADR-0029](docs/adr/0029-next-skill-chain-hints.md)), `SKILL_BODY_TRIGGERS` (default ON — body-derived MAX-pool trigger points, engine-side — [ADR-0016](docs/adr/0016-body-derived-trigger-points.md)), `SKILL_LLM_TRIGGERS` (default OFF — offline flywheel-generated natural-utterance trigger points, utterances-first, capped at `TRIGGERS_MAX` (live 16); reads `SKILL_TRIGGERS` — [ADR-0026](docs/adr/0026-llm-utterance-trigger-layer.md)), `SKILL_CODEX_ROOTS` (default ON — dual-harness discovery of `~/.codex/**` skills under `codex-*` scopes — [ADR-0033](docs/adr/0033-dual-harness-codex-parity.md)), `ENFORCER_ANNEX_DYNAMIC` (default ON — competitive-margin annex sizing: annex rows must score within `ENFORCER_ANNEX_MARGIN` (0.05) of the top installed row, caps 4 external / 2 foreign — [ADR-0036](docs/adr/0036-dynamic-annex-sizing.md)), and `ENFORCER_CROSS_HARNESS` (default ON — the installed offer holds only skills THIS harness can invoke: `_retrieve` over-fetches and POST-filters by scope **plus a per-session invocable-twin test**, since scope records where a copy lives and not invocability; the rest re-surface as a marked `get_skill` annex from a separate query — [ADR-0034](docs/adr/0034-cross-harness-offer-isolation.md)). Every engine-side flag is forwarded by `auto_reindex.py` to the detached reindex (v0.16.1; `SKILL_CODEX_ROOTS` added v0.25.0) so background rebuilds stay consistent with the live query index — the invariant is completeness of that forward list, not its count.
- **Telemetry is EPOCH-SCOPED (HARD — a prior multi-agent analysis got this fatally wrong):** NEVER cite a ledger rate (fallback / conversion / dodge / hit@k) pooled across config changes. This repo changes what the ledger measures ~daily, so the all-time number describes no real config. Window `analyze.py --since "<last commit to enforcer.py / skill-first.md / server.py / embed_server.py>"`, **exclude subagent + self-session traffic**, and if the current epoch is too small say **"insufficient data"** — do not pool backward. A metric shift not aligned to a config commit is **environmental**, not a design flaw. An epoch-pooled or tiny-sample rate is **UNMEASURED**, never "measured". Full rule + checklist: [`AGENTS.md`](AGENTS.md) → *Guardrails*.

Repo layout, full conventions, and guardrails are all in [`AGENTS.md`](AGENTS.md).

## OpenWiki

This repository has documentation located in the /openwiki directory.

Start here:
- [OpenWiki quickstart](openwiki/quickstart.md)

OpenWiki includes repository overview, architecture notes, workflows, domain concepts, operations, integrations, testing guidance, and source maps.

When working in this repository, read the OpenWiki quickstart first, then follow its links to the relevant architecture, workflow, domain, operation, and testing notes.
