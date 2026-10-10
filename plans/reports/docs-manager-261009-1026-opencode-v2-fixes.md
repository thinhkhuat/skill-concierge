# Docs for 0.65.1 (OpenCode v2 live fixes, ADR-0089)

Stateful record, 2026-10-09.

## Files changed

- `README.md`: version badge and "Current release" line to 0.65.1 (`**published**` marker kept); OpenCode row of the skills-roots table now lists `~/.config/opencode/skill-concierge-skills/` and states `codemode: false`, no doctrine/menu/turn row for subagent child sessions, refused calls not logged, menu built at the first model call, `<system-context>` block stripped, link to ADR-0089; uninstall bullet no longer says "re-rooted into `~/.config/opencode/skills/`".
- `openwiki/quickstart.md`: version line to 0.65.1. No other openwiki page mentions OpenCode.
- `docs/repository-layout.md`: the `opencode/` adapter entry now describes the one-entry plugin install, the owned skills folder (`install.sh:72`), `codemode: false` (`plugin/index.ts:103`), subagent scoping, ADR-0089, and names the three new test files. The file lists no per-test inventory, so they sit in that entry rather than in a separate list.
- `docs/runtime-flags.md`: `SKILL_OPENCODE_ROOTS` entry adds the `skill-concierge-skills` root (`skills_discovery.py:150`, enforcer twin root). Table row unchanged.

## Not changed

- `AGENTS.md`: its OpenCode lines state no root or install facts; nothing stale.
- `docs/caveats.md`: no OpenCode mentions.
- ADRs, CHANGELOG, code, tests.

## Not checked

- The OpenCode behaviour claims come from ADR-0089, the CHANGELOG entry and `adapters/opencode/plugin/index.ts` header and lines; I did not run OpenCode or the new tests.

## Final output lines

- `IN SYNC: every fact matches its source of truth.` (driftcheck, exit 0)
- `flag-docs-parity OK: 45 table rows, 43 full entries; 45 table defaults and 40 stated docs defaults match the code` (exit 0)

Remaining grep hits for `opencode/skills` are the legitimate user root (`~/.config/opencode/skills`), not the installer target. Largest edited file: README.md, 538 lines.
