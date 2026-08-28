# ADR-0046 — The blocklist: a user-ordered disable tier

Status: Accepted + implemented (2026-08-29).
Amends: nothing structurally; sits orthogonal to [ADR-0011](0011-keep-off-suppression.md)
(keep-off) and [ADR-0025](0025-autonomous-override-freshness-and-keep-on-management.md)
(keep-on) as the third named list — and is the first mechanism that also covers skills the
index never sees.
Source: owner request in session, 2026-08-29 — "disable that resume-session skill — and if
the concierge has no mechanism for such disabling, build one properly (skills from external
sources or builtin, doesn't matter)".

## Context

The concierge had two curation lists, both about *attention*: keep-on (who gets a full
description every turn) and keep-off (who is chronic-never-taken and gets suppressed from
the offer menu). Neither is a disable. A skill on keep-off is still returned by
`search_skills`, still served by `get_skill`, still invocable, still hintable. And a whole
class of skills is invisible to every retrieval-side filter by design: command-files
surfaced as skills (`~/.claude/commands/*.md`) are excluded from the index
([ADR-0001](0001-index-model-invocable-skills-only.md)) — which is exactly how a useless
`resume-session` kept being invocable with zero governance. The trigger incident: the agent
reached for it on a "reload context" turn, it found no session data, and produced a rigid
briefing format — the user ordered it off, and the concierge had no lever.

## Decision

Add a **blocklist**: a flat, user-owned list of skill names at
`~/.claude/skill-concierge/blocklist.json` (`{"blocked": [...]}`, symmetric with keep-on's
shape; absent file = empty = the no-op default, and deliberately **never seeded** — unlike
keep-on there is no shipped default to own). "Disabled" is enforced at four layers:

1. **Invocation (the deterministic layer)** — new `hooks/scripts/skill_guard.py`, a
   `PreToolUse(Skill)` hook wired in `hooks/hooks.json`, denies any Skill tool call whose
   name matches the list. This is the repo's **second deliberate denying gate** after the
   openwiki commit guard, breaking the "hooks are fail-silent and additive-only" rule on
   purpose: a user-ordered disable is a gate, not telemetry — honoring it "usually" is not
   honoring it. It is the only layer that can catch command-files, plugin skills, and
   anything else the harness lists but the index does not. Fails open on internal error
   (a broken guard must never wedge skill invocation), and the deny reason names the entry
   and the unblock command.
2. **Offers** — `enforcer.py` drops blocked names from the candidate pool (riding the same
   `dropped` ledger field as keep-off), excludes them from deterministic routes, chain
   hints (a blocked seed suppresses the hint entirely — a disabled skill leaves no trace),
   ROUTE projections, and the foreign annex.
3. **Retrieval** — the vendored engine filters blocked rows from `search_skills` results
   and `get_skill` refuses to serve a blocked skill's body. Search-filtering without
   body-refusal would leak externals through their deep-pull lane. Read LIVE at call time
   (the MCP server is long-lived), so an edit applies with no reindex and no restart.
   Logged in `vendor/skill-search/VENDORED.md`.
4. **Injection** — `apply-overrides.py` forces a blocked keep-on skill back to name-only.
   The blocklist outranks the allowlist by construction; `keep-on.json` itself is left
   untouched so unblocking restores the allowlist intact.

**Name semantics** (identical at every layer): a **bare** entry blocks every qualified twin
— blocking `keep-on` blocks `skill-concierge:keep-on` and `plugin:keep-on` from any origin,
because "disable X" means X, everywhere. A **qualified** entry (`skill-concierge:keep-on`)
blocks only that exact form, for when one origin must die but a same-named sibling must
live. This satisfies the origin-agnostic requirement: personal, plugin, external-catalog
(`alias:name`), and command-file names all match.

**Surface**: `scripts/blocklist.py` (list / add / remove) + the `skill-concierge:blocklist`
skill, mirroring the keep-on pair. Path resolution joins `_keepon.py` (`blocklist_path()`),
so the canonical durable home and its `SKILL_CONCIERGE_BLOCKLIST` exact-file test seam are
single-sourced there.

**Kill-switch**: `SKILL_BLOCKLIST=0` disables the entire feature everywhere — the guard
passes, the enforcer filter no-ops, the engine filter no-ops, overrides stop stripping.
One-var revert, per house style. (It does NOT join `auto_reindex._mcp_env()`'s forward
tuple: that tuple's invariant is completeness of *index-shaping* flags the detached reindex
consumes, and the blocklist is index-neutral by design — it never touches a point.)

## What it is NOT

- Not keep-off: keep-off is *mined* attention-curation, offer-menu-only, still
  catalogue-reachable. The blocklist is a *user order*, enforced everywhere.
- Not file deletion / uninstall: the skill stays on disk and in the index (unblocking is
  instant and index-neutral). Physically removing a skill remains a filesystem operation
  the user owns.
- Not a user-typed-slash-command blocker: `/resume-session` typed by the human expands
  without a Skill tool call and is outside the guard's reach — correctly so, since the
  feature exists to stop the *agent's* reach, not the operator's own hands.

## Harness coverage

The deny guard rides the plugin hook surface (Claude Code and ZCode fire plugin hooks
natively; Codex and OMP have no PreToolUse(Skill) equivalent). Layers 2–4 are
harness-independent (the enforcer and engine run wherever the plugin does). Honest limit,
recorded: on harnesses without the Skill-tool hook surface, enforcement degrades to
retrieval-and-offer filtering only.

## Consequences

- Doctor gains a `Blocklist` check: absent file is healthy (nothing disabled), a present
  file must parse and carry a `blocked` list, and a missing `skill_guard.py` is a FAIL (the
  deny gate is the feature's teeth).
- Enforcer selftest pins the matcher (bare-twin catch, qualified exact-only, empty-set
  no-op, kill-switch) alongside the keep-off pins; `tests/test_blocklist.py` pins the guard
  (deny/allow/fail-open/kill-switch/non-Skill tool), the enforcer semantics, and the CLI
  round-trip.
- The matcher is deliberately triplicated (guard / enforcer / engine) rather than shared:
  each layer already self-contains its config reads (house precedent — the enforcer
  duplicates durable-home paths rather than importing across trees), and the layers must
  be free to fail independently.
- Deploying the engine-side filter requires the usual venv re-copy; long-lived MCP servers
  keep executing old bytes until restarted (ADR-0018 class). The hook and CLI layers are
  live immediately.
