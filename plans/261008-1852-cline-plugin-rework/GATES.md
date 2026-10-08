# Gates: Cline plugin rework (parity with Claude Code)

OWNS: adapters/cline/**, plugin.json, mcp.json, hooks/scripts/doctrine.py, scripts/doctor.py, driftcheck.json, tests/test_cline_*.py, docs/adr/0086-*.md, docs/adr/README.md, docs/repository-layout.md, README.md, CHANGELOG.md, openwiki/**, AGENTS.md, .claude-plugin/*.json, .codex-plugin/plugin.json, package.json, plans/261008-1852-cline-plugin-rework/**

Scope: Rebuild the Cline integration as a native code plugin plus an agent-plugins.org Agent Plugin, so that a live Cline 3.0.69 session gets the SKILL-FIRST rule, the per-turn menu, a refuse-only-this-call blocklist deny, the ledger and the exclusion echo, without losing the conversation or tool output.

- [x] G1: The plugin's hooks behave correctly when driven by Node with runtime-shaped contexts (menu appended without replacing messages, deny returns skip, echo uses appendContext, subagents skipped, the first-call wait ends under 2.3 s).
  CHECK: pytest -q -p no:cacheprovider tests/test_cline_plugin.py && echo CLINE_PLUGIN_TESTS_OK
  EXPECT: CLINE_PLUGIN_TESTS_OK
  EVIDENCE: automatic-evidence=v1; definition-sha256=9a22558dac431bed918610b85c82dcf08366e6d634afde7a85fc8b123da21ab9; exit=0; EXPECT=matched; output-sha256=5a68f4750a9ed6a3ef1fe1f708e1436b7a9ff9a7d89c04405a908254b493bf7e; output-bytes=121; shell=/bin/sh; cwd=/Users/thinhkhuat/.worktrees/skill-concierge/cline-v2; path=3309ce9f93b2/82 entries

- [x] G2: The whole tests/ suite passes on the branch.
  CHECK: pytest -q -p no:cacheprovider tests/ && echo ALL_TESTS_OK
  EXPECT: ALL_TESTS_OK
  EVIDENCE: 2026-10-08 20:53 (+07), final tree after the file-hook fallback removal, committed in a throwaway clone ($TMPDIR/sc-final-95604, so the Codex installer tests see the version bump as committed): "1085 passed in 318.52s", exit=0. 1093 → 1085 because tests/test_cline_bridge_modes.py was deleted with the bridge it tested.

- [ ] G3: The version mirrors, the new adapter files and the docs paths are in sync (driftcheck exits 0).
  CHECK: python3 scripts/driftcheck.py driftcheck.json && echo DRIFT_OK
  EXPECT: DRIFT_OK
  EVIDENCE: pending

- [x] G4: The release is 0.63.0 with ADR-0086, and no Cline file still claims ADR-0085 or 0.62.0.
  CHECK: python3 plans/261008-1852-cline-plugin-rework/check_release.py && echo RELEASE_OK
  EXPECT: RELEASE_OK
  EVIDENCE: automatic-evidence=v1; definition-sha256=11fe418aaad55f26e23a41906cd40f7ab9a5cef62ab1990e97f388b9a310a863; exit=0; EXPECT=matched; output-sha256=83c5b6ac636f274d18bf92e42fca393b45ba140efc6a32b72dbdf8a4dc162cb9; output-bytes=48; shell=/bin/sh; cwd=/Users/thinhkhuat/.worktrees/skill-concierge/cline-v2; path=3309ce9f93b2/82 entries

- [x] G5: In a live Cline session the plugin loads and the model receives both the user's prompt and the skill menu.
  EVIDENCE: live 2026-10-08 13:00Z, Cline 3.0.70, -P openai-codex, CLINE_SESSION_BACKEND_MODE=local, final code: _scratch/live/run-final2.jsonl answer lines 1-2 = the prompt verbatim + 'SKILL-FIRST · reply line 1 = …' (menu on the first call); earlier trace runs showed beforeModel returning the full list (msgs=1 → 2).

- [x] G6: In a live Cline session a blocklisted skill is refused and the turn continues to an answer.
  EVIDENCE: live 12:31Z, _scratch/live/run-g678.jsonl: skills tool call for skill-concierge:keep-on returned the blocklist reason as a tool error; run completed after 4 model calls; trace 'beforeTool … decision=deny'.

- [x] G7: In a live Cline session a get_skill load keeps the full skill body and the exclusion echo arrives as separate hook context.
  EVIDENCE: live 12:33Z, _scratch/live/run-g7c.jsonl: get_skill ak-ak returned '# ak — safe CLI operation' (body intact) and the model quoted the separate 'SKILL-EXCLUDES: …' hook context; ledger row 'get_skill ak-ak harness=cline'.

- [x] G8: In a live Cline session a turn with several tool rounds writes exactly one UserPromptSubmit ledger row for its prompt.
  EVIDENCE: ledger rows for sid conv_1791462679644_eyjxs18 (4 model calls, 3 tool calls): exactly one 'turn' and one 'offer' row; tests/test_cline_plugin.py::test_one_turn_row_per_run_however_many_model_calls.

- [x] G9: The generated Agent Plugin (~/.agents/plugins/skill-concierge: plugin.json + mcp.json + skills/) is discovered by Cline with no skill rejected, and its skill-search MCP server answers.
  EVIDENCE: run-final2.jsonl lines 4-5: 10 skill-concierge:* skills and tool skill-concierge_skill-search__search_skills_4d64eb2e visible; run-g678 search returned 6 results; ~/.cline/data/logs/cline.log has 0 'Skipping invalid Agent Plugin skill' lines after 12:20Z (generated folder installed 12:29Z).

- [x] G10: doctor reports the Cline row without findings after install.
  EVIDENCE: 2026-10-08 20:45 (+07), file-hook fallback removed, CLINE_SESSION_BACKEND_MODE=local exported in ~/.config/harness-env.sh (owner approved 20:40): `env -i HOME=$HOME PATH=… zsh -c 'python3 scripts/doctor.py | grep -i cline'` → "[✓] Cline integration plugin loader + Agent Plugin → this checkout". Fresh zsh and bash -l both print CLINE_SESSION_BACKEND_MODE=local. ~/.cline/hooks holds no shim with the old marker and cline_mcp_settings.json has no skill-search row.

- [x] G11: An independent reviewer finds no unresolved correctness defect in the reworked diff.
  EVIDENCE: three blind reviews. (1) plans/reports/code-reviewer-261008-1852-cline-rework-review.md — no Critical; H1–H3, M1, M6, M7 and the L items fixed (budget 2.0 s, subagent stamp on every lane incl. search, runtime reminders skipped, doctor non-ASCII + hub note), H2 settled by the owner exporting CLINE_SESSION_BACKEND_MODE=local. (2) plans/reports/code-reviewer-261008-2001-cline-fix-verification.md — its recommended actions 1–4, 6, 7 applied; N2 moot (fallback removed); N3 (exact hashed tool name) accepted as Low: the doctrine names the `<suffix>` form. (3) plans/reports/code-reviewer-261008-2040-cline-fallback-removal-review.md — no Critical/High; M1 → CHANGELOG 0.63.0 "Upgrade notes" + doctor names leftovers; M2 → write-discipline scan widened to adapters/*/*.py, proven to bite on a raw write in mcp_row.py; L1 → the MCP-row step runs first so invalid JSON stops the install before any write (test added); L2 → doctor tolerant of odd shapes; L4 → umask 077 for the backup; L5 → two stale comments fixed; L6 → use_skill deny case, second-run and option-refusal tests added. L3 accepted: doctor reads its own env, correct in any shell that sources harness-env.sh. After the fixes: 99 Cline/installer/doctor tests passed (20:58 +07).
