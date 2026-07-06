# Verify-as-Claimed Raw-Evidence Report — Anti-Dodge Domains A/B/C/D (v0.14.0 source)

**To:** Lead · **From:** independent verify-as-claimed validator (separate party, no build stake)
**Date:** 2026-07-06 15:11 +07
**Repo/cwd:** `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge` · **Branch:** `main`
**Discipline:** READ-ONLY on subjects; all hook runs redirected to `/tmp` ledgers + env; real `~/.claude` state untouched (proof §7).

> **ARTIFACTS ARE SOURCE, NOT DEPLOYED.** Everything below validates the working-tree SOURCE. Deploy (triple-bump
> `plugin.json`+`marketplace.json`+`CHANGELOG.md` → 0.14.0, engine re-copy, reindex, MCP restart) is Phase 7 and is
> **NOT done**. Proof: engine venv version marker = `0.13.1`; `plugin.json` version = `0.13.1`; the venv's
> `skills_discovery.py` DIFFERS from source (H4 not re-copied → H4 is NOT live). `deployed == source` is a separate
> later gate, out of scope for this pass.

---

## 0. Oracle sources read (expectations formed from these, NOT any builder report)

- Plan phases: `phase-02-h3-subagent-session-scoping.md`, `phase-04-h2-red-flags-table.md`, `phase-05-h5-over-fire-lane-and-gate-legibility.md`, `phase-06-h4-trigger-purity-lint.md`
- ADRs: `docs/adr/0019-*.md`, `0020-*.md`, `0022-*.md`, `0023-*.md`
- `docs/anti-dodge-integration-v0.14.md`
- Subject code: `hooks/scripts/enforcer.py`, `hooks/scripts/doctrine.py`, `hooks/doctrine/skill-first.md`, `vendor/skill-search/skill_search/skills_discovery.py`, plus `skills/skill-usage-audit/scripts/audit_skill_usage.py` (cross-file contract).

Engine venv (from `setup.sh:18`): `$HOME/.local/share/skill-concierge/venv` — Python 3.12.13, pytest 9.1.1. System `python3` = 3.9.6 (the ADR evidence used bare `python3`; both selftests pass under system 3.9.6, see §1).

---

## 1. Bundled selftests — raw output + exit codes

### 1a. `python3 hooks/scripts/enforcer.py --selftest`
```
enforcer --selftest OK: refusal guard (5 fire / 6 silent) + ranked-mandate %-share + actionability imperative-veto (17 fire / 12 off) + keepoff-drop + gap-collapse + per-skill-tau/deterministic-routes (default-inert) + authorized-skip tier (3 injects on / silent-off) + selfref over-fire lane (6 fire / 6 off)
EXIT=0
```
Corroborates ADR-0019: "3 injects on / silent-off; selfref lane 6 fire / 6 off". PASS.

### 1b. `python3 hooks/scripts/doctrine.py --selftest`
```
doctrine --selftest OK: subagent(agent_id) suppressed + top-level/persona(agent_type)/malformed/empty all inject (fail toward injection) + flag-off byte-identical
EXIT=0
```
Corroborates ADR-0020 Evidence. PASS.

### 1c. Vendor pytest (as ADR-0023 runs it), engine venv
`cd vendor/skill-search && $VENV/bin/python -m pytest tests/test_discovery.py tests/test_indexing.py -m "not integration"`
```
platform darwin -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0
collected 26 items / 1 deselected / 25 selected
tests/test_discovery.py .................                                [ 68%]
tests/test_indexing.py ........                                          [100%]
======================= 25 passed, 1 deselected in 0.74s =======================
EXIT=0
```
Matches ADR-0023 Evidence exactly ("25 passed, 1 deselected"). PASS.

> Bundled tests are corroboration, not oracle. My independent adversarial cases follow (§3–§6).

---

## 2. Subject B — `doctrine.py` (H3 subagent scoping) — adversarial stdin cases

Invocation form: `printf '<json>' | [env] python3 hooks/scripts/doctrine.py`. Injection = stdout containing `additionalContext`; suppression = empty stdout.

