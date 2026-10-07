# 2026-10-07 — Reputation badges on the menu (0.61.0)

Thinh wanted his own judgement of skills to count on the per-turn menu, kept in a list he curates the way he curates keep-on. The release is commit `49d535d` (ADR-0083). It added ❤️ house favourite, ⭐ trusted and 🔥 proven badges, a pull-in block, and the `skill-concierge:reputation` skill with `scripts/reputation.py`. The session ended at about 23:10 Asia/Saigon, after two independent reviews had found real defects in the first build.

## Why badges and not reordering
- The first idea was to put reputable sources (ak-*, pstack, Matt Pocock) at the top of the menu. The replay says no. On 313 real turns where the agent used a skill (cached Jev answers, catalogue `f65af73783c60a68`), a hard reorder cut "the used skill ranked first" from 100 to 37 and "in the five-row menu" from 177 to 151 (2 gained, 28 lost). A +0.10 boost lost 9 for 2 gained.
- That measure rewards past agent choices, so it favours today's order. It still rules out a hard reorder, and the ADR says so in those terms.
- So the ranking is shown as a mark next to the name. Jev's order, its five rows and their percentage shares do not move.
- A badge used only as a tie-break was rejected too. Same-job twins rarely tie (45 % `code-review` against 11 % `ak-code-review`), so it would almost never decide.

## The owner's choices
- "all 3 badges now - #b it is": all three badges, and the wider of the two pull-in forms. I recommended the narrow one (❤️ only, `fits` ≥ 0.7, one row) on noise grounds; he took the wider one (❤️ or ⭐, `fits` ≥ 0.5, at most two rows). The revert path is `SKILL_REPUTATION_PULL_MAX=0` or `SKILL_REPUTATION_PULL_FIT=0.7`.
- `suggest` with `--apply`, not suggestions only. His order: "ship it, along with the supporting skills to manage, and suggest skills for each tier as well as maintaining the tiers".
- Demotions stay review-only. The usage log showed it misses rule-driven use, such as intent briefs written under his own rules, so a ❤️ with no recorded use is printed as a review line and never removed.
- His first list: "every plugin:skill should be added to the reputation list, along with ak-* family, matt-pocock's skills too, and those in the keep-on list". I asked which badge each group gets. No answer in 600 s, so I applied the recommended default and logged it in `decisions-log.md`: 54 keep-on skills as ❤️, and `*:*`, `ak-*` plus Matt Pocock's personal skills as ⭐ (heart 54, star 35 written).

## What the two reviews caught
The builder (me) did not validate the build. A validator and a code reviewer ran blind, and both found things my own checks missed.

- **Red test suite.** `_jev_route` became a 4-tuple, and `tests/test_jev_history.py` still unpacked 3. The validator's full run: `1 failed, 1027 passed`. My own earlier suite record showed the same failure, and I had gone past it. The test now passes the 4-tuple (it reads `res["result"][0]`).
- **Env typo crash.** `float(os.environ.get("SKILL_REPUTATION_PULL_FIT", "0.5"))` ran at import, so a typo like `0,5` in `~/.config/harness-env.sh` would have killed the hook in every harness (`ValueError: could not convert string to float: '0,5'`). The repo already had `_env_int` for exactly this. The tunables now go through `_env_float` and `_env_int` (`enforcer.py:2115`, `auto_promote.py:169`).
- **Legend on 🔥-only menus.** 🔥 is automatic, so the full 352-character legend would have appeared on about 70 % of recent offers before Thinh ranked anything (an epoch-pooled figure, indicative only). A 🔥-only menu now gets a one-line legend, about a quarter of the length.
- **`*:*` marking external rows.** A pattern meant for "every plugin skill" would also have badged `antigravity:` and `vercel:` rows. Badges now render on installed and pulled rows only.
- **`suggest` destroying data on bad input.** The reviewer reproduced it on temp copies: with no ledger, 54 ❤️ entries were all demoted; with no installed view, `--apply` left `"heart": [], "star": []`. A mid-write `installed_plugins.json` would do the same. `suggest` now fails closed: no removal from an incomplete installed view or for another harness's plugin, no review from a log shorter than 90 days.
- **Frontmatter-name usage not counted.** The menu names `ak-cook` by directory, the ledger records `ak:cook` as well, and 112 personal skills have that mismatch. Result: a false "unused" line for `ak-problem-solving`. Both 🔥 and `suggest` now fold usage onto the directory name.

Smaller findings in the same reports (skip-band ledger rows recording `badges` for unshown rows, three docs saying the standing order carries the rule when the legend does, nested-category plugin skills invisible to `suggest`) are listed in the two reports under `plans/reports/`. I did not re-check each one for this entry.

## The flaky relay test
`tests/test_owner_jev_relay.py::test_a_pooled_connection_the_provider_closed_is_discarded_before_use` failed once in a full-suite run. It then passed 3 of 3 here and 2 of 2 at 0.60.0, as reported to me by the session that ran it; I did not re-run it for this entry. I have no root cause. The test is about a pooled connection the provider closed, so a timing race is the first suspect, but that is a guess (Inference). Nothing in 0.61.0 touches the relay, which is why I am not blaming this release, but passing 5 times does not prove a race is absent.

## Lessons
- Run the whole suite and read the failure line before saying done. A recorded red test is not a pass.
- Any code that deletes from a curated list must fail closed when its inputs are short or missing. The destructive path was the one the selftest skipped.
- A replay that rewards past agent choices can rule a design out; it cannot prove a new one good. That is why W41 exists.

## Open
- **W41 watch.** Epoch-watch W41 (in `docs/epoch-watch.md`, added in `49d535d`; I did not re-read its text) watches whether agents stretch the first pass ("does this task's job as its main purpose") to admit a badged row. The validator saw the shape live: `ak-github ❤️` at row 1 on a code-review task in the preview path. Nothing is measured yet.
- **Pull-in noise.** The ADR's simulation used three families and caught 0 of 13 at bar 0.5, adding 0.44 rows a turn. Thinh's real list is broad (`*:*`, `ak-*`, 54 exact names), so pull-in will fire more often than that simulation. The ADR's trigger is 0.5 pulled rows per turn.
- **Eleven ❤️ review lines await Thinh.** `suggest` prints ❤️ entries with no recorded use as review lines only. The eleven lines are his to read: keep, demote with `reputation.py add star`, or leave. Nobody else may decide this, and nothing is removed until he does.
- Not checked: the Codex, OMP, ZCode, DSH, Cline and Command Code adapters. The change touches the enforcer's stdout only.
