# skill-concierge

[![version](https://img.shields.io/badge/version-0.12.0-blue.svg)](CHANGELOG.md)
[![license](https://img.shields.io/badge/license-MIT-green.svg)](#license)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-plugin-8A2BE2.svg)](https://docs.claude.com/en/docs/claude-code)
[![built on](https://img.shields.io/badge/built%20on-skill--search-orange.svg)](https://github.com/sowhan/skill-search)

A **skill-governance layer** over Claude Code's default skill mechanism. Where the
default dumps every skill description into context every turn and hopes the model picks
one, skill-concierge replaces *hope* with **retrieve-precisely + enforce-use + measure**.

> **Metaphor:** skill-search is the library; skill-concierge is the concierge who knows
> which book fits, makes sure you actually open one, and remembers what you reached for.

## Table of contents

- [Why this exists](#why-this-exists)
- [Three organs](#three-organs)
- [Critical design facts](#-critical-design-facts-read-before-judging-the-engine)
- [Prerequisites](#prerequisites)
- [Install & setup](#install--setup)
- [Usage](#usage)
- [Configuration](#configuration)
- [Architecture](#architecture)
- [Status & roadmap](#status--roadmap)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [Credits & attribution](#credits--attribution)
- [License](#license)

## Why this exists

Claude Code's default skill discovery injects **every** installed skill's description into
the context window on **every** turn, then trusts the model to notice the right one. As a
catalogue grows past a few dozen skills, that approach burns context and quietly degrades:
the model skims, misses the fitting skill, or "wings it" instead of invoking one at all.

skill-concierge addresses three distinct failure modes the default conflates:

- **Wrong skill chosen** → precise semantic retrieval (*which* skill).
- **No skill chosen** → a per-turn use-mandate hook (*whether* a skill is used at all).
- **No feedback loop** → a compounding invocation ledger (*what actually got used*), so the
  always-on policy is curated from data, not vibes.

## Three organs

| Organ | Question it answers | Mechanism |
|-------|---------------------|-----------|
| **Retrieve** | *Which* skill fits this task? | semantic search over the skill catalogue (Qdrant + multilingual embeddings), including a MAX-pool trigger layer mined from both each skill's description **and** its body's labeled decision sections (`## When to Use`, `Triggers:`, `Use when:`) — [ADR-0012](docs/adr/0012-multi-vector-max-pool-retrieval.md), [ADR-0016](docs/adr/0016-body-derived-trigger-points.md) |
| **Enforce** | *Whether* the model uses a skill at all (vs winging it) | a per-turn hook that hands over the right candidates under a use-mandate; on its two previously-silent verdicts (score-floor miss, conversational turn) it now injects a `SKILL-CHECK:` authorization instead of nothing — [ADR-0015](docs/adr/0015-authorized-skip-tier-and-library-doctrine.md) |
| **Ledger** | *What actually got used* | a compounding, append-only skill-invocation log → data-backed always-on curation |

## ⚠ Critical design facts (read before judging the engine)

- **The index holds model-invocable `SKILL.md` skills ONLY.** Built-in / user-only
  slash-commands (`loop`, `schedule`, `verify`, `run`, `code-review`, `update-config`,
  `keybindings-help`) are **excluded by design** — they aren't `SKILL.md` files, cost no
  model context, and the model can't fire them. → [ADR-0001](docs/adr/0001-index-model-invocable-skills-only.md).
- **The vendored eval is NOT a quality bar here.** `vendor/skill-search/eval/` is calibrated
  to the *upstream author's* environment; its recall@k measures a skill universe this
  deployment excludes. A near-zero score means *wrong universe*, not *weak retriever*. →
  [caveats §1](docs/caveats.md).
- **Plugin skills are namespaced** in the index (`ck:worktree`, not `worktree`). → [caveats §5](docs/caveats.md).
- **Full landmine list:** [`docs/caveats.md`](docs/caveats.md). **Decisions + rationale:**
  [`docs/adr/`](docs/adr/README.md).

## Prerequisites

| Requirement | Version / notes |
|-------------|-----------------|
| [Claude Code](https://docs.claude.com/en/docs/claude-code) | host for the plugin, hooks, and MCP server |
| Python | 3.10–3.12 (set `SKILL_PYTHON` to pin a specific interpreter) |
| Docker / [OrbStack](https://orbstack.dev/) | runs the Qdrant vector store (server tier) |

> The embedding model (`paraphrase-multilingual-mpnet-base-v2`, 768-dim) downloads on first
> index build via `fastembed` — no API key, fully local. For a service-free embedded tier,
> see the `ponytail:` note at the top of [`setup.sh`](setup.sh).

## Install & setup

skill-concierge is developed **local-first** in a workbench and published as a Claude Code
plugin at <https://github.com/thinhkhuat/skill-concierge>.

```bash
git clone https://github.com/thinhkhuat/skill-concierge.git
cd skill-concierge
./setup.sh          # builds the stable venv, ensures Qdrant, reindexes, applies overrides
```

`setup.sh` is idempotent and safe to re-run. It performs four steps:

1. **Stable venv** — installs the vendored engine + deps into `~/.local/share/skill-concierge/venv`
   (outside the plugin cache, so it survives reinstalls — [ADR-0004](docs/adr/0004-bundled-mcp-launcher-stable-venv.md)).
2. **Qdrant** — starts a `skill-search-qdrant` Docker container on ports `6333/6334`.
3. **Index** — builds/refreshes the multilingual index, then runs a health check.
4. **Overrides** — applies the curated always-on policy to `~/.claude/settings.json` (backed up first).

Or invoke the **`skill-concierge:setup`** skill, which runs the same bootstrap and verifies it.

Then **restart Claude Code** and confirm the server is live:

```bash
/mcp        # should list  skill-concierge:skill-search  as connected
```

If you previously registered a user-scope skill-search MCP, de-duplicate it so only the
bundled one runs:

```bash
claude mcp remove skill-search -s user
```

## Usage

Once connected, the router skill (`skills/skill-search/SKILL.md`) is the always-on entry
point. At the start of any multi-step or unfamiliar request, Claude calls `search_skills`
with a short query describing the goal, reads the ranked results, and invokes only the
genuinely relevant skills by name.

### MCP tools

The vendored engine exposes four tools (`vendor/skill-search/skill_search/server.py`):

| Tool | Purpose |
|------|---------|
| `search_skills` | rank skills by semantic relevance to a query |
| `get_skill` | fetch one skill's full description (for thin-description tie-breaks) |
| `reindex` | rebuild the catalogue index after skills change |
| `health` | report index status (collection, count, embedder) |

### Inspecting the ledger

Every turn and skill/search invocation is logged to an append-only JSONL ledger. Analyze
uptake, search rate, and dodge rate with the read-only, stdlib-only analyzer:

```bash
python3 scripts/analyze.py        # reads ~/.claude/skill-telemetry/logs/skill-invocation-ledger.log
```

To compare a window — e.g. before vs after a fix or a go-live — use `--since` / `--until`
instead of splitting the ledger by hand. `WHEN` is epoch seconds or a local ISO time
(`YYYY-MM-DD` or `YYYY-MM-DD HH:MM:SS`); a commit time makes a clean boundary:

```bash
T="$(git show -s --format=%cd --date=format:'%Y-%m-%d %H:%M:%S' <fix-commit>)"
python3 scripts/analyze.py --until "$T"   # the "before" window
python3 scripts/analyze.py --since "$T"   # the "after"  window
```

Output shape (numbers below are illustrative):

```
uptake        : <n>/<N>  <pct>   (turn used a skill)
search called : <n>/<N>  <pct>
dodge         : <n>/<N>  <pct>   (no skill, no search)   ← the behaviour Enforce exists to kill
hit@k         : <n>/<m>  <pct>   (used skill was in the offered set)
```

> `hit@k` computes once `offer` events land from the enforcer hook (now live). Before any
> offers it shows **pending** (no offered-set yet). See [`docs/plan.md`](docs/plan.md).

## Configuration

### MCP environment (`.mcp.json`)

The live MCP server and `setup.sh` read these from `.mcp.json` (single source of truth, so
the built index can't diverge from the model the server uses):

| Variable | Default | Meaning |
|----------|---------|---------|
| `SKILL_QDRANT_URL` | `http://localhost:6333` | Qdrant endpoint |
| `SKILL_EMBED_BACKEND` | `fastembed` | embedding backend |
| `SKILL_EMBED_MODEL` | `sentence-transformers/paraphrase-multilingual-mpnet-base-v2` | embedding model |

### Setup overrides (environment)

`setup.sh` honours these for non-default machines:

| Variable | Default |
|----------|---------|
| `SKILL_PYTHON` | first of `python3.12/3.11/3.10` on `PATH` |
| `SKILL_CONCIERGE_VENV` | `~/.local/share/skill-concierge/venv` |
| `SKILL_QDRANT_CONTAINER` | `skill-search-qdrant` |
| `SKILL_QDRANT_IMAGE` | `qdrant/qdrant:1.18.2` |
| `SKILL_CONCIERGE_LOG` | `~/.claude/skill-telemetry/logs` (ledger directory) |

### Runtime governance flags

Behavior-changing kill-switches, both **default ON** — set to `0` (and reindex, where noted)
to revert to the prior behavior:

| Variable | Default | Meaning |
|----------|---------|---------|
| `ENFORCER_AUTHORIZED_SKIP` | `1` (ON) | Enforcer (`hooks/scripts/enforcer.py`) injects a `SKILL-CHECK:` authorization line on its two previously-silent verdicts (getaway score-floor miss, conversational-intent skip) instead of nothing. `=0` restores the old silence. [ADR-0015](docs/adr/0015-authorized-skip-tier-and-library-doctrine.md). |
| `SKILL_BODY_TRIGGERS` | `1` (ON) | Vendored engine mines each skill body's labeled decision sections into extra MAX-pool trigger points, on top of the existing description-derived ones. `=0` + a reindex reverts to description-only (byte-identical to before). [ADR-0016](docs/adr/0016-body-derived-trigger-points.md). |

### Always-on policy (`config/keep-on.json`)

A curated 32-skill always-on allowlist, applied to `~/.claude/settings.json` by
[`scripts/apply-overrides.py`](scripts/apply-overrides.py) (an atomic keep-on writer — it
does **not** call the upstream override generator; [ADR-0005](docs/adr/0005-overrides-target-and-applier.md)).
The list is catalogue-specific — `apply-overrides.py` reports any entries missing on the
target machine. Edit to taste.

## Architecture

```
skill-concierge/
├── .claude-plugin/{plugin,marketplace}.json   # manifests (bump BOTH versions together)
├── .mcp.json                                  # registers the MCP via bin/skill-search-mcp launcher
├── bin/skill-search-mcp                       # launcher → stable venv (survives cache wipes; ADR-0004)
├── setup.sh                                    # bootstrap: venv + Qdrant + reindex + apply-overrides
├── scripts/apply-overrides.py                  # atomic keep-on writer → ~/.claude/settings.json (ADR-0005)
├── scripts/analyze.py                          # ledger analyzer (uptake / dodge / hit@k)
├── scripts/doctor.py                           # deployment health check + safe --fix
├── config/keep-on.json                         # 32-skill always-on policy
├── hooks/                                       # ledger capture: hooks.json + scripts/ledger.py
├── skills/skill-search/SKILL.md                # router skill (always-on entry point)
├── skills/setup/SKILL.md                       # skill-concierge:setup — bootstrap/refresh
├── skills/doctor/SKILL.md                      # skill-concierge:doctor — healthcheck + auto-fix
├── skills/skill-usage-audit/SKILL.md           # skill-concierge:skill-usage-audit — valid usage measurement (SKILL-FIRST trail)
├── vendor/skill-search/                        # vendored MCP engine (MIT · sowhan/skill-search) + LICENSE + VENDORED.md
├── docs/adr/                                    # Architecture Decision Records (the WHY)
├── docs/caveats.md                             # operational landmines (the loud gotchas)
├── docs/plan.md                                # fusion build plan + dated build log
├── CHANGELOG.md
└── README.md
```

The engine source is vendored for portability; its Python deps, the Qdrant service, the
embedding model, the index, and the `settings.json` overrides are **reproduced by `setup.sh`**,
not embedded.

### How a request flows

1. **SessionStart** — `hooks/scripts/doctrine.py` injects the full SKILL-FIRST standing order once.
2. **UserPromptSubmit** — `hooks/scripts/enforcer.py` runs the per-turn gate: embed the prompt via the
   warm shim → retrieve top-k from the SAME Qdrant index → apply the score/item floors + the
   actionability gate → inject a ranked SKILL-FIRST mandate, or stay silent (fail-open on any error).
   Then `hooks/scripts/ledger.py` records the turn (or a manual `/skill`).
3. **Retrieve** (on demand) — Claude calls `search_skills`; the engine embeds the query and ranks the
   indexed catalogue from Qdrant.
4. **Invoke** — Claude reads the ranked names + descriptions and fires the relevant skills.
5. **PostToolUse** — the ledger captures each `Skill` / `search_skills` invocation
   (matcher `Skill|mcp__.*skill-search__search_skills` — namespace-tolerant since v0.4.1), fail-silent and additive-only.
6. **Curate** — `scripts/analyze.py` rolls the ledger up into offer→take / dodge / hit@k metrics.
   (Usage questions use the `skill-usage-audit` skill + the transcript SKILL-FIRST trail, **not** the
   ledger, which measures gate compliance only.)

## Status & roadmap

`0.12.0` — **published, MCP live, all three organs semantic, SKILL-FIRST gate + actionability gate live, bundled maintenance skills. Multi-vector MAX-pool retrieval (ADR-0012) now also mines each skill body's labeled decision-sections (ADR-0016), and the enforcer's two silent verdict legs emit a `SKILL-CHECK:` authorization instead of nothing (ADR-0015). Everything default-ON behind env kill-switches.**
**Retrieve** (MCP) + **Enforce** (the `enforcer.py` UserPromptSubmit hook sources candidates
from the SAME semantic index via a warm threaded embed shim, with a hard-timeout → mandate-only
fallback) + **Ledger** (telemetry: `offer`/`search`/hit@k/fallback). The legacy lexical
`skill_first_nudge.py` is retired (deregistered from `~/.claude/settings.json`).

The deployment now **self-guards against staleness**: doctor's `Engine freshness` check
(ADR-0013) catches a stale MCP venv engine after a `/plugin update`, and the SessionStart
`auto_reindex` hook (ADR-0014) self-heals a stale index in the background — no manual reindex
or reminders. Full per-version history in [`CHANGELOG.md`](CHANGELOG.md).

Trajectory since the P1 fusion (`0.2.0`):
- **`0.3.0` — SKILL-FIRST doctrine gate.** A SessionStart hook (`hooks/scripts/doctrine.py`)
  injects the rich standing order from a single-source doctrine file; the per-turn enforcer
  message was reworded from persuasion into a cheap gate trigger (forced line-1 token,
  "previewed few don't fit → SEARCH the full index, never skip"). Governance is **in-generation
  only** — no Stop/PostToolUse detection gate (rejected by design as the anti-caveman). The
  driving finding: retrieval was never the bottleneck — compliance is.
- **`0.4.0` — EFFORT decoupled** into its own universal [`effort-gate`](https://github.com/thinhkhuat/effort-gate)
  plugin. skill-concierge governs *which/whether* a skill; effort-gate governs *how much work*.
- **`0.4.1` — search-logging fix.** `search` events were never logged (tool-name drift: the live
  MCP tool is plugin-namespaced); now matched by suffix so the gate's primary lever is visible to
  its own telemetry.
- **`0.4.2` — measurement window.** `analyze.py --since/--until` for clean before/after compares.
- **`0.5.0`–`0.10.x` — retrieval depth + curation.** Index enrichment, the ledger-derived
  offer-suppression map (ADR-0011, auto-drop chronic never-take skills from the menu), and
  multi-vector MAX-pool retrieval (ADR-0012). Per-version detail in the CHANGELOG.
- **`0.11.0` — SKILL-FIRST doctrine rewrite + compliance telemetry.** A 5-day transcript analysis
  showed ~93% token-*form* compliance but only ~47% *behavioral*; the doctrine was rewritten to
  task-gate `SKIPPING` (lawful only on a genuine no-task turn), require the `search_skills` call
  in the same reply, ban `USING: none`, and weld the skip-bar to the take-bar. Added a
  false-SKIPPING detector (`audit_skill_usage.py`) + a substantive-compliance line (`analyze.py`).
- **`0.11.1` — staleness self-guards.** doctor `Engine freshness` check (ADR-0013) catches a stale
  MCP venv engine after `/plugin update`; SessionStart `auto_reindex` (ADR-0014) self-heals a stale
  index in the background.
- **`0.12.0` — usefulness-rate upgrades.** The enforcer's two silent verdict legs (score-floor miss,
  conversational turn) now emit a `SKILL-CHECK:` authorization (ADR-0015) so the agent stops
  re-searching to re-derive a verdict the hook already made; the library doctrine puts the burden of
  proof on SKIP (escalate to `find-skills`). The MAX-pool trigger layer now also mines each skill
  body's labeled decision-sections (ADR-0016; index 2231→3570 points). Everything default-ON behind
  env kill-switches — an operator override of the proposal's gate-first advice (see ADR-0015/0016).

**Open question:** `0.11.0`'s transcript analysis + a controlled A/B gave the first real evidence
the gate shapes orientation — the doctrine fixes the no-task / `USING: none` cases cleanly — but
the longitudinal lift on the hardest behavior (false-SKIPPING, now measurable via the
`skill-usage-audit` detector) still needs a post-`0.11.0` workload window to accrue. See
[`docs/skill-first-enforcement-mental-model.md`](docs/skill-first-enforcement-mental-model.md),
[`docs/plan.md`](docs/plan.md), [ADR-0002](docs/adr/0002-fusion-which-plus-whether.md), and
[ADR-0008](docs/adr/0008-warm-embed-shim-timeout-calibration.md).

## Troubleshooting

**Start here:** run the **`skill-concierge:doctor`** skill (or `python3 scripts/doctor.py`) —
it diagnoses the venv, Qdrant, MCP wiring, overrides, and retrieval health, and `--fix`
auto-repairs most of the rows below (start Qdrant, reindex, re-apply overrides).

| Symptom | Cause & fix |
|---------|-------------|
| `/mcp` shows skill-search **not connected** (`-32000` / ENOENT) | The engine venv is missing. Run `bash setup.sh` once, then restart Claude Code. The launcher only execs a **stable** venv — it never builds on spawn ([ADR-0004](docs/adr/0004-bundled-mcp-launcher-stable-venv.md)). |
| Two `skill-search` servers listed | A leftover user-scope MCP. Remove it: `claude mcp remove skill-search -s user`. |
| `setup.sh` aborts at step 2 | Docker daemon not running. Start Docker/OrbStack and re-run. |
| Vendored eval prints recall@k ≈ `0.00` | **Not a bug.** The eval labels target a different skill universe — see [caveats §1](docs/caveats.md). |
| Router reverted to `name-only` after a cache `setup.sh` rerun | Ensure `skill-concierge:skill-search` is in `config/keep-on.json` (fixed in 0.1.2). |

Full landmine list: [`docs/caveats.md`](docs/caveats.md).

## Contributing

This is a pre-1.0, evolving project. Before opening a change:

- Read the relevant [ADR](docs/adr/README.md) — accepted ADRs are immutable; supersede with a
  new one rather than editing.
- Bump **both** `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` versions
  together, and add a `CHANGELOG.md` entry.
- Do not patch `vendor/skill-search/` to diverge from upstream silently — record any
  customization in [`vendor/skill-search/VENDORED.md`](vendor/skill-search/VENDORED.md).

## Credits & attribution

Built on [**sowhan/skill-search**](https://github.com/sowhan/skill-search) (PyPI
`skill-search-mcp`) by **Sowhan Mohammed**, MIT-licensed. The engine is vendored under
[`vendor/skill-search/`](vendor/skill-search/) with its `LICENSE` and a customization log in
[`VENDORED.md`](vendor/skill-search/VENDORED.md).

## License

MIT — see the plugin manifest. The vendored engine retains its own MIT license at
[`vendor/skill-search/LICENSE`](vendor/skill-search/LICENSE).
</content>
</invoke>
