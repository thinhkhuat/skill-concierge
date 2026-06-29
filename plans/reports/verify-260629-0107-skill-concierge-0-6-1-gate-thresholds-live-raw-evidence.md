# Independent verification — skill-concierge 0.6.1 gate thresholds (LIVE)

**Verifier:** independent (did not build this change). **Date:** 2026-06-29.
**Claim under test:** commit `6995fd8` bumped skill-concierge to 0.6.1; the active enforcer carries
`MAX_SHORT_WORDS = 5` and `GETAWAY_FLOOR` default `0.45` (ADR-0009), deployed == committed source,
and the gate behaves per its documented contract at the new thresholds.

**VERDICT: GO.** (A) values live + deployed==committed source: PROVEN. (B) runtime behavior at 5 / 0.45: PROVEN.
All evidence below is raw bytes from the live system. The active artifact was driven exactly as the
harness drives it (stdin JSON → stdout + ledger side effect); the real ledger was never touched
(fresh temp `SKILL_CONCIERGE_LOG` per case).

---

## STEP 1 — deployed artifact (raw evidence)

### 1a. Which enforcer the harness loads (authoritative record)
`~/.claude/plugins/installed_plugins.json`, key `plugins["skill-concierge@skill-concierge"]`:
```
[{"scope": "user",
  "installPath": "/Users/thinhkhuat/.claude/plugins/cache/skill-concierge/skill-concierge/0.6.1",
  "version": "0.6.1",
  "installedAt": "2026-06-26T06:44:59.002Z",
  "lastUpdated": "2026-06-28T18:07:29.205Z",
  "gitCommitSha": "6995fd8d05ee32f2e41a9655414c798967a8c24f"}]
```
→ active installPath = cache `0.6.1`; recorded version 0.6.1; recorded commit `6995fd8` (matches claim).

Enabled flag — `~/.claude/settings.json` enabledPlugins map:
```
    "skill-concierge@skill-concierge": true,
```

Hook registration — `cache/.../0.6.1/hooks/hooks.json` (UserPromptSubmit):
```
"command": "python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/scripts/enforcer.py\"", "timeout": 5
```
`${CLAUDE_PLUGIN_ROOT}` resolves to the installPath above ⇒ the executed enforcer is
`cache/skill-concierge/skill-concierge/0.6.1/hooks/scripts/enforcer.py`. (Per workbench convention,
hooks run from `cache/<mkt>/<plugin>/<version>/`, not `marketplaces/`.) All 12 version dirs
0.1.0–0.6.1 exist under cache; 0.6.1 is the one recorded active.

`cache/.../0.6.1/.claude-plugin/plugin.json` → `version = 0.6.1`.

### 1b. Knob grep — ACTIVE cache 0.6.1 enforcer.py
```
65:GETAWAY_FLOOR = float(os.environ.get("ENFORCER_GETAWAY_FLOOR", "0.45"))  # ... OPERATOR-SET 0.45 (2026-06-29, ADR-0009) raised from 0.40 ... Revert to the data-backed default: 0.40.
67:MAX_SHORT_WORDS = 5   # ... OPERATOR-SET 5 (2026-06-29, ADR-0009) raised from 2 ... Revert: 2.
```
→ `MAX_SHORT_WORDS = 5`, `GETAWAY_FLOOR` default `"0.45"`. (The trailing "Revert: 2 / 0.40" text is the
documented reversible-revert path per ADR-0009, not the current value.) The `marketplaces/` copy greps
byte-identical on lines 65/67.

### 1c. deployed == committed source (three independent proofs, all byte-identical)
```
diff  cache/0.6.1/hooks/scripts/enforcer.py   <repo>/hooks/scripts/enforcer.py   → [IDENTICAL — empty diff]
diff  marketplaces/.../enforcer.py            <repo>/hooks/scripts/enforcer.py   → [IDENTICAL — empty diff]
git rev-parse HEAD                            → 6995fd8d05ee32f2e41a9655414c798967a8c24f
diff (git show 6995fd8:hooks/scripts/enforcer.py)  cache/0.6.1/.../enforcer.py   → [IDENTICAL]
```
→ active cache copy == working-tree source == committed blob at 6995fd8. Airtight.

