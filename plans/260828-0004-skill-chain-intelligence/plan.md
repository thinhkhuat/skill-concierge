# Plan: Skill-Chain Intelligence — better single picks, proactive multi-skill chains

Opened: 2026-08-28 00:04 ICT · Status: Phases 1–3 implemented and live (0.31.0, 0.32.0 / ADR-0040, ADR-0041); Phase 4 (continuation-rate telemetry in analyze.py) designed, not started — offer rows already carry n_intents/route
Owner ask: strengthen the agent's decision on which skill fits the user's intent — and stop
assuming one skill: most real tasks benefit from chaining 2–3+ skills end-to-end.

## 1. Evidence (what the system actually does today)

All numbers from live artifacts, epoch `--since 2026-08-20` (guardrail: epoch-scoped, never pooled).

**Multi-skill is the norm, not the exception.**
- 623 skill invocations across 191 sessions (all-time ledger, `~/.claude/skill-concierge/logs/skill-invocation-ledger.log`).
- 110/191 sessions (58%) invoked ≥2 distinct skills; length distribution runs to 10.
- Real 8-deep chains observed: `ak-brainstorm → ak-plan → session-handoff → ak-journal`,
  `spec-plan-adversarial-review → whereami → noob-mode → what-next → conventional-commit → …`.
- Current epoch: 17/34 skill-using sessions carried a chain ≥2.

**The chaining layer exists but is data-starved (ADR-0029).**
- CHAIN-HINT fires only *reactively* — after a skill was already used within a 15-min TTL,
  seeded by the single last-used skill.
- Its knowledge source is `next-skills:` frontmatter: **3 of 757 skills declare any (0.4%)**
  + ~8 operator-curated entries in `next-skills-overrides.json` (ADR-0030).
- The ledger already records the ground truth (per-session ordered `auto`/`manual`
  sequences, subagent lanes excluded) — but nothing mines it into chain knowledge.

**Decision quality for the single pick (the "before" baseline).**
- uptake 13% (67/522 turns), offered-turn conversion 7% (28/387), dodge-after-offer 93%,
  hit@k 51% (28/55). Offer slots are repeatedly burned by the same never-taken skills
  (e.g. `tool-design` 0/98, `verify-ratatui-render-headless` 0/104).
  (Caveat per skill-usage-audit: offer→take is a lower bound on usage, not usage itself.)

**Retrieval assumes one intent.** `_retrieve` embeds the whole prompt once; candidates
compete for 8 slots of a single blended intent. A prompt carrying
"research X, then build a deck, then push" starves its secondary intents.

## 2. Architecture — four layers

**L1 · Chain knowledge base (fixes the data starvation).** Offline miner
(`scripts/build_chains.py`) turning the ledger's real per-session sequences into a
successor map `mined-chains.json`, scored by support × lift:
`lift(A→B) = P(B follows A) / P(B)` — suppresses session-tail universals
(`X → session-handoff` follows everything; it is closure, not a semantic successor).
Precedence at read time: **operator overrides > declared frontmatter > mined**
(mined is additive-only: it fills empty slots, never overrides a human decision).
Consumed by the existing CHAIN-HINT path — same filters for free (keep-off, catalogue
membership, scope visibility). Fail-open everywhere. This is Phase 1 (shipped here).

**L2 · Proactive chain projection (fixes "only after a skill fired").** At offer time,
when the top candidate P has successors in the merged map, render one bounded line:
`workflow from here: P → s1 → s2` inside `_ranked_mandate`. Context-only, no gate
bypass, same class as CHAIN-HINT but projected *before* the first invocation.
Flag `ENFORCER_CHAIN_PROJECTION` (default off until L4 shows it does not add push-noise).

**L3 · Multi-intent offer shaping (fixes the single-intent assumption).**
Deterministic, zero-network clustering of the already-fetched top-K: greedy cluster by
lexical overlap of (name + description + top triggers); if ≥2 clusters clear the floor,
re-render the offer as "this task spans N intents" with the best candidate per cluster
first, instead of one blended list. v2 (engine-side): segment multi-imperative prompts
(max 3 segments) and retrieve per segment. Flag `ENFORCER_MULTI_INTENT`.

**L4 · Close the loop.** Extend `analyze.py`: chain-continuation rate (hint named B →
did B fire within N turns?), projection-follow rate, multi-intent offer precision.
Epoch-scoped; snapshot the "before" epoch before arming L2/L3 (recorded in §1).

## 3. Phase 1 scope (this change)

1. `scripts/build_chains.py` — stdlib-only miner: ledger → `mined-chains.json`
   (support ≥2, lift ≥1.5, gap ≤120 min, catalogue-resolved names, cap 3 successors,
   selftest with synthetic ledger).
2. `hooks/scripts/enforcer.py` — merge seam: mined map loads under
   `SKILL_CONCIERGE_MINED_CHAINS`, gated by `ENFORCER_MINED_CHAINS` (default **on** —
   context-only line, same filter pipeline, additive precedence below both human layers).
3. Selftests + ADR-0040 + this plan doc.

Out of scope here: L2, L3, L4 (designs above), any threshold/gate changes.

## 4. Risks & guards

- **Session-tail artifacts** → lift filter + support floor; `session-handoff`-style
  universals die on lift alone; explicit drop-list if any survive.
- **Sparse data** (max pair support 4 all-time) → min-support 2 is honest at this
  density; the map grows as the ledger compounds (the whole point of the compounding
  ledger). Epoch floor `--since` keeps config-era mixing out.
- **Push-noise (ADR-0009)** → hints remain context-only, one line, TTL-bounded;
  L2 stays OFF until L4 measures it.
- **Subagent lanes / cross-harness rows** → sub-stamped rows excluded (ADR-0020);
  sid-scoped sequences are naturally single-harness.
- **Stale names** → catalogue resolution against the reindex-built sidecar union;
  dangling names never enter the map.

## 5. Verification

- `python3 scripts/build_chains.py --selftest` (synthetic ledger, artifact rows,
  lift/suppression, precedence purity).
- Miner run over the live ledger → `mined-chains.json` reviewed by hand (below).
- `hooks/scripts/enforcer.py --selftest` extended with mined-merge precedence cases.
- No behavior delta when `mined-chains.json` absent (fail-open) — pinned by selftest.
