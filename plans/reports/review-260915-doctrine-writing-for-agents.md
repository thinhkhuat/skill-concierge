# Review — SKILL-FIRST doctrine and enforcer strings against `writing-for-agents`

Reviewer: independent (did not write the text). Date: 2026-09-15.
Reference: `/Users/thinhkhuat/.claude/skills/writing-for-agents/SKILL.md` (read in full).
Targets: `hooks/doctrine/skill-first.md` body between the markers (lines 13–118); `hooks/scripts/enforcer.py` injected strings (`MANDATE` :1227, `GETAWAY_SKIP_MSG` :1308, `INTENT_SKIP_MSG` :1315, `SELFREF_SKIP_MSG` :1324, `HARNESS_SKIP_MSG` :1351, `CONSULT_MANDATE` :1888, `_chain_hint` :1086, `_ranked_mandate` :1700–1782).
Comparison copy `/tmp/sc_audit/skill-first.md.bak` was read for the diff only; the old text was not treated as the standard.

## Hard-constraint checks (all pass)

| Check | Result | Evidence |
|---|---|---|
| Four `_AUTHORIZED_SIGNATURES` absent from the body | PASS | `grep -i` over the body for all four phrases: no match (exit 1) |
| Four signatures present in their enforcer strings | PASS | enforcer.py:1309 "full-catalogue retrieval ran", :1316 "intent-margin classifier", :1326 "self-referential recap lane", :1354 "harness-message lane" |
| Bare `SKILL-CHECK:` in body | PASS (allowed) | body lines 51, 78, 106; `AUTHORIZED_SKIP_MARKER = "SKILL-CHECK:"` enforcer.py:723 |
| `search_skills`, `extra_queries`, `get_skill` resolve | PASS | `vendor/skill-search/skill_search/server.py:817` `def search_skills(query, extra_queries=None)`; :921 `def get_skill(name)` |
| `/skill-concierge:skill-search` resolves | PASS | `skills/skill-search/` exists |
| `CHAIN-HINT` marker resolves | PASS | enforcer.py:1094 |
| `tests/test_doctrine_text.py` | not run by me; its assertions (no `find-skills`, no `~NNN`, no `ADR-`, no `v0.x`) are satisfied by inspection of the body |

## Findings (most severe first)

### F1 — HIGH — Rule 5 broke the OMP harness rewrite: OMP agents are now told to call `get_skill`, which that harness does not expose

- Where: `hooks/doctrine/skill-first.md:62` — `` `USING: <name>` for one means `get_skill("<name>")` ``.
- Lever: **Pruning: cache vs environment** and **single source of truth**. The body caches a harness-specific consumption call; `hooks/scripts/doctrine.py:198-200` string-replaces the exact literal `get_skill("<alias>:<skill>")` → `read("skill://<alias>:<skill>")` for OMP. The rewrite is a hidden coupling to the body's bytes, and the rewording (old body line 65 had the literal; new body has `get_skill("<name>")`) silently detached it.
- Proof (run this session, `SKILL_CONCIERGE_HARNESS=omp`, real body through `_harness_adapt`):
  ```
  'get_skill(': 1
  'skill://': 0
  ```
  The `doctrine.py --selftest` still passes (exit 0) because its OMP pin at doctrine.py:296-297 adapts a synthetic `_sample` string, not the real body. The pin cannot catch this class of drift.
- Effect: an OMP agent following rule 5 calls a tool that does not exist on its harness; the doctrine's own docstring (doctrine.py:88-91) says OMP consumes skills via `read("skill://…")`.
- Replacement (harness-neutral, removes the coupling): 
  > **Candidates marked NOT invocable here still count** — an external-catalog hit or a hit installed under another harness. `USING: <name>` for one means pull its SKILL.md the way its row tells you and follow it inline as your procedure. Same take-bar as installed skills; the marker records provenance, not a lower tier of obligation.

  The per-turn annex/foreign blocks (enforcer.py:1763-1766, 1771-1776) and the search row's own `note` (server.py:808-809) already carry the concrete call at the point of need. If the harness-specific literal must stay in the body, then (a) restore the exact replace target and (b) change the selftest to run the OMP branch on the real body and assert `"get_skill(" not in out`.
