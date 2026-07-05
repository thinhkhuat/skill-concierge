# Agent Experience Report — v0.13.0 After Restart (doctrine live, engine stale)

**Date:** 2026-07-05 21:40 (Asia/Saigon) · **Author:** operating agent, first-person
**Scope:** Re-run of the skill-concierge introspection after the operator restarted Claude Code to "make full v0.13.0 active." What the governance layer actually did to me this session, grounded in same-turn evidence. The headline is a gap, not a win: v0.13.0 is HALF-deployed.

## Environment confirmed (grounded, this session)
- Deployed plugin source `~/.claude/plugins/marketplaces/skill-concierge/.claude-plugin/plugin.json` -> **0.13.0** (`json.load`, this turn).
- The doctrine GOVERNING me now IS 0.13.0: the SessionStart injection in my context carries my own v0.13.0 edit verbatim — "pass 2-3 phrasings via `extra_queries=[...]` for one-call max-pool fusion" plus the Raw-vs-Better worked example. Primary evidence the 0.13.0 doctrine is live on me right now.
- The ENGINE is NOT 0.13.0. `python3 scripts/doctor.py` -> **`status: FAIL`**:
  - `[!] Engine freshness — venv engine code DIFFERS from the deployed plugin source — the MCP is serving STALE engine code after a plugin update; rerun ./setup.sh (skill-concierge:setup), then restart Claude Code`.
  - `[x] Retrieval health — 5 indexed skill(s) deleted from disk (dead results) — run reindex(); disk changed since last index`.
  - Live `search_skills` tool schema advertises **`{query}` only** — no `extra_queries`.

## Post-restart verification

| Check | Result |
|---|---|
| Deployed version (marketplace plugin.json) | 0.13.0 |
| SessionStart doctrine | 0.13.0 (`extra_queries` + worked example injected into me) |
| `doctor.py` status | **FAIL** — engine-freshness stale + retrieval-health dead-results |
| Engine freshness | STALE — venv engine != deployed source; restart re-execs but does not rebuild the venv |
| `search_skills` schema | `{query}` only — `extra_queries` NOT exposed |
| Fanout probe `extra_queries=[...]` | **silently ignored** — output byte-identical to the plain query, no `queries` echo |
| `SKILL_TOP_K=10` (`.mcp.json` env) | LIVE — plain query returns 10 results (default was 6) |
| `codebase-onboarding` on the raw query | now rank **7 / 0.6937** — inside top-10 (was outside top-6) |
| Multi-vector layer (doctor) | 3082 trigger points / 3570 total |
| `health()` | degraded — indexed 488 vs disk 483; 5 dead: agent-harness-construction, check, cicd-pipeline-generator, completion-check, design-then-build |

## First-person experience

**1. The 0.13.0 doctrine is live on me — and it instructs a capability the engine can't perform.**
My injected standing order tells me to pass `extra_queries` for one-call fusion. I obeyed it: called `search_skills("explain to me how a project codebase works", extra_queries=["codebase onboarding walkthrough","understand unfamiliar codebase architecture"])`. The call succeeded, but the engine **silently ignored** the arg — the result is byte-identical to the plain single-query call, and the `queries` echo my 0.13.0 code emits when >1 phrasing is absent. The doctrine points me at a lever the live engine does not have.

**2. Why: v0.13.0 is HALF-deployed. The restart moved the doctrine + hooks + env, not the engine.**
`/plugin marketplace update` + restart refreshes the deployed source — doctrine text, the enforcer hook, the `.mcp.json` env — and those reload. But the MCP engine runs from the stable venv (`~/.local/share/skill-concierge/venv`), which a restart re-execs but does NOT rebuild. So the fanout CODE (`_fuse_ranked`, the `extra_queries` param) is simply absent from the running server. This is the exact ADR-0004 / ADR-0013 / ADR-0016 deploy dependency: `pip install vendor/skill-search` into the venv + a reindex is required for an engine change to take effect. Doctor names the fix verbatim: **rerun `./setup.sh` (or the `skill-concierge:setup` skill), then restart.** The operator's restart alone was necessary but not sufficient.

