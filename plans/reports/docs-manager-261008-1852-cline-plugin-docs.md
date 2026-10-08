# Docs update for release 0.63.0 (Cline native plugin + Agent Plugin)

Source: docs/adr/0086-cline-native-plugin-and-agent-plugin.md, CHANGELOG.md [0.63.0], adapters/cline/ (file listing, install.sh flags). Nothing committed.

| File | Change | Why |
|---|---|---|
| README.md line 3 | badge 0.62.0 -> 0.63.0 | version |
| README.md ~line 374 | `adapters/cline/` tree comment rewritten (code plugin, agent_plugin.py + agent-plugin/, mcp_row.py, install.sh plugin default / --file-hooks, mcp.json, fallback bridge + hooks/ shims) | was file-hook only; ADR-0086, ADR-0051 |
| README.md ~lines 407-410 | Cline prose: code plugin + generated Agent Plugin, file hooks as fallback | ADR-0086 |
| README.md ~line 424 | Cline harness table row: vehicle and MCP columns | ADR-0086; MCP now comes from the Agent Plugin mcp.json, installer-merged row only in --file-hooks mode |
| README.md ~line 468 | new `0.63.0` latest-release line above `0.62.0`, "committed on branch feat/cline-plugin-v2, not yet merged or pushed" | requested |
| openwiki/quickstart.md line 14 | Version 0.62.0 -> 0.63.0 | no Cline sentence there named file hooks as the vehicle, so nothing else changed |
| openwiki/operations.md ~line 376 | plugin loader takes effect next Cline session; Agent Plugin re-synced at session start, doctor flags drift; CLINE_SESSION_BACKEND_MODE=local and why | ADR-0086 Decision 1-2, Consequences |
| docs/repository-layout.md line 12 | `cline/` entry rewritten | new layout |
| AGENTS.md line 31 | parenthetical for `cline/` | requested; Runtime flags table untouched |
| docs/runtime-flags.md line 8 | ENFORCER_HARNESS_SKIP lists Cline's system prompt; ADR-0086 link added | ADR-0086 Decision 5; ENFORCER_LEDGER untouched |
| docs/caveats.md end | new section 26: 3-second hook limit + preview-first, hub host limit | ADR-0086 Context 4, Consequences |

## Validation
- `python3 scripts/check_flag_docs_parity.py`: flag-docs-parity OK (40 table rows, 38 full entries).
- `python3 scripts/driftcheck.py driftcheck.json`: all path and command checks ok; ONE drift remains (below).

## Open item
driftcheck.json (line 21) reads the README release version with the regex `` `X.Y.Z`[^\n]*\*\*published `` (first match). The requested wording for the 0.63.0 line ("committed on branch ..., not yet merged or pushed") does not contain `**published`, so the check still picks the 0.62.0 line and reports `DRIFT: README.md has ['0.62.0'] but SSOT is '0.63.0'`. I did not edit driftcheck.json or fake the word "published". Options: (a) leave it; the drift clears when the line is changed to "**published" at merge/push time (my pick, since the wording is true today); (b) change the line to "**published" now (false until pushed); (c) loosen the regex in driftcheck.json.
