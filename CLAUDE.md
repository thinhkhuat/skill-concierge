# CLAUDE.md

Claude Code reads this file automatically. The **canonical** agent-contributor instructions
for this repository live in **[`AGENTS.md`](AGENTS.md)** (open AGENTS.md spec) — read that first.

Claude-specific quick reference:

- **Verify before "done":** run the `skill-concierge:doctor` skill (or `python3 scripts/doctor.py`); a green `status: OK` is the bar.
- **Bootstrap / repair:** the `skill-concierge:setup` skill, or `./setup.sh` (idempotent).
- **Versioning:** bump `.claude-plugin/plugin.json` **and** `marketplace.json` together, plus a `CHANGELOG.md` entry.
- **Don't commit tool state:** `.ijfw/`, `.handoff/`, and `logs/` are gitignored scratch, not source.

Repo layout, full conventions, and guardrails are all in [`AGENTS.md`](AGENTS.md).
