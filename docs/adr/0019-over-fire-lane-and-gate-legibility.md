# ADR-0019 — Self-referential over-fire lane (H5)

Status: Accepted (2026-07-06)
Relates to: ADR-0015 (AUTHORIZED-SKIP tier — this ADDS a 3rd lane to its 2 silent legs), ADR-0009/0010
(getaway floor + short-word pre-gate — the sibling silent pre-gates). Plan:
`plans/260706-1315-superpowers-anti-dodge-integration/` (Phase 5). Design arc + accepted caveats:
`docs/anti-dodge-integration-v0.14.md`. Reference (adapted, not copied): superpowers v6.1.1 — MIT.

## Context
The SKILL-FIRST gate is tuned hard against **under**-firing (skipping a skill too easily) and has no
symmetric guard against **over**-firing. Live dogfood this session surfaced the gap: two near-identical
"explain the next item" turns got opposite verdicts, one of which **forced a pointless `search_skills`**
on a turn that plainly needed none. The severity model prices a needless search as "cheap" — but every
ritual search on a trivial turn erodes the agent's trust in the gate exactly where real work needs it.

The narrow class that over-fires: a user prompt whose whole payload is a request to explain/rephrase the
assistant's OWN immediately-prior message — no external task, no skill applies.

Red-Team (F1/F2, Critical) fixed two traps before build: (a) the enforcer fires on `UserPromptSubmit`
and sees ONLY the user prompt (`enforcer.py:463`), never the agent's self-narration — so the detector
must key on a **2nd-person** request operating on the assistant's prior message, not a 1st-person
"my output" frame; (b) `_is_imperative` checks only the LEADING token (`:408-430`), so "explain your
answer **and implement** the migration" would slip a lead-token check and an outright skip would be
scored *authorized* — invisible to H1's dodge measurement.

## Decision
- **Flag.** `ENFORCER_SELFREF_SKIP` (default-ON, `os.environ.get(...,"1") != "0"`), one-var revert —
  mirrors `ENFORCER_AUTHORIZED_SKIP` / `SKILL_BODY_TRIGGERS`.
- **Detector (`enforcer.py:_is_selfref`).** Three gates, ALL required, NARROW by construction:
  1. **Positive anchor** (`_SELFREF_RE`): opens (after fillers) with a recap verb
     (explain/rephrase/reword/restate/clarify/expand/elaborate/summari[sz]e/recap/unpack/simplify)
     on a 2nd-person / deictic object (`your` / `that` / `this` / `the {above,last,previous,prior}` /
     `what you`). The recap verbs are deliberately NONE of `_IMPERATIVE_VERBS`, so gate 2 never
     self-vetoes the opener. A generic "explain how DNS works" has no such object → falls through.
  2. **Whole-prompt task-verb veto** (Red-Team F1 fix): ANY `_IMPERATIVE_VERBS ∪ _VN_VERBS` token
     (or VN bigram) ANYWHERE in the prompt → NOT selfref. Vetoes "…and implement the migration".
  3. **Tail veto** (`_SELFREF_TAIL_RE`): a new-clause connector (`and/then/by/into/using`, `as a/an`,
     `so that`, `to a/an/the`, `with a/an/the`) → an external object → NOT a pure recap. Catches the
     no-lexicon-verb bypasses ("…as a working config", "…by writing the code").
  Fails toward NOT firing (→ normal routing): a missed selfref costs a harmless forced search; a
  false-fire would bless real work — the exact dodge the doctrine fights.
- **Placement.** A no-I/O pre-gate in `main()` after the refusal check, before the embed: detect →
  `_append_offer(sid, "selfref_skip", …)` → `_authorized_skip_inject("selfref")` → `return 0`.
- **3rd message + LOCKED signature.** `SELFREF_SKIP_MSG` carries the prose-unlikely signature phrase
  **`self-referential recap lane`**. This is a cross-file contract: the audit
  (`audit_skill_usage.py:176-178`, telemetry-dev) matches this exact substring to count the lane as an
  authorized-skip, NOT a false-skip. The phrase MUST NOT appear in the `skill-first.md` doctrine table
  (ADR-0022) — a collision would miscount real dodges as authorized, masking what H1 measures.
- **Legibility deferred [Red-Team F12].** Rewording the existing `GETAWAY_SKIP_MSG` / `INTENT_SKIP_MSG`
  risks breaking the audit's substring anchors; it is a separate hypothesis. This ADR ships the lane only.

## Evidence
- `python3 hooks/scripts/enforcer.py --selftest` → **OK**, exit 0. Authorized-skip tier now asserts
  **3** injects on / silent-off; selfref lane **6 fire / 6 off**. Parity assertion: the signature is
  present in the selfref message and ABSENT from the getaway/intent messages.
- Bypass fixtures proven to route normally (must-NOT-fire): "explain your answer and implement the
  migration", "rephrase your last answer as a working config", "clarify your point by writing the actual
  code", plus real-object cases ("explain how the auth middleware works", "rephrase the readme into plain
  english").
- End-to-end stdin: flag ON on "explain your last answer again for me" → emits `SKILL-CHECK:` +
  `self-referential recap lane`; `ENFORCER_SELFREF_SKIP=0` → routes normally, no signature.

## Consequences
- Trivially self-referential recap turns stop being forced into a ritual `search_skills`; the gate's
  over-fire failure mode gains the symmetric guard it lacked.
- The audit gains a 3rd authorized-skip anchor to exclude from the false-skip denominator (telemetry-dev
  task; dispatched after this signature lands).
- Additive + reversible: `ENFORCER_SELFREF_SKIP=0` restores the exact 2-lane behaviour.

## Open / to measure
- False-fire rate on live traffic: does the narrow detector ever bless a real-work turn? (The
  fail-toward-routing bias + must-NOT-fire fixtures mitigate; watch the ledger `selfref_skip` band.)
- Recall: how many genuine over-fire turns does the detector miss (verb/deictic coverage)? A miss is
  low-cost (a harmless forced search), so precision was chosen over recall by design.
