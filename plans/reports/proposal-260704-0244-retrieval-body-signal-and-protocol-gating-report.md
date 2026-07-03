# Proposal — Raising skill-concierge's usefulness rate: body-level retrieval signal + protocol-gating precision

**Date:** 2026-07-04 · **Method:** 3× `claude-sonnet-5` `ck:team` research fan-out
(ground-truth / body-indexing / gating), synthesized by lead. **Source reports** linked at bottom.

**Validation:** Opus-validated 2026-07-04 (`opus-validation-260704-0320-retrieval-body-signal-and-protocol-gating-proposal.md`).
One blocking evidence issue — a false "enrich overlay is live" current-state claim, inherited from a
source report — was found and is corrected below (Layer 3). All other load-bearing claims and every
recommendation verified against primary sources. Of 5 advisories, 2 applied (softened the intent-margin
"buys nothing" and the imperative-veto "100% precision" wordings).

## Executive summary

Two asks: **(1)** let the in-session agent know which prompts MUST run the protocol vs. which can
skip WITHOUT searching; **(2)** get the "when/how/which to use" signal that lives in skill BODIES into
retrieval, because description-only search feels too thin. Both are worth doing. The fan-out corrected
the framing on **both** before any build:

- **The body is already embedded** — so the fix is not "add the body to the vector store." It's to
  stop *truncating and blending* it, and instead route the body's decision-sections into the
  retrieval mechanism this repo has already **measured as 2.2× better**.
- **The over-firing is not the retrieval** — the enforcer hook already runs a real semantic search
  every turn. The pain is that when its verdict is "no fit," it injects **nothing**, so the agent —
  still bound by the standing doctrine — redoes the search to reach the identical answer.

Recommended order: **gating fix first** — specifically its intent-margin leg (the lowest-risk change,
and it directly kills the over-firing the user feels); the score-floor leg is gated behind a threshold
re-measurement. **Body-trigger extraction second** (higher value, but needs A/B validation). Both are
extensions of mechanisms already in production — not new subsystems.

---

## Premise correction — ground truth of what's indexed today (researcher-a)

The index is built in layers — **two active, one legacy/inert** — not description-only:

1. **Base point** = `embed(name + description[+ when_to_use] + body[:4000 chars])` — one blended 768-d
   vector (`skills_discovery.py:79-91`, `server.py:270-272`). The body **is** embedded — but it is
   discarded from the Qdrant payload afterward (`server.py:354-356`).
2. **Trigger layer** (multi-vector, default ON) — intent phrases split from the **description only**,
   each embedded as its own point, MAX-pooled at query time (`server.py:252-267, 357-362`). This is
   the proven recall lever (ADR-0012: rank-1 11.3%→25.0%, **2.2×**).
3. **Enrich overlay — legacy, superseded, inert under the default index** (`enrich_index.py`). It once
   MEAN-blended trigger vectors into the base vector, but is gated **off** whenever multi-vector is on
   (the default): `setup.sh:76-78` runs `--reapply` only under `SKILL_MULTIVECTOR=0` — the comment says
   the legacy overlay "must NOT run on a multi-vector index"; `doctor.py:499-503` skips it; and
   `doctor.py:306-308` reports zero enriched points as **OK** ("no overlay in use"), not a drift to fix.
   The live index confirms it — **0 enriched points**; base vectors are pure `embed(_skill_text)`, not
   blended (ADR-0012:50-51 superseded this overlay). *(An earlier draft wrongly called this overlay
   "live" — a false current-state claim inherited from researcher-a's Q5; caught by Opus validation and
   corrected here.)*

Two facts that reshape the whole question:

- **The 4000-char cap is a red herring; the real cap is 384 *tokens*.** The deployed embedder is
  `paraphrase-multilingual-mpnet-base-v2` (768-d, set in `.mcp.json`, not the code's bge-small
  default), which truncates at **384 input tokens** (~1,500–2,000 chars). Most bodies are therefore
  **already silently truncated mid-thought** before anything reaches the model (researcher-b, via
  fastembed `list_supported_models`). The body isn't "missing" — it's being cut off and averaged away.
