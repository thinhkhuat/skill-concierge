# Protocol-gating precision — can the enforcer's own retrieval authorize a lawful skip?

**Scope:** read-only code inspection of `hooks/scripts/enforcer.py`, `hooks/scripts/doctrine.py`,
`hooks/doctrine/skill-first.md`, `skills/skill-usage-audit/`, plus `vendor/skill-search/skill_search/server.py`
and `scripts/embed_server.py` (pulled in because the confirm/refute question in Q1 required tracing
whether the two retrievals are actually the same code path).

## 1. What's available at UserPromptSubmit — and is the per-turn retrieval already "a search"?

**Signals available, zero marginal cost (already computed before any I/O):**
- Raw prompt text + word count — `enforcer.py:420,427` (`MAX_SHORT_WORDS=3` pre-gate, `enforcer.py:65,427-428`)
- Leading `/slash` — exempted outright, `enforcer.py:425-426`
- Explicit skill-refusal regex `_REFUSAL_RE` — `enforcer.py:261-267,432-435`
- `_is_imperative(prompt)` — pure syntactic/lexical veto over the raw string, no embedding needed — `enforcer.py:365-387`

**Signals available after the (already-paid-for) embed+retrieve call:**
- Top-1 cosine score `top = cands[0][2]` — `enforcer.py:468`
- The **full top-K candidate list with individual scores** (`TOP_K=5`, `enforcer.py:65,311-328`) — so the
  top1/top2 **gap** is a zero-cost derived signal, already computed (but only *used* by the default-inert
  P6 dominance collapse, `_apply_dominance`, `enforcer.py:224-233,331-338` — off unless `ENFORCER_DOMINANCE_RATIO` is set)
- `_intent_conversational(vector)` — a genuine **class-margin** signal: mean cosine to a `conversational`
  exemplar set minus mean cosine to an `actionable` exemplar set, over `INTENT_K=10` neighbours each,
  thresholded at `INTENT_MARGIN=0.03` — `enforcer.py:71-84,390-411`. This is **already used to gate**
  offer suppression, not just logged.

**Key insight — CONFIRMED, with one important qualifier.** The per-turn retrieval is not merely
*similar to* `search_skills`, it is the same mechanism against the same index:

- `enforcer.py:305-308` `_embed()` calls the shim at `EMBED_SHIM_PORT` (default 6363).
- `scripts/embed_server.py:48` — that shim literally does `from skill_search.server import embed, EMBED_MODEL`
  — it is not a reimplementation, it **is** `search_skills`'s own embedding function, wrapped in a persistent
  process for latency (`scripts/embed_server.py:5-15`).
- `enforcer.py:311-328` `_retrieve()` issues `query_points_groups` on `COLLECTION` (`claude_skills`) with
  `group_by="name", group_size=1` — byte-for-byte the same query shape as `search_skills`
  (`vendor/skill-search/skill_search/server.py:414-416`), against the same collection.
- The docstring says as much up front: "retrieves the top-k semantic candidates from the **SAME Qdrant
  index skill-search serves**" (`enforcer.py:7-8`).

So mechanically: **yes, the per-turn injection already ran a real semantic search over the full catalogue** —
a low top score is not "we didn't look," it's "we looked and nothing cleared the bar." The only two
differences from a deliberate `search_skills` call are cosmetic: `TOP_K` 5 vs 6 (both env-tunable,
`enforcer.py:65` / `server.py:78`), and the **query text** — the enforcer embeds the raw prompt verbatim,
while the doctrine instructs the agent to hand `search_skills` "the task **in your own words**"
(`skill-first.md:30`), i.e. a deliberately distilled query. For long/rambling/multi-topic prompts an
agent-authored reformulation can retrieve materially better results than raw-prompt embedding — so
"the hook already searched" is a strong but not perfect proxy for "a good search already ran."

**The gap that actually causes the pain is not mechanical, it's epistemic.** Today, when the hook's own
verdict is "no fit" or "conversational," it goes **completely silent** — no mandate, no candidates, nothing:

```python
if not det and top < (_floor_for(cands[0][0]) if cands else GETAWAY_FLOOR):
    _append_offer(sid, "getaway", offered, None, prompt, dropped=_dropped or None)
    return 0                                    # enforcer.py:473-477 — NO _inject() at all
...
if not det and not _is_imperative(prompt) and _intent_conversational(vector):
    _append_offer(sid, "intent_skip", offered, "conversational", prompt, dropped=_dropped or None)
    return 0                                    # enforcer.py:483-485 — NO _inject() at all
```

