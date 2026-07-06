# Gate-2 Raw-Evidence Report — Anti-Dodge Integration (Audit domain + cross-file wiring)

**To:** Lead · **From:** independent verify-as-claimed validator (separate party, no build stake)
**Date:** 2026-07-06 15:55 +07
**Repo/cwd:** `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge` · **Branch:** `main`
**Discipline:** READ-ONLY on subjects. All audit/harvest runs redirected to `/tmp` temp `PROJECTS` stores + gitignored sinks; real `~/.claude/projects` mtime unchanged before/after (proof §7). No subject file modified by this pass.

**VERDICT: GO** for the audit domain + integration source. The cross-file enforcer→audit contract is CLOSED. Two non-code items to route: (1) a stale `:176-178` doc reference in `enforcer.py`; (2) the integration is UNCOMMITTED working-tree state (correct per task, but the Lead should know the commit boundary). Deploy (Phase 7) correctly NOT done.

---

## Executive summary — per-area

| Area | Verdict | Cited raw byte |
|------|---------|----------------|
| **Selftests (5, all green together)** | PASS | `audit --selftest OK: false-SKIPPING verdict + H1 harvest filter + SELFREF parity` EXIT=0; enforcer/doctrine/analyze all EXIT=0; vendor `25 passed, 1 deselected` EXIT=0 |
| **Cross-file contract (THE gate-2 test)** | PASS | live `SELFREF_SKIP_MSG` → `_is_authorized_skip_line`=True (counted `authorized_skip`); e2e `audit()`: `authorized_skip=2 false_skip=2`, selfref turn `saw_marker=True`; SELFREF clause EXCLUDED from harvest corpus; bare-doctrine marker `saw_marker=False` (no over-match) |
| **H3 two-legs coherence** | PASS | doctrine `agent_id` → empty stdout (suppress); persona `agent_type` → inject; audit e2e: `ON organic Skill-tool=1` (subagent+dispatched excluded), `global total=3` (whole), `dispatch_sessions=['sess-teammate-D']`, revert widens to 3 |
| **H1 harvest safety** | PASS | `.gitignore:5 logs/skill-rationalizations*.txt`; `git check-ignore` exit=0; scrub redacts `/Users/<user>`,`<email>`,`<token>`,`<hex>`; harvest capped to `SKIPPING:` clause; meta+authorized excluded |
| **Anti-drift** | PASS | single `_AUTHORIZED_SIGNATURES` tuple (`:89-90`); count-side `_is_authorized_skip_line` AND harvest-side `_looks_authorized` BOTH reference it (`:102`,`:201`); no 2nd production signature list |
| **driftcheck** | PASS | `IN SYNC: every fact matches its source of truth` EXIT=0; `version: SSOT = '0.13.1'` |

**Discrepancies:** 1 real-but-cosmetic (stale `:176-178` comment ref, §7). 1 scope note (integration is uncommitted working-tree, §8). Zero code defects. The prior Gate-1 report's §8.1 "REAL GAP — audit lacks the H5 selfref anchor" is now **RESOLVED** in the working tree (§2).

---

## 1. Selftest sweep — all five green TOGETHER (raw + exit)

Engine venv: `$HOME/.local/share/skill-concierge/venv` → Python 3.12.13 (`setup.sh:18`).

```
=== 1. enforcer --selftest ===
enforcer --selftest OK: refusal guard (5 fire / 6 silent) + ranked-mandate %-share + actionability imperative-veto (17 fire / 12 off) + keepoff-drop + gap-collapse + per-skill-tau/deterministic-routes (default-inert) + authorized-skip tier (3 injects on / silent-off) + selfref over-fire lane (6 fire / 6 off)
EXIT=0

=== 2. doctrine --selftest ===
doctrine --selftest OK: subagent(agent_id) suppressed + top-level/persona(agent_type)/malformed/empty all inject (fail toward injection) + flag-off byte-identical
EXIT=0

=== 3. audit --selftest ===
audit --selftest OK: false-SKIPPING verdict + H1 harvest filter + SELFREF parity
EXIT=0

=== 4. analyze --selftest ===
analyze --selftest OK: offer->take join (turn conversion + per-skill)
EXIT=0

=== 5. vendor pytest -m "not integration" (engine venv) ===
collected 26 items / 1 deselected / 25 selected
tests/test_discovery.py .................                                [ 68%]
tests/test_indexing.py ........                                          [100%]
======================= 25 passed, 1 deselected in 0.95s =======================
EXIT=0
```

