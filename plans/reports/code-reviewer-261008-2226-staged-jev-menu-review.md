# Code review: staged Jev menu, deferred offer row, Cline TypeSafe-only pass

Date: 2026-10-08 (Asia/Saigon). Reviewer: independent, adversarial, read-only.
Worktree: `/Users/thinhkhuat/.worktrees/skill-concierge/cline-seen`, branch `feat/cline-offer-seen`, uncommitted changes on top of `main` (b1c7985).

## Scope

- **Revision reviewed:** the revised code (owner decision: Cline uses TypeSafe only), read after the coordinator's change notice. The first revision was also reviewed. Its early-menu and backup-pass findings are **dropped**, because that code no longer exists.
- **Files:**
  - `hooks/scripts/enforcer.py`
  - `hooks/scripts/ledger.py`
  - `adapters/cline/skill-concierge.cline-plugin.ts`
  - `tests/test_cline_plugin.py`
  - `tests/test_jev_router.py`
  - `tests/test_jev_staged_menu.py` (untracked)
  - also `tests/test_auto_flywheel.py` and `scripts/check_flag_docs_parity.py`, per the coordinator.
- **Not reviewed:** docs, README, CHANGELOG, AGENTS and openwiki (a docs agent owns them).
- **Size:** `git diff main --stat` gives 252 insertions and 58 deletions across 7 tracked files, plus the new 100-line test file.

### Method: what I ran and what I only read

All runs used copies under `$TMPDIR` with the `.git` link removed. There were no network, Jev, jevd or Cline calls. Every Jev call was faked in-process.

| Check | Result |
|---|---|
| Scoped tests (cline_plugin, jev_staged_menu, jev_router, auto_flywheel, flag_docs_parity, jevd_bench) | 74 passed, 1 failed. The failure is `test_flag_docs_parity::test_real_tree_is_in_parity`: AGENTS.md still documents the removed `ENFORCER_EARLY_MENU`. |
| Full `tests/` | 1095 passed, 4 failed. One is the same parity failure. Three are environmental: two need git history (`git show 7e6cecf`, `git ls-files`), which the copy lacks by design. The third trips on an untracked `vendor/skill-search/build/lib` artifact that `git ls-files` would normally filter out. |
| `enforcer.py --selftest` | Fails on two cross-harness scope lines. The output is byte-identical to `main`'s enforcer run in the same tree, so this is pre-existing and environmental. |
| `ledger.py --selftest` | OK. |
| Default-mode differential: the same faked turn through `main()` on `main` and on this branch | Stdout is byte-identical (sha `3b2f7d60e3…` on both). The only change in the ledger row is the new key `jev.stage: "full"`. |
| Probes in `$TMPDIR/cr-probes/` | `probe_safety_net.py`, `probe_pin_nan.py`, `e2e_wrapper.py`. Results are quoted in each finding. |

Everything else below is from reading the code, and is labelled that way.

### Edge-case scout (what the diff does not show)

- The safety net's result travels through `_jev_join`, which has its own deadline. That deadline is computed separately from the route's deadline.
- `ENFORCER_JEV_TIER` interacts with the jevd-down fallback in `_jev_bench()`.
- Wide-pass probabilities were never validated. Before this change they only ordered the shortlist; now they are displayed and logged.
- `scripts/calibrate_jev_gate.py` reads the `jev` field of offer rows.
- The `__main__` deferred write sits outside `main()`'s exception boundary.

## Overall assessment

- **Default (non-Cline) harnesses:** output is unchanged, except for the safety net, which matches the owner's locked decision. I proved this by the differential run.
- **Deferred ledger and Cline accounting:** the `ENFORCER_LEDGER=defer` contract and the plugin's single-offer-row accounting are correct in every timing order I traced.
- **Defects found:** four real ones.
  1. The safety net is unreliable in the very case it exists for: every tier's rerank timing out.
  2. A non-finite wide probability now empties the whole turn, which is a regression from `main` for every harness.
  3. The Cline pin silently turns Jev off whenever jevd is not answering.
  4. The tree currently fails the flag-docs parity gate.

