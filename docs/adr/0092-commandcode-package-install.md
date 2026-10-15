# 0092 — The Command Code mod also installs as a Command Code package (`cmd mods add`)

- Status: accepted
- Date: 2026-10-15
- Deciders: Thinh ordered "upgrade our concierge to support installing via `cmd mods add -g thinhkhuat/skill-concierge`", then to
  archive the drop-in copy and reinstall as the package for auto live updates.
- Relates to: ADR-0038 (Command Code adapter), ADR-0091 (the drop-in copy carries its checkout path). Implementation: the packaging
  manifest in `package.json`, doctor's `Command Code integration` row, and the pin test `test_package_cloned_repo_layout_reaches_hook_scripts`.

## Context

`adapters/commandcode/install.sh` reaches Command Code by copying `skill-concierge.mod.ts` into `~/.commandcode/mods/skill-concierge.ts`
with the checkout path written into its `INSTALLED_ROOT` line (ADR-0091). Every repo-side change then needs an installer rerun, and the
copy loses its origin the moment the checkout moves. Command Code has a native package route: a repo whose `package.json` declares a
`commandcode.mods` manifest installs with `cmd mods add owner/repo`, clones the whole tree under
`~/.commandcode/mods/.registry/git/<host>/<owner>/<repo>/`, and loads mods straight from the clone; `cmd mods update` pulls the newest
pushed code. The repo never had that manifest, so the route reported "installed, but provides no mods".

## Decision

1. **The repo ships the package manifest.** Root `package.json` declares `{"commandcode": {"mods": ["./adapters/commandcode/skill-concierge.mod.ts"]}}`
   plus the `cmd-mod` keyword. The mod file stays where it is: only the exact path must match what the manifest points at.
2. **No resolver change.** The mod file sits exactly two directories below the clone root, and the ADR-0091 ladder's last rung,
   `resolve(__dirname, "../..")`, already points there. The registry clone is the full repo and ships `hooks/`. The pin test
   (`tests/test_commandcode_mod.py`) locks the two-dirs-under-root assumption so a future move of the file fails loudly, in the mod harness,
   instead of silently no-oping.
3. **The drop-in route stays first-class.** `install.sh`, `mod_root.py` and the verify step are unchanged. The package install replaces
   only the mod copy: SessionStart hooks, the MCP entry and the skills root remain installer-wired (`~/.commandcode/{settings,mcp}.json`),
   and a package-only install needs the installer run once to wire them.
4. **Doctor accepts either mod source and flags the double.** The `Command Code integration` row reports which model loaded (drop-in or
   package-provided). For the package case it checks the clone root still reaches `hooks/scripts/enforcer.py` and compares the clone's
   `package.json` version against the SSOT (a WARN + `cmd mods update`), not against this checkout: the clone is its own source of truth and
   may be newer than the local checkout after an update. Loading BOTH mods is a finding — each registers its own hooks and would govern
   every prompt twice.

## Alternatives rejected

- **Rename the file to `skill-concierge.ts`** so `cmd mods list` names the mod `skill-concierge` instead of `skill-concierge.mod` (the name is
  the file basename). It breaks the sibling adapters' `-suffix` naming convention (`skill-concierge.dsh.ts`, `skill-concierge.ext.ts`) for
  zero behavior, and drags a docs-plus-tests sweep. The name is cosmetic; nothing keys on it.
- **Ship the skills dir via `commandcode.skills`** so the package also brings the skills. It would double every skill against the settings
  entry the installer already writes (`~/.commandcode/settings.json` skills array) and churn the index; skills stay on the installer root.
- **Make `install.sh` package-aware** (skip the copy when a source is configured). Two moving surfaces for no gap: running the installer again
  with a package present is the exact double-load doctor now flags.
- **Resolver ancestor walk from `__dirname`** in case the mod file moves deeper. YAGNI: the manifest and the file move together; the pin test
  turns any accidental move into a failing test, not a silent miss.

## Consequences

- `cmd mods add -g thinhkhuat/skill-concierge` on 0.69.0+ installs a working governance mod with no installer involved (hooks/MCP aside);
  `cmd mods update` is the live-update path and needs the change pushed to GitHub first.
- `cmd mods list` shows the mod as `skill-concierge.mod` under `from git:github.com/thinhkhuat/skill-concierge`.
- A `cmd mods update` refreshes the mod but never the SessionStart hooks or MCP descriptors, which still point at the (also present)
  checkout. When the checkout lags the clone, doctor's new registry-version row makes the seam visible instead of silent.
- The double-load guard exists in doctor, not in Command Code's loader: the CLI still loads both over it — check `cmd mods list` after both
  routes have been used.
