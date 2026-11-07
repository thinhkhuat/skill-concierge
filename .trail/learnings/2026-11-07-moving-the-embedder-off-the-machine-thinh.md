---
title: "Moving the embedder off the machine blew the per-turn hook's 500ms cap, and 14% of turns were silently censored"
author: Thinh
date: 2026-11-07
branch: main
id: l-6f08f4f6
scope: repo
status: active
src: agent
touches:
  - hooks/scripts/enforcer.py
---

## Decided
Moving the embedder off-box silently broke the per-turn hook's latency budget.
`hooks/scripts/enforcer.py` embeds the query through the LOCAL index owner with a
hard 500 ms cap (`ENFORCER_EMBED_TIMEOUT`, ADR-0054). That cap was calibrated when
the embedder was local ONNX answering in under 10 ms. After the 2026-11-07
cutover the owner forwards every embed over the network to the GPU host, so the
same code path now costs 42-88 ms warm and 854 ms on a cold start.

Evidence it was hurting, not merely slow: 42 of the last 300 ledger rows (14.0%)
recorded `embed_timeout`, and the NORMAL calls in that window maxed at 499 ms
against the 500 ms ceiling. A distribution pressed against its cap is censoring
real work — the exact failure ADR-0054 was written to fix, recurring one layer
down.

Set `ENFORCER_EMBED_TIMEOUT=1.5` in `~/.config/harness-env.sh`: ~17x headroom on
warm latency, covers a cold start, and worst-case hook total stays ~2.75 s
against Claude Code's 10 s hook timeout.

## Tried and ruled out
- **Reading the single smoke failure as an outage.** The `embed_timeout` label
  suggests the embedder was down. A 10-call probe of the same path returned
  42-88 ms throughout — it was never down, it was slower than a 500 ms cap.
- **Changing the code default to 1.5.** That silently invalidates ADR-0054's
  calibration without reopening it. The env override exists for exactly this and
  a revert is deleting two lines from `harness-env.sh`.
- **Raising the cap without measuring first.** The ledger numbers are what turn
  "feels slow" into "14% of turns censored"; without them this would have been a
  guess.

## Watch out
- **A latency budget calibrated for an in-process call does not survive moving
  that call onto the network.** Whenever an embedding, rerank or lookup path moves
  off-box, re-measure every hard timeout that fronts it.
- **`embed_timeout` in the ledger does not mean the embedder was unreachable.** It
  means the call exceeded the cap. Check actual latency before diagnosing an
  outage.
- **Read the cap against the observed distribution, not in isolation.** A normal
  max of 499 ms under a 500 ms cap is the signal; the timeout count alone can look
  like a flake.

In the code:
- `hooks/scripts/enforcer.py` — `EMBED_TIMEOUT_S`, default "0.5", the ADR-0054 note
  and its revert line `ENFORCER_EMBED_TIMEOUT=0.35 ENFORCER_QDRANT_TIMEOUT=0.1`
- `~/.config/harness-env.sh` — `export ENFORCER_EMBED_TIMEOUT=1.5` (backup
  `harness-env.sh.bak-261107-1520`)
- measured: owner path 42-88 ms x10; GPU host direct 56-85 ms warm, 854 ms cold;
  ledger 42/300 turns = 14.0% embed_timeout; normal max 499 ms
