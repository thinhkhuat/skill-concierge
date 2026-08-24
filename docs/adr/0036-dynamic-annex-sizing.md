# ADR-0036: Dynamic annex sizing — competitive margin instead of fixed 2

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-08-24 |
| **Supersedes** | none |
| **Amends** | ADR-0032 and ADR-0034 (their fixed `*_SLOTS = 2` sizing; their zero-displacement invariant is untouched) |

## Context

Both annexes — external catalog (ADR-0032) and cross-harness (ADR-0034) — showed a fixed 2 rows
whenever anything cleared their 0.40 floor. Measured on the live index, that constant is wrong
in both directions:

- **The floor discriminates nothing.** The external pool (~1.9k catalog skills) has **8+ rows
  above 0.40 on essentially every offer-bearing turn** — eight probes, eight times ≥7 rows over
  the floor. "Above the floor" is true of everything, so "top 2 above the floor" is an arbitrary
  slice, not a read of intent.
- **Strong-inventory turns get padded.** On *"review this pull request for security issues"*
  the installed top is 0.750 and the fixed annex still showed 2 externals, one of which loses
  to half the installed menu.
- **Thin-inventory turns get starved.** On *"build an odoo module with automated tests"* the
  installed top is 0.673 while four externals score 0.68–0.76 — exactly the case the catalog
  exists for, capped at 2.

The operator's ask: replace the constant with something that represents the intent and what the
inventory can provide at a glance.

## Decision

**Competitive margin: an annex row earns a slot by scoring within `ANNEX_MARGIN` of the top
installed row.** The per-turn annex floor is:

```
_annex_floor(pool_floor, top_installed) = max(pool_floor, top_installed − ANNEX_MARGIN)
```

capped at the pool's slot cap. One rule, both annexes, two knobs:

- `ENFORCER_ANNEX_MARGIN` — default **0.05, measured not guessed**: on the compressed mpnet
  cosine band (real tasks ~0.5–0.9), margins of 0.10+ saturate every annex at its cap (they
  stop discriminating), while 0.05 cleanly separates strong-inventory intents (annex 1) from
  external-dominated ones (annex at cap).
- Caps: `ENFORCER_EXTERNAL_SLOTS` default **4** in dynamic mode (was 2), `ENFORCER_FOREIGN_SLOTS`
  stays **2**.

The threshold *rises* with the installed top — a well-served intent shrinks its annexes to 0–1,
strictly less noise than the fixed 2 — and *falls* to the pool floor when the inventory is thin,
widening the annex to its cap. The annex width itself becomes the "glance" the operator asked
for: how much the wider world outbids the installed shelf for this intent. Two boundary cases
fall out naturally rather than by special-casing:

- **Deterministic route hits** (score 1.0) push the threshold to ~0.95 and silence the annexes:
  explicit intent wants no alternatives.
- **No installed candidates** (`top_installed ≤ 0`) falls back to the pool floor — an empty
  inventory is the case the annexes exist for, never a reason to suppress them.

**What does not change.** The installed `TOP_K` is untouched; annexes remain separate queries;
zero displacement remains the hard invariant of ADR-0032/0034 — "ratio" here governs annex
width only, and the score-mass option that would have made installed slots negotiable was
considered and rejected for exactly that reason (plus being unpinnable in a selftest).
`ENFORCER_ANNEX_DYNAMIC=0` reverts byte-identically to fixed sizing, including the old
`EXTERNAL_SLOTS` default of 2.

## Consequences

- Offer length now varies with intent: shorter than today on well-served turns, up to +3 lines
  (~90 tokens) only where the inventory is demonstrably thin.
- The ledger's `ext`/`xh` arrays inherit the varying width — `analyze.py` counts rows, so its
  stats need no change, but **any annex-width or conversion metric pooled across this release
  describes two configs. Ledger epoch: window from the 0.26.0 commit.**
- `auto_promote` (ADR-0032) sees more external takes on thin-inventory turns and fewer junk
  offers elsewhere — directionally the same signal, better precision.
- Rejected alternatives, for the record: **coverage-gap binary** (a hard threshold at
  "installed is weak" — coarser, discontinuous at the boundary); **score-mass ratio** (the most
  literally ratio-like, but opaque, unpinnable, and it reframes installed slots as negotiable).

## Validation

- Selftest case (11b) pins the rule in both modes: fixed ignores the installed top; dynamic is
  `top − margin` clamped to the pool floor; absent installed top falls back to the floor; and
  end-to-end, a 0.75 external is pruned under a 0.90 installed top and kept under a 0.55 one.
  Case (12) pins the ADR-0034 shape under fixed mode explicitly.
- Live, six intents (margin 0.05, caps 4/2): review-PR **1** external (0.767 vs installed
  0.750) + 2 foreign; DB-migration **2** (0.931/0.861 vs 0.911); debug-CI **3** externals,
  **0** foreign — the installed twin at 0.784 dominates the whole foreign pool, which is the
  noise-removal working, not a regression; odoo / k8s-helm / TDD **4** (cap) where the
  inventory is thin. Kill-switch re-run on review-PR returns exactly the old 2 rows.
- The debug-CI foreign-annex zero was investigated, not assumed: the raw pool shows every
  non-twin row (0.70, 0.635, …) losing to the installed top by more than the margin.