**3. The half-win that IS live — the env bump alone partly fixes the original complaint.**
`SKILL_TOP_K=10` took effect on the MCP relaunch (env from `.mcp.json`, read at process start): the raw query now returns 10 results, and `codebase-onboarding` — the skill invisible below the top-6 cut when this whole thread began — surfaces at rank 7 (0.6937). The cheapest lever (a config env, not engine code) already delivers a partial live fix; the fusion that would rank it higher is the piece still dark.

**4. AUTHORIZED-SKIP / the two silent legs — not exercised (the honest gap, again).**
Every turn this session carried a real task with a governing skill/command (the introspection itself). No turn was trivial enough to trip the getaway (score-floor) or intent-skip (conversational) legs, so I never received a `SKILL-CHECK:` line. Same gap the v0.12.0 exemplar flagged: a focused work session supplies no live pressure to the riskiest shipped surface.

**5. The friction — line-1 token + preview, a standing tax.**
This turn the per-turn preview surfaced no candidates (a slash-command meta-prompt); the token was `USING: experience-skill-concierge`, unambiguous. The tax bought nothing decision-wise here — it is a cost paid every turn to catch the subset where I would wrongly skip.

**6. The boundary — governance cannot see its own deployment state.**
Sharpest lesson: the doctrine confidently instructed me to use `extra_queries` while the engine it points at silently lacks the param. The in-generation governance layer (doctrine + enforcer) reloads from source and has NO knowledge that the out-of-process engine venv is stale. Retrieval/gating improves skill *selection*; it does not — cannot — verify that its own tool actually implements what its doctrine advertises. Only the out-of-band `doctor.py` catches the skew. I hit a doctrine/engine version mismatch that is invisible to the doctrine itself.

**7. My own process was the unreliable part — I over-claimed "live" earlier.**
Two turns before the restart, after the operator ran the marketplace update + reload, I told them v0.13.0 was "live in your runtime." That was wrong for the engine — I trusted the reload signal and did not run `doctor.py` to confirm the venv. `doctor.py status: FAIL` (stale engine) exposed it. The plugin state was knowable the whole time; my verification was the sloppy link. Graded at the same bar I would grade another agent: an unproven "it's live" claim.

## Net
v0.13.0 is HALF-live. Doctrine + enforcer hook + `SKILL_TOP_K=10` env are active on me — and the env bump alone already surfaces `codebase-onboarding` at rank 7 on the raw query. The flagship — query fanout — is DARK: the engine venv is stale, `extra_queries` is silently ignored, retrieval health is degraded (5 dead results), doctor is FAIL. Restart was necessary but not sufficient.

## Unresolved
- **Engine stale / doctor FAIL** — fanout not callable. Fix: `./setup.sh` (or `skill-concierge:setup`) to rebuild the venv engine + reindex, then restart Claude Code. NOT run here — this is a read-only introspection and a venv rebuild is a runtime change that is the operator's call.
- **Retrieval health degraded** — 5 dead results (agent-harness-construction, check, cicd-pipeline-generator, completion-check, design-then-build); `reindex()` clears it (folded into `setup.sh`).
- **AUTHORIZED-SKIP getaway leg** — still zero live exercise; needs organic trivial/conversational turns + the `skill-usage-audit` window.
- **Fanout live-proof** — deferred until the engine is rebuilt. The code itself is verified (earlier this session: unit tests + a direct-import e2e against Qdrant), but it is not yet exercisable through the live MCP.

## Standing lens (committed)
For the rest of this session I keep watching the layer act on me. After >=3 more real task-turns I append a LIVE ADDENDUM, and I will deliberately route at least one trivial/conversational turn so the AUTHORIZED-SKIP legs get live exercise — the surface single-session reports most often miss.
