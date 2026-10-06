# ADR-0080: jevd is the Jev bench's single source; the hook still walks the ladder

- **Status:** Accepted (2026-10-06, owner's decision via `AskUserQuestion`, about 23:00). Enabled on this machine by
  `JEVD_URL` in `~/.config/harness-env.sh`. Without it the hook behaves as before.
- **Amends:** ADR-0075 and ADR-0079 on one point, where the bench comes from. Their tier logic (order, failover,
  spans, budget) is unchanged. ADR-0079 stays the record of the Command Code tier and is not edited.

## Context

ADR-0075 and ADR-0079 define the bench in an environment variable, `ENFORCER_JEV_BENCH`, plus per-tier timeouts and
keys read by the hook. The owner now runs `jevd` (`github.com/thinhkhuat/jevd`, v0.2.0), a local relay for
SystemOne endpoints that holds the provider keys and keeps warm connections. He wants one place to configure the
ladder: `~/.config/jevd/config.toml` (order, models, per-call `timeout_s`, per-turn `span_s`, keys).

Fact: a router turn is two linked calls, a whole-catalogue ranking and then a rerank that must go to the **same**
provider (`hooks/scripts/enforcer.py`, `_jev_route`). So jevd cannot pick a provider per request: the hook has to
carry the choice from the first call to the second.

The owner chose among three designs. His chosen option, verbatim: "jevd config, hook switches (Recommended)".
Rejected: "jevd switches, hook pins 2nd call" (a time-split guess; a late Command Code answer can leave TypeSafe too
little time) and "jevd runs the whole job" (jevd becomes skill-concierge-specific).

## Decision

1. **jevd is the source of the ladder; the hook walks it.** `_jevd_ladder()` (`hooks/scripts/enforcer.py`) reads
   `GET {JEVD_URL}/ladder` with a 0.3 s limit (`JEVD_LADDER_TIMEOUT_S`). Each provider becomes one bench tier: name
   (the pin), model, per-call `timeout`, `span` when jevd sets `span_s`, and whether jevd holds its key.
   `_jev_bench()` returns that ladder when jevd answers, else the `ENFORCER_JEV_BENCH` path of ADR-0075 and ADR-0079.
2. **Command Code's 5.5 s per-turn span is now jevd's `span_s = 5.5`.** `ENFORCER_JEV_CC_TIMEOUT` still governs the
   direct `cc` tier used when jevd is absent. The tier logic that spends a span (ADR-0079 decisions 2 to 4) is
   unchanged.
3. **A jevd tier sends no key.** `_jev_key` returns the marker `"jevd"` for a tier jevd holds a key for, and an empty
   string otherwise (the tier is then skipped as `NoKey`). The marker is never sent. `_jev_call` POSTs
   `{JEVD_URL}/v1/systemone` with `X-Jevd-Provider` (the pin) and `X-Jevd-Budget` (this call's limit), no
   `Authorization`, and reports `via="jevd"`. jevd answers a pinned request with the provider's answer as it is,
   a 429 and its `Retry-After` included (jevd side, per the owner's brief).
4. **Telemetry.** The router event gains `prov`, the jevd provider name (`hooks/scripts/enforcer.py`, the event
   built beside `"to"`). `via` reads `jevd` or, on the old paths, `relay` or `direct`.
5. **jevd is optional and loopback only.** `JEVD_URL` is accepted only as `http` to `127.0.0.1`, `localhost` or
   `::1`; anything else is ignored. Unset, or jevd silent within 0.3 s, the `ENFORCER_JEV_BENCH` direct path runs
   unchanged, so a user without jevd is unaffected. The index owner's `/jev` TypeSafe relay (ADR-0070) stays as that
   fallback's warm path (owner's choice: "Keep as fallback (Recommended)").
6. **The offline client follows.** `scripts/jev_client.py` takes its tiers from `_jev_bench()`, so it uses jevd's
   ladder too.
7. **Tests** run without the live relay: `tests/conftest.py` also strips `JEVD_URL`.

The ladder on this machine (jevd config, 2026-10-06): `commandcode` (`typesafe/jev`, 5.5 s call, 5.5 s span),
`typesafe` (`jev-1.13.0`, 1.5 s), `gateway` (`openrouter/typesafe/jev-1.13`, 2.0 s), `gateway-oc`
(`oc/jev-1.13-free`, 2.0 s), `gateway-ocz` (`ocz/jev-1.13-free`, 2.0 s). It mirrors the previous
`ENFORCER_JEV_BENCH`. The harness-env line `ENFORCER_JEV_CC_URL` was removed, because it sent only the `cc` tier
through jevd; `JEVD_URL` stays.

## Review fixes

An independent review (`plans/reports/code-reviewer-261006-2315-jevd-integration.md`) found defects in the first
jevd integration. This ADR was still unreleased, so they are recorded here and the Decision above is read with
them.

- **H1: consult widening went dark when jevd answered.** `jev_top` in `scripts/consult_fit.py` and `jev_setup` in
  `scripts/sieve_recall.py` kept only `ep == "ts"` tiers, and a jevd ladder has none. Both now pick the env bench's
  first `ts` tier, or the jevd rung that serves `enf.JEV_MODEL` (the TypeSafe model ADR-0078 was gated on). Repro
  without `tests/conftest.py` and with `JEVD_URL` set: the old code failed 15 of 42 `test_consult_widen` tests, the
  new code 2, both expected (the owner's brief).
- **H2: a late rerank was refused by jevd.** Fixed on the jevd side: its commit 0.2.0 (latest on
  `github.com/thinhkhuat/jevd`) sends a pinned call with its own budget even with under 1 s left. Per the owner's
  brief; not re-read here.
- **H3: the calibrator re-sent timeouts.** `call` in `scripts/calibrate_jev_gate.py` now sends a jevd tier through
  the hook's own `_jev_call` and never re-sends a timeout (it re-sent four times, which bills four times).
- **M1: the turn clock.** `_jev_route` starts its clock before the ladder fetch, so the fetch spends the turn's
  budget, and a non-English turn never fetches the ladder (`hooks/scripts/enforcer.py`, `_jev_route`).
- **M2: a jevd holding no keys no longer switches Jev off.** `_jev_bench()` uses jevd's ladder only when at least
  one tier is keyed; otherwise `ENFORCER_JEV_BENCH` stays in charge.
- **M4: telemetry says which source ran.** Every event the router emits (none when it does not run: router off, non-English prompt, no keyed tier) carries `"bench": "jevd"` or `"env"`. The calibrator's
  live report counts `via` = `jevd` as well as `relay` and `direct`.
- **Low:** a `JEVD_URL` given with the trailing `/v1/systemone` still names the service (the suffix is stripped);
  the `scripts/jev_client.py` docstring is corrected.
- **Judgment call (labeled), the reviewer's open question.** When jevd answers but every provider fails mid-turn,
  the hook does **not** retry the same providers direct: they would meet the same upstream failures and bill twice.
  The embedding path decides that turn. The next turn falls back to `ENFORCER_JEV_BENCH` if jevd itself is down.

## Verification (2026-10-06)

- **Tests:** `tests/test_jevd_bench.py`, 7 tests against a fake jevd on loopback (ladder as the bench, one provider
  pinned per turn with no key, failover down the ladder, a provider jevd has no key for is skipped, jevd down leaves
  the env bench in charge, a non-loopback URL is ignored, the offline client uses the same tiers). Control run on the
  committed pre-change code: 6 of 7 fail; the seventh, the jevd-down fallback, is satisfied by the old code too. The
  Jev suites pass (100 passed).
- **Live, about 23:10, Command Code only** (`plans/261006-2034-commandcode-jev-endpoint/perf/live-jevd-hook.txt` and
  `live-jevd-hook-down.txt`): through jevd, 5 turns were served by `commandcode` in 1.53-2.18 s, every call on a
  reused connection. One turn went to TypeSafe (`fell` = `typesafe/jev`, `NoTime`) because the test's 5.6 s budget
  minus the catalogue read left Command Code under its 5.5 s: a test-harness fault, not a product finding. With jevd
  stopped, 2 turns went direct to Command Code in 3.82 s and 4.79 s.
- **jevd side** (owner's brief, jevd repo commits 968c753, 9905a91, a5c9166): `GET /ladder`, `span_s`, a pinned
  request with an explicit budget takes it as its call limit, and a keyless GET warms the Command Code connection.
  Measured by the owner: a bare TCP+TLS connection was dropped within 15 s; after a keyless GET it was kept 180 s,
  and the warmed connection served calls after 60 s and 150 s idle in 0.87-0.88 s.
- **Not verified here:** the jevd repository itself and its config file were not read for this ADR; the jevd
  facts above are the owner's.

## Consequences

- **One place to change the ladder** (jevd's config), instead of an env var per harness. The hook keeps the
  decision logic (links the two calls, spans, budget), so jevd stays generic.
- **Warm connections for Command Code.** In the live run turns took 1.53-2.18 s through jevd against 3.82-4.79 s
  direct. Two small samples, not a rate; W39 reads real traffic.
- **A new failure surface, bounded.** A dead jevd costs at most 0.3 s per turn (the ladder probe) and then the old
  path runs. A live jevd that fails a provider moves the turn down its ladder as any tier does.
- **No key reaches the hook for jevd tiers.** Keys live in jevd's config. The direct fallback still needs the env
  keys.
- **Router metrics split by path.** Rows now carry `prov` and `via`; read W21-W24 and W38 per path (see
  `docs/epoch-watch.md`, W39).
- **Judgment call (labeled):** keeping the hook as the ladder walker costs a second implementation of the ladder
  semantics (the hook's, not jevd's) but avoids a skill-concierge-specific jevd. The owner chose it.

## Revert

Unset `JEVD_URL`, or remove its line from `~/.config/harness-env.sh` (backup:
`~/.config/harness-env.sh.bak-261006-jevd-ladder`). The hook then uses `ENFORCER_JEV_BENCH` directly, as ADR-0079
describes.
`ENFORCER_JEV_ROUTER=0` turns the router off entirely.
