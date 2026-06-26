# Code Review — skill-concierge invocation-ledger slice

**Date:** 2026-06-26
**Reviewer:** code-reviewer (independent, report-only)
**Scope:** `hooks/scripts/ledger.py`, `hooks/hooks.json`, `scripts/analyze.py` vs `docs/plan.md` (Design item 4 + Acceptance P1)
**Status:** DONE_WITH_CONCERNS — contract is met; all open items are metric-integrity should-fixes, no blocker.

---

## Overall assessment

The slice is small, lean, and faithful to its stated contract. The two non-negotiables
(fail-silent, additive-only) hold by construction. Storage is a single append-only JSONL
`.log` with no rotation/cap/delete. The hook deliberately records `input_keys` instead of
guessing the Skill tool's field name. The analyzer computes uptake/search/dodge + per-skill
rollups and correctly defers hit@k.

The real risks are not crashes or contract breaks — they are **metric-validity defects** in
what the numbers *mean*. Two independent sources of denominator/frequency pollution
(`manual` over-capture of non-skill slashes, and `turn` over-capture of trivial/empty prompts)
both feed the exact decision engine this ledger exists to drive (promote/demote always-on set;
the P2 "build teeth?" call off the dodge rate). Neither breaks an acceptance checkbox, but
both bias the evidence and — more importantly — break the **baseline-comparability** goal in
Acceptance ("before/after must be comparable").

Recommended posture: keep `ledger.py` dumb (raw capture, no log-time heuristics or denylists —
that reintroduces the drifting-catalogue anti-pattern the whole plan exists to kill) and fix
both pollution sources analyzer-side, against the real skill catalogue.

---

## Contract check (plan.md Acceptance P1, ledger-relevant items)

| Contract item | Verdict | Evidence |
|---|---|---|
| FAIL-SILENT — any error → exit 0 | PASS | `main()` body fully wrapped in `try/except → return 0`; `_append()` independently wrapped; stdlib-only imports (no import-time exit risk); `sys.exit(main())` always 0. |
| ADDITIVE-ONLY — no hook-decision output | PASS | No `print`/stdout anywhere. UPS hooks inject stdout into context — this one writes only to file, so nothing leaks into the turn. |
| Events tagged `ev`; manual distinct from auto | PASS | `manual` logged in UPS branch, `auto` in PostToolUse branch — structurally separate. |
| COMPOUNDING — one append-only `.log`, no rotation/cap/delete | PASS | `_append` opens mode `"a"`, one line per event; no rotation logic; lifecycle deferred to logman per plan. |
| No assumption of Skill `tool_input` field name | PASS | Records `input_keys = list(ti.keys())` + best-effort name from `_NAME_KEYS`; never logs input *values*. |
| Analyzer: uptake / search / dodge + per-skill auto & manual freq; hit@k deferred | PASS | All produced; hit@k printed as `pending` with correct rationale (no `offer` events yet). |

All ledger-relevant acceptance items pass. The concerns below are about metric *quality*,
not contract conformance.

---

## Findings

### High / should-fix

**H1. `manual` over-captures non-skill slash commands → pollutes promote/demote evidence.**
`ledger.py:58-61` logs ANY prompt starting with `/` as `ev:manual name=<first token>`.
Slash *commands* are not skills. In this workbench the user routinely types `/ck:ship`,
`/ck:scout`, `/come-clean`, etc.; each lands as `manual name=ck:ship`. (`docs/plan.md`
confirms slash prompts reach the hook as raw text — "it currently early-returns on `/`".)
Whether *built-ins* like `/clear`/`/compact` reach UserPromptSubmit vs. being client-intercepted
is a CC runtime detail not verifiable from source — so anchor this on custom/plugin commands,
which certainly route through.

- **Impact:** `manual_freq` (`analyze.py:81`) is the plan's *strongest* promote signal
  ("skills the owner keeps invoking by hand"). Commands masquerading as manual skill
  invocations would wrongly promote a non-skill into the always-on set.
