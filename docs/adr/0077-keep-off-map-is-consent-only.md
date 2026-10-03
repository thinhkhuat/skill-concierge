# ADR-0077: The keep-off map is consent-only — never built or refreshed automatically

- **Status:** Accepted (2026-10-04, owner's order).
- **Supersedes:** the automatic-build and automatic-refresh parts of ADR-0011 (generator not wired into doctor) and ADR-0054 decision 4 and its consequences (`doctor --fix` re-runs the generator on every pass via `REFRESH_FIXERS`; `setup.sh` builds the map at install). Both ADRs stay as written; their mechanism (what the map is, what it drops, the durable home) still stands.
- **Relates to:** ADR-0011 (keep-off), ADR-0054 (harness-message lane, keep-off activated), ADR-0046 (blocklist, the user-ordered disable tier).

## Context

Keep-off hides chronic never-take skills from the per-turn offer menu. Until now the map was derived from the ledger and rebuilt without asking: `setup.sh` step 3c built it at install, and `doctor --fix` re-ran the generator on every pass.

On 2026-10-04, `setup.sh` ran during the 0.57.0 release and grew the map from 10 to 45 skills. Nobody had approved that list. Checking how it was measured showed the "never taken" figure is not trustworthy:

- A skill counts as "taken" only when the Skill tool is invoked on the exact offered name in the same turn. `get_skill` loads (124 in the window), typed slash commands (32 `manual` events), inline `SKILL.md` reads and takes on a later turn are all invisible to it.
- 64 of the 381 Skill invocations in the window were made by subagents.
- `build_keep_off.py` `_windows` keys turns by `(sid, q)` in a dict, so repeated identical prompts collapse into one turn. `analyze.py` has since moved to a FIFO deque for the same join; the generator has not.
- Of the 45 names, 32 were never Skill-invoked under any name and 13 were invoked once or twice.

A suppression list that silently removes skills from what the agent is shown, built from a count with these gaps, is not something to run unattended.

## Decision

Thinh's order, verbatim: "keep off list should ONLY be built with my consent and NEVER BE auto. fix that"

1. **No automatic builder.** `setup.sh` no longer builds or refreshes the map (step 3c is a comment that points at the commands below). `scripts/doctor.py` only reports (`check_keepoff`); `fix_keepoff` and `REFRESH_FIXERS` are removed.
2. **The generator proposes by default.** `scripts/build_keep_off.py` prints the proposed list and writes nothing. It saves only with `--apply`, run after Thinh says yes to that list. The saved file carries `"approved_by_user": true`.
3. **The hook honours only an approved map.** `_load_keepoff` in `hooks/scripts/enforcer.py` returns the keep-off set only when the map has `"approved_by_user": true`. A map without the marker, or with any other value, hides nothing. The existing fail-open behaviour for an absent or unreadable file is unchanged.

The guard is `tests/test_keep_off_consent.py`: the hook ignores an unmarked or `false`-marked map, the generator writes nothing without `--apply`, and no automatic path (`setup.sh`, `doctor.py`, hooks, adapters) invokes the generator. Comments that tell Thinh how to run it by hand are allowed.

## Consequences

- **No suppression until he approves a list.** The map the 0.57.0 `setup.sh` run built at `~/.claude/skill-concierge/keep-off.json` (45 skills, generated 2026-10-04T01:32) is left on disk untouched. It has no `approved_by_user` marker, so it now hides nothing, and doctor's `Keep-off` row says so. All 45 skills return to the offer menu.
- Offer composition changes for every harness that reads the map: skills previously hidden can be offered again. Epoch-scoped ledger metrics must treat the change as a new epoch (`docs/epoch-watch.md`).
- `doctor --fix` and `setup.sh` leave the map alone, so an approved list ages with the ledger window until Thinh asks for a new proposal.
- **Open follow-up — the measurement defects above are not fixed by this change.** This ADR removes automation and requires consent; it does not make the "taken" count correct. Still open: `get_skill`, slash-command, inline-read and next-turn takes are not counted; subagent invocations are not separated from the agent's own; `_windows` still collapses repeated identical prompts. A proposal printed today inherits all three, so read it with that in mind before saying yes.

## How to approve a list

```
python3 scripts/build_keep_off.py            # prints the proposal, writes nothing
python3 scripts/build_keep_off.py --apply    # saves it as an approved map, only after Thinh says yes
```

`--apply` writes to `SKILL_CONCIERGE_KEEPOFF` (default `~/.claude/skill-concierge/keep-off.json`). `--full` still refuses the live path.

## Revert path

To restore the earlier automatic behaviour, revert the change that introduced this ADR: the consent check in `_load_keepoff`, the proposal-only default and `--apply` in `build_keep_off.py`, `check_keepoff` replacing the fixer in `doctor.py`, and the replaced step 3c in `setup.sh`. That also removes `tests/test_keep_off_consent.py`. This is the opposite of the owner's order and should be done only on his word. To make one specific map live without the revert, Thinh adds `"approved_by_user": true` to it himself.
