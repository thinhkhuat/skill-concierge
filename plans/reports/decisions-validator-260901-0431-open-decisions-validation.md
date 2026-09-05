# Validation — open-decisions-260901-0429-validated.md (R1–R6 + §7)

Validator: independent (did not author the report under review) · Date: 2026-09-01
Subject: `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/plans/reports/open-decisions-260901-0429-validated.md`
Bar applied: zero false alarms — every number re-derived from source; every recommendation tested against full sources.

**VERDICT: FAIL** — 3 blocking false alarms (R5 premise, R3 bctt claims, R2 count), 5 advisory.

## Blocking findings

### B1 — R5's central premise is false; its FIX recommendation is a no-op
Report claims (R5): "all 12 registrations in settings.json point at `/.orca/agent-hooks/claude-hook.sh` — **root-absolute, a path that does not exist**… with `HOME` set, the guard's else-branch executes the wrong path and fails quietly" → recommend FIX (repoint to `$HOME/.orca/...`).

Source reality (`~/.claude/settings.json`, 12 orca registrations at lines 922/989/1010/1096/1199/1253/1272/1313/1333/1344/1403/1414): every command is
`if [ -z "${HOME-}" ]; then … printf '{}\n'; else case "${OSTYPE-}" in … *) if [ -f "${HOME-}/.orca/agent-hooks/claude-hook.sh" ] && [ -r … ] && [ -x … ]; then /bin/sh "${HOME-}/.orca/agent-hooks/claude-hook.sh"; else … printf '{}\n'; fi ;; esac; fi`
- The path is **`${HOME-}`-relative, not root-absolute** — the `${HOME-}/` prefix is in every registration.
- The else-branch **executes nothing** — it prints `{}` (no-op JSON). The then-branch executes the **correct** path, and the script exists (`~/.orca/agent-hooks/claude-hook.sh`, 3,667 bytes = 3.6K, mode rwxr-xr-x).
- Nothing is broken; the hooks are correctly wired. The report's prescribed FIX ("repoint to `$HOME/.orca/...`") would change already-deployed state.
- Origin of the error: `hooks-audit-260831-0339-instruction-audit.txt:8-32` lists these as "MISSING FILES: `/.orca/agent-hooks/claude-hook.sh`" — a parsing artifact of the audit tool (it extracted the path substring and dropped the `${HOME-}/` prefix). The report inherited the tool output instead of reading the command strings — the exact quote-depth failure class §7 claims to have eliminated. §7.3 corrects the "retire" framing but keeps the equally wrong "path bug" framing.

### B2 — R3's vn-bctt length claims are false and resurrect a figure the arc already corrected
Report claims (R3): "several `vn-*` skills carry 1,100–1,900 character frontmatter descriptions"; "bctt first — its description is the longest at ~1,900 chars"; recommendation "starting with vn-bctt-report".

Source reality:
- `~/.claude/skills/vn-bctt-report/SKILL.md:4` description = **472 chars — the SHORTEST in the vn family** (identical file in `~/.codex/skills/`). It is already compact.
- Longest vn description on disk: `vn-news-coverage-tracker` = **1,442 chars** (census agrees: `description=1442`); next `vn-deep-dive-report` = 1,114. Only two vn skills exceed 1,100. No vn description approaches 1,900; no source contains a 1,900 figure (grep across `plans/reports/` finds it only in the validation report that *corrected* it).
- `validation-260831-0339-instruction-audit.md:12` already withdrew this exact number earlier in the arc: "'vn-canu-family description (~1,900 chars) appears 5×' misattributes the cleaner leaf: the 5× description is `vn-deep-dive-report` at 1,114 chars". The report under review resurrects the corrected-away figure and attaches it to a different skill.
- vn-bctt-report does not appear among the 30 census candidates at all.

The "compact, starting with vn-bctt-report" recommendation is false-premised: it targets the family's shortest description. (R3's other elements verified: 30 candidates exact; `used_of_2%_budget: 99.9%` of gpt-5.5 Codex 2% budget exact — census header; the Codex-prelude-not-concierge scope note accurate.)

### B3 — R2's "five GoalBuddy agents" is a false count
Report (R2 recommendation): "the three validators and **five GoalBuddy agents** first".
Source reality: the GoalBuddy fleet is **3** agents — goal-scout, goal-worker, goal-judge:
- `~/.claude/agents/`: exactly 3 `goal-*.md` files.
- `~/.claude/skills/goal-prep/agents/`: `goal_judge.toml`, `goal_scout.toml`, `goal_worker.toml` (3).
- `~/.codex/agents/`: 3 roles in two spellings (`goal-judge.toml`/`goal_judge.toml`, etc.).
- `skills goal-prep /references/goal-execution.md:300-302` names exactly those three as the dispatch contract.
No reading of any source yields five. The priority work order misstates its own scope (8 files claimed → 6 actual).

## Advisory findings

