# D2 — OVER-ENGINEERING AUDIT (ponytail / KISS lens)

**Question:** what did skill-concierge ADD that a senior engineer would call bloat or a net-negative vs
the lean `skill-search` 0.1.0 OG? Yardstick: YAGNI / KISS / DRY.
**Constraint:** READ-ONLY. Nothing modified. All evidence is file:line from the fork tree
(`/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge`) or the vendored OG (`vendor/skill-search/`).
**Date:** 2026-07-04 · **Author:** D2 auditor (first-hand reads + live-ledger telemetry).

Verdict key: **DELETE** (remove, no measured value) · **SIMPLIFY** (keep intent, cut machinery) ·
**REVERT** (return to the data-backed / OG operating point) · **KEEP** (complexity is earned).

Bottom line up front: the fork is **~4,000 LOC of scripts/hooks** (`wc -l scripts/*.py hooks/scripts/*.py`
= 4,016) on top of an OG whose whole engine is four files. A large slice of that is either **provably
never-executed** (the inert graveyard) or **bypassed on the majority of live turns** (the enforcer's
semantic half). The single most damning number in this audit is not a LOC count — it is that the fork's
heaviest infrastructure bet is dead on **63% of recent turns**.

---

## THE HEADLINE FINDING (frames everything below)

**The enforcer's semantic-retrieval half — the sole reason the fork runs a warm embed shim + Docker
Qdrant server + a +60%-inflated multi-vector index in the per-turn hook path — is bypassed on ~63% of
recent turns.**

- Live ledger `~/.claude/skill-telemetry/logs/skill-invocation-ledger.log`, most-recent 150 offer-events:
  band = `{offer: 42, fallback: 94, intent_skip: 5, getaway: 6, negation: 3}`; **all 94 fallbacks are
  `embed_timeout`** (= 63% of recent offer-events). Over the full ledger: 167 of 583 offer-events (29%)
  are `embed_timeout` — so the rate is *worsening*, not improving.
- The enforcer's own comment (`hooks/scripts/enforcer.py:56-62`) documents the "fix": a threaded shim +
  relaxed 200ms budget was shipped *because* "~60% of turns hit embed_timeout." The live ledger shows the
  threaded-shim fix **did not hold** — recent turns time out at the same ~63%.
- On every one of those 94 turns the entire retrieval stack (shim → Qdrant → MAX-pool query) is skipped
  and the hook emits the plain `MANDATE` string (`enforcer.py:254-260`, path `481-484`). **A 10-line
  stdlib hook with zero infrastructure produces the identical output.**

This is the KISS crux: the fork pays the full operational cost of the semantic machinery (Docker, sidecar,
768-dim multilingual index, calibration) but delivers the semantic offer on barely a third of turns. The
complexity is not paying rent where it is most expensive to carry.

---

## RANKED CANDIDATES

### 1. The DEFAULT-INERT graveyard — five features shipped/wired/tested/documented but PROVABLY NEVER FIRED → **DELETE / SIMPLIFY**

The fork ships five features permanently OFF. The live ledger proves **none has ever executed a single
production code path**:

| Feature | Wiring | Cost carried while OFF | Ever armed? (evidence) |
|---|---|---|---|
| Per-skill τ | `enforcer.py:158-189` (~32 LOC) + call `512-514` + selftest `637-661` + data file `eval/thresholds.json` (14 entries) + generator `scripts/calibrate_thresholds.py` (240 LOC) | ~272 LOC + a JSON corpus | **No** — no `ENFORCER_PER_SKILL_TAU` in `~/.claude/settings.json`, shell, or `hooks.json`. Its own header (`enforcer.py:162-166`) admits arming it *lowers* the bar and *adds* the false-offers ADR-0009 tuned against. |
| Deterministic routes | `enforcer.py:192-233` (~42 LOC) + call `505-507` + selftest `652-659` + `config/deterministic-routes.json` (`"routes": []`) | ~50 LOC + empty config | **No** — 0 offer-events ever carried a score-1.0 deterministic hit (ledger scan). Config ships empty by its own instruction. |
| Runner-up-gap dominance collapse | `enforcer.py:236-245, 372-379` (~20 LOC) + call `534` + selftest `618-635` | ~40 LOC | **No** — no `ENFORCER_DOMINANCE_RATIO` set. Header (`enforcer.py:238-240`): "no evidence collapsing improves conversion; fires only ~5%." |
| Keep-off offer-suppression | `enforcer.py:130-155` (~30 LOC) + call `499-500` + selftest `610-616` + `config/keep-off.json` (`"keep_off": []`) + generator `scripts/build_keep_off.py` (132 LOC) | ~170 LOC + empty config | **No** — 0 offer-events ever carried a `dropped` field (ledger scan). Generator ran once, produced `[]`. |
| Legacy MEAN `enrich_index.py` | `scripts/enrich_index.py` (324 LOC) | 324 LOC, superseded | **Must-not-run** — superseded by v0.12.0 body-triggers; its own header (`enrich_index.py:3-8`) marks it a reverse-engineered Phase-1 MEAN recipe. A dormant `--live` mutator that "upsert → skills go dark → doctor FAILs" (`enrich_index.py:22-25`) is a live footgun. |

