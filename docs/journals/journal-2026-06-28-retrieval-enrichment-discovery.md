# Journal — 2026-06-28 · skill-concierge: the dodge is (substantially) a retrieval problem

## The arc
Started as a briefing on recent skill-concierge dev, became a chain of findings that
reframed the project. The plugin's thesis was *"retrieval works; compliance is the
bottleneck"* (offered-turn dodge ≈ 92%). By session end the evidence says the opposite
for ~⅔ of skills: **retrieval doesn't discriminate, and that's a large part of the dodge.**

The chain:
1. **Negation guard (Phase A1).** Verified empirically that mpnet cosine does NOT encode
   negation (cos(affirm,neg)=0.65–0.87). But a broad bm25-style "any negation → suppress"
   rule wrongly suppressed 3/4 bug-report prompts. Shipped a *narrow* guard anchored on
   negation + an invocation-meta verb only. Lesson: the borrowed idea (bm25 negation) was
   right in spirit, wrong at our prompt distribution — full task prompts carry negations
   that describe bugs, not refuse skills.
2. **Per-skill calibration (Phase D) backfired usefully.** Built a calibrator scoring each
   corpus prompt by its real cosine to the skill's indexed vector. F1 came out 0.83–1.0 for
   all 14 skills — a trap: with 12 pos vs 5 neg a catch-all τ scores F1=0.83 while
   discriminating nothing. Switched the status metric to **separation (pos_mean − neg_mean)**,
   which exposed the real picture: 5 ok, 5 weak, **4 inverted** (negatives out-score
   positives). The threshold was never the lever.
3. **Root cause = index content.** The engine embeds `name + description + body[:4000]`;
   for generic dev skills that text is a semantic grab-bag ("test failures, CI/CD, database
   diagnostics" all name-drop sibling domains). Enriching the indexed vector with trigger
   phrases (centroid of separately-embedded utterances) flipped all 4 inverted skills
   positive offline (14/14 improved, 0 regressions, held-out).
4. **Shadow PoC.** Built `claude_skills_shadow` (full 495, 14 enriched), tested held-out
   prompts in real 495-way retrieval: correct-skill rank-1 **12% → 90%**, clears-floor
   37% → 100%. This is the headline result.

## Decisions worth remembering
- **Separation, not F1, is the honest calibration signal** when pos/neg counts are skewed.
- **Overlay, not vendored edit.** Enrichment ships as a non-vendored vector overlay
  (recompute centroid, vector-only update) to keep `vendor/skill-search` pristine and
  reversible — vendored indexing edit only if overlay reindex cost forces it.
- **Per-skill *measured* trigger source.** Step-0 refuted the red-team's "prose source is
  dead (text already embedded)": prose-*phrase* enrichment (split→embed→centroid) flips
  inverted skills positive — the mechanism extracts intent the one-blob embedding doesn't.
  But utterances are the ceiling, and prose can regress a skill (vn-author). So the source
  is chosen per-skill by the separation harness, never one global recipe.

## Methodology that paid off
- **Held-out everywhere.** Every separation/recall claim used held-out positives; the one
  same-distribution worry was then refuted by an adversarial reviewer's out-of-style prompts
  (6%→88%).
- **Adversarial red-team materially improved the plan.** Two reviewers (primary-source +
  live probes) turned Phase 1 from NO-GO into a staged, precision-gated rollout — caught a
  payload-wiping `upsert`, an unmeasured 494-way precision risk (57% of cross-domain prompts
  spuriously fired an enriched skill in the 14-shadow), an embed-parity dependency, and the
  rank≠offer floor interaction.
- **The step-0 gate exists to test the reviewer too.** It refuted the red-team's strongest
  claim by measurement rather than deferring to authority.

## Bugs / traps caught
- Broad negation guard over-suppresses (fixed: narrow).
- F1-only status hides catch-all degeneracy (fixed: separation gate).
- 14-of-495 shadow structurally inflates recall + understates false-positives (fixed in
  plan: enrich all 495 in shadow before any number).
- Qdrant `upsert` clears payload → dark skills (planned fix: vector-only update).

## Open thread
The retrieval fix (enrichment) is proven on samples but not rolled out. Whether fixing
retrieval actually lowers the live dodge still needs a clean-window measurement (the ledger
is contaminated by meta-sessions about skill-concierge itself). Phases B (freshness),
analyze.py (C1 instrument), and the negation/presentation enforcer changes all shipped and
are verified; Phases 2 (doctrine re-injection), 3 (per-skill τ), and the Phase-1 build-out
remain.
