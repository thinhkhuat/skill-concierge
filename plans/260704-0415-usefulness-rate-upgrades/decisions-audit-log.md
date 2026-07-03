# Decisions Audit Log — usefulness-rate upgrades (260704-0415)

Standalone, append-only record of every autonomous fork decision taken during this run, per the user's
explicit instruction: *"If you were about to face a genuine fork — or more — make the well-informed,
factually-grounded decisions and record every of them in a standalone doc clearly for me to later audit."*

Format per entry: **Decision · Fork · Grounds · Risk · Reversal.**

---

## D0 — Goal binding (`/goal` substitution)

- **Fork:** the user ordered "invoke `/goal`", but `/goal` is a UI command that cannot be called via the
  Skill tool (runtime returned: *"goal is a UI command, not a skill. Ask the user to run /goal themselves"*).
  Halt-and-ask vs. proceed with a durable substitute.
- **Decision:** proceed. This plan + this log bind me to the same completion criteria a `/goal` would; the
  EFFORT standing order already forbids stopping before done-and-proven. User may run `/goal` themselves for
  the UI-tracked version.
- **Grounds:** halting over an un-callable UI command would defeat the user's primary directive ("complete
  autonomously"). Not a preference fork — a physical tool limit.
- **Risk / Reversal:** none material; user can invoke `/goal` anytime.

## D1 — Rollout posture: EVERYTHING default-ON (user override of the recommendation)

- **Fork:** proposal (Opus-validated) recommends shipping the **getaway-floor AUTHORIZED-SKIP leg** and
  **Option-4 body-trigger retrieval** as **default-OFF**, gated behind a post-v0.10.0 score re-measurement /
  shadow-A-B, because ADR-0009 shows cosine score is anti-correlated with adoption (taken 0.414 < dodged
  0.457) — a bare score-floor skip risks under-gating real work.
- **Decision:** ship **EVERYTHING default-ON**, per the user's explicit final lock-in ("#2, EVERYTHING as ON
  by default, NOW"). This is a **User Decision** and is honored, not silently reversed.
- **Grounds:** the user was shown the exact tradeoff (verbatim: option said it "contradicts the proposal's
  own evidence… raises under-gating/regression risk — the exact failure your library doctrine warns
  against") and chose it knowingly.
- **Risk:** under-gating regression — the getaway leg may pre-authorize skips on real-but-low-scoring tasks;
  body-trigger retrieval ships without the shadow-A/B the proposal required.
- **Mitigation / Reversal:** (a) each feature gets an env kill-switch **defaulting ON** —
  `ENFORCER_AUTHORIZED_SKIP`, `SKILL_BODY_TRIGGERS` — so rollback is one env var; (b) the getaway-leg
  AUTHORIZED-SKIP message embeds the **library-doctrine escalation** (real/ambiguous work → `find-skills`,
  never a bare skip), so the feature firing does not equal a blind skip; (c) the audit metric
  (`audit_skill_usage.py`) will surface any false-skip regression; (d) a shadow-A/B smoke runs in Phase 7 and
  its result is recorded even though the feature ships on; (e) prereq #4 (score re-measurement) remains a
  documented post-ship follow-up.

## D2 — Go-live scope: LOCAL, hold the push (user choice)

- **Fork:** how far the autonomous run takes "go-live".
- **Decision:** implement → dual-validate → merge to `main` + bump version + CHANGELOG **committed locally**,
  but **do NOT push** to the GitHub remote. User reviews the diff and pushes, then runs `/plugin update` +
  restart. Per the user's selection ("Local main, hold the push").
- **Grounds:** user's explicit choice; also the runtime `/plugin update` + restart is user-side regardless.
- **Risk / Reversal:** none — the outward-facing irreversible step (remote push) stays with the user.

## D3 — Execution model: sequential sub-agents, NO worktree (user directive)

- **Fork:** the ck:team cook default is parallel devs with worktree isolation; user said "NO WORKTREE" and
  "if parallel agents aren't feasible, then sequential sub agents … could replace".
- **Decision:** **sequential** sonnet-5 implementer sub-agents, no worktree. One phase's files at a time.
- **Grounds:** without worktree isolation, parallel edits to shared files (esp. `enforcer.py`) would collide;
  sequential is conflict-free and user-authorized. `TeamCreate` is also unavailable in this environment.
- **Risk / Reversal:** slower wall-clock; acceptable. No correctness risk.

## D4 — Branch: feature branch → merge to main

- **Fork:** implement directly on `main` vs. a feature branch.
- **Decision:** feature branch `feat/usefulness-rate-upgrades-0.12.0`; merge `--no-ff` to `main` at Phase 8
  after both validation gates pass.
- **Grounds:** cleaner history + a single reviewable merge; matches the user's "merge to main". Git ops are
  explicitly authorized by the go-live order (overrides the workbench "no git ops unless asked" default).
- **Risk / Reversal:** none; branch is discardable pre-merge.

## D5 — Version bump: 0.11.1 → 0.12.0 (minor)

- **Fork:** patch vs. minor bump.
- **Decision:** **0.12.0** (minor) — new user-visible features (new enforcer tier, new retrieval signal, new
  doctrine), backward-compatible, pre-1.0.
- **Grounds:** Keep-a-Changelog + semver intent; these are additive features, not fixes.
- **Risk / Reversal:** trivial to change before push.

---

## D6 — Body triggers capped COMBINED with description at `_TRIG_MAX` (bounded point-count growth)

- **Fork (implementation):** give body-derived trigger phrases their own extra point slots (grows the
  multi-vector layer 1.5–2×) vs. cap description+body COMBINED at the existing `_TRIG_MAX=12`.
- **Decision:** cap COMBINED — description phrases first, then body phrases (deduped) up to the same 12-slot
  per-skill ceiling.
- **CORRECTION (empirical, D8):** an earlier draft of this note + the code comment + VENDORED.md + the Phase-4
  commit claimed this keeps the point count "flat / does not grow." The live reindex disproved that: points
  went **2231 → 3570 (+60%)**. The COMBINED cap bounds per-skill triggers at 12 (vs. additive-on-top, which
  would be unbounded), but the TOTAL rises because most skills left slots empty (median description ~3/12) that
  body phrases now fill. Still far below full-body chunking's 2-4×. Code comment + VENDORED.md corrected.
- **Grounds:** the proposal flagged point-count growth as the main risk of body indexing; a per-skill cap
  keeps growth BOUNDED (the conservative first step) — not zero. Trade-off: skills whose descriptions already
  fill the 12 slots get no body phrases (rare — median description uses ~3 slots).
- **Risk / Reversal:** slightly less body recall for verbose-description skills; revisit the cap later if the
  A/B (Phase 7) or organic data shows it's limiting. Purely a constant to raise.

## D7 — Pre-existing integration test left failing (out of scope)

- **Fork:** `vendor/skill-search/tests/test_indexing.py::test_end_to_end_build_search_incremental` asserts
  `embedded == indexed`, which is FALSE under the multi-vector layer (2231 points ≠ 488 skills). Fix it vs.
  leave it.
- **Decision:** leave it. It is **pre-existing** (identical assertion on `main`, commit `73ea518`), unrelated
  to this change, and `@pytest.mark.integration` (deselected from the normal unit gate: `-m "not integration"`).
- **Grounds:** fixing an unrelated pre-existing test is scope creep; the unit gate (29 passed) is the relevant
  bar. Documented here + in the handoff so it isn't mistaken for a regression from this work.
- **Risk / Reversal:** none for this change; flagged as a separate pre-existing cleanup.

---

*(Further decisions appended below as they arise during implementation.)*
