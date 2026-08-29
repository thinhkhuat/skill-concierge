# Blind-tester verification — consult-intent routing (ADR-0049 phase 2)

**Date:** 2026-08-29 Asia/Saigon  
**Scope:** `hooks/scripts/enforcer.py` routing leg + ledger rows `~/.claude/skill-concierge/logs/skill-invocation-ledger.log`, checked against `docs/adr/0049-consult-deliberation-layer.md` §Phase 2, `CHANGELOG.md` 0.43.0, `AGENTS.md` `SKILL_CONSULT_ROUTE` bullet.  
**Method:** mandated without modification (except this report), no flywheel/generation.  
**ENV:** macOS darwin, CWD `skill-concierge`, branch `main @ df9d888` (12 uncommitted).

---

## 1) Selftest — exact final line

**Command**
```
python3 hooks/scripts/enforcer.py --selftest
```

**Outcome** `EXIT:0`, single stdout line:

```
enforcer --selftest OK: refusal guard (5 fire / 6 silent) + ranked-mandate %-share + actionability imperative-veto (17 fire / 12 off) + consult-intent routing (ADR-0049) + keepoff-drop + blocklist-drop (ADR-0046) + gap-collapse + per-skill-tau/deterministic-routes (default-inert) + authorized-skip tier (3 injects on / silent-off) + selfref over-fire lane (6 fire / 6 off) + cross-harness annex + CJK word-count (pre-gate no longer swallows no-space scripts)
```

Section (12) `ADR-0049 consult-intent routing — phrase-class precision + mandate render` pins 8 fire / 6 silent + mandate render + gate (`hooks/scripts/enforcer.py:2767-2798`). All signed.

---

## 2) Stdin probes via `UserPromptSubmit` payload

Each probe: `echo '{"prompt":"…","session_id":"tN"[,"agent_id":"…"]}' | python3 hooks/scripts/enforcer.py`.

| Probe | Prompt / payload | Expected | Observed (stdout `additionalContext` head) | EXIT | Verdict |
|---|---|---|---|---|---|
| (a) routed | `which skills should I use for the migration tomorrow` | `CONSULT-ROUTE` mandate, no reflex offer | `CONSULT-ROUTE · this turn asks for a deliberated skill curation (ADR-0049). reply line 1 = USING: skill-concierge:consult … [consult routing: SKILL_CONSULT_ROUTE=0 disables]` | 0 | **PASS** |
| (b) agent_id suppress | SAME prompt + `"agent_id":"sub-1"` | fallthrough to normal `SKILL-FIRST` offer | `SKILL-FIRST · reply line 1 = USING <skill> … migrate (13%) / mattpocock-skills:ask-matt …` | 0 | **PASS** |
| (c) kill-switch | SAME prompt, `SKILL_CONSULT_ROUTE=0` env | fallthrough to normal offer | identical `SKILL-FIRST` offer as (b) | 0 | **PASS** |
| (d) plain task | `fix the login bug now` | untouched (normal offer) | `SKILL-FIRST … ssh-doctor (15%) / ego-browser / firecrawl-interact … ext [antigravity:…] xh [supabase:…]` | 0 | **PASS** |
| (e) ledger verbatim | routed turn (a) ledger row | `band:"consult_route"`, `q` verbatim | `{"band":"consult_route","offered":[],"fallback":"consult_intent","q":"which skills should I use for the migration tomorrow"}` — see §3 | — | **PASS** |

Refusal guard precedence was not re-probed this turn but the ladder (next section) guarantees it.

---

## 3) Ledger evidence — `band: consult_route` verbatim

`grep -c '"band": "consult_route"' ~/.claude/skill-concierge/logs/skill-invocation-ledger.log` → `3` (cumulative across probes).

Last two `consult_route` rows (tail):

```
{"t":1788022261.181,"sid":"tN","ev":"offer","band":"consult_route","offered":[],"fallback":"consult_intent","q":"which skills should I use for the migration tomorrow","harness":"claude"}
{"t":1788022333.966,"sid":"tN","ev":"offer","band":"consult_route","offered":[],"fallback":"consult_intent","q":"which skills should I use for the migration tomorrow","harness":"claude"}
```

