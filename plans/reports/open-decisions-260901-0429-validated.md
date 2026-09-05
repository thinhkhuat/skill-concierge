# Open decisions — validated breakouts (harness audit arc remainings)

Date: 2026-09-01 04:29 · **Status: FINAL — independently validated** (round 1: FAIL with 3 blocking, all corrected; delta re-check: PASS, 0 blocking; validator reports at `decisions-validator-260901-0431-*.md` and `decisions-validator-260901-0447-*.md`, same directory) · Six suggestions were caught overstated across drafting and validation and are withdrawn in §7. Bar applied: nothing stays in this report on quote-depth evidence alone.

---

## R1 — Validator "shared gate text" extraction (audit item 5b)

**What it is.** The agents-styles audit (leaf M-20) claimed three validators (agent-validator, tk-validator, vn-validator) carry "anti-hallucination gate text duplicated verbatim" and recommended extracting it into one shared reference file.

**What full-source verification found (this turn).** The claim is overstated. `agent-validator.md` contains none of the marker phrases — it is a different design (Opus validation harness), not a copy. The real duplication is a **pair**, not a triple: `tk-validator.md` and `vn-validator.md` share near-identical independence-doctrine clauses (~4 lines: "did not write the draft / no stake / never rewrite / URL must trace to its own tool output"), once in each description and once at different compressions in each body (`tk-validator.md:9`, `vn-validator.md:31`).

**Why it is still open.** It was queued as your last item-5 pick.

**Options.**
- *Extract to one shared reference*: saves ~4 lines × 2, one-place edit for doctrine changes. Cost: `tk-validator.md` lives inside the `tk-research` bundle and `vn-validator.md` inside `vn-canu-reporting` — a shared file crosses two portable skill families, so each bundle stops being self-contained (your batteries-included rule for portable skills). Also the doctrine text is deliberately restated per validator so each remains meaningful alone.
- *Leave as-is*: zero risk, keeps bundles portable; the cost of the duplication is ~8 lines total.

