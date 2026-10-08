# B dispositions: hooks/ (minus enforcer.py), bin/ (minus embed-shim), skills/

Agent B, 2026-10-09 (Asia/Saigon). Worktree `/Users/thinhkhuat/.worktrees/skill-concierge/chisle-cuts`, no git operations.

## Findings

- hooks/scripts/doctrine.py:174 — SKIPPED: unifying harness detection into one module is decided out (it changes ledger rows; owner follow-up). The concrete missing cases are FIXED in place: doctrine now recognises `SKILL_CONCIERGE_HARNESS=opencode|open-code` and the `.opencode` and `.cline` path markers (the enforcer already knew all of these). Under OpenCode it now names OpenCode's search tool `skill-search_search_skills` (ADR-0085 §7, ledger SEARCH_TOOLS) for both the tool and the slash hint, with the duplicate `or:` bullet dropped. Before this fix the OpenCode adapter ran doctrine.py with SKILL_CONCIERGE_HARNESS=opencode and got Claude Code's `mcp__plugin_skill-concierge_…` tool name and its `/skill-concierge:skill-search` slash form, and OpenCode exposes neither. Tests: tests/test_opencode_adapter.py::test_doctrine_names_opencodes_search_tool (3 cases; all 3 fail on HEAD, pass now) and tests/test_cline_plugin.py::test_real_doctrine_renders_for_cline (new `.cline` marker case; it fails on HEAD and passes now).
- hooks/scripts/auto_reindex.py:39 — FIXED: new sibling `hooks/scripts/selfheal.py` holds `recent`, `mcp_env(root)`, `qdrant_up` and `flywheel_locked(root)`. auto_reindex, auto_overrides and auto_flywheel import `_recent` and `_qdrant_up` by name. `_mcp_env()` and `_flywheel_locked()` stay zero-argument module wrappers that pass the module's own import-time PLUGIN_ROOT, so the existing monkeypatches (`af._mcp_env`, `af._qdrant_up`, `af._flywheel_locked`, `ar._mcp_env`, `mod._qdrant_up`) still take effect. auto_promote keeps its own `_recent`: it catches `OSError` where the other three catch `FileNotFoundError`, so sharing one function would change its behaviour. The redundant `status = None` is gone with the duplicate.
- skills/skill-usage-audit/SKILL.md:41 — SKIPPED: medium confidence, and restructuring a 71-line paragraph is not one of the medium classes the policy permits.
- hooks/scripts/doctrine.py:226 — SKIPPED for the dict-and-loop refactor (medium confidence, not a permitted class). The dead part is FIXED: `if harness in ("commandcode", "cmd", "command-code")` became `if harness == "commandcode"`, because lines 177-178 already normalise those aliases. doctrine `--selftest` still pins `cmd`.
- bin/embed-shim:1 — SKIPPED: another agent owns this file (it is being archived).
- hooks/scripts/auto_reindex.py:2 — SKIPPED: low confidence.
- hooks/scripts/ledger.py:151 — FIXED: one `_log(ev, sub, harness)` helper replaces the five repeated tails. The `turn` branch passes `sub=False`, which keeps its rows free of `sub`. I fed 11 payloads covering every branch to HEAD's ledger.py and to the new one: the rows are byte-identical apart from `t`.
- hooks/scripts/doctrine.py:414 — FIXED: removed the unused `import types as _types`, the no-op `try/finally: pass`, and both dead `harness = "zcode"` assignments that sat right before a `return`.
- skills/catalogs/SKILL.md:15 — FIXED: (a) the external annex is described as ON by default with the `ENFORCER_EXTERNAL_ANNEX=0` revert (checked against enforcer.py:104-106); (b) flywheel coverage of catalogs is stated, citing ADR-0043 (checked against auto_flywheel `_catalog_aliases` and `flywheel.py --catalog`); (c) the machine-specific path line is dropped.
- hooks/scripts/skill_exclusions.py:37 — FIXED: ledger.py gains `from __future__ import annotations` and now imports on /usr/bin/python3 3.9.6. Before: `TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'`. After: `ledger OK`. The drifted fallback copies are gone. When the sibling is missing, the import now falls back to empty tuples, so the hook matches no load and stays silent rather than keeping a second copy. Every caller runs `python3` from PATH (hooks.json plus the OMP, Command Code, DSH, OpenCode and Cline adapters), and that can resolve to 3.9. Test: tests/test_skill_exclusions.py::test_every_interpreter_reads_ledgers_load_shapes. Its two /usr/bin/python3 cases (`skill-search_get_skill`, and the Skill tool with key `id`) fail on HEAD and pass now.
- hooks/hooks.json:2 — SKIPPED: medium confidence. The description restates prose, not code, so it is not a permitted class, and "the two named gates" (skill_guard plus the openwiki guard, both named in the text) is not clearly contradicted.
- hooks/scripts/ledger.py:4 — FIXED for part (a) only: the docstring now gives the real PostToolUse matcher, the `get_skill` event, the adapter activation lanes and the `ConciergeOffer` event. Part (b) is SKIPPED because the finding is marked (check) and not approved: the `input_keys` write and the sentence explaining it are unchanged.
- hooks/doctrine/skill-first.md:14 — SKIPPED: low confidence.
- skills/consult/agents/analyst.md:52 — SKIPPED: marked (check) and not approved.
- hooks/scripts/skill_names.py:20 — FIXED: dropped the never-varied `registry`/`skills_root` parameters and the `aliases` parameter. A search confirmed that the only callers (ledger.py `canonical(name)` and auto_promote.py `plugin_bare_aliases()`) pass no extra arguments. Both selftests rebind the module globals, and they still pass.
- skills/skill-usage-audit/scripts/audit_skill_usage.py:4 — FIXED: "three signals" is now "four signals". The `_is_authorized_skip_line` docstring now says the count side and the harvest side (`_looks_authorized`) share `_AUTHORIZED_SIGNATURES`, and its duplicate sync sentence is gone (the sync note stays once, above `_AUTHORIZED_SIGNATURES`).
- skills/keep-on/SKILL.md:61 — SKIPPED: medium confidence, and prose duplicating other prose is not a permitted class.
- skills/skill-search/SKILL.md:24 — SKIPPED: low confidence (vendored upstream text).
- skills/skill-usage-audit/SKILL.md:5 — FIXED: the `argument-hint` lost `[--until <when>]`, because argparse defines only --since, --meta-keyword, --selftest, --continuations and --harvest.
- skills/setup/SKILL.md:34 — FIXED: "from BOTH Claude Code and Codex directories, ADR-0033" now reads "from every supported harness's skill roots".
- skills/flywheel/SKILL.md:92 — FIXED: the link now points to `../../references/flywheel-llm-providers.md` (the file lives at the repo root and skills/flywheel/ has no references/).
- skills/doctor/SKILL.md:71 — SKIPPED: low confidence. I did verify the statement is stale: "the container" contradicts its own line 36 (ADR-0070), so this is an owner follow-up.

