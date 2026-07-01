# Opus Validation Report

**Subject:** implementation — bug fix to `skills/skill-usage-audit/scripts/audit_skill_usage.py` (commit `37225fa`)
**Scope:** the single commit `37225fa` — "fix(skill-usage-audit): capture real user prompts in self/meta scoping"
**Verdict:** PASS
**Date:** 2026-07-01
**Evidence Files Examined:** 4 (current script, pre-fix script via `git show`, real transcript store `~/.claude/projects/**/*.jsonl`, AGENTS.md/CHANGELOG.md)

## Executive Summary
The fix is correct and does exactly what it claims: genuine user-prompt lines now reach the self/meta classifier that the old pre-filter silently dropped. I independently reproduced the causal effect against the pre-fix version — self/meta flagged sessions go up for `--since "2026-07-01"` while every other count (Skill-tool, /slash, USING, SEARCH, SKIPPING, false-SKIPPING verdict) stays byte-identical, proving the change is surgical and regression-free. Critically, I did not stop at the *count*: an identical-window pre/post diff shows the commit newly flags exactly 3 sessions, and **all 3 are genuinely self/meta, each carried by a real typed user prompt** (this validation session, a `verify-as-claimed` verifier session, a gate-review session) — so the fix's marginal classifications are correct, not just more numerous. Verdict is PASS with advisory items; the sharpened finding is that the fix over-captures non-typed user-role string content (`<teammate-message>`/`<command-message>`) but that over-capture is **inert in current data** (redundant with a typed hit in every flagged session), and a separate genuinely-organic false flag exists via the *pre-existing* list-text path, not this commit.

## Observable Truths
| # | Claim | Status | Evidence |
|---|-------|--------|----------|
| 1 | `--selftest` still reports "OK: false-SKIPPING verdict" | ✓ | `audit_skill_usage.py --selftest` → `audit --selftest OK: false-SKIPPING verdict` |
| 2 | Post-fix `--since "2026-07-01"` flags more self/meta sessions than pre-fix | ✓ | current run: `3 flagged` (earlier) / `4 flagged` (later, live-data grew); pre-fix same-window run: `0 flagged` |
| 3 | The sessions the commit newly flags are genuinely self/meta | ✓ | identical-window pre/post diff: `meta_post − meta_pre = 3`, **all 3 carried by a genuine TYPED prompt** (handoff/validation, `verify-as-claimed` verifier, "review the skill-concierge gate") |
| 4 | Fix corrects organic counts downward | ✓ | organic Skill-tool `12→6`, organic USING `22→7` (pre→post, live-data figures) |
| 5 | Commit's exact figures (`0→3`, organic `10→5`/`18→6`) reproduce | ⚠ | flagged-delta direction reproduces exactly; absolute magnitudes drift (`3`, then `4`; organic `12→6`/`22→7`) — the transcript store is live and grew (incl. this very session) between runs; direction/isolation are solid, frozen magnitudes are not |
| 6 | No regression in n_search/n_skip/false_skip/skill_tool/using/slash | ✓ | pre vs post identical: Skill-tool 12, /slash 4, USING 22, SEARCH 11, SKIPPING 12, false-SKIPPING 9/12 |
| 7 | A real dropped prompt exists (root-cause claim) | ✓ | traced real `type:user` string-content records mentioning "skill-concierge" with `has_marker=False` → OLD code drops, NEW code admits |
| 8 | Commit is scoped to only the one file | ✓ | `git show --name-only 37225fa` → sole file `skills/skill-usage-audit/scripts/audit_skill_usage.py` |
| 9 | Robust against malformed/partial JSONL (no crash) | ✓ | `json.loads` in try/except at :157-160, file open try/except at :132-135; full-store run completed without error |
| 10 | Captures *genuine user prompts* only (per comment/commit narrative) | ⚠ | narrative imprecise — capture condition `role=="user" and isinstance(content,str)` also matches `<teammate-message>`/`<command-message>`/`<task-notification>` string records; INERT in current data (every such hit coincides with a typed-prompt hit) but the mechanism is broader than "typed prompts" |

