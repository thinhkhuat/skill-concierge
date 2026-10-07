# Code review: `reputation.py suggest` (pre-ship)

Date: 2026-10-07 (Asia/Saigon). Reviewer: code-reviewer subagent. Mode: read-only.
Scope: `scripts/reputation.py` lines 180-302 (`_installed`, `_usage`, `_suggestions`, `cmd_suggest`, the suggest half of `cmd_selftest`). File is untracked (`?? scripts/reputation.py`), so this was a full read, not a diff.
Cross-read: `hooks/scripts/auto_promote.py:161-192` (`_proven_counts`), `hooks/scripts/ledger.py:101-200` (how `name` is recorded), `hooks/scripts/enforcer.py:1015-1074` (`_owner_tier`, `_badge`), `vendor/skill-search/skill_search/skills_discovery.py:346-391, 607-634, 694-711, 840-883` (how menu names are minted), `docs/adr/0083-owner-reputation-badges.md`, `tests/test_reputation_badges.py:224-228`.

## Commands run (raw results)

| Command | Result |
|---|---|
| `/usr/bin/python3 --version` | `Python 3.9.6` |
| `/usr/bin/python3 scripts/reputation.py selftest` | `reputation selftest ok`, exit 0 |
| `/usr/bin/python3 scripts/reputation.py suggest` (real files, read-only) | 64 suggestions (12 promote, 41 add, 11 demote, 0 remove), exit 0, 0.074 s |
| `pytest -q tests/test_reputation_badges.py -p no:cacheprovider` | `18 passed` |
| 3.10+ syntax scan of `reputation.py` + `auto_promote.py` (`X \| None`, `match`, `:=`) | no match - Python 3.9 safe (Fact) |
| Degenerate input A: real HOME, `SKILL_CONCIERGE_LOG` -> empty dir, temp reputation copy | `54 ⭐ demote` - every ❤️ entry demoted |
| Degenerate input B: `HOME` -> empty dir, temp copy, then `--apply` on the temp copy | 89 `remove` suggestions; after apply the temp file was `"heart": [], "star": []` (`_note` kept, backup `reputation.json.bak-20261007-224703` written) |

The real `~/.claude/skill-concierge/reputation.json` was never written. Probes ran from a `mktemp -d` dir outside the repo.

## Overall assessment

Rules logic in `_suggestions` is internally consistent: no name can be both promoted and demoted (promote needs ≥5 sessions in 30 days, demote needs 0 in 90), promote and exact-remove are disjoint (installed vs not installed), pattern-ranked skills resolve through the same exact-first rule as the hook (`_resolve` mirrors `enforcer._owner_tier`), add/promote de-dup works. `--apply` backs up before writing, writes atomically (`os.replace`), and keeps `_note` and any other top-level keys. Python 3.9 is fine. No private data printed: ledger junk names (pasted paths such as `Users/thinhkhuat/...handoff...md`, built-in slash commands) are filtered out because every promote/add name must be in the installed set.

The defects are in the **inputs**: the usage view and the installed view are both narrower than reality, and both degrade *toward destructive suggestions* instead of toward silence. With `--apply` writing every suggestion, that turns a transient read problem into a wiped or flattened ranking.

## High

### H1. Usage under a skill's frontmatter name is not credited; produces a false demote today
`scripts/reputation.py:203-211` (`_usage`) + `:224-226` (demote rule).
- Fact: the menu names a personal skill by its **directory** (`skills_discovery.py:619-628`, "name: the DIRECTORY name, always"), so the owner ranks `ak-problem-solving`. The ledger records whatever string the Skill tool received (`ledger.py:150-157`); 112 personal skills on this machine have a frontmatter `name:` different from the dir (e.g. `ak-cook` -> `name: ak:cook`), and the ledger holds both forms: `ak-cook` 28 sessions and `ak:cook` 4 sessions in 90 days; `ak-code-review` 2 + `ak:code-review` 2.
- Concrete failure (live data): `ak-problem-solving` is ❤️, used in 1 session in 90 days as `ak:problem-solving`, and `suggest` prints `⭐ demote ak-problem-solving — ❤️ but unused for 90 days`. `--apply` would demote it. Promote/add thresholds are likewise undercounted (`ak-cook` 28 -> union 31).
- Inference: Claude Code's Skill tool accepts the frontmatter name as well as the dir name. Not verified in Claude Code source; the ledger shows both forms arriving from `ev: auto`.
- Sibling (same class, outside this diff, per [73][70]): `auto_promote._write_proven` keys 🔥 on raw ledger names, so `ak:cook` usage never makes the menu row `ak-cook` 🔥.
- Fix: count sid **sets**, not counts, then fold aliases before thresholding. In `auto_promote.py` split `_proven_counts` into `_proven_sids(now=None) -> {name: set(sid)}` and keep `_proven_counts` as `{n: len(s)}` over it. In `reputation.py`, have `_installed()` also return `{frontmatter_name: dir_name}` for personal skills (read the first `^name:` line of each `SKILL.md`), and in `_usage` do `folded[alias.get(n, n)] |= sids`. Apply the same fold in `_write_proven` for the 🔥 sibling.

