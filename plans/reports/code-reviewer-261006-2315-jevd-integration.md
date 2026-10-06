# Code review: jevd as the enforcer's Jev bench (uncommitted)

Reviewer: code-reviewer subagent, blind and adversarial, read-only. Date: 2026-10-06.
Scope: the jevd parts of the diff in `hooks/scripts/enforcer.py` (`JEVD_URL`, `_jevd_ladder`, `_jev_bench`,
`_jev_key`, the jevd branch of `_jev_call`, `prov` in the `_jev_route` event), `scripts/jev_client.py`,
`tests/test_jevd_bench.py`, `tests/conftest.py` (untracked). Where they interact, I also looked at the ADR-0079 changes in the
same diff (`_jev_call_capped`, span tiers, fall-through). I read jevd's `src/jevd/{server,router,upstream,config}.py`
and README to check the contract on the jevd side.
Method: I read the code and reproduced each finding offline. Every server was on loopback: fake jevds, fake
upstreams, and the REAL jevd `Router`/`Server` imported from the jevd repo (run with `-B`, so no bytecode was
written) with its providers pointed at loopback fakes. I made no network calls to any Jev provider or to the live
jevd. Throwaway scripts lived in a temp dir, now deleted.

## Test run (requested)

`~/.claude/skills/.venv/bin/python3 -m pytest -q tests/test_jevd_bench.py tests/test_jev_bench.py tests/test_jev_client.py`
-> `71 passed in 4.20s`.
Broader selection (`-k "jev or consult or widen or sieve or trigger_filter or calibrat"`) -> `343 passed, 639 deselected`.
These suites pass only because `tests/conftest.py` deletes `JEVD_URL` before collection. See M3 and H1.

## High

### H1. Consult widening and the sieve-recall instrument switch off silently whenever jevd answers
- `scripts/consult_fit.py:392-394` (`jev_top`) and `scripts/sieve_recall.py:1626-1628` (`jev_setup`) keep only
  `t["ep"] == "ts"` from `enf._jev_bench()`. When jevd answers `/ladder`, every tier has `ep == "jevd"`, so the
  filter leaves nothing. `jev_top` then raises `JevError("no ts tier or no TYPESAFE_API_KEY")`, and `widen()`
  returns the sieve rows with `state: not-widened`. This disables `SKILL_CONSULT_JEV_WIDEN`, which is default ON and
  shipped on a held-out gate (ADR-0078), with no error anywhere. `sieve_recall` raises `EngineError`.
- Reachability: `~/.config/harness-env.sh` has one `export JEVD_URL=` line (I counted the line and did not read its
  value), and a process listens on 127.0.0.1:4377. My inference is that fresh agent shells running
  `consult_fit.py widen` take the jevd path now.
- Reproduction 1 (fake jevd, stubbed `ask_fn`):
  `jevd up -> jev_top FAILED: JevError no ts tier or no TYPESAFE_API_KEY` / `jevd up -> widen state: not-widened`;
  `jevd unset -> widen state: widened`.
- Reproduction 2 (the existing suite): `JEVD_URL=<fake jevd> pytest --noconftest tests/test_consult_widen.py` gives
  `14 failed, 28 passed`, for example `AssertionError: assert ('sieve' == 'both'`.
- Fix: choose the tier by model, not by endpoint, so the gated model (jev-1.13.0) is still the one used, e.g.
  `[t for t in enf._jev_bench() if t["ep"] in ("ts", "jevd") and enf._jev_model_base(t["model"]) == enf._jev_model_base(enf.JEV_MODEL)]`.
  For jevd tiers, key presence comes from `_jev_key`, which already returns the marker. Add a widen test that runs
  with a fake jevd up.

### H2. jevd refuses any pinned call whose budget is under 1.0 s, but the hook sends reranks with as little as 0.5 s
- jevd `src/jevd/router.py:112`: `if left < min(p.timeout_s, MIN_START_S)` (`MIN_START_S = 1.0`, line 17) applies to
  pinned requests with an explicit budget too. The jevd README (lines 58-61) says such a request "takes its explicit
  budget as the call limit" and does not mention this floor. The hook's own floor is `JEV_RERANK_MIN_S = 0.5`
  (`enforcer.py:1727`). Any rerank budget between 0.5 and 1.0 s therefore gets a 502 `NoTime` from jevd. The wide
  call was already billed, so the turn loses its verdict and that money is wasted.