The audit selftest string is the load-bearing new evidence: **`+ SELFREF parity`** did NOT exist in the Gate-1 report (the audit was unmodified there, last commit `496dcac`). The SELFREF leg is now wired.

---

## 2. THE cross-file contract (the key Gate-2 test) — enforcer→audit closed

**Oracle:** derived by loading the LIVE `enforcer.py` module and pulling its actual `SELFREF_SKIP_MSG` / `GETAWAY_SKIP_MSG` / `INTENT_SKIP_MSG` constants — not a hand-typed string.

Live message (byte-exact):
```
'SKILL-CHECK: this turn only asks you to explain/rephrase your own immediately-prior message — the self-referential recap lane — with no external task, so no skill applies. SKIPPING: none is pre-authorized; no further search_skills needed.'
```

### 2a. Helper-level classification (`_is_authorized_skip_line`, count-side)
```
[PASS] expect=True  got=True   SELFREF inject line
[PASS] expect=True  got=True   GETAWAY inject line
[PASS] expect=True  got=True   INTENT inject line
[PASS] expect=False got=False  bare doctrine marker (no signature)      ← "| a SKILL-CHECK: line marks the AUTHORIZED-SKIP tier ... |"
[PASS] expect=False got=False  signature w/o SKILL-CHECK marker (prose) ← "we added the self-referential recap lane this session"
```
The SELFREF line is counted `authorized_skip`; the bare doctrine Red-Flags line (marker text, NO signature) is NOT (over-match guard holds); a signature echoed in prose WITHOUT the `SKILL-CHECK:` marker is NOT (both-conditions AND).

### 2b. End-to-end `audit()` file-walk over a temp `PROJECTS` store (4 realistic transcripts)
Fixtures: (s1) top-level session, assistant echoes the live SELFREF `SKILL-CHECK:` line then a `SKIPPING:` reply, no search; (s2) genuine false-skip; (s3) getaway authorized line + SKIPPING; (s4) bare doctrine marker line + SKIPPING.
```
false_skip     = 2
lawful_skip    = 0
authorized_skip= 2

turn sid=sess-doctrine-0004   saw_skip=True saw_marker=False ...   ← bare marker: false_skip (correct)
turn sid=sess-falseskip-0002  saw_skip=True saw_marker=False ...   ← genuine: false_skip
turn sid=sess-getaway-0003    saw_skip=True saw_marker=True  ...   ← getaway: authorized
turn sid=sess-selfref-0001    saw_skip=True saw_marker=True  ...   ← SELFREF: authorized (THE fix)
```
Assertions all PASS: `authorized_skip==2`, `false_skip==2`, SELFREF turn `saw_marker=True` (**NOT** false_skip — the exact miscount ADR-0019/phase-05 warned about is now prevented), bare-doctrine turn `saw_marker=False` (no over-match).

### 2c. Harvest corpus excludes SELFREF (H1 side of the same contract)
```
corpus: {"SKIPPING: none - I'll just do it.": 1, "SKIPPING: none - I already know how to do this...": 1}
[PASS] SELFREF clause EXCLUDED from harvest corpus
[PASS] getaway clause EXCLUDED from harvest corpus
[PASS] genuine false-skip IS harvested
```
An authorized (selfref/getaway) turn never enters the harvest (it is not a false-skip turn at all — `saw_marker=True`), so H2 will never author a refutation of the excuse H5 just authorized. Contract closed on BOTH the count leg and the harvest leg.

**Signature-in-sync check (audit tuple ↔ enforcer messages):** all 3 `_AUTHORIZED_SIGNATURES` entries are present in a live enforcer message (`full-catalogue retrieval ran`, `intent-margin classifier`, `self-referential recap lane` → all PASS).

