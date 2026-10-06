# Gates: Command Code SystemOne endpoint as bench tier 1 (whole 5 s), TypeSafe fallback, Jev budget 3 s -> 7.3 s

OWNS: hooks/scripts/enforcer.py, tests/conftest.py, scripts/calibrate_jev_gate.py, docs/epoch-watch.md, openwiki/operations.md, scripts/jev_client.py, tests/test_jev_relay_timeout.py, tests/test_jev_client.py, README.md, hooks/hooks.json, adapters/commandcode/skill-concierge.mod.ts, adapters/dsh/skill-concierge.dsh.ts, tests/test_jev_bench.py, tests/test_jev_router.py, docs/adr/0079-*.md, docs/adr/README.md, AGENTS.md, CLAUDE.md, CHANGELOG.md, plans/261006-2034-commandcode-jev-endpoint/**, ~/.config/harness-env.sh

Scope: Thinh's order (2026-10-06): add `https://api.commandcode.ai/provider/v1/systemone` (key `CMD_API_KEY`, model `typesafe/jev`) to harness-env and the Jev bench as the first tier; amended by his decision at ~21:06 ("B - with a 2nd call to come after the entire 5s mark without any response at all or due to error responded from commandcode endpoint. at least for now."): Command Code gets the whole 5 s; TypeSafe is called only on a Command Code error or no answer by 5 s; route budget 7.3 s (after review M1); Claude Code hook kill 10 s.

- [x] G1: the whole test suite passes, including new tests for the `cc` tier, its 5 s span, TypeSafe only after a CC error or a full-span miss, the 7.3 s budget cap, the rerank skip, and the offline span rule; run with the live harness-env loaded (review H1)
  CHECK: zsh -c 'source ~/.config/harness-env.sh >/dev/null 2>&1; ~/.claude/skills/.venv/bin/python3 -m pytest -q tests' && echo ALL-TESTS-GREEN
  EXPECT: ALL-TESTS-GREEN
  EVIDENCE: automatic-evidence=v1; definition-sha256=4b0463545247fa40a032a854a98a34763067f2f3beaf520e3237e3dc2fe0a047; exit=0; EXPECT=matched; output-sha256=aff8939c8dc3c1b8bc2d376f2c9777280f500bacc4ff04fffd9d89fac3b8d715; output-bytes=1168; shell=/bin/sh; cwd=/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge; path=fd6e06ddc85b/81 entries

- [x] G2: real calls answer: the `cc` tier alone through jev_client, a full router turn on the live bench, and a forced Command Code timeout that the same turn finishes on TypeSafe
  CHECK: zsh -c 'source ~/.config/harness-env.sh >/dev/null 2>&1; ~/.claude/skills/.venv/bin/python3 -I plans/261006-2034-commandcode-jev-endpoint/verify_live.py'
  EXPECT: CC-LIVE-VERIFIED
  EVIDENCE: automatic-evidence=v1; definition-sha256=851e130becf3751871ec7f5434bb8f51c19a7fd79d10accacf3df0ea5bd91e37; exit=0; EXPECT=matched; output-sha256=39fd3838d27e24c2f2bdf99110341a2ad86a9b210c4b0bce9bc45df10edc1058; output-bytes=263; shell=/bin/sh; cwd=/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge; path=fd6e06ddc85b/81 entries

- [x] G3: harness-env exports the bench with `cc:typesafe/jev` first and TypeSafe second
  CHECK: zsh -c 'source ~/.config/harness-env.sh >/dev/null 2>&1; set -- ${=ENFORCER_JEV_BENCH}; [[ $1 == cc:typesafe/jev && $2 == ts:jev-1.13.0 ]] && echo BENCH-CC-FIRST'
  EXPECT: BENCH-CC-FIRST
  EVIDENCE: automatic-evidence=v1; definition-sha256=8e51d694b81c3e1edf131c33fae4f0037a1eef841b04a8d105a201fd194bc772; exit=0; EXPECT=matched; output-sha256=7b02ecb526146f769cf37dcea70d1d3040672e951855fa81fc48c53124a3ac35; output-bytes=15; shell=/bin/sh; cwd=/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge; path=fd6e06ddc85b/81 entries

- [x] G4: every harness's enforcer kill window exceeds the Jev budget it runs under (Claude Code hooks.json, Command Code and DSH adapters)
  CHECK: ~/.claude/skills/.venv/bin/python3 -I plans/261006-2034-commandcode-jev-endpoint/verify_windows.py
  EXPECT: KILL-WINDOWS-OK
  EVIDENCE: automatic-evidence=v1; definition-sha256=4638b9610a5d3b99b704c5019df98eb57499ed8bf62fe4950c2e46192b734b30; exit=0; EXPECT=matched; output-sha256=a0dcaf018f668020ec9cb6b33ca0c6cf6b929a78399d741397bcc9ee77185a4e; output-bytes=321; shell=/bin/sh; cwd=/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge; path=fd6e06ddc85b/81 entries

- [x] G5: doc/version drift check passes
  CHECK: python3 scripts/driftcheck.py driftcheck.json && echo DRIFT-OK
  EXPECT: DRIFT-OK
  EVIDENCE: automatic-evidence=v1; definition-sha256=9c68f06651258eec83c77f23723a1e9beef36d578703a21bfbee5d0264ec7342; exit=0; EXPECT=matched; output-sha256=019c8f8d4d763d45378859ef0291cbe69a0fd75b44ab620657da53c970db6fb1; output-bytes=3571; shell=/bin/sh; cwd=/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge; path=fd6e06ddc85b/81 entries

- [x] G6: ADR-0079 exists and is indexed; AGENTS.md, CLAUDE.md and CHANGELOG cite ADR-0079 and name `ENFORCER_JEV_CC_TIMEOUT` (both tokens absent from all four files before this change)
  CHECK: zsh -c 'f=(docs/adr/0079-*.md); [[ -f $f[1] ]] && rg -q "0079" docs/adr/README.md && for d in AGENTS.md CLAUDE.md CHANGELOG.md; do rg -q "ADR-0079|0079-" $d && rg -q ENFORCER_JEV_CC_TIMEOUT $d || exit 1; done && echo DOCS-OK'
  EXPECT: DOCS-OK
  EVIDENCE: automatic-evidence=v1; definition-sha256=a4a32835ae0d0cbf0a3bcb61434cd4d6ffde7b2216120faf64eba22f37193565; exit=0; EXPECT=matched; output-sha256=2f994fac08121c4f08560e6e1210c76191fe546fa80e877c9121af6d10b342db; output-bytes=8; shell=/bin/sh; cwd=/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge; path=fd6e06ddc85b/81 entries

- [x] G7: RULES [72] update drafted for Thinh's approval (draft -> approve -> promote, RULES [4]); RULES.md itself untouched
  EVIDENCE: 2026-10-06 21:33 — draft at plans/261006-2034-commandcode-jev-endpoint/rules-72-draft.md; `rg -c -F` of the current sentence "Sole metered exception: TypeSafe **Jev** ..." in ~/.claude/RULES.md returns 1 (unchanged). Promotion awaits Thinh's approval.

- [x] G8: independent blind review of the diff (RULES [57]) returned and every real finding fixed
  EVIDENCE: 2026-10-06 — code-reviewer (opus) report plans/reports/code-reviewer-261006-2034-commandcode-jev-tier.md. H1 fixed by tests/conftest.py (control: without it 13 failed / 34 passed under the live env; with it 254 Jev tests pass). M1 fixed: budget 7.3 s + JEV_RERANK_MIN_S, two new tests, each shown failing on the reverted behaviour. M2 join fixed; the history-skip fall-through rejected with reason (it would bill a second whole turn), recorded in ADR-0079 item 9. M3 fixed by the offline span rule, recorded as a judgment call awaiting Thinh's confirmation (ADR-0079 item 10). L1 (calibrator User-Agent, cc endpoint) and L2 (docstring, W23) fixed; L3/L4 documented in epoch-watch W23/W38. Full suite under the live env: 974 passed (G1).
