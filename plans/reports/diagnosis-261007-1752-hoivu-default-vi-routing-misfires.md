# Routing misfires on the HOIVU "default UI in VI" turn

Date: 2026-10-07. Read-only diagnosis; no code changed.

## Evidence

Ledger: `~/.claude/skill-concierge/logs/skill-invocation-ledger.log`.

- Original turn, 17:23:47, sid `832d2916…`, prompt "have the default UI to be set in VI please".
  Offer (Jev router, whole-shelf ranking): `tui-fundamentals` 0.40, `working-with-claude-code` 0.15,
  `skill-search` 0.10, `computer-use` 0.08, `prime-frontend` 0.07. Jev `fit` 0.49 (floor 0.30),
  `conf` 0.36, `prov` commandcode, `ms` 2697. External annex `ui-theme-designer-help` 0.61.
  Chain hint `session-handoff`, `ak-journal`, `brief-me`.
- One `search` event at 17:23:56. Hits are not logged.
- Replay of the agent's query today ("change default language of a static web page"):
  `tavily:tavily-extract` 0.68, external `codebase-to-wordpress-converter` 0.64, `firecrawl-scrape` 0.64.
  The engine warns the index is stale. The hits the transcript names (progress-map, i18n-localization)
  do not reproduce.
- This diagnosis turn, 17:52:24, sid `37119ad6…`: the prompt pastes the transcript, which contains the
  text "progress-map". The route `{"contains": "progress-map"}` (`config/deterministic-routes.json:9`)
  pinned `progress-map` at 1.0. The offer row has no `jev` key: a named route turns the Jev router off.
- The HOIVU hub is hand-built (`HOIVU/library/DESIGN.md`, `library/assets/hub.js:116`), not progress-map
  output. progress-map was not a fit for the original turn.

## Defects

1. Deterministic route fires on a quoted mention. `_route_matches` (`hooks/scripts/enforcer.py:1278`)
   checks whole-word presence anywhere in the prompt. A pasted transcript, log or quote that names a
   skill pins it, and the same hit switches off the Jev router.
2. The whole-shelf ranking was confidently wrong. "UI … VI" ranked a terminal-UI skill first at fit 0.49,
   above the 0.30 floor, so it was labelled "Whole-shelf ranking". That label tells the agent every skill
   was judged. Inference, not verified: "VI" (Vietnamese vs the vi editor) and "UI" pulled toward TUI;
   the rerank sees no history (`ENFORCER_JEV_HISTORY=0`).
3. Embedding search ranks URL-scraping skills for a "web page" query, and the index is stale.
   There is no installed i18n/localization skill on the Claude shelf, so part of this is a catalogue gap.
4. Noise: a chain hint left over from the previous wrap-up, and an off-topic external annex row.

Agent side (not concierge): the verdict "no skill fits" was right, but the reason given
("it's just a one-line default") is the doctrine's red-flag "trivial" thought, and there was no
`NO SKILL:` line naming the query and the top hit.

## Fix approach

1. Routes: match name-type routes only as an invocation (`/name`, "use/run/invoke name") or in the
   prompt's own head, and skip prompts that look like pasted transcripts. Keep the Jev router running
   on a route hit; the route only pins its row. Replay route hits from the ledger to count false pins
   before and after. Test: a pasted transcript naming `progress-map` must not pin it.
2. Jev presentation: replay with `scripts/calibrate_jev_gate.py` before touching any number. Candidate
   change: below a second, higher fit bar, render the offer with the "Preview" header instead of
   "Whole-shelf ranking". Compare Command Code vs TypeSafe rankings on this turn. Epoch rule applies.
3. Search: run a reindex, re-run the query, then decide whether a curated trigger or a new skill is
   needed.
4. Chain hint and annex noise: watch only; no change yet.

## Open questions

- Which i18n-localization skill did the original search return (origin, installed or external)?
  The ledger does not store search hits.

## Addendum 18:05: Jev decides first (owner's direction)

Owner direction: before any skill search, Jev decides whether the concierge gets involved, or hands the
agent a calibrated measurement to base its skill/no-skill call on.

Prior art: ADR-0060 asked Jev a prompt-only yes/no ("needs a playbook?"); on 431 real skill turns it would
have skipped 206 (47.8 %); ADR-0061 replaced it with the per-candidate `fits` floor (0.30).

Offline curve, cached answers only (no Jev calls): `calibrate_jev_gate.py curve --shelf wide --variant ctx
--catalog-hash f65af73783c60a68` (catalogue of 2026-10-03/04, not today's; jev-1.13.0). 313 real skill
turns, 297 traffic turns.

| max_fits bar | real skill turns lost (UCB95) | traffic skipped |
|---|---|---|
| 0.30 (today) | 0.3 % (1.8 %) | 3.0 % |
| 0.40 | 4.8 % (7.8 %) | 10.4 % |
| 0.50 | 10.2 % (14.1 %) | 23.6 % |

Reading: the score separates cleanly only at the bottom. A hard Jev skip above 0.30 costs about one real
skill turn for every two noise turns removed. The HOIVU turn (0.49) would need a 0.50 bar, which loses
about 1 in 10 real skill turns. So Jev should decide alone only at the low bar; between the low bar and a
high bar it should hand the agent the calibrated reading, and that reading should count as a lawful skip
source in the doctrine (no forced search), while the menu stays visible.

## Correction 18:07: a higher fit bar would not catch conversation turns

Ledger, this session (sid 37119ad6…): three conversational design questions got Jev offers with
max fit 0.82 (17:58, lead `which-skills`), 0.59 (18:02, lead `jevd`) and 0.48 (18:04, lead `ak-ask`).
None needed a skill; each forced a `search_skills` call whose hits were unrelated.

So the three-band proposal in the addendum above is wrong for this class: `fits` measures how well a
skill's topic matches the prompt, not whether the turn asks for work. A conversation ABOUT skills scores
high against skill-routing skills. No fit bar separates these turns.

The first question should be the turn type: is the user asking the agent to produce or change something,
or asking for its view in conversation? A Jev Noul on that question has not been tested; ADR-0060 tested
"needs a playbook?" wordings, which is a different question. Test before building: replay it on the 313
real skill turns (`calibrate_jev_gate.py`), where every positive is a work turn, and require false-NO near
today's 0.3 %.

The doctrine is the second half: "Your judgment is not a skip source" (`hooks/doctrine/skill-first.md`,
rule 6) is what forced each search once the hook gave no `SKILL-CHECK:` line.
