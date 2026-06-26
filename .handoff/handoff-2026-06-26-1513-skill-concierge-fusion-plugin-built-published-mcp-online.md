# Session Handoff — skill-concierge: fusion plugin built, published, MCP brought online

## Where it started
Session opened with a context briefing (fresh session), then deep analysis of the operator's existing skill-search MCP deployment + the skill-first-nudge UserPromptSubmit hook. Conclusion: the two are **orthogonal** — skill-search = WHICH skill (semantic retrieval), skill-first = WHETHER Claude uses any skill (anti-dodge enforcement) — not competitors. That fusion idea graduated into a new Claude Code plugin, **skill-concierge**, which was scaffolded, given a telemetry ledger, had the skill-search engine vendored into it, was published to public GitHub, installed, and debugged to a working MCP.

## Decisions locked + what shipped
- **Orthogonality + fusion thesis.** skill-search (retrieve/WHICH) vs skill-first (enforce/WHETHER); fuse so the enforcer sources candidates from the semantic index and the lexical scorer is retired. Captured in memory `skill-first-vs-skill-search-purpose`.
- **Always-on curation is deliberate.** 31 keep-on = 20 core `ck:*` routing + 6 `vn-*` + `skill-search` + 4 guardrails. Tier-1 promotions (`come-clean`, `verify-as-claimed`) were applied by a separate agent. Memory `ck-routing-skills-always-on`.
- **Plugin scaffolded** at `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge` (mandatory stops done: plugin-scaffold + working-with-claude-code; ENFORCED component-building doc Rule A local-first / Rule B docs).
- **Ledger slice (telemetry, P1 step 0)** — `hooks/scripts/ledger.py` (UserPromptSubmit `turn`/`manual` + PostToolUse `auto`/`search`, fail-silent, stdlib) + `scripts/analyze.py` (uptake/dodge/hit@k + per-skill rollups). code-reviewer + tester (13/13); fixes applied: H1 manual real-skill-vs-builtin split via live catalogue, H2 empty-skip + denominator caveat. HELD local (hooks ship in the plugin's `hooks/hooks.json`, so now active via the installed plugin — verify).
- **Vendored skill-search engine** (MIT, Sowhan Mohammed) → `vendor/skill-search/` + `VENDORED.md` attribution + customization log. Router skill → `skills/skill-search/SKILL.md`. Ops docs → `docs/`.
- **Reproduction layer** — `.mcp.json` (points at the launcher), `setup.sh` (stable venv, Qdrant, `--reindex`, apply-overrides), `scripts/apply-overrides.py` (atomic settings.json write, NOT upstream skill-search-overrides; backs up; refuses empty/invalid keep-on), `config/keep-on.json` (32-skill keep-on snapshot incl. the namespaced router). code-reviewer caught a blocker (B1 non-atomic write) + should-fixes; all applied + re-verified.
- **Published** → https://github.com/thinhkhuat/skill-concierge (public). Versions: 0.1.0 (initial) → 0.1.1 (MCP launcher fix) → 0.1.2 (router keep-on). HEAD `d1b9a74`, in sync with origin/main.
- **MCP fix.** ENOENT cause: `.mcp.json` pointed at `${CLAUDE_PLUGIN_ROOT}/vendor/.venv` — a wipe-on-reinstall cache path that was never built. Fix: `bin/skill-search-mcp` launcher execs a STABLE venv at `~/.local/share/skill-concierge/venv` (non-editable engine install, survives reinstalls). The first-on-PATH `~/.local/bin/python3.12` has a broken `ensurepip`; built the venv with `/opt/homebrew/bin/python3.12` instead. Engine healthy (509 indexed, dim 768). Router `skill-concierge:skill-search` set `on` (32 on / 477 name-only).

## Key files for next session

| File | Why |
|------|-----|
| `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/docs/plan.md` | READ FIRST — the fusion plan + full Build log (every slice, decisions, the deferred fusion phases). Serves as the technical journal. |
| `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/.mcp.json` | MCP registration → `bin/skill-search-mcp` launcher + env (Qdrant URL, fastembed mpnet). |
| `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/bin/skill-search-mcp` | Launcher; execs the stable venv. The piece that fixed ENOENT. |
| `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/setup.sh` | Reproduction bootstrap: stable venv + Qdrant + index + overrides. |
| `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/scripts/apply-overrides.py` | Atomic, settings-safe keep-on applier. MUST run with Python 3.10+ (uses venv python; system 3.9 breaks on `dict | None`). |
| `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/config/keep-on.json` | 32-skill keep-on policy (incl. `skill-concierge:skill-search`). |
| `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/hooks/scripts/ledger.py` + `scripts/analyze.py` | Invocation ledger + analyzer. |
| `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/vendor/skill-search/` | Vendored engine (MIT) + `VENDORED.md`. |
| `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/plans/reports/{code-review,test}-260626-{ledger,reproduction}-slice.md` | Review/test reports for the two slices. |
| `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/docs/skill-search-deployment-readme.md` | The original system-wide deployment ops doc (vendored from skills-dev). |

- Memory touched: `/Users/thinhkhuat/.claude/projects/-Users-thinhkhuat-in-PROD-MY-WORKBENCH/memory/skill-first-vs-skill-search-purpose.md`, `.../ck-routing-skills-always-on.md`, + `MEMORY.md` index. No agentmemory `lsn_` lessons written.

## Running state
- Background processes: none (code-reviewer + tester subagents completed; none live).
- Dev servers / ports: **Qdrant** container `skill-search-qdrant` on `localhost:6333` (+6334), `--restart unless-stopped`. Stop: `docker stop skill-search-qdrant`.
- Stable venv (engine): `/Users/thinhkhuat/.local/share/skill-concierge/venv` (skill-search installed, healthy).
- Git: `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge` — `main` → `origin/main` at `d1b9a74`, in sync. Installed plugin cache is still **0.1.1** (settings applied from source; update to 0.1.2 to sync the cached keep-on).
- Removed earlier by the operator: user-scope `skill-search` MCP in `~/.claude.json` (so the plugin's `.mcp.json` is the single source). pipx `skill-search-mcp` still installed (now redundant).

## Verification — how to confirm things still work
- MCP: `/reload-plugins` (or restart Claude Code) → `/mcp` shows `skill-concierge:skill-search` connected (was `-32000` before the venv existed).
- Engine: `SKILL_QDRANT_URL=http://localhost:6333 SKILL_EMBED_BACKEND=fastembed SKILL_EMBED_MODEL="sentence-transformers/paraphrase-multilingual-mpnet-base-v2" /Users/thinhkhuat/.local/share/skill-concierge/venv/bin/skill-search --health` → status ok, indexed 509.
- Overrides: `python3 -c "import json,os;from collections import Counter;print(Counter(json.load(open(os.path.expanduser('~/.claude/settings.json')))['skillOverrides'].values()))"` → `{name-only:477, on:32}`; `skill-concierge:skill-search` == `on`.
- Repo sync: `git -C /Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge rev-parse HEAD origin/main` → both `d1b9a74`.
- Qdrant: `docker ps --filter name=skill-search-qdrant` → Up.

## Deferred + open questions
- Deferred **#2 — setup.sh Python-picker hardening**: it picks the first `python3.12` (the broken-ensurepip `~/.local/bin` one); should test `venv`+pip per candidate and fall through. Operator's machine works (venv built with brew python), so this is portability-only for fresh installs.
- Deferred **THE FUSION ITSELF** (the project's core remaining work, plan.md P1): warm fastembed-mpnet embed shim + hook rewrite so skill-first sources candidates from the semantic index (retire the lexical scorer) + the hard ~120ms timeout→mandate-only fallback. NOT started.
- Deferred — **classifier (P2)**: hard skill-worthiness gate; build only if the ledger's dodge-rate shows soft enforcement leaks.
- Deferred — **recall@k eval**: `vendor/skill-search/eval/labeled_queries.jsonl` (28 queries) vendored but not run.
- Open — **cache 0.1.1 vs source 0.1.2**: update the installed plugin to 0.1.2 so the cached `keep-on.json` matches; otherwise a future cache `setup.sh` re-run would revert the router to name-only.
- Open — **guard friction**: skill-concierge is now agent-write-locked (workbench artifact hook blocks the Write tool; `~/.claude/.ckignore` `build` pattern blocks Bash heredocs containing "build"). `!venv` was added to .ckignore this session. Further in-repo edits need either a re-root + a writable channel or the operator applies patches. This handoff was saved to the workbench `.handoff/` for that reason.
- Open — **ledger live?**: the ledger hooks ship in the plugin's `hooks/hooks.json`, so enabling the plugin may have registered them. Verify whether the ledger is logging to `~/.claude/skill-telemetry/logs/` (it was designed/held but the plugin install may have activated it).

## Pick up here
Reload/restart and confirm `/mcp` shows `skill-concierge:skill-search` connected and the router is `on`; then the major next body of work is the fusion phase (warm embed shim + hook rewrite per `skill-concierge/docs/plan.md` P1).
