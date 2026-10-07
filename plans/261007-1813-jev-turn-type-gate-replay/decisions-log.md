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
