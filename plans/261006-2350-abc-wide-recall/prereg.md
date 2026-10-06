# Pre-registration: A/A2/B/C wide-pass recall test (Jev skill router)

Written 2026-10-06 (Asia/Saigon), before the first live Jev call. Not to be changed after the first live call;
any later note goes in a dated section at the end, marked as written after calls began.

Owner order (Thinh, approved via question): run the A/B/C test with "200 turns + noise check".
Hard constraint (Thinh): "do not run any more of the typesafe calls without me saying yes".

## Question

The Jev router's wide pass shows Jev each skill's description cut to 160 characters (`JEV_WIDE_DESC`).
Does giving Jev better text per skill raise recall of the skill the user actually used?

## Variants (wide pass only; same catalogue, state, chunking and shortlist rule)

- **A**: today's wide questions, `_jev_wide_questions(catalog)` exactly.
- **A2**: A again, sent as an independent request. It measures Jev's run-to-run disagreement (noise floor).
- **B**: option text = `(when_to_use + " " + description)` cut to 160 characters, for skills whose SKILL.md
  frontmatter has `when_to_use` (SKILL.md path taken from the index payload `path`; list values joined with a
  space; whitespace collapsed). Every other skill keeps A's text. Built by passing the replaced descriptions
  through the enforcer's own `_jev_wide_questions` (160-character cut unchanged).
- **C**: option text = description cut to 160 characters + `" Examples: "` + up to the first 3 English
  flywheel utterances (`triggers.json` `<skill>.llm_triggers.triggers`, English by the enforcer's own
  `_is_english`, list order, joined with `"; "`), total capped at 320 characters. Skills with no English
  utterance keep A's text. Built through `_jev_wide_questions` with `JEV_WIDE_DESC` set to 320 only while
  C's questions are built.

The questions are built once (the catalogue is pinned), stored in `_RESEARCH_ARTIFACTS/questions.json`, and
reused for every turn. A and A2 send byte-identical questions.

Prep facts (from `_RESEARCH_ARTIFACTS/prep-meta.json`): catalogue 567 skills in 3 Choice chunks (250/250/67),
so the shortlist holds 15 names; B changes 116 skills; C changes 567 (566 with 3 examples, 1 with 2);
estimated question tokens A 27,630, B 27,540, C 40,435; enforcer file sha256 `8efea3bc…403d`
(full value in prep-meta.json). The run refuses to start if the enforcer file changed after prep.

## Catalogue

`_jev_catalog()` snapshot taken once at prep (local index owner, cwd = repo root, so project isolation as for a
session in this repo) and saved to `_RESEARCH_ARTIFACTS/catalog.json` (sha16 `117582aa1a051fa0`). Same list
for every variant and turn.

## Data and sample

Source: `~/.claude/skill-concierge/jev-calibration/real-turn-labels.jsonl` (private; only uuids and aggregates
leave it).

Eligible turn:
1. `lang == "en"`;
2. `skill_call` is true (a skill was actually invoked);
3. gold = bare names (`split(':')[-1]`, lowercased, arguments dropped; the search slugs `skill-search` and
   `skill-concierge-skill-search` removed) of `skill_calls`; at least one gold name is in the pinned catalogue
   (same bare-name rule);
4. **offer-independent** (design amendment, see below): no gold name is in `ledger_offered`, or
   `ledger_offered` is empty/absent.

Sample: 200 turns drawn with `random.Random(20261006).sample(eligible sorted by uuid, 200)`. Seed 20261006.
Eligible pool: 356 turns (546 before the offer-independence filter). The sampled uuids are in
`_RESEARCH_ARTIFACTS/sample.json`.

State per turn (the enforcer's shape): `request` = prompt[:JEV_MAX_CHARS] (4000), `recent_context` =
`prev_assistant` (already the last 1,500 characters) or "", `skills_already_loaded_this_session` =
`session_skills` (skills loaded earlier in the session, before this turn) or [].

### Design amendment (before any live call)

Reason, from the main session on Thinh's request: the answer key can be shaped by what the hook offered on that
turn, because agents tend to pick offered skills; that biases recall toward whichever text produced the offer.
The corpus spans 2026-06-11 to 2026-09-26 15:14; the Jev router went live 2026-09-26 09:47 (v0.51.0), so very
few turns had Jev-ranked offers and earlier offers came from embedding retrieval. So the sample is drawn from
the offer-independent stratum only (rule 4 above). Results are also reported split before/after
2026-09-26 09:47 Asia/Saigon (`ts_utc` < / >= `2026-09-26T02:47`); only 1 sampled turn falls after it.

## Calls

- Tier: the jevd ladder entry named `commandcode` only (`_jevd_ladder()`, `JEVD_URL=http://127.0.0.1:4377`).
  The run asserts every tier used has `name == "commandcode"` before the first call. jevd's router serves a
  pinned request (header `X-Jevd-Provider`) from that one provider only and never walks its ladder.
- TypeSafe excluded structurally: `TYPESAFE_API_KEY` (and `CMD_API_KEY`, `FLYWHEEL_LLM_API_KEY`,
  `ENFORCER_JEV_KEY`) removed from the process before the enforcer loads; `_jev_route` is never called.
- Each call: enforcer `_jev_call(state, questions, tier, key, 5.5)`, key = `_jev_key(tier)` (jevd marker only).
  At most 3 calls in flight. A failed call is retried once after 2 s; every failure is recorded.
- Variant order per turn is shuffled with `random.Random(f"20261006:{uuid}")`, so drift over time hits all
  variants alike.
- Pilot: the first 5 sampled turns (they count toward the 200). Token use is estimated with the enforcer's
  `_jev_tokens` on `{"state", "questions"}` per call; latency logged per variant. The run continues to 200
  without stopping unless the projected total exceeds 60M estimated input tokens, in which case it stops and
  reports.

## Metrics and decision rule

- **Primary**: recall@shortlist = gold ∩ `_jev_shortlist(wide answers)` is non-empty (bare-name match).
  Paired over turns where all four variants answered.
- **Secondary**: reciprocal rank of the first gold name in one list of every option sorted by wide probability
  across all chunks (MRR). Descriptive only, no test. Caveat: probabilities from different chunks are not
  strictly comparable.
- **Noise floor**: A vs A2 disagreement rate on the primary metric = (A2-only hits + A-only hits) / n.
- **Test per variant vs A** (B, C): exact McNemar on discordant pairs (binomial, two-sided), Holm across B and C.
  - **proven**: Holm p < 0.05 AND net gain (b − c)/n > A-vs-A2 disagreement rate;
  - **harmful**: Holm p < 0.05 and net change negative;
  - otherwise **not-proven**.
- **MDE**: smallest net paired difference detectable with 80 % power at two-sided alpha 0.025 (Holm's first
  step), normal approximation for paired proportions (Connor 1987), using each comparison's observed discordant
  proportion; also a grid of discordance 0.05–0.30 at alpha 0.025 and 0.05.

## Caveats known before running

- Command Code serves the unpinned model `typesafe/jev`; the version behind it is not visible. Results compare
  variants with each other, not with the 0.30 fits floor tuned on jev-1.13.0.
- C's requests are about 46 % larger, so C may time out more often; the paired set drops any turn a variant
  failed, which could select easier turns. Failure counts per variant are reported.
- Gold is the skill the agent invoked, which is not always the best skill.
- Token counts are the enforcer's estimate (documented as 2–18 % above Jev's own count), not billed usage.