None is a security or data-loss issue.

## Critical issues

None.

## High priority

### H1. The safety net loses a race with `_jev_join`'s deadline when the last tier's rerank runs to the budget

- **Where:** `enforcer.py:2435`, `enforcer.py:2525-2528`, `enforcer.py:2550`, `enforcer.py:2561`.
- **What happens:**
  - Two deadlines exist, computed separately:
    - The route's deadline is `deadline = t0 + JEV_BUDGET_S`, with `t0` taken inside the worker thread.
    - `_jev_join` uses `time.time() + JEV_BUDGET_S`, taken in the main thread right after `t.start()`.
  - When the last eligible tier's rerank is capped at `tdl - time.time()`, the route reaches the safety-net `return` a few ms after its deadline. That is essentially the same instant `_jev_join` gives up.
  - Whichever side wins decides the outcome:
    - If the join wins, `t.is_alive()` is true and `_JEV_EVENT = {"err": "BudgetExceeded"…}`. The function returns `None`, so the turn falls to the embedding menu, exactly as before the change.
    - If the route wins, the wide menu is shown.
- **Measured (offline, faked Jev, rerank never answers):**
  - Scaled single tier (budget 1.2 s, tier timeout 1.0 s): the safety net held in **4 of 10** runs on the current code. On the first revision it held in 6 of 10.
  - Production-shaped ladder (`cc` span 5.5 s then `ts` 1.5 s, budget 7.8 s): the safety net held in **1 of 4** runs (2 of 4 on the first revision).
- **Concrete failure:**
  - A Claude Code turn on the live bench where Command Code's rerank times out at 5.5 s.
  - TypeSafe then gets about 2.3 s: wide about 1 s, then a rerank capped at about 1.3 s, which also hangs.
  - Result: a coin-flip between the wide menu and the embedding menu, with `BudgetExceeded` logged and the wide answer discarded.
  - The owner's "safety net" decision is therefore only partly in effect, and in a nondeterministic way.
- **Where it does not apply:** the Cline pass, pinned to a single TypeSafe tier, is mostly unaffected. Its rerank cap is 1.5 s, well inside the 7.8 s budget, so it returns early.
- **Fix:** make the kept wide menu reachable from the join, not only from the route's `return`.
  - Have `_jev_route` write `box["wide"] = (rows, wide_ev)` as soon as the menu exists (`_jev_start` would pass `box` in).
  - In `_jev_join`, when `t.is_alive()`, return `("offer", rows, None, [])` with `{**wide_ev, "fell": …, "err_join": "BudgetExceeded"}` instead of `None`.
  - Add a test with a rerank that hangs past the budget. No current test covers this; `test_blown_budget_is_abandoned` replaces `_jev_route` wholesale.

### H2. A non-finite wide probability now empties the whole turn, in every harness (regression from `main`)

- **Where:** `enforcer.py:2161-2182` (`_jev_wide_rows` takes `float(pr[n])` unchecked), `enforcer.py:2181`, `enforcer.py:3085`.
- **What happens:**
  - `_jev_decide` rejects NaN, inf and out-of-range rerank probabilities (`prob()`). The wide answer gets no such check.
  - With one NaN in a wide answer, `lifts` holds NaN, so `total` is NaN. The guard `or 1.0` does not fire, because NaN is truthy. Every share becomes NaN.
  - On the safety-net path, `_ranked_mandate` evaluates `round(score / total * 100)` and raises `ValueError: cannot convert float NaN to integer`. `main()`'s fail-silent `except` swallows it.