- Worst hit: the Command Code and DSH adapters (`ENFORCER_JEV_BUDGET=1.6`). Every turn whose wide call takes more
  than about 0.6 s gets no verdict. On Claude Code it also hits the TypeSafe tier after a Command Code timeout, and
  the Command Code tier when its wide call ends with less than 1 s left in the 5.5 s span.
- Reproduction (real jevd, one provider, upstream wide 0.7 s / rerank 0.3 s, `ENFORCER_JEV_BUDGET=1.6`):
  `direct: offer {'err': None, 'via': 'direct', 'fell': None, 'ms': 1015} upstream calls: 2`
  `jevd:   None {'err': 'HTTPError', 'via': None, 'fell': [['jev-1.13.0', 'HTTPError']], 'ms': 703} upstream calls: 1`
  jevd's call log: `{'status': 502, 'fell': [['typesafe', 'NoTime']], 'budget': 0.898, 'pinned': True}`.
  With a 0.4 s wide call both paths give an offer.
- Fix (in jevd, where the contract lives): skip the start floor for `pinned and explicit` requests, because the
  client running its own ladder has already decided, e.g. `if not (pinned and explicit) and left < min(...)`. Add a
  jevd test for a pinned 0.6 s budget. Until then, the hook could treat `min(timeout, 1.0)` as the rerank floor for
  jevd tiers. That only saves the round trip; it does not recover the verdict.

### H3. `calibrate_jev_gate.py` sends the `jevd` marker as a bearer key, sends no budget, and retries billed timeouts 4 times
- `scripts/calibrate_jev_gate.py:148-150`: `tier_for` returns the jevd tier whenever its model matches `--model`.
  Lines 161-169 (`call`) then build their own request: `Authorization: Bearer jevd`, no `X-Jevd-Provider`, no
  `X-Jevd-Budget`. jevd pins by body model, but with no explicit budget it caps the call at the provider's
  `timeout_s` (1.5 s for TypeSafe), not at the script's `--timeout` (default 15.0, line 1173). `call` retries any
  exception 4 times, and every attempt is a billed upstream send.
- The marker also reaches jevd as `client_key`. If jevd has no key of its own for that provider at call time (for
  example after a jevd restart between `/ladder` and the call), `router.py:107-108` forwards `Bearer jevd` upstream.
- Reproduction (real jevd, upstream answers in 2.0 s, timeout 15): `call -> err=HTTPError after 6.0s; jevd saw 4
  requests: {'client_key_is_marker': True, 'budget': None, 'provider': None}` / `upstream (billed) sends: 4`.
  The direct path would answer on the first send.
- Fix: route `call()` through `enf._jev_call(state, qs, tier, key, timeout)`. That already pins, sends the budget,
  omits Authorization for jevd and checks the model (`JevModelMismatch`). Also stop retrying a timeout: it was
  probably billed. Alternatively, make `tier_for` build a direct tier when `--endpoint` is given explicitly.

## Medium

### M1. The `/ladder` GET runs before `_jev_route`'s clock starts, so the router outlives the join and sends calls after the hook has given up
- `enforcer.py:2154` calls `_jev_bench()` (and so `/ladder`, up to 0.3 s) before `t0 = time.time()` at 2157. The
  join deadline is set at thread start (`_jev_start`, `time.time() + JEV_BUDGET_S`). The router's own deadline is
  therefore later than the join's by the ladder's latency. Its last call can be sent with a full limit and answered
  after `_jev_join` has recorded `BudgetExceeded`: the call is billed and its answer discarded. The event `ms` also
  leaves out the ladder time, which understates the W23 latency.
- The same placement means every turn pays the ladder GET before eligibility is checked, including non-English
  turns and turns with no keyed tier.
