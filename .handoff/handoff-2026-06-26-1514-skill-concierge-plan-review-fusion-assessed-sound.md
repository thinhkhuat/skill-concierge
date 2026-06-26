# Session Handoff — skill-concierge plan review: fusion approach assessed sound (warm-embedder A + timeout)

> Saved to `skills-dev/.handoff/` (not `skill-concierge/.handoff/`) because **read-only mode is active on the skill-concierge repo** — it was left untouched. This continues the same `.handoff/` dir as the prior (skill-search) handoff this conversation.

## Where it started
Continuation of the skill-search deployment session (prior handoff: `handoff-2026-06-26-0134-skill-search-system-wide-deploy-keepon-tuning.md`). After clarifying the token saving is **per-turn** (~19% of the 200K window, every turn), the user revealed a "totally other plan" for the skill-discovery problem and asked me to study, in **read-only mode**, a new in-planning plugin: `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge`. Output was an assessment + a verdict on whether to proceed — no build.

## Decisions locked + what shipped (this slice = analysis only, no files written)
- **skill-concierge = a skill-governance layer fusing 3 organs** (`skill-concierge/README.md:8-13`, `docs/plan.md:9-13`): **Retrieve** (which skill — *is* skill-search: Qdrant + mpnet-768) + **Enforce** (whether the model uses one — the `skill-first` UserPromptSubmit hook, rewritten) + **Ledger** (what actually got used — compounding invocation telemetry → data-backed always-on curation).
- **Reframes "discovery" as 3 gaps, not 1** — which / whether / what-actually-used. Proactive (hook injects semantic candidates every turn under a use-mandate) vs my earlier reactive framing (model must remember to call `search_skills`). This is a broader, arguably better answer to the discovery problem.
- **Phase 1 core** (`plan.md:46-59`): retire the hook's weak lexical scorer + the drifting `library.json` catalogue; point the hook at the **same semantic Qdrant index** skill-search uses. One catalogue, kills the 585-vs-508-vs-512 drift.
- **The crux** (`plan.md:25-44`): the hook fires cold every prompt and must stay fast (~71ms today); cold-loading mpnet-768 per prompt is seconds → over budget. So Phase 1's real deliverable is a **warm embedding endpoint**.
- **Warm-embedder decision — I endorsed A** (`plan.md:38-44`): persistent fastembed-mpnet HTTP shim, sidecar to Qdrant, **same model → existing index stays valid, no rebuild**. Rejected B (Ollama; forces rebuild + parity re-validation for only daemon-consolidation) and C (cold-load; multi-second hook).
- **My one refinement (fold into acceptance `plan.md:113`+`:117`):** add a hard embed **timeout (~120ms) → fall through to mandate-only**, so an *up-but-slow* shim degrades gracefully and the ≲150ms budget is enforced, not hoped (the plan's fallback currently triggers only on *unreachable*).
- **Verdict rendered: SOUND to proceed, no blocking objection.** What makes it sound is that it's **self-falsifying** — telemetry-first banks a baseline, then measures dodge-rate/uptake before-vs-after rather than asserting the lift.
- **Data-backed always-on curation** (`plan.md:90-99`) will **supersede this session's judgment-curated 31-on set**: promote = high auto+manual frequency × cross-session breadth; demote = in always-on but ~never invoked. My reasoning-based picks are the seed/baseline; the ledger is the corrective.

## Key files for next session

| File | Why |
|------|-----|
| Plan: `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/docs/plan.md` | THE design (143 lines). Read first — goal, crux, A/B/C, phases, ledger spec, acceptance, risks. |
| `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/README.md` | 3-organ overview + target layout. |
| `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/.claude-plugin/plugin.json` | Plugin manifest (v0.1.0 scaffold). |
| `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/dev-hooks/skill-first-nudge/skill_first_nudge.py` | The enforcement-half hook to be rewritten. NOTE: `plan.md:50` calls the dir `hooks-dev/skill-first-nudge/` but session memory shows `dev-hooks/skill-first-nudge/` — verify the real path before editing. |
| `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skills-dev/.handoff/handoff-2026-06-26-0134-skill-search-system-wide-deploy-keepon-tuning.md` | The skill-search deployment (the retrieval substrate skill-concierge fuses) — full config state. |
| `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skills-dev/docs/skill-search-deployment-readme.md` | skill-search ops doc — Qdrant server, embedder, 31-on set, the `generate_overrides.py` landmine. |

- Memory touched: none (no file-memory or agentmemory lessons written this session).

## Running state
- Background processes: none (no `run_in_background` shells/subagents this slice).
- Dev servers / ports: Qdrant container `skill-search-qdrant` on `localhost:6333` (from the skill-search deployment; it is the index home skill-concierge reuses). Stop: `docker stop skill-search-qdrant`. No warm-embed shim exists yet (that's Phase 1's deliverable).
- Open worktrees / branches: none.
- **Mode: READ-ONLY active on `skill-concierge`** — survives compaction. Must lift via the 2-gate process (explicit directive + AskUserQuestion confirm) before any build/write in that repo.

## Verification — how to confirm things still work
- Read-only status: still active until explicitly lifted; re-assert on resume.
- skill-search substrate (skill-concierge depends on it): in-session call `mcp__skill-search__health` → ok, or CLI `skill-search --health` with env (`SKILL_QDRANT_URL=http://localhost:6333`, `SKILL_EMBED_MODEL=sentence-transformers/paraphrase-multilingual-mpnet-base-v2`).
- `docker ps --filter name=skill-search-qdrant` → `Up`.

## Deferred + open questions
- Resolved this session: **warm-embedder approach A nodded** (with the timeout refinement). The plan's "awaiting nod" gate (`plan.md:3`) is cleared.
- Open: build has NOT started — awaiting go to build Phase 1.
- Deferred (by plan design): P2 hard-gate classifier (`plan.md:106-109`) — only if logged dodge-rate shows soft-enforcement leak; logman wiring with `RETENTION_DAYS=0` (`plan.md:80-84`); custom recall@k eval (carried from skill-search).
- Risk to guard (corroborated this conversation): `generate_overrides.py` targets `settings.local.json` (now moved to `settings.json`) with a 2-item keep-on default → a rerun nukes the curated always-on set (`plan.md:141-143`). Guard before any override regen.

## Pick up here
Lift read-only on skill-concierge, then build Phase 1 **telemetry-first**: ship the append-only invocation ledger + analyzer and bank a baseline on the CURRENT `skill-first` lexical hook BEFORE the warm-embedder + hook rewrite — otherwise the before/after fusion-lift comparison is lost permanently.