- **Recommended fix (RECOMMEND only):** analyzer-side filter of `manual` names against the
  real skill catalogue (`discover_skills()` / Qdrant index), **not** a log-time denylist.
  Rationale: (1) log-time filtering is lossy — misclassified data is unrecoverable;
  (2) a hardcoded denylist is exactly the "separate, drifting catalogue" the plan retires
  (the 585-vs-508-vs-512 drift); (3) keep the hook raw, interpret at analysis time. Split
  `manual` into `skill-manual` (name ∈ catalogue) vs `other-slash` at report time.

**H2. `turn` denominator is not "substantive" — trivial/empty prompts inflate it.**
Both `plan.md` ("dodge rate — *substantive* offered turn") and `analyze.py`'s own docstring
("dodge rate — *substantive* turn with NO skill") claim a substantive denominator. But
`ledger.py:62-64` logs **every** non-slash prompt as `ev:turn`, including "yes" / "continue" /
"thanks" — and even **empty** prompts: `prompt = d.get("prompt") or ""` → `s=""` → not a
slash → falls into the `turn` branch with `q=""`. There is no triviality or empty gate.

- **Impact:** `n` (turn-window count, `analyze.py:75`) is inflated by trivial/empty turns
  where no skill should ever fire → **dodge biased high, uptake biased low.** This is the
  direct sibling of H1: both corrupt the same promote/demote + "build teeth?" decision engine.
- **Comparability break (the load-bearing consequence):** Acceptance requires "Baseline
  captured on the CURRENT lexical hook... so before/after is comparable." Post-fusion dodge
  will be measured over *offered* turns (the enforcer has a trivial-getaway gate); this baseline
  is measured over *all* non-slash turns. Different denominators → the before/after lift the
  plan exists to prove is not apples-to-apples.
- **Recommended fix (RECOMMEND only):** keep the hook dumb (don't add a log-time triviality
  heuristic — that's the enforcer's job and would drift). Cheap analyzer-side win now: drop
  `turn` windows with empty `q`. Document explicitly that the current baseline denominator =
  all non-slash turns, so it must be re-derived once offer/triviality gating exists.

### Low / nit

**L1. Orphan `search` is silently dropped; orphan `auto` is not — asymmetry.**
`analyze.py:61-68` creates an `orphan-auto` window when an `auto` arrives with no open window
for the session, so its name still lands in `auto_freq`. But `analyze.py:69-71` only credits a
`search` `if sid in cur` — a `search` before any `turn` in that session is dropped from
`searched`. Rare (search-before-first-turn), non-fatal, but inconsistent. Mirror the auto path
if search-call rate needs to be exact.

**L2. JSONL append concurrency — safe here, NFS caveat only.**
Multiple hook processes (e.g., parallel subagents each firing `Skill` PostToolUse — plausible
in this workbench, not just theory) append concurrently. On a local FS (APFS/ext4) with
O_APPEND and small single-line writes (`q` truncated to 120c, so well under PIPE_BUF / the
text buffer), each line is one atomic `write()` at EOF — no interleave. Risk would only appear
on a network FS (NFS O_APPEND atomicity not guaranteed) or for lines exceeding the buffer.
`analyze.py:37-40` tolerates a corrupt/partial row (`except: pass`), so even a rare torn line
is dropped, not fatal. No change needed; note the NFS caveat if the log dir ever moves.

**L3. Prompt text persisted in a never-deleted log (owner-accepted tradeoff).**
`ledger.py:64` stores the first 120 chars of every substantive prompt in a compounding,
never-rotated log. `plan.md` explicitly chose "truncated ≤120c (not hashed)", so this is an
accepted owner decision on a local-only file — not reversing it. Flagging once: the first 120c
can contain a pasted secret/PII (e.g., a prompt beginning with a key), and the store compounds
forever with no redaction. Acceptable given the explicit decision + local scope; revisit only
if the log ever leaves the machine.

