# Changelog

All notable changes to **skill-concierge**. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); this project is pre-1.0 and evolving.

## [Unreleased]

## [0.2.0] — 2026-06-26

### Added
- **Maintenance skills** — `skill-concierge:setup` and `skill-concierge:doctor`:
  - `setup` — wraps the idempotent `setup.sh` bootstrap (stable venv, Qdrant, index,
    overrides) for first-time install and post-update refresh, then verifies with doctor.
  - `doctor` — `scripts/doctor.py`, a pure-stdlib deployment-layer health check with safe
    `--fix` (start Qdrant, reindex, re-apply overrides). Delegates the retrieval diagnostic
    to the engine's own `skill-search --health` so the two never drift.
- `scripts/doctor.py` — the diagnostic engine behind the doctor skill (has a `--selftest`).
- `docs/adr/` — Architecture Decision Records (0001–0006) capturing the design rationale:
  model-invocable-only indexing, the WHICH×WHETHER fusion, embedder/Qdrant choice, the MCP
  launcher + stable venv, the overrides applier, and the compounding ledger.
- `docs/caveats.md` — operational landmines (wrong-universe eval, override-generator nuke,
  Qdrant dependency, python-picker, namespacing, reindex, version sync, logman retention).
- `vendor/skill-search/eval/README-LOCAL.md` — loud note that the vendored eval is calibrated
  to the upstream author's environment and its recall@k is not a quality bar here.
- `CHANGELOG.md`.

### Notes
- Both maintenance skills declare `name:` (matching the directory) so Claude Code registers
  them as `skill-concierge:setup` / `skill-concierge:doctor` — the registration pattern proven
  by the existing `skill-search` skill in this deployment (158/159 installed plugin skills use
  it). Descriptions are single-line because the vendored engine parses frontmatter with a regex,
  not a YAML parser, so a `>-` block scalar would leak into the indexed text.
- The docs slice (ADRs, caveats) documents an existing reality; no behavioural code change.
  The fusion (P1) remains unbuilt — see `docs/plan.md` and ADR-0002.

## [0.1.2] — 2026-06-26

### Fixed
- Keep the bundled router skill `skill-concierge:skill-search` always-on: added it to
  `config/keep-on.json` (32-skill keep-on policy). Without it a cache `setup.sh` rerun could
  revert the router to `name-only`.

## [0.1.1] — 2026-06-26

### Fixed
- Bundled MCP failed to connect (`-32000` / ENOENT). `.mcp.json` had pointed at a venv inside
  the plugin **cache** (wiped on every reinstall). Now `.mcp.json` points at a launcher
  (`bin/skill-search-mcp`) that execs a **stable** venv at `~/.local/share/skill-concierge/venv`,
  surviving plugin cache wipes. (See ADR-0004.)

## [0.1.0] — 2026-06-26

### Added
- Initial scaffold: plugin manifests, README, `.gitignore`.
- Vendored skill-search MCP engine (MIT · sowhan/skill-search) under `vendor/skill-search/`
  with `LICENSE` + `VENDORED.md` attribution and customization log.
- Router skill `skills/skill-search/SKILL.md`.
- Telemetry ledger: `hooks/scripts/ledger.py` + `scripts/analyze.py` (reviewed + tested).
- Reproduction layer: `.mcp.json`, `setup.sh`, `scripts/apply-overrides.py`,
  `config/keep-on.json`.
- Build plan + ops docs under `docs/`.

[Unreleased]: https://github.com/thinhkhuat/skill-concierge/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/thinhkhuat/skill-concierge/releases/tag/v0.2.0
[0.1.2]: https://github.com/thinhkhuat/skill-concierge/releases/tag/v0.1.2
[0.1.1]: https://github.com/thinhkhuat/skill-concierge/releases/tag/v0.1.1
[0.1.0]: https://github.com/thinhkhuat/skill-concierge/releases/tag/v0.1.0