- **Measured (`e2e_wrapper.py`, wide answer `{"ak-git": NaN, "tk-research": 0.7}`, rerank refused):**

  | Tree and mode | Stdout | Ledger rows |
  |---|---|---|
  | This branch, default mode | 0 bytes | 0 |
  | This branch, defer mode | 0 bytes | — |
  | `main`, same input | 1070 bytes (embedding menu) | 1 offer row |

- **Consequence:** where `main` fell back to the embedding menu, this branch shows no menu and writes no ledger row at all. The fallback/coverage counts also lose the turn silently. In addition, `json.dumps` writes bare `NaN` into offer rows (`"offered": [["ak-git", NaN], …]`), which is invalid JSON for any non-Python reader.
- **Fix:** validate in `_jev_wide_rows` with the same rule as `prob()` (finite, between 0 and 1). Drop or raise on a bad entry, so the tier's existing `except` and `fell` path handles it. Add a test with a NaN and an inf wide answer.

### H3. `ENFORCER_JEV_TIER=typesafe` switches Jev off for Cline whenever jevd is down, slow (over 0.3 s) or unset

- **Where:** `enforcer.py:2431-2432`, `adapters/cline/skill-concierge.cline-plugin.ts:45` and `:211`.
- **What happens:**
  - The pin matches `t.get("name")` or `t["model"]`. Only jevd ladder tiers carry a `name`.
  - When jevd does not answer, `_jev_bench()` deliberately falls back to `ENFORCER_JEV_BENCH`. Its own docstring says this is so a dead jevd "must not switch Jev off".
  - The env-bench TypeSafe tier is `{"ep": "ts", "model": "jev-1.13.0"}`: it has no name, and its model is not `"typesafe"`. So the pinned bench is empty, and `_jev_route` returns `{"result": None, "event": None}` without a single call.
  - Probe output: `pin typesafe, env bench -> {'result': None, 'event': None} calls: []`.
- **Consequence:**
  - Cline's "full" pass becomes a second embedding menu.
  - The ledger logs it as `seen: "full"` with no `jev` key.
  - Before this change, the same situation still routed through the env bench's TypeSafe tier, because the full pass had no pin.
  - The local configuration (`~/.config/harness-env.sh:85` sets the env bench; `:95` sets `JEVD_URL`) makes this fallback the live path whenever jevd is down. jevd's uptime and Cline's environment were not checked (see the open questions).
- **Fix:** let the pin match the env tier by endpoint too. For example, map `{"ts": "typesafe", "gw": "gateway", "cc": "commandcode"}` over `t["ep"]` (the names jevd uses in `tests/test_jevd_bench.py:32-34`), or pin by model `jev-1.13.0`. Add a test that pins `typesafe` with jevd absent and asserts that a TypeSafe call is made. The current pin test uses only a model id on the env bench.

## Medium priority

### M1. The tree fails the flag-docs parity gate