## Python 3.9 scope extension (coordinator)

The check was `env -i HOME=$HOME PATH=/usr/bin:/bin /usr/bin/python3 -c "import sys; sys.path.insert(0,'hooks/scripts'); import <m>"` (Python 3.9.6).
- Before: `ledger` failed with `TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'`. doctrine, skill_guard, skill_exclusions, skill_names, auto_promote, auto_reindex, auto_overrides and auto_flywheel printed OK.
- After: all ten print OK: ledger, doctrine, skill_guard, skill_exclusions, skill_names, selfheal, auto_promote, auto_reindex, auto_overrides, auto_flywheel.
- Runtime under 3.9:
  - `ledger.py --selftest`, `doctrine.py --selftest`, `auto_promote.py --selftest` and `audit_skill_usage.py --selftest` all report OK.
  - doctrine with `SKILL_CONCIERGE_HARNESS=opencode` emits the context JSON.
  - skill_guard exits 0.
  - auto_reindex, auto_overrides and auto_flywheel each exit 0.
  - `selfheal.mcp_env`, `qdrant_up`, `flywheel_locked` and `recent`, plus the hooks' wrappers, return the same values on 3.9 and 3.12.
- A grep for 3.10+ runtime constructs (zip strict, `isinstance` with `|`, match/case, tomllib, datetime.UTC, pairwise, slots/kw_only, except*) found none in these files. The one `fromisoformat` call (audit_skill_usage.py:420) already turns `Z` into `+00:00`.
- bin/: skill-search-mcp is bash, so there is nothing to check.

## Verification

- `python3 hooks/scripts/enforcer.py --selftest` → `enforcer --selftest OK: refusal guard (5 fire / 6 silent) + ranked-mandate %-share + … + CJK word-count (pre-gate no longer swallows no-space scripts)`
- `python3 -m pytest -q -p no:cacheprovider tests/test_skill_exclusions.py tests/test_opencode_adapter.py tests/test_cline_plugin.py tests/test_auto_flywheel.py tests/test_engine_env.py tests/test_trigger_filter.py tests/test_synced_skills.py tests/test_reputation_badges.py tests/test_doctrine_text.py tests/test_doctrine_jevd_check.py tests/test_adapter_exclusion_echo.py tests/test_builtin_selftests.py tests/test_python39_hooks.py tests/test_harness_regex_parity.py tests/test_chain_hint_e2e.py tests/test_ruling_parsers.py tests/test_blocklist.py` → `258 passed in 166.28s (0:02:46)`
- `python3 scripts/driftcheck.py driftcheck.json` → `IN SYNC: every fact matches its source of truth.` (rc=0)
- Full suite `python3 -m pytest -q -p no:cacheprovider tests/` → `2 failed, 1114 passed in 326.12s (0:05:26)`. Both failures are in other agents' files: test_port_env_guard reads the archived `bin/embed-shim` (FileNotFoundError), and test_sibling_installers::test_readme_054_1_line… fails with `ValueError: substring not found` on the edited README.md.
- One transient run of auto_flywheel + engine_env + trigger_filter + synced_skills showed 27 setup errors. Three reruns in a row passed 45/45, and the same set passed on a pristine `git archive HEAD` export. I did not capture the error text; the likeliest cause is a concurrent edit by another agent in the shared worktree. Inference, unproven.

## For the main session

- New file `hooks/scripts/selfheal.py`. docs/repository-layout.md, AGENTS.md and openwiki do not mention it, and those files are outside my scope. Add a line if the layout docs should list it.
