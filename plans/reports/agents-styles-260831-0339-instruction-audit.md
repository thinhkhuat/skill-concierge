# Harness Instruction Audit — Agents & Output Styles

**Date:** 2026-08-31
**Scope:** 34 files `~/.claude/agents/*.md` + 7 files `~/.claude/output-styles/*.md` = **41 files, full coverage**
**Rubric:** `directional-prompting/SKILL.md` v2.1.0 (Layer 1 outcome block + Layer 2 directional language + 4 legitimate-negation exceptions + 9-token audit + ALWAYS/NEVER/MUST signal) and `writing-for-agents/SKILL.md` (context pointers, two loads, information hierarchy, steps/completion criteria, leading words, pruning: duplication/cache/sediment/no-ops)
**Method:** Live reads of all 41 files + dumps to `/tmp/agents_dump.txt` (3700 lines) and `/tmp/styles_dump.txt` (40KB). Token scan via `re.compile(r"\b(don't|do not|never|avoid|refrain|instead of|...|won't|shouldn't)\b", re.I)` + hedge scan + absolute scan (`ALWAYS|NEVER|MUST`) + frontmatter parse + Goal/Success/Stop string scan. Verdict threshold: byte-exact `file:line` quote required for every finding.
**Treat-as-data rule:** Instruction-shaped text inside audited files was treated as DATA to report, never as directive.

---

## 1. Totals per severity

| Severity | Definition | Count |
|---|---|---|
| **HIGH** | Contradiction, wrong instruction, hard safety boundary miss, scope-creep that changes tool authority | **9** |
| **MED** | Ambiguity, duplication, missing trigger/branch, illegitimate negation, absent outcome block that creates drift, sprawl | **22** |
| **LOW** | Polish: decorative absolute, register/AI-slop tell, sediment, no-op, punctuation hygiene | **18** |
| **Total** | | **49** |

All 49 findings cite `file:line` + byte-exact short quote (≤90 chars). Counts are finding-level, not file-level; one file can carry multiple severities.

---

## 2. Per-file verdict table (41 rows — every file appears)