---

## 3. H3 two-legs coherence

### 3a. Leg 1 — `doctrine.py` `agent_id` suppression (re-confirmed)
```
(a) {"source":"startup","agent_id":"abc123"}          -> empty stdout (SUPPRESS)  exit=0
(b) {"source":"startup"}                               -> {"hookSpecificOutput":...additionalContext":"#... (INJECT)  exit=0
(c) {"source":"startup","agent_type":"Explore"}        -> INJECT (must NOT suppress on agent_type)  exit=0
```
Keyed on `agent_id` (`doctrine.py:71,86`), fail-toward-inject on parse error (`:22` comment, positive-proof-only).

### 3b. Leg 2 — audit-side exclusion (subagent per-file + dispatched phrase), e2e file-walk
Fixtures: normal top-level (Skill-tool + USING); subagent file under `.../subagents/` with `isSidechain:true`; dispatched teammate (own sid, carries `"You have been spawned as a teammate"`).
```
global Skill-tool total (whole):   3
dispatch_sessions flagged:         ['sess-teammate-D']
ON  organic Skill-tool=1  organic USING=1        ← only NORMAL counts organic
OFF organic Skill-tool=3  organic USING=3        ← revert re-includes subagent+dispatched
[PASS] ON organic Skill-tool == 1 (only normal)
[PASS] global Skill-tool total == 3 (whole, unchanged)
[PASS] dispatched session flagged
[PASS] OFF dispatch_sessions empty (revert lifts dispatch scan)
```
Subagent (per-FILE `subagents/` path + `is_sub`, `audit:255,276`) and dispatched (`_DISPATCH_MARKERS` phrase match, `:81,268`) are both excluded from the ORGANIC denominator while GLOBAL totals stay whole. Normal session included. `SKILL_SUBAGENT_STOP=0` reverts. Both legs coherent.

---

## 4. H1 harvest data-safety

```
.gitignore:2  logs/
.gitignore:5  logs/skill-rationalizations*.txt          ← explicit glob (in addition to logs/)
git check-ignore -v logs/skill-rationalizations.txt -> .gitignore:2:logs/  exit=0
```
Scrub (`_scrub`, `audit:190-194` / `_SCRUB` `:110-116`):
```
[PASS] /Users/thinhkhuat/secret/proj      -> /Users/<user>/secret/proj
[PASS] bob@example.com                     -> <email>
[PASS] sk-ABCDEFGHIJ1234567890             -> <token>
[PASS] deadbeef...12 (32-hex)              -> <hex>
[PASS] /home/alice/repo                    -> /home/<user>/repo
```
Actual `--harvest` over a temp store: genuine false-skip captured (scrubbed to `/Users/<user>/x`), meta-session (`enforcer` keyword) excluded, output line = the `SKIPPING:` clause ONLY (no surrounding task text). Cap-to-clause is enforced at the match site (`audit:356-358`, `txt[ls:le]`). Data-safety requirements from phase-03 / ADR-0021 all met.

---

## 5. Anti-drift (the 2-vs-3 signature fix)

```
audit_skill_usage.py:89-90  _AUTHORIZED_SIGNATURES = ("full-catalogue retrieval ran",
                                                      "intent-margin classifier",
                                                      "self-referential recap lane")
:102  _is_authorized_skip_line  -> "return AUTHORIZED_SKIP_MARKER in line and any(s in line for s in _AUTHORIZED_SIGNATURES)"   [count-side]
:201  _looks_authorized         -> "return any(sig in clause for sig in _AUTHORIZED_SIGNATURES)"                                 [harvest-side]
```
`rg` for the three signature literals in the file: the ONLY production occurrence is the single tuple at `:89-90`. The other hits (`:418,:433-436`) are inside the `--selftest` fixtures, which deliberately reconstruct the enforcer messages as test oracles (correct — a drift-detector SHOULD hardcode the expected strings). No second production signature list exists → the 2-vs-3 drift is structurally impossible. `_skip_verdicts` (`:167-187`) has NO filesystem/os access → still PURE (the phase-03 non-functional requirement).