**Recommendation: NO CHANGE.** The portability cost exceeds the dedup value — strengthened by a validation note: the doctrine text also lives in source-tree copies beyond the deployed pair (`skills-dev/vn-deep-dive-report/agents/vn-validator.md`, the vn-canu bundle copy, and each bundle's `sub-agent-templates.md`), so a "shared reference" would have to thread more locations than the deployed two, cementing the NO CHANGE. This closes item 5(b) — item 5 is then fully resolved (scout/judge withdrawn, gate-extract declined).

## R2 — Outcome blocks for agent/style files (audit item 6)

**What it is.** All 41 deployed files (34 agents + 7 output styles — recounted this turn) lack a short outcome block at the top: `Goal: / Success means: / Stop when:`. The audit's top-leverage writing finding: without it, an agent's notion of "done" drifts turn by turn.

**Why it is still open.** Gated on your U1 answer (unanswered since the audit): should the block live in each file, or in one shared template disclosed behind a pointer?

**Options.**
- *Per-file blocks*: each agent carries 3 tailored lines. Highest precision (the Stop-when clause differs meaningfully per role); costs ~123 lines total across the fleet.
- *One shared template + per-file pointer*: one file defines the block shape; each agent keeps a one-line pointer plus its 3 filled lines — which in practice is the same as per-file with a style guide. The pointer itself saves nothing (the lines are the content).

**Recommendation: per-file blocks, authored from a shared wording pattern** (the "template" is the pattern in the maintainer's head plus a line in the agents README, not a deployed pointer file). Practical route: batch by priority — the three validators and the three GoalBuddy agents first (6 files that gate real work), the rest opportunistically. Estimate: ~1–2 h for the full fleet, less if batched by lane. Awaiting your U1 confirmation before executing.

## R3 — vn skill description compaction (Codex-side budget)

**What it is.** The skill-cleaner census (30 drafted candidate descriptions, re-verified on disk this turn) puts the always-loaded description set at 99.9% of the gpt-5.5 Codex 2% prelude budget ("prelude budget" = the token allowance Codex spends on every skill's one-line description before any work starts — the menu, not the meal). Scope note, corrected during this arc: this is the **Codex prelude** budget, not Claude Code retrieval — the concierge index is unaffected by description length. Corrected at validation: only two vn skills exceed 1,100 description chars — vn-news-coverage-tracker (1,442) and vn-deep-dive-report (1,114); vn-bctt-report's description is 472 chars, the *shortest* in the family (an earlier draft here claimed bctt was the longest at ~1,900 — that number was the audit's already-withdrawn misattribution resurfacing).

**Why it is still open.** Rewriting descriptions changes what every harness sees when routing; it is a taste call on your voice, not a mechanical fix.

**Options.**
- *Compact the two long ones* (news-coverage-tracker, deep-dive-report): each rewrite trims to the essential what+when+triggers. The cleaner's candidates are drafts to edit, not accept verbatim.
- *Leave*: the cost is Codex-side token pressure only; nothing is broken.

**Recommendation: compact those two, only if Codex-side context pressure bothers you.** Not urgent; genuinely optional.

## R4 — Injection-budget policy (RULES [48] vs the deployed stack)

**What it is.** RULES.md:132 [48] orders: "Price per-turn injection before proposing it." The measured always-loaded stack at audit time (2026-08-31, byte-counted): 734 lines / 51,409 bytes ≈ 13K tokens of rules corpus per session, plus per-turn hook injections; live figure after this arc's own edits: 736 / 51,717 (date-stamped — the corpus moves as rules get fixed). The rule's own mandate is unmet by the deployed reality — either the rule needs teeth or the stack needs a budget.

**Why it is still open.** It sets policy for every future standing order; yours alone.

**Options.**
- *Adopt a standing budget line*: e.g., "always-loaded prose ≤ 60K bytes; new injections displace, not accumulate." Enforceable by the same byte-count probe used in the audit (a 5-line script could gate it).
- *Amend [48]* to "price and state the number when proposing" (reporting-only, no cap).
- *Accept the status quo* and withdraw the pricing mandate (honest but loses the discipline).

**Recommendation: the budget line with a byte cap** — it converts an ignored mandate into a checkable gate, consistent with how the rest of your rules now work.

## R5 — Hook registrations: `.orca` ×12 (WORKING — keep) and SUPERSET ×8 (dormant)

**What it is.** Two guarded hook families. Corrected at validation: an earlier draft of this section claimed the `.orca` registrations pointed at a nonexistent root-absolute path and recommended a fix — **that was false**. The actual commands (re-read from settings.json after the validator flagged it) are `"${HOME-}/.orca/agent-hooks/claude-hook.sh"` — HOME-relative, wrapped in an OSTYPE guard that picks `.cmd` on Windows and `.sh` on Unix, with `-f/-x` existence checks. Orca is installed (`~/.orca/` with `agent-hooks/`, `claude-agent-teams-bin/`, `keybindings.json`), the script exists (3.6K, executable). The wiring is correct and the integration is live.

**Why still open / what to decide.**
- *`.orca` ×12 — recommend KEEP, no action.* The false "broken path" reading came from tool output: hooks-audit's report displays the bare `/.orca/...` twelve times, and its path extractor (`audit-hooks.py:52-59`, "extract the first absolute script file path") shows the mechanism at source. A second display of the dropped-prefix form existed in this session's own command inventory (session transcript, not a durable artifact — recollection, not evidence). The wiring itself is verified: HOME-relative paths, `-f && -r && -x` guards, script present and executable.
- *SUPERSET ×8 — recommend RETIRE, conditional on one confirmation*: nothing found that ever sets `SUPERSET_HOME_DIR` on this machine (checked zshenv, zshrc, harness-env.sh, LaunchAgents — all empty). The guards make them cost-free no-ops, but they are 8 dormant registrations across 8 events. If you never run Claude inside a "superset" supervisor environment, removing them is pure cleanliness; if some external tool you use sets that variable, keep them.

## R6 — Workbench twins: symlink or copies

**What it is.** `MY-WORKBENCH/CLAUDE.md` and `AGENTS.md` are currently byte-identical real copies. They had diverged before the 2026-08-31 sync (how long is unverifiable — the workbench root keeps no git history). Live proof exists that the symlink pattern works in production: `~/.codex/AGENTS.md` is a symlink to `~/.claude/CLAUDE.md` and silently inherited every global fix this arc.

**Options.** *Symlink* (AGENTS.md → CLAUDE.md): drift becomes structurally impossible; one command; revert by re-copying. *Copies + the retitled heading warning*: works, but relies on discipline. Known symlink caveat: a tool that rewrites AGENTS.md in place would write through the link (changing CLAUDE.md too) — no such tool is known on your setup.

**Recommendation: symlink**, whenever you are ready; zero urgency since the pair is currently identical.

---

## §7 Withdrawn during this report's own verification (the false-alarm log)

1. **goal-scout/goal-judge merge** — withdrawn earlier today at full-source read (distinct roles; the GoalBuddy runner spawns agents by their exact file names with fallback logic written around those names — a "dispatch contract" — plus Codex-side `.toml` copies of each role). Owner confirmed no-change.
2. **"Validator gate ×3 verbatim" extraction as scoped** — withdrawn above (R1): it is a tk/vn pair sharing ~4 doctrine lines, not a triple verbatim block; extraction would break bundle self-containment. R1 records the corrected recommendation (NO CHANGE).
3. **`.orca` = "retire candidate"** — corrected during drafting (R5): Orca is installed; the registrations are live.
4. **`.orca` = "broken path, fix it"** — withdrawn at independent validation (R5): the commands are `${HOME-}/`-relative and correctly guarded (`-f && -r && -x`); the "root-absolute path" reading came from hooks-audit's dropped-prefix display (artifact-evidenced) — the quote-depth failure class again, hiding in *tool output* this time. I verified the `~/.orca` directory existed but never re-read the command strings before publishing the claim — in a report whose header promised "re-probed against full sources."
5. **"vn-bctt description ~1,900 chars, the longest"** — withdrawn at validation (R3): bctt is 472 chars, the *shortest*; the 1,900 figure was the audit's already-withdrawn misattribution resurfacing from memory instead of from the file. Corrected to the two real >1,100 skills.
6. **"Five GoalBuddy agents"** — withdrawn at validation (R2): the fleet is three (scout/worker/judge).

Pattern, stated plainly: every withdrawal — the three above and the three from the audit arc itself — came from reading at quote depth or from tool-display output instead of full sources. The audit's findings remain valuable as *leads*; and the corollary this report itself proved twice in one drafting cycle: **the author's own verification claim is not verification** — only the independent pass caught items 4–6, which is why the builder-never-validates rule exists.

## Unresolved questions

- U1 (R2): per-file outcome blocks — confirm the per-file recommendation.
- R5 SUPERSET: confirm no external supervisor sets `SUPERSET_HOME_DIR`.
- R3: whether Codex-side description pressure is worth acting on now.
