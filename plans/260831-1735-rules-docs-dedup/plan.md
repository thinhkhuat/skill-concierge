# Plan: dedupe `docs/` ↔ `rules/` divergent rule copies (roadmap item 1)

**STATUS: EXECUTED 2026-08-31 ~17:45 — D1 (archive-and-remove) applied as safe-partial-path under AFK (Constitution §4): D1 question timed out after 300s; action is fully reversible. Judgement call logged per RULES [2].**

Executed: 4 stale docs/ files → `~/.claude/_Archived/rules-docs-dupes-260831/` (+ `rules-CLAUDE.md.bak-260831`); `rules/CLAUDE.md` On-Demand References repointed to the auto-loaded rules/ copies, archive notes kept out of the index. Verified: `inject-ondemand-docs-index.cjs` now emits only the 3 legitimate docs; zero residual references outside `_Archived/`. Revert: `mv` the 4 files back to `docs/` + restore the `.bak` over `rules/CLAUDE.md`.

Origin: harness instruction-prose audit 2026-08-31 (`plans/reports/audit-260831-0339-harness-instruction-prose.md`), findings C3/C10, matrix pairs 3–6. Governing-artifact change → draft → approve → promote (RULES [4]). No execution before explicit approval.

## Evidence

| File | docs/ (stale) | rules/ (current) | docs/ mtime | rules/ mtime |
|---|---|---|---|---|
| documentation-management.md | 72 ln, no sections | 28 ln, 2 sections | 2026-06-05 | 2026-08-26 |
| orchestration-protocol.md | 116 ln, incl. "Agent Teams (Optional)" | 49 ln, incl. "Model Escalation" | 2026-06-05 | 2026-08-26 |
| skill-domain-routing.md | 159 ln, 12 per-domain sections | 42 ln, capability-map table | 2026-06-05 | 2026-08-26 |
| skill-workflow-routing.md | 73 ln, incl. "PR Review Workflow" | 53 ln, "Shared-Workspace Setup" | 2026-06-05 | 2026-08-26 |

- Lineage: docs/ copies ≈ `_Archived/rules.260612.bak/` bodies + `load-when` frontmatter (only ~196 byte diffs each) — pre-reorg long versions adapted as on-demand docs, then orphaned by the Aug-26 condensed rewrites of `rules/`.
- Consumers of the stale copies: only `rules/CLAUDE.md` (On-Demand References section) + the dynamic hook. `hooks/inject-ondemand-docs-index.cjs` globs `~/.claude/docs/*.md` at SessionStart/SubagentStart and builds the injected index from each file's own `load-when` frontmatter — removing the files self-heals the index.
- Consumers of the current copies: `metadata.json`, `.agentkit/.../native-skill-paths.json` + hashes (machine-read, untouched by this plan).
- Unique-content check: nothing load-bearing unique in the stale copies. Differences are the deliberate redesign (per-domain sections → capability table; team rules → `docs/team-coordination-rules.md`, untouched; Model Escalation added). Minor stale-only sections (Agent Teams inline detail, PR Review Workflow, per-domain prose) — preserved by archiving, recoverable on demand.

## Decision needed (D1)

**Recommended — archive-and-remove:** move the 4 stale files to `~/.claude/_Archived/rules-docs-dupes-260831/`, edit `rules/CLAUDE.md` index. One authority per name; the stale copies were authored for a structure that no longer exists.
Alternative — rename-as-deep-versions: rename to e.g. `orchestration-protocol-deep.md` and keep as on-demand full docs. Rejected as default: their June-era content contradicts the Aug-26 rules in places (delegation paths, routing procedure) — keeping both re-creates the drift this fix removes. If deep on-demand versions are wanted later, regenerate them FROM the current rules/ sources.

## Phases (after approval)

1. **Archive**: `mkdir -p ~/.claude/_Archived/rules-docs-dupes-260831/` + `mv` the 4 files. (His established archive pattern; reversible by mv back.)
2. **Index fix**: edit `~/.claude/rules/CLAUDE.md` — On-Demand References keeps the 3 non-duplicated docs/ entries (claude-code-component-building, multi-step-skill-discipline, team-coordination-rules); drop the 4 stale entries; the "Subagents or teams" bullet already points at `docs/team-coordination-rules.md` (stays). Also fix the same file's "Core Rules" claim friction: the "Shared blocks (single source of truth)" note stays accurate after removal.
3. **Verify**:
   - `node ~/.claude/hooks/inject-ondemand-docs-index.cjs </dev/null` → injected index no longer lists the 4 files.
   - `grep -rn "docs/orchestration-protocol\|docs/skill-domain-routing\|docs/skill-workflow-routing\|docs/documentation-management" ~/.claude --include="*.md" --include="*.cjs"` → only `_Archived/` hits.
   - Fresh session smoke: the auto-loaded `rules/*.md` set unchanged (files untouched).
4. **Record**: note the removal in the audit synthesis's roadmap (mark item 1 done) + one-line memory update.

## Rollback

`mv` the 4 files back + revert the `rules/CLAUDE.md` edit (git? `~/.claude` is not a git repo — the archive dir itself is the rollback; keep a `.bak` of `rules/CLAUDE.md` beside it: `rules/CLAUDE.md.bak-260831`).

## Out of scope (other roadmap items)

dev-rules-reminder.cjs prose (item 2), token-economy reconciliation (item 3), tool-layer migrations (item 4), lane consolidation (item 5), outcome blocks (item 6), hygiene batch (item 7).

## Unresolved questions

- D1 choice (recommend archive-and-remove).
- None blocking beyond D1.