- Side observation (outside the review target, reported not scored): `enforcer.py` has no OMP rewrite at all (`grep skill:// hooks/scripts/enforcer.py` → nothing), so the per-turn annex/foreign blocks say `get_skill` under OMP too. The neutral wording above does not fix that; it only stops the doctrine from making it worse.

### F2 — HIGH — The lawful-skip set is stated in five places with three different contents, and the enforcer's getaway leg admits a class ("trivial") the doctrine refutes

Locations and what each says a lawful `SKIPPING: none` is:

| Place | Sources named |
|---|---|
| Token table, body line 24 | (a) closed list in 4; (b) shown search finds nothing adaptable — **two** |
| Rule 4, lines 49-56 | "ONE class only — a turn that carries no task": harness/system notification, await-only ping, inbound message handing no work; `SKILL-CHECK:` mentioned only as the pre-authorization for the first bullet |
| Rule 6 row 7, line 78 | a pure recap of your own last message, authorized by a `SKILL-CHECK:` line — a class not in rule 4's list |
| Library doctrine, lines 103-109 | "Three sources … and only three": closed list in 4; shown search; a `SKILL-CHECK:` line marking the turn "non-task, conversational, or a recap" |
| Persistence, line 116 | "a skip comes only from the three sources above" |
| `GETAWAY_SKIP_MSG` enforcer.py:1310-1311 | "pre-authorized ONLY if this turn is genuinely **trivial**/non-task" |
| `INTENT_SKIP_MSG` :1316-1317 | "conversational/non-task" |

Contradictions an agent will hit:
1. **"Trivial" is a task class.** Rule 4 excludes it (the class is "no task"); Red-Flags row 1 (line 72) refutes "it's a mechanical / domain call" with SEARCH; the Library doctrine names "trivial errand" as a kind of turn (line 94) but never rules on it. The getaway `SKILL-CHECK:` line pre-authorizes a skip on a trivial turn, and Library bullet 3 says "The marker authorizes the ruling it states." So on a below-floor trivial task the agent holds two rulings: SEARCH (rule 4 + row 1) and SKIP (getaway line + Library bullet 3).
2. **Count mismatch.** Line 24 says two sources; line 103 says three; rule 4 says one class. "Conversational" (intent leg, Library bullet 3) and "recap" (row 7, Library bullet 3) are lawful in some places and absent from the closed list that line 24 and rule 4 call authoritative.
3. Rule 4's parenthetical ties `SKILL-CHECK:` to "harness / system notification, or an await-only ping" only; the enforcer emits it on four legs (getaway, intent, selfref, harness — enforcer.py:1371-1374).

- Lever: **Pruning: single source of truth** (one meaning, five places, three versions) and **Information hierarchy: co-location** (the definition of a lawful skip is scattered across the token table, rule 4, row 7, Library, Persistence).
- Severity: HIGH — the text contradicts itself and the per-turn string.
- Replacement: one reference block, referred to everywhere else by the token **lawful skip**. Replace rule 4 and the Library "Burden of proof" list with:

  > 4. **A lawful skip has exactly two sources:**
  >    - a `search_skills` call shown in THIS reply whose hits are not even loosely adaptable (rule 3);
  >    - a `SKILL-CHECK:` line from the enforcer stating that this turn is non-task, conversational, a recap of your own last message, or harness-generated. It authorizes the ruling it states. When it says the turn may be real or ambiguous work, it is telling you to SEARCH.
  >
  >    Anything that hands you work is a task and routes through 2: a notification's content, a message's content, work you dispatch to another agent, a preview that arrived with candidates.

  Then line 24 becomes `SKIPPING: none   lawful skip only (rule 4)`, row 7 becomes `| … | A pure recap is lawful only with the enforcer's SKILL-CHECK: line for it (rule 4). Otherwise SEARCH. |`, and Persistence drops the "three sources" sentence.
- Enforcer side, choose one: (i) delete "trivial/" from `GETAWAY_SKIP_MSG` :1311 — the signature "full-catalogue retrieval ran" is untouched, and the leg's own comment (:1305-1306) says it "can't tell trivial from real-but-low-scoring"; or (ii) add "trivial errand" to the lawful list above. Recommend (i): it aligns with row 1 and rule 3 and removes the only place "trivial" is a lawful class.