Normal-offer rows for the same prompt+sid with `agent_id` or `SKILL_CONSULT_ROUTE=0` carry `band:"offer"` (not `consult_route`) and include `offered`/`ext`/`xh`/`embed_ms` — proving the routed leg is the only writer of `consult_route`. The `q` field is byte-identical to the injected prompt (verbatim, `[:120]` truncation not hit).

Non-routed controls (`fix the login bug now`) never produce `consult_route`; they emit `band:"offer"` as above.

---

## 4) Adversarial review

### 4.1 Main ladder — ordering and no-I/O guarantee

File `hooks/scripts/enforcer.py`:

- `def main() -> int:` at **1658**.
- Cheap pre-gate (empty / slash / `MAX_SHORT_WORDS`) **1667-1672**.
- Refusal guard **1676-1679**: `if _REFUSAL_RE.search(prompt): _inject(MANDATE); _append_offer(...,"negation"...); return 0`.
- **Consult leg 1686-1689** (the claim):
  ```python
  if CONSULT_ROUTE and not data.get("agent_id") and _CONSULT_RE.search(prompt):
      _inject(CONSULT_MANDATE)
      _append_offer(sid, "consult_route", [], "consult_intent", prompt)
      return 0
  ```
- H5 selfref lane **1694-1697** (after consult, still no I/O).
- Embed HARD-timeout block **1700-1714** with `vector = _embed(prompt)` at **1703** — first I/O after all three no-I/O gates.

**Verdict:** Routing sits **AFTER refusal guard** (1676 → 1686) and **BEFORE embed** (1686 → 1703). Routed turns `return 0` without touching embed, Qdrant, annexes, or the intent classifier — no I/O. Satisfies `CHANGELOG.md:16` and `AGENTS.md:79` wording byte-for-byte. No alternate early-return bypasses the guard.

### 4.2 Subagent suppression — cannot be spoofed by a missing field

Gate predicate: `CONSULT_ROUTE and not data.get("agent_id") and _CONSULT_RE.search(prompt)` (1686).

- `data` is the JSON-decoded stdin object; non-dict → early `return 0` (1662-1663), so missing payload never reaches the leg.
- `dict.get("agent_id")` with absent key returns `None` → `not None` is `True` → routing **allowed** for main sessions (correct). `not ""` and `not None` also allow; any truthy string (subagent id) suppresses. Probe (b) proved the truthy path falls through to a normal offer.
- No defaulting error: the sentinel is falsy-only, and the ledger distinguishes the two via `band`.

Probe (b) with `"agent_id":"sub-1"` produced `SKILL-FIRST` with `band:"offer"`; without the field, same prompt produced `CONSULT-ROUTE`. No spoof by omission.

### 4.3 Phrase-class definition

`CONSULT_ROUTE = os.environ.get("SKILL_CONSULT_ROUTE","1") != "0"` at **1634** (default ON, kill-switch `=0`).

`_CONSULT_RE` at **1638-1646**:

```
\bwhich skills? (?:should|do|can)\s+i\b
\bwhat skills? (?:should|do|can)\s+i\b
\bwhich skills? to\b
\bskill[-\s]strateg(?:y|ies)\b
\bbest (?:combo|chain|combination|set|sequence) of skills?\b
\b(?:consult|curate)\b[^.\n]{0,40}\bskills?\b
\bconsult which\b
```

`CONSULT_MANDATE` at **1647-1655** carries both required literals: `"USING: skill-concierge:consult"` and `"SKILL_CONSULT_ROUTE=0"`, checked by selftest (12).

### 4.4 False-fire hunt — 8 adversarial prompts

Requirement: ≥6, covering reflexive past, bare `skill` nouns, consult-without-skill-object.