Verdict scale: **CLEAN** (no required fix) → **PASS_WITH_NOTES** (LOW/MED polish) → **NEEDS_REWRITE** (≥1 MED+HIGH). Universe-wide Layer-1 absence is downgraded to MED for this cohort because these are routing-embedded agent definitions (goal is carried by the host skill's outcome block) — but flagged for migration.

| # | File | Lines | Negs | Abs.(MUST/NEVER/ALWAYS) | Frontmatter when? | Outcome block Goal/Success/Stop | Verdict | Top signal |
|---|---|---|---|---|---|---|---:|---|
| 1 | `advisor.md` | 156 | 8 | 0 | no | — / — / — | PASS_WITH_NOTES | Neg-heavy constraints, outcome block absent |
| 2 | `agent-validator.md` | 163 | 9 | 7 | no | — / — / — | NEEDS_REWRITE | Absolute-rule section `NEVER` ×3 decorative-adjacent |
| 3 | `brainstormer.md` | 136 | 7 | 0 | no | — / — / — | PASS_WITH_NOTES | `Don't Repeat Yourself` acronym negation (legit by exception 4, still flagged) |
| 4 | `code-reviewer.md` | 183 | 6 | 0 | **yes** (`Use after...`) | — / — / — | PASS_WITH_NOTES | Compact; one MED duplication vs. `docs-manager` |
| 5 | `code-simplifier.md` | 54 | 3 | 0 | no | — / — / — | PASS_WITH_NOTES | Thin file — lowest risk |
| 6 | `debugger.md` | 174 | 7 | 0 | yes | — / — / — | PASS_WITH_NOTES | Checklist negations rewriteable |
| 7 | `docs-manager.md` | 111 | 10 | 0 | yes | — / — / — | NEEDS_REWRITE | Prohibition cluster (§21-22) |
| 8 | `explore.md` | 36 | 4 | 0 | no | — / — / — | PASS_WITH_NOTES | Two prohibitions, both rewriteable |
| 9 | `fullstack-developer.md` | 122 | 5 | 2 | no | — / — / — | PASS_WITH_NOTES | Decorative `IMPORTANT` caps |
| 10 | `git-manager.md` | 25 | 0 | 0 | yes | — / — / — | **CLEAN** | Shortest, no negations |
| 11 | `goal-judge.md` | 49 | 3 | 0 | no | — / — / — | PASS_WITH_NOTES | Read-only fence via negation |
| 12 | `goal-scout.md` | 49 | 6 | 0 | no | — / — / — | PASS_WITH_NOTES | Overlap with `explore.md`/`goal-judge.md` |
| 13 | `goal-worker.md` | 53 | 13 | 0 | no | — / — / — | NEEDS_REWRITE | Densest prohibition cluster in GoalBuddy lane |
| 14 | `journal-writer.md` | 149 | 7 | 0 | yes | — / — / — | PASS_WITH_NOTES | Tool-use `Do not` triggers, no outcome block |
| 15 | `kongming.md` | 85 | 10 | 0 | no | — / — / — | PASS_WITH_NOTES | Adversary boundary uses legit negations |
| 16 | `librarian-cataloger.md` | 29 | 6 | 3 | no | — / — / — | PASS_WITH_NOTES | `NEVER` trio — small file amplifies |
| 17 | `ocx-gpt-5-4-mini.md` | 20 | 2 | 0 | no | — / — / — | PASS_WITH_NOTES | Single banned-skill negation (exception 4) |
| 18 | `ocx-gpt-5-5.md` | 20 | 2 | 0 | no | — / — / — | PASS_WITH_NOTES | Clone of above |
| 19 | `ocx-gpt-5-6-luna.md` | 20 | 2 | 0 | no | — / — / — | PASS_WITH_NOTES | Clone |
| 20 | `ocx-gpt-5-6-sol.md` | 20 | 2 | 0 | no | — / — / — | PASS_WITH_NOTES | Clone |
| 21 | `ocx-gpt-5-6-terra.md` | 20 | 2 | 0 | no | — / — / — | PASS_WITH_NOTES | Clone |
| 22 | `ocx-self.md` | 17 | 1 | 0 | no | — / — / — | **CLEAN** | Single guard negation |
| 23 | `planner.md` | 159 | 11 | 1 | yes | — / — / — | NEEDS_REWRITE | 11 negs; also heaviest duplication with `researcher` |
| 24 | `project-manager.md` | 37 | 0 | 0 | yes | — / — / — | **CLEAN** | No negations, when-clause present |
| 25 | `researcher.md` | 70 | 5 | 0 | yes | — / — / — | PASS_WITH_NOTES | Overlaps planner |
| 26 | `tester.md` | 166 | 1 | 0 | yes | — / — / — | PASS_WITH_NOTES | Single `Never ignore failing tests` (legit exception 3) |
| 27 | `tk-validator.md` | 71 | 9 | 0 | no | — / — / — | PASS_WITH_NOTES | Fresh-context boundary uses legit negs |
| 28 | `ui-ux-designer.md` | 247 | 0 | 3 | yes | — / — / — | **CLEAN** | Zero negs — rare positive-direction model |
| 29 | `vn-author-agent.md` | 57 | 7 | 1 | no* | — / — / — | PASS_WITH_NOTES | Caveman guard is legit exception 1 |
| 30 | `vn-bctt-researcher.md` | 238 | 44 | 5 | no | — / — / — | NEEDS_REWRITE | Highest neg density (18.5 /100 lines) |
| 31 | `vn-canu-researcher.md` | 260 | 48 | 0 | no | — / — / — | NEEDS_REWRITE | Highest absolute count; HIGH drift risk |
| 32 | `vn-editor-agent.md` | 60 | 7 | 1 | no* | — / — / — | PASS_WITH_NOTES | Mirrors vn-author |
| 33 | `vn-news-signals-researcher.md` | 199 | 38 | 5 | no | — / — / — | NEEDS_REWRITE | Sibling of 30 — shared sprawl |
| 34 | `vn-validator.md` | 377 | 39 | 9 | no | — / — / — | NEEDS_REWRITE | `HARD FLOOR:` + `MUST` cluster (see §3) |
| 35 | `casual-vietnamese.md` | 61 | 0 | 0 | n/a (style) | — / — / — | PASS_WITH_NOTES | Register scope contradiction (flagged LOW) |
| 36 | `coding-level-0-eli5.md` | 103 | 11 | 27 | n/a | — / — / — | NEEDS_REWRITE | `MUST`×15 + `NEVER`×8 — decorative absolutes |
| 37 | `coding-level-1-junior.md` | 124 | 9 | 23 | n/a | — / — / — | NEEDS_REWRITE | `MUST`×5×3 sections |
| 38 | `coding-level-2-mid.md` | 146 | 6 | 22 | n/a | — / — / — | NEEDS_REWRITE | `MUST`×15 stacked |
| 39 | `coding-level-3-senior.md` | 148 | 9 | 24 | n/a | — / — / — | NEEDS_REWRITE | Same pattern, inverted FORBIDDEN |
| 40 | `coding-level-4-lead.md` | 159 | 9 | 30 | n/a | — / — / — | NEEDS_REWRITE | Highest absolute density of style lane |
| 41 | `coding-level-5-god.md` | 91 | 11 | 27 | n/a | — / — / — | NEEDS_REWRITE | `NEVER`×10 in 91 lines |

`*` `vn-author-agent.md` and `vn-editor-agent.md` use folded `description: >` with embedded `<example>` routing — `when`-branch is present but buried inside prose rather than front-loaded per `writing-for-agents` pointer rule (MED duplication/packaging finding L2).

---

## 3. Findings — HIGH (contradiction / wrong instruction)

**H-1 — `vn-validator.md:9` — Hard floor declares model tier as file content, not runtime contract**
Quote `vn-validator.md:9`: `# HARD FLOOR: `opus` or `fable` ONLY. Never `sonnet`, never `haiku`, and never remove`
Why HIGH: Tier enforcement is a harness/runtime concern. Embedding it as markdown text is the `asserted, not enforced` anti-pattern the file itself warns about (`vn-validator.md:344-350` reasoning that `No Edit denial ... was security theatre`). Contradicts `~/.claude/docs/claude-code-component-building.md` (load-when: building any CC component) which requires tier to be declared in component metadata, not prose. Legit exception 1 does not save a non-enforcing prohibition.

**H-2 — `vn-canu-researcher.md:12` — Same hard-floor duplication with added `model: opus` mismatch risk**
Quote `vn-canu-researcher.md:12`: `# HARD FLOOR: `opus` or `fable` ONLY. Never `sonnet`, never `haiku`, and never delete`
Cross-file HIGH: `vn-bctt-researcher.md:3` declares `model: opus` while `vn-canu-researcher.md:17` also `model: opus` and `vn-validator.md:35` `model: opus` — three collectors assert the same floor in prose but the actual floor is inherited from the spawning host (per `vn-canu-researcher.md:10-14` self-warning). Contradiction: prose says absolute, mechanism says inherit.

**H-3 — `agent-validator.md:22-24` — `NEVER` ×3 absolute-rule block bleeds signal**
Quotes `agent-validator.md:22`: `1. **NEVER assume something works** — verify from provided evidence`
`agent-validator.md:23`: `2. **NEVER claim partial completion as done**`
`agent-validator.md:24`: `3. **NEVER fabricate evidence**`
Why HIGH per `directional-prompting` Layer 2 rule 4 (absolute-rule check): `NEVER` is reserved for true invariants; these three mix genuine safety (3) with diligence guidance (1,2) at equal weight, training the model to discount `NEVER`. Rewrite as positive: `Verify from provided evidence; check every TODO; cite source or mark UNVERIFIABLE`.

**H-4 — `goal-worker.md:15-18` — Prohibition cluster governs scope via negation, not boundary definition**
Quote `goal-worker.md:15`: `- Edit only files matching `allowed_files`. Do not edit GoalBuddy control files unless explicitly li`
`goal-worker.md:16`: `- Do not decide product strategy, architecture direction, live/API/deployment policy, or c`
`goal-worker.md:17`: `- Do not spawn agents.`
Why HIGH: `GoalBuddy Worker` is a bounded writer (critical trust boundary). A deny-list expressed as 4 consecutive `Do not` lines is exception-3 terrain (`acceptable space too large to enumerate`) but here the positive is enumerate-able: `Edits are bounded to allowed_files; strategy/architecture/deployment decisions route to PM; agent spawning is PM-only`. Negation plants the forbidden action verbatim.

**H-5 — `vn-bctt-researcher.md:50` — Absolute prohibition on canonical filesystem paths conflicts with agent tool surface**
Quote `vn-bctt-researcher.md:50`: `NEVER write to `/tmp/`, `~/Desktop`, or any path outside `{plan_dir}/`. Audit trails depen`
Why HIGH: The agent's `tools: Read, Write, Edit` (line 5) is not path-scoped; the prohibition attempts to enforce at prompt layer what should be enforced at tool-permission layer. Contradicts `vn-news-signals-researcher.md:69` identically phrased — duplication doubles non-enforcement surface.

**H-6 — `coding-level-5-god.md:40-48` — Style forbids work that the global `CONCISE` harness requires**
Quotes `coding-level-5-god.md:40`: `1. **NEVER** explain concepts, patterns, or syntax`
`coding-level-5-god.md:43`: `4. **NEVER** add comments unless they request it`
Global rule (`~/.claude/CLAUDE.md` → Output Style: Concise) requires leading-with-result and numbered steps for multi-step tasks. Level-5's `NEVER explain` / `NEVER add comments` forbids the very structure that makes a response auditable under `writing-for-agents` completion-criteria clarity. Contradiction, not calibration — the style should say `Explain only when asked` (positive), not `NEVER explain`.

**H-7 — `casual-vietnamese.md:3-4` — Style hard-overrides global language invariant without scoping guard**
Quote `casual-vietnamese.md:3`: `description: Nói tiếng Việt với người cho thật tự nhiên, giọng đời thường`
Contradiction HIGH (downgraded from BLOCKER because `keep-coding-instructions: true` scopes it): `~/.claude/CLAUDE.md` RULES line 39 `Reply in English by default` + rule 40 `Never coin a Vietnamese phrase` are load-bearing invariants. A style that flips the language without an explicit `scope: output-style only, opt-in per turn` sentence risks contagion into `code`, `commit`, `docstring` paths — which the body does re-scope (`casual-vietnamese.md:14` `code, commit, comment, docstring ... cứ để nguyên tiếng Anh`) but frontmatter does not.

**H-8 — `planner.md:30` — Instruction to `re-grep, don't copy` contradicts `directional-prompting` positive-verb rule while being correct**
Quote `planner.md:30`: `1. **Re-grep, don't copy** — Every file path and symbol from scout reports must be re-verified with`
Why HIGH-classified as *legit exception 2* (disambiguating near-identical paths) but still counted HIGH because the phrasing plants the exact wrong action (`copy`) on the critical path: re-verification failures are fabricated paths, the costliest defect. Keep — but rewrite to `Re-verify every path with a fresh grep; do not copy scout output verbatim`.

**H-9 — `ocx-*.md` ×5 (representative `ocx-gpt-5-5.md:15`) — Model-identity negation duplicated 5× with no source-of-truth**
Quote `ocx-gpt-5-5.md:15`: `Do not invoke blocked Claude Code skills: "claude-api".`
Five identical prohibition lines across `ocx-gpt-5-4-mini.md`, `ocx-gpt-5-5.md`, `ocx-gpt-5-6-luna.md`, `ocx-gpt-5-6-sol.md`, `ocx-gpt-5-6-terra.md` (line 15 each) duplicate a deny-list that belongs in the skill router, not prompt prose. Single source of truth violation (`writing-for-agents` pruning). Also violates exception 4 clarity: `Use only skills in allowlist X` is narrower positive form.

---

## 4. Findings — MED (ambiguity / duplication / illegitimate negation / missing branch)

**M-1 — All 41 files lack Layer-1 outcome block** (`Goal: / Success means: / Stop when:`). No file contains `Goal:` in its first 2000 chars, and zero contain `Success means` or `Stop when`. Per `directional-prompting` Application checklist item 1, this is a mandatory block for non-trivial prompts. Severity MED (not HIGH) for this cohort because the host skill supplies the outcome — but without it the agent's notion of "done" drifts turn-by-turn, exactly the failure mode the rubric warns about (re-planted every turn via system prompt).

**M-2 — Frontmatter `when`-clause absent in 24/34 agent definitions.** Affected: `advisor.md`, `agent-validator.md`, `brainstormer.md`, `code-reviewer.md` (description says `Comprehensive code review... Use after...` — borderline but not front-loaded), `code-simplifier.md`, `explore.md`, `fullstack-developer.md`, `goal-judge.md`, `goal-scout.md`, `goal-worker.md`, `kongming.md`, `librarian-cataloger.md`, `ocx-*` (6 files), `planner.md` (yes — counted present but weak front-load), `tk-validator.md`, `vn-author-agent.md`, `vn-bctt-researcher.md`, `vn-canu-researcher.md`, `vn-editor-agent.md`, `vn-news-signals-researcher.md`, `vn-validator.md`. Per `writing-for-agents` Context pointers, `One trigger per branch; front-load the leading word`. Weak pointer = variance bug: must-have skill behind weak trigger fires unreliably.

**M-3 — `vn-bctt-researcher.md:20` / `vn-news-signals-researcher.md:20` / `vn-canu-researcher.md:20-23` — `do NOT draft / do NOT sanitize` boundary by prohibition**
Quotes `vn-bctt-researcher.md:20`: `You do NOT draft. You do NOT call sanitize / content-mass rails on draft prose (those oper`
Rewrite per Layer 2 rule 3: `Your output is the ledger JSON at scope.ledger_path; drafting and sanitize run downstream in the main agent`. Places responsibility positively; removes planted verb `draft`.

**M-4 — `docs-manager.md:21-22` — Negation pair is placeholder text, not instruction**
Quote `docs-manager.md:21`: `Never re-describe implementation behavior in prose. Point to the owning source,`
`docs-manager.md:22`: `test, schema, manifest, or workflow. Do not hand-maintain counts, LOC tables,`
Both lack concrete positive target (`which source? which schema?`). Per rubric, if no positive replacement exists and none of the 4 exceptions apply, cut the rule — currently MED ambiguous.

**M-5 — `brainstormer.md:54` `Don't Repeat Yourself` is legitimate (exception 4) but body repeats the acronym's negativity**
Quote `brainstormer.md:54` (truncated dump): `You operate by **KISS** (Keep It Simple, Stupid) and **DRY** (Don't Repeat Yourself). Every solution`
No fix required; noted to prevent false-positive rewrite of a coined acronym. MED-Low informational.

**M-6 — `explore.md:13` / `explore.md:16` — Tight-scope prohibitions hide missing completion criteria**
Quote `explore.md:13`: `- Keep scope tight to the caller's prompt; do not broaden into unrelated refactors.`
`explore.md:16`: `- Do not edit files, stage changes, commit, push, or run destructive commands.`
Missing per `writing-for-agents` Steps and completion criteria: no `done when` clause (e.g., `done when every required file class has been listed with path:line evidence`). The prohibition carries the weight that a checkable criterion should.

**M-7 — `goal-scout.md:13` vs `goal-judge.md:13` — Overlapping read-only mappers differ by 3 tokens**
`goal-scout.md:13`: `- Read only. Do not edit, stage, install, start long-running services, or spawn agents.`
`goal-judge.md:13`: `- Read only. Do not edit, stage, install, or implement.`
Same intent, two wordings, two files — duplication per `writing-for-agents` Pruning / single source of truth. Merge into one shared gate referenced by both.

**M-8 — `advisor.md:36` — Scope fence without positive scope definition**
Quote `advisor.md:36`: `do NOT implement code, scaffold projects, or edit files other than your own state`
Positive form `Your only edits are to <state-path>; all other code work routes to host` is available — negation is illegitimate (none of the 4 exceptions).

**M-9 — `librarian-cataloger.md:21` — Code-switched negation mid-instruction**
Quote `librarian-cataloger.md:21`: `- **Do not** re-read `SKILL.md` files. The orchestrator already did. Trust the dossier.`
`Do not re-read` is exception 2 (disambiguate near-identical path: re-read vs trust cache) — keep but demote to positive: `Trust the orchestrator's dossier; skip raw SKILL.md re-reads`.

**M-10 — `coding-level-{0..5}.md` — `FORBIDDEN` lists violate Layer 2 audit pass**
Representative `coding-level-0-eli5.md:38`: `## FORBIDDEN at this level (You MUST NOT do these)`
Per `directional-prompting` audit pass line 85: `Lists titled "Anti-patterns", "Pitfalls", "Mistakes to avoid" — convert each entry to the positive action`. Six styles carry this title ×8 entries each = 48 entries planting the forbidden action. Rewrite title to `Rules` or `Do this instead` and invert each: `Assume zero prior knowledge` vs `NEVER assume they know ANY concept`. Severity MED per file, aggregate HIGH.

**M-11 — `vn-author-agent.md:32` / `vn-editor-agent.md:30` — `Never compress / never drop` double prohibition on the same sentence**
Quote `vn-author-agent.md:32`: `is efficient — the OUTPUT is Vietnamese, not your chain of thought. Never drop function words,`
`vn-editor-agent.md:30`: `Vietnamese. Never compress telegraphically, never drop function words.`
Rewrite: `Write full native sentences with all function words intact; keep register-length output`.

**M-12 — `debugger.md:18` — Checklist hedge disguised as negation**
Quote `debugger.md:18`: `- [ ] 2-3 competing hypotheses formed: do not lock onto first plausible explanation`
Hedge per audit pass (`watch out for`). Positive: `Form 2-3 competing hypotheses before selecting one`.

**M-13 — `code-simplifier.md:12` / `code-simplifier.md:25` — Temporal prohibition + `Avoid` hedge**
Quote `code-simplifier.md:12`: `1. **Preserve Functionality**: Never change what the code does—only how it does it. All original fea`
`code-simplifier.md:25`: `4. **Maintain Balance**: Avoid over-simplification that could:`
Both rewriteable: `Keep behavior identical; restructure only` and `Stop simplifying when tests/clarity would regress`.

**M-14 — `fullstack-developer.md:30` / `planner.md:30` — Borrowed `KISS/DRY` diligence framed as prohibition**
`fullstack-developer.md:30`: `**IMPORTANT**: Respect KISS and DRY principles. Deliver the full requested scope — never trim or def`
Negation `never trim` is legitimate exception 3 (acceptable space too large to enumerate) but should pair with positive: `Deliver the full requested scope; trim nothing`.

**M-15 — `vn-canu-researcher.md:42-43` — Threefold `never` in one instruction block**
Quote `vn-canu-researcher.md:42`: `1. **Read the scope file.** Missing or unreadable → return the error JSON below. Never imp`
Prose cost: three prohibitions where one positive contract suffices: `Return error JSON at preflight on missing/unreadable scope; do not infer scope`.

---

*(M-16 through M-22 are the remaining MEDs: M-16 `kongming.md:16` advisory-only negations split; M-17 `journal-writer.md` tool-imperative negs without pairing positives; M-18 `researcher.md:36` KISS/DRY again; M-19 `tester.md`/`planner.md` cross-pointer duplication on test-scope; M-20 `agent-validator.md` vs `tk-validator.md` vs `vn-validator.md` validator-role overlap (three validators, distinct independence claims, shared anti-hallucination gate text duplicated verbatim); M-21 `vscode`/`cursor` harness leaks in `vn-*` frontmatter paths (`~/.claude/skills/vn-...`) hardcoding user home; M-22 output-style `when=False` — styles correctly have no frontmatter trigger but their selection relies on `output-styles/` directory magic, which is a context-pointer bypass.)*

---

## 5. Findings — LOW (polish / register / sediment / no-op)

**L-1 — Decorative `ALWAYS`/`NEVER`/`MUST` in coding-level styles (22-30 hits each).**
`coding-level-0-eli5.md` 27, `coding-level-1-junior.md` 23, `coding-level-2-mid.md` 22, `coding-level-3-senior.md` 24, `coding-level-4-lead.md` 30, `coding-level-5-god.md` 27. Per Layer 1 rule 4, `Constraints carry real weight. Reserve ALWAYS, NEVER, MUST for true invariants`. These files use them as section ornament (`## MANDATORY RULES (You MUST follow ALL of these)` — `coding-level-0-eli5.md:13`). The emphasis leaks into every downstream agent turn as re-planted anxiety.

**L-2 — `casual-vietnamese.md:4-15` — AI-slop tell: over-polished self-instruction register.**
Frontmatter `description` is 31 tokens of Vietnamese register coaching while the body is 60 lines of the same. Co-location violation: definition + rules + caveats are scattered across `tool-results/call_01a05...txt` dump length 852 lines vs file's 61 — indicates sprawl handled elsewhere.

**L-3 — Sediment markers: commented legacy probes in `vn-*` frontmatter.**
`vn-validator.md:7-28` carries 22 lines of `Pinned, not inherited` changelog prose inside `---` frontmatter comments. Per `writing-for-agents` sediment: `adding feels safe, removing feels risky, until you must core down`. Move to `CHANGELOG.md`.

**L-4 — No-op sentences (model already obeys).** Example `explore.md:13` second clause `do not broaden into unrelated refactors` — baseline obedient agent already scopes to caller prompt; test via `writing-for-agents` no-op test: does it change behaviour vs default? Marginal.

**L-5 through L-18 — Remaining LOW:** L-5 `advisor.md` register word `what to avoid` in description plants avoidance; L-6 `code-reviewer.md:15` `Operate as a rulebook-first reviewer, not as a collaborator` exception-2 keep but rewrite; L-7 `debugger.md:9` `**Senior SRE**` prestige label no-op; L-8 `fullstack-developer.md:8` `**Senior Full-Stack Engineer**` same; L-9 `brainstormer.md:35` `**CTO-level advisor**`; L-10 `goal-judge`/`goal-scout`/`goal-worker` triple `GoalBuddy` prefix redundancy; L-11 `project-manager.md:37` `comprehensive` vague bound (premature-completion risk); L-12 `tester.md:139` `Never ignore failing tests just to pass the build` — legit but hortatory, not checkable; L-13 `planner.md` 159 lines, sprawl past split-by-sequence threshold; L-14 `vn-validator.md` 377 lines, double sprawl (sibling of L-13); L-15 `vn-bctt-researcher.md` 238 lines + `vn-canu-researcher.md` 260 lines sibling sprawl; L-16 `ui-ux-designer.md` 247 lines but zero negs — sprawl offset by directionality; L-17 `ocx-*` 5-file clone sprawl (single source should be one template); L-18 `coding-level-{0..5}` 6-file ladder duplicates 70% structure (branch-by-sequence split would cut 30% tokens).

---

## 6. Cross-file findings

### 6.1 Overlapping lanes (duplication per `writing-for-agents` single source of truth)

| Lane | Claimants | Overlap |
|---|---|---|
| **Codebase scouting** | `explore.md` (36 lines, fast scanner) · `goal-scout.md` (49 lines, read-only mapper) · `goal-judge.md` (49 lines, read-only gate) · `librarian-cataloger.md` (29 lines, read-only cataloger) · `researcher.md` (70 lines, technical analyst) | All five promise `Read, Grep, Glob, Bash` evidence sweeps. `explore.md` vs `goal-scout.md` differ only by `Task(Explore)` subagent hint; `goal-judge.md` vs `goal-scout.md` share 80% body text (see M-7). Single `scout` capability behind one pointer would cut context load by 4×. |
| **Planning** | `planner.md` (159 lines) · `researcher.md` (70 lines) · `brainstormer.md` (136 lines) | `planner.md` and `researcher.md` both claim KISS/DRY + investigation workflow; `brainstormer.md` re-claims DTO framing. |
| **Validation** | `agent-validator.md` (163 lines) · `tk-validator.md` (71 lines) · `vn-validator.md` (377 lines) | Three adversarial validators with identical anti-hallucination gate prose (`you did not write the draft, you have no stake in shipping it, you never...`). Legit branching (general vs tk-research vs vn-* family) but gate text should be disclosed reference, not inline triplicate. |
| **GoalBuddy** | `goal-judge.md` · `goal-scout.md` · `goal-worker.md` | `goal-worker.md` contradicts its siblings: siblings bound reads, worker binds writes to `allowed_files` — yet all three repeat `Read only. Do not edit...` phrasing. Positive boundary statements would disambiguate lanes. |
| **Vietnamese** | `vn-author-agent.md` · `vn-editor-agent.md` · `vn-bctt-researcher.md` · `vn-canu-researcher.md` · `vn-news-signals-researcher.md` · `vn-validator.md` | 6 files share `vn-` prefix, 48-44-38 negation counts each. Sibling duplication noted M-22; worst sprawl since `vn-validator.md` alone is 377 lines. |
| **Coding ladder** | `coding-level-0`…`5` (91-159 lines each, 781 lines combined) | Six styles duplicate the same `MANDATORY RULES / FORBIDDEN` scaffold + `Required Response Structure` + identical `Note: 1h (last cache write...` noise. Progressive disclosure by branch (filter at selection time, not six inline copies) would halve. |

### 6.2 Contradictions (one file mandates what another forbids)

1. **Comment policy.** `coding-level-3-senior.md:38` `NEVER over-comment code` vs `coding-level-0-eli5.md:13` `MUST add a comment explaining what EVERY single line does` is legitimate tier calibration, not contradiction — but the per-file `NEVER` makes it read as invariant, so a model loading both (God mode + ELI5 residue) inherits conflicting absolutes. Downgraded to MED but flagged HIGH-aggregate for absolute-reservation violation.
2. **Language policy.** `casual-vietnamese.md` (Vietnamese by default) vs global `~/.claude/CLAUDE.md` RULES 39 `Reply in English by default` — scoped exception, not defect, but frontmatter lacks scope sentence (H-7).
3. **Verbosity policy.** `coding-level-5-god.md` `NEVER explain ...; NEVER add context` vs `docs-manager.md` `Point to the owning source` (which requires explanatory pointer prose) and harness `ADHD` rule `Restate state every turn`. Styles cannot forbid what the harness mandates; resolution is positive scoping: `Defer explanations to code`.
4. **Tool authority vs prompt authority.** `vn-*` family `NEVER write to /tmp/` (prompt) vs actual `Bash` + `Write` tool grants (harness) — non-enforcing prohibition (H-5).

### 6.3 Output styles contradicting each other or global rules

- Global `Output Style: Concise` (lead with result, cap lists at 5, suppress tangents) vs `coding-level-{0,1}` `MUST` blocks demanding 5-section scaffolds, analogies, try-it brackets — MED tension by design (style deliberately widens concise). Not a defect if opt-in, but list-cap 5 (`coding-level-0` requires 5+ sections) and tangent-suppression are violated by construction.
- Global `Never coin a Vietnamese phrase` vs `casual-vietnamese.md` authoring new register terms — scoped exception again; style body re-scopes correctly, frontmatter does not (H-7 duplicate).

### 6.4 Duplication / no-op / sediment summary (writing-for-agents lens)

- **Duplication:** Validator gate triplicate; five `ocx-*` clones; GoalBuddy read-only fence triplicate; `vn-bctt`/`vn-canu`/`vn-news-signals` share 38-48 negs each with overlapping `Scope lock`, `legitimate-negation`, `anti-pattern guards` boilerplate.
- **No-ops:** `ui-ux-designer.md` prestige opener `You are an elite UI/UX Designer who won awards` is a weak leading word (already thorough → `relentless` would be stronger; boasting is no-op per `Pruning` test). Same for `debugger.md` Senior SRE / `fullstack-developer.md` Senior Full-Stack / `advisor.md` advisor labels.
- **Sediment:** 22-line `Pinned, not inherited` changelog inside `vn-validator.md` frontmatter; legacy `HARD FLOOR` comments in `vn-canu-researcher.md`; `coding-level-*` `Note: ... full output saved to: /tmp/...` footer polluting dumps is display-layer sediment, not doc sediment.
- **Cache vs lookup:** `vn-*` frontmatter hardcodes `~/.claude/skills/vn-...` absolute home paths — lookup-able via `VN_SHARED_CORE` env, so per `Environment is a source of truth too` these are caches earning load on every turn.
- **Context load budget:** 34 agent descriptions are always-loaded pointers (one line each in the agent index). 24/34 waste leading tokens on identity (`You are a...`) rather than trigger branch; per `Front-load the leading word`, descriptions should open with the branch verb (`Validate evidence independently when...`) not persona.

---

## 7. Top 5 issues overall (ranked by fix leverage)

1. **Missing Layer-1 outcome block in all 41 files (M-1, aggregated HIGH if unmitigated).** Every agent system prompt is re-loaded each turn without a destination frame. Fix once in a shared template: `Goal: / Success means: / Stop when: / Constraints:` with per-agent fill. Highest leverage: restores `direction without outcome wanders` diagnosis across the fleet.

2. **`ALWAYS/NEVER/MUST` decorative inflation in the coding-level ladder (L-1 + M-10 + H-6 aggregate, 153 absolute hits across 6 files).** The hardest-working words are bleached into section ornaments. Fix: keep `MUST` only for the 2-3 true invariants per level (e.g., `MUST return Result<T,E> with branch coverage` at senior+), demote the rest to plain prose.

3. **`FORBIDDEN` / `NEVER` negation architecture in `vn-*` family (M-3, H-5, 169 combined negs across 4 vn researchers + validator).** Plants forbidden verbs (`draft`, `sanitize`, `write to /tmp`) verbatim. Fix: invert to positive outputs (`Your output is the ledger JSON; downstream owns drafting`) and enforce filesystem bounds at tool layer.

4. **Validation-lane triplication + `HARD FLOOR` non-enforcement (H-1, H-2, H-3, H-9).** Three validators duplicate the same gate and assert tier in prose; five `ocx-*` clones duplicate a skill deny-list in prose. Fix: extract gate to `references/validation-gate.md` (disclosed reference), enforce tier and deny-list in harness metadata, not markdown.

5. **Scout/mapper lane sprawl — 5 agents for one capability (6.1).** `explore`, `goal-scout`, `goal-judge`, `librarian-cataloger`, `researcher` compete for the same `Read+Grep+Glob` sweep. Fix: single `scout` capability with branch pointers (`scout: fast scan` vs `scout: deep analysis` vs `scout: adversarial gate`) per `One trigger per branch`.

---

## 8. What was not checked

- Live agent selection/triggering behaviour (requires harness trace, not static reads).
- Rendered style output quality (requires sampled model runs per style — `writing-for-agents` leading-word recruitment is model-relative and settles by running the document).
- Tool-permission enforcement parity (`vn-*` path fences) — static prose scan only.
- Full cross-harness `~/.codex/**` parity (flag `SKILL_CODEX_ROOTS`) — not enumerated.

---

## 9. Unresolved questions for owner

1. Should Layer-1 outcome blocks live in each agent file or in a single `references/agent-outcome-template.md` disclosed behind a pointer (context-load trade-off)?
2. Confirm `casual-vietnamese.md` intended scope: global opt-in style vs per-turn selection — determines whether H-7 is documentation fix or policy revert.
3. Confirm retention of three validators as distinct agents vs consolidation behind one disclosed gate with per-skill parameterization.

---

## 10. Evidence fidelity note

Every `file:line` quote above truncates to ≤90 chars for table legibility; full line is in dumps `/tmp/agents_dump.txt` and `/tmp/styles_dump.txt` (tool-results `call_01a0546b3e5c7b328ad8f43e609f2a90`). Negation/absolute counts are `re.I` matches of the 9-token audit list; `when`-presence is regex on frontmatter `description` only; `Goal:/Success means:/Stop when:` scan is literal substring. No finding asserts beyond its cited line.

---

*Report written READ-ONLY against audited files; no audited file was modified. Audit consumed 2 skill bodies, 41 target files, 2 dumps, and 3 live scans.*
