# ADR-0020 — Subagent session-scoping for the doctrine injector (H3)

Status: Accepted (2026-07-06)
Relates to: ADR-0016 / ADR-0015 (the default-ON one-var-revert flag pattern this mirrors), the
audit-side subagent exclusion (telemetry-dev — the PRIMARY H3 leg). Plan:
`plans/260706-1315-superpowers-anti-dodge-integration/` (Phase 2). Design arc:
`docs/anti-dodge-integration-v0.14.md`. Live source docs: https://code.claude.com/docs/en/hooks
(pulled 2026-07-06). Reference (adapted, not copied): superpowers v6.1.1 `<SUBAGENT-STOP>`
(`using-superpowers/SKILL.md:6-8`) — MIT.

## Context
`doctrine.py` (SessionStart hook) injected the SKILL-FIRST standing order into EVERY session,
including subagent / dispatched sessions. Two costs: (a) a scoped worker that cannot act on the
doctrine gets nagged anyway; (b) subagent traffic contaminates the shared usage ledger H1 measures
(a single meta session alone once swung uptake 17%→14%).

**Correcting the red-team.** Red-Team F3(b) claimed "the SessionStart payload carries NO subagent
signal (`source ∈ startup/resume/clear/compact`)" and concluded `doctrine.py` could not be scoped
live. That was wrong — it read the `source` enum but MISSED the COMMON hook-input field **`agent_id`**:
per the live docs, *"Present only when the hook fires inside a subagent call. Use this to distinguish
subagent hook calls from main-thread calls."* So live injection-scoping IS feasible, and `doctrine.py`
is in-scope (not "audit-side only").

The fail-DIRECTION trap from F3(a) stands and is honored: `doctrine.py`'s existing idiom is
`except → return 0`, which for an INJECTOR means SUPPRESS. A naive `try/except: return 0` wrapper would
drop the doctrine on real top-level sessions — the opposite of intended.

## Decision
- **Flag.** `SKILL_SUBAGENT_STOP` (default-ON, `os.environ.get(...,"1") != "0"`), one-var revert.
- **Detection (`doctrine.py:_is_subagent`).** Read the SessionStart stdin payload; suppress injection
  ONLY on a POSITIVE proof — the common `agent_id` field present and a non-empty string. Keyed on
  `agent_id`, **NOT `agent_type`** (`agent_type` also appears for top-level `--agent`/persona sessions,
  which MUST keep the doctrine). Suppression is `agent_id present AND SKILL_SUBAGENT_STOP on`.
- **Fail TOWARD injection [Red-Team F3a].** The stdin read is wrapped so any failure leaves `raw=""`;
  `_is_subagent` returns False on ANY parse error / non-dict / missing field. A detection glitch
  therefore FALLS THROUGH to the existing inject block — it NEVER `return 0`s on a parse error.
  Suppression requires positive `agent_id` proof, never absence-of-signal. The pre-existing
  `except → return 0` now guards ONLY a genuine doctrine-FILE read error (nothing to inject anyway).
- **Byte-identical revert.** `SKILL_SUBAGENT_STOP=0` → the subagent branch is skipped entirely →
  unconditional injection, byte-identical to the pre-H3 behaviour.

## Evidence
- `python3 hooks/scripts/doctrine.py --selftest` → **OK**, exit 0. Cases: subagent (`agent_id`)
  suppressed; top-level, persona (`agent_type` only, no `agent_id`), malformed stdin, and empty stdin
  all INJECT (fail toward injection); flag-off output byte-identical regardless of `agent_id`; flag-on
  top-level injection byte-identical to flag-off.
- Live end-to-end: `agent_id` payload → empty stdout (suppressed); top-level payload → injects; and
  `SKILL_SUBAGENT_STOP=0` on the same subagent payload → injects (byte-identical old behaviour).
- `py_compile` clean.

## Consequences
- Subagent / dispatched sessions stop receiving the doctrine (flag ON) — no nagging of scoped workers.
- Pairs with the audit-side exclusion (telemetry-dev): both the live nag AND the ledger contamination
  are addressed. The audit exclusion remains the PRIMARY leg (offline over transcripts, no live signal
  needed); this ADR is the live injection-scoping leg the red-team had wrongly ruled out.
- Additive + reversible via one env var.

## Open / to measure
- `agent_id` field stability: it is a common hook-input field per the live docs; if a future Claude
  Code release renames/removes it, `_is_subagent` silently returns False → the doctrine over-injects
  into subagents again (the SAFE failure direction — never suppression). Watch the docs on upgrade.