| Case | stdin payload | Expect | Raw result | Exit | Verdict |
|------|---------------|--------|-----------|------|---------|
| (a) subagent | `{"…,"agent_id":"abc"}` | NO injection | empty stdout | 0 | **PASS** |
| (b) top-level | `{"source":"startup"}` | inject | `{"hookSpecificOutput":{…"additionalContext":"## SKILL-FIRST …` | 0 | **PASS** |
| (c) persona | `{"…,"agent_type":"Explore"}` (no agent_id) | inject (must NOT suppress on agent_type) | `{"hookSpecificOutput":{…"additionalContext":"## SKILL-FIRST …` | 0 | **PASS** |
| (d1) malformed | `{ not valid json` | inject (fail-open) | injects `## SKILL-FIRST` | 0 | **PASS** |
| (d2) empty | `` | inject (fail-open) | injects `## SKILL-FIRST` | 0 | **PASS** |
| (d3) non-dict | `["agent_id","x"]` | inject (fail-open) | injects `## SKILL-FIRST` | 0 | **PASS** |
| (e) flag-off | `SKILL_SUBAGENT_STOP=0` + agent_id | inject (byte-identical) | injects `## SKILL-FIRST` | 0 | **PASS** |

**Byte-identical proof (case e):** md5 of `off+agent_id` output == md5 of `on+top-level` output:
```
off+agent_id bytes: 7530   md5=d8a898ca4733d6f133296be0f79e168e
on +top-level bytes:7530   md5=d8a898ca4733d6f133296be0f79e168e
on +agent_id (suppress) bytes: 0
diff off+agent_id vs on+top-level: IDENTICAL (byte-for-byte)
```

**Unit adversarial on `_is_subagent` (11 edge cases) — ALL PASS:**
```
OK  _is_subagent('{"agent_id":"abc"}')   = True   [normal subagent id]
OK  _is_subagent('{"agent_id":""}')      = False  [empty-string -> inject]
OK  _is_subagent('{"agent_id":"   "}')   = False  [whitespace-only -> inject]
OK  _is_subagent('{"agent_id":null}')    = False  [null -> inject]
OK  _is_subagent('{"agent_id":123}')     = False  [numeric non-str -> inject]
OK  _is_subagent('{"agent_id":true}')    = False  [bool -> inject]
OK  _is_subagent('{"agent_type":"Explore"}') = False [agent_type only -> inject; F3b fix]
OK  _is_subagent('{}')                   = False  [empty dict -> inject]
OK  _is_subagent('not json')             = False  [garbage -> inject]
OK  _is_subagent('[1,2,3]')              = False  [array -> inject]
OK  _is_subagent('{"agent_id":"x","agent_type":"y"}') = True [agent_id wins -> suppress]
RESULT: ALL PASS
```
Positive-proof-only + fail-toward-injection is airtight. **Subject B verdict: PASS.**

---

## 3. Subject A — `enforcer.py` (H5 over-fire lane) — adversarial cases

Invocation: `printf '{"prompt":"…","session_id":"vtest"}' | SKILL_CONCIERGE_LOG=/tmp/… python3 hooks/scripts/enforcer.py`.
The selfref lane is a no-I/O pre-gate (runs before embed), so the fire cases need no live shim.

### (a) FIRE — `"explain your last answer again for me"` → expect SKILL-CHECK: + signature
```
{"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "SKILL-CHECK: this turn only asks you to explain/rephrase your own immediately-prior message — the self-referential recap lane — with no external task, so no skill applies. SKIPPING: none is pre-authorized; no further search_skills needed."}}
EXIT=0
```
Signature `self-referential recap lane` present. **PASS.**

Ledger side-effect (temp `/tmp/enf_ledger_test`), proving band tagging:
```
{"t": 1783325322.172, "sid": "vtest", "ev": "offer", "band": "selfref_skip", "offered": [], "fallback": "self_referential", "q": "explain your last answer again for me"}
```

### (b) RED-TEAM BYPASSES — must NOT authorize skip (whole-prompt task-verb / connector veto)
| Prompt | Signature present? | Routed to | Verdict |
|--------|-------------------|-----------|---------|
| `explain your answer and implement the migration` | NO | full embed+retrieve, normal ranked mandate (real skills offered: `agent-skills:deprecation-and-migration`, `migrate`, …) | **PASS** |
| `rephrase your last answer as a working config` | NO | normal routing | **PASS** |
| `clarify your point by writing the actual code` | NO | normal routing | **PASS** |

