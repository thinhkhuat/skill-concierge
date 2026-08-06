# Agent Experience Report — Live Run Under v0.18.1

**Date:** 2026-07-09 01:49 (Asia/Saigon) · **Author:** operating agent (Opus 4.8), first-person
**Scope:** what the shipped skill-concierge governance layer actually did to me across this session
(a `session-handoff` onboarding → flywheel-coverage verify → `verify-as-claimed` smoke-test →
this introspection arc). A lived-run account, not a spec review.

## Environment confirmed (grounded, this session)

- **Live marketplace install `= 0.18.1`** — read from `~/.claude/plugins/marketplaces/skill-concierge/.claude-plugin/plugin.json`; matches repo HEAD `.claude-plugin/plugin.json = 0.18.1`. (The `cache/` tree holds every historical version dir 0.1.0→0.18.1; the *marketplace* path is the live one.)
- **SessionStart injection is the live doctrine.** My context this turn carries the SKILL-FIRST standing order verbatim — the tells: *"The skills handed to you each turn are a TOP-FEW PREVIEW — not the inventory"* and the library-doctrine line *"Burden of proof is on SKIP."* That injection is primary evidence I am governed right now, not reciting from memory.
- **`doctor.py status: OK`** — all 13 rows green: 533 skills indexed (6m ago), 6999 trigger points of 7532 total (MAX-pool multi-vector live), flywheel 533/533 utterance coverage, overrides `32 on / 501 name-only`, single MCP, engine freshness matches deployed source.

## Verification table (this session, grounded)

| Check | Result |
|---|---|
| Live install version | `0.18.1` (marketplace plugin.json, read) |
| `doctor.py` | `status: OK`, 13/13 green |
| Retrieval health | 533 indexed, embedder+qdrant reachable, indexed 6m ago |
| Flywheel coverage | 533/533; last run `generated=5 error=0 skipped=528` |
| Utterance layer live | 6999 trigger points (base+utterances), `SKILL_LLM_TRIGGERS=1` in settings env |
| Cache-durable-home fix (v0.18.1) | smoke-tested this session — warm cache skipped 528/533, regen only 5 (separate raw-evidence report) |

## First-person experience (numbered, grounded)

**1. Library doctrine took a loose fit I might once have skipped — observably.**
On the smoke-test turn, the per-turn preview surfaced `verify-as-claimed` at **15%** — a loose, not obvious, fit for "run the generate command and see if the fix works." The doctrine line *"a loosely-adaptable fit is a USING, not a skip"* is exactly what made me route through it (`USING: verify-as-claimed`) and produce a raw-evidence table rather than free-hand a "looks fine." Same mechanism the v0.12.0 exemplar reported, firing again on a live turn.

**2. On THIS turn, the fitting skill was NOT in the preview — I selected by name-knowledge, not retrieval.**
The introspection turn's preview showed `cognee-quickstart 15% · verify-as-claimed 15% · ck:test 12% · writing-skills 12% · hunt 12% · compound-to-skill 12% …` — `experience-skill-concierge` was **absent**. I invoked it because I know the name exists in the catalogue, not because retrieval ranked it. Honest read: for a meta/introspection request phrased conversationally, the preview under-retrieved the precise skill — the exact failure mode rule 2 warns about ("a conversational sentence buries the precise one"). Retrieval is not omniscient; my catalogue memory covered the gap this time.

**3. The AUTHORIZED-SKIP tier (`SKILL-CHECK`) never fired on me — the honest, recurring gap.**
Every turn this session carried a real task with a fitting skill (`session-handoff`, `verify-as-claimed`, `experience-skill-concierge`), so I always went `USING:` and never hit the two silent legs (score-floor getaway / conversational skip). Same finding as the v0.12.0 exemplar: a focused work session supplies zero trivial/conversational turns, so the riskiest shipped leg gets no live pressure. I will deliberately route a trivial turn in the addendum to exercise it.

**4. The compliance ledger for this epoch is UNMEASURED — I will not cite it as a quality signal.**
Per the EPOCH-SCOPED hard rule (AGENTS.md L75-94), I windowed `analyze.py --since "2026-07-08 11:50"` (the last commit touching the doctrine/retrieval paths, `ee20e2e`). It returns: 102 events / 43 turn-windows, `fallback 69% (29/42)`, `offered-turn dodge 92% (12/13)`, `hit@k 1/3`. **These are not readable as effectiveness.** The entire window is contaminated exactly as the rule says it will be: it is *almost all my own traffic* — the flywheel go-live session (heavy verify-subagent fan-out) plus this very introspection session. The `top auto` list confirms it (`verify-as-claimed, session-handoff, experience-skill-concierge, skill-concierge:flywheel, come-clean …` — all mine). The `fallback 69%` is environmental (embed shim degrading to mandate-only while the detached reindex ran under load), NOT a design property — a shift that lines up with load, not a config commit. **Verdict: insufficient / contaminated data; the current epoch is too small and too self-dominated to conclude anything about real-user compliance.**

**5. What the layer does NOT touch — hit two boundaries live.**
(a) *Input correctness.* The layer picked the right skill every turn but did nothing to validate the *inputs* I fed it — same boundary the exemplar hit. (b) *A different governance layer stopped me.* On turn 1 I ended on a prose fork ("fire the generate, or something else?"); the **anti-confirmation Stop hook** blocked the turn and forced it into an `AskUserQuestion`. That is a separate user hook, **not** skill-concierge — worth naming precisely so the credit/blame lands right. skill-concierge governs *which skill*; it has no opinion on how I close a turn.