1. **R1 nuance — extra doctrine copies not mentioned.** The "pair, not triple" claim is TRUE on the deployed agent surface (grep of all 34 agents: the four doctrine clauses appear only in `tk-validator.md` and `vn-validator.md`; `agent-validator.md` has none; line cites tk:9 / vn:31 exact; descriptions line 3 each). But the source tree adds copies the report omits: `skills-dev/vn-deep-dive-report/agents/vn-validator.md`, `skills-dev/vn-canu-bundle/components/vn-canu-reporting/agents/vn-validator.md`, and the doctrine inside each bundle's `references/sub-agent-templates.md`. This STRENGTHENS the NO CHANGE portability argument (a shared reference would need to reach three bundles, not two) but the report's "~8 lines total" and "crosses two portable skill families" cover the deployed surface only.
2. **R4 figure slightly stale.** Cited "734 lines / 51,409 bytes (this arc, byte-counted)" — provenance accurate and independently validated as exact at measurement time. Live recount: **736 / 51,717** (`~/.claude/CLAUDE.md` edited Sep 1 03:26, after the measurement). Drift +2 ln / +308 B (~0.6%); no impact on the recommendation. A byte figure in a "re-probed this turn" report should be re-derived or date-stamped.
3. **R5 imprecision that survives:** "`~/.orca/` exists with `agent-hooks/`, `claude-agent-teams-bin`, **config**" — no `config` entry exists in `~/.orca/` (contents: `agent-hooks/`, `claude-agent-teams-bin/`, `keybindings.json`, `minimax-session-cookie.enc`).
4. **R6 history unverifiable:** "drift risk returned twice… diverged for months" — divergence-before-sync is verified (roadmap item 3 records AGENTS.md as a stale twin, resolved 2026-09-01), but "twice"/"months" have no artifact trail (workbench root is not a git repo). Core R6 facts verified: `~/.codex/AGENTS.md` is a symlink to `~/.claude/CLAUDE.md`; workbench twins cmp byte-identical, both regular files.
5. **Register:** mostly plain; "root-absolute", "Codex prelude", "else-branch", "dispatch contract" would not parse for a smart non-specialist unglossed — and R5's headline term ("root-absolute") is also wrong.

## Verified-clean spot-checks (independent re-derivation)

| Claim | Report | Independent | Match |
|---|---|---|---|
| Agent files | 34 | 34 (`ls` glob) | yes |
| Output styles | 7 | 7 | yes |
| Outcome blocks absent from all 41 | "lack" | grep `Success means\|Stop when:` → 0 files | yes |
| Doctrine text location | pair; desc line 3 + body tk:9/vn:31; agent-validator none | grep confirms exactly | yes |
| Census candidates | 30 | 30 (parsed) | yes |
| 99.9% Codex 2% budget | 99.9% | census `used_of_2%_budget: 99.9%` (5,432/5,440, gpt-5.5) | yes |
| vn desc range | 1,100–1,900; bctt ~1,900 longest | 946–1,442; bctt = 472 (shortest) | **NO — blocking B2** |
| RULES [48] | RULES.md:132, quoted | byte-exact at line 132 | yes |
| Rules corpus | 734 / 51,409 (arc) | 736 / 51,717 now (+2/+308 post-measurement) | yes w/ drift note |
| orca registrations | ×12 | 12 commands / 12 distinct events | yes |
| orca path shape | root-absolute, dead | `${HOME-}`-relative, guarded, script exists+exec | **NO — blocking B1** |
| claude-hook.sh | 3.6K executable | 3,667 B, rwxr-xr-x | yes |
| SUPERSET | ×8, 8 events, dormant no-ops | 8 commands / 8 events; guard true-no-op when unset | yes |
| SUPERSET_HOME_DIR setters | none found | zshenv/zshrc/harness-env.sh/LaunchAgents grep empty | yes |
| codex AGENTS.md | symlink → ~/.claude/CLAUDE.md | readlink exact | yes |
| Workbench twins | byte-identical copies | cmp IDENTICAL, both regular files | yes |
| §7.1 withdrawal record | owner-confirmed no-change, distinct roles, exact-name dispatch, toml twins | lane map:14 + roadmap item 5 + goal-execution.md:300-302 + codex tomls | yes |
| §7 "items 1–4, 7 executed" | roadmap items 1–4, 7 done | audit roadmap lines 45-53: 1,2,3,4,7 DONE | yes |

## Verdict rationale
The user's bar: every factual claim traces to source; any overstatement is blocking. B1 and B2 are false alarms of exactly the class §7 logs — B2 even resurrects a number the same arc had already withdrawn. B3 is a false count inside the recommended work order. R1, R4, R6, §7 and the SUPERSET half of R5 survive full-source checks; the report's NO CHANGE (R1) and RETIRE-conditional (R5 SUPERSET) recommendations stand; R5's orca FIX and R3's start-with-bctt must be discarded and re-derived.

Status: DONE