**L4. `name` extraction false-positive on slash-prefixed non-commands.**
`ledger.py:60` treats any `/`-prefixed prompt as a command; a pasted `/usr/local/bin` logs as
`manual name=usr/local/bin`. Subsumed by the H1 catalogue filter (won't match a real skill).
No separate fix needed.

---

## Positive observations (risk-calibration)

- **Exact-match dispatch defuses matcher over-breadth.** The PostToolUse matcher
  `Skill|mcp__skill-search__search_skills` is a regex and `Skill` is unanchored (could match a
  tool whose name merely *contains* "Skill"), but `ledger.py:68,79` dispatch on exact `==`, so
  an over-firing matcher logs nothing spurious — only an extra negligible cold-start. Good
  defensive coding.
- **Trust boundary passes by construction.** Untrusted prompt text flows into the log, but
  `json.dumps(..., ensure_ascii=False)` still escapes `\n`/`"`/control chars — a crafted prompt
  cannot split a JSONL line or inject a forged row. The boundary holds structurally.
- **`input_keys` capture is the right call** for the undocumented Skill field — learns the real
  field from live data instead of guessing, exactly per contract item 5.

---

## Specific concerns — adjudicated

| Concern | Verdict |
|---|---|
| Built-in slash pollution of manual-skill freq | **Real (H1).** Fix analyzer-side against the catalogue, not a log-time denylist. Anchor on custom/plugin commands (certain); built-in routing unverifiable from source. |
| Per-turn latency (cold python per prompt + per tool call) | **No blocking risk.** Work = stdin read + one `json.loads` + a dict lookup + a small append; no network. Well under the 5s hook timeout and the ~150ms budget (~71ms cited for the heavier sibling). `mkdir(exist_ok=True)` per call is a negligible stat. |
| Concurrency / JSONL interleave | **Low (L2).** Safe on local FS; analyzer tolerates torn rows. NFS caveat only. |
| Analyzer segmentation (auto/search → latest window per sid) | **Mostly correct.** Cross-session interleave handled (per-sid `cur`). Edge: orphan-search dropped (L1); orphan-auto handled. Same-`t` ties resolved by stable sort over file (causal) order since UPS precedes PostToolUse. A subagent `Skill` call sharing the parent `session_id` could attach to the parent's latest turn window — possible mis-attribution, unverifiable from source; note if subagents are expected. |
| hooks.json wrapper / `${CLAUDE_PLUGIN_ROOT}` | **Conformant.** Correct top-level `hooks` object, event arrays, `matcher` only on PostToolUse (none on UPS, as required), `type:command` + `timeout`. Uses `${CLAUDE_PLUGIN_ROOT}`. Nit: bare `python3` assumes it is on the hook PATH and is the intended interpreter — portability only, matches sibling hooks presumably. |

---

## Recommended actions (priority order; all RECOMMEND, no code changed)

1. **H1** — analyzer-side `manual` split against the real skill catalogue (skill-manual vs other-slash).
2. **H2** — analyzer drop empty-`q` turn windows; document baseline denominator = all non-slash turns and that it must be re-derived once offer/triviality gating exists (protects before/after comparability).
3. **L1** — mirror the orphan-auto path for orphan-search if search-call rate must be exact.
4. **L2/L3/L4** — no action; note NFS caveat and the accepted prompt-retention tradeoff.

---

## Unresolved questions

- **Subagent session_id:** do subagent `Skill` invocations share the parent `session_id`? If so,
  their `auto` events attach to the parent's latest turn window and inflate that turn's uptake.
  Unverifiable from these three files — confirm against CC runtime behavior before trusting
  per-turn uptake at fine granularity.
- **Built-in slash routing:** whether `/clear`/`/compact`/`/context` reach UserPromptSubmit or are
  client-intercepted is a CC runtime detail not determinable from source. H1 stands on
  custom/plugin commands regardless.

**Status:** DONE_WITH_CONCERNS — contract (fail-silent, additive-only, compounding, distinct manual/auto, input-key capture, analyzer metrics) is met; two should-fix metric-integrity issues (manual non-skill pollution; trivial/empty-turn denominator inflation + baseline comparability) are best fixed analyzer-side, plus minor nits.
