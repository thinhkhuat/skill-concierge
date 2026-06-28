# BM25 Routing vs skill-concierge — Competitor Analysis + Replication Plan

**Type:** xia `--compare`+plan handoff · **Date:** 2026-06-28 00:08 · **Local target:** skill-concierge (v0.4.2)
**Source:** `FlorianBruniaux/claude-code-ultimate-guide` @ `11abfdbd4b7cd0ec4799979d9c1e19e788a9388e` · path `examples/hooks/`
**Method:** xia 6-phase (Recon→Map→Analyze→Challenge→Plan). Upstream files read verbatim (bm25 engine in full; 8 sibling bash hooks via research agent). Treated as untrusted data.

> **Implementation status — updated 2026-06-28 02:20.** **DONE + verified:** A1 negation guard, A2 %-share, C1 offers↔takes join, **B** freshness (stale→WARN), **C2** scenarios corpus (14 skills), **D** calibrator mechanism (`calibrate_thresholds.py`, dry-run; NOT wired live). C3 verified (§5). **Headline finding from D:** per-skill calibration only helps **5/14** skills — for the other 9 the mpnet cosine doesn't separate the right skill from siblings (4 are *inverted*); see §8 Q1. Remaining: **E**; D live-wiring deferred (helps only the 5 `ok` skills). Code shipped to the live plugin, not committed (workbench git-dir toggle).

---

## TL;DR (conclusion first)

The BM25 router is a **lexical competitor to skill-concierge's semantic router** — and skill-concierge already wins the axis that matters most to this user (cross-lingual EN↔VN matching, which pure lexical BM25 structurally cannot do). **So do NOT port the BM25 matcher.** But the upstream wraps that matcher in **6 matcher-agnostic engineering ideas skill-concierge lacks**, three of them directly attacking skill-concierge's two named open problems (manual reindex hygiene; the precision of its single global threshold). The highest-value borrows, ranked:

1. **Per-skill calibrated thresholds** (replace the one global `GETAWAY_FLOOR=0.20`) — biggest precision win. Adapt the *calibration idea* to skill-concierge's **ledger** data, not hand-authored corpora.
2. **Negation guard** in the enforcer — a real correctness **bug-class gap** (semantic embeds can't separate "use X" from "don't use X"); cheap fix.
3. **Self-healing staleness detection** (mtime/hash cache key + debounced background reindex) — closes the "reindex is manual" open item.
4. **Offered-but-not-taken logging** + **scenarios.json eval corpus** — supplies the *denominator* skill-concierge needs to measure dodge-rate (its stated #1 bottleneck).
5. **Confidence-as-%-share** presentation reframe.
6. (sibling hook) **identity-reinjection's conditional, transcript-aware re-injection on decay** — re-assert doctrine only when the transcript shows it decayed; targets compliance-decay directly.

Effort split: items 2, 5 are hours; 3, 4 are a day; 1 is the real project and should be **gated behind the compliance-measurement that is already skill-concierge's open question**. Full phased plan in §6–7.

---

## 1 · Source manifest

| | |
|---|---|
| Repo | `github.com/FlorianBruniaux/claude-code-ultimate-guide` |
| Commit | `11abfdbd4b7cd0ec4799979d9c1e19e788a9388e` |
| Scope | `examples/hooks/bm25-routing/` (engine) + `examples/hooks/bash/` (8 sibling hooks) |
| License | (verify before any code reuse — not captured this pass) |
| Deps | bm25-routing: **zero npm**, Node ≥16 builtins only (`fs`, `path`, `crypto`, `child_process`) |

bm25-routing anatomy:
- `bm25-suggest.js` — the UserPromptSubmit hook (entry point).
- `routing/bm25.js` — Okapi BM25 scoring core (`K1=1.2, B=0.3`).
- `routing/build-index.js` — index builder + **leave-one-out threshold calibrator**.
- `routing/tokenize.js` — EN+FR tokenizer (camelCase split, accent fold, stemmer, **negation detection**).
- `routing/paths.js` — path/env resolution.
- `skills-corpus/<skill>/evals/scenarios.json` — per-skill labeled positives/negatives.

---

## 2 · What the BM25 router actually is (grounded)

A `UserPromptSubmit` hook that scores each prompt against a hand-authored skill corpus with Okapi BM25 and injects `additionalContext` routing hints when a match clears a **per-skill calibrated threshold**. README:8 `bm25-routing/README.md`:

> "Each skill … gets a `scenarios.json` file with positive examples … and negative examples …. `build-index.js` … auto-calibrates a per-skill confidence threshold using leave-one-out cross-validation."

Output is identical in *channel* to skill-concierge's enforcer — additive `additionalContext`, non-blocking, exit 0 (`bm25-suggest.js:165`):

```json
{ "hookSpecificOutput": { "hookEventName": "UserPromptSubmit",
  "additionalContext": "BM25 routing hint:\n- /debug-tool (72%)\n- /code-review (28%)\nMultiple candidates, pick the one matching intent." } }
```

### The genuinely clever parts (verbatim evidence)

**(a) Per-skill threshold via leave-one-out cross-validation, recall-biased.** `build-index.js:79-92`:
```js
// beta^2 = 4 (beta=2): recall weighted 4x more than precision.
// We prefer to suggest and occasionally be wrong rather than stay silent when relevant.
const beta2 = 4;
const fbeta2 = ... (1 + beta2) * precision * recall / (beta2 * precision + recall);
```
Each positive is scored against the *rest* of its skill's positives (`scorePositiveAgainstSkill`, leave-one-out, `build-index.js:69-77`); threshold candidates are midpoints between observed pos/neg scores (`build-index.js:125`); τ maximizes F-beta²=4. Status `ok` only if plain `F1 >= 0.60`, else `conflict`; corpus < 8 pos or < 2 neg → `excluded` (`build-index.js:33-34, 143`).

**(b) Negation short-circuit.** `tokenize.js:18-20`:
> "Negation short-circuits routing entirely: negated prompts pass through because 'don't run /deploy' and 'run /deploy' would otherwise score identically."

`NEGATION_TOKENS` (EN+FR) set `negated=true`; `bm25-suggest.js:138` `if (tokens.length === 0 || negated) return passthrough();`.

**(c) Self-healing detached rebuild + atomic writes + mtime cache key.** Hook detects corpus newer than the index (`hasNewerScenarios` vs `manifest.built_at`, `bm25-suggest.js:90-102`), spawns a **detached, unref'd** background rebuild and passes the current turn through unblocked (`bm25-suggest.js:50-59, 132-134`). Builder writes `.tmp.<pid>` then `rename` (atomic, `build-index.js:210-214`); `cache_key` = SHA-256 over corpus paths+mtimes skips no-op rebuilds (`build-index.js:159-168, 186`).

**(d) Confidence = share of top scores** (relative, not absolute), `bm25-suggest.js:150-154`; README:11 is explicit it is "each skill's share of the combined top scores, not an absolute probability."

**(e) Best-single-match per skill** (max over positives, not sum) so large corpora don't win by volume — `bm25.js:10-11`, `bm25-suggest.js:110-111`.

---

## 3 · Head-to-head: BM25 router vs skill-concierge enforcer

Grounded in `hooks/scripts/enforcer.py` (read this session).

| Aspect | BM25 router (upstream) | skill-concierge enforcer | Edge |
|---|---|---|---|
| Match method | Okapi BM25 lexical (token overlap, IDF, stemming) | mpnet-768 embeddings + Qdrant cosine | — |
| **Cross-lingual** | ✗ lexical only; EN prompt can't hit a VN-only skill | ✓ EN query → VN-described skill, zero lexical overlap (enforcer.py docstring) | **skill-concierge** |
| Corpus source | hand-authored `scenarios.json` (10–15 pos, 3–5 neg)/skill | auto-indexed skill frontmatter/descriptions (495 skills) | **skill-concierge** (scale) |
| **Threshold** | **per-skill calibrated τ (LOO CV, F-β²=4)** | **single global** `GETAWAY_FLOOR=0.20` + `ITEM_FLOOR=0.18` | **BM25** |
| **Negation** | ✓ short-circuits on negation tokens | ✗ embeds raw prompt — "don't use X" ≈ "use X" | **BM25** |
| Confidence shown | ✓ %-share + "pick intent" note | raw cosine (compressed 0.18–0.40 band) | **BM25** (legibility) |
| **Index freshness** | ✓ self-healing detached rebuild on stale mtime | ✗ manual `reindex()` (open item) | **BM25** |
| Dependencies | zero npm, Node builtins | Docker (embed shim + Qdrant) + fastembed | **BM25** (footprint) |
| Latency | ~instant local lexical | ~100–250ms (needed threaded shim + 200ms cap) | **BM25** |
| Skip on `/cmd` | ✓ `bm25-suggest.js:124` | partial (MAX_SHORT_WORDS getaway only) | **BM25** (minor) |
| Blocking model | additive-only, exit 0, `timeout:2` | additive-only, fail-silent, never blocks | tie |
| Offer logging | smart-suggest sibling logs offers to JSONL | logs `offer` events to ledger (already has it) | tie |

**Read:** skill-concierge is correctly *ahead on the matcher* (semantic > lexical for this multilingual user). BM25 is *ahead on the operational envelope around the matcher* — threshold calibration, negation, freshness, legibility. Those are the borrows.

---

## 4 · Novel ideas extracted, classified

| # | Idea | vs skill-concierge | Action |
|---|---|---|---|
| 1 | Per-skill calibrated threshold (LOO CV, recall-biased) | **BM25 wins** — sc has 1 global floor it admits is a guess | **Adopt (adapt to ledger data)** |
| 2 | Negation guard (pass-through on negation tokens) | **Gap/bug** in sc — none | **Adopt (cheap)** |
| 3 | Self-healing staleness detection + atomic + cache-key | **BM25 wins** — sc reindex manual | **Adopt (debounced, not per-prompt)** |
| 4 | scenarios.json labeled corpus + offered-not-taken log | **Complementary** — gives dodge-rate denominator | **Adopt (curated subset + eval)** |
| 5 | Confidence-as-%-share + "pick intent" framing | **BM25 wins** legibility | **Adopt (presentation)** |
| 6 | identity-reinjection: conditional re-inject on transcript decay | **Gap** in sc — doctrine injected once at SessionStart | **Adopt (pattern; fix JSONL parse)** |
| — | BM25 lexical matcher itself | sc semantic already beats it cross-lingual | **Reject** |
| — | verification-gate (blocking PostToolUse certifier) | sc rejected this by design (anti-caveman) | **Reject** (concept-only) |
| — | velocity-governor (token-rate throttle, blocking sleep) | unrelated domain; fictional 500-tok estimate | **Reject** |
| — | learning-capture (Stop reflection prompt) | write-back unimplemented; ledger already does this | **Reject** |
| — | prompt-injection / unicode scanners | complementary security, out of sc's job; `grep -P` fails-open on darwin | **Reject for sc** (note as standalone) |

Design corroboration (not code): governance-enforcement-hook's "warn at SessionStart, audit periodically, never block" (`governance-enforcement-hook.sh:172-174`) and the hard-block-vs-warn tiering across the two scanners independently validate skill-concierge's in-generation/anti-caveman posture.

---

## 5 · Challenge phase (xia gate — trade-offs before plan)

| # | Challenge | Source's way | sc's way / reality | Risk if assumption wrong | Recommendation |
|---|---|---|---|---|---|
| C1 | Add BM25 as a parallel **lexical channel** (hybrid)? | pure lexical | pure semantic, already covers the multilingual case BM25 can't | hybrid doubles infra + maintenance for a channel that loses on the key axis | **No hybrid matcher.** Adopt the wrapper ideas only. |
| C2 | Per-skill thresholds from **hand-authored corpora**? | yes, scenarios.json/skill | 495 skills — hand-authoring per-skill corpora is infeasible | months of corpus authoring; never converges | **Calibrate from the ledger** (offer→take signal). scenarios.json only for a curated high-value subset + as eval truth. |
| C3 | Does semantic embedding **actually** fail on negation? | assumes lexical ties | **VERIFIED 2026-06-28**: yes — cos(affirm,neg)=0.65–0.87, mpnet barely moves on negation | a *broad* guard suppresses legit bug-report negations (3/4 in testing) | **✅ DONE → narrow guard.** Broad bm25-style rule refuted; shipped a guard anchored on negation + an invocation-meta verb only (see A1). |
| C4 | Port the **per-prompt detached rebuild**? | JSON file, cheap to rebuild | sc index is in Qdrant (Docker container) — rebuild is heavy, can race | per-prompt background reindex thrashes Qdrant / racey writes | **Adopt staleness *detection* (mtime/hash); trigger a *debounced* / doctor-driven reindex, not per-prompt.** |
| C5 | Is any of this worth it given the **open question** (does the gate lift compliance at all)? | n/a | sc's own #1 unknown | building calibration on an unproven gate | **Sequence it.** Ship cheap correctness wins (C3 negation, #5 presentation) now; gate the big calibration bet (#1) behind the compliance measurement already pending. |

**Risk score: MEDIUM-LOW.** All borrows are additive, fail-silent, and consistent with sc's existing contract (no new blocking surface). The one real risk is over-investing in #1 calibration before the gate's value is proven (mitigated by C5 sequencing).

---

## 6 · Replication plan — phased

> Not an implementation. Phases sized for `/ck:cook` handoff. Each item: what, files, effort, gate.

### Phase A — Cheap correctness + legibility (ship now, ~hours)
- **A1 · Negation guard** (idea #2) — **✅ DONE 2026-06-28.** C3 verified that mpnet ignores negation, but a broad any-negation rule over-suppressed **3/4** bug-report prompts. Shipped a *narrow* guard (`_REFUSAL_RE`): negation bound to an invocation-meta verb (`don't use/invoke X`, `without using X`, `skip …ing`) → mandate-only; bug-report negations untouched. `--selftest` 5 fire / 6 silent; verified end-to-end (ledger band `negation`).
  - Files: `hooks/scripts/enforcer.py`. ✅ implemented + verified.
- **A2 · Confidence-as-%-share + disambiguation note** (idea #5) — **✅ DONE 2026-06-28.** `_ranked_mandate` now shows each candidate's %-share of the shown score mass (only with 2+ candidates; a lone candidate is always 100% → omitted) + the disambiguation note; raw cosine dropped from the DISPLAY (still logged to the ledger). `--selftest` covers it; verified e2e.
  - Files: `hooks/scripts/enforcer.py`. ✅ implemented + verified.
- **A3 · Skip explicit `/slash` prompts** (minor) — **✅ ALREADY PRESENT** in `enforcer.py` (pre-gate `prompt.startswith("/")`); no work needed.

### Phase B — Freshness hygiene — **✅ DONE 2026-06-28**
- **B1 · Staleness detection** — **NOT NEEDED (already in the engine).** `skill-search --health` already tracks disk↔index drift (`"stale": true`, `dark_skills`, `indexed_at`); a new mtime/hash manifest would be redundant (DRY). The real gap was in `doctor.py`: a stale-but-serving index was classed **FAIL**. Fixed → **WARN** (exit 0) via `_stale_only()`, with index-age surfaced; `--selftest` covers 4 cases. Verified live (`[!] index stale (indexed 9h ago) — 495 indexed & serving`).
  - Files: `scripts/doctor.py`. ✅ implemented + verified.
- **B2 · Debounced reindex** — `doctor --fix` already runs `skill-search --reindex` (the human/cron-driven trigger). Per C4, per-prompt auto-reindex stays **rejected** (heavy/racey on Qdrant). No new code; existing path IS the debounced trigger.

### Phase C — Measurement substrate (enables the big bet, ~1 day)
- **C1 · Offered-but-not-taken accounting** (idea #4) — **✅ DONE 2026-06-28.** Added `_offer_conversion()` to `analyze.py`: offered-turn conversion + per-skill offer→take rollup + `--selftest`. First read: **offered-turn dodge 78/85 = 92%** (agent improvised even when a fitting skill was offered) — the "compliance is the bottleneck" thesis quantified. ⚠ on a **CONTAMINATED** ledger (this + prior meta-sessions); the instrument is built, the clean number needs `analyze.py --since <clean-window>`.
  - Files: `scripts/analyze.py`. ✅ implemented + verified.
- **C2 · scenarios.json eval corpus** (idea #4) — **✅ DONE 2026-06-28.** Authored 14 distinct-intent skills × (12 pos / 5 neg), 2 Vietnamese positives each, contrastive negatives drawn from sibling skills; all 14 skill-ids verified against the live index.
  - Files: `eval/scenarios/*.json` (14). ✅ authored + validated.

### Phase D — Per-skill calibration — **⚙ MECHANISM DONE 2026-06-28; live-wiring deferred**
- **D1 · Calibrator built** (idea #1, adapted). `scripts/calibrate_thresholds.py` scores each corpus prompt by its **real cosine to the skill's indexed vector** (== live retrieval, no LOO proxy needed), picks τ via F-β²=4, and classifies each skill by honest **separation** (`pos_mean − neg_mean`), not F1. `--selftest` + `--dry-run`; writes `eval/thresholds.json`. NOT wired into the enforcer (deliberate).
  - **🔑 Finding (decision-critical):** of 14 skills, **5 ok · 5 weak · 4 no-signal**. Only distinctive-vocabulary skills separate (vn-author 0.30, supabase 0.18, security-scan 0.12, media 0.11, tdd 0.10). Generic dev skills don't — 4 are **inverted** (negatives out-score positives: payment, debug, deep-research, ai-artist). **F1 was 0.83–1.0 for all 14** → F1 alone is a trap; separation is the honest signal. A naive bm25-style F1 gate would have "passed" all 14.
  - **Implication:** per-skill τ is worth wiring live for the **5 `ok` skills only**; for the other 9 **no threshold helps** — the lever is the index/embedding content (richer per-skill descriptions), not calibration. This partially challenges "retrieval isn't the bottleneck": for ~⅔ of common skills, retrieval discrimination IS weak.
  - Files: `scripts/calibrate_thresholds.py`, `eval/thresholds.json`. Live-wiring (`enforcer.py` per-skill τ lookup) = next deliberate step, scoped to `ok` skills.

### Phase E — Doctrine-decay re-injection (sibling-hook borrow, independent track)
- **E1 · Conditional re-injection on decay** (idea #6, from `identity-reinjection.sh`). A UserPromptSubmit/SessionStart check: read the transcript, test whether the SKILL-FIRST doctrine marker is still present in recent context; if decayed (post-compaction), re-inject the doctrine. Additive-only, fail-silent.
  - Files: `hooks/scripts/doctrine.py` (or a new `hooks/scripts/redoctrine.py`).
  - **Caveat:** upstream's jq selector assumes a JSON array; Claude Code transcripts are **JSONL** — fix the parse (slurp/stream) before reuse. Borrow the *pattern*, not the selector.

---

## 7 · What NOT to absorb (explicit)

- **The BM25 lexical matcher** — semantic already beats it on the multilingual axis that is this user's whole reason for going semantic. Adopting it is a regression dressed as a feature.
- **verification-gate.sh** — the exact blocking PostToolUse certifier sc rejected by design; also `eval "$cmd"` on an env-overridable string is a smell.
- **velocity-governor.sh** — unrelated (API rate-limit), fictional flat 500-token estimate, blocking inline `sleep` that stalls the session opaquely.
- **learning-capture.sh** — write-back unimplemented (vaporware loop); ledger+analyze already capture more, automatically.
- **prompt-injection / unicode scanners** — good *standalone* hardening but out of sc's job; both rely on `grep -P`, **absent on stock macOS BSD grep → silently fail-open** on this darwin host.

---

## 8 · Open questions / unresolved

1. **Upstream license** not captured this pass — verify before any code reuse (README implies MIT-spirit guide, but confirm the repo LICENSE).
2. ~~**C3 unverified**~~ — **RESOLVED 2026-06-28:** verified — mpnet cosine does NOT separate negation (cos 0.65–0.87). Fix refined to a *narrow* guard (a broad rule over-suppresses bug reports). A1 shipped + verified.
3. **🔑 NEW (from D, 2026-06-28) — semantic discrimination is weak for ~⅔ of skills.** Per-skill calibration showed only 5/14 skills have cosine separation strong enough for a usable τ; 4 are inverted. No threshold fixes the other 9 — the lever is the **index/embedding content** (the skill's indexed vector for generic dev skills isn't distinctive). **VALIDATED 2026-06-28 (held-out test):** enriching a skill's indexed vector with its trigger phrases (the C2 positives) improves separation on **14/14 skills, 0 regressions** — flipping all 4 inverted skills strongly positive (debug −0.060→+0.245, plan +0.228, ai-artist +0.220) and lifting even the already-`ok` skills (vn-author 0.314→0.374). This is THE lever (bm25's real insight: index the scenarios, not the description); D thresholds are marginal beside it. **Shadow PoC (end-to-end, 495-way retrieval, held-out, no live/vendored change):** with the 14 skills enriched in a `claude_skills_shadow` collection, the correct skill went rank-1 **12%→90%**, top-5 29%→100%, clears-0.20-floor **37%→100%**, mean score 0.344→0.615; precision cost is small (a skill wrongly topping its own contrastive negatives 1/70→5/70). **Implication: the ~92% dodge is substantially a RETRIEVAL failure, not only compliance** — the live router surfaces the right skill at the floor only 37% of the time. Open: source trigger phrases for the other 481 skills (auto-gen from SKILL.md / LLM-expand / harvest), then whether to modify the vendored indexing path & go live.
4. **The project's own open question (still open):** does the SKILL-FIRST gate lift compliance at all? C1 supplies the *instrument* (offered-turn conversion); the contaminated ledger reads ~92% dodge, but a clean workload window on v0.4.1+ is still required. Phase D live-wiring stays gated on this.
4. **identity-reinjection JSONL parse** (E1) is environment-specific and unverified against real Claude Code transcripts.
5. Whether a curated scenarios corpus (C2) is worth the authoring cost vs. pure ledger-derived signal (C1) — decide after C1 shows whether ledger data alone is dense enough.

---

## 9 · Handoff

Source manifest, anatomy, dependency/decision matrices, risk score (MEDIUM-LOW) all above. This is a `--compare`+plan deliverable; **no code written**. To implement a phase:

```
/ck:cook  <this report> — Phase A + C1 DONE; next is Phase B (freshness) or D (calibration, gated).
```

Recommended order: ~~A → C1~~ **(✅ done)** → **B → (clean-window compliance measurement) → D**, with **E** as an independent parallel track. Phase D is explicitly gated on the compliance measurement.