- Reproduction (fake jevd, budget 1.6, tier `a` hangs with span 0.5, tier `b` timeout 1.0, its rerank takes 0.9 s):
  ladder delay 0.0 -> `join returned at +1.47s result=offer`;
  ladder delay 0.28 -> `join returned at +1.61s result=None event={'err': 'BudgetExceeded', 'ms': 1600, 'leg': 'router'}`
  and `POST prov=b wide=False sent +0.84s budget=1.000 answered +1.74s AFTER the hook gave up`.
  Vietnamese prompt -> `non-English prompt -> /ladder GETs: 1`.
- Fix: start the clock once and share it. Pass the thread start time from `_jev_start` into `_jev_route` and set
  `deadline = start + JEV_BUDGET_S`. Check `JEV_ROUTER and _is_english(prompt)` before fetching the ladder.

### M2. A jevd that answers but holds no keys turns the router off with no ledger trace, even when the hook has its own keys
- `enforcer.py:2027-2029` returns the ladder whenever it parses. If every tier has `key: false` (env file missing,
  key refused for whitespace), `_jev_route` (2155) returns `{"result": None, "event": None}`, so the ledger gets no
  `jev` field at all. This happens even though `TYPESAFE_API_KEY` and `ENFORCER_JEV_BENCH` would work.
- Reproduction: `route result: {'result': None, 'event': None} | bench: [('jevd', 'typesafe')]` with
  `TYPESAFE_API_KEY` and `ENFORCER_JEV_BENCH=ts:jev-1.13.0` set.
- Fix: use jevd's ladder only if `any(t["keyed"] for t in ladder)`, otherwise fall back to the env bench. Either way,
  log an event naming the reason (e.g. `{"err": "NoKey", "bench": "jevd"}`).

### M3. The tests pass for the wrong reason, and the guard they depend on is untracked
- `FakeJevd` (`tests/test_jevd_bench.py:34-77`) answers any budget and has no start floor, so H2 cannot show up in the
  suite. Nothing covers a slow or hung `/ladder` (M1), a keyless ladder (M2), consult or calibrate through jevd (H1,
  H3), or that the hook's wall-clock cap equals the `X-Jevd-Budget` it sends. Only `0 < budget <= 5.5` is asserted.
- `tests/conftest.py` is untracked (`git log --all -- tests/conftest.py` is empty) but load-bearing. Without it
  (`--noconftest`), with `JEVD_URL` pointing at a fake jevd: `test_jev_router.py: 3 failed, 17 passed` with 19
  `/ladder` GETs to the jevd, `test_jev_relay_timeout.py: 3 failed`, `test_jev_client.py: 5 failed, 36 passed`,
  `test_consult_widen.py: 14 failed, 28 passed`. Those were GETs to my fake. Against the live jevd, a test that
  reaches `_jev_call` would POST to real providers. My run did not prove that (0 POSTs observed).
- Fix: commit `tests/conftest.py` in the same commit as the enforcer change. Make the fake jevd enforce jevd's
  documented rules (budget as the call limit plus the floor), or add one contract test against jevd's real `Router`
  when the jevd package is importable (skip otherwise, since jevd is optional). Add tests for a slow ladder, a keyless
  ladder, and widen/calibrate with jevd up.

### M4. Telemetry cannot tell jevd turns or providers apart
- `enforcer.py:2224` records `fell` as `[tier["model"], err]`. jevd's ladder can list several providers under the
  same model, and reproduction 7 gives `fell=[['jev-1.13.0', 'TimeoutError'], ['jev-1.13.0', 'JevModelMismatch']]`,
  where you cannot tell which provider failed. Error events (2235, and `BudgetExceeded` in `_jev_join`) carry no
  `prov` and no bench marker. Only successful rows show `via: "jevd"`. `tier` now indexes jevd's ladder, not
  `ENFORCER_JEV_BENCH`. Because the bench switches per turn with jevd's health, the epoch rule in AGENTS.md needs
  every row to say which bench produced it.
- `scripts/calibrate_jev_gate.py:689` (`cmd_live`) tallies `via` over `("relay", "direct")` only, so jevd turns
  disappear from the W23 `via` line.