### 1d. --selftest on the ACTIVE cache 0.6.1 enforcer (corroboration only)
```
$ python3 ~/.claude/plugins/cache/skill-concierge/skill-concierge/0.6.1/hooks/scripts/enforcer.py --selftest
enforcer --selftest OK: refusal guard (5 fire / 6 silent) + ranked-mandate %-share + actionability imperative-veto (6 fire / 6 off)
exit=0
```
(Selftest pins the refusal/ranked-mandate/imperative contracts; it does NOT test the threshold values —
those are proven by 1b/1c above and the behavioral drives in Step 2.)

### 1e. dependencies up (so behavioral cases are valid, not fail-open artifacts)
- Qdrant `http://localhost:6333/collections` → `claude_skills`, `claude_skills_shadow`, `prompt_intent` all present.
- Embed shim `http://127.0.0.1:6363/embed` returns a real 768-float vector (the `/health` body is a
  schematic type-listing, a display red herring; the `/embed` POST returns a genuine 768-dim vector).
- Confirmed live by the drives: every embedding case produced REAL cosine scores in the ledger and band
  `offer`/`getaway`/`intent_skip`/`negation` — **zero** `fallback` / `embed_timeout` / `qdrant_down` bands.
- Drives ran under plain `python3` (3.9.6), `ENFORCER_GETAWAY_FLOOR` unset (exercising the file 0.45 default).

---

## STEP 2 — drove the REAL gate; raw bytes per case

Invocation per case: `echo '<json>' | SKILL_CONCIERGE_LOG=<fresh-temp> python3 <active enforcer.py>`.
"words" = `len(prompt.strip().split())` (what the pre-gate sees). Ledger lines are the verbatim single
line written to that case's fresh temp log. Verdict is one line UNDER the bytes.

| # | case | words | stdout | exit | band (ledger) | top score | verdict |
|---|------|-------|--------|------|---------------|-----------|---------|
| 1 | empty | 0 | "" | 0 | <none> | — | PASS pre-gate silent |
| 2 | whitespace-only | 0 | "" | 0 | <none> | — | PASS pre-gate silent |
| 3 | slash "/foo bar baz qux quux corge" | 6 | "" | 0 | <none> | — | PASS slash precedes word-check |
| 4 | "thanks man" | 2 | "" | 0 | <none> | — | PASS ≤5 silent |
| 5 | "update the handoff" | 3 | "" | 0 | <none> | — | PASS 3w dropped pre-embed (2→5 bites) |
| 6 | "fix the parser bug" | 4 | "" | 0 | <none> | — | PASS 4w dropped pre-embed (2→5 bites) |
| 7 | "refactor the old parser module" | 5 | "" | 0 | <none> | — | PASS ==floor → silent |
| 8 | "refactor the old parser module today" | 6 | inject | 0 | offer | 0.5679 | PASS 6w fires → boundary pins floor=5 |
| 9 | long actionable imperative | 12 | inject | 0 | offer | 0.5918 | PASS imperative → offer |
| 10 | long conversational/meta | 17 | "" | 0 | getaway | 0.4103 | PASS top∈[0.40,0.45) → getaway (discriminates 0.45 vs 0.40) |
| 11 | "do not use the supabase skill here please" | 8 | mandate | 0 | negation | — | PASS refusal → mandate-only, offered=[] |
| 12 | Vietnamese actionable | 14 | "" | 0 | intent_skip | 0.6109 | PASS encoding OK; suppressed (see caveat 2) |
| 13 | survey react component | 10 | inject | 0 | offer | 0.5273 | PASS ≥0.45 → offer |
| 14 | survey unit tests | 9 | inject | 0 | offer | 0.6159 | PASS |
| 15 | survey deploy cloudflare | 8 | inject | 0 | offer | 0.7438 | PASS |
| 16 | survey debug tests | 10 | inject | 0 | offer | 0.6404 | PASS |
| 17 | survey postgres schema | 9 | inject | 0 | offer | 0.7600 | PASS |
| 18 | survey security audit | 10 | inject | 0 | offer | 0.7198 | PASS |
| 19 | survey banner image | 10 | inject | 0 | offer | 0.6138 | PASS |
| 20 | survey excel pivot | 10 | inject | 0 | offer | 0.8411 | PASS |
| 21 | survey commit/push | 11 | inject | 0 | offer | 0.5497 | PASS |
| 22 | survey VN gov report | 13 | "" | 0 | intent_skip | 0.6525 | PASS suppressed (see caveat 2) |
| 23 | malformed JSON | n/a | "" | 0 | <none> | — | PASS fail-silent, exit 0, no crash |

