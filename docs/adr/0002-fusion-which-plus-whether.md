# ADR-0002: Fusion architecture — skill-search (WHICH) × skill-first (WHETHER)

**Status:** Accepted; P1 implementation **COMPLETE** — enforcer hook built, warm embed shim operational, fallback tested. Deploy pending (owner-gated). See `../plan.md` build log.
**Date:** 2026-06-26
**Deciders:** owner (thinhkhuat)

## Context

Two mechanisms existed independently before this plugin:

- **skill-search** (MCP, semantic) answers **WHICH** skill fits a task — retrieval by
  meaning over the indexed catalogue.
- **skill-first** (a `UserPromptSubmit` hook) answers **WHETHER** Claude uses a skill at
  all, versus winging it — anti-dodge enforcement. Its *sole* purpose was to fight the
  observed behaviour of the model skipping a clearly-applicable skill.

They look like competitors but are **orthogonal**: one decides relevance, the other decides
compliance. The only real conflict is the hook's *second, rushed* job — it also lexically
ranks and echoes skill names, using a weaker engine and a **separate, drifting catalogue**
(`library.json`, which diverged from the index: 585 vs 508 vs 512 counts).

## Decision

Fuse them into ONE skill-governance layer with three organs: **Retrieve** (skill-search) +
**Enforce** (skill-first) + **Ledger** (telemetry). Concretely, the enforcer stops doing
its own lexical ranking and instead **sources its per-turn candidates from the SAME
semantic index**, then enforces use over them. One catalogue, one ranker.

> Library / doorman: skill-search is the library; skill-first is the doorman who makes the
> model walk in every turn, hands it the few books that actually fit (semantically, not by
> spine-title), and won't let it leave a real task without opening one.

## Considered options (the lexical scorer's fate)

- **Retire the lexical scorer entirely** (original plan wording). — Reconsidered:
  see "Open" below. The decision to retire is **not yet evidence-backed**.
- **Hybrid (semantic ∪ lexical).** — Possible if a *valid local* eval shows the embedder
  has blind spots the lexical path covers. No such evidence exists yet (the only eval run
  was the wrong-universe one — ADR-0001).
- **Keep separate.** — Rejected: leaves the drifting `library.json` and the weaker ranker.

## The crux (why this is not "delete `score()`, call Qdrant")

The hook fires on **every** prompt from a **cold** process and must stay fast (~71ms today,
stdlib-only). Semantic retrieval = embed(query) + Qdrant search. Qdrant search is ms;
embedding the query needs the **mpnet-768** model (ADR-0003), and cold-loading it per
prompt is **seconds-scale** — over budget. So **P1's real deliverable is a WARM embedding
endpoint** serving that exact model, that the cold hook hits in tens of ms, with a hard
client-side **~120ms timeout → mandate-only fallback** (never silence, never crash).

## Consequences

- Single catalogue (the index) — kills the `library.json` drift.
- A new always-on dependency (the warm embed shim, like Qdrant) — mitigated by the
  mandate-only fallback: an outage degrades enforcement, never breaks the turn.
- Enforcement is **soft** by design; P2 (a hard skill-worthiness gate / classifier) is
  **deferred** until the ledger's *dodge rate* shows soft enforcement leaks — measure, don't
  guess.

## Open (revised by session evidence, 2026-06-26)

The "retire the lexical scorer" call is **undecided**, not settled. It needs a recall@k
number from an eval whose ground truth is drawn **only** from the indexed catalogue
(ADR-0001 / caveats §1). Until that exists, neither "retire" nor "hybrid" is justified.

## Related

- ADR-0001 (what the index contains — the candidate source).
- ADR-0003 (the embedder the warm shim must serve).
- ADR-0006 (the ledger that decides whether the fusion worked).
- `../plan.md` (full P1 design, acceptance criteria, build log).
