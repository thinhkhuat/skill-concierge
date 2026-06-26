# PM Progress — skill-first × skill-search Semantic Fusion (P1)

**Plan:** `plans/260626-1751-skill-first-semantic-fusion-impl/` · **Run:** `ck:cook --auto` · 2026-06-26
**Overall:** Phases 1-3 DONE + verified. Phase 4 acceptance/review/baseline DONE; **live go-live owner-gated → STOPPED**.

## Phase status (from checkbox sync-back)

| Phase | Status | Criteria | Evidence |
|---|---|---|---|
| 1 Warm Embed Endpoint | **Done** | 4/4 | health ok·mpnet·dim768; parity cosine **1.000000** vs deployed Docker shim (EN+VN); warm POST **13.8ms** median; sidecar `--restart unless-stopped` 127.0.0.1:6363 |
| 2 Hook Rewrite | **Done** | 5/5 | `enforcer.py` injects semantic top-k; lexical scorer + `library.json` removed; `analyze.py` repointed to Qdrant index + hit@k; safety contract intact; semantic-jump smoke |
| 3 Resilience & Budget | **Done** | 4/4 | hard **90ms** client embed timeout; embed-down / embed-timeout / qdrant-down → mandate-only; slow-path **140ms**; fallback tagged + rate reported |
| 4 Acceptance & Rollout | **In progress** | 8/10 | baseline snapshot captured; acceptance green; code-review (0 blockers, 6/6) + tester (11/11); 2 findings fixed. **2 pending → owner** |

## Built / changed (working dir `skill-concierge/`, NOT yet installed)

- `scripts/embed_server.py` (new), `bin/embed-shim` (new), `Dockerfile` + `.dockerignore` (new)
- `vendor/skill-search/pyproject.toml` — `fastembed==0.8.0` pin
- `setup.sh` — shim sidecar bring-up
- `hooks/scripts/enforcer.py` (new) + `hooks/hooks.json` (register) + `hooks/scripts/ledger.py` (q-join fix)
- `scripts/analyze.py` — Qdrant catalogue repoint + hit@k/fallback/band reporting

## Verified-empirically deviations

1. **Embed timeout 90ms (not nominal ~120ms).** Measured python cold-start ~50ms made 120ms breach the co-equal ≲150ms total budget. 90ms → slow-path 140ms, 3.75× headroom over 24ms warm p95. Env: `ENFORCER_EMBED_TIMEOUT`.
2. **Plan misattributions corrected:** the `library.json` read was in `analyze.py` (not `ledger.py`); `bin/embed-shim`↔Docker-sidecar tension resolved (sidecar = deployed runtime, launcher = host/dev + parity-test).

## Pending (owner-gated — Phase 4 go-live, HIGH-RISK)

1. Back up + **deregister `skill_first_nudge.py`** from `~/.claude/settings.json`.
2. **Marketplace version bump + full plugin install** so `enforcer.py` goes live via `hooks.json` (cache 0.1.0/0.1.1/0.1.2 has only `ledger.py`).
3. logman `RETENTION_DAYS=0` wiring (step 8, deferrable).

## Risk note

**No double-injection today** — verified the cached plugin lacks `enforcer.py`; only the lexical hook fires. Correct ordering (deregister → install) prevents double-injection at go-live. Baseline is captured, so the before/after comparison survives the swap.

## Unresolved questions

- Go-live timing: owner signals ready after inspecting `analyze.py` (no fixed window).
- `session_id` sharing for subagent `Skill` calls (Phase 2 open question) — verify against post-go-live data; tag/segment if it inflates uptake/hit@k.
