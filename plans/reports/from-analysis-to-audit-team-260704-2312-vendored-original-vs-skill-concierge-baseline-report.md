# HANDOVER ASSESSMENT — Vendored Original (skill-search 0.1.0) vs skill-concierge (0.12.0)

**Type:** baseline study + audit charter · handed to the evaluation team
**Date:** 2026-07-04 23:12 (Asia/Saigon) · **Author:** orchestrating agent (first-hand reads)
**Constraint (HARD):** READ-ONLY. Do NOT write to the skill-concierge repo OR the vendored source.
ALL outputs go to workbench reports dir: `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/plans/reports/`.

## Why this exists
The user forked/built skill-concierge on top of the vendored `sowhan/skill-search` engine. Two
questions to answer, evidence-grounded:
1. **Missed novelties** — did we DROP, disable, or diverge-from anything good in the original?
2. **Over-engineering / degradation** — did we ADD machinery that made the process WORSE (heavier,
   slower, less reliable, lower-converting) rather than better?

## Ground truth established this session (cite these, don't re-derive)

### Upstream drift: NONE.
`WebFetch https://github.com/sowhan/skill-search` (2026-07-04): latest release **v0.1.0** (2026-06-18),
7 commits total, no post-0.1.0 features. → The vendored copy at `vendor/skill-search/` **is** the
current upstream. "Missed novelties" = things in 0.1.0 we didn't carry, NOT new upstream work.

### The original (skill-search 0.1.0) — design DNA
Source read first-hand: `vendor/skill-search/README.md`, `pyproject.toml`, `generate_overrides.py`,
`scripts/measure_tokens.py`, `skill_search/server.py`, `skill_search/skills_discovery.py`, `VENDORED.md`.

- **One idea, two pieces "useless apart"** (README:141-149): (a) `generate_overrides.py` sets all
  skills `name-only` to free the budget; (b) `server.py` retrieves top-k on demand. Skip (a) → pay
  both taxes.
- **SERVICE-FREE by default** (README:159-163, pyproject:20): embedded on-disk Qdrant
  (`~/.cache/skill-search/qdrant`) + local ONNX `fastembed BAAI/bge-small-en-v1.5` (384-dim). **No
  Docker, no Ollama, no server.** Opt-in faster tier = Qdrant server + Ollama 768-dim.
- **4 MCP tools:** `search_skills`, `get_skill`, `reindex` (incremental, content-hash), `health`.
- **Fails loud, not silent** (README:99-108): `search_skills` appends a `warning` when skills changed
  on disk; `health` lists **dark** (on-disk, unindexed) + **stale** (indexed, deleted) skills, exits
  non-zero when degraded (cron/CI-safe).
- **Proof harness shipped** (README:26-97): measured token savings on 117 skills (6,380 tok/turn saved)
  via `scripts/measure_tokens.py` (real tiktoken BPE); a 24-query labeled eval → bge-small
  recall@1 0.67, @3/@6 0.79; incremental reindex ~0.07s. Honest "prompt-cached?" rebuttal
  (README:111-137): caching is a BILLING win, not a CONTEXT-WINDOW win.
- **Tail-scale caveat, stated by the author** (README:19-22, 285-286): "pays off once you have a lot of
  skills — roughly hundreds. With only a handful… you don't need the extra round-trip." Overkill at a
  handful.
- **Overrides target = `settings.local.json`**, keep-on default `{"skill-search","skill-finder"}`.
- **Tests:** 13 unit (offline) + integration marker; pins discovery/parsing/namespacing/dedup,
  point-ID validity, content-hash determinism, staleness guards.
- Lean: `server.py` + `skills_discovery.py` + `generate_overrides.py` + `measure_tokens.py`.

### What skill-concierge did to it (the fork delta)
From `VENDORED.md` + first-hand reads of the fork (enforcer.py, hooks, scripts, ADRs 0001/0009/0012/
0015/0016, README, doctor output). Two layers:

**A. Plugin-level layer (vendored source UNMODIFIED):**
- Embedder swapped bge-small-384 → **mpnet-multilingual-768** (fixes EN-query→VN-skill misses).
- Vector store: embedded → **Qdrant server (Docker) @ localhost:6333** (concurrent sessions).
- Overrides: rewritten `scripts/apply-overrides.py` → **global `~/.claude/settings.json`**, 31-skill
  keep-on (upstream `generate_overrides.py` is BANNED — reverts the curated set; caveats §2).
- Stable venv outside plugin cache (ADR-0004); bundled MCP launcher; warm embed shim sidecar
  (`scripts/embed_server.py` @ 6363, Docker sidecar).

**B. Direct engine patches (modify vendored source; re-apply on re-vendor):**
- Multi-vector MAX-pool retrieval (v0.10.0, ADR-0012) — base + per-trigger points, `group_by=name`.
- Plugin self-prefix guard (v0.10.2) — no `ck:ck:`.
- Body-derived trigger points (v0.12.0, ADR-0016) — mine body decision-sections; index 2231→3570 (+60%).