- Fix: add `"bench": "jevd"|"env"` to every router event, errors included. For jevd tiers, put the provider name in
  `fell` entries, either as a third element or with `tier.get("name", tier["model"])`, after checking the analyzers.
  Add `"jevd"` to the live `via` tally.

## Low

- L1. `scripts/jev_client.py:7-8` still says "Offline calls go direct, never through the owner's relay, which drops
  Retry-After and serves the live hook". With jevd up, offline batches go through jevd, the same process that serves
  the live hook. Functionally this is fine (reproduction 6: pinned 429 + `Retry-After` honoured, 10 s budget reached
  the provider), but the doc is stale. jevd has no concurrency cap shared between offline batches and live turns.
- L2. A `JEVD_URL` that names the API path (e.g. `http://127.0.0.1:4377/v1/systemone`, a form jevd's README
  invites for plain clients) makes `/ladder` a 404 (jevd `server.py:47` matches the exact path), and jevd is
  ignored silently. Normalize `JEVD_URL` to scheme+netloc, or document that it must be the base.

## Checked and found clean
- Key handling: the hook and `jev_client` send no `Authorization` to jevd (`test_a_turn_is_pinned_to_one_provider_with_no_key`;
  in reproduction 6 the upstream saw only jevd's own key). The `jevd` marker never leaves `_jev_call`. The one leak is
  H3's separate request builder. `_jev_direct_url(..., "jevd")` allows loopback only, and `JEVD_URL` is limited to
  http on 127.0.0.1, localhost or ::1 (test plus code at `enforcer.py:1526-1528`).
- Budget interplay: `X-Jevd-Budget` equals the hook's per-call cap (reproduction 3: `budget=0.500`, `budget=1.000`).
  With a hung pinned provider, jevd stopped at 1501 ms against the hook's 1.5 s (reproduction 7), so jevd does stop
  when the hook stops waiting. jevd's `_exchange` re-sends only when the send itself fails on a stale pooled
  connection, and checks the deadline before sending. The hook's urllib makes no retries.
- Model pin: it still works through jevd. In reproduction 7 an upstream answering `typesafe/jev-1.12.0` gave
  `JevModelMismatch` and the turn moved to the next provider. jevd returns the provider body unchanged for pinned
  calls. An upstream that omits `model` passes, as before.
- Optionality: `JEVD_URL` unset -> no I/O. Refused port -> env bench (test). Invalid ladder values (NaN, 0, -1, 1e9)
  fail safe with zero POSTs (reproduction 9: `ValueError`, `TimeoutError`, `TimeoutError`, `NoTime`).
- Hook kill: the ladder fetch runs inside the worker thread, so `_jev_join`'s bound (7.8 s, or 1.6 s on the other
  harnesses) is unchanged. No new risk of the hook being killed, only M1's wasted calls.
- `jev_client` through jevd: 429 `Retry-After` is passed through on pinned requests and honoured. The span tier gets
  its whole span offline (test).

## Not checked
- The live jevd, real providers, and real latencies. Everything here ran against loopback fakes or jevd's code
  pointed at fakes.
- The value of `JEVD_URL` in `harness-env.sh`. I counted the export line only; I did not read the value.
- Whether the Command Code and DSH adapters pass `JEVD_URL` through to the enforcer process.
- Consult's fit-matrix timing through jevd compared with the env bench, because I did not read the env bench value.
- jevd's warmer and pool behaviour under concurrent offline and live load.

## Recommended order
1. H1 (selector fix plus a test). 2. H2 (jevd router floor for pinned explicit budgets). 3. H3 (calibrate through
`_jev_call`). 4. M1 (shared clock, eligibility before the ladder). 5. M2. 6. Commit `tests/conftest.py` and harden
the fake jevd. 7. M4 telemetry. 8. L1, L2.

## Unresolved questions
- When jevd is up but every provider fails mid-turn, should the hook fall back to the direct env bench? Today the
  turn ends with no verdict. The stated intent only covers the case where `/ladder` does not answer, so I did not
  count this as a defect.
- Is it intended that jevd's ladder, not `ENFORCER_JEV_MODEL`, now sets the pinned model? It is outside
  skill-concierge's epoch commits. The router event records `model`, so it can be seen.
