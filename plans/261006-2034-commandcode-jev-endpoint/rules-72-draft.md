# Draft: RULES [72] amendment (draft -> approve -> promote, RULES [4])

Ordered: Thinh, 2026-10-06, answering the [72] override question: "yes, allow, since I've been with Command Code for long time and have good relationship with their services, as well as a bundled package to use with them. so CommandCode is not only allowed, but also as a preferred provider".

Target: `~/.claude/RULES.md:68`. Only the sentence about metered exceptions changes.

## Current sentence (byte-exact)

> Sole metered exception: TypeSafe **Jev** (`api.typesafe.ai`, `TYPESAFE_API_KEY`).

## Proposed sentences

> Metered exceptions, two only: **Command Code** (`api.commandcode.ai`, `CMD_API_KEY`), Thinh's preferred provider on a bundled package — when both serve a need, route to Command Code first; and TypeSafe **Jev** (`api.typesafe.ai`, `TYPESAFE_API_KEY`).

## Also needed on promotion

- `~/.claude/RULES-changelog.md`: one entry with the date, Thinh's quoted words above, and the revert path (restore the current sentence).
- Tell every running session that RULES.md changed (RULES [4]).

## Open point for Thinh

"Route to Command Code first" is my reading of "preferred provider". For the Jev router I did not apply it blindly. Command Code is first in line there, but it gets only 3.3 s of each turn before TypeSafe takes over, because Command Code was 3-9 s per turn against TypeSafe's 1 s (your choice "CC first, fall back to TS"). Say if the rule should carry a speed exception like that, or stay as written.
