# ADR-0057 — Command Code's `personal` scope follows the live shelf

Status: Accepted (2026-09-25, owner order: "finish and release it")
Supersedes: the Command Code `_foreign_scopes()` line of ADR-0038 §1 (`personal` always foreign)
Relates to: ADR-0034 (cross-harness offer isolation), ADR-0042 (the ZCode shared-shelf rule this mirrors)

## Context

ADR-0038 made `personal` (skills under `~/.claude/skills`) always foreign under Command Code, on
the reasoning that Command Code loads only its own roots. That reasoning holds for the roots, not
for what they point at. Command Code reads `~/.commandcode/skills`; on the reference machine that
directory is a symlink to `~/.claude/skills` (verified live 2026-09-18: `commandcode -p` returned
a personal-scope skill's real content; re-checked 2026-09-25 with `readlink`). So every `personal`
skill IS invocable there, and treating the scope as foreign pushed the whole personal shelf out of
the Command Code offer and into the "other harness" annex.

An uncommitted fix from 2026-09-18 simply dropped `personal` from the Command Code tuple. That is
right for the reference machine and wrong for any machine where `~/.commandcode/skills` is a
separate directory: there, personal skills would be offered as if invocable. ZCode had already met
the same shape (ADR-0042, `~/.agents/skills`) and settled it with a per-session filesystem check.

## Decision

- `enforcer.py` gains `_resolves_to_claude_personal(root)` — the body of the old
  `_zcode_shares_personal_shelf()` with the root as a parameter — and a
  `_commandcode_shares_personal_shelf()` wrapper for `~/.commandcode/skills`.
- Under Command Code, `_foreign_scopes()` returns the other harnesses' exclusive roots, plus
  `personal` only when `~/.commandcode/skills` does NOT resolve to `~/.claude/skills`. Anything that
  is not positive knowledge of a shared shelf (missing dir, divergent dir, `OSError`) keeps
  `personal` foreign — the ADR-0038 behaviour.
- The decision is resolved per session in the hook, never baked into the machine-global index
  (the ADR-0028 hazard).
- Selftest (6c) pins both branches: shared shelf → `personal` invocable; divergent shelf →
  `personal` foreign and a route naming a bare personal skill does not fire.

Shipped in the same release, because they fix the same 2026-09-18 Command Code incident:
`adapters/commandcode/install.sh` strips `PreCompact` as well as `UserPromptSubmit` (Command Code
accepts only `PreToolUse`/`PostToolUse`/`Stop`/`SessionStart`), and `doctor.py` warns on any
unsupported hook event and on a stray root-level `SKILL.md`, which makes Command Code discard every
skill in that root. See `docs/caveats.md` §23 items 2, 6, 7.

## Consequences

- On the reference machine the Command Code offer regains the personal shelf; the annex no longer
  lists skills the session can in fact invoke.
- On a machine without the symlink, behaviour is unchanged from ADR-0038.
- Revert: return `base + ("personal",)` unconditionally in the Command Code branch.
