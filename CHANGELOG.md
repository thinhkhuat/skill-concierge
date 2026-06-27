# Changelog

All notable changes to **skill-concierge**. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); this project is pre-1.0 and evolving.

## [Unreleased]

## [0.4.2] — 2026-06-27

### Added
- `scripts/analyze.py` — `--since WHEN` / `--until WHEN` flags window the ledger by event
  time (`WHEN` = epoch seconds or local ISO `YYYY-MM-DD[ HH:MM:SS]`), so before/after
  compares (e.g. around a fix or go-live commit time) no longer need hand-splitting the
  ledger. Prints a `window` header; positional-path and no-flag invocations are unchanged;
  stays stdlib-only. Documented in `README.md`, `AGENTS.md`, and the mental-model doc.

### Fixed
- `README.md` ledger example claimed `hit@k` was "pending (needs offer events)" — stale:
  `offer` events land and hit@k computes. Updated the example line and the note.

## [0.2.1] — 2026-06-26

### Changed
- **Enforcer embed timeout 90ms → 200ms, total per-turn budget ≲150ms → ≲300ms**, and the
  embed shim is now **threaded** (`ThreadingHTTPServer`). Live dogfooding (the plugin's own
  ledger) showed ~60% of real turns were hitting `embed_timeout` → mandate-only: the
  single-threaded shim's mpnet inference, under real in-turn CPU contention (concurrent
  UserPromptSubmit hooks + overlapping sessions), slipped past 90ms even though it's ~18ms idle.
  Threading flattens concurrent embeds (8 parallel: 288ms serial → 65ms wall) and the wider
  budget recovers the semantic candidates on the common path; the hook is non-blocking additive
  context so ~250ms worst-case is imperceptible. Both knobs env-overridable
  (`ENFORCER_EMBED_TIMEOUT` float-seconds, `ENFORCER_QDRANT_TIMEOUT`). See ADR-0008.

## [0.2.0] — 2026-06-26

### Added
- **P1 fusion — semantic skill-enforcement (the headline of 0.2.0).** Retires the lexical
  per-turn enforcement hook and points it at the SAME semantic Qdrant index `skill-search` serves:
  - **Warm embed shim** — `scripts/embed_server.py` (stdlib http.server holding fastembed
    mpnet-768 in memory; `POST /embed`, `GET /health`), shipped as a Docker sidecar next to the
    Qdrant container on `127.0.0.1:6363` (`Dockerfile`, `bin/embed-shim`, `setup.sh`). Reuses the
    engine embed path; `vendor/skill-search/pyproject.toml` pins `fastembed==0.8.0` for index
    parity (cosine 1.000000 verified, EN+VN).
  - **Semantic enforcer** — `hooks/scripts/enforcer.py` (UserPromptSubmit): embed → Qdrant top-k →
    inject mandate + semantic candidates; fail-silent, additive-only, never blocks. Hard ~90ms
    client-side embed timeout → mandate-only fallback on embed/Qdrant down or slow (see ADR-0008
    for the 90ms calibration). Replaces the lexical scorer + `library.json`.
  - **Telemetry** — `scripts/analyze.py` catalogue repointed off `library.json` onto the Qdrant
    index; now reports hit@k / fallback rate / bands from new `offer` events.
  - Go-live: lexical `skill_first_nudge.py` deregistered from `~/.claude/settings.json`; this
    plugin version is the live enforcement layer.
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
- The ADR/caveats docs slice documents existing reality; the P1 fusion (above) is the
  behavioural change in 0.2.0 — the enforcement organ moved from the lexical scorer to the
  semantic index. See `docs/plan.md` build log, ADR-0002, and ADR-0008.

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

[Unreleased]: https://github.com/thinhkhuat/skill-concierge/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/thinhkhuat/skill-concierge/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/thinhkhuat/skill-concierge/releases/tag/v0.2.0
[0.1.2]: https://github.com/thinhkhuat/skill-concierge/releases/tag/v0.1.2
[0.1.1]: https://github.com/thinhkhuat/skill-concierge/releases/tag/v0.1.1
[0.1.0]: https://github.com/thinhkhuat/skill-concierge/releases/tag/v0.1.0
