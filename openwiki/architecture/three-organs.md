# Architecture — the three organs & how a request flows

This is the conceptual spine of skill-concierge. Read it once and the two internals pages
([retrieval-engine.md](retrieval-engine.md), [enforcement-gate.md](enforcement-gate.md)) become
"here is how organ X is built" rather than "what is organ X."

## The model

skill-concierge fuses **three organs**, each answering a different question the default skill
mechanism conflates:

| Organ | Question | Where it runs | Built from |
|-------|----------|---------------|------------|
| **Retrieve** | *Which* skill fits this task? | on-demand (the `search_skills` MCP tool) + inside the per-turn hook | the vendored Qdrant + mpnet-768 engine |
| **Enforce** | *Whether* the model uses a skill at all (vs winging it) | every turn, `UserPromptSubmit` hook, in-generation | `hooks/scripts/enforcer.py` + the SessionStart doctrine |
| **Ledger** | *What* actually got used | every turn + on each invocation | `hooks/scripts/ledger.py` + the enforcer's `offer` events |

### Why three, not one

The founding insight (proven from telemetry, recorded in
[`docs/skill-first-enforcement-mental-model.md`](../../docs/skill-first-enforcement-mental-model.md)):
**retrieval was never the bottleneck — compliance is.** Early ledger data showed the model was
offered genuinely-good skills and still improvised (~14–18% uptake, flat before vs after a
retrieval upgrade). Better candidates did not raise usage. So tuning *which* (Retrieve) has
diminishing returns; the binding constraint is *whether* (Enforce). The Ledger exists to keep
that distinction honest — to measure the thing that actually matters instead of the flattering
proxy. See [ADR-0002](../../docs/adr/0002-fusion-which-plus-whether.md) for the fusion decision.

### The load-bearing design boundary: in-generation, never post-hoc

Governance happens **while the model writes**, because the doctrine is in context as it writes.
There is **no Stop hook and no PostToolUse enforcement gate** — a detection layer that catches a
dodge *after* the turn was considered and **rejected by design** (the "anti-caveman": it polices
spent tokens instead of shaping the disposition). This is the single most important architectural
commitment; if a future change is tempted to "just add a Stop gate to catch skips," read
[mental-model §3 and §8](../../docs/skill-first-enforcement-mental-model.md) first — reversing it
reverses the owner's core call.

A second boundary: **all hooks are fail-silent and additive-only.** Any error → the hook exits 0
and the turn proceeds unchanged. A telemetry or retrieval failure must never block a turn. A hook
that "does nothing" may be silently swallowing an exception — never assume silence means success.

## How a single request flows

Wiring lives in [`hooks/hooks.json`](../../hooks/hooks.json). One user message traverses:

1. **SessionStart (once per session)** —
   [`hooks/scripts/doctrine.py`](../../hooks/scripts/doctrine.py) injects the full **SKILL-FIRST
   standing order** (read at runtime from [`hooks/doctrine/skill-first.md`](../../hooks/doctrine/skill-first.md)),
   and two SessionStart self-heals fire, both detached + throttled:
   [`auto_reindex.py`](../../hooks/scripts/auto_reindex.py) runs an incremental reindex so a stale
   index re-freshens, and [`auto_overrides.py`](../../hooks/scripts/auto_overrides.py) reconciles the
   `~/.claude/settings.json` name-only budget when the installed catalogue drifts
   ([ADR-0025](../../docs/adr/0025-autonomous-override-freshness-and-keep-on-management.md)).
2. **UserPromptSubmit (every turn)** — the **Enforce** organ:
   [`enforcer.py`](../../hooks/scripts/enforcer.py) runs the per-turn gate — embed the prompt via
   the warm shim → retrieve top-k from the **same** Qdrant index → apply the score/item floors +
   the actionability (imperative-veto) gate → inject a ranked SKILL-FIRST mandate, **or** stay
   silent / emit a `SKILL-CHECK:` authorization (fail-open on any error). Then
   [`ledger.py`](../../hooks/scripts/ledger.py) records the turn (or a manual `/skill`).
3. **Retrieve (on demand)** — Claude calls `search_skills`; the engine embeds the query and ranks
   the indexed catalogue from Qdrant. Claude reads the ranked names + descriptions.
4. **Invoke** — Claude fires the genuinely relevant skills by name.
5. **PostToolUse** — the ledger captures each `Skill` / `search_skills` invocation (matcher
   `Skill|mcp__.*skill-search__search_skills` — namespace-tolerant), fail-silent, additive-only.
6. **Curate** — [`scripts/analyze.py`](../../scripts/analyze.py) rolls the ledger up into
   offer→take / dodge / hit@k metrics. *Usage* questions use the `skill-usage-audit` skill + the
   transcript SKILL-FIRST trail, **not** the ledger (which measures gate compliance only) — this
   distinction matters; see [enforcement-gate.md](enforcement-gate.md#ledger--usage-a-hard-line).

```
SessionStart ──▶ doctrine (standing order) + auto_reindex (index self-heal) + auto_overrides (budget self-heal)
                     │
User message ──▶ [Enforce] enforcer: embed ▸ retrieve ▸ floors+intent gate ▸ mandate | SKILL-CHECK | silent
                     │                                    └─▶ [Ledger] turn / offer
                     ▼
              Claude thinks ──▶ [Retrieve] search_skills (Qdrant) ──▶ Invoke skill
                                                                          │
                                                                    [Ledger] auto / search (PostToolUse)
                                                                          │
                                                            [Curate] analyze.py ▸ offer→take / dodge / hit@k
```

## Retrieve and Enforce share one index

A subtle but important property: the per-turn enforcer does **not** run a second, cheaper
retriever. It embeds the prompt through the **same** warm embedding shim and queries the **same**
Qdrant collection that the `search_skills` tool uses. That is why the embed shim and index model
must stay in lock-step (fastembed version + model parity) — if the shim's vectors drift from the
index, both organs degrade silently. The mechanics are in
[retrieval-engine.md](retrieval-engine.md) and the parity trap is in [operations.md](operations.md#the-warm-embed-shim).

## See also

- [ADR index](../../docs/adr/README.md) — every accepted decision, with the *why*.
- [mental-model doc](../../docs/skill-first-enforcement-mental-model.md) — the full Enforce-organ reasoning, the caveman role-model, and the open/unproven questions.
