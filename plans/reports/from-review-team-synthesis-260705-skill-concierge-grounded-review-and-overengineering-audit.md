# skill-concierge — consolidated grounded review + over-engineering audit

Synthesis of a 4-agent review team (2026-07-05). Every finding below traces to a per-surface
report + the underlying `file:line`. Correctness and over-engineering are kept in **separate
sections** — they are different lenses and were owned by different agents.

Source reports:
- A — gate: `plans/reports/review-260705-enforcer-gate.md`
- B — retrieval: `plans/reports/review-260705-retrieval-engine.md`
- C — ops: `plans/reports/review-260705-ops-maintenance.md`
- D — ponytail: `plans/reports/audit-260705-ponytail-overengineering.md`

Grounding standard held across all four: `file:line` + verbatim quote on every claim; unverifiable
items flagged `UNVERIFIED`, not derived. Three findings were **independently reproduced by execution**
(not just read), marked ⚑ below.

---

## Headline — one cut resolves a bug AND the biggest bloat

The **deterministic-routes** feature was flagged by three independent agents from three angles:
- **A (correctness):** a keep-off'd "chronic never-take" skill (ADR-0011) can resurface at score `1.0`
  and bypass both gates if an operator also configures a matching route — `enforcer.py:220-233`. ⚑ reproduced.
- **D (over-engineering):** the same feature is dead-by-default `yagni` — its config
  `config/deterministic-routes.json` ships permanently empty.
- **C (ops):** independently noted that empty config as inert/opt-in.

Deleting the unarmed feature (D-1) **also eliminates** the gate bypass (A-1). Same line-range, one action.

---

## Correctness / fidelity findings — ranked across all surfaces

| # | Sev | Finding | Where | Repro |
|---|-----|---------|-------|-------|
| 1 | 🔴 | Vendored integration test **fails** against the shipped `MULTIVECTOR` default — asserts `embedded == indexed` (488 == 3570). ADR-0016 calls it "deselected" (benign); a plain `pytest tests/` actually **fails**. Real test/prod drift logged as a skip. | `vendor/skill-search/tests/test_indexing.py:92-95` (B) | ⚑ live pytest |
| 2 | 🔴 | `analyze.py` offer→turn join keys on `(sid, prompt[:120])` with plain dict overwrite. Two turns in one session sharing a 120-char prefix (a retried "continue") misattribute offers to whichever was last — silently corrupting `hit@k` / conversion / per-skill offer→take. Undermines the very telemetry the audit apparatus exists to produce. | `scripts/analyze.py:206,228-233` (C) | traced |
| 3 | 🟡 | Keep-off (ADR-0011) bypassable by a co-configured deterministic route → resurfaces at `1.0`, bypasses getaway + actionability gates. Narrow blast radius (both features opt-in/off by default), untested in combination. | `hooks/scripts/enforcer.py:220-233` (A) | ⚑ direct exec |
| 4 | 🟡 | `doctor.py`'s `fix_reapply` lacks the `MULTIVECTOR` guard `fix_reindex` has → a future `doctor --fix` could MEAN-corrupt live base vectors (the self-heal tool becoming the corruption vector). Dormant today (`enriched=0` on live probe). | `scripts/doctor.py:492-514` (B) | code + live probe |
| 5 | 🟡 | `doctor.py` docstring claims "Read-only by default" but `check_ledger()` unconditionally `mkdir`s the log dir on every plain run. | `scripts/doctor.py:358-365` vs `:10` (C) | traced |
| 6 | 🟡 | Embed-shim Docker sidecar has **no freshness check** parallel to `check_engine_freshness`; `setup.sh` skips rebuilding it if already listening → can serve stale code/model after a plugin update indefinitely, nothing turns red. | `setup.sh:58-72` vs `doctor.py` CHECKS (C) | traced |
| 7 | 🟡 | `driftcheck.py` catches broad `Exception` for SSOT extraction but only `FileNotFoundError` for mirror checks → a malformed mirror regex/missing key crashes the whole run instead of reporting one drift. Not currently triggered (live config well-formed). | `scripts/driftcheck.py:111-124` (C) | traced |
| 8 | 💭 | `≤3`-word pre-gate is a third silent no-op path outside ADR-0015's "two legs" framing — intentional, doc-clarity gap only. | `enforcer.py:468-469` (A) | — |
| 9 | 💭 | `check_qdrant` labels a never-created container "stopped" (`docker ps` lacks `-a`) — cosmetic. | `doctor.py:100-106,214-225` (C) | — |
| 10 | 💭 | Two "skill catalogue" SSOTs: `apply-overrides.py` uses disk-discovery, `analyze.py` uses live Qdrant — can diverge. | `apply-overrides.py:34-42` vs `analyze.py:59-86` (C) | — |
| 11 | 💭 | `VENDORED.md`'s ADR-0012 attribution to `skills_discovery.py` unverifiable from current source — imprecise provenance, no behavior misrepresented. | `VENDORED.md:37-38` (B) | UNVERIFIED |