Raw (b1), abridged — confirms it fell through to the real retrieval path (embed shim + Qdrant live):
```
{"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "SKILL-FIRST · reply line 1 = USING <skill> | SEARCH <query> | SKIPPING none.\nPreview for this task (NOT the full ~500 shelf):\n  • agent-skills:deprecation-and-migration (17%) …  • migrate (16%) …  • supabase-apply-migration (10%) …"}}
```

### (c) FLAG-OFF — `ENFORCER_SELFREF_SKIP=0` on a would-fire prompt → no signature / normal routing
```
{"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "SKILL-FIRST · reply line 1 = USING <skill> …  • requirements-clarity (15%) …
<<<no signature — flag-off correctly routes to embed/mandate path>>>
```
**PASS.**

### (d) My OWN adversarial selfref probes (beyond the bundled fixtures) — hunting false-bless of real work
```
ADVERSARIAL SELFREF OK: 4 fire, 10 correctly-rejected (no false-bless of real work)
```
- 4 genuine recaps fired: `explain your previous message`, `restate that more simply`, `recap what you just told me`, `please expand on your last point`.
- 10 real-work prompts ALL correctly rejected, incl. subtle bypasses: `restate that as a bash script`, `explain your answer with a code example`, `expand on that by running the deploy`, `summarize the previous discussion into a migration plan`, `explain how you would refactor the auth module`. No false-fire. The narrow-by-construction claim holds under independent pressure.

**Subject A verdict: PASS** (the lane itself). See §8 for a cross-file gap that does NOT belong to Subject A's build scope.

---

## 4. Subject C — `skill-first.md` (H2 red-flags table)

```
H2-1: rg "self-referential recap lane" hooks/doctrine/skill-first.md → rg-exit=1 (NO match) — PASS
H2-2: table header at :60  "| Symptom … | Refutation … |"  ;  data rows = 7  (ADR-0022 "v1 rows (7)") — PASS
H2-3: rule cross-refs resolve — "closed list in 4" (:18,:62,:110), "rule 6" (:53,:58), "rule 3" (:67), "rule 2" (:95) — PASS
```
**Row 7 phrasing (anchor-collision guard):** `:68` uses "the enforcer's **OVER-fire lane**" + references the `SKILL-CHECK:` line, and does NOT use the forbidden `self-referential recap lane` signature. Matches ADR-0022 §Decision. PASS.