## Key Dependency Verification
| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| pre-filter `continue` | `sess_text` accumulation | `has_marker or (is_user and not is_list_content)` (:155) | ✓ WIRED | New disjunct admits genuine-prompt lines that carry no tool marker |
| admitted user line | `sess_text[sid]` | `role=="user" and isinstance(msg["content"],str)` (:177-178) | ✓ WIRED | String content captured (`[:400].lower()`); guard blocks non-string content safely |
| `sess_text` | `meta_sessions` | `any(kw in t for kw in meta_keywords)` (:222-223) | ✓ WIRED | Feeds organic-exclusion at :277-278 → printed at :279-281 |
| `is_user`/`is_list_content` | new pre-filter clause | raw-substring flags (:144-145) | ✓ WIRED | Unchanged by diff; reused correctly |
| newly-admitted lines | `_CMD`/`skill_tool`/`using`/verdict counters | downstream loop (:168-210) | ✓ NO-OP | Empirically no count change → lines admitted only by the new clause contribute nothing but `sess_text` |

L1/L2/L3: file EXISTS (293 lines), SUBSTANTIVE (real logic, no stubs/TODO/FIXME), WIRED (skill script backing `skill-concierge:skill-usage-audit`, runs and produces output).

## Blocking Issues (FAIL)
No blocking issues found.

## Advisory Suggestions (WARN)
1. **Narrative/comment imprecision — capture is broader than "genuine user prompts," but the over-capture is currently inert.** The commit message and inline comments (:150-152, :175-176) assert the new path captures "real user-typed prompts" and that hook-injected reminders/tool-results use *list-wrapped* content. Empirically imprecise: `<teammate-message>`, `<command-message>`, `<task-notification>`, `<system-reminder>` records also arrive as **user-role STRING content** and ARE captured. *Verified impact (identical-window pre/post diff):* of the 3 sessions this commit newly flags, **every one is carried by a genuine typed prompt** — the non-typed string hits are redundant, so the over-capture changes **no** classification outcome in current data (inert). The latent risk is real but one-directional and conservative: a future session could in principle be flagged meta *solely* by a non-typed string record (e.g. a `<teammate-message>` mentioning a keyword), which would only *shrink* organic counts, never inflate them — so it can under-credit the gate change, never over-credit it. *Fix:* correct the comment to say "all user-role string content" (not "typed prompts"); optionally exclude leading `<teammate-message>`/`<system-reminder>`/`<task-notification>` tags from the string capture if typed-prompt precision is wanted.
2. **Pre-existing (out-of-scope) precision bug the check surfaced: the `"skill-concierge"` keyword self-matches the plugin's own cache path.** A genuinely organic session in a *different* project (`…/postiz-app`) is flagged self/meta because a skill's injected `Base directory for this skill: …/.claude/plugins/cache/skill-concierge/…` contains the keyword — via the **pre-existing list-text path (:197-198), not this commit** (it is in `meta_pre`). *Rationale/impact:* any organic session using any skill delivered under the skill-concierge plugin cache can be false-flagged meta, understating organic usage. This is not introduced or worsened by `37225fa`, but the operator should know the headline "organic" figure carries this pre-existing downward bias; consider tightening `DEFAULT_META` matching (e.g. word-boundary or excluding cache-path injections) in a follow-up.
3. **No automated regression pin for the fixed behavior.** `--selftest` only exercises `_skip_verdicts` (false-SKIPPING), not the self/meta capture this commit fixes. The bug could silently regress and `--selftest` would still say OK. *Rationale:* the codebase already demonstrates the fix — extract the classification into a pure helper (mirroring `_skip_verdicts`), e.g. `_is_meta(text, keywords)` or a record-list → `meta_sessions` function, and add a `--selftest` assertion pinning that a string-content user record with a meta keyword flags the session and a list-content-only record does not. This is the project's own established pattern (pure function + selftest), so it is low-cost and idiomatic.
4. **`[:400]` truncation is a mild latent fragility.** Meta keywords appearing only after char 400 of a single prompt would be missed (:178). Current project usage places keywords early, and `sess_text` accumulates *every* prompt in the session (each truncated), so real-world risk is low — but it is luck, not a guarantee. Acceptable as-is; note it if prompt shapes change.
5. **Optional `[Unreleased]` CHANGELOG entry.** The `[Unreleased]` section is empty and this fix was not logged there. AGENTS.md :52 mandates a CHANGELOG entry only *when bumping the version* ("Never bump one alone"); no version bump occurred, so this is **not** a hard compliance gap. Keep-a-Changelog best practice would still add a one-line `### Fixed` note under `[Unreleased]` for traceability. Judgment call; not required.

## Validation Dimensions (Implementation Validation)
- [x] Correctness of the pre-filter change — PASS
  - Evidence: :155 `if not (has_marker or (is_user and not is_list_content)): continue`
  - Notes: admits exactly genuine user-turn-opening lines plus the original marker set. Lines admitted only by the new clause cannot double-count: `_CMD.findall` needs `<command-name>` (which would itself set `has_marker`), and the list-content branch (:179) is skipped for string content. Verified empirically — all non-meta counts unchanged pre/post.