### Verbatim ledger lines for the load-bearing cases

**#8 boundary 6w (offer):**
```
{"t": 1782670727.724, "sid": "verify", "ev": "offer", "band": "offer", "offered": [["gitnexus-refactoring", 0.5679], ["pdf-to-markdown-structured", 0.5458], ["langchain-rag", 0.5421], ["rules-distill", 0.5324], ["ponytail:ponytail-review", 0.5224]], "fallback": null, "q": "refactor the old parser module today"}
```
Verdict: 5w sibling (#7) wrote NO ledger and emitted ""; the only change is one extra word → fires. This pins `MAX_SHORT_WORDS = 5` exactly.

**#10 conversational-meta (getaway — the 0.45 vs 0.40 discriminator):**
```
{"t": 1782670727.897, "sid": "verify", "ev": "offer", "band": "getaway", "offered": [["brief-me", 0.4103], ["agentmemory:session-history", 0.3994], ["agent-skills:incremental-implementation", 0.3859], ["live-match-tracker", 0.366], ["agentmemory:recap", 0.3622]], "fallback": null, "q": "i was just thinking ..."}
```
Verdict: top = **0.4103 ∈ [0.40, 0.45)** → band `getaway` (silent). This behaviorally proves the live floor is
**> 0.4103**, which **rules out the 0.40 revert value** (at 0.40, a 0.4103 top would have proceeded past line
307, not gone silent). The exact value `0.45` is pinned by the grep (1b); this case rules out the alternative.
No env override used.

**#11 refusal (negation):**
```
{"t": 1782670727.943, "sid": "verify", "ev": "offer", "band": "negation", "offered": [], "fallback": "skill_refusal", "q": "do not use the supabase skill here please"}
```
Verdict: `_REFUSAL_RE` matched "do not … use" → mandate-only (plain MANDATE in stdout), `offered=[]` (no embed). Per contract.

**#12 / #22 Vietnamese (intent_skip, top ≥ 0.45):**
```
{"... "band": "intent_skip", "offered": [["vn-ares-research-report", 0.6109], ["vn-editor", 0.5988], ["vn-author", 0.5833], ...], "fallback": "conversational", "q": "hãy tạo giúp tôi một báo cáo phân tích dữ liệu bằng tiếng Việt"}
{"... "band": "intent_skip", "offered": [["white-paper-writing", 0.6525], ["business-report", 0.5915], ["vn-canu-reporting", 0.5718], ...], "fallback": "conversational", "q": "viết một báo cáo tham mưu chính phủ về tình hình kinh tế"}
```
Verdict: top ≥ 0.45 cleared getaway; then the actionability gate fired (`intent_skip`). VN chars round-trip
intact in the ledger (`ensure_ascii=False`) ⇒ encoding robust. Suppression here is the gate's English-only
imperative-veto + corpus lean, NOT a threshold defect (caveat 2).

**Offer-path sanity (representative):** survey-excel top 0.8411, survey-postgres 0.7600, survey-deploy 0.7438,
survey-security 0.7198 — all ≥ 0.45 → `offer`, stdout carries the ranked SKILL-FIRST injection with %-share.
→ the offer path is alive and abundant at 0.45 (it is NOT dead at the raised floor).

---

## STEP 3 — synthesis (reconciled to the bytes)

**(A) Values live + deployed==source: PROVEN.** Active enforcer = cache `0.6.1` (installPath + enabled flag +
`${CLAUDE_PLUGIN_ROOT}` hook + plugin.json 0.6.1). Knobs grep `MAX_SHORT_WORDS = 5`, `GETAWAY_FLOOR="0.45"`.
Byte-identical: cache == working tree == committed blob at HEAD `6995fd8` (== recorded gitCommitSha). selftest OK.

**(B) Behavior correct at 5 / 0.45: PROVEN.**
- Word floor 5: clean boundary — 5w (#7) silent/no-ledger vs 6w (#8) fires. Short imperatives at 3w (#5) and
  4w (#6) are dropped **before** embed and **before** the imperative-veto — exactly the trade-off ADR-0009
  flagged ("nicks short commands"). Behavior matches the new floor and matches the ADR's own prediction.
- Score floor 0.45: the conversational-meta top 0.4103 landing in `getaway` (#10) discriminates 0.45 from
  0.40 directly; every top ≥ 0.45 → `offer`/`intent_skip`; getaway fires only below 0.45. Gate ordering
  (getaway before intent_skip) confirmed.
- Other contract paths all honored: negation (#11), intent_skip only when top≥0.45 (#12/#22), fail-silent on
  malformed stdin (#23), pre-gate silence with no ledger for empty/blank/slash/≤5w (#1–#7). Fail-OPEN path
  not exercised because deps were up (correct — no fixture artifact).

### Caveats (tagged)
1. **OBSERVED but UNRESOLVED — a data-currency discrepancy, NOT a deployment defect, and I am NOT claiming a
   real-world impact direction.** My 15 hand-picked high-signal test imperatives topped **0.52–0.84** — well
   above BOTH the in-file comment (lines 47–54: "real tasks land ~0.22–0.40") AND ADR-0009's own contemporary
   ledger medians (taken 0.414 / dodged 0.457, with 3 of 6 adopted offers sitting in [0.40,0.45)). So three
   sources disagree on where real scores sit. Cause unverified — plausibly the 0.5.0 trigger-enrichment lifted
   the scale, plausibly my clean prompts are simply not representative of messy real traffic (ADR-0009 says real
   traffic lives exactly in the [0.40,0.45) band this change targets). **I cannot prove from this sample whether
   the 0.40→0.45 raise helps, hurts, or barely moves real-world offer volume** — and I do not assert it either
   way. What IS proven: the floor is deployed at 0.45 and the gate executes the contract correctly at it. The
   discrepancy is worth a doc/telemetry refresh; it does not touch the verdict.
2. **OBSERVATION — gate design, predates 0.6.1, orthogonal to the threshold change.** Genuinely actionable
   Vietnamese prompts ("hãy tạo…", "viết…") are suppressed via `intent_skip` because `_is_imperative` only
   recognizes English verbs and the `prompt_intent` kNN leans them conversational. This is a known limitation
   of the 0.6.0 actionability gate, not introduced or altered by 0.6.1's threshold tune.
3. **NOTE — not a defect.** The "Revert: 2 / 0.40" text in the knob comments is the documented revert path per
   ADR-0009 (Accepted, reversible). Current live values are 5 / 0.45.

**No fixture artifacts:** deps were up for every drive (zero fallback bands); the real ledger was never written.

### BOTTOM LINE: GO.
The deployed gate matches the claim. Values are live (5 / 0.45), the deployed artifact is byte-identical to the
committed source at 6995fd8, and the runtime behavior matches the documented contract at the new thresholds —
proven by raw bytes including a direct 0.45-vs-0.40 discriminator (#10) and an exact word-floor boundary (#7/#8).
