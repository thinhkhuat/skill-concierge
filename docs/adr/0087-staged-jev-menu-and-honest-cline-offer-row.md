# 0087 — Staged Jev menu, the Cline first-call chain, and an honest Cline offer row

- Status: accepted
- Date: 2026-10-08
- Deciders: Thinh
- Amends: ADR-0086 on two points: its `ENFORCER_LEDGER=0` on the preview pass, and the Jev provider order of
  its full pass (Cline now uses TypeSafe only, Decision 9). Its rule that the first model call carries the
  full menu when ready, else the embedding preview, stands. The rest of ADR-0086 stands.
- Relates to: ADR-0061 (Jev router), ADR-0075 / ADR-0079 (tiers, Command Code span), ADR-0080 (jevd as the bench)

All times are Asia/Saigon (+07), 2026-10-08. The decision trail below is kept whole: Decisions 3 to 5
describe a design that was built and then removed before release (Decision 9 supersedes its Cline parts). Evidence: `plans/reports/replay-261008-2151-cline-first-menu.md`,
`plans/reports/validator-261008-2151-cline-first-menu-replay.md`, `plans/261008-2226-staged-jev-menu/GATES.md`
(gates G1 to G9, with the live evidence), and the replay tool `plans/261008-2151-cline-first-menu-replay/first_menu_replay.py`.

## Context

Two problems, both found after 0.63.0 shipped the Cline plugin (ADR-0086).

1. **Cline's offer row described a menu the model did not see.** The plugin runs two enforcer passes per run:
   the full Jev pass and a fast embedding preview. ADR-0086 muted the preview's ledger row
   (`ENFORCER_LEDGER=0`), so the full pass logged the turn's one offer row. But Cline's first model call waits
   only 2 s (its hook limit is 3 s, and the trip into and out of the plugin sandbox counts), and the full
   Jev menu landed in 2.0 to 2.3 s live. So on most first calls the model was given the preview while the
   ledger recorded the Jev menu. Cline's offer-to-take numbers mixed two different menus. (Fact: ADR-0086,
   Consequences; the live landing times are from that record.)
2. **The Cline first call mostly carried the weakest menu**, the embedding preview. Replay of real turns
   (below) puts it far behind both Jev menus.

The Jev router's own structure also leaves value on the table in every harness. It makes two linked calls
per turn: a **wide** pass (the whole shelf in chunks of at most 250, top 5 per chunk become a shortlist) and a
**rerank** of that shortlist. If the rerank fails on every tier, the turn used to drop to the embedding menu
and discard the wide answer it had already paid for.

### Replay, what it measured (fact)

Corpus: 313 real Claude Code turns where the agent used a skill (the `calibrate_jev_gate` positives), 233 of
which name a skill still installed on today's 549-skill shelf. Jevd pinned to Command Code. A hit at k means a
skill the agent actually used is in the menu's top k. Replay hit rates on the 233 reachable turns:

| Menu (top 5) | hit@1 | hit@3 | hit@5 |
|---|---|---|---|
| Embedding preview | 12.9 % | 21.9 % | 27.5 % as first reported; 22.7 % corrected (below) |
| Wide pass only | 34.8 % | 63.9 % | 71.2 % |
| Full (wide + rerank) | 43.8 % | 66.1 % | 75.1 % |

Independent validation (same day, `validator-261008-2151-…`) reproduced every cell and made these corrections:

- **Preview hit@5 is 22.7 %, not 27.5 %.** On 33 of the 233 turns the enforcer shows the model a skip message,
  not the preview's menu; the replay had credited a menu there. Exact-name scoring (no bare-name matching)
  gives 27.0 / 67.4 / 70.4 % for preview / wide / full at top 5.
- **Paired over 233 turns:** wide minus full is -3.9 points at hit@5 (95 % CI -8.0 to +0.3, not significant;
  McNemar p 0.11) and -9.0 points at hit@1 (p 0.009, significant). Wide minus preview is +43.8 points at
  hit@5 (CI +36.2 to +51.4).
- **The replay's timing claim was wrong and is retracted.** The replay said the wide pass plus 0.35 s of
  start-up fits Cline's 2 s wait on 96 % of turns. It timed the Jev request alone, in one 17-minute window.
  Over 90 live Command Code turns (2026-10-07 01:10 to 2026-10-08 21:51; 79 Claude Code, 7 Cline, 4 OMP) the
  wide pass, measured from before the jevd ladder fetch, took p50 1,786 ms and p90 2,498 ms. Only 36 to 52 %
  of turns would fit 2 s. The replay's own timings were wide p50 1,255 ms / p90 1,490 ms and full p50
  2,062 ms / p90 2,364 ms (Jev calls only, six calls at a time).
