# ADR-0075: the Jev bench — ordered SystemOne tiers, TypeSafe plus the owner's gateway

- **Status:** Accepted (2026-10-03, owner's order). Enabled on this machine by an `ENFORCER_JEV_BENCH` block in
  `~/.config/harness-env.sh`; the code default is unchanged.
- **Extends:** ADR-0061 (Jev router), ADR-0070 (warm `/jev` relay in the index owner).

## Context

ADR-0061's router calls one endpoint, TypeSafe (`api.typesafe.ai`, model `jev-1.13.0`), through the index
owner's warm relay. The owner runs his own SystemOne gateway (`api.thinhkhuat.com/v1/systemone`, the
`FLYWHEEL_LLM_*` seam) that serves several upstream routes to the same model family. He ordered the router
to use it. Measured on 2026-10-03, 8 interleaved router-shaped exchanges on the 542-skill catalogue
(`plans/reports/jev-gateway-261003-0334/_RESEARCH_ARTIFACTS/model_latency_compare3.out`):

| Route | Whole route p50 / max | Same top pick as `oc` |
|---|---|---|
| `openrouter/typesafe/jev-1.13` (answers `typesafe/jev-1.13-20260917`) | 1.51 s / 2.02 s | 7/8 |
| `oc/jev-1.13-free` (answers `jev-1.13-free`, cost 0) | 1.92 s / 2.43 s | — |
| `ocz/jev-1.13-free` (answers `jev-1.13-free`) | 2.12 s / 2.49 s | 7/8 |
| TypeSafe via the warm relay (live ledger, current epoch) | 0.87 s / p90 1.15 s | |

Every gateway route is slower than TypeSafe's warm relay and needs a per-call timeout above 1.5 s; all fit
the 3.0 s route cap, which stays (the hook is killed at 5 s).

## Decision

1. **A bench of ordered tiers.** `ENFORCER_JEV_BENCH` lists `<endpoint>:<model>` entries, tried in order
   within one turn. `ts` = TypeSafe (`ENFORCER_JEV_URL`, `TYPESAFE_API_KEY`, the warm relay, per-call
   `ENFORCER_JEV_TIMEOUT`); `gw` = the owner's gateway, whose URL is derived from `FLYWHEEL_LLM_ENDPOINT`'s
   host (`https://<host>/v1/systemone`), key `ENFORCER_JEV_KEY` else `FLYWHEEL_LLM_API_KEY`, per-call
   `ENFORCER_JEV_GATEWAY_TIMEOUT` (default 2.0 s). Unset = `ts:<ENFORCER_JEV_MODEL>`, byte-identical
   behaviour to ADR-0061. The owner's starting order, expected to change often during tuning:
   `ts:jev-1.13.0 gw:openrouter/typesafe/jev-1.13 gw:oc/jev-1.13-free gw:ocz/jev-1.13-free`.
2. **Fixed order, not round-robin** (owner's choice after the trade-off was laid out): offers stay
   consistent turn to turn, and each tier's numbers stay readable from the ledger.
3. **Failover only on a fast failure.** An HTTP error, a refused connection, a refused host, a model
   mismatch or a malformed answer moves the turn to the next tier — if that tier's per-call timeout still
   fits the remaining 3.0 s budget (else `NoTime`, and the turn falls back to the embedding path). A
   timeout ends the chain: its budget is spent and, per ADR-0061 decision 7, the call may already be billed.
   A tier without a key is skipped (`NoKey`). Each tier runs the whole route (wide and rerank), so one
   model makes each verdict.
4. **Trust and identity.** The key is sent only over https to `api.typesafe.ai` or the `FLYWHEEL_LLM_ENDPOINT`
   host (or loopback in tests); redirects are refused everywhere. A returned model must equal the tier's
   pin up to a provider path and a trailing snapshot date (`oc/jev-1.13-free` ≡ `jev-1.13-free`,
   `openrouter/typesafe/jev-1.13` ≡ `typesafe/jev-1.13-20260917`); anything else is `JevModelMismatch`.
5. **The relay stays TypeSafe-only.** It forwards to a fixed TypeSafe host (ADR-0070), so `gw` tiers call
   the gateway directly, one TLS handshake per call.
6. **Telemetry.** The router event records `model` (the tier that answered), `rmodel` (the exact id Jev
   returned — a new dated snapshot under the same pin shows here), `tier` (its index), `to`, `floor`, and
   `fell` (`[model, error]` per tier that failed first). A turn every tier failed is one router error
   carrying `fell`. The calibrator picks a tier with `--model` (and `--endpoint gw` for a model the bench
   does not list).

## Verification (2026-10-03)

- Replay on the 542-skill catalogue, same 313 skill turns and 300 traffic turns: TypeSafe `jev-1.13.0` 161/222
  offers held the used skill (72.5 %), OpenRouter 159/222 (71.6 %); both 1/313 false NO and 3.0 % traffic
  skipped. The two free routes returned HTTP 429 under replay load and then at one call per 10 s; not yet
  replayed.
- End to end through the hook with real calls (`_RESEARCH_ARTIFACTS/e2e_bench.out`): a normal turn served
  by TypeSafe via the relay (0.89 s); with TypeSafe's key broken, the turn fell to OpenRouter (1.96 s,
  `fell: [jev-1.13.0, HTTPError]`), same lead skill.
- Accepted risk: a loopback URL stays allowed for tests in any build; whoever can set it already holds the key.

## Consequences

- A tier change is a config change with no commit: the ledger's `model`/`tier` fields, not the commit date,
  delimit its epoch. W22/W23 must be read per model.
- Turns served by a gateway tier are slower; a fast-failing TypeSafe tier costs its failure time before
  the gateway tier starts.
- The free gateway routes carry no per-call charge; OpenRouter is billed by OpenRouter (owner-approved by
  placing it on the bench, RULES [72]).

## Revert

Delete the `ENFORCER_JEV_BENCH` block in `~/.config/harness-env.sh` (TypeSafe alone again), or reorder its
entries; `ENFORCER_JEV_ROUTER=0` turns the router off entirely.
