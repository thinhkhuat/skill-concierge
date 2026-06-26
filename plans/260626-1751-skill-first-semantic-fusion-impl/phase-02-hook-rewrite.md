---
phase: 2
title: "Hook Rewrite"
status: done
priority: P1
effort: "1-1.5d"
dependencies: [1]
---

# Phase 2: Hook Rewrite

## Overview

Replace the lexical enforcement hook with a semantic one. On a non-trivial prompt: POST the query to
the Phase 1 embed endpoint → vector → Qdrant top-k → inject the enforcement **mandate + semantic
candidates** (name, desc, score). Retire the lexical scorer and the drifting `library.json`. Preserve
the safety contract. Emit `offer` telemetry so hit@k becomes computable. (Resilience/timeout is
Phase 3 — this phase is the happy-path rewrite.)

## Related Code Files

- Create: `hooks/scripts/enforcer.py` — the new semantic UserPromptSubmit hook (lives in the plugin
  alongside `ledger.py`).
- Modify: `hooks/hooks.json` — register `enforcer.py` on `UserPromptSubmit` (alongside the ledger).
- Modify: `hooks/scripts/ledger.py` — switch the `manual` real-skill-vs-builtin split off the interim
  `library.json` and onto the engine catalogue (see step 6).
- Retire at rollout (Phase 4, not here): `~/.claude/hooks/skill_first_nudge.py`.
- Reuse (port the keep-able parts of) the old hook: trivial-getaway gate, fail-silent, empty/slash
  suppression.

## Implementation Steps

1. **Keep the cheap pre-gate** from the old hook: trivial-getaway (skip injection on trivial/empty/
   slash prompts), fail-SILENT, additive-only. **Drop** `score()` / `_tokens()` / `_fold()` /
   `_distinct_hits()` and the `library.json` read entirely.
2. **Embed:** `POST /embed {text: prompt}` → vector (stdlib `urllib`; no heavy imports at module load
   so the cold hook stays fast).
3. **Retrieve:** Qdrant search top-k (start k=5, tunable) on collection `claude_skills` → candidates
   `(name, description, score)`.
4. **Compose injection:** enforcement mandate text + rendered top-k (name · short desc · score).
   Additive context only — never blocks the turn.
5. **Emit `offer` telemetry** at injection (per `docs/plan.md:71`):
   `{t, sid, ev:offer, band, offered:[[name,score]...], fallback, q:<prompt≤120c>}`. This is what
   unlocks **hit@k** in `analyze.py` (currently pending — `docs/plan.md:152`).
6. **Unify the catalogue:** candidate set + any name validation now come from the engine
   (`discover_skills()` / Qdrant index), NOT `library.json`. Repoint the ledger's `manual` split
   (step in Related Files) to the same source so the two halves can't drift (kills the 585-vs-508-vs-512
   drift, `docs/plan.md:128`).
7. **Latency hygiene:** keep the hook stdlib-only; defer/avoid imports that aren't needed on the
   trivial-getaway path.

## Success Criteria

- [x] Non-trivial prompt → hook injects semantic top-k from Qdrant (mandate + candidates + scores).
- [x] Lexical scorer and `library.json` read fully removed; catalogue count reconciles to the index.
- [x] `offer` events written to the ledger; `analyze.py` now reports hit@k.
- [x] Safety contract intact: trivial/empty/slash suppressed, fail-silent, never blocks.
- [x] Semantic-jump smoke: an EN query with no lexical overlap to a VN-described skill surfaces it
      (the "janky UI on mobile" → `responsive-design` class — `docs/plan.md:124`). Full gate in Phase 4.

## Risk Assessment

- **session_id sharing (open question, `docs/plan.md:152`).** Subagent `Skill` calls may share the
  parent `session_id` → could inflate uptake/hit@k. Verify against live data; tag/segment if real.
- **k tuning.** Too high = noisy injection + token cost; too low = misses. Start k=5, then tune from
  the ledger's offered-but-never-taken rollups.
