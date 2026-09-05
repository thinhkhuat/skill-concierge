# Config-prose audit — global instruction surfaces (G3)

Date: 2026-08-31 03:39 · Scope: `~/.claude/CLAUDE.md` (194 ln), `~/.claude/RULES.md` (162 ln), all 10 `~/.claude/rules/*.md`, plus hook-emitted prose from `~/.claude/hooks/dev-rules-reminder.cjs` and session-start blocks. Rubric: `directional-prompting` (outcome-first, negation→positive-verb, documented exceptions) + `writing-for-agents` (duplication, no-op instructions, context pointers, sediment). Read-only audit; no surface edited. 16 findings below, each with file:line citations (C6 withdrawn at validation; recorded in place).

Severity: HIGH = contradiction or wrong/misleading instruction · MED = ambiguity, duplication, drift, missing pointer · LOW = polish.

## Findings

| # | Sev | Location | Finding (quote byte-exact) |
|---|-----|----------|---------------------------|
| C1 | HIGH | `MY-WORKBENCH/CLAUDE.md:52` × `RULES.md:134` | Token-economy contradiction. Workbench block: "## Token efficiency (applies to every response)" incl. "If a task needs 1 tool call, don't use 3" vs RULES [49]: "Token economy is never a reason to do less." The workbench "not a loophole" clause resolves it ONLY for completion discipline; the block's other 6 bullets still instruct economizing that [49] forbids as justification. Directional fix: state the positive rule once ("verify fully; economize only redundant re-reads — RULES [49]") and delete the block. |
| C2 | HIGH | `hooks/dev-rules-reminder.cjs` (UserPromptSubmit injection) | "Sacrifice grammar for the sake of concision when writing reports." contradicts the system Language mandate ("Maintain full orthographic correctness for English") and Constitution §1 ("Terse, direct, and complete sentences"). Same phrase family propagates into skill bodies (e.g. `skills/project-management` "Sacrifice grammar for brevity"). One source, many copies — fix at the hook. |
| C3 | HIGH | `rules/` vs `docs/` (4 file pairs) | Same-named rule files deployed twice with DIVERGENT content: `documentation-management.md` (28 vs 72 ln), `orchestration-protocol.md` (49 vs 116 ln), `skill-domain-routing.md` (42 vs 159 ln), `skill-workflow-routing.md` (53 vs 73 ln). The rules/ copies are auto-loaded; the docs/ copies are the on-demand index targets (`rules/CLAUDE.md:14` "## On-Demand References"). Two authorities, no statement of which wins. Single-source-of-truth violation (`rules/CLAUDE.md:22` claims "Shared blocks (single source of truth)" for exactly these paths). |
| C4 | MED | `CLAUDE.md:4` | Typo + grammar in the first instruction the session reads: "Read, and allways hold on to the RULES provided above at all time - during the entire working session." → "allways"/"at all time". Also "Pass to the sub-agents with relevant context taken from that RULES.md" — garbled imperative. |
| C5 | MED | `RULES.md:85` | Rotation-chain off-by-one: "exa → exa advanced → `tvly` → `firecrawl`; `web_search` is 4th" — four providers precede the clause, making web_search 5th in the chain as written. Intent ambiguous (4-step rotation with web_search as 4th-choice tool?). |
| C6 | ~~MED~~ WITHDRAWN | `RULES.md:5-6` | Originally: "stale count — live rules number 76". Withdrawn at independent validation: RULES.md carries 77 distinct live rule indexes (1–78 with 62 withdrawn), so the header "77 rules … [62] withdrawn" is accurate under the index unit; the original finding was a unit error. |
| C7 | MED | `rules/skill-workflow-routing.md:14` | Undefined term, no pointer: "start with the brainstorm contract" — "brainstorm contract" is defined only in `rules/primary-workflow.md` §1; the file never links it. |
| C8 | MED | `rules/primary-workflow.md:22` | Harness-specific alias in a global rule: "resolve the installed cook skill through the runtime's live skill catalog, then load its `references/workflow-routing.md`" — "cook skill" (ak:cook) is one harness's name; on Codex/other harnesses this rule dead-ends. Also densest sentence in the always-loaded corpus. |
| C9 | MED | `rules/anti-patterns.md:24,28` | Cell density: rows 18 and 22 are 300+ words inside single table cells, mixing rule + rationale + catalog pointers + jargon ("pull-only memory never fires at the ask moment", "#19 gate-input swap"). Unreadable at injection time; violates its own row 7 (format overkill). Extract rationale to a reference file, keep the table row ≤2 lines. |
| C10 | MED | `rules/CLAUDE.md:14-30` | The on-demand index itself: 6 of 7 entries point into `~/.claude/docs/`, of which 4 collide with auto-loaded `rules/` names (see C3); the 7th (`multi-step-skill-discipline.md`) has no rules/ twin — inconsistent placement pattern, no rule stating which dir owns what. |
| C11 | MED | `hooks/dev-rules-reminder.cjs` injection | Config values leaked as prose with no instruction attached: "Validation: mode=prompt, questions=3-8" and "docs.maxLoc: 800" — the agent is told the values but not what to do with them (no-op instructions per writing-for-agents). Either state the behavior ("ask 3-8 questions before writing a plan") or move to machine config. |
| C12 | MED | Session-start `[cache-ttl]` block | "Report this TTL to the user in your first reply of the session." — buried as block 2 of a 6-block injection stack. Observed missed this session (the audit session's own first reply did not report it — disclosed as evidence, not accusation). Instruction with no checkpoint and no enforcement; either surface it as a required first-line token or drop it. |
| C13 | MED | Injection budget (RULES.md:132) | [48] mandates "Price per-turn injection before proposing it", yet the deployed always-on stack is unpriced: 734 lines / 51,409 bytes (~13K tokens) of rules corpus every session + per-turn UserPromptSubmit block (~700 tokens) + SKILL-FIRST order (~600) + memory injections + ADHD/caveman scopes. No ledger of per-turn cost exists anywhere. |
| C14 | LOW | `CLAUDE.md:42,44` vs Constitution §2/§3 | Double statement: "1. **No flattery, no filler.**" and "3. **Never fabricate.**" restate the Constitution's Anti-Syncophancy and Truthfulness sections in the same payload. Harmless but sediment; RULES.md [15]/[44] state the fabrication rule a third time. |
| C15 | LOW | `CLAUDE.md:4` | Brittle position language: "the RULES provided above" assumes injection order inside the compiled prompt; a pointer ("RULES.md as imported above") survives reordering. |
| C16 | LOW | AgentKit session-start block | "Review the previous-session status data, then continue or start fresh." — no criteria for choosing continue vs fresh; every session must re-derive the decision. One line of criteria would close it. |
| C17 | INFO | `RULES.md:150` | Negation-dense military register is deliberate and self-documented ([46] "Write rules in the military register — short, direct, commanding"). directional-prompting's negation flag does NOT apply — in-rule exception. Recorded so no future pass "fixes" it. |

## Per-file verdicts

| File | Verdict |
|------|---------|
| `CLAUDE.md` (global) | FINDINGS C4, C14, C15 — structurally sound, two typos, sediment overlap with Constitution |
| `RULES.md` | FINDINGS C1 (side), C5, C13; C6 withdrawn — dense by design; two precision defects |
| `rules/CLAUDE.md` | FINDINGS C3, C10 — index contradicts its own SSOT claim |
| `rules/anti-patterns.md` | FINDING C9 — content strong, format hostile |
| `rules/primary-workflow.md` | FINDING C8 — one portability defect |
| `rules/skill-workflow-routing.md` | FINDINGS C3, C7 |
| `rules/skill-domain-routing.md` | FINDING C3 — rules/ copy is the 42-line variant; docs/ 159-line twin diverges |
| `rules/development-rules.md` | FINDING — `--yagni` convention (line 10) duplicated verbatim in dev-rules-reminder.cjs injection; double-loaded every turn |
| `rules/documentation-management.md` | FINDING C3 only |
| `rules/orchestration-protocol.md` | FINDING C3 only |
| `rules/process-management.md` | clean |
| `rules/review-audit-self-decision.md` | clean |
| `hooks/dev-rules-reminder.cjs` prose | FINDINGS C2, C11 + duplication of development-rules.md content per turn |
| Session-start blocks | FINDINGS C12, C13 (side), C16 |

## Feeds the contradiction matrix (G5)

C1 (token economy ×2), C2 (grammar × orthography), C3 (docs/ × rules/ ×4), C5 (rotation order internal), C11 (config-as-prose), C13 ([48] × deployed stack) all carry dual citations and enter the pairwise matrix.