- [x] Correctness of the sess_text capture condition — PASS
  - Evidence: :177 `if role == "user" and isinstance(msg, dict) and isinstance(msg.get("content"), str)`
  - Notes: gated on the *parsed* `role`, not the raw-line `is_user` heuristic, so a raw-substring false-positive on `'"type":"user"'` (mitigated anyway by JSON escaping — a pasted `"type":"user"` renders as `\"type\":\"user\"`, which does not match) cannot cause an incorrect capture; a false-positive line merely falls through to existing logic with no new effect.
- [x] No regression in other signals — PASS
  - Evidence: pre vs post identical — Skill-tool 12, /slash 4, USING 22, SEARCH 11, SKIPPING 12, false-SKIPPING 9/12
  - Notes: strongest possible evidence — byte-identical output except the meta/organic block.
- [x] Causal effect isolated — PASS
  - Evidence: `git show 37225fa~1` pre-fix run = `0 flagged` vs current `3`/`4`; plus an identical-window single-pass diff (`meta_pre=1`, `meta_post=4`, `meta_post−meta_pre=3`) that is immune to live-data drift
  - Notes: the single-pass diff cleanly attributes exactly 3 newly-flagged sessions to this commit's string-capture path alone.
- [x] Newly-flagged sessions are CORRECTLY classified (not just more numerous) — PASS
  - Evidence: all 3 of `meta_post−meta_pre` carry a genuine TYPED-PROMPT keyword hit — `3c40052b` (handoff/validation), `be015945` (`verify-as-claimed` verifier), `dde66745` ("review the skill-concierge gate")
  - Notes: this is the load-bearing check behind advisory #1 — the fix's marginal classifications are right; the extra non-typed string hits are redundant (inert), not the reason any session flags.
- [x] Root-cause claim verified against real data — PASS
  - Evidence: traced real `type:user` string-content records mentioning "skill-concierge" with `has_marker=False`
  - Notes: confirms the old pre-filter dropped genuine prompts before `json.loads`/classification.
- [x] Robustness / fail-safe (AGENTS.md :61 spirit) — PASS
  - Evidence: try/except at :132-135 and :157-160; clean full-store run
  - Notes: script is a manual CLI tool, not a hook, so the fail-silent hook guardrail is not directly binding, but it satisfies the spirit.
- [x] Scope & convention compliance — PASS
  - Evidence: single-file commit; stdlib-only imports (:27-33) matching the project's stdlib convention (AGENTS.md :50); no plugin.json/marketplace.json/vendor/ADR/gitignored-scratch touched
  - Notes: pre-flight forbidden patterns ("Never bump one alone", "Don't edit an accepted ADR", "never patch vendor/skill-search/") correctly NOT triggered.
- [x] Performance trade-off — PASS (acceptable)
  - Evidence: extra `json.loads` now runs on genuine user-turn-opening lines regardless of markers (:155-158)
  - Notes: user-prompt lines are a small fraction of transcript volume; the fast-path for the bulk of lines is preserved. A keyword-substring pre-check before `json.loads` was considered but would couple the pre-filter to the (overridable) `--meta-keyword` set and add complexity — current approach is correct and simpler (KISS).
- [x] Test coverage adequacy — WARN (advisory #3)
  - Evidence: `--selftest` covers only `_skip_verdicts`, not the fixed self/meta path
  - Notes: acceptable for internal telemetry tooling; a pure-helper + selftest assertion is the idiomatic close.

## Unverifiable Items
- The commit message's exact absolute figures (flagged `0→3`, organic `10→5`/`18→6`) are non-reproducible as frozen numbers because the transcript store is live and grows continuously — including this very validation session (`3c40052b`), whose own transcript is one of the flagged sessions. Across my runs I observed `3` then `4` flagged and organic `12→6`/`22→7`. This is expected behavior of a tool reading a mutating data source, not a defect. What IS verified and drift-immune is the *isolation*: the identical-window single-pass pre/post diff attributes exactly 3 newly-flagged, all-correct sessions to the commit. Classified UNVERIFIABLE only as to the frozen magnitudes.

## Context Gaps
- No context gaps material to the verdict. `driftcheck.py` (AGENTS.md :43-46) was not run because the diff touches none of the version triple (`plugin.json`/`marketplace.json`/`CHANGELOG.md`) it guards, so it cannot be affected by this commit.