### F3 — MED — Two token syntaxes are in context at once

- Where: `_ranked_mandate` header enforcer.py:1777 and `MANDATE` :1228 render `USING <skill> | SEARCH <query> | SKIPPING none` (no colon); the doctrine (lines 22-24, 58, 62) and `CONSULT_MANDATE` :1890 use `USING: <name>` with a colon.
- Lever: **Leading words** (the token must be one token, repeated identically) and variance. The audit tolerates both (`_USING = re.compile(r'(?im)^\s*USING:?\s+…')`, audit_skill_usage.py:52-54) so measurement is safe, but the agent sees two spellings every turn.
- Replacement: `"SKILL-FIRST · reply line 1 = USING: <skill> | SEARCH: <query> | SKIPPING: none.\n"` in both places (:1228, :1777). No selftest pins the exact header string (grep on `reply line 1 = USING` finds only the three definitions).

### F4 — MED — `Skill tool` is a Claude Code tool name in a multi-harness body

- Where: body line 62 "The Skill tool cannot run them"; also enforcer annex/foreign blocks :1764, :1773 "do not use the Skill tool".
- Lever: **Cache vs environment** (a harness-specific name cached in text that other harnesses read) and the task's cross-harness constraint. `_harness_adapt` never rewrites this phrase.
- Replacement: body — "They cannot be invoked by name here"; enforcer — "(NOT installed here — consume via get_skill)". Both keep the positive target and drop the harness name. The negation "do not use the Skill tool" is also the pattern the reference warns about; the positive form alone carries the meaning.

### F5 — MED — Rule 4 says "route it through 2" four times in three lines

- Where: body lines 54-56.
- Lever: **Pruning: duplication** / **sprawl**.
- Replacement: the single sentence given in F2 ("Anything that hands you work is a task and routes through 2: …").

### F6 — MED — The three Not/Yes pairs restate rules 3, 4 and 5 and spell the banned outputs verbatim

- Where: body lines 81-88.
- Lever: **Negation** ("state the target behaviour so the banned one is never spoken") and **duplication**. Pair 2 is rule 4 + rule 3; pair 3 is rule 5 word for word ("USING takes a real skill name. A no-skill outcome is SKIPPING: none."). Each Not line puts the exact forbidden string (`USING: none`, `SKIPPING: none — mechanical git check`) into context.
- Replacement: keep one worked positive example under rule 2 and delete the block:
  > Example: "5 don't fit → `SEARCH: postgres schema migration` → search_skills runs → `supabase-specialist` (38%) → `USING: supabase-specialist`."
  If a negative guardrail is judged necessary, keep at most pair 1 and drop its `~~SKIPPING: none~~` strike-through rendering, which is markdown that not every harness renders.

### F7 — MED — Library doctrine and Persistence are mostly restatement

- Where: body lines 92-116.
- Lever: **Relevance** (exposition), **duplication**, **sprawl**.
  - Line 94-96 "never a score threshold … a number, not a ruling" — restates Library bullet 3 (lines 106-109) and `GETAWAY_SKIP_MSG`.
  - Lines 98-101 "Costs are asymmetric … Weigh a skip against that asymmetry, not against how confident you feel" — the last clause is Red-Flags row 5 ("Confidence is not a ruling", line 76). The card-catalogue image is a good leading image; keep one sentence of it.
  - Line 108 "with intent-and-domain phrasings, because the raw prompt is what just scored below the floor" — restates rule 2 (line 36) and `GETAWAY_SKIP_MSG` :1311-1312, which fires at the point of need.
  - Lines 115-116 restate lines 17, 19, 22-24 and the lawful-skip list. The only new content is session persistence.
- Replacement: after F2 absorbs the "Burden of proof" list into rule 4, reduce the two sections to:
  > **Library doctrine.** A skip is a ruling on what kind of turn this is, never a score. Declaring "nothing fits" on real or ambiguous work while a shelf of hundreds sits unsearched is the top-severity failure here — the student who glances at the card catalogue and writes the thesis unaided. Burden of proof is on SKIP.
  >
  > **Persistence.** Bound every task turn for the whole session, however long it runs; unsure → bound.