- **Problem:** `scripts/check_flag_docs_parity.py` reports `AGENTS.md says ENFORCER_EARLY_MENU defaults OFF, but no code default for it was found`, so `tests/test_flag_docs_parity.py::test_real_tree_is_in_parity` fails.
- **Cause:** the flag was removed from the code, but its AGENTS.md row (the docs agent's lane) is still there. This may resolve when the docs agent finishes. Re-run the check before landing.
- **The parity-script change itself (`UNSET` accepts `(empty)`)** reads correctly. When the cell is empty, `v = m.group(1) or ""` is then checked against `strings[flag]`. That relies on `code_strings()` capturing `""` from `os.environ.get("ENFORCER_JEV_TIER", "")`. The new path is test-covered according to the coordinator; I did not re-read that test.

### M2. Safety-net rows count as successful routes in `calibrate_jev_gate.py live`

- **Where:** `scripts/calibrate_jev_gate.py:637` and `:696`.
- **Problem:**
  - `jev_kind` classifies any `jev` that has `via` as `"router"`.
  - `cmd_live` treats every such row without `err` as "routed" and feeds its `ms` into the W23 latency percentiles.
  - Safety-net rows (`stage: "wide"`, `fell` set, no `err`) are rerank failures, yet they will now count as routed turns. Their `ms` is the full failed-ladder time.
- **Effect:** the W21–W24 routed and error counts shift at this epoch boundary for a reason that is not router quality.
- **Fix:** split on `jev.get("stage")` in the analyzer. Also name `stage` in `docs/epoch-watch.md`, which is the docs agent's lane.

### M3. The deferred final write is outside the fail-silent boundary

- **Where:** `enforcer.py:4737-4740`.
- **Problem:** `json.dumps(_DEFERRED)` and `sys.stdout.write` run after `main()` returns, outside its `try`.
  - Any non-serialisable value in the offer row would surface as a traceback with exit code 1. The Cline `run()` maps a non-zero exit to `null`, so both the menu and the row would be lost.
  - In non-defer mode the same error is caught inside `_append_offer` and only the row is lost.
- **Likelihood:** low. Every field I read is a JSON type. But the hook doctrine is "a hook never lets an error escape".
- **Fix:** wrap the write in a try. On failure, write `{"hookSpecificOutput": …}` alone.

## Low priority

- **L1. HistorySkip early return bypasses the safety net** (`enforcer.py:2501`). With `ENFORCER_JEV_HISTORY=1`, the history-skip guard returns `None` even when a wide menu is held. This is inconsistent with "no tier finished its rerank → wide menu". The flag is OFF by default.
- **L2. Dead code left by the revision:**
  - `_offer_ev(..., jev=None)` (`enforcer.py:1559`) no longer has a caller passing `jev`.
  - `if True:` (`enforcer.py:1570`) is an indentation shim.
  - The `_offer_ev` docstring still says "Append the offer event. Fail-silent", but it only builds the event.
  - `tests/test_jev_router.py:207` keeps a `*_w` parameter that existed for the removed `on_wide` watcher.
- **L3. UTF-8 split in the plugin's stdout reader** (`skill-concierge.cline-plugin.ts:78`, `out += String(d)`). This is pre-existing and not introduced here. A multi-byte character split across pipe chunks becomes U+FFFD. I proved it in node: `❤️🔥` became `❤️���`. Badges (ADR-0083) are 4-byte emoji. `child.stdout.setEncoding("utf8")` fixes it.
- **L4. The case for lift ordering is weak by its own numbers** (`enforcer.py:2161` docstring). It cites top-5 70.8 % for lift against 71.2 % for raw order, so lift is not better on the replay. I did not verify the replay. Raw order would be one line shorter; lift is a judgment call.
- **L5. `ENFORCER_LEDGER=defer` outside Cline** adds a top-level `skillConciergeOffer` key to Claude Code hook JSON. How Claude Code treats unknown keys is unverified. No consumer sets it today, but `harness-env.sh` is shared across harnesses, so a stray export would reach all of them.

## Verified correct (for calibrating risk)

- **The `_append_offer` → `_offer_ev` split:**
  - Every keyword the callers pass (`dropped, embed_ms, qdrant_ms, ext, xh, n_intents, route, hint, pulled`) is in the new signature.
  - `badges` and the `_JEV_EVENT` attachment are unchanged when `jev` is `None`.
  - The exception list around the build is identical to `main`'s, so nothing new escapes.
  - Shown by reading and by the byte-identical differential run.
- **The safety-net verdict through `main()` and `_jev_serve`:**
  - The tuple `("offer", rows, None, [])` is safe: `_jev[2]` and `best` are formatted only on the `skip` path (`enforcer.py` main and `_jev_serve`).
  - `wide_ev["lead"]` is always set, because `_jev_wide_rows` raises rather than return `[]`.
  - `_jev_wide_rows` cannot raise where `_jev_shortlist` succeeded. Both filter top-5 per chunk by catalogue membership, and the key parsing fails in the shortlist first. So a tier's rerank is never skipped by this change.
- **Defer mode:** one JSON object at exit containing `hookSpecificOutput` and `skillConciergeOffer`, and no ledger write. Shown by an end-to-end run and by `test_enforcer_ledger_switch[defer]`.
- **Cline accounting:**
  - **One `ev: "offer"` row per turn:**
    - full ready at the first call → `seen: full`;
    - preview shown → `seen: preview`, and later a single `offer_late`;
    - nothing ready → `seen: none`, and the full row is logged on arrival as `seen: late`;
    - full arrives between the end of the wait and `recordSeen` → consistent, because `fullDone` reads `state.value`, which `settle` sets.
  - **No duplicate `offer_late`:** `recordSeen` logs it only when `fullDone`, and `settle` only when `seen` was set before the full pass landed. These are mutually exclusive.
  - **Accepted gaps (shown by reading):** zero rows when the full pass fails and the preview has no text, or when a run never reaches a model call.
- **ledger.py:** `ConciergeOffer` appends only dict rows whose `ev` is `offer` or `offer_late`. Tested, including junk input.
- **tests/test_auto_flywheel.py:** the `_flywheel_locked` stub targets a function that exists (`auto_flywheel.py:160`). It isolates tests from the machine's live lock and is a sound fix for the reported mid-suite failures.

## Test quality

- **Behavioural, not mock-only:** `test_enforcer_ledger_switch[defer]` and `test_ledger_appends_a_handed_back_offer_row` run the real scripts.
- **Faked only at the call layer:** the staged-menu tests fake only `_jev_call`, the catalogue and the context, and run the real `_jev_route`.
- **Timing margins:** the plugin timing test uses a 3.5 s stub, a 2 s wait and a 2.5 s pause, which leaves about 1 s of slack on each side. I judge it low-risk for flakiness.
- **Not covered:**
  - the deadline race (H1);
  - non-finite wide probabilities (H2);
  - the `typesafe` pin without jevd (H3);
  - the `seen: "late"` path (nothing ready at the first call);
  - a full pass that fails while the preview was shown (no `offer_late`);
  - `ENFORCER_JEV_HISTORY` combined with the safety net.

## Recommended actions, in priority order

1. **H2:** validate wide probabilities in `_jev_wide_rows`, and add the NaN and inf test. This is a regression from `main` for every harness.
2. **H3:** make the `typesafe` pin match the env-bench TypeSafe tier, and add a jevd-absent test.
3. **H1:** expose the wide menu to `_jev_join` so the budget timeout keeps it, and add a hanging-rerank test.
4. **M1:** re-run `scripts/check_flag_docs_parity.py` after the docs agent finishes; it must exit 0.
5. **M2:** split `stage` in `calibrate_jev_gate.py live`, or record why not.
6. **M3, then L2:** cheap hardening and cleanup.

## Metrics

- **Type coverage:** not applicable. The Python is untyped; the TypeScript was not type-checked, because the repo runs the plugin through node's type stripping and has no `tsc` config in scope.
- **Test coverage:** not measured.
- **Lint:** not run (no linter configured in scope).

## Unresolved questions

1. **Is jevd reliably up, and does Cline's process environment carry `JEVD_URL`?** If Cline is launched from a GUI, it may not source `~/.zshenv`. This decides how often H3 fires. Not checked: probing the live daemon or Cline was out of bounds.
2. **H1:** does the owner want the safety net to hold on a budget timeout, or only when every tier fails quickly? The code comment says "no tier finishes its rerank", which covers timeouts.
3. **L5:** does Claude Code tolerate an unknown top-level key in UserPromptSubmit hook JSON? Unverified.

**Status:** DONE_WITH_CONCERNS

**Summary:** Default-harness output is unchanged and the Cline single-offer-row accounting is correct, but the safety net is lost to a join-deadline race on budget timeouts. A NaN wide probability now empties the whole turn (a regression from `main`), and the Cline `typesafe` pin turns Jev off whenever jevd is not answering.