---

## Over-engineering (ponytail — complexity lens only, kept separate)

1. `yagni:` Three unarmed retrieval knobs in the per-turn hot path — per-skill tau (`enforcer.py:158-189`),
   deterministic routes (`:192-233` + empty `config/deterministic-routes.json`), P6 dominance-collapse
   (`:236-245`). Each fully wired with loader + selftest but the code's own comments say arming would
   *worsen* results or shows no benefit. Cut these + `calibrate_thresholds.py` (241 lines, feeds the
   never-armed tau) + `doctor.py:439-465` `check_corpus_health`. **~90 lines of always-false conditionals
   in the hottest hook + a 241-line dead-end script.**
2. `shrink:` Same urllib POST/GET/PUT/DELETE wrapper hand-rolled 6× across `scripts/` (enrich_index,
   build_prompt_intent, build_triggers, calibrate_thresholds, precision_eval, multivector_experiment).
   One shared `scripts/_qdrant_http.py` → **−70 to −90 lines.**
3. `shrink:` `cosine()` duplicated verbatim (enrich_index / calibrate_thresholds); `rank_of()` duplicated
   verbatim (multivector_experiment / precision_eval). Fold into the same helper → **−15 to −20 lines.**
4. `yagni:` `driftcheck.py` (168 lines) built as a "drop into any repo" framework but has one caller and
   one fact family — and its two hardest checks hand-roll their own diff instead of using it.
5. `delete:` `config/deterministic-routes.json` — permanently-empty stub (dead config for #1).

**net: ~−175 to −200 lines possible, 0 deps.** Vendored `server.py` skimmed and left alone (ADR-backed,
not this repo's to cut).

---

## What's verified solid (don't touch)

- **Fail-silence contract holds** across all three governance hooks — every exit path traced, no block/
  exit-2 path exists, empirically confirmed via `enforcer.py --selftest` (exit 0). (A)
- **AUTHORIZED-SKIP tier matches ADR-0015 exactly** — flag default (ON, `=0` reverts), `SKILL-CHECK:`
  marker literal, both message bodies, and the cross-file contract with `audit_skill_usage.py` all
  byte-matched. (A + C both traced the two sides.)
- **Telemetry `authorized_skip` separation verified TRUE** — `audit_skill_usage.py:106-126` buckets it
  distinctly, never into `false_skip`; marker anchors match `enforcer.py:312-320` verbatim. (C)
- **ADR-0016 body-trigger patch** present, correctly logged in `VENDORED.md`, live index numbers match
  claim (3570 points, +60%, `enriched=0`). (B, live read-only probe)
- **Epoch-scoping** is a documented human/agent discipline, not a code invariant — consistent with how
  AGENTS.md itself frames it. Not a gap. (C)

---

## Evidence quality + honest gaps

- All four agents grounded (file:line + quote). Reproduced-by-execution: #1 (live pytest), #3 (direct
  function exec), + live Qdrant probe for #4/B-context.
- **UNVERIFIED (flagged, not derived):** harness hook→transcript plumbing that surfaces the `SKILL-CHECK:`
  marker (A); `SKILL_BODY_TRIGGERS=0` byte-identity (B); real upstream `skill-search` diff — assessed only
  against this repo's own VENDORED.md self-report (B); live duplicate-prompt ledger repro for #2 (C wants a
  second pass).
- Not read (out of scope): `build_keep_off.py`, `embed_server.py` internals, `enrich_index.py` end-to-end
  math, `skills_discovery.py` by A/C.

## Suggested order of action (advisory — nothing applied)

1. **Delete the unarmed deterministic-routes feature** — kills correctness #3 and bloat #1's config in one move.
2. **Fix the `analyze.py` join (#2)** — it corrupts the audit numbers the whole project reasons from; add a
   collision-safe key (append event index) before trusting any post-change metric.
3. **Fix the two vendored-fidelity items (#1, #4)** — correct the integration-test assertion (or run CI with
   `-m "not integration"` explicitly) and add the `MULTIVECTOR` guard to `fix_reapply`.
4. Robustness clean-ups (#5–#7) and ponytail shrinks (#2/#3) as lower-priority housekeeping.
