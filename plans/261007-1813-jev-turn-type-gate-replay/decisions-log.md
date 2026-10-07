# Judgement calls under GO (2026-10-07, Thinh: "GO pls")

1. Provider: Jev via jevd pinned to `commandcode` (model `typesafe/jev`, unpinned version). Why: Thinh's
   preferred provider (RULES [72]); the previous handoff says no TypeSafe call without his yes. Effect: the
   new questions' answers are not on the same model id as the cached cookbook-gate answers (jev-1.13.0),
   so the two sets are compared as separate measurements, not pooled.
2. Two question wordings (`work`, `convo` inverted), written by me, asked in one request per turn.
   Why two: one wording can fail by accident; a second checks the first. Neither was tuned on the data.
3. State = the live `ctx` variant (request + previous assistant tail + skills loaded). Why: that is what the
   live hook can send.
4. Labels are behavioural only (agent used a skill / searched then skipped / skipped conversationally),
   per the owner's 2026-09-26 order that no hand-labelled prompt set justifies a decision. This session's
   five prompts are reported as illustrative probes only.
5. Baseline measured alongside: the embedding actionability gate (`_intent_conversational`) on the same
   populations, to show what ADR-0061 removed and why.
6. No code in hooks/ or the doctrine is changed by this analysis.

## 2026-10-07 22:28 — reputation tier mapping (default applied, owner's question unanswered)
- Owner order: "every plugin:skill should be added to the reputation list, along with ak-* family, matt-pocock's skills too, and those in the keep-on list".
- Asked which badge per group (AskUserQuestion); no answer in 600 s. Applied the recommended option: keep-on (54) as heart; `*:*`, `ak-*` and Matt Pocock's personal skills (34; `writing-for-agents` stays heart via keep-on) as star.
- Written to ~/.claude/skill-concierge/reputation.json (heart 54, star 35). Reversible with scripts/reputation.py add/remove.
- To make `*:*` mean "every plugin skill" without marking external-catalogue and other-harness rows, owner badges now render on installed and pulled rows only (ADR-0083 updated).
