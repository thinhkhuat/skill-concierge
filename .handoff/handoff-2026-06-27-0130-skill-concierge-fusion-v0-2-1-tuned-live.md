# Session Handoff — skill-concierge semantic fusion: shipped v0.2.0, dogfood-tuned to v0.2.1 (live)

> Supersedes `handoff-2026-06-26-2037-skill-concierge-semantic-fusion-shipped.md` (same `.handoff/`).
> That one ended at "shipped, awaiting reload"; this one covers through the v0.2.1 dogfooding fix + live reload.

## Where it started
User ran `/cook <plan> --auto` on `skill-concierge/plans/260626-1751-skill-first-semantic-fusion-impl/plan.md`: retire the lexical per-turn skill-enforcement hook and point it at the SAME semantic Qdrant index `skill-search` serves, via a warm embed shim. Built 1→2→3→4, shipped on owner GO, then — when the user asked how the plugin performed from a dogfooding view — the plugin's own ledger exposed a ~60% fallback rate, which drove a v0.2.1 tuning fix. Everything is now live.

## Decisions locked + what shipped (full project, by phase)
- **Phase 1 — warm embed shim (Docker sidecar).** `scripts/embed_server.py` (stdlib http.server, mpnet-768 in memory; `POST /embed`, `GET /health`), reusing `skill_search.server.embed` for index parity. `Dockerfile`+`.dockerignore` build the sidecar on `127.0.0.1:6363`, pin `fastembed==0.8.0` (pooling parity; 0.5.1 is a trap), bake the model. `bin/embed-shim` host launcher. `setup.sh` builds/runs it. Parity = cosine **1.000000** (engine vs docker, EN+VN).
- **Phase 2 — semantic enforcer.** `hooks/scripts/enforcer.py` (UserPromptSubmit): embed→Qdrant top-k→inject mandate+candidates; fail-silent/additive/never-blocks; dropped the lexical scorer + `library.json`. Registered in `hooks/hooks.json` beside `ledger.py`. `scripts/analyze.py` catalogue repointed off `library.json` onto the Qdrant index (stdlib scroll) + reports hit@k/fallback/bands. Score getaway floor **0.20** (calibrated: trivia ~0.11, real tasks ~0.22–0.40 — narrow band, so low floor + always-show-top-k, not a high threshold).
- **Phase 3 — resilience.** Hard client-side embed timeout → mandate-only fallback on embed-down/timeout/qdrant-down, tagged in telemetry.
- **Phase 4 — shipped + live.** Committed/pushed, lexical `skill_first_nudge.py` deregistered from `~/.claude/settings.json`, plugin installed, reloaded.
- **Gates:** code-reviewer (0 in-code blockers, 6/6) + tester (11/11). Fixed: telemetry `offer↔turn` join broke on whitespace (`ledger.py` logs stripped `q`); stale docstrings.
- **Post-ship docs freshening (commit `f13ae51`):** caught go-live drift — README/CHANGELOG/`docs/plan.md`/ADR-0002 still said "unbuilt/held/pending"; freshened to "live".
- **Dogfooding fix → v0.2.1 (commit `d1acc32`, the latest work):** the live ledger showed **~60% `embed_timeout` fallback** — the single-threaded shim's mpnet inference, under real in-turn CPU contention (≈4 concurrent UserPromptSubmit hooks + working model + overlapping sessions), slipped past the 90ms cap (it's ~18ms idle). Two owner-approved fixes:
  1. **Threaded shim** — `embed_server.py` → `ThreadingHTTPServer` (ORT releases the GIL; 8 parallel embeds 288ms→**65ms**). **Already live** (container redeployed).
  2. **Timeout 90ms→200ms, total budget ≲150ms→≲300ms** (the hook is non-blocking additive context, so ~250ms worst-case is imperceptible). Lives in the 0.2.1 plugin; **applied via `/reload-plugins`**.
  - Versions bumped 0.2.0→**0.2.1** (plugin.json + marketplace.json); ADR-0008 rewritten, CHANGELOG 0.2.1 added.

## Key files for next session

