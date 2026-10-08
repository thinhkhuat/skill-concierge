## Repository layout

The full tree is in the README's *Architecture* section. One line per area here; the per-file detail (every script, hook, and adapter's behavior and its ADR) is in [`docs/repository-layout.md`](docs/repository-layout.md). Read that file before you edit a hook, a script, or an adapter.

- `skills/{skill-search,setup,doctor,skill-usage-audit,keep-on,blocklist,reputation,flywheel,catalogs,consult}/SKILL.md` — the plugin skills.
- `scripts/` — maintenance CLIs: `doctor.py` (health), `analyze.py` (ledger; window with `--since`/`--until`, never split the ledger by hand), the list managers (`keep-on.py`, `blocklist.py`, `reputation.py`, `catalogs.py`), the Jev tools, and `engine_env.py` (the one `ENGINE_ENV_KEYS` list, see *Runtime flags*).
- `hooks/` — the in-generation governance layer: `enforcer.py` (the per-turn SKILL-FIRST gate), `skill_guard.py` (blocklist deny), `skill_exclusions.py` ("not for" echo), `ledger.py` (invocation capture), `doctrine.py` + `doctrine/skill-first.md` (the standing order), and the SessionStart self-heal hooks.
- `vendor/skill-search/` — vendored MCP engine (MIT · sowhan/skill-search). **Do not diverge silently**: record every patch in [`VENDORED.md`](vendor/skill-search/VENDORED.md).
- `adapters/` — one module per harness: `codex/`, `claude-code/`, `commandcode/`, `omp/`, `zcode/`, `dsh/`, `cline/`. The `codex/` and `claude-code/` installers refuse to downgrade a newer cache; ZCode needs no adapter vehicle (its `install.sh` only verifies and repairs).
- Manifests: `.claude-plugin/{plugin,marketplace}.json`, `.codex-plugin/plugin.json` + `.codex/hooks.json`, and root `package.json` (carries the OMP extension hook `omp.extensions`).
- `config/keep-on.json` — the shipped seed for the always-on allowlist; the runtime copy lives in `~/.claude/skill-concierge/keep-on.json` (ADR-0025).
