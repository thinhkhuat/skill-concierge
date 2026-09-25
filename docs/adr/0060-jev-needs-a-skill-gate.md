# ADR-0060 — The Jev needs-a-skill gate: a fifth AUTHORIZED-SKIP leg

Status: Accepted (2026-09-26)
Relates to: ADR-0009 (getaway floor), ADR-0015 (authorized-skip tier), ADR-0019 (selfref lane), ADR-0054 (harness-message lane, deterministic routes).
Evidence: `MY-WORKBENCH/plans/reports/ask-260926-0050-jev-in-skill-first-gate.md` (analysis, two independent reviews, revision); ledger line 11970 (2026-09-26).

## Context

The per-turn gate decides whether a turn needs the skill procedure (menu, search, quoted ruling) by the
top mpnet cosine against `GETAWAY_FLOOR` (0.45). The enforcer's own tuning note says the cosine "is a
RANK signal, not absolute confidence", and it has drifted: the note calibrated real tasks at ~0.22-0.40
(2026-06-26); on 2026-09-26 the turn "propagate/inform other sessions of your revision to the RULES.md"
was offered eight irrelevant skills at 0.601-0.644 (ledger line 11970). The floor no longer separates
conversation from work, and each false offer costs the agent a mandated `search_skills` round trip and a
quoted ruling.

TypeSafe's Jev returns a calibrated yes/no probability for a question over short text. Owner decision
(Thinh, 2026-09-26): add it at the very start of the gate, live, then smoke-test. RULES [72] names Jev as
its sole metered exception.

## Decision

1. **One Noul call, after every no-I/O lane and before embed** (`_jev_needs_skill`). State = the prompt
   (first 4 000 chars). Question: should the agent load a specialized playbook rather than handle the
   request with its built-in abilities; criteria define `true` (a substantial task in a playbook's domain,
   any language) and `false` (conversation, a question about the agent's prior answer, an acknowledgement,
   a go-ahead, a short direct action, a request whose method the user dictated).
2. **p < `ENFORCER_JEV_SKIP_BELOW` (0.25) → authorized skip**: ledger band `jev_skip`, fallback
   `jev_no_skill`, a fifth `SKILL-CHECK:` leg whose locked signature is **"Jev needs-a-skill gate"**
   (audit `_AUTHORIZED_SIGNATURES`), chain hint allowed. Any other outcome falls through to today's path.
3. **Fail open, lopsided by design.** A wrong YES is today's behaviour; only a wrong NO costs. No key, a
   timeout (`ENFORCER_JEV_TIMEOUT`, 1.2 s), an HTTP error, or a malformed/out-of-range answer → normal
   routing. A named deterministic route never asks Jev.
4. **Every ledger row after an attempted call carries `jev`**: `{"p", "ms"}`, or `{"err", "ms"}` when the
   call failed. No call (gate off, no key, or a named route) → no `jev` field.
5. **Model pinned** to `jev-1.13.0` (`ENFORCER_JEV_MODEL`); `jev-latest` moves with each release and
   would shift the threshold silently.

The vendor cookbook's three generic gate questions (acts on user systems / documented procedure / prose
suffices) were tried first and rejected: they measure "needs tools", so the RULES.md broadcast turn
scored 0.71. The tailored question, tuned on 22 labelled EN+VN prompts, scored every NO at ≤ 0.12 and
every YES at ≥ 0.45; the 0.25 floor sits in that gap. Measured latency from the reference Mac:
0.58-0.88 s per call, ~530 input tokens (about $0.00002 per turn).

## Consequences

- Conversation, go-aheads and questions about the agent's own output stop paying the search round trip.
- Every qualifying prompt now waits for one network call (~0.65 s typical, 1.2 s cap); worst-case hook
  time rises from ~1.75 s to ~2.95 s, inside the 5 s budget.
- Every qualifying prompt's text (up to 4 000 chars) is sent to `api.typesafe.ai`.
- The 22-prompt tuning set is also the only evidence for the threshold. The epoch-watch v0.50.0 section
  tracks the false-NO rate on real traffic; that, not the tuning set, decides the threshold.

## Revert

`ENFORCER_JEV_GATE=0` restores the four-leg ladder byte-identically (no network call, no `jev` field).
