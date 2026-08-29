# consult-mode build plan — ADR-0049

Accepted design: [`docs/ideas/consult-mode.md`](../../docs/ideas/consult-mode.md) (four
locked decisions + practice-run findings). GO given 2026-08-29 ~22:40.

## Goal

Ship the deliberation layer: `skill-concierge:consult` — an opt-in, reasoning-driven
skill-chain curation (sieve → deep-read analyst → composed verdict), with a capsule
dossier corpus, a wide-recall sieve verb, and consult verdict telemetry. Phase 2
(enforcer consult-intent routing) lands after the core is verified green.

## File map

New:
- `scripts/llm_capsules.py` — capsule generator (mirrors `llm_triggers.py`: shared
  `flywheel_llm` client, shared cache with `capsules:v1:` prefix, body+description
  fingerprint, ThreadPool single-writer pattern, `--selftest` network-free).
- `skills/consult/SKILL.md` — the funnel skill (sieve → admit misses → analyst
  delegation → compose → RUN/⚠/ALSO card → verdict log → route by flag).
- `skills/consult/agents/analyst.md` — analyst template ({{TASK}}/{{CANDIDATES_JSON}}
  substitution, deep-read mandate, strict JSON contract, untrusted-bodies security).
- `scripts/consult_log.py` — verdict row appender for the invocation ledger.
- `docs/adr/0049-consult-deliberation-layer.md`.

Edited:
- `scripts/build_triggers.py` — `scroll_all_points(paths=False)` optional third
  field; default byte-identical.
- `scripts/flywheel.py` — `--capsules` flag wires the third generator into
  `generate()` (opt-in; NOT in auto_flywheel v1 — bulk first run is
  operator-commissioned, same doctrine as ADR-0031 D10).
- `vendor/skill-search/skill_search/server.py` — new `consult_candidates` MCP tool
  (wide top_n, capsule attachment, path+scope carried, blocklist-filtered) +
  `SKILL_CAPSULES` gate (default ON, live-read corpus); `_fuse_ranked` grows a
  `with_paths` param, default off = byte-identical.
- `vendor/skill-search/VENDORED.md` — record the engine patch.
- `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`,
  `.codex-plugin/plugin.json`, `package.json` — 0.41.0 → 0.42.0.
- `CHANGELOG.md`, `README.md` (usage + skills list), `AGENTS.md` (skills line +
  flag doc), root `CLAUDE.md` quick-ref, `openwiki/` (parity gate),
  `docs/epoch-watch.md` (new epoch section).

Corpus (runtime, not in repo): `~/.claude/skill-concierge/capsules.json`.

## Capsule schema (v1)

`{purpose, capabilities[3-6], inputs, outputs, avoid_when}` — problem/outcome framing
with vocabulary deliberately different from the description (the ADR-0026 v2 lesson:
vocabulary distance is the recall lever). ~150-300 tokens.

## Verification (status 2026-08-29 ~23:3x)

1. [DONE] `llm_capsules.py --selftest` PASS · `consult_log.py --selftest` PASS ·
   `build_triggers` import OK · engine compile OK · venv redeployed
   (`pip install --force-reinstall --no-deps vendor/skill-search`).
2. [DONE] e2e probe PASS (plans/260829-2240-consult-mode/e2e_probe.py): leg 2 —
   production server binary exposes `consult_candidates` + live tools/call returns
   rows; leg 1 — fused rows, capsule_coverage, empty-query error, SKILL_CONSULT=0
   kill-switch. Two probe-harness defects found and fixed en route: payload `path`
   backfill (trigger points omit it → deterministic-id batch retrieve, now in
   server.py) and stdin-EOF reply loss (probe holds stdin open now — probe-only).
3. [DONE] Capsule pipeline live: `--limit 2` smoke wrote 2 capsules; attachment
   verified (9router carries its capsule in a live sieve call).
4. [N/A in-session] The `consult` skill enters the index when the OPERATOR updates
   the plugin (`/plugin marketplace update` → plugin updates → restart); the dev
   repo's skills/ dir is not a discovery root.
5. [DONE] `driftcheck.py` exit 0 · `doctor` WARN only on sibling-harness cache lag
   (OMP 0.40.0 / Codex 0.41.0 / ZCode 0.41.0 vs SSOT 0.42.0 — operator-gated
   deployment chain, the standing between-release condition).
6. [RUNNING] Blind tester subagent (RULES [57]) — report at
   plans/reports/blind-tester-260829-2330-consult.md.
7. [PENDING] Commit (scoped to consult files) + push.

## Rollback

- `SKILL_CAPSULES=0` disables capsule attachment (sieve degrades to rows-only).
- Remove `--capsules` from a flywheel invocation = old behavior.
- Git revert of the single commit restores 0.41.0; no data migrations (capsules.json
  is a new file, ignorable).