**6. My own process was the least reliable link — again.**
The turn-1 prose-fork miss above was mine, not the layer's: I named an action I could take and offered it as a chat question instead of committing or using the proper tool. The anti-confirm hook caught what my own self-check should have. Graded at the same bar I'd grade another agent: that is a real Anchor-4/anti-pattern-#22 slip on my part. My greps this session were clean (version + epoch boundary both verified first-try), so the sloppy part was decision-closure, not evidence-gathering.

## Net

v0.18.1 is live, health-green, and the library doctrine changed a real decision in my favor once this session (obs. 1). Two honest gaps stand: the preview under-retrieved the precise skill on a conversational meta-request (obs. 2), and the AUTHORIZED-SKIP getaway leg — the riskiest shipped change — got zero live exercise (obs. 3). The compliance ledger cannot be cited: this epoch is a self-dominated, load-contaminated window (obs. 4).

## Epoch comparison — 0.15.0 era vs 0.16.0-onward (broader windows)

Windowed as **two separate, non-overlapping epochs** (never one pooled rate — that would describe no real config, per the EPOCH-SCOPED rule). Boundaries from config commits: 0.15.0 `984ff78` (07-06 22:00), 0.16.0 retrieval-engine `4181d01` (07-08 09:45).

| Metric | **Epoch A — 0.15.0 era**<br>`[07-06 22:00 .. 07-08 09:45)` | **Epoch B — 0.16.0 onward**<br>`[07-08 09:45 .. now)` |
|---|---|---|
| turn-windows (n) | **201** | 48 |
| offers | 198 | 47 |
| uptake (turn used a skill) | 13% (27/201) | 25% (12/48) |
| substantive compliance | 23% (47/201) | 31% (15/48) |
| offered-turn conv (took an offered skill) | 10% (6/58) | 8% (1/13) |
| offered-turn dodge | 90% (52/58) | 92% (12/13) |
| hit@k | 44% (7/16) | 33% (1/3) |
| fallback rate (mandate-only) | 62% (122/198) | 70% (33/47) |
| AUTHORIZED-SKIP legs fired | **getaway 18 · intent_skip 6** | getaway 1 · intent_skip 0 |

**What the broader window actually buys (grounded reads, with the contamination caveat held throughout):**

**A. The AUTHORIZED-SKIP getaway leg is NOT unexercised in the wild — it fired 18× in the 0.15.0 epoch.**
Every single-session report so far (this one and the v0.12.0 exemplar) flagged the getaway leg as getting "zero live pressure." The 201-turn window refutes that at the population level: `bands: {getaway: 18, intent_skip: 6}`. The riskiest shipped change *does* fire on real workloads — it just never happened to fire on the handful of turns a focused session sees. This is the single most valuable thing the wider window surfaced.

**B. fallback stays 62%→70% across BOTH epochs — so it is environmental, not a design property of either config.**
Per rule 5 (design vs environment): a metric that does not move with a config commit is environmental. Fallback (mandate-only: embed shim down/slow) sits high in both epochs regardless of the retrieval change between them → it tracks *load* (the embed shim degrading during heavy dev/reindex sessions), not the code. It is NOT evidence that either config's retrieval is weak — it means the query path frequently fell back to mandate-only before retrieval even ran.

**C. uptake and substantive both rose A→B (13→25%, 23→31%) — suggestive, NOT concluded.**
The direction is up and it lines up with the 0.16.0 utterance-layer landing. But I will not call it "measured": (1) both windows are self/dev/subagent-dominated — `analyze.py --help` confirms there is **no session-exclude filter**, so I cannot strip my own turns mechanically, and the `top auto`/`top manual` lists are all dev traffic (doctor, setup, keep-on, session-handoff, cognee, verify); (2) Epoch B's offered-turn conv is n=13 — underpowered; (3) Epoch B itself spans 0.16.0→0.16.1→0.18.x, and the utterance layer was *unstable until 0.16.1's env-forwarding fix* — so B is a config-in-motion, not a settled state.

**Bottom line:** the broader range gives **real datapoints** (201-turn epoch A is a genuine sample), and it earns exactly two grounded conclusions — the getaway leg fires in the wild (A), and fallback is environmental across configs (B). The compliance *level* remains UNMEASURED for organic use (self-contamination, no filter). The A→B rise is a hypothesis to test on a clean window, not a result.

## Unresolved

- **Compliance rate for v0.16.1+ retrieval is still UNMEASURED** — needs a window of organic, non-self, non-subagent offered turns (the exemplar's ~50–100 organic offers). Every window since go-live is dominated by dev/verify sessions.
- **`fallback 69%`** — flag, not a defect: watch whether the embed shim keeps degrading to mandate-only outside heavy-reindex windows. If it persists on light real turns, the shim timeout (ADR-0008) needs a look; if it only spikes under reindex load, it's expected.
- **AUTHORIZED-SKIP getaway leg** — zero live exercise this session; addendum will force a trivial turn to test it.
- **Preview under-retrieval of `experience-skill-concierge`** — a single data point; not a bug, but a note that meta/introspection phrasings may not surface plugin-own skills without name-knowledge.

## Standing lens (committed)

For the rest of this session I keep watching the layer act on me. After ≥3 more real task-turns I append a LIVE ADDENDUM, deliberately routing at least one trivial/conversational turn so the AUTHORIZED-SKIP legs get live exercise — the surface single-session reports most often miss.