### H2. Missing or short ledger -> every ❤️ entry suggested for demotion; `--apply` flattens the top tier
`scripts/reputation.py:224-226`, `auto_promote.py:177-191` (returns `{}` on `OSError`).
- Fact (run A above): with no ledger, `suggest` emits 54 demotes, one per installed exact ❤️ entry. The same happens on any machine whose ledger covers fewer than 90 days: a new public-repo user who installs the plugin and runs the monthly pass after 3 weeks gets "unused for 90 days" for every favourite. This ledger starts 2026-07-06, i.e. ~93 days, so the real run here is only just covered.
- Fix: compute ledger coverage (earliest `auto`/`manual` `t`) in the same pass; if the ledger is absent or `earliest > now - 90*86400`, skip the demote rule and print `demote skipped: usage log covers N days, needs 90`. The claim "unused for 90 days" must be backed by 90 days of log.

### H3. Partial or unreadable installed view -> mass `remove`; `--apply` wipes the ranking
`scripts/reputation.py:185-200` (`_installed`), `:227-237` (remove rule).
- Fact (run B above): with no `~/.claude/skills` and no `installed_plugins.json`, all 89 entries (both tiers, patterns included) are suggested for removal and `--apply` leaves `heart: []`, `star: []`. The `except (OSError, ValueError, AttributeError): pass` at :198-199 turns a corrupt or mid-write `installed_plugins.json` (Claude Code rewrites it on every plugin update) into "no plugin skill installed", which removes every `plugin:skill` exact entry and every plugin pattern (`pstack:*`, `*:*`). The backup makes it recoverable, but the hook reads the file live, so the badges vanish on the next prompt with no warning.
- Fix: fail closed for the destructive rule. Return `None` (or a flag) from `_installed` when the registry is missing/unreadable or the personal root is absent, and in that case skip every `remove` and print why. Also refuse `--apply` when removals would exceed, say, half the entries without an explicit flag. The owner chose "apply all", so this is a guard on bad input, not a change of that decision.

