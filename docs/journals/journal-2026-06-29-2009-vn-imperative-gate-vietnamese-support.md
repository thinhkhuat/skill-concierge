# Enforcer Imperative Veto: Vietnamese Language Support

**Date**: 2026-06-29 20:09
**Severity**: High
**Component**: `hooks/scripts/enforcer.py` — actionability gate, imperative-veto `_is_imperative()`
**Status**: Resolved

## What Happened

The enforcer's actionability gate was suppressing skill offers on non-imperative turns to reduce noise. An imperative-veto (`_is_imperative()`) protected task requests from suppression by detecting whether the user was asking for something to be done. That check worked for English — but was entirely broken for Vietnamese. The tokenizer was ASCII-only (`[a-z']+`), which shredded Vietnamese diacritics into garbage, and the verb list was English only. Result: Vietnamese task prompts like "sửa lỗi …" (fix error), "viết báo cáo …" (write report) were not recognized as imperatives. A Vietnamese-primary operator working in their native language got their legitimate task requests silently suppressed.

## The Brutal Truth

This is infuriating because it's a silent failure. The operator sends a clear directive in Vietnamese and nothing breaks visibly — the request just disappears into the suppression logic, and the human blames themselves. That's the worst kind of bug: it works perfectly, just not for you. An i18n half-measure shipped without checking the languages that were supposed to be safe, and a non-English user paid for it. 

The real kick in the teeth: the gating logic was already there. It just wasn't internationalized.

## Technical Details

**Root issue:** `_is_imperative()` in `hooks/scripts/enforcer.py`:
- Tokenizer: `re.findall(r"[a-z']+", prompt.lower())` — ASCII only, strips all Unicode.
- Verb list: 17 English verbs (`{"fix", "add", "write", "change", …}`) — no Vietnamese.
- Impact: `"sửa lỗi trong ..."` → tokens `["s", "a", "l", "i", "trong"]` (gibberish) → no verb match → suppressed.

**Verification failure:** No test coverage for non-English paths.

## What We Tried

1. **Extend English verb list** — No. We are not playing whack-a-mole with every language.
2. **Add Vietnamese verbs inline** — Partial. But needed the tokenizer fixed first or they'd still be shredded.
3. **Defer full `prompt_intent` corpus** — Correct. But we still needed a working gate *now* for Vietnamese.

Final approach: Fix the three concrete blockers (tokenizer, VN verbs, selftest), mark the ceiling, defer deeper work.

## Root Cause Analysis

Three design oversights bundled together:

1. **Tokenizer assumed ASCII.** The regex `[a-z']+` was written without considering that "lowercase and keep contractions" is a universal requirement, not an English one. Should have been Unicode-aware from day 1.

2. **Verb list was English-only.** No one asked "what languages will this gate run against?" before baking in 17 English verbs as the only ground truth.

3. **No selftest for non-English.** The selftest only fired English cases. Non-English regressions were invisible.

The root cause is not malice or ignorance — it's the assumption that an English prototype would be re-examined before shipping to a multilingual operator.

## Lessons Learned

1. **Gating logic is not optional for i18n.** If a gate touches user input, it touches every language that user speaks. There is no "English version" of a gate; there is only "works" and "broken for speakers of X".

2. **Tokenization is a language problem.** `re.findall(r"[a-z']+", ...)` is not portable. Unicode normalization (NFC) + Unicode-aware regex (`[^\W\d_]+(?:'[^\W\d_]+)*`) is the portable floor. Test both NFC and NFD edge cases.

3. **Verb lists scale via pattern, not enumeration.** For Vietnamese, we added `_VN_VERBS` (single-syllable core) + `_VN_VERB_BIGRAMS` (two-syllable, because Vietnamese is analytic). The next language needs the same structure, not a new hardcoded set.

4. **Ceiling clarity prevents debt.** We explicitly accepted false-fire on VN status-questions (e.g., "chạy tốt không?" / "is it running well?") because `chạy` is a verb. That's a cheap miss (one extra offer, no suppression loss) and marked with `# ponytail:`. Knowing the ceiling prevents silent degradation.

## Implementation Details

**Changes (3 parts, +36/−6 net):**

1. **Tokenizer:** 
   - Input: `unicodedata.normalize("NFC", prompt).lower()` (load-bearing: normalizes NFD input)
   - Regex: `[^\W\d_]+(?:'[^\W\d_]+)*` (Unicode word boundary, keeps diacritics and contractions)

2. **Vietnamese verbs:**
   - `_VN_VERBS`: `{"sửa", "viết", "chạy", "thêm", …}` (17 core single-syllables)
   - `_VN_VERB_BIGRAMS`: `{("làm", "ơn"), ("vui", "lòng")}` (polite requesters)
   - Filler: Added `"hãy"`, `"xin"` (polite openers)
   - **Deliberately excluded `"làm"`** from verb list. It's the top question-opener ("làm sao để…"  / "how to…"). Including it would have gutted suppression for conversational Vietnamese. Marked in code.

3. **Selftest:**
   - Extended with `let's` contraction guard (English regression)
   - Added 10 VN imperative fire cases, 8 VN conversational off cases
   - Verified 15 fire / 10 off; independent tester: 26/26 fresh probes correct

**Key decision:** Kept this high-precision, localized fix. Deferred the deeper `prompt_intent` corpus (mostly-English, requires substantial rewrite) as a separate project. Current gate is now correct for VN imperatives and safe on regressions.

## Verification

- `enforcer.py --selftest`: PASS (imperative-veto 15 fire / 10 off; all English cases preserved)
- Independent tester (26 fresh probes): PASS (10 VN imperative → True, 8 VN conversational → False, 8 EN regressions → correct)
- NFC/NFD edge cases: Confirmed diacritics preserved, no double-normalization
- External callers: Zero. `_is_imperative()` is private; safe to change.
- Driftcheck: IN SYNC with enforcer.py main logic

## Next Steps

1. **Version bump + commit** — user-run (held, not shipped yet)
2. **Monitoring:** Watch for false-fire on VN status-questions (acceptable, marked)
3. **Future:** Full `prompt_intent` corpus for deeper language support (separate larger project, tracked in plan)
4. **Documentation:** Update enforcer docs to note VN support and the `làm` ceiling

---

**Plan reference:** /Users/thinhkhuat/in-PROD/MY-WORKBENCH/plans/260629-1854-vn-imperative-gate-fix/plan.md


## Scope correction (post-review, 2026-06-29)

An advisor pass caught that the initial verification cases were all <=5 words. In production `main()` drops prompts with <= `MAX_SHORT_WORDS` (5) words via a pre-gate BEFORE `_is_imperative` runs — so this fix only affects VN imperatives **>5 words** that reach the `intent_skip` gate. Short commands like "sửa lỗi này" (3 words) are dropped upstream regardless of language (a separate `MAX_SHORT_WORDS` / ADR-0009 matter, not this change). Re-verified end-to-end through `main()` (stubbed embed/retrieve/intent): a >5-word VN imperative is now offered (veto rescues it), a >5-word VN question stays suppressed, a 3-word imperative is dropped at the word-gate. Selftest extended with representative >5-word VN cases.