**Enforcer↔doctrine consistency (no-drift claim):** MANDATE re-assert `enforcer.py:288-289` carries `"Few don't fit" / "I'm confident" / "you named a tool"`; doctrine table rows carry the same three refutations at `skill-first.md:63` (already-searched), `:64` (named tool), `:66` (I'm confident). No drift. PASS.

**Subject C verdict: PASS.**

---

## 5. Subject D — `skills_discovery.py` (H4 trigger-purity lint, shadow default)

### 5a. Byte-identical claim (default shadow == off) — the load-bearing safety claim
Full extraction pipeline over the live corpus, per-mode module reload:
```
shadow total phrases: 2688
off    total phrases: 2688
active total phrases: 2606
SHADOW == OFF (byte-identical claim): True     ← per-skill list equality, not just totals
ACTIVE drops (off_total - active_total): 82
```
**PASS** — at default `shadow`, the extracted trigger set is byte-identical to `off`; nothing is dropped.

### 5b. Conservative "generate a report" survivability + predicate probes
```
impure=False :: 'When the user wants to generate a report'      ← use-CONDITION survives (protected)
impure=True  :: 'generate a report of findings'                 ← terse verb-LEAD flagged (documented FP class, ADR-0023 Open §)
impure=False :: 'Use when you need to produce a report'         ← survives
impure=True  :: 'Runs the plan->cook->test pipeline'            ← process branch flags (correct)
impure=True  :: '1. Scaffold the project'                       ← step branch flags (correct)
impure=True  :: 'generates a workflow report'                   ← process branch flags (correct)
impure=True  :: 'creates a deployment pipeline'                 ← process branch flags (correct)
```
The vendor test pins exactly the protected phrasing (`test_discovery.py:145`): `"When the user wants to generate a report from raw metrics"` → survives in active. Its comment (`:142-143`) is honest that a terse verb-LEAD `"generate a report …"` WOULD be flagged. My probe matches both the test and ADR-0023's own "Open" caveat. **No defect — documented, owner-accepted heuristic limit.**

### 5c. Phase-7 flag (i): the `@integration` test fails, and the failure is unrelated to H4
`pytest tests/test_indexing.py::test_end_to_end_build_search_incremental -m integration`:
```
>       assert stats["indexed"] > 0 and stats["embedded"] == stats["indexed"]
E       assert (526 > 0 and 3860 == 526)
tests/test_indexing.py:111: AssertionError
=================== 1 failed, 1 warning in 131.61s (0:02:11) ===================
EXIT=1
```
Fails on `embedded (3860) == indexed (526)` — the multi-vector layer emits 3860 phrase vectors for 526 skills. This lives in `server.py::build_index` (the `embedded == indexed` assertion predates ADR-0012/0016 trigger points). **Unrelated to H4's `skills_discovery.py` purity code.** Corroborates ADR-0023 Evidence §. (The test is deselected by the standard `-m "not integration"` marker, so it does not affect the release gate.)

### 5d. Phase-7 flag (ii): the process-verb branch is corpus-SILENT today
Shadow scan classifying every would-drop by branch over the live corpus:
```
STEP-branch would-drops (numbered step):        85
PROCESS-branch would-drops (verb+summary-noun):  0
BOTH branches:                                   0
--- PROCESS-branch samples (should be 0 if corpus-silent) ---   (none)
--- STEP-branch samples ---  '1. gitnexus_rename(…)', '2. Review ast_search edits', '3. …', …
```
`_IMPURE_PROCESS_RE` fires on ZERO live phrases; only `_IMPURE_STEP_RE` fires. Confirms ADR-0023 Open §: "the process-verb branch is corpus-SILENT today … its false-positive rate is UNMEASURED." (ADR said ~82; I observe 85 — minor drift from live-corpus growth, not a defect.)

**Subject D verdict: PASS** at the release default (`shadow`). The heuristic subjectivity + the unmeasured process-branch FP rate are documented owner-accepted caveats, not defects.

---

## 6. Cross-cutting checks

- **VENDORED.md updated for H4** (phase-06 non-functional req): `git diff --stat` → `+14 lines`; documents the purity predicate, states, `shadow` byte-identical, and the FULL-reindex-on-activation dependency. PASS.
- **Default-ON one-var revert flags all present:** `SKILL_SUBAGENT_STOP` (doctrine.py:47), `ENFORCER_SELFREF_SKIP` (enforcer.py:134), `SKILL_TRIGGER_PURITY` (skills_discovery.py:96). PASS.
- **enforcer selftest asserts exactly 3 authorized-skip injects** (`enforcer.py:770`) + selfref uniqueness parity (`:785-789`: signature in `_captured[2]`, absent from `_captured[0]/[1]`). PASS — this is the parity test ADR-0019 Evidence refers to.

---

## 7. READ-ONLY / no-side-effect proof

- All enforcer runs used `SKILL_CONCIERGE_LOG=/tmp/enf_ledger_test*` → writes landed in `/tmp`, not real telemetry.
- Real ledger `~/.claude/skill-telemetry/logs/skill-invocation-ledger.log` last-modified `Jul 6 15:00:57 2026` (a prior session), while validation ran ~15:03–15:11 — real state untouched.
- No subject file modified. `git status` shows only pre-existing working-tree changes (the anti-dodge build itself) + untracked ADRs/plans; nothing authored by this validation.
- Temp harnesses under `/tmp` only: `h4_shadow_scan.py`, `h4_byteident.py`, `selfref_adversarial.py`, `subagent_adversarial.py`.

---

## 8. Discrepancies — real-defect vs fixture-artifact

### 8.1 [REAL GAP — NOT in Subject A/B/C/D build scope] Audit lacks the H5 selfref anchor
The audit `skills/skill-usage-audit/scripts/audit_skill_usage.py:176-177` counts an authorized skip ONLY when the line contains `"full-catalogue retrieval ran"` (getaway) OR `"intent-margin classifier"` (intent_skip). The live H5 selfref inject contains NEITHER (it says `self-referential recap lane`). Proven:
```
SELFREF inject substring probes:
  does NOT match getaway anchor ("full-catalogue retrieval ran")
  does NOT match intent anchor ("intent-margin classifier")
  contains "self-referential recap lane"  — but the audit does NOT look for it
```
`audit_skill_usage.py` is UNMODIFIED in this working tree (last commit `496dcac`, predates the release). **Consequence:** an authorized selfref-skip turn followed by `SKIPPING:` would be tallied by the audit as a **false_skip**, not `authorized_skip` — the exact miscount ADR-0019/phase-05 warned about.

**Classification: REAL, but consistent with the intended split — NOT a Subject A defect.**
- ADR-0019 (Consequences, `:66-67`) explicitly defers this: *"The audit gains a 3rd authorized-skip anchor … (telemetry-dev task; **dispatched after this signature lands**)."* The signature has landed in enforcer.py; the audit wiring is a separate downstream task by design.
- The audit's own comment (`:173-174`) says it "Fails SAFE: … under-count authorized (over-flag false), never the reverse" — so the gap degrades a metric conservatively, it does not bless a dodge.
- **Tension to flag to the Lead:** phase-05 Success Criteria (`:45-46`) list the audit anchor + an audit-side parity test AS H5 deliverables, while ADR-0019 defers them. If phase-05 is the acceptance contract, H5 is **incomplete** on the audit leg; if ADR-0019's deferral governs, H5-source is complete and the audit is a pending telemetry-dev dispatch. This is a documentation/scope conflict for the Lead to resolve — not a code correctness bug in enforcer.py.

### 8.2 [FIXTURE-ARTIFACT] ADR "~82 would-drops" vs observed 85 (H4 step branch)
ADR-0023 says ~82 numbered-step would-drops; I observe 85. Live corpus grew since the ADR was written. Not a defect.

### 8.3 [FIXTURE-ARTIFACT] Two phrase-count harnesses report different totals (3956 vs 2688)
`h4_shadow_scan.py` (single import, counts regex-matches post-extraction) vs `h4_byteident.py` (per-mode module reload through the full pipeline). The reload-based figure (2688) is the authoritative extracted-set size; both agree shadow==off. Harness-counting difference, not a code discrepancy.

### 8.4 [EXPECTED — not a defect] H4 not live in the venv
The venv `skills_discovery.py` differs from source; engine marker `0.13.1`. H4 (and H2/H5) are source-only until Phase-7 deploy. Stated in the task and anti-dodge-doc §5 caveat 5.

---

## 9. Verdict per subject

| Subject | What | Verdict | Key cited byte |
|---------|------|---------|----------------|
| **A** `enforcer.py` H5 | selfref lane + flag + 3rd SKILL-CHECK + task-verb veto | **PASS** | fire→`SKILL-CHECK: … self-referential recap lane …`; 3 bypasses no-signature; flag-off routes normally; my 10 adversarial bypasses all rejected |
| **B** `doctrine.py` H3 | agent_id-scoped suppression, fail-toward-inject | **PASS** | agent_id→0 bytes; top/persona/malformed/empty→7530-byte inject; flag-off md5 identical `d8a898ca…`; 11/11 `_is_subagent` edge cases |
| **C** `skill-first.md` H2 | red-flags table, forbidden phrase absent | **PASS** | `rg "self-referential recap lane"` exit 1; 7 table rows; row 7 uses "OVER-fire lane"; MANDATE↔table 3-refutation consistency |
| **D** `skills_discovery.py` H4 | shadow-default purity lint, byte-identical | **PASS** | shadow==off True (2688==2688); active drops 82; process-branch 0 live drops; integration fail is server.py, unrelated |

**Cross-file caveat (§8.1):** the H5 audit anchor is NOT wired (audit unmodified). Per ADR-0019 this is a deferred telemetry-dev dispatch (design-intended); per phase-05 Success Criteria it is an unmet H5 deliverable. Route the scope reconciliation to the Lead. It does not weaken any Subject A/B/C/D code verdict above.

**Overall:** the four source subjects behave exactly as their ADRs claim. Deploy currency (source==deployed) is a separate Phase-7 gate, correctly NOT yet satisfied.
