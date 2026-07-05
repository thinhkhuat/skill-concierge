# skill-concierge — OpenWiki quickstart

**skill-concierge** is a Claude Code **plugin** that governs how Claude picks and uses
*skills*. It is a thin **governance layer** over Claude Code's default skill mechanism: where
the default injects **every** installed skill's description into the context window on **every**
turn and hopes the model notices the right one, skill-concierge replaces *hope* with
**retrieve-precisely + enforce-use + measure**.

> **Metaphor (the whole design in one line):** skill-search is the *library*;
> skill-concierge is the *concierge* who knows which book fits, makes sure you actually open
> one, and remembers what you reached for.

- **Version:** `0.13.0` · **License:** MIT · **Manifest:** [`.claude-plugin/plugin.json`](../.claude-plugin/plugin.json)
- **Built on** the vendored MIT engine [`sowhan/skill-search`](https://github.com/sowhan/skill-search) (see [`vendor/skill-search/`](../vendor/skill-search/)).
- **Not a coding tool** — it changes *which specialized skill Claude reaches for*, invisibly, in the half-second before Claude answers. See the [plain-language explainer](../docs/how-it-works-plain-language.md) for a non-technical two-minute read.

## What problem it solves

Claude Code's default discovery degrades as a catalogue grows past a few dozen skills: the
model skims the injected list, misses the fitting skill, or "wings it" instead of invoking one.
skill-concierge separates three failure modes the default conflates:

- **Wrong skill chosen** → precise semantic retrieval (*which* skill).
- **No skill chosen** → a per-turn use-mandate hook (*whether* a skill is used at all).
- **No feedback loop** → a compounding invocation ledger (*what actually got used*), so the
  always-on policy is curated from data, not vibes.

## The three organs

| Organ | Question | Mechanism | Deep page |
|-------|----------|-----------|-----------|
| **Retrieve** | *Which* skill fits? | semantic search over the catalogue (Qdrant + multilingual embeddings), a MAX-pool trigger layer mined from each skill's description **and** its body's labeled decision-sections | [architecture/retrieval-engine.md](architecture/retrieval-engine.md) |
| **Enforce** | *Whether* the model uses a skill at all | a per-turn `UserPromptSubmit` hook that hands over ranked candidates under a use-mandate; on its two silent verdicts it emits a `SKILL-CHECK:` authorization | [architecture/enforcement-gate.md](architecture/enforcement-gate.md) |
| **Ledger** | *What actually got used* | a compounding, append-only skill-invocation log → data-backed always-on curation | [architecture/enforcement-gate.md](architecture/enforcement-gate.md#the-ledger--what-actually-got-used) |

The conceptual spine — how the three organs fit together and how a single request flows
through them — lives in **[architecture/three-organs.md](architecture/three-organs.md)**. Start there
if you want the model before the internals.

## ⚠ Critical design facts (read before judging the engine)

These have bitten before; the ADRs and [`docs/caveats.md`](../docs/caveats.md) exist because of them.

- **The index holds model-invocable `SKILL.md` skills ONLY.** Built-in / user-only
  slash-commands (`loop`, `schedule`, `verify`, `run`, `code-review`, …) are **excluded by
  design** — they aren't `SKILL.md` files and the model can't fire them. Their absence is
  correct, not a bug. → [ADR-0001](../docs/adr/0001-index-model-invocable-skills-only.md).
- **The vendored `eval/` recall@k is NOT a quality bar here.** It is calibrated to the
  upstream author's skill universe, which this deployment deliberately excludes; a near-zero
  score means *wrong universe*, not *weak retriever*. → [caveats §1](../docs/caveats.md).
- **Plugin skills are namespaced** in the index (`ck:worktree`, not `worktree`). → [caveats §5](../docs/caveats.md).
- **Ledger metrics are EPOCH-SCOPED — never pool them across config changes.** This repo
  changes what the ledger measures almost daily, so an all-time rate describes no real config.
  → [AGENTS.md → Guardrails](../AGENTS.md), [operations.md](operations.md#reading-the-ledger-the-epoch-scoped-trap).

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| Claude Code | host for the plugin, hooks, and MCP server |
| Python 3.10–3.12 | `snake_case`; set `SKILL_PYTHON` to pin an interpreter |
| Docker / OrbStack | runs the Qdrant vector store **and** the warm embed shim (both Docker sidecars) |

The embedding model (`paraphrase-multilingual-mpnet-base-v2`, 768-dim) downloads on first
index build via `fastembed` — no API key, fully local.

## Install & verify

```bash
git clone https://github.com/thinhkhuat/skill-concierge.git
cd skill-concierge
./setup.sh          # idempotent: stable venv + Qdrant + embed shim + reindex + apply-overrides
```

Then **restart Claude Code** and confirm the server is live:

```bash
/mcp        # should list  skill-concierge:skill-search  as connected
```

Or run the **`skill-concierge:setup`** skill (same bootstrap, self-verifying). If a green
`status: OK` is not what you get, run **`skill-concierge:doctor`** (or `python3 scripts/doctor.py`)
— it diagnoses the venv, Qdrant, MCP wiring, overrides, and retrieval health, and `--fix`
auto-repairs the common failures. Full setup/ops detail: **[operations.md](operations.md)**.

## The MCP tools

The vendored engine ([`vendor/skill-search/skill_search/server.py`](../vendor/skill-search/skill_search/server.py))
exposes four tools:

| Tool | Purpose |
|------|---------|
| `search_skills` | rank skills by semantic relevance to a query (accepts `extra_queries` for multi-phrasing fusion) |
| `get_skill` | fetch one skill's full description (for thin-description tie-breaks) |
| `reindex` | rebuild the catalogue index after skills change (incremental by default) |
| `health` | report index status (collection, count, embedder, staleness) |

Day-to-day, Claude never calls these by hand: the **`skills/skill-search/SKILL.md`** router is
the always-on entry point that calls `search_skills` at the start of any multi-step request.

## Where to go next

- **[architecture/three-organs.md](architecture/three-organs.md)** — the conceptual model + how a request flows.
- **[architecture/retrieval-engine.md](architecture/retrieval-engine.md)** — the vendored semantic engine internals.
- **[architecture/enforcement-gate.md](architecture/enforcement-gate.md)** — the per-turn gate, the SKILL-FIRST doctrine, and the ledger.
- **[operations.md](operations.md)** — setup, doctor, the ledger analyzer, runtime flags, config, versioning, and the landmine list.

### Primary sources (this wiki is a map over these — read them for depth)

- [`README.md`](../README.md) — full product overview, install, usage, architecture.
- [`AGENTS.md`](../AGENTS.md) — canonical agent-contributor instructions + guardrails.
- [`docs/adr/`](../docs/adr/README.md) — accepted design decisions + rationale (immutable; the *why*).
- [`docs/caveats.md`](../docs/caveats.md) — operational landmines (the loud gotchas list).
- [`docs/skill-first-enforcement-mental-model.md`](../docs/skill-first-enforcement-mental-model.md) — the complete Enforce-organ mental model.
- [`docs/how-it-works-plain-language.md`](../docs/how-it-works-plain-language.md) — the non-technical explainer.
- [`CHANGELOG.md`](../CHANGELOG.md) — per-version history.
