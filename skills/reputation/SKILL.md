---
name: reputation
user-invocable: true
description: Manage the owner's skill ranking — the ❤️ house-favourite and ⭐ trusted badges skill-concierge shows next to skills on its per-turn menu, plus the automatic 🔥 proven badge. Use this skill when the user wants to view, add, remove, or move a ranked skill, says "heart X", "star X", "make X a favourite", "I trust the pstack skills", "unrank X", "which skills are my favourites", "why does X have a badge", asks about the badges on the menu, or wants tier suggestions / a maintenance pass ("suggest favourites", "which skills should be starred", "clean up my ranking"). Runs scripts/reputation.py (list / add / remove / why / suggest); the ranking lives at ~/.claude/skill-concierge/reputation.json and is read live by the per-turn hook — ADR-0083.
argument-hint: "[list | add heart|star <skill> | remove <skill> | why <skill> | suggest [--apply]]"
license: MIT
metadata:
  version: 0.3.0
---

# skill-concierge reputation

The owner's own ranking of skills, shown as a badge next to a skill on the per-turn menu:

| Badge | Meaning | Set by |
|---|---|---|
| ❤️ heart | House favourite: the owner's pick for its job | the owner, with this skill |
| ⭐ star | Trusted: vetted, preferred over skills the owner does not know | the owner, with this skill |
| 🔥 | Proven: used in at least 5 separate sessions in the last 30 days | computed at session start |

A badge never moves a row; Jev's order stays as it is. The menu's legend line tells the agent how
to choose: among rows that do the task's job as their main purpose, take ❤️ first, then ⭐,
then the rest, preferring 🔥 inside each group. A ❤️ or ⭐ skill that Jev ranked 6th to
10th and judged a fit joins the menu under its five rows (at most two).

## Steps

1. **Show the ranking and the current 🔥 list:**

   ```bash
   python3 "$CLAUDE_PLUGIN_ROOT/scripts/reputation.py" list
   ```

2. **Rank skill(s).** Use the name exactly as the menu shows it, or a pattern for a family.
   Adding a name to one tier moves it out of the other.

   ```bash
   python3 "$CLAUDE_PLUGIN_ROOT/scripts/reputation.py" add heart ak-code-review pstack:architect
   python3 "$CLAUDE_PLUGIN_ROOT/scripts/reputation.py" add star 'pstack:*' 'ak-*'
   ```

   Quote patterns so the shell passes the `*` through.

3. **Unrank skill(s):**

   ```bash
   python3 "$CLAUDE_PLUGIN_ROOT/scripts/reputation.py" remove <skill-name> [<skill-name> ...]
   ```

4. **Check what a name gets, and which entry gives it:**

   ```bash
   python3 "$CLAUDE_PLUGIN_ROOT/scripts/reputation.py" why ak-git pstack:recall
   ```

5. **Maintain the tiers (monthly, or when the menu feels off).** `suggest` reads the usage log
   and what is installed, then proposes: ❤️ for a 🔥 skill that is unranked or only ⭐; ⭐ for an
   unranked skill used in 2+ sessions in 90 days; and removal of an entry that is no longer
   installed or a pattern that matches nothing. A use is a Skill-tool load or a `get_skill` read.
   A ❤️ with no recorded use for 90 days prints as a **review** line only: the log misses
   rule-driven use (an agent writing an intent brief because a rule says so) and direct SKILL.md
   reads, so taking a ❤️ away stays the user's call. Each line prints the command that applies it.
   Show the list to the user. ❤️ is the user's own judgement, so ❤️ promotions print as `? ❤️`
   lines like the reviews; `--apply` writes only the ⭐ add and remove lines (the file is backed up
   beside itself first) and never adds or removes a ❤️. Bad input fails closed: no removal when
   the installed view is incomplete (and never for another harness's plugin), no review lines when
   the usage log covers less than 90 days; usage under a skill's frontmatter name (`ak:cook`)
   counts for its directory name (`ak-cook`), as on the menu:

   ```bash
   python3 "$CLAUDE_PLUGIN_ROOT/scripts/reputation.py" suggest
   python3 "$CLAUDE_PLUGIN_ROOT/scripts/reputation.py" suggest --apply
   ```

## Name rules

- An **exact** entry matches the menu name exactly: `code-review` does not match
  `agent-skills:code-review`. Use `why` to confirm a name.
- A **pattern** (`pstack:*`, `ak-*`) ranks a whole family.
- An exact entry beats every pattern, so `ak-code-review` as ❤️ stays ❤️ inside an `ak-*` ⭐
  family, and an exact ⭐ inside a ❤️ family demotes that one skill.
- Between two matches of the same kind, ❤️ wins.
- Owner badges show on skills installed here (and pulled rows) only. External-catalogue and
  other-harness rows never carry one, so `*:*` is safe for "every plugin skill"; `why` reports
  the entry a name matches, not where the row appears.

## Switches

| Variable | Default | Effect |
|---|---|---|
| `SKILL_REPUTATION` | on | `=0` shows no badge anywhere and stops the 🔥 digest |
| `SKILL_REPUTATION_PULL_MAX` | 2 | ranked skills pulled under Jev's five rows; `=0` turns pull-in off |
| `SKILL_REPUTATION_PULL_FIT` | 0.5 | the Jev fit a ranked skill needs to be pulled in |
| `SKILL_REPUTATION_PULL_DEPTH` | 10 | the lowest Jev rank a pulled skill can come from |
| `SKILL_PROVEN_MIN_SESSIONS` / `SKILL_PROVEN_WINDOW_DAYS` | 5 / 30 | the 🔥 bar |