- **`get_skill` already does full progressive disclosure** — it reads the complete, uncapped
  `SKILL.md` from disk on demand (`server.py:439-457`). So "fetch the body when needed" already exists.

**So the honest answer to "should we extend the vector store to hold the body too?" is: it already
does, nominally — and that's the wrong representation.** Don't pour more body text into the one blended
base vector. That repeats a mechanism this repo already disproved (see below).

## The through-line worth naming: the substrate measures TOPIC, not USEFULNESS

Both ideas run into the same wall, and it's worth stating once. Per `journal-2026-06-29 (v0.6.0)`:
*"the substrate measures topic, not usefulness/intent… cosine score did not predict adoption,"* and
ADR-0009: cosine is **anti-correlated** with adoption here — *taken* offers score **lower** than
dodged (median 0.414 vs 0.457). Consequences:

- For **body indexing**: adding more topical text won't fix an intent-disambiguation problem, and
  blending it dilutes the one distinctive phrase (ADR-0012 measured MEAN-centroid as *worse* than
  MAX-pool over separate points). The lever is **representational** (separate points from
  decision-labeled sections), not **volumetric** (more text in one vector).
- For **gating**: you cannot trust raw score magnitude to decide "mandatory vs. skip." The win is
  making the hook's *existing composite verdict* legible — not inventing a new score threshold.

---

## Idea 2 — Body-level signal: extract the body's triggers, don't dump the body

Winning option (researcher-b, Option 4, scored 20/25 and the only one that fixes the stated recall
miss on both retrieval paths):

**Extract the body's own "when to use" / "Triggers:" / "Use when:" sections and feed them through the
SAME MAX-pool trigger pipeline that already measured 2.2×.** Mirror `_split_phrases` / `_LABEL_RE`
(`server.py:245-267`), cap like description triggers (`_TRIG_MAX=12`), emit separate trigger points.

Why this and not the alternatives:

- **Fixes the actual miss** — body-only decision signal becomes its own queryable point, retrievable
  in both the enforcer-hook (≲300ms) path AND the MCP `search_skills` path.
- **No dilution** — separate points, not a blended vector (avoids the ADR-0012 trap).
- **No truncation** — short extracted phrases stay well under the 384-token ceiling that a full-body
  chunk would hit.
- **Reuses proven, budget-safe infra** — same stable point-id scheme, incremental-reindex safety,
  content-hash change detection.

Ship **alongside** it (free, orthogonal): **Option 3 — nudge the agent to call `get_skill(name)` when
a candidate's fit is unclear** from the lossy 96-char description slice shown in the offer. MCP-path
only; a complement, not a substitute (a body-only skill still has to *surface* first — that's what
Option 4 fixes).