- **Chunk bias.** The 49-skill chunk (8.9 % of the shelf, 18.5 % of used skills) supplied 36 % of the wide
  top-5 rows when ordered by raw within-chunk probability. See Decision 5.

## Decision

1. **Honest offer row (22:05, "1+2": fix the ledger; test a wide-only first menu by replay).**
   `ENFORCER_LEDGER` gains a third value, `defer`. The enforcer writes no ledger row and returns its
   would-be offer row in its JSON output as `skillConciergeOffer`. The Cline plugin runs every enforcer pass
   with `defer`. At the run's first model call it logs, through `ledger.py` (new hook event
   `ConciergeOffer`), the offer row of the menu that call actually carried, tagged `seen`:
   `full` (the full pass) or `preview` (the embedding pass). (The first design also had `typesafe` and `wide`;
   Decision 9 removed them.) If no menu was ready, the row is written when the full pass lands, tagged
   `late`. A full-pass row that lands after another menu was sent is logged as `ev: "offer_late"`,
   `seen: "later"`. `analyze.py` reads only `ev == "offer"`, so offer counts never see `offer_late` rows.
2. **Staged Jev route, every harness.** The wide pass's own menu is a result. When no tier finishes its
   rerank (failure, refused answer, or no time), the turn keeps the first tier's wide menu instead of
   dropping to the embedding menu. A later tier's full route is still tried first. The routing telemetry
   gains `stage`: `full` or `wide`. The net also holds when the hook's own time limit (`JEV_BUDGET_S`, joined
   in `_jev_join`) runs out while a later tier's rerank is still running: the route hands its first wide menu
   to the join the moment it has one, and a join that times out serves it with `stage: wide` and
   `err: BudgetExceeded` (an independent review measured the wide menu surviving only 4 of 10 such runs before
   this fix). Under `ENFORCER_JEV_HISTORY=1`, a history-skip guard that runs out of time keeps it too
   (`err: HistorySkip`, `stage: wide`). Wide probabilities are validated like the rerank's: a NaN, infinite or
   out-of-range value fails that tier (`ValueError`, recorded in `fell`) and the next tier runs; before the
   fix a NaN emptied the turn's output on every harness and wrote invalid JSON to the ledger. This changes shared enforcer behaviour for Claude Code, Codex, ZCode,
   OMP, OpenCode, Command Code, DSH and Cline alike, and only in the case that used to fall back.
3. **Early wide menu, opt-in (22:17, "A": the full pass emits the wide menu early; no extra Command Code
   call). Built, then removed (Decision 9).** `ENFORCER_EARLY_MENU=1` made the enforcer print the wide menu as
   its own JSON line (`skillConciergeEarly`) the moment the wide pass returned, while the rerank ran. Only
   the Cline plugin set it. It no longer exists as a flag or in the code.
4. **Cline first-call chain (22:37 and 22:52). Built, then superseded (Decision 9).** Plan A plus a TypeSafe
   call as the fallback before the embedding menu: the full pass (Command Code first) with the early menu, an
   embedding preview, and, if the full pass had not finished 0.5 s into the run (`BACKUP_AFTER_MS = 500`), a
   backup pass with `ENFORCER_JEV_TIER=typesafe`. At 22:52 the owner settled that the backup runs TypeSafe's
   **full** route (about 0.65 s), not a wide-only route. The first model call (2 s wait) carried, in order:
   Command Code full, TypeSafe full backup, Command Code early wide, embedding preview. Because the backup
   had to start before Command Code answered, most Cline turns would have called both providers.
5. **`ENFORCER_JEV_TIER=<jevd provider name or model id>`** limits the route to that one tier. Default
   unset (all tiers). Kept. The Cline plugin uses it to pin its full pass to TypeSafe (Decision 9). When jevd
   is not answering, the pin also matches an `ENFORCER_JEV_BENCH` tier by endpoint (`JEV_PIN_EP`: `typesafe`
   = `ts`, `commandcode` = `cc`, `gateway` = `gw`); the first version matched nothing then, so Cline would
   have run without Jev.