### F8 — MED — Rule 5 ¶2 duplicates the per-turn annex/foreign footer and the search row's note

- Where: body lines 60-64 vs enforcer.py:1766, :1776 ("To use one: `USING: <name>` then get_skill(\"<name>\") and follow its SKILL.md inline") and server.py:808-809 (row `note`).
- Lever: **Progressive disclosure by branch** ("inline what every branch needs, push behind a pointer what only some branches reach"). External/foreign hits occur on some turns only; the per-turn block and the row note are the right home. Fixing this also removes the F1 literal from the body.
- Replacement: the one-paragraph wording in F1.

### F9 — MED — Steps and reference are interleaved; the skip criterion is fuzzy

- Where: rules 1-6 are numbered as peers, but rule 2 is a step, rule 3 a completion criterion, rules 1, 4, 6 and Library are reference.
- Lever: **Information hierarchy** (in-file step vs in-file reference) and **Steps and completion criteria** (clarity). The search step's criterion is checkable ("the tool call appears in this reply", line 42). The skip criterion "nothing returned is even loosely adaptable" (line 47) is the whole skip-bar and is not checkable from the reply.
- Replacement (structure): `Steps` — 1 write the token; 2 on SEARCH call `search_skills` this reply with 2–3 intent+domain phrasings; 3 rule on the hits: closest fit adapted → USING and invoke now; else SKIPPING with the query shown. `Reference` — Preview is not the shelf; Lawful skip (F2); Not-invocable hits count; Red Flags.
  Sharpened skip criterion: "`SKIPPING: none` after a search is lawful only when, for the top hit, you can state in the reply what it does and why this task lies outside it."

### F10 — LOW — Red-Flags row 8 duplicates the CHAIN-HINT line's own caveat

- Where: body line 79 vs `_chain_hint` enforcer.py:1094-1095 "— candidates, fit still required."
- Lever: **duplication** / point-of-need disclosure. The per-turn line already says it; delete row 8.

### F11 — LOW — Example skill names do not resolve on this machine

- Where: body lines 82 (`supabase-specialist`), 88 (`git-commit`).
- Lever: **context pointers** (a name in an always-loaded body is a pointer) and the test's own intent ("point only at real things", tests/test_doctrine_text.py:41-43, which bans only `find-skills`). `ls ~/.claude/skills | grep -E '^(git-commit|supabase-specialist)$'` → no match. An agent may write `USING: git-commit`.
- Replacement: `<skill>` placeholders, or names that exist (`conventional-commit` is in the installed catalogue).

### F12 — LOW — External marker spelling differs from what the enforcer renders

- Where: body line 61 `[external: <alias>]` (space) vs enforcer.py:1761 f-string `[external:{alias}` (no space) vs search_skills JSON key `"external": "<alias>"` (server.py:807).
- Lever: **leading words** (one token, one spelling). Align to the rendered form or describe it generically ("a hit marked external").

### F13 — LOW — Enforcer per-turn strings: relevance and human-facing text

- `HARNESS_SKIP_MSG` :1351-1353 — the parenthetical taxonomy "(a task notification, monitor event, cross-session/teammate message, idle reminder, or summarizer call)" is for the maintainer; the agent needs only "harness-generated, not a user task". Relevance.
- `CONSULT_MANDATE` :1894 `[consult routing: SKILL_CONSULT_ROUTE=0 disables]` addresses the operator, not the agent (the agent cannot set env vars mid-session). Pinned by selftest enforcer.py:3147, so removing it needs a selftest edit. No-op for the agent.
- `INTENT_SKIP_MSG`, `SELFREF_SKIP_MSG`, `HARNESS_SKIP_MSG` each end with the same "If the turn hands you work, that is the task: route it" tail, which rule 4 also states. One leg fires per turn, so in-context this is doctrine + one copy; acceptable as a point-of-need re-assert, but a maintenance duplication across three strings.
- `MANDATE` and the `_ranked_mandate` footer :1780-1781 deliberately restate rules 2-3 (the comment at :1217-1222 calls it the cheap per-turn re-assert). Not scored.
- `_chain_hint`, `note`, `route_line` are tight; no finding.

## No-ops (the agent does these by default)

