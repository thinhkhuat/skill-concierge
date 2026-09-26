# ADR-0069 — Codex and Claude Code installers; checkout-aware exports for every installer

Status: Accepted (2026-09-27)
Amends: ADR-0033 (Codex parity: adds a sync installer) and the OMP/ZCode installers of ADR-0039 and
ADR-0042 (their git-checkout test). Owner decision D9 (2026-09-26): the installers ship as their own
release ahead of Track B, not inside v0.54.0.
Evidence: `plans/reports/orchestrate-260926-2100/` — `arbiter/result.md` (the first review, FAILED on the
Codex installer), `fix-installers/result.md`, `fix-followups/result.md`, `bloat-audit/result.md`; the
merging session's own review of commits `a33435a`, `1455586` and `c6497b0` against every arbiter finding,
with the tests run in a throwaway clone.

## Context

OMP, ZCode, DSH, Cline and Command Code each had an installer that brings their copy of the plugin to this
checkout's version. Codex and Claude Code, the two harnesses the owner uses most, had none: Codex needed
hand-run `codex plugin` commands, and Claude Code relied on the marketplace alone, which only ever reaches
what is pushed. The first Codex installer failed its independent review. It ran `codex plugin remove`
then `add`, so a failed `add` left Codex with nothing installed while the script still exited 0. It also
re-enabled a plugin the user had disabled, and it misstated what gets deleted.

## Decision

1. **`adapters/codex/install.sh`** syncs an existing registration. It never runs `codex plugin remove`.
   - It refuses to downgrade a newer cached copy, both before any CLI call and after the refresh.
   - It refuses, before any CLI call, when the plugin is installed but disabled: `codex plugin add` always
     re-enables, and Codex has no command that keeps a plugin disabled.
   - It runs `codex plugin marketplace upgrade`, then `codex plugin add`. If the add fails, or `codex plugin
     list --json` does not then show the plugin installed, it exits 1 with restore steps.
   - When the plugin is installed but the cache still lags this checkout (the normal unpushed case), it
     exports this checkout into a new version-named cache dir. That step deletes nothing; Codex's own
     `add` was observed to replace the plugin's whole cache dir.
   - Verify: the cache manifest version, `skills/`, the launcher exec bit, the MCP and hooks files, the
     enforcer byte-identical to the checkout, the `plugin list` state and doctor's Codex row.
2. **`adapters/claude-code/install.sh`** runs `claude plugin update skill-concierge@skill-concierge --json -y`.
   - It refuses a downgrade before and after that call.
   - When the marketplace has not reached this checkout, it exports the checkout into the versioned cache
     dir and repoints `installed_plugins.json`: backup first, then a temp file swapped in with `os.replace`.
   - It never edits `enabledPlugins` and says so. `-y` would accept a command the marketplace declares;
     this marketplace declares none, and `--accept-command <sha256>` is the narrower option if one appears.
3. **Doctor** gains a Claude Code row: the installed content's own version, not the registry's, against
   this checkout, plus the launcher exec bit. The Codex row picks the newest version dir by number, ignores
   non-version staging dirs, and names the installer as the fix.
4. **Every installer that exports** (Codex, Claude Code, OMP, ZCode) takes `git archive HEAD` only when the
   checkout is its own git top level (`git rev-parse --show-toplevel` equals the resolved root). A linked
   worktree exports HEAD. A plain directory inside some other repo is copied as a directory, and says so,
   instead of exporting the outer repo. The old test, whether `.git` is a directory, sent worktrees down
   the copy path.

## Consequences

- Tests: `tests/test_codex_installer.py` and `tests/test_claude_code_installer.py` (fake CLIs, throwaway
  `HOME`), including a worktree export and a plain root nested in an unrelated repo. Both nested-root tests
  fail when the old `--is-inside-work-tree` check is restored. The repo suite has 254 passing tests at
  `c6497b0`.
- Open, not verified:
  - whether Claude Code keeps a hand-repointed registry entry through its own update logic at session
    start (the marketplace auto-updates on this machine);
  - whether a live Codex session loads hooks and MCP from a fallback-synced dir (only `codex plugin list`
    was checked).
- Not covered:
  - the OMP and ZCode installers have no dedicated tests;
  - `CODEX_HOME` and `CLAUDE_CONFIG_DIR` are ignored, like the rest of the repo;
  - a missing `codex` binary is reported as "no marketplace registered";
  - the workbench's no-dot `git/` state is not excluded when a checkout is copied as a plain directory.
- The Codex copy on this machine is at 0.45.0 and doctor now names the installer as the fix; running it is
  the owner's step.
- No change to the standing order, the enforcer or the engine, so no new trail epoch.
- Revert: `git revert` of the release commit and the three installer commits.
