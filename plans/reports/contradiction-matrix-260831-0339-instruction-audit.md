# Cross-surface contradiction matrix (G5)

Date: 2026-08-31 · Method: (a) mechanical pairwise term-collision scan over 13 config-surface files = 78 pairs, all executed; (b) 26 deep pairs enumerated below where signal existed (config × config, hooks × config, styles × config, agents × config, agents × agents, skills × config). Relationship types: CONTRADICT (one mandates what another forbids) · OVERLAP (duplication, two authorities one lane) · DRIFT (copies diverged) · AMBIG (internally unclear).

pairs-checked: 98

(78 mechanical + 26 deep rows, of which 6 overlap the mechanical set — 98 distinct pairs.)

## Deep pairs

| # | Pair | Rel | Evidence (both sides) | Sev |
|---|------|-----|----------------------|-----|
| 1 | workbench `CLAUDE.md:52` × `RULES.md:134` | CONTRADICT | "## Token efficiency (applies to every response)… If a task needs 1 tool call, don't use 3" × "[49] Token economy is never a reason to do less." Resolution clause covers only completion discipline | HIGH |
| 2 | `hooks/dev-rules-reminder.cjs` × system Language mandate / Constitution §1 | CONTRADICT | "Sacrifice grammar for the sake of concision when writing reports." × "Maintain full orthographic correctness for English" + "Terse, direct, and complete sentences" | HIGH |
| 3 | `rules/documentation-management.md` × `docs/documentation-management.md` | DRIFT | 28 vs 72 lines, same name, both deployed (auto-loaded vs on-demand index target) | HIGH |
| 4 | `rules/orchestration-protocol.md` × `docs/orchestration-protocol.md` | DRIFT | 49 vs 116 lines | HIGH |
| 5 | `rules/skill-domain-routing.md` × `docs/skill-domain-routing.md` | DRIFT | 42 vs 159 lines | HIGH |
| 6 | `rules/skill-workflow-routing.md` × `docs/skill-workflow-routing.md` | DRIFT | 53 vs 73 lines | HIGH |
| 7 | `rules/CLAUDE.md:22` × the four pairs above | CONTRADICT | "## Shared blocks (single source of truth)" indexes exactly the divergent copies | MED |
| 8 | `RULES.md:85` (self) | AMBIG | "exa → exa advanced → `tvly` → `firecrawl`; `web_search` is 4th" — 4 precede it | MED |
| 9 | `RULES.md:5-6` (self) | withdrawn | "77 rules" + "[62] withdrawn" — 77 distinct live indexes; header accurate. Original 76-live DRIFT claim was a unit error, caught at validation (INFO) | INFO |
| 10 | `hooks/dev-rules-reminder.cjs` × `rules/development-rules.md:10` | OVERLAP | KISS/DRY/YAGNI + `--yagni` convention injected twice per turn (hook block + auto-loaded rule file) | MED |
| 11 | SKILL-FIRST order × `rules/skill-domain-routing.md` × using-agent-skills flowchart × `rules/skill-workflow-routing.md` | OVERLAP | Four skill-routing authorities all always-loaded; enforcer token system vs "capability map" vs flowchart vs bracketed-capability resolution | MED |
| 12 | `rules/primary-workflow.md` × `rules/skill-workflow-routing.md` × using-agent-skills lifecycle | OVERLAP | Three workflow maps (5-phase core loop vs capability chain vs 16-skill lifecycle) co-deployed; precedence unstated except piecemeal | MED |
| 13 | `output-styles/coding-level-5-god.md:40,43` × global Concise style + ADHD restate-rule | CONTRADICT | "**NEVER** explain concepts… **NEVER** add comments" × "lead with result", "Restate state every turn" | HIGH |
| 14 | `output-styles/casual-vietnamese.md:3` × `RULES.md` [39] | AMBIG | Vietnamese-default style × "Reply in English by default" — body re-scopes (`:14`), frontmatter carries no scope sentence | MED |
| 15 | `coding-level-3-senior.md:38` × `coding-level-0-eli5.md:13` | AMBIG | "NEVER over-comment code" × "MUST add a comment explaining what EVERY single line does" — tier calibration stated as invariants; both loadable in one session | MED |
| 16 | `coding-level-5-god.md` × `agents/docs-manager.md` | CONTRADICT | "NEVER explain / NEVER add context" × "Point to the owning source" (explanatory pointer prose required) | MED |
| 17 | `agents/vn-bctt-researcher.md:50` (+ `vn-news-signals-researcher.md:69`) × harness tool grants | CONTRADICT | "NEVER write to `/tmp/`, `~/Desktop`, or any path outside {plan_dir}" × `tools: Read, Write, Edit, Bash` unscoped | HIGH |
| 18 | `agents/vn-validator.md` × `agents/tk-validator.md` × `agents/agent-validator.md` | OVERLAP | Three validators, independence claims + anti-hallucination gate text duplicated verbatim | MED |
| 19 | `agents/explore.md` × `goal-scout.md` × `goal-judge.md` × `librarian-cataloger.md` × `researcher.md` | OVERLAP | Five agents claim the same Read+Grep+Glob sweep; goal-judge/goal-scout share ~80% body | MED |
| 20 | `agents/ocx-*.md` ×5 (`:15` each) | OVERLAP | Identical "Do not invoke blocked Claude Code skills" deny-list duplicated in prompt prose, belongs in router | MED |
| 21 | `agents/goal-worker.md:15-18` × `goal-judge.md:13`/`goal-scout.md:13` | AMBIG | Siblings repeat "Read only. Do not edit…" phrasing while worker's actual fence is write-bounding `allowed_files` | MED |
| 22 | `CLAUDE.md:42,44` (behavioral defaults) × Constitution §2/§3 × `RULES.md` [15][44] | OVERLAP | Fabrication + flattery rules stated three times in one payload | LOW |
| 23 | `RULES.md:132` [48] × deployed always-on stack | CONTRADICT | "Price per-turn injection before proposing it" × unpriced 51.4KB rules corpus + per-turn hook stack | MED |
| 24 | Session-start `[cache-ttl]` block × 6-block injection stack | AMBIG | "Report this TTL to the user in your first reply" — no checkpoint; observed missed in the audit session itself | MED |
| 25 | `~/.claude/skill-concierge/keep-on.json` `_note` × `keep_on` list | DRIFT | Note: "the ck:/vn: skills must exist on the target machine" — zero ck:/vn: entries remain (snapshot 2026-06-26) | LOW |
| 26 | `skill-concierge/CLAUDE.md` × workbench `CLAUDE.md` | OVERLAP | 57 shared distinctive terms; hard-rule restatement is deliberate layering, but nothing marks which copy is canonical when they diverge | INFO |

## Mechanical batch (78 pairs)

All C(13,2) pairs across {CLAUDE.md, RULES.md, workbench CLAUDE.md, project CLAUDE.md, 9 rules/*.md} executed via distinctive-term collision scan. Top overlaps: CLAUDE.md × RULES.md (110 shared terms — import plus restatement), CLAUDE.md × workbench (97), RULES.md × workbench (95), CLAUDE.md × anti-patterns.md (84), RULES.md × anti-patterns.md (77). Lowest: process-management × development-rules (2 shared) — clean separation. Full ordered list preserved in the session transcript of 2026-08-31 03:46.

## Verdict

No pair is an unrecoverable conflict: every HIGH has a concrete directional fix (state the positive rule once, enforce at the tool layer, or delete the divergent copy). The dominant pattern is not contradiction but **unpriced duplication** — the same authority restated across 2–4 always-loaded surfaces (pairs 1, 10, 11, 12, 18, 19, 20, 22), which is what makes the rare true contradiction (2, 13, 17) hard to see at injection time.