6. **Wide rows are ordered by lift (probability times chunk size), top 5** (`_jev_wide_rows`). Evidence
   (gate G3): on the same 312 wide answers, raw order gave hit@5 71.2 % and hit@1 36.1 %; lift gave 70.8 % and
   36.5 %. The quality is equal. Lift was chosen because raw order always ranks a one-option chunk's skill
   first (its probability is 1.0), a hazard that grows with the catalogue size modulo 250. Raw order gave the
   49-skill chunk 36 % of top-5 rows; lift gives it 13 %.
7. **Keep-full is locked for the 10-second harnesses (22:26, "keep-full for the 10-second harnesses is
   locked-in").** Claude Code, Codex (30 s hook), ZCode, OMP and OpenCode (10 s) keep the full route.
   Reasons, measured: a wide-only route would cut requests per routed turn from 2 to 1 but only about 10 % of
   the question text (wide about 96,000 characters, rerank about 11,000), save about 0.8 s, lose about 21 %
   relative top-1 accuracy (34.8 % against 43.8 %), and lose the "no skill fits" verdict (5 % of live Jev
   turns, 34 of 661 in 14 days).
8. **Command Code and DSH keep the full route (22:33 probe).** Their adapters pass `ENFORCER_JEV_BUDGET=1.6`
   and kill the enforcer at 2.5 s; they already get the full route through jevd's TypeSafe tier at 0.62 to
   1.07 s. An earlier claim in this work that they skip Jev was wrong.

9. **TypeSafe only for Cline (22:58, owner's choice via AskUserQuestion; options were TypeSafe only / keep
   both / Command Code only).** Reason: the Decision 4 chain, as built, billed both providers on most Cline
   turns (about 4 Jev calls: the TypeSafe backup's two plus Command Code's two), the "both" option the owner
   had declined. The final Cline plugin runs ONE full enforcer pass with `ENFORCER_LEDGER=defer` and
   `ENFORCER_JEV_TIER=typesafe` (TypeSafe's full route), plus the embedding preview pass
   (`ENFORCER_JEV_ROUTER=0`, `defer`). The first model call (2 s wait) carries the full TypeSafe menu when
   ready, else the preview; later calls carry the full menu once it lands. Offer-row `seen` is `full` or
   `preview` (or `late`); a full row that lands after the preview was sent is `ev: "offer_late"`. Command Code
   is never called for Cline turns. Removed before release: `ENFORCER_EARLY_MENU` and `_emit_early`, the
   backup timer, and the Command Code early wide menu in Cline. Kept for every harness: the staged safety net
   (Decision 2), lift ordering (Decision 6), `ENFORCER_JEV_TIER` and `ENFORCER_LEDGER=defer`.

## Alternatives rejected

- **Wide-only first menu everywhere.** Rejected for the 10-second harnesses by Decision 7 (small saving, real
  accuracy and verdict loss).
- **Raise Cline's 2 s first-call wait.** Not possible without risk: the hook limit is 3 s with no override,
  and the sandbox round trip counts against it (ADR-0086). An overrun fails the user's whole turn.
- **A separate wide-only Command Code pass for Cline.** Rejected at 22:17 for "A" (print the full pass's wide
  result early, no extra call); "A" itself was later removed (Decision 9).
- **Keeping both providers on Cline (the Decision 4 chain) and Command Code only.** The owner was offered
  TypeSafe only / keep both / Command Code only on 22:58 and chose TypeSafe only (Decision 9). Keeping both
  doubled the Jev calls per Cline turn; Command Code only is what ADR-0086 had, and its full menu lands in
  2.0 to 2.5 s, past Cline's 2 s wait.
- **A TypeSafe wide-only backup.** Considered at 22:37, replaced at 22:52: TypeSafe's full route is fast
  enough (about 0.65 s) to give Cline a reranked menu, with the "no skill fits" verdict, inside the wait.
- **An `ENFORCER_JEV_STAGE=wide` switch.** Built to make a pass return only the wide menu, tested, and
  removed before release, once the TypeSafe backup became a full route and nothing used it. It is not a flag.
- **`ENFORCER_EARLY_MENU` and the Cline backup timer.** Built (Decisions 3 and 4), then removed before
  release when the owner chose TypeSafe only (Decision 9). They are not flags and not in the code.

## Consequences

- **Evidence that the final Cline design works (live, Cline 3.0.70, 22:57 to 22:59).** Three task turns: the
  first model call carried the full TypeSafe menu (`seen: full`, `prov: typesafe`, `stage: full`) at
  751 / 673 / 822 ms, with no Command Code call and no `offer_late` row. (Fact.) A fourth turn, at 22:58:11,
  fell to the embedding fallback because the index owner was restarting: the shared engine venv stamp moved
  0.63.0 to 0.64.0 at 22:57:40 and the owner was ready at 22:58:11. That is a pre-merge testing side effect
  (the worktree and the live install share the engine venv), not a design fault.
- **Evidence from the first design (superseded, kept as history).** Gate G6 on the Decision 4 chain: three
  turns carried the TypeSafe full backup menu at 941 / 706 / 679 ms, and Command Code's full menu landed at
  2,171 / 2,008 / 2,498 ms (`offer_late`) with the same lead skill.
- **Evidence that other harnesses are unchanged (live, gate G7).** The same prompt through claude, omp,
  opencode, codex and zcode returned one output line, no early line, `stage: full`, `prov: commandcode`
  (1.7 to 2.3 s). Command Code and DSH (`ENFORCER_JEV_BUDGET=1.6`) returned `stage: full`, `prov: typesafe`
  (618 and 639 ms).
- **Billing.** Cline's Jev calls now go to TypeSafe only: two per routed turn (wide, then rerank). Command Code,
  the owner's preferred provider, serves the other harnesses' full routes. Command Code and DSH adapters
  already used TypeSafe inside their 1.6 s budget. A Cline turn that falls back to the embedding path makes
  no Jev call.
- **Expected gain, as a judgment, not a measurement.** TypeSafe's full route lands in 0.67 to 0.82 s live, well
  inside the 2 s wait, so the first call should usually carry a reranked Jev menu (replay: hit@5 75.1 % for
  full against 22.7 % for the preview, on Claude Code turns). The live sample is 3 turns.
- **Telemetry (epoch).** Cline offer rows change meaning at this release: before it, the row was the full
  menu whatever the model saw; from it, the row is the menu seen (`seen`). New fields and events:
  `stage` (`full` or `wide`) in the `jev` routing telemetry of every harness, `seen` (`full`, `preview`, `late`) on Cline offer rows, and
  `ev: "offer_late"` rows that offer counts ignore. Cline metrics before and after 0.64.0 must not be pooled,
  and any Jev metric that reads `stage` starts a new epoch (`docs/epoch-watch.md`).
- **A `stage: wide` row is a different object from a full row.** It has no `fits` verdict and no `conf`; the
  wide menu has no floor, so it shows 5 rows even on a turn the full route would have skipped. The replay
  population holds only skill-using turns and cannot measure that cost.

## Limits (what is not known)

- **The corpus is Claude Code, not Cline.** The replay used Claude Code turns, the 549-skill Claude shelf
  and the live `ctx` state. Cline's shelf is 472 skills (two chunks, 250 and 222, so a 10-name shortlist
  rather than 15) and the plugin sends no `transcript_path`, so Cline's Jev state is the bare one. On 82 of
  233 turns the replayed wide top 5 held a skill Cline cannot invoke. No Cline-view replay was run.
- **Live Cline evidence is 3 turns** (final design). TypeSafe's full-route latency distribution on Cline is
  unmeasured, and there is no Command Code fallback: a TypeSafe outage sends Cline's first call to the preview.
- **The no-skill case is unmeasured.** The population holds only turns where a skill was used.
- **Replay timings** came from one 17-minute window at six concurrent calls; the live figures above replace them.
- **Mixed scoring.** Bare-name scoring counts twin names (`doctor` and `skill-concierge:doctor`) as hits;
  strict scoring changes hit@5 by -1 / -9 / -11 hits (preview / wide / full). Immaterial to the decisions.

## Revert paths

- **Cline back to ADR-0086's provider order:** remove `ENFORCER_JEV_TIER` from the full pass's env in
  `adapters/cline/skill-concierge.cline-plugin.ts` (Cline then uses the jevd ladder, Command Code first, whose
  full menu usually lands after the 2 s wait).
- **Tier pin:** unset `ENFORCER_JEV_TIER` (any harness).
- **Honest offer row:** `ENFORCER_LEDGER=0` writes no row (the pre-0.64.0 preview setting); unset or `1` writes
  the row at once. `defer` is meant for the Cline plugin only.
- **Wide-menu safety net (every harness):** no env switch. Revert the `wide_menu` fallback at the end of
  `_jev_route` in `hooks/scripts/enforcer.py`. `ENFORCER_JEV_ROUTER=0` turns the whole Jev route off.