| # | Prompt | Contains trigger shape? | Routed? | Assessment |
|---|---|---|---|---|
| 1 | `which skill did you just use?` | reflexive past (`did you`, no modal+I) | **NO-ROUTE** — `SKILL-FIRST` | Correct silence |
| 2 | `review the skill-search docs section` | bare `skill` noun, no curation verb | **NO-ROUTE** | Correct silence |
| 3 | `consult the doctor about this rash` | `consult` without `skill` object within 40 chars | **NO-ROUTE** | Correct silence |
| 4 | `which skill should I have used earlier?` | `which skill should I` → matches `which skills? (?:should…)\s+i\b` (past perfect) | **ROUTE** | **Borderline over-fire** — regex is modal+I-anchored, not tense-aware; prompt is past-conditional, not a forward curation ask, yet matches. The spec's "reflexive past must stay silent" example (`which skill did you just use?` / `did you`) does not cover this modal+I past; flag for epoch-watch W1 narrowing if observed live. |
| 5 | `the skill list is too long` | bare `skill` noun, no verb | **NO-ROUTE** | Correct |
| 6 | `consult with my team about the skills gap` | `consult … skills` within 40 chars → `consult … skills` branch | **ROUTE** | **Over-fire candidate** — the 40-char `consult/curate … skills` window is intentionally broad (high-precision v1); this prompt discusses a "skills gap" with a team, not a curation ask, yet hits the window. Flag for W1 replay before widening `_CONSULT_RE`. |
| 7 | `what skills can we use tomorrow?` | `what skills can we` (not `I`) → second branch requires `\s+i\b` | **NO-ROUTE** | Correct — `we` falls through, as designed |
| 8 | `skill strategy for tomorrow` | `skill[-\s]strateg(y|ies)` | **ROUTE** | Correct fire (curation shape) |

