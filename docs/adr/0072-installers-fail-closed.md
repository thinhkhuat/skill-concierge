# ADR-0072 — Installers fail closed: a complete copy or an error

Status: Accepted (2026-09-27)
Amends: ADR-0069 (the Codex and Claude Code installers), ADR-0071 decision 6 and the OMP, ZCode, Cline
and DSH installers (quoting, the checkout test). Corrects ADR-0069, which is accepted and left as written.
Evidence: `plans/reports/code-reviewer-260927-0020-v0527-diff.md`, the post-ship review of 0.52.7:
1 High, 6 Medium, 10 Low.

## Context

The v0.52.7 review found one High problem. The Codex installer's verify step failed only on a wrong
manifest version or a missing `skills/`. A missing launcher, MCP descriptor or hooks file was only a
warning. The fallback also extracted straight into the live cache dir. So an interrupted copy left a dir
that the next run called "Already current", with doctor reporting OK and an exit code of 0. Codex starts
`./bin/skill-search-mcp` directly, so that copy gives Codex no MCP server and no hooks.

Six Medium problems:
- **Quoting (M1).** `$ROOT` and `$DEST` were pasted into `python3 -c` source, so a path with an
  apostrophe crashed the installer, and a crafted directory name ran code.
- **Registry write (M2).** The rewrite replaced a symlinked `installed_plugins.json` with a plain file,
  widened its permissions, and could still lose a change made while it ran.
- **Doctor (M3).** Doctor's Claude Code row reported OK with the launcher missing, and printed the
  registry's version.
- **Fast path (M4).** The Codex fast path never asked Codex whether the plugin was installed or enabled.
- **Copy branch (M5).** The workbench's no-dot `git/` state went down the copy branch, shipping the git
  database and untracked files. So did a case-variant path to a real checkout.
- **Version (M6).** An uncommitted version bump put HEAD's content under the new version's name. Fixed
  in 0.52.8 (ADR-0071).

## Decision

1. **The Codex copy must be complete.**
   - The fast path, and the verify step, require the manifest, `skills/`, the launcher (executable),
     `.codex-plugin/mcp.json` and `.codex/hooks.json`. A missing one fails the verify.
   - The fallback extracts into a staging dir beside the target and swaps it in. A previous dir at that
     name is moved aside to `<version>.replaced-<time>`, never deleted.
   - Doctor's Codex row checks the launcher and the MCP descriptor too.
2. **Codex's own registry is read on every path.** The verify step always runs the read-only
   `codex plugin list --json`:
   - not installed → exit 1;
   - installed but disabled → stated plainly, with no "restart Codex to load" claim;
   - no `codex` CLI → a clear error, not "no marketplace registered".
3. **Paths never become code.** Every installer passes paths to `python3` and `node` as arguments. That
   covers Codex, Claude Code, OMP, ZCode, Cline and DSH.
4. **The registry repoint keeps the file's setup.**
   - It writes to the file a symlink points at, and keeps the file's permissions.
   - It stops, without writing, if the file changed while it ran.
   - It repoints only the record for the scope it refreshed, and records a commit only for a real checkout.
   - Backup names are unique per run. Fields are split with a unit separator, so an empty field no longer
     shifts the others.
5. **The checkout test uses file identity.** `[ "$ROOT" -ef <git top level> ]` is used in every exporting
   installer, so symlinked and case-variant paths to a checkout still export HEAD. A root whose git dir is
   renamed to `git/` is refused before any CLI call.
6. **Claude Code:**
   - The fallback is staged and swapped in the same way as Codex's.
   - The launcher's exec bit is restored on every path.
   - A missing launcher fails the verify; a missing exec bit only warns, because Claude Code starts it
     with bash.
   - Doctor's Claude Code row treats a missing launcher as a finding, reports the deployed content's
     version, and returns it as a top-level `version` key (for the Track B cut-over gate).
7. **The tests are hermetic.** The installer tests point the verify step's doctor at a dead Qdrant port
   and stub `docker`.

## Consequences

- Tests: 45 installer tests, 280 in `tests/` in all.
  - Twelve new tests fail on the 0.52.8 installers.
  - Three pin behaviour the 0.52.8 installers already had (an `add` that installs nothing, a symlinked
    root, a downgrade after the CLI refresh), and each fails when that behaviour is broken.
  - The doctor selftest fails when the missing-launcher finding is removed.
- **Corrections to ADR-0069:**
  - Its Decision 1 listed the launcher, the MCP and hooks files and the enforcer under "Verify" as if
    they could fail it; before this release only the manifest and `skills/` could.
  - "Refuses … a disabled plugin before any CLI call": two read-only CLI calls (`marketplace list`,
    `plugin list`) come first; no mutating call does.
  - `plugin-install-<random>` staging dirs sit one level up, beside `skill-concierge/`, not among the
    version dirs.
- Still open:
  - The OMP and ZCode installers still extract in place. They have no tests, so their exports were not
    changed beyond the checkout test.
  - `-y` stays unconditional (the marketplace declares no command).
  - `CODEX_HOME` and `CLAUDE_CONFIG_DIR` are still ignored.
  - Whether Claude Code keeps a hand-repointed registry entry, and whether a live Codex session loads a
    fallback copy, are still unverified.
- `adapters/codex/install.sh` is safe to run again; the Codex copy on this machine is at 0.45.0.
- No change to the standing order, the enforcer or the engine, so no new trail epoch.
- Revert: `git revert` of the release commit.
