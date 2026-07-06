# Name-only coverage audit — MISSED skills (still injecting full descriptions)

**Author:** skill-audit-dev (teammate)
**Date:** 2026-07-06 19:36 (Asia/Saigon)
**Mode:** READ-ONLY — no overrides applied, `~/.claude/settings.json` untouched.
**Repo/cwd:** `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge`

## Bottom line

The `skillOverrides` map in `~/.claude/settings.json` is a **stale snapshot** from the
last `apply-overrides.py` run. Since that run the skill inventory drifted:

- **42 skills discovered but never written** → no override → still injecting their full
  description on **every turn** (the leak this audit was after).
- **11 stale entries** point at skills that no longer exist (harmless, but confirms drift).

Not a discovery-path gap and not a namespacing bug — the misses are correctly discovered
and correctly namespaced. Pure **temporal drift**: new plugins/skills arrived after the last
write. **Fix = re-run `scripts/apply-overrides.py`** (setup's `[4/4]` step). One command.

## Counts (every number grounded — see "How measured")

| Metric | Count | Source of truth |
|---|---|---|
| Skills discovered (SKILL.md, 3 sources, deduped) | **533** | repo `discover_skills()` — personal 271 / plugin 258 / project 4 |
| Override entries in `settings.json` (`skillOverrides`) | **502** | direct read: **32 `on`** + **470 `name-only`** |
| Discovered **correctly name-only'd** | **459** | 470 name-only − 11 stale = 459 |
| Discovered **kept-on** (always-on) | **32** | == keep-on list; all present, all mapped `on` |
| **MISSED** (discovered · no override entry · not keep-on) | **42** | 533 − 459 − 32 = 42 |
| `on` but NOT in keep-on (rogue full-desc) | **0** | clean |
| keep-on entries dark / not-`on` | **0** | all 32 correctly `on` |
| Stale entries (override present, skill not discovered) | **11** | listed below |
| Built-ins wrongly counted as misses | **0** | structural — see note |

Cross-check: `502 = 32 on + 470 name-only` matches doctor's "Settings overrides 32 on /
470 name-only" exactly. Engine-installed `discover_skills` (deployed venv) also returns
**533** → repo-vendored and deployed discovery are in parity.

## 1. Always-on list (keep-on / excluded from the miss-check)

`config/keep-on.json` → **32 entries**, all present on this machine, all mapped to `on`:

```
Verification Before Completion, come-clean, requirements-clarity,
skill-concierge:skill-search, skill-search, verify-as-claimed,
vn-author, vn-bctt-report, vn-canu-reporting, vn-comm, vn-deep-dive-report, vn-editor,
ck:ask, ck:brainstorm, ck:code-review, ck:context-engineering, ck:cook, ck:debug,
ck:fix, ck:git, ck:loop, ck:plan, ck:predict, ck:problem-solving,
ck:project-management, ck:research, ck:scenario, ck:scout, ck:sequential-thinking,
ck:ship, ck:team, ck:test
```

`keep_on_absent_on_machine = 0` — nothing in the allowlist is missing.

## 2. The 42 MISSED skills (by source, with why-missed)

Every entry below has a real `SKILL.md` on disk and no key in `skillOverrides`. Grouped by
the cluster that explains the miss.

### Plugin — superpowers marketplace family (32) — the team's study target, freshly installed
These post-date the last `apply-overrides.py` run (the whole reason this team exists is to
"study superpowers' novelty" — the plugins were just added).

- **`superpowers:*`** (v6.1.1, 14): brainstorming, dispatching-parallel-agents, executing-plans,
  finishing-a-development-branch, receiving-code-review, requesting-code-review,
  subagent-driven-development, systematic-debugging, test-driven-development,
  using-git-worktrees, using-superpowers, verification-before-completion, writing-plans, writing-skills
- **`superpowers-dev:*`** (v6.1.1, 14): same 14 skill names, `-dev` plugin variant
- **`superpowers-lab:*`** (v0.5.0, 4): finding-duplicate-functions, mcp-cli,
  using-tmux-for-interactive-commands, windows-vm

### Plugin — other recently-installed plugins (5)
- **`cognee-memory:*`** (v0.2.0, 3): cognee-remember, cognee-search, cognee-sync
- **`episodic-memory:remembering-conversations`** (superpowers-marketplace, v1.4.2)
- **`watch:watch`** (claude-video, v0.2.0)

### Project-scoped — this repo's own `.claude/skills/` (4)
Added to `skill-concierge/.claude/skills/` after the last write (or the last write ran from a
different cwd, so project-scope was never in that discovered set):
- `aionui-config`, `claude-code`, `native-mcp`, `skill-creator`

### Personal — `~/.claude/skills/` (1)
- `keep-a-changelog` — a personal skill added after the last write.

**By source:** plugin 37 · project 4 · personal 1 = **42**.

## 3. Built-ins are NOT in this set (ADR-0001, by construction)

`discover_skills()` walks only `SKILL.md` files (`~/.claude/skills/*/SKILL.md`,
`$CWD/.claude/skills/*/SKILL.md`, `~/.claude/plugins/cache/**/skills/*/SKILL.md`). Built-in
slash-commands (`/model`, `/review`, `/init`, `/commit`, `/security-review`, `/loop`,
`/schedule`, `/verify`, `/run`, `/code-review`, `/simplify`, `/checkpoint`, …) carry no
`SKILL.md`, so they never enter the discovered set — and therefore **cannot** appear in the
42-miss set. Each of the 42 was verified to resolve to a `SKILL.md` path. Built-in
contamination of the miss count = **0**.

## 4. The 11 stale override entries (drift evidence, not a leak)

Present in `skillOverrides` but no longer discovered — former skills, renamed/removed since
the last write. Harmless (an override for a skill that doesn't exist does nothing), but they
prove the map has not been reconciled:

```
Hook Development, Systematic Debugging, agent-harness-construction, check,
cicd-pipeline-generator, codex, completion-check, design-then-build,
gateguard, ocr-and-documents, skill-comply           (all => name-only)
```

## 5. Root cause

**Single cause: `skillOverrides` is a point-in-time snapshot never re-reconciled after the
inventory changed.**

- `apply-overrides.py` writes the map once, per run, from whatever `discover_skills()` returns
  at that moment. It has no watcher and no incremental reconcile — a skill added after the run
  gets no entry until the next run.
- Since the last run: **+42** skills (superpowers family 32, cognee 3, episodic 1, watch 1,
  4 project, 1 personal) arrived; **−11** skills left. Nothing re-ran the applier, so the 42
  new skills default to full-description injection and the 11 departed skills linger as dead keys.

**Ruled out:**
- *Discovery-path gap* — no. All three sources enumerated correctly (personal/project/plugin);
  the misses come from every source, including correctly-globbed plugin-cache paths.
- *Namespacing mismatch* — no. Misses carry correct namespaced ids (`superpowers:x`,
  `cognee-memory:x`, `watch:watch`), matching how Claude Code overrides them.
- *Doctor bug* — no. Doctor faithfully reports what's *in* `skillOverrides` (32/470); it just
  **doesn't diff discovered-vs-written**, so a discovered-but-unwritten skill is invisible to it.

## 6. Recommendations (report-only — not acting per READ-ONLY mandate)

1. **Re-run `python scripts/apply-overrides.py`** (or invoke the `skill-concierge:setup`
   skill) — writes all 533 into `skillOverrides`, name-only'ing the 42 leaks and dropping the
   11 stale keys. Idempotent; backs up settings.json first.
2. **Doctor gap:** add a discovered-vs-override diff to `doctor.py` so misses + stale entries
   surface as a check, instead of only echoing the current map's on/name-only split. This is
   what would have caught the 42-skill leak automatically.

## How measured (grounding)

- `config/keep-on.json` — read (32 keep-on entries).
- `~/.claude/settings.json` `skillOverrides` — read (502 entries: 32 on / 470 name-only).
- Discovery = repo's own engine, read-only:
  `python vendor/skill-search/skill_search/skills_discovery.py::discover_skills()`, cwd = repo
  root → 533 skills. Cross-checked against the **deployed** engine venv
  (`~/.local/share/skill-concierge/venv`) → also 533 (parity).
- Reconciliation done in-memory; **no writes**. `apply-overrides.py` was **not** executed;
  `generate_overrides.py` was read for mechanism only.

## Unresolved / caveats

- The project-scope 4 depend on cwd. This audit used cwd = repo root (matching setup.sh's
  invocation and the task ENV). If the last real `apply-overrides` ran from a different cwd,
  the 4 project skills may have been unreachable then rather than added later — either way the
  fix (re-run from repo root) is the same.
- Exact timestamp of the last `apply-overrides` run not established (would need the
  `settings.json.bak-skillconcierge-*` backups' mtimes); not required to conclude drift, since
  the +42/−11 delta is self-evident from the discovered-vs-written diff.