### H4. Category-nested plugin skills are invisible to `_installed`
`scripts/reputation.py:196` globs only `skills/*/SKILL.md`.
- Fact: discovery (the menu's source of names) globs both `skills/*/SKILL.md` and `skills/*/*/SKILL.md` with a phantom guard (`skills_discovery.py:874-882`, `_nested_glob` docstring at :694-700 names `mattpocock-skills` as the observed case). On this machine `mattpocock-skills@claude-plugins-official` is installed and all 35 of its skills (`mattpocock-skills:tdd`, `:grilling`, ...) are missing from `_installed()`; the ledger already records 6 of them.
- Concrete failure: an exact entry `mattpocock-skills:tdd` would be suggested for removal and removed by `--apply`; a `mattpocock-skills:*` pattern would be removed as "matches no installed skill"; such a skill used in ≥5 sessions is never promoted. Latent today only because the owner ranked the personal symlinked copies (`~/.claude/skills/tdd`) and the plugin copies ride `*:*`.
- Fix: copy the discovery rule exactly: for each install root add `skills/*/*/SKILL.md` hits whose grandparent is not itself a flat skill dir, named `f"{pid}:{Path(h).parent.name}"` (`skills_discovery.py:871-882`).

## Medium

### M1. `remove` is Claude-only, but the ranking is read by every harness
`scripts/reputation.py:185-200`, `:236-237`. Fact: `_installed` reads `~/.claude/skills` and `~/.claude/plugins` only. ADR-0083 badges "installed" rows, and the enforcer builds installed rows per harness (Codex, OMP, ZCode, DSH, Cline skills, plus `<cwd>/.claude/skills` project skills). An owner who ranks a Codex-only skill, a `<project>/.claude/skills` skill, or an OMP plugin family gets a `remove` for it, and `--apply` deletes it. Also the ledger counts rows from every harness (`harness: omp/cline` rows exist) while names there are often bare (`doctor` 8 sessions from omp/cline/manual never credit `skill-concierge:doctor`). Fix: either state in the docstring/SKILL.md that `suggest` judges Claude Code installs only and restrict `remove` to entries whose shape is a Claude name (bare dir present under a Claude root, or `<pid>:` prefix of a registered Claude plugin), or include project skills (`Path.cwd()/.claude/skills/*/SKILL.md`). Judgment call: the doc statement plus the H3 guard is the smaller change.

### M2. Selftest skips the destructive path and the real readers
`scripts/reputation.py:288-298`; `tests/test_reputation_badges.py:224` is named `..._covers_every_suggestion_rule` but runs only this selftest. Not covered: `--apply` (backup exists and equals the pre-write bytes, `_note`/extra keys preserved, promote moves star->heart, demote moves heart->star, remove deletes from both tiers), promote of a skill ⭐ only through a pattern (`ak-git` under `ak-*` with 6 sessions -> exact ❤️), `_installed` (nested layout, unreadable registry), `_usage` (alias fold, coverage). Fix: add an `--apply` case against a temp file in the selftest, plus the three H-cases as regressions.

### M3. Threshold/window mixed between digest and hardcode
`scripts/reputation.py:244-245`. `proven_min` comes from `proven.json` (falls back to literal `5`, ignoring `SKILL_PROVEN_MIN_SESSIONS`), while the window is hardcoded `30` and `_usage(30)` overwrites the module's env-resolved `PROVEN_WINDOW_DAYS`. If the owner sets `SKILL_PROVEN_WINDOW_DAYS=14`, the menu's 🔥 and the "🔥 N sessions in 30 days" promote rule disagree. `proven.json` was absent on this machine at review time, so the literal fallback is what ran. Also `int(pv.get("min_sessions") or 5)` raises `ValueError` (traceback) on a non-numeric value. Fix: take both from the loaded `auto_promote` module (`ap.PROVEN_MIN_SESSIONS`, `ap.PROVEN_WINDOW_DAYS`, already env-validated by `_env_int`) and drop the digest read here; label the reason with the actual window.

## Low

- L1. `:259` backup name has 1-second resolution; two `--apply` runs in the same second overwrite the first backup with the already-modified file. Fix: open with `"xb"` and add a counter, or include microseconds.
- L2. `:251` printed commands are not shell-safe: `add` names are unquoted and `remove` uses `'{n}'`, which breaks on a name containing `'`. Names come from installed directory names, which a third-party plugin controls. Fix: `shlex.quote(n)` for every name. Also the printed `reputation.py ...` is not runnable as shown; the skill uses `python3 "$CLAUDE_PLUGIN_ROOT/scripts/reputation.py"`.
- L3. `_load` (:77) does not de-dup within or across tiers, so an entry listed twice yields duplicate suggestion lines. Harmless on apply (idempotent).
- L4. `_save` (:81-88, pre-existing) replaces a symlinked `reputation.json` with a regular file and drops non-string tier entries silently; no fsync before `os.replace`. Not new in this change.
- L5. `_installed` counts skills of installed-but-disabled plugins (`enabledPlugins: false`); their ranked entries get "demote" instead of "remove". Acceptable; mention in the docstring.

## Edge cases found by scouting

- Ledger `manual` rows include every `/...` prompt, so names like `Users/thinhkhuat/.../handoff-....md`, `''`, `login`, `insights` exist (122 names in 90 days not in the installed set). All filtered by the installed check, so nothing private prints. Keep that invariant if the filter is ever loosened.
- No promote/demote conflict, no promote/remove conflict (verified by rule reading and by the live output: 0 overlaps among 64 lines).
- `_usage` exec's `auto_promote.py` twice; module import has no side effects (no mkdir/write at import, verified), 5.2 MB ledger read twice in 74 ms total.

## Recommended actions (priority order)

1. H3 + H2: fail closed. Skip `remove` when the installed view is incomplete; skip `demote` when the ledger covers < 90 days. These two make `--apply` safe against bad inputs.
2. H1: fold frontmatter-name aliases onto directory names using sid sets (and fix the 🔥 digest sibling in `auto_promote._write_proven`).
3. H4: nested-category plugin skills, copied from `_claude_plugin_skill_paths`.
4. M2: selftest cases for `--apply` and each fix above.
5. M1, M3, then lows.

## Metrics

- Type coverage: n/a (untyped stdlib script).
- Test coverage of suggest: `_suggestions` 4 rules on one fixture; `_installed`, `_usage`, `--apply` uncovered.
- Lint: not run (no linter configured for this script found; not checked).

## Not checked

- Claude Code source for whether the Skill tool resolves frontmatter `name:` (H1 is grounded on ledger evidence only).
- Behaviour under Codex/OMP/other harness runs of `suggest` (M1 is from code reading).
- `cmd_list/add/remove/why` beyond what `--apply` reuses (out of scope).

## Unresolved questions

1. Should `suggest` judge only Claude Code installs (document it) or every harness's installed skills? (M1; my pick: document Claude-only and rely on the H3 guard, smaller change.)
2. For H2, should a short ledger skip demotes entirely or scale the window to the coverage? (My pick: skip and say so; "unused for 90 days" must mean 90 days.)

Status: DONE_WITH_CONCERNS
Summary: The suggestion rules are internally consistent, Python 3.9 safe, leak no private data, and `--apply` backs up, writes atomically and keeps `_note`. But both inputs fail toward destructive output: a missing/short ledger demotes every ❤️, an unreadable or partial installed view removes every entry (reproduced on a temp copy: ranking emptied), nested plugin skills are invisible, and frontmatter-name usage is not credited, which produces a false demote of `ak-problem-solving` on today's live data. Fix H1-H4 (fail closed on bad inputs, alias folding, nested glob) and add `--apply` selftest coverage before shipping.
