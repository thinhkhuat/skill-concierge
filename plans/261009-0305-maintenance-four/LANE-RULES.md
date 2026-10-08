# Rules for every lane agent (main session decided these; follow exactly)

- Work ONLY in your own worktree and branch (given in your prompt). Edit ONLY the files your prompt assigns.
  Never touch the main checkout `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge` or another lane's worktree.
- Commit on YOUR branch after each slice that passes its tests (`git -C <your worktree> commit`), with a
  conventional-commit subject and a body explaining why. No push, no merge, no stash, no rebase, no branch switching.
  No AI attribution in commit messages.
- Do NOT bump versions, edit CHANGELOG.md, write ADRs or edit docs under docs/, openwiki/, README.md, AGENTS.md,
  CLAUDE.md: the main session does those after merging. List every doc statement your change makes stale in your
  final reply (file:line + what changed).
- Behaviour must stay the same: same stdout, same hook output JSON, same ledger rows, same exit codes, same files
  written. Prove it by running old (`git show main:<path>` copied under $TMPDIR) against new on the same inputs.
  When you run any hook by hand, set `SKILL_CONCIERGE_LOG` to a temp dir and `ENFORCER_LEDGER=0`; never write to
  `~/.claude/skill-concierge/logs/`.
- Hooks stay fail-silent and must load on Python 3.9 (`/usr/bin/python3`): keep `from __future__ import annotations`
  in every module you add under hooks/ or tests/ that the hooks load.
- Every new behaviour or structural guarantee gets a test that fails before your change and passes after.
- Run the tests covering your files after each slice, and the full suite (`python3 -m pytest -q -p no:cacheprovider tests/`)
  before your final reply. Quote the summary lines.
- Delete nothing outside your assignment. Scratch goes under $TMPDIR, never under ~/.worktrees/.
- End your reply with `Status: DONE | DONE_WITH_CONCERNS | BLOCKED`, a one-sentence summary, your commit hashes,
  and the stale-doc list. Timezone Asia/Saigon. English.