**C. The whole NEW governance layer skill-concierge added (has NO analog in the OG):**
- **Enforce organ** — `hooks/scripts/enforcer.py` (~715 lines): per-turn UserPromptSubmit gate, embeds
  via warm shim, retrieves, applies GETAWAY_FLOOR (0.45, operator-set against ADR-0009 data) + word
  floor + an **actionability gate** (class-margin over a 912-prompt `prompt_intent` corpus) + AUTHORIZED-
  SKIP tier (ADR-0015, getaway leg shipped ON against its own data) + a VN imperative lexicon.
- **Doctrine** — SessionStart injection of the SKILL-FIRST standing order (`hooks/doctrine/skill-first.md`).
- **Ledger** — append-only JSONL + `scripts/analyze.py` (uptake/dodge/hit@k) + `audit_skill_usage.py`.
- **Self-heal** — `auto_reindex.py` (ADR-0014), `doctor.py` engine-freshness (ADR-0013).
- **Default-INERT machinery** (shipped, wired, tested, OFF): per-skill tau, deterministic routes,
  runner-up-gap collapse, keep-off suppression (`config/keep-off.json` currently `[]`), legacy MEAN
  `enrich_index.py` (superseded, must-not-run).
- **16 ADRs**, ~5,200 LOC of scripts/hooks, Docker, calibration harnesses.

### Known open tensions (from the fork's own docs — the audit should weigh these)
- GETAWAY_FLOOR 0.45 raised on *perceived* behavior; ADR-0009 data argued AGAINST it (taken offers
  score LOWER than dodged, 0.414 < 0.457) — a higher floor cuts the better-converting offers first.
- AUTHORIZED-SKIP getaway leg shipped ON against that same data (operator override, ADR-0015 D1); zero
  live exercise in two wild-run reports.
- Body-trigger lift un-isolable; the vendored `eval/` is wrong-universe (recall@k ≈ 0, by design).
- No valid retrieval-quality benchmark exists in the fork (the OG's 24-query eval was NOT re-run on our
  excluded-universe index).

## AUDIT DIMENSIONS (one agent each)

**D1 — Missed-novelty auditor.** Did we drop/disable/degrade anything good from 0.1.0? Focus: the
SERVICE-FREE default (we now HARD-require Docker+server — is that a portability regression?); the
`search_skills` on-disk-drift `warning` + `health` dark/stale reporting (did our fork preserve or lose
it?); the shipped token/recall PROOF HARNESS (`measure_tokens.py`, the 24-query eval — did we keep a
way to prove value on OUR index?); the OG's honest tail-scale caveat; upstream tests (did we keep/adapt
the 13 unit tests?). Output: table of {OG feature → status in fork (kept / diverged / dropped / broken)
→ evidence file:line → verdict}.

**D2 — Over-engineering auditor (ponytail lens).** What did we ADD that a senior would call bloat or a
net negative? Rank candidates to DELETE / SIMPLIFY / REVERT-TO-NATIVE. Prime suspects: the default-inert
graveyard (per-skill tau, deterministic routes, dominance collapse, keep-off, enrich_index) — shipped
but OFF, is it dead weight?; the GETAWAY_FLOOR-against-data + AUTHORIZED-SKIP-against-data decisions; the
715-line enforcer vs the OG's lean design; 16 ADRs / Docker / shim / stable-venv operational surface.
Output: ranked list {thing → why it may degrade vs OG → delete/simplify/keep → evidence}.

**D3 — Retrieval-fidelity auditor.** Did multi-vector MAX-pool + body-triggers genuinely IMPROVE
retrieval over the OG's single full-description embedding, or add topical noise / dilution? Weigh: the
+60% index growth, the COMBINED _TRIG_MAX=12 cap, MAX-pool vs mean-centroid, the ABSENCE of a valid
benchmark on our universe. Is the fork's retrieval provably better, provably worse, or UNMEASURED?
Output: evidence-graded verdict + what benchmark would settle it.

**D4 — Ops-complexity & value auditor.** Install/deploy/maintenance cost delta. OG = ~4 commands,
service-free, one process. Fork = Docker + Qdrant server + stable venv + shim + overrides + reindex +
doctor + 16 ADRs. Is the added ops surface JUSTIFIED by measured value, or has the fork traded the OG's
"drop-in, service-free, tail-scale" simplicity for machinery whose payoff is unproven? Cross-check the
tail-scale premise: the OG says the whole approach is "overkill at a handful" — does our added
enforcement change that calculus, and for whom? Output: cost/benefit ledger + honest ruling.

**Cross-cutting rule for all four:** distinguish (a) genuine improvements, (b) lateral changes, (c)
regressions/over-engineering. Ground every claim in a file:line from either tree. Read-only. Report to
the workbench reports dir with your own `{d1|d2|d3|d4}-...` filename. End each with
Status + one-line Summary + Unresolved.

## Unresolved (for the team to close or flag)
- No valid retrieval benchmark on the excluded-skill universe — D3 must say what it'd take to build one.
- Whether the service-free default is RECOVERABLE as an option in the fork, or architecturally lost.
- Whether any default-inert feature has EVER been armed in production (ledger/telemetry check).
