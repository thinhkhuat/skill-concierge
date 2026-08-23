# Plan — external catalog roots (ADR-0031)

Authority: [ADR-0031](../../docs/adr/0031-external-catalog-roots.md) — 11 owner
decisions, 2026-08-23. First target catalog:
`/Users/thinhkhuat/env-DEV/antigravity-awesome-skills/skills` (1,599 skills, 23 name
collisions with `~/.claude/skills`).

Grounding (scout 2026-08-23): roots hardcoded `skills_discovery.py:29-40`; scope filter
`server.py:574-581`; name derivation + first-writer-wins `skills_discovery.py:273-285,401`;
`get_skill` payload-path lookup `server.py:731-750`; staleness signature `server.py:141-158`.

## Phase 1 — Engine: catalog discovery (vendored patch)

- [x] Config loader for `~/.claude/skill-concierge/catalog-roots.json`
      (`{alias: {path, include?, exclude?}}`); env repath `SKILL_CONCIERGE_CATALOG_ROOTS`;
      fail-open on absent/malformed (absent file = byte-identical behavior).
- [x] Extend discovery: catalog roots scanned one level deep like existing roots;
      apply include/exclude globs; skill name minted `<alias>:<dirname>`; scope
      `catalog:<alias>`; wire scopes into `visible_scopes()` (reindex must not prune).
- [x] Promoted-skill dedup: suppress a catalog skill whose resolved realpath equals an
      already-discovered personal skill (symlink promotion produces twins).
- [~] Alias validation: format check (`[a-z0-9][a-z0-9_-]*`) + path-existence at config
      load, warn-and-skip. **Plugin-id collision rejection was NOT built** — softened to
      precedence handling instead (catalogs discovered last, installed name always wins);
      see decisions log D5 for the rationale. Original "fail loudly on plugin-id
      collision" line deliberately dropped.
- [x] VENDORED.md entry; forward any new env through `auto_reindex.py` (ADR-0026 gap
      class); body-derived triggers (ADR-0016) apply to catalog skills as-is; flywheel
      explicitly excluded for `catalog:*` scopes (deferred, not dropped).
- [x] Verify: engine selftests — namespacing, scope assignment, globs, dedup,
      absent-config no-op; reindex with antigravity root → point count + spot queries.

## Phase 2 — Retrieval tiering + results UX

- [x] `search_skills` (server): include `catalog:*` scopes in `_scope_filter()`;
      result rows for catalog hits carry `[external: <alias>]`, absolute path, and the
      read-inline consumption note (`get_skill` pulls the body; Skill tool cannot
      invoke it).
- [x] Enforcer per-turn path: EXCLUDE `catalog:*` from offer retrieval (search-only
      tier). Keep-on/keep-off/floors untouched for installed skills.
- [x] Verify: enforcer `--selftest` new case (catalog point never offered);
      `search_skills("seo audit")` surfaces `antigravity:seo` with marker while the
      per-turn preview does not.

## Phase 3 — Management surface

- [x] `scripts/catalogs.py`: `list` / `add <alias> <path>` / `remove <alias>` /
      `promote <alias>:<name>` (symlink to `~/.claude/skills/<bare-name>`, refuse on
      collision, report broken promoted symlinks) — keep-on script conventions,
      `--selftest`.
- [x] `skills/catalogs/SKILL.md` (skill-concierge:catalogs) fronting the script;
      setup.sh/doctor awareness: doctor checks config parse + root existence + scope
      counts vs config.
- [x] Verify: script selftest; add antigravity root end-to-end; promote one skill,
      confirm dedup (personal wins) after reindex; remove-root prune confirmed.

## Phase 4 — Doctrine + telemetry

- [x] `hooks/doctrine/skill-first.md`: external consumption path — `USING:
      <alias>:<name>` = pull body via `get_skill`, follow inline.
- [x] Ledger: `get_skill` event class (`ledger.py`), logged on every deep pull;
      `analyze.py` classifies external takes by catalog alias prefix (D7); epoch note
      in the CHANGELOG/AGENTS guardrail style — window from ship date, never pool across.
- [x] Verify: `ledger.py --selftest` (added this run — classifies get_skill/auto/
      search/manual); live external-take confirmed via a hook-shaped get_skill feed →
      `analyze.py` reports `external takes: 1`.

## Phase 5 — Ship gate

- [x] Measure `_disk_signature()` latency at ~2k skills: **894ms at 1,975 skills**.
      NOT cached this run — it runs only on the infrequent `search_skills`/`health`
      path, never the per-turn enforcer (which reads Qdrant directly), so it taxes
      no hot path. The in-process "ponytail" cache (`server.py:148`) stays the
      recorded remedy if the count grows enough to slow interactive search.
- [x] Selftests green (discovery 40, full engine 73, enforcer, analyze, catalogs);
      docs sweep (README, CHANGELOG, AGENTS.md, openwiki); version bump
      plugin.json + marketplace.json (0.22.0); driftcheck exit 0. doctor: catalog
      check green, overall **WARN — engine build-drift only** (live MCP servers on
      pre-deploy build; clears on Claude Code restart, D9). Commit + push below.
- [x] Record Evidence section of ADR-0031.

## Non-goals (v1, by owner decision)

Git-remote/marketplace catalog sources; per-project catalog visibility; flywheel
utterances for externals (deferred phase); preview-tier eligibility for externals;
injection scanners / first-use confirm gates.

## Unresolved questions

- Whether `external-take` should also count promoted-then-invoked skills (currently:
  no — promotion makes them ordinary installed skills; the ledger's existing events
  cover them).
- Flywheel-for-externals phase trigger: owner call, contingent on external-take
  adoption data.
