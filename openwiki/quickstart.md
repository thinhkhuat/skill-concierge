# skill-concierge — OpenWiki quickstart

**skill-concierge** is a **plugin** for Claude Code, Codex, Command Code, Oh My Pi (OMP), ZCode, DeepSeek Harness (DSH), Cline, and OpenCode v2 that governs how the agent
picks and uses *skills*. It is a thin **governance layer** over all eight harnesses' default skill
mechanisms: where
the default injects **every** installed skill's description into the context window on **every**
turn and hopes the model notices the right one, skill-concierge replaces *hope* with
**retrieve-precisely + enforce-use + measure**.

> **Metaphor (the whole design in one line):** skill-search is the *library*;
> skill-concierge is the *concierge* who knows which book fits, makes sure you actually open
> one, and remembers what you reached for.

- **Version:** `0.66.3` · **License:** MIT · **Manifest:** [`.claude-plugin/plugin.json`](../.claude-plugin/plugin.json) · Codex: [`.codex-plugin/plugin.json`](../.codex-plugin/plugin.json) · Command Code: [`adapters/commandcode/skill-concierge.mod.ts`](../adapters/commandcode/skill-concierge.mod.ts) · OMP: [`adapters/omp/skill-concierge.ext.ts`](../adapters/omp/skill-concierge.ext.ts) · ZCode: native Claude-plugin parity (no adapter; [ADR-0042](../docs/adr/0042-zcode-quintuple-harness-parity.md)) · OpenCode v2: native plugin ([`adapters/opencode/plugin/index.ts`](../adapters/opencode/plugin/index.ts); [ADR-0085](../docs/adr/0085-opencode-octa-harness-parity.md))
- **Built on** the vendored MIT engine [`sowhan/skill-search`](https://github.com/sowhan/skill-search) (see [`vendor/skill-search/`](../vendor/skill-search/)).
- **Not a coding tool** — it changes *which specialized skill Claude reaches for*, invisibly, in the half-second before Claude answers. See the [plain-language explainer](../docs/how-it-works-plain-language.md) for a non-technical two-minute read.

## What problem it solves

The harnesses' default discovery degrades as a catalogue grows past a few dozen skills: the
model skims the injected list, misses the fitting skill, or "wings it" instead of invoking one.
skill-concierge separates three failure modes the default conflates:

- **Wrong skill chosen** → precise semantic retrieval (*which* skill).
- **No skill chosen** → a per-turn use-mandate hook (*whether* a skill is used at all).
- **No feedback loop** → a compounding invocation ledger (*what actually got used*), so the
  always-on policy is curated from data, not vibes.

## The three organs

| Organ | Question | Mechanism | Deep page |
|-------|----------|-----------|-----------|
| **Retrieve** | *Which* skill fits? | semantic search over the catalogue (a local index owner speaking Qdrant's REST format + multilingual embeddings), a MAX-pool trigger layer mined from each skill's description, its body's labeled decision-sections, **and** offline flywheel-generated natural-utterance phrases (EN+VN) | [architecture/retrieval-engine.md](architecture/retrieval-engine.md) |
| **Enforce** | *Whether* the model uses a skill at all | a per-turn `UserPromptSubmit` hook that hands over ranked candidates under a use-mandate; on its silent verdicts (getaway, conversational, self-recap, harness-generated prompt) it emits a `SKILL-CHECK:` authorization instead | [architecture/enforcement-gate.md](architecture/enforcement-gate.md) |
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
| Claude Code, Codex, Command Code, Oh My Pi (OMP), ZCode, DeepSeek Harness (DSH), Cline, or OpenCode v2 | host for the plugin (or its adapter), hooks, and MCP server |
| Python 3.10–3.12 | `snake_case`; set `SKILL_PYTHON` to pin an interpreter |

No Docker: the vector store and the warm embedder are one local process, the index owner
([ADR-0070](../docs/adr/0070-local-index-owner-replaces-qdrant-and-docker-embed-shim.md)), which
`setup.sh` starts itself. The embedding model (`paraphrase-multilingual-mpnet-base-v2`, 768-dim)
downloads on first index build via `fastembed` — no API key, fully local.

## Install & verify

```bash
git clone https://github.com/thinhkhuat/skill-concierge.git
cd skill-concierge
./setup.sh          # idempotent: stable venv + start the index owner + reindex + apply-overrides
```

Then **restart Claude Code** and confirm the server is live:

```bash
/mcp        # should list  skill-concierge:skill-search  as connected
```

Or run the **`skill-concierge:setup`** skill (same bootstrap, self-verifying). If a green
`status: OK` is not what you get, run **`skill-concierge:doctor`** (or `python3 scripts/doctor.py`)
— it diagnoses the venv, the local index owner, MCP wiring, overrides, and retrieval health, and
`--fix` auto-repairs the common failures. A green doctor shows files and config exist; to prove a harness runs the
concierge, run `python3 scripts/smoke.py` ([operations.md](operations.md#live-proof--smokepy)). Full setup/ops
detail: **[operations.md](operations.md)**.

**In Codex** (v0.24.0+, ADR-0033): add the repo as a plugin marketplace
(`codex plugin marketplace add https://github.com/thinhkhuat/skill-concierge.git`), install
with `codex plugin add skill-concierge@skill-concierge`, then verify the MCP with
`codex mcp list` (should list `skill-search`). The local index owner,
index, and ledger are SHARED with the Claude Code install — one concierge, every harness. Codex skips a plugin hook
whose definition changed until you trust it again: after such an update, open Codex and trust the skill-concierge
hooks ([caveats §27](../docs/caveats.md)).
How [`adapters/codex/install.sh`](../adapters/codex/install.sh) keeps the cached copy current, and
what it refuses to do, is explained in [operations.md](operations.md#versioning--deploy-discipline)
and the installer's header.

**In OMP** (v0.28.0+, ADR-0039): install via the plugin marketplace; OMP ignores Claude-format
hooks, so enforcement runs from the `skill-concierge.ext.ts` extension module (`package.json`
`omp.extensions`), and it expands the plugin `.mcp.json` natively, so no per-harness MCP descriptor
is written (a duplicate `skill-search` at user scope is a known hazard). What
[`adapters/omp/install.sh`](../adapters/omp/install.sh) does on each path is in its header. The
local index owner, index, and ledger are SHARED with every other harness install.

## The MCP tools

The vendored engine ([`vendor/skill-search/skill_search/server.py`](../vendor/skill-search/skill_search/server.py))
exposes five tools:

| Tool | Purpose |
|------|---------|
| `search_skills` | rank skills by semantic relevance to a query (accepts `extra_queries` for multi-phrasing fusion) |
| `consult_candidates` | the consult skill's wide sieve: one query per sub-goal (≤5), `top_n` to 40, capsule dossiers attached ([ADR-0049](../docs/adr/0049-consult-deliberation-layer.md)) |
| `get_skill` | fetch one skill's full description (for thin-description tie-breaks) |
| `reindex` | rebuild the catalogue index after skills change (incremental by default) |
| `health` | report index status (collection, count, embedder, staleness) |

Day-to-day, Claude never calls these by hand: the **`skills/skill-search/SKILL.md`** router is
the always-on entry point that calls `search_skills` at the start of any multi-step request.

Since `0.42.0` ([ADR-0049](../docs/adr/0049-consult-deliberation-layer.md)) the engine also
serves a **deliberated lane**: `consult_candidates` feeds the `skill-concierge:consult` skill
(`skills/consult/SKILL.md`) — an opt-in planning step that sieves wide over installed AND
external skills, attaches **capsule dossiers** (per-skill structured summaries from
`scripts/llm_capsules.py`, corpus at `~/.claude/skill-concierge/capsules.json`, generated via
`flywheel.py --generate --capsules`), delegates deep body reads to an analyst subagent, and
composes a RUN/⚠/ALSO verdict logged as `consult_verdict` ledger rows. `SKILL_CONSULT=0` is
the kill-switch; an absent corpus degrades rows to description-only. Since `0.43.0`
(ADR-0049 phase 2) the enforcer also ROUTES deliberation-shaped turns ("which skills
should I use for X") there via a `CONSULT-ROUTE` mandate — pre-I/O, never in subagent
sessions, ledger kind `consult_route` carrying the prompt for false-route replay;
`SKILL_CONSULT_ROUTE=0` disables. Since `0.58.0`
([ADR-0078](../docs/adr/0078-consult-sieve-jev-widening.md)) the consult skill widens the sieve:
`scripts/consult_fit.py widen` puts Jev's whole-catalogue top 10 for the user's request ahead of
the `consult_candidates` rows (top_n 40), deduped and cut to 20. A pre-registered held-out gate
measured recall@20 24.1 -> 48.3 on cases not shaped by a Jev offer. `SKILL_CONSULT_JEV_WIDEN=0`
turns it off; any Jev failure falls back to the sieve rows.

Since `0.22.0`, `search_skills` can also surface **external catalog skills** — third-party
collections registered in `~/.claude/skill-concierge/catalog-roots.json` without being
installed ([ADR-0031](../docs/adr/0031-external-catalog-roots.md)). They rank marked
`external: <alias>`, cost zero resident context, and are consumed by pulling their body with
`get_skill` (the Skill tool cannot invoke them). Manage roots with
[`scripts/catalogs.py`](../scripts/catalogs.py) / the `skill-concierge:catalogs` skill.

Externals are **first-class in the per-turn offer** too
([ADR-0032](../docs/adr/0032-external-catalogs-first-class-annex.md)): an additive annex below the
installed offer (zero displacement), where an external must clear `ENFORCER_EXTERNAL_FLOOR` (0.32)
and, once the installed top reaches `GETAWAY_FLOOR` (0.45), beat it by `ENFORCER_ANNEX_BEAT` (0.04)
([ADR-0048](../docs/adr/0048-complement-annex.md)). The one-day merged-pool parity experiment was
reverted ([ADR-0047](../docs/adr/0047-revert-tier-parity-restore-annex.md)); an external used across
enough distinct sessions auto-graduates to an installed skill. Kill-switches:
`ENFORCER_EXTERNAL_ANNEX=0`, `ENFORCER_ANNEX_COMPLEMENT=0`.

The same annex shape covers **other harnesses' skills**
([ADR-0034](../docs/adr/0034-cross-harness-offer-isolation.md)): the installed offer holds only what
the running harness can invoke, and the rest appear read inline via `get_skill`, each row marked
with the harness whose roots hold it (`[omp]`, `[zcode]`, …); the annex is sized by score margin
([ADR-0036](../docs/adr/0036-dynamic-annex-sizing.md)). The isolation is harness-complete, with a
project-scope test on top ([ADR-0059](../docs/adr/0059-harness-complete-offer-isolation-echo-everywhere.md),
`ENFORCER_PROJECT_ISOLATION`). `search_skills` still spans the union. The flags and their defaults are
in [`AGENTS.md` → Runtime flags](../AGENTS.md).

## Where to go next

- **[architecture/three-organs.md](architecture/three-organs.md)** — the conceptual model + how a request flows.
- **[architecture/retrieval-engine.md](architecture/retrieval-engine.md)** — the vendored semantic engine internals.
- **[architecture/enforcement-gate.md](architecture/enforcement-gate.md)** — the per-turn gate, the SKILL-FIRST doctrine, and the ledger.
- **[operations.md](operations.md)** — setup, doctor, the ledger analyzer, runtime flags, config, versioning, and the landmine list.

### Primary sources (this wiki is a map over these — read them for depth)

- [`README.md`](../README.md) — full product overview, install, usage, architecture.
- [`AGENTS.md`](../AGENTS.md) — canonical agent-contributor instructions + guardrails.
- [`AGENTS-ONBOARDING.md`](../AGENTS-ONBOARDING.md) — the 5-minute orientation (read-order, mental model, first-week traps); `AGENTS.md` wins on any conflict.
- [`docs/adr/`](../docs/adr/README.md) — accepted design decisions + rationale (immutable; the *why*).
- [`docs/caveats.md`](../docs/caveats.md) — operational landmines (the loud gotchas list).
- [`docs/skill-first-enforcement-mental-model.md`](../docs/skill-first-enforcement-mental-model.md) — the complete Enforce-organ mental model.
- [`docs/anti-dodge-integration-v0.14.md`](../docs/anti-dodge-integration-v0.14.md) — **the v0.14.0 anti-dodge work**: the 5 mechanisms, the decision arc (study → red-team → owner Option B), and the loud accepted caveats.
- [`docs/how-it-works-plain-language.md`](../docs/how-it-works-plain-language.md) — the non-technical explainer.
- [`CHANGELOG.md`](../CHANGELOG.md) — per-version history.
