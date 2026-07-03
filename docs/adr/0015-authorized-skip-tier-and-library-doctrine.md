# ADR-0015 — AUTHORIZED-SKIP tier + the library doctrine

Status: Accepted (2026-07-04)
Relates to: ADR-0009 (operator gate floor / score↔adoption anti-correlation), ADR-0010 (word floor),
ADR-0002 (semantic which+whether). Source: `plans/reports/proposal-260704-0244-retrieval-body-signal-and-protocol-gating-report.md`
(Opus-validated: `plans/reports/opus-validation-260704-0320-…`). Implementation plan: `plans/260704-0415-usefulness-rate-upgrades/`.

## Context
The enforcer runs a real semantic retrieval over the full catalogue on **every** prompt — the same
`embed()` + `query/groups` call `search_skills` uses (`hooks/scripts/enforcer.py` `_embed`/`_retrieve`;
the shim imports `skill_search.server.embed` directly). But on its two "no offer" verdicts it returned
`0` with **no `additionalContext` at all**:
- **getaway** — `top < floor` (nothing cleared the bar), `enforcer.py` getaway path.
- **intent_skip** — the actionability class-margin judged the turn conversational.

Every other exit (embed down, Qdrant down, refusal) still injects `MANDATE`. Only these two were silent.
Consequence: the agent, bound by the SessionStart SKILL-FIRST doctrine ("no skip without a search"), had
no signal the hook already looked and cleared the turn — so it re-ran `search_skills` to re-derive the same
verdict. The over-firing the operator felt was not hook noise; it was the doctrine's blindness to a decision
the hook already made.

## Decision
Two coupled changes plus an audit fix:

- **AUTHORIZED-SKIP tier (`hooks/scripts/enforcer.py`).** Replace the silence on both legs with a one-line
  authorization, gated by `ENFORCER_AUTHORIZED_SKIP` (default ON; `=0` restores prior silence). Each line
  begins with the literal marker `SKILL-CHECK:` (`AUTHORIZED_SKIP_MARKER`). The injects are try/except-wrapped
  — the hook stays additive and fail-silent. `_append_offer` telemetry is unchanged.
  - **getaway** message keeps the **burden of proof on SKIP**: it authorizes `SKIPPING: none` ONLY for a
    genuinely trivial/non-task turn; for real-or-ambiguous work it tells the agent to escalate to
    `find-skills`, and nudges `get_skill(<name>)` when a candidate's fit is unclear.
  - **intent_skip** message states the intent-margin classifier judged the turn conversational and
    pre-authorizes the skip.
- **Library doctrine (`hooks/doctrine/skill-first.md`).** A skip is a reasoning-based intent classification,
  not a score threshold. Costs are asymmetric: a needless search is cheap; declaring "nothing fits" on real
  work while a 500+ catalogue and `find-skills` sit unused is the top-severity failure. Burden of proof on
  SKIP; real-or-ambiguous + no-fit escalates to `find-skills`. Explicitly tied to the `SKILL-CHECK:` marker.
- **Audit detector (`skills/skill-usage-audit/scripts/audit_skill_usage.py`).** A turn carrying `SKILL-CHECK:`
  is a lawful hook-authorized skip — excluded from false-SKIPPING, tallied separately as `authorized_skip`.
  Same marker literal (cross-file contract). SKILL.md metric definition updated.

## The all-ON override (operator decision, recorded)
The proposal recommended shipping the **intent-margin (getaway=conversational) leg default-ON** but the
**getaway-floor leg default-OFF**, gated behind a post-v0.10.0 score re-measurement — because ADR-0009 shows
cosine is anti-correlated with adoption (taken offers median 0.414 < dodged 0.457; a bare score-floor skip
fires exactly where real-but-low-scoring work lives, risking under-gating). **The operator explicitly
overrode this and directed BOTH legs ON now** (decision log: `plans/260704-0415-usefulness-rate-upgrades/decisions-audit-log.md` D1).
Honored. Mitigations: (a) the getaway message embeds the `find-skills` escalation so the feature firing is
not a blind skip; (b) the ON-default `ENFORCER_AUTHORIZED_SKIP` kill-switch reverts in one env var; (c) the
audit's `authorized_skip` vs `false_skip` split makes any regression measurable.

## Evidence
- `enforcer.py --selftest`: both legs inject the marker + required content when ON, stay silent when
  `ENFORCER_AUTHORIZED_SKIP=0`. Passes ON and OFF.
- `audit_skill_usage.py --selftest`: `SKILL-CHECK:`-then-`SKIPPING` → 0 false-skip, 1 authorized_skip; all
  prior cases pass.
- No live offered-turn adoption A/B yet — that needs a post-deploy traffic window (see Open).

## Consequences
- On hook-cleared turns the agent no longer re-runs `search_skills` to re-derive an existing verdict.
- The false-SKIPPING metric stays honest (authorized skips no longer inflate the hardest-rule violation rate).
- The getaway-floor leg ships ON against the data-backed caution — accepted per operator override; the
  escalation text + kill-switch + audit metric are the guardrails.

## Open / to measure
- **Prerequisite still open:** re-measure the score↔adoption correlation on post-v0.10.0 (multi-vector)
  traffic before trusting `GETAWAY_FLOOR` or judging the getaway leg — the ADR-0009 numbers are from the
  single-vector index (flagged in `skills/skill-usage-audit/SKILL.md`).
- Watch `authorized_skip` vs `false_skip` in `audit_skill_usage.py` over the first ~50–100 organic offered
  turns; if authorized-skips correlate with missed real work, flip `ENFORCER_AUTHORIZED_SKIP=0` for the
  getaway leg (or split the flag per leg).
