# Cline plugin rework: status (2026-10-08 20:15)

Branch `feat/cline-plugin-v2`, worktree `~/.worktrees/skill-concierge/cline-v2`, cut from `main` at
`1ccbd5b`. Nothing is committed. It replaces the first attempt, branch `cline/0a565`, which did not
merge (`review-261008-1839-cline-worktree-merge-verdict.md` in the main checkout's reports).

## Result

On Cline 3.0.70, skill-concierge now runs as a native code plugin plus a generated agent-plugins.org
Agent Plugin, as the owner chose: a blocked skill refuses only that call, both plugin forms ship, and
the rework is proven live. Design and verified platform facts: `docs/adr/0086-cline-native-plugin-and-agent-plugin.md`.

Shown live (Cline 3.0.70, `openai-codex` provider, `CLINE_SESSION_BACKEND_MODE=local`, final code):
- **Prompt and menu:** the model receives the prompt word for word and the skill menu on the first call.
- **Rule:** the SKILL-FIRST rule is in the system prompt.
- **Skills and MCP:** all ten `skill-concierge:*` skills are listed, and the MCP search tool is present.
- **Blocklist:** a blocklisted skill is refused with the blocklist's reason, and the turn completes.
- **`get_skill`:** the skill body arrives whole, and the "not for" echo follows as separate hook context.
- **Ledger:** a four-call turn writes one turn row and one offer row.
- **Clean load:** Cline rejected no skill once the generated folder replaced the symlink.

## Gates (`plans/261008-1852-cline-plugin-rework/GATES.md`)

Met 7 of 11: G1 (plugin hook tests), G4 (release 0.63.0 / ADR-0086), and G5–G9 (live behaviour).

Open:
- **G2, whole `tests/` suite in the worktree:** fails only because the version bump is uncommitted
  (the Codex installer tests refuse a working-tree version that differs from HEAD). A committed
  scratch copy of the same tree is the evidence until the commit (see Tests).
- **G3, driftcheck:** one problem, by design. The README release line must say `**published`, and this
  release is not yet committed, merged or pushed. The wording changes in the merge commit.
- **G10, doctor's Cline row:** warns while `CLINE_SESSION_BACKEND_MODE` is not `local`. This waits on
  owner decision 1.
- **G11, independent review:** both reviews are done and every confirmed defect is fixed except H2,
  which waits on owner decision 1.

## Reviews

- **`code-reviewer-261008-1852-cline-rework-review.md`:** H1–H3, M1–M7 and L1–L9.
  - Fixed: H1 (hook budget 2.7 s → 2 s), H3 (subagent `agent_id`), M1, M6, M7, L1, L2, L3 and L9.
  - H2 (hub sessions run no plugin): doctor now warns, and the fix itself is owner decision 1.
  - Documented as caveats in ADR-0086: M2, M3 and M5.
  - In the merge plan: M4.
  - Accepted as is: L4 (`--no-mcp` removal, now in the CHANGELOG), L5, L6, L7 and L8.
- **`chisle-audit-261008-1852-cline-rework.md`:**
  - Applied: `mcp.json` generated from `.mcp.json`; `--print-for` removed (the output was
    byte-identical); disallowed keys dropped instead of folded; migration code removed; doctor runs
    `agent_plugin.py check`; `fire` merged; the wait timer cleared.
  - Open: deleting the file-hook fallback (owner decision 2).
- **`code-reviewer-261008-2001-cline-fix-verification.md`:** H1, H2, M7, L1–L3 and the symlink
  refusal hold. Then fixed: N1 (an ownership check in `sync()`, run before any write), M1 narrowed to
  `userRunSpan === 0`, L9 (only plain scalars quoted; a YAML-parse test added), H3's search lane
  (`ledger.py`, every harness), N4 (stale docs), and the doctor env check normalised. Left as notes:
  N2 (the file-hook mode doctrine names the plugin tool; moot while that mode's doctrine output is
  discarded), N3, N5 and N6.
- **Incident:** a reviewer's test run wrote through a symlink into the worktree's `skills/` at 19:48.
  It was restored from HEAD and verified clean. The cause was the removed guard, and the generator now
  refuses a symlinked destination and any folder it did not build.

## Tests

- Cline tests in the worktree pass: `test_cline_plugin.py`, `test_cline_agent_plugin.py`,
  `test_cline_installer.py`, `test_cline_bridge_modes.py`, `test_sibling_installers.py`, and
  `test_harness_regex_parity.py`.
- Mutation checks: putting the old bugs back fails 4 of 8 plugin tests, the decoy fails the G4 oracle,
  and removing the search-lane stamp fails its ledger test.
- Full suite on a committed scratch copy of the final code (20:18): **1093 passed, 0 failed**. An
  earlier run had one load-sensitive failure,
  `test_installer_staging_cleanup.py::test_a_signal_killed_export_leaves_no_staging_dir_behind`,
  while a second suite ran in parallel; that file passed 3 of 3 runs alone.

## Live state on this machine

- `~/.cline/plugins/skill-concierge.ts` loads the plugin from the cline-v2 worktree.
- `~/.agents/plugins/skill-concierge/` is generated from the same worktree.
- The old file-hook shims and the MCP row this installer once merged are removed. The shim backups
  are in `~/_ARCHIVE/skill-concierge-cline-install-backups-20261008/`, and the settings backups sit
  beside `cline_mcp_settings.json`.
- After a merge, re-run `adapters/cline/install.sh` from the main checkout before removing the
  worktree.

## Owner decisions still open (asked 20:02, no answer)

1. **Hub mode.**
   - *What:* add `export CLINE_SESSION_BACKEND_MODE=local` to `~/.config/harness-env.sh`.
   - *Why:* sessions attached to a running Cline hub, such as the VS Code extension's sidecar, are
     built with no plugins (`configExtensionCount: 0`), and that sidecar also lacks `jiti`.
   - *Pick: add it.* Cost: CLI sessions stop attaching to the hub, so they may not appear in the VS
     Code session list (unverified).
2. **File-hook fallback.**
   - *What:* delete `install.sh --file-hooks` and its bridge, shims and tests.
   - *Why:* on Cline 3.0.69+ it delivers no menu and no doctrine, and its deny ends the whole turn.
   - *Pick: delete it* (about 590 lines). It reverses ADR-0086 decision 6, so it is the owner's call.
3. **Ship.**
   - *What:* commit on the branch, fast-forward `main` (clean, and equal to the base), push, re-run
     the installer from `main`, and remove the cline-v2 worktree.
   - *Pick: all of it,* once decisions 1 and 2 are made. The old Cline-made worktree
     `~/.cline/worktrees/0a565` is left for the owner.

## Final state (2026-10-08 21:00 +07) — supersedes the open decisions above

Thinh answered at 20:40: hub mode yes, delete the fallback yes, ship. Done since:

- `CLINE_SESSION_BACKEND_MODE=local` is exported in `~/.config/harness-env.sh` (backup beside it); fresh zsh and bash shells see it, and doctor's Cline row is green in a fresh shell.
- The file-hook fallback is deleted (bridge, four shim templates, `adapters/cline/mcp.json`, `--file-hooks`, `tests/test_cline_bridge_modes.py`). `install.sh` takes no options and retires an old install's marked shims and MCP row; the CHANGELOG carries an upgrade note.
- A third blind review of the removal found no Critical or High issue; its findings are fixed or accepted (GATES.md G11).
- Full suite on a committed copy of the tree before the last review fixes: 1085 passed, 0 failed; the Cline, installer and doctor tests after them: 99 passed.
- One-off edit scripts and backups moved to `~/_ARCHIVE/skill-concierge-cline-rework-scratch-20261008/`; the live-session evidence stays in `_scratch/live/`.
