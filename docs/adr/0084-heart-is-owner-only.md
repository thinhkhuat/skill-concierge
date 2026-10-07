# ADR-0084: ❤️ is owner-only — `suggest --apply` never adds or removes one

- **Status:** Accepted (2026-10-07, shipped in 0.61.1 on the owner's choice "❤️ is owner-only").
- **Amends:** ADR-0083 decision 5 (`suggest --apply` wrote ❤️ promotions).

## Context

ADR-0083 shipped `suggest --apply` writing ❤️ promotions (a 🔥 skill, 5+ sessions in 30 days, that
is unranked or only ⭐) while leaving ❤️ demotions as review lines, because the usage log misses
rule-driven use. Together those rules let ❤️ only grow: each monthly run adds today's busiest skills
(12 on 2026-10-07) and nothing removes one. The legend prefers ❤️ over ⭐, so a ❤️ list that tracks
usage stops marking the owner's own picks, and usage already has its own badge, 🔥.

## Decision

`--apply` writes only ⭐ additions and removals of entries that are no longer installed. ❤️
promotions print as `? ❤️ promote` lines, beside the `? ❤️ review` lines, each with the command that
applies it; the owner runs the ones he accepts. `APPLIED = ("add", "remove")` in
`scripts/reputation.py`; the script's selftest fails if `_apply` changes the ❤️ tier.

## Consequences

The ❤️ tier changes only by the owner's command. A heavily used skill still shows 🔥 on the menu.
Revert: put `"promote"` back into `APPLIED`.