**Reserve:** Option 1 (full-body chunking) — hold; gate on post-Option-4 data. Real dilution risk +
2–4× point-count growth (index is already ~2,312 points).
**Reject:** Option 2 (body rerank) — can't fit the hook's latency budget (ADR-0008), and doesn't fix a
recall miss. Option 5 (revive `enrich_index.py`'s MEAN-centroid) — the exact mechanism ADR-0012
superseded.

**Cheap orthogonal win:** only **101 of 688 skills (~15%)** set the `when_to_use` frontmatter field
that already feeds the embedded text. Encouraging adoption is a skill-authoring/docs lever — no engine
change — and should be tracked separately.

**Validate the ADR-0012 way:** shadow A/B via `scripts/multivector_experiment.py` before default-on,
not a blind ship. Also fix the char→token cap honestly regardless — the current 4000-char cap misleads.

---

## Idea 1 — Protocol gating: surface the verdict the hook already made

### Governing principle: intent-classified skip, asymmetric error cost ("the library doctrine")

A skip is an **intent classification made with reasoning** — *trivial errand* vs. *real work*,
*unambiguous* vs. *ambiguous* — **not** a score threshold. The two errors are not symmetric:

- **Over-gating** (a needless search on a genuinely trivial turn) = cheap noise, a few wasted tokens.
- **Under-gating** (declaring "nothing fits" on non-trivial/ambiguous work while a 500+ and-growing
  catalogue *and* the `find-skills` meta-skill sit unused) = **slop of the highest severity** — the
  lazy student who glances at the card catalogue and decides to write the thesis alone.

So the gate must **fail toward search/USING**, and the **burden of proof is on SKIP**: only a
positively-reasoned "trivial / unambiguous" earns a no-search skip. Anything classified real-or-ambiguous
is mandatory-protocol, and a bare "nothing cleared the floor" must **not** authorize a skip — it
**escalates to `find-skills`** (the reasoning-driven meta-lookup), never a self-declared "I'll do it
myself." This is the invariant the whole gating design serves; the mechanics below exist to enforce it,
not to make skipping cheaper in general. It is also *why* the score-floor leg is quarantined: raw score
is topic-similarity, not intent, so it cannot certify "trivial" — only the intent classifier can.

**Root cause of over-firing (researcher-c):** the enforcer's per-turn retrieval *is* the same call as
`search_skills` — `embed_server.py:48` imports `skill_search.server.embed` directly; same Qdrant
collection, same query shape (`enforcer.py:311-328` vs `server.py:414-416`). So a low-scoring per-turn
result set already **is** a real search — "the hook looked and nothing cleared the bar."

The problem is **epistemic, not mechanical**: when the verdict is "no fit" (getaway) or
"conversational" (intent_skip), the hook injects **nothing** (`enforcer.py:473-477, 483-485`) — unlike
every other path, which still injects a mandate. The agent, still carrying the SessionStart doctrine
("no skip without a search"), has no way to know the hook already cleared the turn — so it re-runs
`search_skills` to re-derive the same verdict. **That's the over-firing** — not hook noise, but the
doctrine's blindness to a decision the hook already made.

**Proposed fix — a 3rd tier, `AUTHORIZED-SKIP`, replacing today's silence:** on the *identical
predicate* that already skips silently, inject one line surfacing the verdict, e.g.:

```
SKILL-CHECK: ran full-catalogue retrieval (top=0.21 < floor 0.45) — no fit.
SKIPPING: none is pre-authorized this turn; no further search_skills call required.
```

This is not a new classifier — it surfaces a decision the hook already ships. But its safety is **not
uniform across the two legs** of that predicate, and a flat "it can't make things worse" is too strong:

- **Intent-margin leg — safe, do first.** When the skip is driven by the intent-margin classifier
  (validated, ~2% false-suppression, `enforcer.py:78-80`), surfacing it is genuinely low-risk: the
  verdict is trustworthy and re-deriving it buys little — only the residual ~2% of false-suppressions
  could recover via a reformulated re-search, an order of magnitude below the getaway leg's exposure.
- **Getaway-floor leg — NOT safe as-is, gate it.** When the skip is driven by bare `top < floor`, two
  problems bite. (a) That is the anti-correlation band: adopted offers cluster *below* the floor
  (median 0.414 vs floor 0.45; raising 0.40→0.45 killed **50% of adopted offers**, ADR-0009), so
  pre-authorizing a skip there disproportionately discards turns where a fitting skill actually exists.
  (b) Today's silent skip still leaves the agent doctrine-bound to re-search — and that re-search uses
  a **reformulated** query ("in your own words," `skill-first.md:30`) that can retrieve better than the
  hook's raw-prompt embedding. A "no further search required" line **deletes that recovery path**. So
  for this leg it is *not* merely removing a duplicate call.

**Therefore split the rollout:** ship the intent-margin leg first (low-risk); gate the getaway-floor
leg behind the post-v0.10.0 floor re-measurement (prereq #4) — or require intent-margin agreement
before it fires.

**Guardrails (non-negotiable):**

- **Split the two `AUTHORIZED-SKIP` legs** — the intent-margin leg is validated and safe to ship; the
  getaway-floor leg fires where real adoptions live (median 0.414 < floor 0.45) and deletes the
  reformulated-query recovery path, so it must be gated behind the floor re-measurement (#4), not
  shipped default-on alongside the intent-margin leg.
- **Ambiguous / non-trivial + nothing clears the floor ⇒ escalate to `find-skills`, never skip.** A bare
  "no fit" is not a license to self-serve; only the intent-margin *conversational* verdict (a genuinely
  trivial / non-task turn) may authorize a skip. This keeps the burden of proof on SKIP.
- **Do NOT gate on raw score magnitude** — ADR-0009 shows it's backwards. Anchor on the two validated
  signals: the **imperative veto** (syntactic, "never suppressed" — high precision on the open, low
  recall by design, `enforcer.py:368-370`) and the **intent-margin classifier** (~2% false-suppression, held-out
  validated, `enforcer.py:78-80`). Do NOT add the top1/top2 gap as a new gate.
- **Patch the audit detector in the same change** — `audit_skill_usage.py:101-116` scores false-SKIP
  as "SKIPPING with no `search_skills` in the same turn." A lawful `AUTHORIZED-SKIP` would be
  mis-scored as a violation unless the detector learns the new marker (or a distinct ledger event).
- **Tune before default-on** via the audit skill's existing harness: sweep through the real enforcer
  fns over a labeled corpus, held-out only, absolute-coverage metric, volume-gated (~50–100+ organic
  offered turns).
- **Re-measure score↔adoption on post-v0.10.0 (multi-vector) traffic** before touching
  `GETAWAY_FLOOR` — the anti-correlation was measured on the single-vector index and is stale.

---

## Prioritized roadmap

| # | Change | Value | Risk | Notes |
|---|--------|-------|------|-------|
| 1a | **Gating: `AUTHORIZED-SKIP` — intent-margin leg + audit-detector patch** | High (kills the bulk of over-firing) | **Low** — validated classifier (~2% false-suppression) | Do first. |
| 1b | **Gating: `AUTHORIZED-SKIP` — getaway-floor leg** | Medium | **Medium** — fires in the anti-correlation band; deletes the reformulated-query recovery | Gate behind #4, or require intent-margin agreement before it fires. |
| 2 | **Body: Option 4 extractor + shadow A/B; fix char→token cap** | High (the "buried info" fix) | Medium — needs validation, no dilution by design | Do second. Don't blind-ship. |
| 3 | **Complements: `get_skill` nudge + `when_to_use` adoption push** | Medium | Low | Free; ship alongside #2. |
| 4 | **Prereq: re-measure score↔adoption on post-v0.10.0 traffic** | Enabling | Low | Gates any threshold work, incl. `GETAWAY_FLOOR`. |
| — | Reserve: full-body chunking (Option 1) | — | — | Only if #2 leaves measurable body-only misses. |
| — | Reject: body rerank (Option 2), MEAN-centroid revival (Option 5) | — | — | Evidenced against. |

## Risks & guardrails (summary)

- Raw cosine score is not a usefulness proxy here — do not build new gates on it (ADR-0009).
- Blending more into the base vector repeats the disproven MEAN-centroid (ADR-0012).
- Any gate/threshold change must pass the audit skill's held-out, volume-gated sweep before default-on.
- The audit tool must learn any new marker or it mis-scores the new correct behavior as a violation.

## Validation plan

- **Gating:** implement `AUTHORIZED-SKIP` behind a flag; run the audit sweep on ≥50–100 organic
  offered turns (self/meta sessions dropped); confirm false-SKIPPING drops and coverage holds; then
  default-on.
- **Body:** build a small labeled set of bodies with clean "when to use" sections; shadow A/B via
  `multivector_experiment.py`; require a rank-1/separation gain before default-on.

## Unresolved questions

- No labeled corpus yet for body-derived trigger-extraction quality (how many bodies have a cleanly
  labeled section vs. free prose) — needed to estimate real coverage gain, not just point count.
- The 384-token figure came from fastembed metadata, not the model's SBERT config — worth a second
  source if it becomes load-bearing for an implementation PR.
- The post-v0.10.0 score↔adoption re-measurement appears not yet done — it gates any threshold change.
- Whether Option 4's extractor should skip bodies that already duplicate `when_to_use` frontmatter
  (avoid double-counting) — an implementer decision.

## Source reports

- `plans/reports/researcher-a-260704-0236-current-index-ground-truth.md`
- `plans/reports/researcher-b-260704-0239-body-level-indexing-design-options-report.md`
- `plans/reports/researcher-c-260704-0236-protocol-gating-precision.md`