---

## 6. driftcheck

```
IN SYNC: every fact matches its source of truth.   EXIT=0
[info]  version: SSOT = '0.13.1' (from .claude-plugin/plugin.json)
[ok]    marketplace.json / CHANGELOG.md / README.md all match SSOT '0.13.1'
skill-list-parity OK: 4 on-disk skills [doctor, setup, skill-search, skill-usage-audit]
```
Version still `0.13.1` — correct, pre-Phase-7.

---

## 7. Stale-comment pin (item 7) — exact locations for the Lead to fix

| Ref | Exact current line | Says | Reality |
|-----|-------------------|------|---------|
| **Stale ref** | `hooks/scripts/enforcer.py:356` | `# a LOCKED cross-file contract — the audit (audit_skill_usage.py :176-178) matches this exact` | `:176-178` is now INSIDE the `_skip_verdicts` docstring/init (`false_skip = lawful_skip = authorized_skip = 0`), NOT a matcher |
| **Actual matcher (count-side)** | `audit_skill_usage.py:93` def + `:102` body + invoked at **`:289-290`** | `if _is_authorized_skip_line(line): cur["saw_marker"] = True` | This is where the audit ACTUALLY matches the enforcer signature |
| **Reciprocal (fine)** | `enforcer.py:79-80` | `# CROSS-FILE CONTRACT: skills/skill-usage-audit/scripts/audit_skill_usage.py (Phase 3) joins its false-skip exclusion on this exact literal.` | Correct — no line number, points at the file. No fix needed. |

**Fix for the Lead:** change `enforcer.py:356` `:176-178` → `_is_authorized_skip_line` (or `:93/:289`). Cosmetic doc drift only; zero runtime impact (the code binds by function, not line number).

---

## 8. READ-ONLY / no-side-effect proof + scope note

- Real `~/.claude/projects` dir mtime **unchanged** before/after (`1783310817` → `1783310817`). All audit/harvest runs used temp `PROJECTS` stores under `/tmp/gate2_*`.
- No subject file modified by this pass. `git status` shows only the pre-existing anti-dodge build changes + untracked ADRs/plans; my fixtures are `/tmp/gate2_*.py` only.
- **Scope note (route to Lead):** the audit integration validated here is **uncommitted working-tree** state. `git show HEAD:...audit_skill_usage.py` (commit `496dcac`) contains NEITHER `_AUTHORIZED_SIGNATURES` NOR `self-referential recap lane` — `git diff --stat HEAD` = `232 insertions(+), 27 deletions(-)`. This matches the task framing ("source working tree, NOT deployed"); the source-of-truth is the working tree, which is what I validated. The Lead should confirm this lands in a commit before Phase-7 deploy.

---

## 9. Discrepancies — real-defect vs fixture-artifact

| # | Item | Classification |
|---|------|----------------|
| 9.1 | `enforcer.py:356` references audit `:176-178`; actual matcher is `_is_authorized_skip_line` (`:93`/`:289`) | **REAL but cosmetic** (doc drift, no runtime effect). Fix the ref. |
| 9.2 | Prior Gate-1 report §8.1 "audit lacks the H5 selfref anchor" | **RESOLVED** in working tree — the anchor is now wired (§2). Prior report was accurate for commit `496dcac`; the audit was updated afterward (uncommitted). |
| 9.3 | Integration is uncommitted working-tree (232 insertions vs HEAD) | **Not a defect** — matches task framing. Scope/commit-boundary note for the Lead (§8). |
| 9.4 | Signature literals appear at `:418,:433-436` besides the `:89-90` tuple | **Not drift** — those are `--selftest` oracles, correctly hardcoded to catch drift. |

**Overall:** the audit domain + the enforcer→audit integration behave exactly as ADR-0019/0020/0021 and phase-02/03/05 claim. The cross-file contract that could not be tested until now is CLOSED on both the count and harvest legs. GO for source. Deploy currency (source==deployed) is a separate Phase-7 gate, correctly NOT yet satisfied (venv + plugin.json still `0.13.1`).