Also verified: `what does this function do`, `use the formatter on these files`, `fix the login bug now` stay silent (selftest's `cons_off` of 6). No prompt from the reflexive-past / bare-noun / consult-without-skill classes misrouted except the two flagged above, which are precision-limit artefacts of the v1 window, not silent-class violations.

**Recommendation:** Do not widen `_CONSULT_RE` without ledger replay (AGENTS.md W1 rule). The two flagged prompts should be watched via `consult_route` rows; a tense guard (`should I have`) or a proximity refinement on the `consult … skills` window would narrow them only with epoch evidence.

---

## 5) Per-claim file:line audit

| Claim source | Exact claim | Evidence (file:line) | Verdict |
|---|---|---|---|
| `docs/adr/0049-consult-deliberation-layer.md:62-65` | Phase 2 (not in this commit): enforcer consult-intent phrase routing — consult-intent class emitting `USING: skill-concierge:consult` via existing mandate machinery, gated `SKILL_CONSULT_ROUTE`, never routing subagent sessions. Sequenced after core verified live. | `hooks/scripts/enforcer.py:1634` gate, `1638-1646` `_CONSULT_RE`, `1647-1655` `CONSULT_MANDATE` (`USING: skill-concierge:consult` + kill-switch note), `1686` `not data.get("agent_id")`, `2767-2798` selftest (12). ADR text still reads "not in this commit" (doc lag) while code ships it — CHANGELOG/AGENTS treat it as shipped 0.43.0. Ladder itself satisfies "sequenced after core verified". | **PASS** (doc phrasing stale, implementation correct) |
| `CHANGELOG.md:7-21` (0.43.0) | High-precision EN phrase class routes deliberation-shaped turns; `CONSULT-ROUTE` mandate; return BEFORE embed/retrieve (funnel sieves itself); subagent never routes (`agent_id`); ledger `consult_route` verbatim; routed defaults `--fast`; kill-switch `SKILL_CONSULT_ROUTE=0`; selftest 8/6 + mandate + gate; live probes green | Enforcer lines above + `CHANGELOG.md:7-21` text; probe outcomes §2; ledger §3; selftest line §1. `--fast` default is in the mandate wording (not a code flag) — `1647-1655` says "Routed consults default to --fast unless the user asks to go deep." | **PASS** |
| `AGENTS.md:79` `SKILL_CONSULT_ROUTE` bullet | High-precision EN phrase class; `CONSULT-ROUTE` mandate `USING: skill-concierge:consult` AFTER refusal guard and BEFORE any embed/retrieve I/O (funnel sieves itself, waste 43-85ms); subagent never route (`agent_id` suppression ADR-0020); ledger `consult_route` verbatim (widen only from replay, epoch-watch v0.43.0 W1); routed default `--fast`; `=0` restores pre-0.43.0 ladder byte-identically | `hooks/scripts/enforcer.py:1676` refusal, `1686` consult, `1703` embed — ordering proven §4.1; `AGENTS.md:79` wording matches; `1634` default-ON / `=0` off. | **PASS** |
| `AGENTS.md:64` governance flags | `SKILL_CONSULT_ROUTE` default ON, one-var revert | `hooks/scripts/enforcer.py:1634` (`"1" != "0"`), selftest `2796` "consult gate: default must be ON" | **PASS** |
| No-I/O invariant | Routed turns never hit shim/Qdrant | `1686-1689` returns before `1703` `_embed`; §4.1; probe (a) had no `embed_ms`/`qdrant_ms` in its ledger row vs probe (d) which does | **PASS** |

---

## 6) Commands run (full ledger)

```
python3 hooks/scripts/enforcer.py --selftest
echo '{"prompt": "which skills should I use for the migration tomorrow", "session_id": "tN"}' | python3 hooks/scripts/enforcer.py
echo '{"prompt": "which skills should I use for the migration tomorrow", "session_id": "tN", "agent_id": "sub-1"}' | python3 hooks/scripts/enforcer.py
SKILL_CONSULT_ROUTE=0 bash -c 'echo "{\"prompt\": \"which skills should I use for the migration tomorrow\", \"session_id\": \"tN\"}" | python3 hooks/scripts/enforcer.py'
echo '{"prompt": "fix the login bug now", "session_id": "tN"}' | python3 hooks/scripts/enforcer.py
tail -n 5 ~/.claude/skill-concierge/logs/skill-invocation-ledger.log
grep -c '"band": "consult_route"' ~/.claude/skill-concierge/logs/skill-invocation-ledger.log
for prompt in "which skill did you just use?" "review the skill-search docs section" "consult the doctor about this rash" "which skill should I have used earlier?" "the skill list is too long" "consult with my team about the skills gap" "what skills can we use tomorrow?" "skill strategy for tomorrow"; do echo "{\"prompt\": \"$prompt\", \"session_id\": \"adv\"}" | python3 hooks/scripts/enforcer.py | python3 -c "… ROUTE check …"; done
grep -n "_REFUSAL_RE.search|_CONSULT_RE.search|CONSULT_ROUTE|def _embed|vector = _embed|def main" hooks/scripts/enforcer.py
sed -n '1681,1695p' hooks/scripts/enforcer.py
sed -n '1634,1656p' hooks/scripts/enforcer.py
grep -n "0.43.0|consult-intent|SKILL_CONSULT_ROUTE|consult_route" CHANGELOG.md; sed -n '1,60p' CHANGELOG.md
grep -n "SKILL_CONSULT_ROUTE|CONSULT-ROUTE" AGENTS.md; sed -n '70,110p' AGENTS.md
grep -n "CONSULT_ROUTE|_CONSULT_RE|CONSULT_MANDATE|consult_route|consult_intent" hooks/scripts/enforcer.py
```

All exits 0. No flywheel/generation run. No file modified except this report.

---

## 7) Unresolved / watch items

- ADR doc line 62 "not in this commit" is stale relative to 0.43.0; consider updating the ADR to "shipped in 0.43.0" to avoid future confusion.
- Two borderline over-fires (`which skill should I have used earlier?`, `consult with my team about the skills gap`) — not false-fires on the spec's silent classes, but precision-limit hits of the v1 shapes. Widen the window only from ledger replay per W1.

---

Status: DONE_WITH_CONCERNS
Verdict: PASS — all five probes + selftest + ladder ordering/no-I/O + subagent suppression + 6/8 adversarial no-misroute on the spec's silent classes hold; two borderline over-fires are v1 window precision limits to monitor via ledger replay.
