# Docs update: Cline file-hook fallback removal (v0.63.0, unreleased)

## Files changed
- README.md: adapters/cline tree comment (no fallback bridge, shims, mcp.json or --file-hooks; says mcp_row.py retires the old row and install.sh retires leftovers); Cline row of the harness table (code plugin plus Agent Plugin only, MCP comes from the Agent Plugin's mcp.json); 0.63.0 line (retirement fact replaces "--file-hooks as the fallback", "amends" became "supersedes ADR-0051's file-hook vehicle"). The "not yet committed, merged or pushed" wording is untouched.
- CHANGELOG.md, 0.63.0 entry only: install.sh bullet rewritten (no options, retires marked shims and the old MCP row, exit 1 on any option, plugin sets SKILL_CONCIERGE_HARNESS=cline); doctor bullet rewritten (warns on old shim or old MCP row); --no-mcp bullet now also notes check_mcp_env_parity.py no longer checks adapters/cline/mcp.json; new "### Removed" section listing the deleted files, tests/test_cline_bridge_modes.py and the option, with the reason in one sentence. CLINE_SESSION_BACKEND_MODE was already discussed in the entry (doctor bullet, unchanged); I did not add the machine-wide harness-env.sh export, since the entry describes repo behaviour and the instruction was to add it only if the entry discusses the variable. This is a judgment call: the entry discusses the doctor warning, not the export.
- docs/adr/0086-...md (new in this branch): header now "Supersedes: ADR-0051's file-hook vehicle"; decision 6 rewritten as "File hooks are retired" with reason, leftovers handling, doctor behaviour and the plugin setting SKILL_CONCIERGE_HARNESS. Context point 1 and other sentences describe the old behaviour historically and were left.
- docs/repository-layout.md line 12, cline/ part: fallback, mcp.json and bridge/shim clause dropped.
- docs/runtime-flags.md SKILL_CLINE_ROOTS: "set by the Cline code plugin"; `_invocable_plugin_ids()` clause corrected.

## Code check behind the runtime-flags wording
hooks/scripts/enforcer.py: `_invocable_plugin_ids()` still returns None for Cline (comment at ~line 667). What changed is the filesystem twin: for Cline, a namespaced `plugin:skill` row passes when `~/.agents/plugins/<plugin>/plugin.json` and `skills/<skill>/SKILL.md` exist (`_cline_agent_plugin_skill`, used at ~lines 783 and 858); a plain row passes when it is in Cline's personal or project skill root or `~/.agents/skills`. The doc says exactly that. So the brief's hint that it "no longer simply returns None" is true of the twin test, not of that function.

## Not touched
AGENTS.md, openwiki/*.md and docs/caveats.md: grep found no Cline text describing the removed fallback, so no edit. openwiki/quickstart.md stays at 0.63.0 (driftcheck confirms).
Stale-comment note, out of scope (code, not in my file list): hooks/scripts/enforcer.py comments at ~lines 244 and 259 still say the Cline file-hook bridge sets SKILL_CONCIERGE_HARNESS.

## Verification
- grep for "file-hooks|cline-hook|cline/hooks/|adapters/cline/mcp.json" over README.md, AGENTS.md, docs/repository-layout.md, docs/runtime-flags.md, docs/caveats.md, openwiki/, docs/adr/0086-*.md: only three hits, ADR-0086 lines 85, 86 and 91, all in the "File hooks are retired" decision, historical.
- driftcheck.py driftcheck.json: exit=1, exactly one DRIFT line: "version: README.md has ['0.62.0'] but SSOT ... is '0.63.0'" (the known README release regex). All paths and the four command checks pass.
- check_flag_docs_parity.py: "flag-docs-parity OK: 40 table rows, 38 full entries; 40 table defaults and 37 stated docs defaults match the code".
- No git state-changing command run. Not checked: rendering of the edited Markdown, and doctor.py / install.sh behaviour (taken from the brief, not re-read in code).

Status: DONE_WITH_CONCERNS
Summary: All listed docs now describe the fallback as removed and the installer as retiring leftovers; checks pass except the one expected README drift line.
Unresolved questions: (1) Should the CHANGELOG entry also mention the machine-wide CLINE_SESSION_BACKEND_MODE=local export in ~/.config/harness-env.sh? I left it out because it is machine config, not repo behaviour. (2) The two stale enforcer.py comments (~lines 244, 259) naming the file-hook bridge need a code-side fix by whoever owns that file.