- Line 17 "Obey on every task turn." — the whole document is an order; duplicated by Persistence.
- Line 67 "Match the symptom, read the counter, act on it." — describes how to read a two-column table.
- Line 116 "Execute."
- Lines 27-28 "The token decides the turn before the work starts. Writing it first is what binds the ruling to the evidence instead of to the work you already began." — rationale, not behaviour; "Write it before anything else" (line 19) already carries the instruction.
- Line 37-38 "Retrieval is semantic over each skill's name, description and body; a conversational sentence retrieves generic skills and buries the precise one." — the "why"; the tool's own docstring says the same (server.py:821-826). The Raw/Better example pair (lines 40-41) does change behaviour and should stay.

## Remaining duplications (one meaning, two or more places)

1. Lawful-skip definition — five places (F2).
2. "Route it through 2" — four times inside rule 4 (F5).
3. Rule 5 ¶2 ↔ per-turn annex/foreign footer ↔ search row note (F8).
4. Not/Yes pairs ↔ rules 3, 4, 5 (F6).
5. Row 8 ↔ CHAIN-HINT line (F10).
6. "Confidence is not a ruling" (row 5) ↔ "not against how confident you feel" (line 101).
7. Intent+domain phrasing rule — rule 2, Library bullet 3, `MANDATE`, `GETAWAY_SKIP_MSG`, tool docstring.
8. Session persistence — line 17 ↔ line 115.

## Rule 4 / rule 6 table / Library doctrine agreement on SKIPPING

They do not agree. Rule 4: one class (no-task), `SKILL-CHECK:` only for notifications and pings. Rule 6 row 7: adds the own-recap lane via `SKILL-CHECK:`. Library: three sources, with `SKILL-CHECK:` covering non-task, conversational, and recap. Token table line 24: two sources. The enforcer adds "trivial" (getaway leg). Details and the merged wording are in F2.

## What I did not check

- I did not run `tests/test_doctrine_text.py` or the enforcer `--selftest`; I ran only `doctrine.py --selftest` (passes) and my own OMP probe (fails the real body).
- I did not verify the Codex / Command Code / DSH / Cline rewrite branches against the real body beyond reading them; their replace targets (`mcp__plugin_skill-concierge_skill-search__search_skills`, `/skill-concierge:skill-search`) are both still present in the body (lines 34-35), so those branches are not affected by F1.
- I did not measure per-turn token cost of the enforcer strings; the reference's load argument is applied qualitatively.

## Verdict

**APPROVE-WITH-FIXES.** F1 and F2 must be fixed before this body ships: F1 makes an OMP agent act wrongly, and F2 gives an agent two contradictory rulings on a trivial below-floor turn. F3-F9 are load and variance cuts that together remove roughly a third of the body without losing a rule.

## Second pass (2026-09-15, revised body and enforcer strings)

Re-read the live body (706 words, 4,327 chars, down from 1,052 words) and the same enforcer strings. Line numbers below are body-relative (line 1 = `<!-- DOCTRINE-START -->`) unless a file is named.

Checks re-run this pass:

| Check | Result |
|---|---|
| Four locked signatures absent from body | PASS (`grep -i` → no match) |
| `tests/test_doctrine_text.py` | 3 passed |
| `doctrine.py --selftest` | OK; the OMP pin now reads the LIVE body (doctrine.py:297-301) and asserts `"get_skill(" not in _adapted` |
| `enforcer.py --selftest` | OK |
| OMP probe on the live body | `get_skill(`: 0, `skill://`: 1, `Skill tool`: 0 |
| Phantom names / leftover phrases (`supabase-specialist`, `git-commit`, `Skill tool`, `route it through 2`, `three sources`, `Execute.`, `Obey on`) | none in body |

### (1) Per finding

