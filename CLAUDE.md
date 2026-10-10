# CLAUDE.md

Claude Code reads this file automatically. The **canonical** agent-contributor instructions
for this repository live in **[`AGENTS.md`](AGENTS.md)** (open AGENTS.md spec) — read that first.

Claude-specific quick reference:

- **Verify before "done":** run the `skill-concierge:doctor` skill (or `python3 scripts/doctor.py`); a green `status: OK` is a precondition. The proof that a harness works is `python3 scripts/smoke.py` (one live headless turn per harness; PASS needs an offer row and a search row; ADR-0090).
- **Release order:** bump versions → `python3 scripts/driftcheck.py driftcheck.json` → commit → `adapters/install-all.sh` (installs the local commit, then runs the smoke) → push only when green. Changing a hook in `hooks/hooks.json` fails `tests/test_hook_definitions_pinned.py` until a CHANGELOG line tells Codex users to trust the hooks again ([caveats §27](docs/caveats.md)).
- **Bootstrap / repair:** the `skill-concierge:setup` skill, or `./setup.sh` (idempotent; no Docker — starts the local index owner, ADR-0070).
- **Versioning:** bump `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `.codex-plugin/plugin.json`, root `package.json` and `adapters/opencode/plugin/package.json` together, plus a `CHANGELOG.md` entry. After the push, run `adapters/install-all.sh`: it runs every harness installer, then doctor.
- **Don't commit tool state:** `.ijfw/`, `ijfw/`, `.handoff/`, `logs/`, and `graphify-out/` are gitignored scratch, not source.
- **Commits are gated on openwiki parity:** a `PreToolUse(Bash)` hook (`scripts/openwiki_parity_guard.py`, wired in `.claude/settings.json`) denies `git commit` when `openwiki/quickstart.md` names a different version than `.claude-plugin/plugin.json`, or when any relative link under `openwiki/` is broken. Fix with `/openwiki:wiki update`; verify with `python3 scripts/driftcheck.py driftcheck.json` (exit 0). Fails open on internal error; `OPENWIKI_GUARD=0` overrides. Full rule: [`AGENTS.md`](AGENTS.md) → *Guardrails*.
- **Graph staleness is a NOTICE, not a gate:** a second `PreToolUse(Bash)` hook (`scripts/graph_staleness_notice.py`) warns on `git commit` when git-tracked files have moved ahead of `graphify-out/manifest.json`. It **never blocks** and never emits `permissionDecision` — `graphify-out/` is gitignored, so a stale graph harms only the local session, and doc refreshes cost LLM calls. Code drift self-heals via graphify's post-commit hook; docs need `/graphify . --update`. Override: `GRAPH_NOTICE=0`. Full rule: [`AGENTS.md`](AGENTS.md) → *Guardrails*.
- **Governance flags (one-var reverts):** every flag, with its default, code and ADR, is indexed in [`AGENTS.md`](AGENTS.md) → *Runtime flags* (one-line table plus the `ENGINE_ENV_KEYS` invariant); each flag's full text, tuning knobs and preconditions are in [`docs/runtime-flags.md`](docs/runtime-flags.md). On this machine's Claude Code, `ENFORCER_MULTI_INTENT=0` is set in `~/.claude/settings.json` env as a trial ([ADR-0055](docs/adr/0055-multi-intent-off-projection-pending.md)).
- **Telemetry is EPOCH-SCOPED (HARD — a prior multi-agent analysis got this fatally wrong):** NEVER cite a ledger rate (fallback / conversion / dodge / hit@k) pooled across config changes. This repo changes what the ledger measures ~daily, so the all-time number describes no real config. A ledger event `{"ev": "corpus_epoch"}` (written by `scripts/trigger_filter.py backfill` and `reindex`) also starts an epoch for retrieval metrics — the trigger corpus changed without a code commit. Window `analyze.py --since "<last commit to enforcer.py / skill-first.md / server.py / index_owner.py>"` (the local index owner, ADR-0070; the old `embed_server.py` shim is retired, archived in v0.64.1), **exclude subagent + self-session traffic**, and if the current epoch is too small say **"insufficient data"** — do not pool backward. A metric shift not aligned to a config commit is **environmental**, not a design flaw. An epoch-pooled or tiny-sample rate is **UNMEASURED**, never "measured". Full rule + checklist: [`AGENTS.md`](AGENTS.md) → *Guardrails*. Standing per-epoch watch items (what to monitor, triggers, actions): [`docs/epoch-watch.md`](docs/epoch-watch.md) — the single canonical reference.

Repo layout, full conventions, and guardrails are all in [`AGENTS.md`](AGENTS.md); per-file layout detail is in [`docs/repository-layout.md`](docs/repository-layout.md).

## OpenWiki

This repository has documentation located in the /openwiki directory.

Start here:
- [OpenWiki quickstart](openwiki/quickstart.md)

OpenWiki includes repository overview, architecture notes, workflows, domain concepts, operations, integrations, testing guidance, and source maps.

When working in this repository, read the OpenWiki quickstart first, then follow its links to the relevant architecture, workflow, domain, operation, and testing notes.
