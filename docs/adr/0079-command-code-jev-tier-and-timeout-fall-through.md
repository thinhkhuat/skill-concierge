# ADR-0079: Command Code as the first Jev tier with its whole 5.5 s span; any failure or a missed span falls to TypeSafe

- **Status:** Accepted (2026-10-06, owner's order); the Command Code span is an interim choice, see *Owner's decision*. Enabled on this machine by the `ENFORCER_JEV_BENCH` block in
  `~/.config/harness-env.sh`; with the variable unset the bench is still `ts:<ENFORCER_JEV_MODEL>`.
- **Amends:** ADR-0075 (the timeout rule and the bench's endpoint list) and ADR-0061 (the 3.0 s route budget cap, now 7.8 s).
  Both stay as written; this ADR replaces the stated parts.

## Context

Command Code is the owner's preferred provider (a long relationship and a bundled usage package with them). It exposes a SystemOne
endpoint, `https://api.commandcode.ai/provider/v1/systemone`, authenticated with a Bearer key (`CMD_API_KEY`, set in
`~/.config/harness-env.sh`). He ordered it onto the bench as tier 1, then chose "Command Code first, fall back to
TypeSafe".

What the endpoint does, observed 2026-10-06:

- It accepts only the unversioned model `typesafe/jev`. `typesafe/jev-1.13.0` and `jev-1.13.0` are rejected with
  "Use typesafe/jev", and the answer carries `model: "typesafe/jev"`. The tier therefore cannot pin a version, and
  the ledger's `rmodel` cannot show which Jev version served a turn on it. The 0.30 fits floor was calibrated on
  `jev-1.13.0`.
- Its Cloudflare front rejects Python's default User-Agent with HTTP 403 "error code: 1010".
- It is slow. Ten full router turns (wide call plus rerank) per endpoint on the 571-skill catalogue, Tailscale off:
  Command Code 2.97-9.39 s (median about 5.2 s; 2 of 10 within 3.3 s, 5 of 10 within 5 s), TypeSafe 0.87-1.06 s. The
  wide call alone: Command Code 2.24-13.08 s, TypeSafe 0.59-0.98 s. Raw:
  `plans/261006-2034-commandcode-jev-endpoint/_RESEARCH_ARTIFACTS/turn-latency-tailscale-off.txt` and
  `latency-tailscale-off.txt`.

Two rules in force would have made that tier unusable. ADR-0075 decision 3 ended the chain on a timeout, so a slow
first tier would have cost the whole turn its Jev verdict. ADR-0061 capped the route at 3.0 s and the hook was killed
at 5 s, which leaves no room for a slow tier and a fallback behind it.

## Decision

1. **A `cc` endpoint in `ENFORCER_JEV_BENCH`** (`_jev_bench` in `hooks/scripts/enforcer.py`): URL
   `ENFORCER_JEV_CC_URL` (default the address above), key `CMD_API_KEY`, sent only over https to
   `api.commandcode.ai` (its own entry in the host lock, ADR-0075 decision 4). Always a direct call, never through
   the warm relay, which stays TypeSafe-only. The model entry is `typesafe/jev`, unpinned.
2. **`ENFORCER_JEV_CC_TIMEOUT` (default 5.5 s) is both the per-call timeout and the tier's span**: Command Code gets
   the whole 5.5 s of the turn. TypeSafe, the next tier, is called only when Command Code returns an error or has not
   answered by the end of that span. (The first implementation cut Command Code at 3.3 s, the second gave it 5.0 s;
   see *Owner's decision*.)
3. **Any failure falls through, a timeout included.** This replaces ADR-0075's "a timeout ends the chain". A tier
   whose per-call timeout no longer fits the remaining budget is recorded as `NoTime` and skipped, and later tiers
   are still tried (ADR-0075 stopped there). A timed-out call may still be billed; the owner accepted that. The
   relay-reported timeout is recorded as a timeout and never re-sent direct to the same upstream. The offline client
   `scripts/jev_client.py` follows the same rule: a timeout moves the batch to the next tier while its deadline
   allows. `_jev_timed_out` had no remaining caller and was deleted.
4. **The route budget cap moves from 3.0 s to 7.8 s.** `ENFORCER_JEV_BUDGET` now defaults to 7.8 and is clamped to
   7.8: Command Code's 5.5 s span, TypeSafe's 1.5 s call and 0.8 s for the catalogue read and thread start-up. The
   span itself is held by the clock (item 12), not by urllib. Claude Code's `UserPromptSubmit` enforcer
   hook timeout in `hooks/hooks.json` moves from 5 s to 10 s: the worst case is about 8.9 s (startup about 0.1 s +
   7.8 s + post-join annex queries up to about 1.0 s), so the annex still runs inside the kill window. The module
   docstring states the 7.8 s cap and the 8.9 s worst case against that 10 s.
5. **Harnesses with a shorter kill window pass a smaller budget.** The Command Code and DSH adapters kill the
   enforcer at 2.5 s, so each now sets `ENFORCER_JEV_BUDGET=1.6` in the enforcer's environment: TypeSafe's 1.5 s call
   fits, the `cc` tier never fits and is skipped, so TypeSafe serves there. This also closes an earlier gap where a 3.0 s budget outlived a
   2.5 s kill. OMP (10 s) and Cline (20 s) windows still cover the 7.8 s budget (the adapters' `verify_windows` check requires a kill at least budget + 2 s) and are untouched.
6. **Every Jev request sends `User-Agent: skill-concierge`**, which clears the Cloudflare 1010 refusal; the
   calibrator `scripts/calibrate_jev_gate.py` sends it too and `--endpoint` accepts `cc`.
7. **The bench on this machine** is `cc:typesafe/jev ts:jev-1.13.0 gw:openrouter/typesafe/jev-1.13
   gw:oc/jev-1.13-free gw:ocz/jev-1.13-free`.
8. **A rerank that cannot finish is not sent.** `JEV_RERANK_MIN_S` (0.5 s, a code constant with no env var): with
   less than that left in a tier, its rerank call is not sent, because it could not finish but would still be
   billed. The turn falls through as a `TimeoutError`.
9. **History (`ENFORCER_JEV_HISTORY`, default off).** The history join reserves TypeSafe's per-call time on a span
   tier instead of the whole span (it was effectively dead on the Command Code tier). A history-caused skip that
   cannot be re-asked still ends the turn without a Jev verdict instead of falling through. **Judgment call:**
   falling through would bill a whole second turn for a skip; the embedding path decides those turns.
10. **The offline client** `scripts/jev_client.py` never cuts a span tier (Command Code) before its span: its
    per-call timeout is the larger of the caller's timeout and the span, still bounded by the caller's deadline.
    For `consult --fast` (`scripts/consult_fit.py`, 2.0 s per call, 4.0 s budget) Command Code therefore gets the
    whole 4 s, and if it has not answered TypeSafe cannot fit, so consult falls back to inline analysis: no double
    bill, but consult loses its Jev evidence in slow Command Code spells. **Judgment call, pending the owner's
    confirmation.**
11. **Tests** run with a clean Jev environment: `tests/conftest.py` removes every `ENFORCER_JEV_*` variable plus
    `TYPESAFE_API_KEY` and `CMD_API_KEY` before collection. Without it, 13 router and history tests failed in any
    shell that had loaded the machine's `harness-env.sh` (control run: 13 failed, 34 passed without it; 254 Jev tests
    pass with it).
12. **Every router call is held to its limit by the clock** (`_jev_call_capped`): the call runs in a daemon thread
    and is abandoned, reported as a `TimeoutError`, when its limit passes. urllib's timeout bounds each socket
    operation, not the call: in the first valid live round (21:30) Command Code ran a second and more past its 5 s
    span on 2 of 12 turns, TypeSafe was then refused with `NoTime`, and those turns got no Jev verdict at all after
    6.7-7.3 s. With the cap, the next round (21:32) handed both misses to TypeSafe at about 5.7-5.9 s and no turn
    lost its verdict. Test: `test_command_code_is_cut_off_by_the_clock_not_by_its_socket` (real time; it fails on
    the code without the cap). An abandoned call may still be billed; that is the accepted double-bill case.

## Owner's decision (2026-10-06, interim)

The first implementation cut Command Code at 3.3 s and fell through to TypeSafe. The owner objected: an answer
arriving after the cut is discarded while TypeSafe is billed for the same request, which may well give the same
answer, a double bill on about 8 of 10 measured turns. Asked how Command Code should be used, he chose option B in
these words:

> B - with a 2nd call to come after the entire 5s mark without any response at all or due to error responded from commandcode endpoint. at least for now. mark this decision clearly in docs

So the rule is: Command Code gets the entire 5 s; TypeSafe is called only after 5 s with no response, or on an error
from the Command Code endpoint. **This is interim ("at least for now")**; the owner may revisit it, for example once
the W38 numbers exist.

Still a double bill, stated honestly: a Command Code answer that arrives after 5 s is discarded and TypeSafe is
billed too. In the 10-turn measurement 5 of 10 Command Code turns ran past 5 s. When Command Code answers inside
5 s, TypeSafe is never called (one bill).

### Amendment: the span becomes 5.5 s (2026-10-06 about 21:43)

After the first valid live rounds the owner ordered, verbatim: "refine the threshold to 5.5s now". The span
(`ENFORCER_JEV_CC_TIMEOUT`) goes from 5.0 s to 5.5 s, and `ENFORCER_JEV_BUDGET` from 7.3 s to 7.8 s (5.5 s span + 1.5 s
TypeSafe call + 0.8 s for the catalogue read and thread start-up). The hook kill stays at 10 s (worst case about
8.9 s). The rule above is otherwise unchanged and still interim. This section keeps the original 5 s quotation
because it is the owner's decision of record; the number it names is superseded.

## Verification (2026-10-06)

Script: `plans/261006-2034-commandcode-jev-endpoint/verify_live.py`. With the 5.0 s span: Command Code alone answered
through `jev_client` in 1792 ms, and a real router turn on the live bench was served by Command Code itself (tier 0,
no fall-through) in 5165 ms total. With `ENFORCER_JEV_CC_TIMEOUT=0.3`, TypeSafe served in 1693 ms. (Run against the
earlier 3.3 s design: Command Code timed out at its span and TypeSafe served in a total of 4682 ms.) Offline tests:
`tests/test_jev_bench.py` (including `test_command_code_gets_its_whole_span_before_typesafe_is_called` and
`test_command_code_answering_inside_its_span_never_calls_typesafe`), `tests/test_jev_client.py`,
`tests/test_jev_relay_timeout.py`, `tests/test_jev_router.py`.

Raw files are in `plans/261006-2034-commandcode-jev-endpoint/_RESEARCH_ARTIFACTS/`:

- `live-turns-5s.txt` (21:07), `live-turns-round2.txt` (21:15) and `live-turns-round3.txt` (21:28): **invalid,
  retracted.** The test script set the TypeSafe-only bench once at load, and `_jev_bench` reads the bench at call
  time, so every "Command Code" turn in these files actually ran on TypeSafe (every row records `jev-1.13.0`). An
  earlier revision of this ADR read them as Command Code at TypeSafe speed; that claim was false.
- `live-turns-valid-round4.txt` (21:30, fixed script, before item 12): Command Code served 10 of 12 turns in
  2.65-4.51 s (median 3.98 s). The other 2 timed out at the span and TypeSafe got `NoTime`, so they had no Jev verdict
  (6.69 and 7.33 s). TypeSafe alone on the same prompts: 0.74-1.03 s. Same lead skill 9 of 10.
- `live-turns-valid-round5-wallcap.txt` (21:32, with item 12): Command Code served 10 of 12 in 2.34-4.42 s (median
  3.67 s); the 2 misses fell to TypeSafe and were answered in 5.70 and 5.95 s; no turn lost its verdict. TypeSafe
  alone: 0.71-1.27 s. Same lead skill 12 of 12, same offer-or-skip verdict 12 of 12.
- `live-turns-cc-only-dns1111.txt` (21:41, 5.0 s span) and `live-turns-cc-only-span55.txt` (21:44, 5.5 s span), script
  `live_turns_cc_only.py`: real-size router turns on Command Code **only** (bench `cc:typesafe/jev`, TypeSafe key
  removed, because the owner ordered no TypeSafe calls without his yes), 12 prompts each. At 5.0 s, 9 of 12
  answered in 2.28-4.95 s (median 3.47 s) and 3 missed at exactly 5.02-5.03 s (the wall-clock cap holds). At 5.5 s,
  6 of 12 answered in 2.27-3.58 s (median 3.07 s) and 6 missed at exactly 5.52-5.53 s. The answered turns all
  finished by 3.6 s, so the misses are not calls that a slightly longer span would catch.
- **DNS change** (owner, about 21:38: ControlD DNS disabled, cache flushed, DNS server 1.1.1.1). A small curl probe,
  10 calls with the tiny example request: `curl-10-calls.txt` before, `curl-10-calls-dns1111.txt` after. Totals
  0.75-5.50 s (median about 2.0 s) before, 1.01-3.34 s (median about 1.7 s) after. The worst connection setup
  roughly halved (TLS done by 3.69 s at worst before, 1.70 s after; TCP connect 1.96 s at worst before, 0.53 s
  after). Server time (first byte minus TLS done) was unchanged, a median of about 1.2-1.3 s.
- `turn-latency-round3.txt` (21:28, direct HTTPS) Command Code 2.84-4.77 s per turn, TypeSafe 0.91-1.46 s;
  `cmd-vs-http.txt` (21:2x, direct HTTPS) Command Code 2.43-2.68 s per turn.
- `turn-latency-rerun-2130.txt` (21:10, direct-urllib probe, one repeated prompt): Command Code 2.80-7.32 s per
  turn, TypeSafe 0.85-1.01 s.
- `repeat-vs-distinct.txt` (21:11, router path, Command Code only, 6 s span): the same prompt 4.3-5.7 s, distinct
  prompts 3.0-6.5 s, plus one `URLError` and one `TimeoutError` in 10 calls. Prompt repetition is not the cause.

## Consequences

- **One bill when Command Code answers inside 5.5 s, two when it does not.** Inside 5.5 s the turn takes up to about
  5.5 s and TypeSafe is never called. When Command Code errors, or is silent past 5.5 s, TypeSafe is then called: up to
  about 7.8 s of Jev time in the worst case, and two bills if the late Command Code answer is discarded. The first
  measurement had 5 of 10 turns past 5 s. The tier is a provider-preference choice, not a latency
  gain: TypeSafe alone takes about 1 s.
- **Fact:** in every valid measurement this evening (direct probes and the fixed router rounds), a Command Code turn
  took 2.3-9.4 s and a TypeSafe turn 0.7-1.5 s; no valid Command Code turn was faster than 2.3 s. So on this tier
  every prompt waits about 2-4 s longer than on TypeSafe. The share of turns past the span ranged from 0 of 8 (21:24-21:28,
  direct) and 5 of 10 (the first probe, 5 s) through the router rounds: 2 of 12 (21:30), 2 of 12 (21:32), 3 of 12 (21:41,
  5.0 s span, Command Code only) and 6 of 12 (21:44, 5.5 s span, Command Code only). A longer span did not lower the
  miss rate in that one sample: the answered turns finished by 3.6 s, so some requests stall well past the span
  (inference). W38 on real traffic decides the rate. **Open questions:** why Command Code is slower for the same model (prompt repetition is ruled out), and how long the
  missed requests really take. The DNS change cut connection setup but not server time.
- **Verdicts on the `cc` tier come from an unpinned model.** A Command Code version change would pass silently, and
  the 0.30 fits floor is calibrated on `jev-1.13.0`. The ledger's `model`/`tier` fields show which tier served a turn;
  `rmodel` will read `typesafe/jev` there.
- **A new ledger epoch for router metrics.** The change touches the enforcer's budget and tier logic and ships with
  the bench edit, so W21-W24 must be read from the go-live and split by `tier` by hand (see `docs/epoch-watch.md`, W38).
- **Deployment lag.** An installed plugin cache that still runs the older enforcer silently drops the unknown `cc:`
  entry, so live turns stay TypeSafe-first until this change is committed and installed.

## Revert

Fastest, no commit: remove `cc:typesafe/jev` from `ENFORCER_JEV_BENCH` in `~/.config/harness-env.sh`, or restore
`~/.config/harness-env.sh.bak-261006-commandcode`. That returns the bench to TypeSafe first. To keep Command Code but
restore the earlier cut-over design, set `ENFORCER_JEV_CC_TIMEOUT=3.3` (Command Code is then cut at 3.3 s and TypeSafe
serves the rest). `ENFORCER_JEV_CC_TIMEOUT=5.0` restores the previous 5.0 s span. `ENFORCER_JEV_BUDGET=3.0` restores the old route cap's value; the hook's 10 s timeout is harmless
at that setting. `ENFORCER_JEV_ROUTER=0` turns the router off entirely.