| # | Status | Proof |
|---|---|---|
| F1 | FIXED | Body line 41 restores `get_skill("<name>")`; doctrine.py:198-200 rewrites it; probe on the live body under OMP yields `read("skill://<name>")` and zero `get_skill(`; the selftest sample is now `_body(DOCTRINE_PATH.read_text(...))` (doctrine.py:300) with a guard that the body carries the rewrite target (:303-304). |
| F2 | FIXED | Rule 4 (lines 31-38) is the two-source block; token line 10 `lawful skip only (4)`; row 7 (line 56) points at (4); Library (65-68) has no source list; Persistence (72) is one sentence; `GETAWAY_SKIP_MSG` enforcer.py:1310-1311 now "non-task or conversational" and the word "trivial" survives only inside the refuted rationalization at row 1 (line 50). Rule 4 bullet 2's four classes (non-task, conversational, harness-generated, recap) match the four legs (getaway/intent/harness/selfref). |
| F3 | FIXED | `MANDATE` enforcer.py:1228 and the ranked header :1777 both read `USING: <skill> \| SEARCH: <query> \| SKIPPING: none`. |
| F4 | FIXED | Body line 40 "cannot be invoked by name here"; annex/foreign blocks enforcer.py:1763, :1772 "consume via get_skill"; `Skill tool` count 0. |
| F5 | FIXED | Rule 4 tail is one sentence (lines 37-38). |
| F6 | FIXED | Not/Yes block gone; one worked example (lines 58-59). |
| F7 | FIXED | Library and Persistence are the proposed wording (lines 63-72). |
| F8 | PARTIAL, accepted | Rule 5 (lines 40-43) still carries the concrete `get_skill("<name>")` call that the per-turn annex footer also carries. Kept deliberately because it is the OMP rewrite target and the enforcer annex is not OMP-adapted; the duplication is one sentence. |
| F9 | PARTIAL | Rules 2 and 3 now read as the step sequence ("SEARCH — query…", "Rule on the hits") and the sharpened, checkable skip criterion is in (lines 27-29). Reference rules 1, 4, 5, 6 remain interleaved with them rather than under a separate heading. Acceptable at this length. |
| F10 | FIXED | Row 8 deleted; the table has seven rows (lines 50-56). |
| F11 | FIXED | Example uses `<hit>` placeholders (line 59); no phantom skill names in the body. |
| F12 | FIXED | Line 40 "Hits marked external or other-harness". |
| F13 | FIXED / accepted | `HARNESS_SKIP_MSG` :1351-1354 taxonomy trimmed; `CONSULT_MANDATE` :1886-1892 has no operator footer (comment :1893-1894 records the move); the three-leg "route it" tails remain as accepted in the first pass. |
| No-ops | FIXED | Lines "Obey on every task turn", "Match the symptom, read the counter, act on it", "Execute.", the token rationale, and the "Retrieval is semantic…" why-sentence are all gone. |

### (2) New defects introduced by the revision

None at HIGH or MED. Three LOW polish items:

- **N1 — LOW** — Body lines 28-29 and 32 state the after-search skip criterion twice: rule 3 gives the sharpened form ("state, for the top hit, what it does and why this task lies outside it"), rule 4 bullet 1 restates it as "hits are not even loosely adaptable (3)". Same meaning, two phrasings. Replacement for bullet 1: "a `search_skills` call shown in THIS reply that fails the rule-3 bar".
- **N2 — LOW** — Worked example line 59 keeps "(38%)" beside a `<hit>` placeholder; the number carries nothing once the name is generic. Replacement: `` → `<hit>` → `USING: <hit>` ``.
- **N3 — LOW, pre-existing, now visible** — Under OMP the two search bullets (lines 17-18) render identically (`tool:` and `or:` both become `skill-concierge:skill-search/search_skills`, probe output above). Not introduced by this revision (the old body had the same pair) but the leaner body makes the duplicate bullet stand out. Fix belongs in `_harness_adapt` (drop the `or:` line under OMP) or by collapsing the two bullets into one line that names the tool once.

Consistency re-check: rule 4 (lines 31-38), row 1 and row 7 (lines 50, 56), the token line (10), the Library paragraph (65-68), `MANDATE`, and all four `SKILL-CHECK:` legs now agree that a lawful skip comes from a shown search or an enforcer line stating a non-task / conversational / harness-generated / recap ruling, and that "trivial" is not a lawful class. Every pointer in the body resolves (`search_skills`, `extra_queries`, `get_skill`, `/skill-concierge:skill-search`, `SKILL-CHECK:`).

### (3) Final verdict

**APPROVE.** F1 and F2 are fixed with proof on the live body; the remaining PARTIALs (F8, F9) are deliberate, one-sentence trade-offs; N1-N3 are polish and do not block shipping.