Compare to the fallback paths (embed down, Qdrant down, refusal), which all still call `_inject(MANDATE)`
before returning (`enforcer.py:433,441,445,453`). So getaway/intent_skip are the ONE case where the hook
already reached a verdict but tells the agent **nothing** — not even the cheap re-assert line. The agent
still carries the full SessionStart doctrine in context ("ACTIVE EVERY TASK TURN... No skip without a
search... Still bound if unsure," `skill-first.md:75-77`), which has no way to know the hook already
cleared this turn — so it re-derives the same verdict the hard way, via a fresh `search_skills` call, on
every one of these turns. **That's the over-firing the user is feeling**: not noise injected by the hook,
but the doctrine's blindness to a decision the hook already made.

The audit tool corroborates that this distinction is invisible downstream too: `audit_skill_usage.py:46-50`
only credits `saw_search` for a literal `search_skills` tool call or the `skill-search` slash
(`_SEARCH_SLUGS = {"skill-search", "skill-concierge-skill-search"}`) — a getaway/intent_skip verdict
leaves no trace an agent (or the auditor) can point to as "a search happened here."

## 2. Concrete gating scheme

Three tiers, reusing signals that already exist — no new inference, no new I/O beyond what's already paid for.

**Tier 0 — mechanical exemptions (unchanged).** Empty / `/slash` / ≤3 words / explicit refusal
(`enforcer.py:425-435`). Zero semantic judgment, zero risk. Leave as-is.

**Tier 1 — MANDATORY-PROTOCOL (today's "offer" path, unchanged).** Fires when `_is_imperative(prompt)`
is true (task-verb opener — **never suppressed by design**, `enforcer.py:369-370`), or top1 clears its
floor and the intent-margin does not lean conversational. Agent commits `USING:`/`SEARCH:` per the
existing doctrine. No change.

**Tier 2 — NEW: AUTHORIZED-SKIP, replacing today's silence.** Fires on exactly the same condition that
today produces silence (`not det and not imperative and (top < floor or intent_conversational)`). Instead
of injecting nothing, inject one line surfacing the verdict the hook already computed, e.g.:

```
SKILL-CHECK: ran over full catalogue (top=0.21 < floor 0.45) — no fit.
SKIPPING: none is pre-authorized this turn; no further search_skills call required.
```

This is **not a new classification** — it is making an existing, already-shipped decision legible. It
cannot make under-gating worse than today, because it fires on the identical predicate that already
silently skips the turn; the only behavior change is that the agent no longer has to re-derive the
verdict via a duplicate tool call.

**Tier 3 — fallback (unchanged).** Embed/Qdrant down, refusal → `MANDATE`-only. The hook could not verify
anything this turn, so full rigor still applies (search or reason it's a no-task turn).

**Explicitly NOT recommended yet:** promoting the top1/top2 raw-score **gap** to a gating signal. It's
already computed for free, but the only place it's wired in (`_apply_dominance`, P6) is default-inert
specifically because "no evidence collapsing improves conversion... fires only ~5%" (`enforcer.py:227-228`).
Shipping a gap-based skip-authorization without the same held-out validation the other two gates got would
reintroduce exactly the failure mode in §3 below.

## 3. Under- vs over-gating — which error is worse, and what does the evidence say about score-based cutoffs

The brief's working hypothesis — "high top-score ⇒ mandatory, low/clear-gap ⇒ lawful skip" — is
**directionally contradicted by this system's own measured data**, per `docs/adr/0009-operator-set-gate-thresholds.md`:

> "Cosine magnitude is *anti-correlated* with adoption here: **taken offers score LOWER than dodged**
> (median top 0.414 vs 0.457 — three independent confirmations)." Raising the score floor 0.40→0.45
> "removes 20 of 91 noise offers (22%) but **3 of 6 adopted offers (50%)**" (ADR-0009).

That ADR was accepted **over the data's objection**, on explicit operator order (ADR-0009, "Decision").
And it isn't isolated: the per-skill calibrated-tau mechanism (`enforcer.py:146-171`) ships but stays
default-OFF specifically because "all 5 current `ok` skills calibrate to tau < 0.45 (one negative), so
arming this LOWERS their bar and ADDS the false-offers ADR-0009 tuned against" (`enforcer.py:150-152`).
Two independent mechanisms in this codebase have already hit the same wall: **raw score magnitude is not
a trustworthy proxy for whether a skill was actually useful.**

Consequence for gating design: a scheme that says "low top score → safe to skip" inherits this same risk
in the other direction — a low score can mean "nothing fits" just as easily as "the right skill, but with
weak lexical/embedding overlap to the raw prompt" (exactly the population ADR-0009 shows gets suppressed
by score-based tightening). **Using raw score magnitude alone as a skip-authorization would risk
under-gating** — the costlier error per this brief.

That's why Tier 2 above is built on the **composite** verdict already in production (getaway floor AND/OR
the intent-margin classifier), not a bare score cutoff:
- The imperative veto is syntactic and Boolean — 100% precision by construction, "never suppressed"
  (`enforcer.py:369-370`), immune to the score-anti-correlation problem entirely.
- The intent-margin gate has an actual validated backtest: "~2% false-suppression on a held-out backtest;
  validated to fire on out-of-distribution prompts" (`enforcer.py:78-80`), and fails toward offering on any
  error, empty class, or missing collection (`enforcer.py:79-80,407-411`).
- The getaway floor alone (bare score < 0.45) is the one leg of Tier 2 with a **documented** adoption cost
  (ADR-0009). Tier 2 doesn't add new risk here — it fires on the same predicate the floor already gates
  today — but it means Tier 2's overall safety is only as good as `GETAWAY_FLOOR`'s current calibration,
  which the record says was set **against** the data.

**Threshold posture that minimizes the worse error:** lean fail-open — keep the imperative veto absolute,
keep the intent-margin as the primary "is this really conversational" arbiter (it's validated), and treat
the raw score floor as the weak leg needing re-validation, not the strong leg to build new gates on. Do
not add a second raw-score-based gate (the top1/top2 gap) on top of an already-suspect first one.

One more open variable that changes the calculus: `skills/skill-usage-audit/SKILL.md:76-81` flags that the
anti-correlation above was measured on the **single-vector** index, and the v0.10.0 multi-vector MAX-pool
upgrade "roughly doubled positive↔negative separation" — so the score↔adoption relationship "must be
re-measured on post-v0.10.0 traffic before reuse." Nobody should trust `GETAWAY_FLOOR=0.45` itself, let
alone a new gap-based cutoff, without that re-measurement.

## 4. Tying gating changes to skill-usage-audit's empirical loop

Two concrete couplings, both already implied by the existing skill:

**(a) The audit's false-SKIPPING metric must learn the new authorization marker, or it will mis-score
Tier 2 as violations.** `audit_skill_usage.py:101-116` computes false-skip as "`SKIPPING` declared with NO
`search_skills` call in the SAME turn," keyed off `_SEARCH_SLUGS` (`audit_skill_usage.py:46-50`), which
only recognizes an explicit `search_skills` tool call or the `skill-search` slash. If Tier 2 ships, a
lawful `SKIPPING: none` following a `SKILL-CHECK:` line has **no representation** in that detector — it
would report as a false skip, inflating the "hardest rule" violation rate for behavior that is, under the
new rule, correct. Any Tier 2 rollout needs a matching patch to the turn-detection logic (recognize the
`SKILL-CHECK:` marker, or better, thread a distinct ledger event the auditor can join on) before the
metric is trustworthy again.

**(b) Any new numeric threshold (a Tier-2 firing rate change, a margin retune, etc.) must go through the
sweep methodology this skill already prescribes, not be guessed:**
- "Sweep candidate floors through the **real enforcer fns** (`_embed`/`_retrieve`/`_is_imperative`/
  `_intent_conversational`) over a labeled corpus — never reimplement the gate" (`SKILL.md:67-68`).
- "**Held-out only**" for the `prompt_intent` collection — it self-scores in-sample (~73% vs ~53%
  held-out) — build a `...heldout` split, evaluate out-of-sample, then delete it (`SKILL.md:69-71`).
- Report **absolute coverage** (right skill surfaced-and-used ÷ applicable turns), not conditional
  offer→take — raising a floor mechanically inflates conversion even as real routing drops
  (`SKILL.md:56-59`).
- **Gate on volume**, "~50–100+ organic offered turns" (`SKILL.md:53`), reusing the same clean-window /
  min-N discipline ADR-0011 already applies to keep-off (`docs/adr/0011-ledger-derived-offer-suppression.md`:
  window ≥ `MIN_WINDOW_OFFERED_TURNS=40`, never suppress on a thin window).
- Drop self/meta (dogfood) sessions before scoring (`SKILL.md:44-48`, `audit_skill_usage.py:37-41,224-232`).

In short: the audit skill already has the exact harness needed to validate Tier 2 empirically before
default-on — it just needs to be pointed at the new marker/tier, not a new tool built from scratch.

## Unresolved questions

1. I did not verify whether `embed_server.py`'s persistent process and `skill_search.server.embed()`'s
   in-process call are numerically identical at the byte level (same process import, so almost certainly
   yes — `embed_server.py:48` imports the function directly, doesn't reimplement it) — but I did not run
   both and diff vectors; flagging in case that matters for a stricter proof.
2. No ledger/transcript data was queried in this pass (code-only, as scoped). The Tier-2 firing rate, its
   overlap with today's `getaway`/`intent_skip` telemetry bands, and the false-SKIPPING delta it would
   produce are all measurable from existing logs but weren't pulled here.
3. The re-measurement `skill-usage-audit` flags as required post-v0.10.0 (score↔adoption correlation on
   the multi-vector index) does not appear to have been done yet based on files read; recommend it precede
   any threshold change, including reconsidering `GETAWAY_FLOOR` itself, not just a new Tier-2 gate.