**Aggregate dead weight:** roughly **140 LOC of inert branches inside the 715-line enforcer** (plus their
selftest scaffolding, which is ~half of `_selftest`), **~700 LOC of supporting scripts**
(`calibrate_thresholds` 240 + `build_keep_off` 132 + `enrich_index` 324), two permanently-empty config
files, and a 14-entry `thresholds.json` corpus. All of it carries maintenance, re-vendor-reapply, and
cognitive cost on **every** read of the enforcer, and none of it has moved a single production decision.

**Why it degrades vs the OG:** the OG has exactly one gate (name-only override + on-demand top-k) and no
opt-in levers at all. Optionality is not free — every `if not os.environ.get(...)` branch is a thing a
maintainer must read, test, and reason about the interaction of (the enforcer's `main()` now threads
keepoff → routes → per-skill floor → dominance in sequence, `enforcer.py:499-534`, four inert stages in the
hot path). This is textbook premature abstraction (anti-pattern #8): machinery built for a future that the
authors' own headers admit the data does not support yet.

- **DELETE now:** `enrich_index.py` (superseded footgun), `build_keep_off.py` + `config/keep-off.json`
  (never produced a non-empty set), the dominance-collapse branch (no hypothesis it helps).
- **SIMPLIFY:** collapse per-skill-τ + deterministic-routes to a single documented note ("levers considered,
  data said no — see ADR-0009") and drop the code + `calibrate_thresholds.py` + `thresholds.json` until a
  substrate change actually lifts separation. Keeping the *decision record* is cheap; keeping the *inert
  code* is not.

Honest counter-weight: every branch is fail-open and cannot break a turn (`enforcer.py:139-144, 172-180`),
and the selftests do pin them. So the graveyard is **inert, not dangerous** (except `enrich_index --live`).
But "harmless dead code" is still dead code — YAGNI says delete it, not gold-plate it with tests.

---

### 2. Two decisions shipped AGAINST their own recorded data → **REVERT (or split the flag)**

The fork twice overrode its own evidence, and both overrides sit in the live hot path:

- **`GETAWAY_FLOOR = 0.45`** (`enforcer.py:66`). The inline comment and ADR-0009 (`docs/adr/0009:16-20`)
  both state the analysis argued *against* it: cosine is anti-correlated with adoption (taken offers median
  **0.414 < dodged 0.457**), so raising the floor from 0.40→0.45 removes "3 of 6 adopted offers (50%)" vs
  "20 of 91 noise (22%)" — surviving take-rate *falls* 6.2%→4.1%. The fork raised the bar on the better-
  converting offers, on "perceived behaviour the telemetry may under-capture" (`adr/0009:26`).
- **AUTHORIZED-SKIP getaway leg shipped ON** (`enforcer.py:78`, ADR-0015). The proposal recommended the
  getaway leg **default-OFF** pending a post-multi-vector re-measurement precisely because of the same
  anti-correlation; "the operator explicitly overrode this and directed BOTH legs ON now"
  (`adr/0015:42-50`). ADR-0015's own "Open" section (`:65-71`) says the prerequisite measurement is **still
  open** and there is "no live offered-turn adoption A/B yet."

**Why this is an over-engineering / degradation smell:** shipping a knob *against* the only data you have,
then adding a second layer (authorized-skip) that *also* fires on that same un-remeasured floor, compounds
an unproven bet. The getaway leg fired 57 times in the ledger (6 recent) — every one authorized a skip on
the exact low-score band where ADR-0009 says real adopted work lives. This is not added *capability*; it is
added *risk* dressed as governance.

- **REVERT:** set `GETAWAY_FLOOR` default back to 0.40 (one-line, env-overridable — `adr/0009:31-32`), OR at
  minimum split `ENFORCER_AUTHORIZED_SKIP` per leg and turn the getaway leg OFF until the prerequisite
  measurement ADR-0015 itself demands is done. The intent-margin leg (data-supported) can stay.
- Fair defense: both are one-env-var reversible and fail-open, and the operator legitimately owns the UX
  trade-off (review-audit rule: don't silently undo a user decision). So this is a **flag to reopen with the
  owner**, not a unilateral delete. But the audit's job is to say plainly: the data points the other way.

---

### 3. The 715-line enforcer + the whole in-generation governance layer vs the OG's ZERO enforcement → **KEEP the core idea, SIMPLIFY the apparatus**

The OG has *no* enforcement layer — it frees the skill budget and answers `search_skills` on demand
(README:141-149). The fork adds an entire per-turn governance organ: enforcer (715 LOC) + SessionStart
doctrine injection (`hooks/doctrine/skill-first.md`, `doctrine.py` 67 LOC) + append-only ledger
(`ledger.py` 93 LOC) + `analyze.py` (305 LOC) + actionability gate (912-prompt `prompt_intent` corpus via
`build_prompt_intent.py` 227 LOC) + a VN imperative lexicon (`enforcer.py:108-123`).

**Where it is EARNED (KEEP):**
- The **mpnet multilingual swap** is a genuine improvement — it fixes a real EN-query→VN-skill recall miss
  the OG's bge-small-en could not (README:52-54 fork delta). Not bloat.
- The **VN imperative lexicon** (`enforcer.py:114-123`) is the language-aware half of that same fix, and its
  selftest exercises real VN prompts (`enforcer.py:588-608`). Earned.
- **Fail-silent, additive-only, stdlib-only** hook contract (`enforcer.py:12-16`) is disciplined and
  correct — it cannot block a turn.

**Where it is NOT earning its complexity (SIMPLIFY):**
- Per finding #1, **63% of recent turns never reach retrieval** — so on the majority of turns this 715-line
  file collapses to "emit the MANDATE string." That is a ~15-line hook wearing a 715-line coat.
- The actionability gate is a two-class kNN over a 912-prompt corpus (`enforcer.py:431-452`) that fires
  `intent_skip` on only 19 of 583 offer-events (3%). A 912-prompt corpus + a `build_prompt_intent.py`
  generator + a second Qdrant collection (`prompt_intent`) to change 3% of verdicts is a heavy apparatus for
  a thin effect — candidate to fold into the cheap `_is_imperative` lexical veto that already runs first.
- The whole layer rests on an **unproven premise** — that the model will not skill-first without a per-turn
  tax. The fork has *no* valid retrieval or adoption benchmark on its own universe (handover `:83-85`;
  ADR-0015 "no live A/B yet"). So the central bet is un-measured; the machinery is an act of faith, and its
  size should match the confidence, which is currently low.

Verdict: **KEEP** the SKILL-FIRST idea and the multilingual retrieval; **SIMPLIFY** the enforcer by deleting
the inert stages (finding #1) and consider demoting the actionability gate to the lexical veto until a
benchmark justifies the corpus.

---

### 4. 16 ADRs + Docker + shim + stable-venv + calibration scripts as operational surface → **mostly KEEP, but some doesn't pay rent**

- **Docker Qdrant server + warm embed shim + stable venv** (fork delta A, README:55-58; ADR-0004): this is
  the biggest departure from the OG's *service-free* default (embedded on-disk Qdrant + local ONNX, no
  Docker — vendor README:159-163). The fork's justification is concurrent sessions + the 768-dim model. That
  is a **defensible lateral trade** for a multi-session power user — but finding #1's 63% embed_timeout says
  the shim, the very component added to make this fast, is the bottleneck. The ops cost is real and the
  payoff is leaking. (D4 owns the full cost/benefit; from the KISS seat: the service-free default was a
  genuine OG virtue and the fork lost it — flagged, not scored here.)
- **16 ADRs** are, unusually, **NOT bloat** — they are the *cheapest* artifact in the repo. Every against-
  data decision in finding #2 is auditable *only because* the ADRs exist. A decision record costs one file
  and pays for itself the moment someone asks "why 0.45?" Keep them.
- **Calibration harnesses that feed inert features** (`calibrate_thresholds.py`, `build_keep_off.py`) inherit
  finding #1's verdict — they generate data for levers that never fire. **DELETE with the features they
  serve.**
- **`multivector_experiment.py` (439 LOC) + `precision_eval.py` (161 LOC)** are dev-time experiment scaffolds
  living in `scripts/`, not wired into any hook or the doctor. Fine as throwaway research, but they are the
  largest single script and add to the "what is all this?" tax. **SIMPLIFY:** move to a `research/` or
  archive dir so the operational surface reads clean.

---

## SUMMARY TABLE (ranked, most-negative first)

| # | Thing | Surface cost | Verdict | Anchor |
|---|---|---|---|---|
| 1 | Inert graveyard (5 features, never fired) | ~140 LOC in enforcer + ~700 LOC scripts + 2 empty configs | **DELETE / SIMPLIFY** | `enforcer.py:130-245,499-534`; ledger scan = 0 hits |
| — | *(cross-cut)* semantic half bypassed 63% of recent turns | full shim+Qdrant+index cost, no output | **SIMPLIFY** | ledger last-150 = 94 embed_timeout; `enforcer.py:56-62` |
| 2 | `GETAWAY_FLOOR=0.45` + authorized-skip getaway leg, both against own data | 2 hot-path knobs | **REVERT / split flag** | `enforcer.py:66,78`; ADR-0009:16-20; ADR-0015:42-71 |
| 3 | 715-line enforcer + governance layer on unproven premise | 715 + 67 + 93 + 305 + 227 LOC | **KEEP core, SIMPLIFY** | `enforcer.py`; handover:83-85 (no benchmark) |
| 4 | Ops surface: Docker/shim/stable-venv, 16 ADRs, experiment scripts | service-free default lost; 600 LOC of experiments in `scripts/` | **KEEP ADRs; SIMPLIFY scripts; flag service-free loss** | README:55-58; `multivector_experiment.py`, `precision_eval.py` |

**Earned complexity, explicitly defended (NOT bloat):** the mpnet multilingual embedder swap + VN
imperative lexicon (fixes a real recall miss), the fail-silent/additive hook contract, the curated 31-skill
`keep-on` override (the OG's core idea, kept), and the 16 ADRs (cheapest, highest-leverage artifact here).

---

## Unresolved / honest caveats

- **Ledger attribution:** the 63% `embed_timeout` is real in the log, but I did not instrument *why* the
  threaded shim regressed (CPU contention vs the +60% index growth vs cold-starts). The number is solid; the
  root cause is D3/D4's to pin. It does not change the KISS verdict (the machinery is bypassed regardless of
  cause).
- **"Never armed" is proven for the two ledger-observable features** (deterministic routes = 0 score-1.0
  hits; keep-off = 0 `dropped` fields) and **inferred** for per-skill-τ / dominance (no env flag anywhere in
  settings/shell/hooks.json). I could not rule out a one-off manual `export` in a past shell session, but no
  persisted trace exists.
- **Findings #2 is a user/operator decision** (per review-audit rules) — the audit recommends REVERT but the
  owner holds the call; this is a flag-and-reopen, not a unilateral delete.
- No retrieval-quality benchmark exists on the fork's universe, so #3's "unproven premise" is a structural
  gap, not a measured regression. D3 must say what benchmark would settle it.

---

**Status:** DONE
**Summary:** The fork's worst KISS sins are a ~840-LOC inert-feature graveyard that the live ledger proves
never fired, and a semantic-retrieval stack that is bypassed on 63% of recent turns (embed_timeout) — the
heaviest infrastructure delivering the OG-plus-nothing plain mandate most of the time. The mpnet
multilingual swap and the ADRs are earned; the against-data gate knobs should be reverted with the owner.
**Top-3 delete/simplify:** (1) DELETE the inert graveyard — `enrich_index.py`, `build_keep_off.py` +
`keep-off.json`, dominance-collapse, and demote per-skill-τ/routes to an ADR note; (2) SIMPLIFY the enforcer
around the 63%-timeout reality (the semantic half rarely runs); (3) REVERT `GETAWAY_FLOOR` to the
data-backed 0.40 and split the authorized-skip flag to turn the getaway leg OFF.