| File | Why |
|------|-----|
| Plan: `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/plans/260626-1751-skill-first-semantic-fusion-impl/plan.md` | Read first — phases, status, deviation notes |
| `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/hooks/scripts/enforcer.py` | Live hook — tuning constants: `ENFORCER_EMBED_TIMEOUT` (0.20s), `GETAWAY_FLOOR` 0.20, `TOP_K` 5 |
| `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/scripts/embed_server.py` | Threaded shim served by the Docker sidecar |
| `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/scripts/analyze.py` | Ledger → uptake/dodge/hit@k/fallback; catalogue from Qdrant |
| `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/docs/adr/0008-warm-embed-shim-timeout-calibration.md` | Timeout/budget SoT — the 120→90→200ms history + dogfooding lesson |
| `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/plans/reports/baseline-260626-lexical-hook-snapshot.txt` | Lexical "before" (uptake 18% / dodge 82%) for before/after |
| `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/docs/journals/260626-semantic-fusion-impl.md` | Technical narrative (+ go-live update note) |
| `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/CHANGELOG.md` | 0.2.0 (fusion) + 0.2.1 (tuning) entries |

- Memory touched: none (no file-based memory or agentmemory `lsn_` written; decisions live in ADR-0008, the journal, the plan).

## Running state
- Background processes: none (all subagents completed; dev host shim killed).
- Docker containers (both `--restart unless-stopped`, REQUIRED for the live enforcer): `skill-concierge-embed-shim` → `127.0.0.1:6363` (now the THREADED 0.2.1 image); `skill-search-qdrant` → `localhost:6333`. Start: `docker start skill-search-qdrant skill-concierge-embed-shim`. Stop: `docker stop` the two.
- Dev servers / ports: the two containers above. No others.
- Branches/worktrees: none — `main`, clean, pushed to `origin/main` (`github.com/thinhkhuat/skill-concierge.git`), HEAD `d1acc32`.
- Plugin: `skill-concierge@skill-concierge` v**0.2.1**, enabled, reloaded live (37 skills / 34 hooks).
- Rollback: settings backup `/Users/thinhkhuat/.claude/settings.json.bak-260626-pre-fusion-golive`.

## Verification — how to confirm things still work
- `claude plugin list | grep -A2 skill-concierge@` → `Version: 0.2.1`, `Enabled`.
- `curl -s http://127.0.0.1:6363/health` → `status:ok`, mpnet, `dim:768`; `docker logs skill-concierge-embed-shim | grep threaded` → "(threaded)".
- `curl -s http://localhost:6333/collections/claude_skills` → `status:ok`.
- `python3 /Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/scripts/analyze.py` → live stats; **watch the fallback rate** (baseline was 60% pre-0.2.1; should drop now).
- Live enforcer happy-path (temp ledger, don't pollute the real one): `SKILL_CONCIERGE_LOG=/tmp/x echo '{"session_id":"t","prompt":"set up a postgres schema and migrations","hook_event_name":"UserPromptSubmit"}' | python3 .../hooks/scripts/enforcer.py` → injected JSON with ranked candidates; ledger `band=offer`.

## Deferred + open questions
- Open (the live verdict): is the v0.2.1 fix enough? Early post-reload window was ~33% fallback (down from 60%) but only ~1–2 true post-0.2.1 turns — **inconclusive**. Bank a handful of normal turns, then `analyze.py`. If still high, re-tune `ENFORCER_EMBED_TIMEOUT` or investigate host CPU contention.
- Open: cross-session ledger mixing — the global hook is shared, so a second concurrent Claude session writes `turn`/`offer` to the SAME ledger; the `session_id`-sharing question (do subagent `Skill` calls share the parent sid?) is still unverified and could skew uptake/hit@k.
- Open: the fusion before/after LIFT is unmeasured — needs a comparable post-go-live window vs `baseline-260626-lexical-hook-snapshot.txt`.
- Deferred: logman `RETENTION_DAYS=0` wiring (Phase 4 step 8) — ledger is already a single append-only `.log`; default 90d would DELETE data, so wire `RETENTION_DAYS=0` before relying on long-term compounding.
- Behavioral note (not a bug): uptake 17% / dodge 83% / hit@k n/a — the enforcer offers correctly but the agent still mostly improvises instead of invoking the offered skill. The nudge fires; compliance is the unsolved half.

## Pick up here
Let the v0.2.1 enforcer bank ~10+ normal turns, then run `analyze.py` and confirm the fallback rate dropped from the 60% baseline (and measure the uptake/dodge lift vs the lexical baseline snapshot). If fallback is still high, re-tune `ENFORCER_EMBED_TIMEOUT` / investigate contention before any further build work.
