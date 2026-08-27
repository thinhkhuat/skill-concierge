# skill-concierge

[![version](https://img.shields.io/badge/version-0.30.1-blue.svg)](CHANGELOG.md)
[![license](https://img.shields.io/badge/license-MIT-green.svg)](#license)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-plugin-8A2BE2.svg)](https://docs.claude.com/en/docs/claude-code)
[![built on](https://img.shields.io/badge/built%20on-skill--search-orange.svg)](https://github.com/sowhan/skill-search)

A **skill-governance layer** over Claude Code, Codex, Command Code, and Oh My Pi (OMP) default skill mechanisms. Where the
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

The default skill discovery in Claude Code, Codex, Command Code, and OMP injects **every** installed skill's description into
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
| [Claude Code](https://docs.claude.com/en/docs/claude-code), [Codex](https://codex.openai.com), [Command Code](https://github.com/sst/command-code), or [Oh My Pi](https://ohmy.pi) | host for the plugin, hooks, and MCP server |
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

1. **Stable venv** — installs the vendored engine + deps into `~/.claude/skill-concierge/venv`
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
python3 scripts/analyze.py        # reads ~/.claude/skill-concierge/logs/skill-invocation-ledger.log
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
| `SKILL_CONCIERGE_VENV` | `~/.claude/skill-concierge/venv` |
| `SKILL_QDRANT_CONTAINER` | `skill-search-qdrant` |
| `SKILL_QDRANT_IMAGE` | `qdrant/qdrant:1.18.2` |
| `SKILL_CONCIERGE_LOG` | `~/.claude/skill-concierge/logs` (ledger directory) |

### Flywheel LLM config (utterance generation — ADR-0027)

Configures the offline generator that writes the utterance layer. One OpenAI-compatible client covers
LM-Studio, Ollama (`/v1`), and any 3rd-party gateway; put these in `~/.claude/settings.json` env. Run
the **`skill-concierge:flywheel`** skill to see coverage + endpoint health and to generate; full setups
in [`references/flywheel-llm-providers.md`](references/flywheel-llm-providers.md).

| Variable | Default | Meaning |
|----------|---------|---------|
| `FLYWHEEL_LLM_ENDPOINT` | `http://localhost:4310/v1/chat/completions` | OpenAI-compatible chat endpoint (LM-Studio / Ollama `/v1` / gateway). |
| `FLYWHEEL_LLM_MODEL` | `gemma-4-e4b-it-qat-optiq` | must match the endpoint's exact served model name. |
| `FLYWHEEL_LLM_API_KEY` | unset | when set, sent as `Authorization: Bearer <key>` — for 3rd-party gateways. |
| `FLYWHEEL_LLM_SCHEMA_MODE` | `json_schema` | `json_schema` (strict, LM-Studio) \| `json_object` (Ollama/loose) \| `off` (prompt-only). |
| `SKILL_AUTO_FLYWHEEL` | `1` (ON) | the `auto_flywheel` SessionStart hook auto-generates utterances for new/changed skills when the endpoint is reachable (detached, throttled, fail-open — ADR-0027). `=0` disables; manual `skill-concierge:flywheel --generate` still works. |
| `AUTO_FLYWHEEL_THROTTLE_S` | `21600` (6h) | min seconds between background auto-flywheel runs. |
| `AUTO_FLYWHEEL_MAX_PER_RUN` | `25` | cap on skills generated per background run (protects metered endpoints). |

### Runtime governance flags

Behavior-changing kill-switches, all **default ON** except `SKILL_LLM_TRIGGERS` — set to `0`
(and reindex, where noted) to revert to the prior behavior:

| Variable | Default | Meaning |
|----------|---------|---------|
| `ENFORCER_AUTHORIZED_SKIP` | `1` (ON) | Enforcer (`hooks/scripts/enforcer.py`) injects a `SKILL-CHECK:` authorization line on its two previously-silent verdicts (getaway score-floor miss, conversational-intent skip) instead of nothing. `=0` restores the old silence. [ADR-0015](docs/adr/0015-authorized-skip-tier-and-library-doctrine.md). |
| `ENFORCER_SELFREF_SKIP` | `1` (ON) | Enforcer authorizes a skip for the narrow self-referential recap lane (a turn that only asks to explain/rephrase the agent's own prior message). `=0` restores the old 2-lane behaviour. [ADR-0019](docs/adr/0019-over-fire-lane-and-gate-legibility.md). |
| `ENFORCER_CHAIN_HINT` | `1` (ON) | Enforcer appends a `CHAIN-HINT:` candidate line to every inject-bearing leg when this session used a skill declaring `next-skills:` within 15 min (`ENFORCER_CHAIN_TTL_S`). Ledger tail-read + sidecar map, zero hot-path network; hinted names pass keep-off and catalogue filters and bypass no floor. `=0` reverts byte-identically. [ADR-0029](docs/adr/0029-next-skill-chain-hints.md). |
| `SKILL_BODY_TRIGGERS` | `1` (ON) | Vendored engine mines each skill body's labeled decision sections into extra MAX-pool trigger points, on top of the existing description-derived ones. `=0` + a reindex reverts to description-only (byte-identical to before). [ADR-0016](docs/adr/0016-body-derived-trigger-points.md). |
| `SKILL_LLM_TRIGGERS` | `0` (OFF) | Layers offline flywheel-generated natural-utterance phrases (`eval/triggers.json` `llm_triggers`, EN+VN) FIRST in the MAX-pool trigger layer, ahead of description/body. `=1` + a reindex enables; needs `SKILL_TRIGGERS` pointed at the (gitignored) `eval/triggers.json`. Live deploy sets this ON via `.mcp.json`. [ADR-0026](docs/adr/0026-llm-utterance-trigger-layer.md). |
| `TRIGGERS_MAX` | `12` | Per-skill COMBINED cap on trigger points across all sources. Raise (live deploy uses `16`) so LLM-utterance phrases add slots rather than evict description/body ones. |

### Always-on policy (the keep-on allowlist)

A curated 32-skill always-on allowlist; every other skill is `name-only` (retrieved on demand).
The shipped default is [`config/keep-on.json`](config/keep-on.json); on first run it is **seeded
once** into the canonical durable home `~/.claude/skill-concierge/keep-on.json`, which survives
`/plugin update` ([ADR-0025](docs/adr/0025-autonomous-override-freshness-and-keep-on-management.md)).
[`scripts/apply-overrides.py`](scripts/apply-overrides.py) writes the resulting policy atomically to
`~/.claude/settings.json` (it does **not** call the upstream generator; [ADR-0005](docs/adr/0005-overrides-target-and-applier.md)).

**It stays fresh on its own.** The SessionStart `auto_overrides.py` hook reconciles the budget
whenever the installed catalogue drifts — a new skill no longer leaks its full description until
someone remembers to re-apply — and `doctor` flags any drift meanwhile.

**Curate it seamlessly** with the `keep-on` skill / [`scripts/keep-on.py`](scripts/keep-on.py):

```bash
python3 scripts/keep-on.py list                 # view the always-on set
python3 scripts/keep-on.py add <skill-name>…    # add, then reconcile immediately
python3 scripts/keep-on.py remove <skill-name>… # remove, then reconcile
```

### External catalogs (search without installing)

Third-party skill collections — a cloned awesome-skills repo, a shared team folder — can be
indexed for retrieval **without installing anything**
([ADR-0031](docs/adr/0031-external-catalog-roots.md)). Register a local directory whose children
carry `SKILL.md` files in the operator-owned `~/.claude/skill-concierge/catalog-roots.json`
(absent file = feature off):

```bash
python3 scripts/catalogs.py add antigravity ~/env-DEV/antigravity-awesome-skills/skills
python3 scripts/catalogs.py list                      # roots, counts, broken promotions
python3 scripts/catalogs.py promote antigravity:seo   # symlink a keeper into ~/.claude/skills
```

Catalog skills index as `<alias>:<name>` under scope `catalog:<alias>` at **zero per-turn
resident cost** — the whole point. Consume one by pulling its body with
`get_skill("<alias>:<name>")` and following it inline; the Skill tool cannot invoke it. Name
collisions with installed skills are a non-event (alias namespace), a promoted symlink's
catalog twin is auto-suppressed, and removing a root prunes its points at the next reindex.
Embeddings + body triggers only — the flywheel utterance layer deliberately skips externals
(deferred phase).

Since `0.23.0` externals are **first-class in the per-turn offer**, not just explicit search
([ADR-0032](docs/adr/0032-external-catalogs-first-class-annex.md)): the enforcer appends an
**additive annex** of up to `ENFORCER_EXTERNAL_SLOTS` (2) externals scoring
≥ `ENFORCER_EXTERNAL_FLOOR` (0.40), marked `[external:<alias>]` with the `get_skill`
instruction. The installed offer is **byte-identical** whether the annex is on or off (a
separate query supplies it — externals never take an installed slot). An external used across
≥ `PROMOTE_MIN_TAKES` (3) distinct sessions **auto-graduates** to a real installed skill
(`hooks/scripts/auto_promote.py`) — organic curation by demonstrated usage. Kill-switch
`ENFORCER_EXTERNAL_ANNEX=0` restores search-only.

## Architecture

```
skill-concierge/
├── .claude-plugin/{plugin,marketplace}.json   # Claude Code manifests (bump ALL FOUR versions together)
├── .codex-plugin/plugin.json                  # Codex manifest (dual-harness, ADR-0033; no hooks field — hooks auto-discovered)
├── package.json                               # root manifest: {"omp":{"extensions":["adapters/omp/skill-concierge.ext.ts"]}} — loads the OMP extension module
├── adapters/commandcode/                      # Command Code adapter: mod adapter + install.sh + mcp.json (ADR-0038)
├── adapters/omp/                              # Oh My Pi adapter: skill-concierge.ext.ts + install.sh + mcp.json (ADR-0039)
├── .mcp.json                                  # registers the MCP via bin/skill-search-mcp launcher
├── bin/skill-search-mcp                       # launcher → stable venv (survives cache wipes; ADR-0004)
├── setup.sh                                    # bootstrap: venv + Qdrant + reindex + apply-overrides
├── scripts/apply-overrides.py                  # atomic keep-on writer → ~/.claude/settings.json (ADR-0005; --check/--if-changed drift modes)
├── scripts/keep-on.py                          # view/add/remove the always-on allowlist (ADR-0025)
├── scripts/analyze.py                          # ledger analyzer (uptake / dodge / hit@k)
├── scripts/doctor.py                           # deployment health check + safe --fix
├── config/keep-on.json                         # 32-skill always-on SEED (runtime copy → ~/.claude/skill-concierge/, ADR-0025)
├── hooks/                                       # SessionStart self-heals (auto_reindex + auto_overrides + auto_flywheel) + ledger capture (ledger.py)
├── skills/skill-search/SKILL.md                # router skill (always-on entry point)
├── skills/setup/SKILL.md                       # skill-concierge:setup — bootstrap/refresh
├── skills/doctor/SKILL.md                      # skill-concierge:doctor — healthcheck + auto-fix
├── skills/skill-usage-audit/SKILL.md           # skill-concierge:skill-usage-audit — valid usage measurement (SKILL-FIRST trail)
├── skills/keep-on/SKILL.md                     # skill-concierge:keep-on — curate the always-on allowlist (ADR-0025)
├── skills/flywheel/SKILL.md                    # skill-concierge:flywheel — utterance coverage + generation (ADR-0027)
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

### Harness matrix

skill-concierge is a first-class citizen in all four harnesses. Enforcement rides whatever
each harness's extension mechanism supports (settings hooks for Claude Code, a mod adapter for
Command Code, a TS extension module for OMP — Codex auto-discovers hooks, no `hooks` field);
discovery always indexes **all** harnesses' roots into one shared Qdrant collection under
distinct per-harness scopes (fail-open — a harness you don't run is simply absent from disk);
and the MCP server is wired per-harness from the shared descriptor, never duplicated.

| Harness | Discovery roots (scopes) | Enforcement vehicle | MCP wiring |
|---------|--------------------------|---------------------|------------|
| Claude Code | `~/.claude/skills`, `$CWD/.claude/skills`, `~/.claude/plugins/cache/**` (`personal`/`project`/`plugin`) | `UserPromptSubmit` settings hook → `enforcer.py` + SessionStart doctrine | shared `.mcp.json` |
| Codex | `~/.codex/skills`, `$CWD/.codex/skills`, `~/.codex/plugins/cache/**` (`codex-*`) | auto-discovered settings hooks (no `hooks` field; ADR-0033) | `.codex-plugin/mcp.json` (relative command; ADR-0035) |
| Command Code | `~/.commandcode/skills`, `$CWD/.commandcode/skills` (`commandcode-*`) | mod adapter `transformInput` (`adapters/commandcode/skill-concierge.mod.ts`; ADR-0038) | `adapters/commandcode/mcp.json` (absolute paths; ADR-0038) |
| Oh My Pi (OMP) | `~/.omp/agent/skills`, `$CWD/.omp/skills`, `~/.omp/agent/managed-skills`, `~/.omp/plugins/cache/plugins/**` (`omp-*`) | extension module `before_agent_start` (`adapters/omp/skill-concierge.ext.ts` via `package.json` `omp.extensions`; ADR-0039) | plugin `.mcp.json` imported natively (`${CLAUDE_PLUGIN_ROOT}` expanded by OMP); `adapters/omp/mcp.json` manual fallback only |

`SKILL_CODEX_ROOTS` / `SKILL_COMMANDCODE_ROOTS` / `SKILL_OMP_ROOTS` (all default ON) are one-var
reverts that drop that harness's roots + scopes byte-identically (see AGENTS.md → Runtime flags).

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



`0.30.1` — **published, flywheel transport resilience: `ping()` budget widened 5 s → 10 s (`FLYWHEEL_LLM_PING_TIMEOUT`) after a real preflight miss against a gateway that legitimately takes 6-7 s+ on `/v1/models`; `chat()` now retries socket timeouts (both urllib shapes) on the same 3-attempt/5s-10s backoff as HTTP 503 — the gateway is bimodal under load (2-10 s or 60-95 s per call), so a timeout is contention, not a verdict — while refused/DNS errors still fail fast.**
`0.30.0` — **published, flywheel concurrency + observability: a single lock file (~/.claude/skill-concierge/.flywheel.lock, `FLYWHEEL_LOCK` override) now guards every `flywheel --generate` — `fcntl.flock` with an `O_CREAT|O_EXCL` fallback, 2 h stale window + PID liveness — so the SessionStart auto run and a manual run can no longer overlap and double the LLM request rate (live overlap observed: two manifest runs 13 s apart, 11 timeouts vs the normal 0-4; the auto hook skips without stamping so the held run retries next session, manual runs exit 4 with the holder PID); per-skill error messages flow into `flywheel-manifest.json` `skills[].detail` (optional key, backward-compatible) and surface in `--generate` summaries, `flywheel.py` status, and `doctor.py`'s flywheel row.**
`0.29.0` — **published, adversarial-review remediation batch: OMP telemetry capture fixed (every MCP tool name arrives flattened to single underscores — both ext.ts matchers and `ledger.py` SEARCH_TOOLS/GET_TOOLS now accept the flattened forms, verified end-to-end with a live `{"ev":"search","harness":"omp"}` probe row); enforcer offers now stamped `ev["harness"]` (per-harness analytics computable; unstamped rows are legacy); flywheel `--generate` fixed for detached paths (`_cfg()` resolves endpoint/model/key from real env then `~/.config/harness-env.sh`) and `max_tokens` 4096→8192 (deepseek-v4-flash spends budget on reasoning before content) — utterance coverage closed 556/645 → **645/645 (100%)**; `doctor.py` covers all four harnesses (`check_codex()` + `check_commandcode()`, WARN-only, live-verified); README Uninstall section (all four harnesses + shared components); per-harness subagent doctrine table (mental-model doc §12); 5-lens review report with owner verdicts committed.**
`0.28.1` — **published, enforcer short-prompt pre-gate CJK fix: `MAX_SHORT_WORDS` counted whitespace words, so any Chinese/Japanese/Korean prompt collapsed to one "word" and bypassed mandate+offer entirely (found in the post-0.28.0 live smoke: a 12-char Chinese prompt logged only a turn row). `_word_count()` counts CJK chars as ~1 word each — a ≥4-char CJK prompt passes the gate; English byte-identical; threshold value untouched.**
`0.28.0` — **published, ADR-0039 OMP quadruple-harness parity: Oh My Pi (`omp`) added as fourth first-class citizen alongside Claude Code, Codex, and Command Code. OMP ignores Claude-format hooks, so enforcement rides a TS extension module (`adapters/omp/skill-concierge.ext.ts`, loaded via root `package.json` `omp.extensions`) — `before_agent_start` (the UserPromptSubmit equivalent) feeds the prompt to `enforcer.py` and returns an injectable persisted `customType: "skill-concierge"` message; `session_start` dispatches detached `auto_reindex`/`auto_overrides`/`auto_flywheel`/`auto_promote`; `tool_result` forwards `read` + `skill://` activation and skill-search tool calls to `ledger.py`. Fail-open everywhere. Discovery mirror indexes OMP's four roots — `~/.omp/agent/skills` (`omp-personal`), `<cwd>/.omp/skills` (`omp-project:<abspath>`), `~/.omp/agent/managed-skills` (`omp-managed`), `~/.omp/plugins/cache/plugins/**` (`omp-plugin`, node_modules symlink farm excluded) — under distinct `omp-*` scopes; `SKILL_OMP_ROOTS=0` + a reindex reverts byte-identically. Harness identity: `_running_harness()` resolves `omp` via `SKILL_CONCIERGE_HARNESS=omp/oh-my-pi` → `OMPCODE=1` (OMP sets both `OMPCODE` and `CLAUDE-CODE`, so CLAUDECODE alone is never claude proof) → `.omp/` path marker; new `UNDER_OMP` constant. `_invocable_plugin_ids()` under `omp` unions `~/.omp/plugins/installed_plugins.json`; `_invocable_twin()` active under claude OR omp; foreign scopes `codex-plugin` + `commandcode-personal` annexed under the `commandcode` label. `adapters/omp/install.sh` uses the plugin marketplace when installed, the dev path appends to `~/.omp/agent/config.yml` extensions, and never writes `~/.omp/agent/mcp.json` — OMP expands the plugin `.mcp.json`'s `${CLAUDE_PLUGIN_ROOT}` natively (no ADR-0035 duplicate-server hazard). **

`0.27.0` — **published, ADR-0038 Command Code triple-harness parity: Command Code (`cmd`, v1.32.1) added as third first-class citizen alongside Claude Code and Codex. Full governance loop parity: mod adapter (`adapters/commandcode/skill-concierge.mod.ts`) implements `transformInput` for in-generation semantic enforcement on every typed user prompt, and observes `skill_loaded`/`tool_completed` events for automatic ledger capture of skill and search invocations; discovery mirror indexes `~/.commandcode/skills` and `.commandcode/skills` under `commandcode-*` scopes; three-way harness detection isolates foreign scopes into the marked annex without displacing installed slots; native doctrine tool naming adapts MCP tool IDs at SessionStart; idempotent installer `adapters/commandcode/install.sh` wires the mod, settings hooks, and MCP config cleanly.**

`0.26.2` — **published, ADR-0037 borrowed-manifest freshness: an MCP server whose cwd is not a project (Codex pins it to the plugin cache per ADR-0035) derived a phantom manifest key and reported `degraded — never indexed` forever, with a false `run reindex()` riding every Codex search reply. Health and the staleness warning now borrow the newest OTHER root's manifest for FRESHNESS (published as `freshness_from`), keep per-root staleness honestly `None` (borrowed signature = another cwd — unknowable, not false), and still degrade on a genuinely manifest-less machine. Closes the last defect from the second live Codex revalidation.**

`0.26.1` — **published, fixes from the second live Codex revalidation (retrieval organ end-to-end PASS under Codex; defects all telemetry/test-harness class): the deployed selftest no longer false-alarms from a Codex cache (case 12 pins UNDER_CODEX alongside the scope world; verified from a /.codex/-marked path); harness detection skips non-absolute env candidates after a LITERAL `$HOME/.claude` was found injected by the settings env block (debris removed, backed up); ledger + hooks matcher accept Codex's underscore normalization (`skill[-_]search__…`, dormant until Codex fires PostToolUse — re-confirmed it does not today); doctor's Trigger-hygiene resolves the durable home first (the 0.25.1 thresholds pattern). D2 (phantom manifest key from the ADR-0035 cwd) tracked for next release.**

`0.26.0` — **published, ADR-0036 dynamic annex sizing: the fixed 2-row annexes become a competitive-margin rule — an external/cross-harness row earns a slot by scoring within `ENFORCER_ANNEX_MARGIN` (0.05, measured on the live index: 0.10+ saturates, 0.05 discriminates) of the top installed row, capped at 4 external / 2 foreign. The 0.40 floor alone discriminated nothing (the 1.9k-skill pool clears it 8+ deep on every turn); now strong-inventory turns shrink to 0–1 annex rows (less noise than fixed-2) and thin-inventory turns widen to the cap — annex width itself reads what the inventory offers for the intent. TOP_K and zero displacement untouched; deterministic hits silence the annexes; `ENFORCER_ANNEX_DYNAMIC=0` reverts byte-identically. Ledger epoch boundary.**

`0.25.2` — **published, ADR-0035 Codex MCP wiring: Codex expands `${CLAUDE_PLUGIN_ROOT}` in plugin hook commands but leaves it LITERAL in plugin MCP command/args (openai/codex#35762) — so skill-search was silently unreachable in every Codex session while hooks and the ledger worked (first Codex-side validation report, 8/9 checks PASS on real Codex execution, this wiring the one FAIL). Fix: `.codex-plugin/mcp.json` with a relative command resolved against `\"cwd\": \".\"` — Codex's native plugin-root mechanism (discussion #28145), portable across versioned cache dirs; shared `.mcp.json` untouched; env parity between the two descriptors enforced by `scripts/check_mcp_env_parity.py` in driftcheck; `SKILL_SERVER_RECORDS` deliberately omitted on the Codex side (its `${HOME}` literal only Claude's launcher expands). Corrects ADR-0033's claim that Codex reads `.mcp.json` the same way — true for hooks, false for MCP.**

`0.25.1` — **published, calibration artifact relocated to the durable home (`~/.claude/skill-concierge/thresholds.json`): kept under the plugin root it died with every `/plugin update` — no installed cache ever carried one, so doctor's Corpus health row was silently N/A on every fresh install and per-skill tau floors fell back to the global floor. Durable-home-first resolution with legacy fallback across enforcer, doctor (which also gains the `SKILL_THRESHOLDS` env seam it alone was missing) and the calibrator's writer. The ADR-0027 artifact class, third instance.**

`0.25.0` — **published, ADR-0034 cross-harness offer isolation (amends ADR-0033): the per-turn installed offer now holds only skills the RUNNING harness can invoke — measured live over six prompts, 18 of 48 rows named skills the Skill tool cannot invoke here; after, 0 of 48, and a 20-prompt sweep returns 160 rows with 0 non-invocable. `_retrieve` over-fetches to `TOP_K*5` and POST-filters (the multiplier is headroom, not a guarantee — a foreign-dominated domain can still return a short menu, which beats a full one padded with dead rows), because scope records where a skill's indexed copy LIVES, not whether this harness can invoke it: Claude Code layers plugin enablement across user/project/local settings while discovery reads only the user file, so 24 `agent-skills:*` skills Claude invokes fine carry `scope: codex-plugin` — a query-side filter deleted all 24 and labelled them 'NOT invocable here'. `_invocable_twin()` resolves the merged settings per session, in the hook rather than the machine-global index. The rest re-surface from a separate query as a marked `[codex]`/`[claude]` annex consumed via `get_skill` (≤`ENFORCER_FOREIGN_SLOTS`=2, ≥`ENFORCER_FOREIGN_FLOOR`=0.40). Foreign scopes are derived per harness — from Claude `codex-plugin`+`codex-personal`, from Codex `plugin` ONLY, since discovery walks the Claude personal root first so a skill present in both personal roots is tagged `personal` while Codex can still invoke it; harness detection uses precedence and never resolves a falsy path (`Path("")` is the cwd, which would invert the filter); both annex queries moved past the getaway/actionability gates; `search_skills` and chain hints keep the ADR-0033 union; ledger `xh` field + `analyze.py` consumer; kill-switch `ENFORCER_CROSS_HARNESS=0`. Same release adds a `doctor` **`MCP reachable`** check — every other doctor row answers *is the index healthy*, none answered *can the agent reach it*, and a project-disabled MCP leaves the engine green while `search_skills`/`get_skill` do not exist for that session (observed live; `Duplicate MCP` counts installs, not their state). It also fixes three blind spots: category-grouped plugin skills (`skills/<category>/<skill>/`) were never globbed — 35 installed, invocable `mattpocock-skills` unretrievable — now globbed at both depths with a structural phantom guard; `scope` and `tier` gained the payload indexes only `name` had, so the enforcer's filters stop linear-scanning ~25k points inside a hard 100ms cap; and `SKILL_CODEX_ROOTS` is now forwarded to the detached reindex (the ADR-0026 env-forwarding gap class).**

`0.24.0` — **published, ADR-0033 dual-harness Codex parity: the retriever indexes Codex's skill universe alongside Claude Code's (`~/.codex/skills` + `~/.codex/plugins/cache/**`) under distinct `codex-*` scopes so neither harness prunes the other's points; Codex plugin cache indexed unfiltered (config.toml is TOML, not stdlib-parseable on the 3.10 floor); chain-hint sidecar mirror reads the codex scopes; kill-switch `SKILL_CODEX_ROOTS=0` restores Claude-only discovery (a reindex prunes the codex points); test conftest pins the Codex seams so a populated ~/.codex cannot leak into fixtures; revives the abandoned July `feat/codex-dual-harness` attempt with its known test failures fixed.**

`0.23.0` — **published, ADR-0032 external catalogs first-class in the offer: an additive external annex (installed offer byte-identical whether on/off — a separate `must tier=external` query supplies ≤`ENFORCER_EXTERNAL_SLOTS`=2 externals ≥`ENFORCER_EXTERNAL_FLOOR`=0.40, so externals never take an installed slot), marked `[external:<alias>]` with the get_skill read-inline instruction; usage-promotion (`auto_promote.py`) graduates an external used across ≥`PROMOTE_MIN_TAKES`=3 distinct sessions to a real installed skill; ledger `ext` + `analyze.py` external offer→take conversion; kill-switch `ENFORCER_EXTERNAL_ANNEX=0` restores search-only; supersedes ADR-0031's search-only tier.**

`0.22.1` — **published, doctor fix: flywheel coverage + trigger-hygiene no longer count external catalog skills (tier=external) as "missing utterances" — `_indexed_skill_names()` excludes them, matching the generators that skip externals by design; a registered catalog no longer shows a permanent false coverage gap. Surfaced validating the 0.22.0 deploy.**

`0.22.0` — **published, ADR-0031 external catalog roots: third-party skill collections indexed for retrieval without installing — operator-owned `~/.claude/skill-concierge/catalog-roots.json`, skills minted `<alias>:<name>` under scope `catalog:<alias>` with `tier: external` on every point; search-only tier (never the per-turn offer preview; `search_skills` marks hits `external: <alias>` with a `get_skill` consumption note); promotion via symlink with collision refusal; skillOverrides/sidecar/flywheel all exclude catalogs by design; new `scripts/catalogs.py` + `skill-concierge:catalogs` skill + doctor `check_catalogs`; first catalog `antigravity` (1,603 skills) registered and indexed.**

`0.21.3` — **published, ADR-0030 operator-owned chain overrides: third-party `next-skills` curation moves to `~/.claude/skill-concierge/next-skills-overrides.json` (reader-side merge in the enforcer — the sidecar's only consumer — override-wins, `[]` suppresses, fail-open, absent file byte-identical), so an upstream upgrade can no longer silently wipe curated chains; 8 ak workflow chains seeded there (brainstorm→plan→cook→test→code-review→ship→journal + debug→fix→test) with all loaned frontmatter reverted and hints proven firing from overrides alone; keep-on router-guard false gap fixed (bare `skill-search` dropped, namespaced form accepted); `setup→doctor` chain rides the 0.21.3 cache.**

`0.21.2` — **published, enforcer `0.20s->0.35s` + `embed_ms`/`qdrant_ms` on every `offer` (diagnoses the `65%` fallback), `--latency` histogram in `analyze.py`, flywheel `max_tokens` `2048->4096` on the permanent `api.thinhkhuat.com` gateway (fixes `22× length` truncations), menu `10->6`, chain `ak-plan->ak-cook` (sidecar `3` chains), and `-24` stale overrides cleared — `doctor` now green.**

`0.21.1` — **published, the utterance-layer prune/rebuild flip-flop fixed: SKILL_TRIGGERS pinned to the durable home (~/.claude/skill-concierge/triggers.json) in .mcp.json — absolute path, since the ${HOME} literal survives only Claude Code's MCP launcher, not the json.load readers — and flywheel's post-generate reindex now forwards all 7 trigger-layer keys instead of 3, so it stops stripping the layer it just wrote. Incremental core and flywheel scoping proven sound by identical-env probes (embedded:0 / skipped:all). Also the first live ADR-0029 authoring: doctor declares next-skills: flywheel.**

`0.21.0` — **published, engine-side skill chaining: skills can declare `next-skills:` successors and the enforcer surfaces them one turn later as a filtered `CHAIN-HINT:` candidate line on every inject-bearing leg (ADR-0029). Scope-keyed atomic sidecar written at index time (413 keys live), bounded ledger tail-read for state (auto + slash invocations, subagent rows excluded, 15-min TTL) — zero new network, zero new state files; keep-off and catalogue membership filter every hinted name; `ENFORCER_CHAIN_HINT=0` reverts byte-identically. `analyze.py --chains` measures real sequences (first run: 130 sessions, 67 chained, top pair verify-as-claimed→session-handoff). A drafted multi-intent clause-split (number never issued; the later ADR-0030 is a different decision) was cut on dual review — `extra_queries` MAX-pool already provides per-intent retrieval and the doctrine now says so.**

`0.20.8` — **published, the engine-drift message no longer names a cause it cannot observe. One symptom hides two causes with opposite remedies: a server still live on the old build (restart — a reindex hands the mismatch back) or a manifest merely left over from the previous release (reindex — it re-stamps and clears). The text asserted the first while every engine upgrade lands in the second, because changing the engine necessarily changes the build id. The engine now offers both remedies and asserts neither; doctor, which holds the live-server evidence in the same pass, decides which applies, names the pids, and auto-fixes ONLY a fleet proven entirely on the current build. 0.20.7: doctor's `Running engine` check compares build IDENTITY, not file timestamps. 0.20.6 added the check and answered the question with `max(ctime, mtime)` of the venv engine — but `setup.sh` re-copies the engine on every run, so those timestamps advance even when the bytes do not, and the first deploy flagged three live servers while the engine's own `health()` correctly reported `stale: false`. Each MCP server now publishes the build it runs to `~/.cache/skill-search/servers/<pid>.json` at startup and doctor looks it up, so a no-op re-copy is invisible by construction; `started_at` guards pid reuse, CLI runs are excluded by their flags, and an engine too old to publish an id reports N/A rather than accusing every server. `health()` correspondingly emits `engine_build` on every report (`index_written_by: null` when clean) — consumers key on that field, never on the block's presence. 0.20.6: a frontmatter value is now indexed as its TEXT, without its YAML scalar syntax. `parse_skill()` took the regex capture verbatim, so `description: >-` carried the literal `">-"` plus every continuation line's newline and indent into the embedded text, and `description: "…"` kept its surrounding quotes — the retriever was scoring skills partly on punctuation. `_unwrap_scalar` now handles block scalars (literal keeps line breaks, folded folds to spaces), quoted flow scalars, and plain wrapped scalars, on `description:` and `when_to_use:` alike, still without a YAML dependency. Measured on this catalogue: 210 of 416 skills affected; after the fix, 0. Distinct from 0.20.4, which fixed where a value ENDS; this fixes the value's own syntax. Same release documents `docs/caveats.md` §16 — the always-on allowlist is a BUDGET, not a list: `skillOverrides` does not apply to plugin skills at all (63 of them ≈ 5.3k tok/turn only `/plugin disable` can reclaim), and past `skillListingBudgetFraction` Claude Code DROPS descriptions rather than truncating them, choosing by `usageCount × 0.5^(days/7)` — so a long description loses its slot to a shorter, less-used skill. 0.20.5: `setup.sh` now builds the index with the SAME trigger-layer composition the query server serves. Its `env_run()` forwarded only the embedder and store keys from `.mcp.json`, so every run rebuilt at engine defaults — `SKILL_LLM_TRIGGERS` off, `TRIGGERS_MAX` 12 — pruning the utterance points while the MCP served with the layer ON at 16. The server then reported its own freshly-built index as stale, permanently, and every `search_skills` reply carried a spurious "run reindex()" warning. This is the identical gap `auto_reindex._mcp_env()` closed in 0.16.1; setup.sh was never updated. It now reads the same four keys through the existing `read_mcp()` SSOT helper, exporting each only when non-empty (an empty `SKILL_LLM_TRIGGERS` would read as truthy and switch the layer on by accident). 0.20.4: a frontmatter value now ends at the NEXT key even when that key is hyphenated. The terminator was `(?=\n\w+:|\Z)`, and `\w` is `[A-Za-z0-9_]` — it excludes `-`, so `user-invocable:`, `argument-hint:` and `allowed-tools:` never stopped the capture and their raw key/value lines were swallowed into `description`. That polluted the skill listing and, worse, the EMBEDDED text: a vector carrying the literal "user-invocable: true" is noise that degrades retrieval. Measured on this catalogue: 168 of 356 personal skills affected, ~1.7k est. tokens of frontmatter junk indexed; after the fix, 0. 0.20.3: skill discovery now identifies a skill by its DIRECTORY name — the way Claude Code actually does. `parse_skill()` preferred frontmatter `name:`, so any skill whose `name:` differed from its folder got its `skillOverrides` entry written under a key Claude Code never looks up: the name-only budget silently never applied and the skill's full description stayed resident every turn, while `apply-overrides --check` still reported "in sync, no drift" (it only ever compared its own map to itself). Measured on a 606-skill catalogue: 122 skills mismatched, ~9.6k tokens of description resident per session, and 21 of 32 curated keep-on entries silently unmatched. Verified: `zread-cli` ships `name: zread` — a valid slug, not an unparseable one — and Claude Code still lists and overrides it as `zread-cli`. 0.20.2: `doctor` now catches junk ALREADY AT REST in the utterance layer (`Trigger hygiene`), and `--fix` purges it. 0.20.1 stopped a degraded model from *writing* junk; nothing audited what earlier runs had already stored — 5 skills were found holding empty strings, one-char noise and a phrase repeated three times. The reason it hid is load-bearing: coverage measures *presence*, not *validity* — a skill whose utterances are all junk still counts toward `N/M have utterances`, never shows as missing, and the generator then skips it forever (cache-hit + layer present); a green `467/467` was hiding junk. The check re-runs `clean_triggers()` over each live skill's stored layer, importing the junk definition rather than restating it so it cannot drift from the generator. `--fix` drops the poisoned layer (keeping any prose layer), clears the generation-cache key and reindexes, backing up `triggers.json` first — it never regenerates, because doctor never calls the LLM; the cleared cache key is what lets the next flywheel run rewrite the skill instead of skipping it. Still a *mechanical* filter: semantically-wrong but well-formed output passes. 0.20.1: the flywheel actually reaches the skills it was meant to fix. Three bugs, one symptom: `auto_flywheel` runs `--generate --limit 25`, but both generators sliced the alphabetically-sorted full skill list *before* filtering out already-covered skills — so every capped run burned its whole budget on no-ops (`generated=0`) while 29 skills sat with no utterances, permanently. The cap now applies after the filter (0/25 → 25/25 slots doing real work), restoring what `enforcement-gate.md` already documented. `doctor` separately reported `0/467` coverage on a fully-covered install because `check_flywheel()` ignored the `SKILL_TRIGGERS` env seam every other tool honours and read an absent `eval/` under the plugin cache; it now honours the seam and says "coverage unknown" rather than miscounting an absent file as zero. And `validate_reply()` only checked "a list of ≥4 strings", so a degraded local model poisoned the live index with empty strings, one-char noise and repeated phrases — while the Vietnamese-parity retry manufactured its own junk (pressed for Vietnamese, the model echoed the literal words `tiếng Việt`, which counted). Validation now runs on cleaned phrases; it catches malformed junk, not semantically-wrong-but-well-formed output. Generation model set to `gemma-4-12b-it-qat-optiq` via `FLYWHEEL_LLM_MODEL` on reliability grounds — 0.20.0's measured case for e4b is not refuted, and was not re-measured. 0.20.0: flywheel reliability: a truncated completion no longer silently costs a skill its triggers. `flywheel_llm.chat()` never inspected `finish_reason`, so a reply cut short at `max_tokens` surfaced as an opaque `JSONDecodeError` and the generator skipped that skill with only a `WARN` on stdout. `chat()` now raises `TruncatedCompletion` on any explicit `finish_reason != "stop"`, keying on the field rather than on whether the body parses — a `length` cut can leave syntactically valid but semantically short JSON. Root cause reproduced and independently validated: LM Studio enforces `json_schema` strictly (`pattern` and `minItems` alike), so a constraint the model is unlikely to satisfy masks the string-closing quote and generation runs to the token cap. Same release swaps the generation model default to `gemma-4-e4b-it-qat-optiq` (MRR `0.231 → 0.462`, mean rank `56.6 → 13.1` on a 20-probe held-out eval) and fixes a `FLYWHEEL_LLM_MODEL` default that pointed at a model no endpoint serves. 0.19.1: multi-session correctness — a globally-shared artifact must never be driven by a CWD-scoped view. `skillOverrides` lives in the global `~/.claude/settings.json`, but the override map was built from `discover_skills()`, whose project dir is `Path.cwd()/.claude/skills` — so each session saw the other's keys as drift and rewrote the global file, churning a backup every time. Project-scoped skills are now excluded; the map is identical from every CWD. 0.19.0: the same class of bug in the index (ADR-0028) — concurrent sessions sharing one Qdrant collection were pruning each other's project skills, since `build_index()` deleted any point absent from *its* view. Points now carry an owning `scope` (`personal`/`plugin`/`project:<root>`); only the installed + enabled plugin version is indexed (the cache is append-only and had been serving ancient versions and disabled plugins); `health()` stops false-alarming. 0.18.1: flywheel regen cache moved to the canonical durable home so `/plugin update` cannot wipe it. 0.18.0: `auto_flywheel` SessionStart hook + a global run manifest; smart `--generate` covers both generators for new/changed skills. 0.17.0: the retrieval flywheel promoted to first-class — multi-provider LLM routing, the `skill-concierge:flywheel` skill, and a fail-open `doctor` flywheel check. 0.16.1: stability fix for the utterance layer — the detached `auto_reindex` SessionStart hook only forwarded the embedder/store env from `.mcp.json`, so a background reindex rebuilt at engine defaults and pruned the utterance points every run; `auto_reindex._mcp_env()` now forwards the trigger-layer keys (`SKILL_LLM_TRIGGERS`/`TRIGGERS_MAX`/`SKILL_TRIGGERS`/`SKILL_BODY_TRIGGERS`) so the indexer builds the same index the query server serves. 0.16.0: LLM-utterance trigger layer (ADR-0026): offline flywheel-generated natural-utterance phrases (EN+VN, 532/532 skills) layered FIRST as MAX-pool trigger points, utterances-first + `TRIGGERS_MAX=16`, gated `SKILL_LLM_TRIGGERS`; shadow-vs-live gate rank-1 +7.0 / top-5 +8.4 / false-fire −0.4. 0.15.0: autonomous `skillOverrides` freshness + seamless keep-on management (ADR-0025): a SessionStart self-heal (`auto_overrides.py`) reconciles the name-only budget on catalogue drift the same way the index already self-heals, `doctor` now detects override drift, and `scripts/keep-on.py` + the `keep-on` skill make the always-on allowlist viewable/editable. 0.14.1: stale-index root-cause fix (retrieval-health detector fingerprints CONTENT not mtime — no more false 'disk changed since last index', ADR-0024). 0.14.0: anti-dodge integration (H1–H5, ADRs 0019–0023) — folds anti-skip doctrine craft + a measurement loop into the enforcement layer; see [`docs/anti-dodge-integration-v0.14.md`](docs/anti-dodge-integration-v0.14.md). Prior: self-healing MCP launcher (engine auto-resyncs on `/plugin update`, ADR-0018); MCP live, all three organs semantic, SKILL-FIRST gate + actionability gate live, bundled maintenance skills. Recall upgrades: `search_skills` query fanout — the caller passes 2–3 phrasings, the server MAX-pools the union so a skill a single phrasing buries still surfaces; the enforcer offer menu widened 5→8 (ADR-0017, supersedes ADR-0009); `SKILL_TOP_K=10` for the pull tool. Multi-vector MAX-pool retrieval (ADR-0012) also mines each skill body's labeled decision-sections (ADR-0016); the enforcer's two silent verdict legs emit a `SKILL-CHECK:` authorization (ADR-0015). Everything default-ON behind env kill-switches.**
**Retrieve** (MCP) + **Enforce** (the `enforcer.py` UserPromptSubmit hook sources candidates
from the SAME semantic index via a warm threaded embed shim, with a hard-timeout → mandate-only
fallback) + **Ledger** (telemetry: `offer`/`search`/hit@k/fallback). The legacy lexical
`skill_first_nudge.py` is retired (deregistered from `~/.claude/settings.json`).

The deployment now **self-guards against staleness**: doctor's `Engine freshness` check
(ADR-0013) catches a stale MCP venv engine after a `/plugin update`, and three SessionStart hooks
self-heal in the background — `auto_reindex` (ADR-0014) refreshes a stale index,
`auto_overrides` (ADR-0025) reconciles the name-only budget on catalogue drift, and
`auto_flywheel` (ADR-0027) generates utterances for new skills — no manual
reindex, re-apply, or reminders. Full per-version history in [`CHANGELOG.md`](CHANGELOG.md).

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

## Uninstall

Removing skill-concierge requires cleaning up across four harnesses plus the shared infrastructure. Each section below names what the installer created and the exact reversal steps.

### Shared components

Created by [`setup.sh`](setup.sh):

| Component | What is created | Reversal |
|-----------|-----------------|----------|
| Stable venv | `~/.claude/skill-concierge/venv/` — vendored engine + Python deps (`setup.sh:18`, step 1) | `rm -rf ~/.claude/skill-concierge/venv/` |
| Durable home | `~/.claude/skill-concierge/` — logs, keep-on policy (`keep-on.json`), telemetry ledger, utterance triggers (`triggers.json`), per-skill thresholds (`thresholds.json`), flywheel manifest, chain overrides (`next-skills-overrides.json`) | `rm -rf ~/.claude/skill-concierge/` |
| Qdrant container | Docker container `skill-search-qdrant` (`setup.sh:19`, step 2), image `qdrant/qdrant:1.18.2`, volume at `~/.cache/skill-search/qdrant-server/` | `docker rm -f skill-search-qdrant && docker rmi qdrant/qdrant:1.18.2 && rm -rf ~/.cache/skill-search/qdrant-server/` |
| Embed shim | Docker container `skill-concierge-embed-shim` (`setup.sh:21`, step 2b), image `skill-concierge-embed-shim:latest` | `docker rm -f skill-concierge-embed-shim && docker rmi skill-concierge-embed-shim:latest` |
| Old ledger migration | If the old path `~/.local/share/skill-concierge/` or `~/.claude/skill-telemetry/` exists from a pre-0.13 install, it is orphaned after setup. | `rm -rf ~/.local/share/skill-concierge/ ~/.claude/skill-telemetry/` |
| MCP launcher records (if enabled) | `~/.cache/skill-search/servers/<pid>.json` — per-launch build-id record | `rm -rf ~/.cache/skill-search/` |

No launchd agents are created — the warm embed shim runs as a Docker sidecar, not a launchd plist (the embed shim was switched to Docker sidecar before the first published release).

### Claude Code

Installed via the plugin marketplace. The plugin bundle (`.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`) is not written by a local installer — it is placed by the marketplace or by `cp` into `~/.claude/plugins/cache/skill-concierge/skill-concierge/<version>/`. The hooks wiring (`hooks/hooks.json` → `UserPromptSubmit` enforcer + ledger, `SessionStart` doctrine + self-heal, `PostToolUse` ledger) and MCP wiring (`.mcp.json` → shared `skill-search` server) ship with the plugin package.

**To uninstall:**
1. Disable the plugin: `/plugin disable skill-concierge` in Claude Code. This removes the hooks and MCP server from the running session without deleting data.
2. Fully remove: `/plugin uninstall skill-concierge` — deletes the versioned cache dir.
3. After either, clean shared components (venv, Qdrant, durable home) as described above.

### Codex

Wired by the plugin manifest `.codex-plugin/plugin.json` (`.codex-plugin/plugin.json:1-40`) and the matching MCP descriptor `.codex-plugin/mcp.json`. The hooks file `.codex/hooks.json` provides the openwiki-parity commit guard only (`.codex/hooks.json:2-16` — enforcement hooks auto-discover from the plugin cache per ADR-0033). Skill discovery indexes `~/.codex/skills/` and `~/.codex/plugins/cache/`.

**To uninstall:**
1. Remove the plugin from Codex's config (Codex CLI: remove the plugin entry from `~/.codex/skills/` and `~/.codex/plugins/cache/` or via the Codex UI).
2. Remove the hook file: `rm -f ~/.codex/hooks.json` (if nothing else relies on Codex hooks).
3. Remove any skill-concierge skill files from Codex roots: `rm -rf ~/.codex/skills/skill-concierge/` + check `~/.codex/plugins/cache/skill-concierge/`.
4. Optionally drop the scope env pins: `SKILL_CODEX_ROOTS` (revert from machine env or settings).

### Command Code

Installed by [`adapters/commandcode/install.sh`](adapters/commandcode/install.sh) — creates four things:

| File | Purpose | Installer line |
|------|---------|----------------|
| `~/.commandcode/mods/skill-concierge.ts` | Mod adapter — per-turn enforcer via `transformInput` | `install.sh:41-51` (step 1) |
| `~/.commandcode/settings.json` | Hook entries (SessionStart, skill-concierge skills array) | `install.sh:54-118` (step 2, inline python) |
| `~/.commandcode/mcp.json` | Skill-search MCP server (absolute paths) | `install.sh:121-152` (step 3, inline python) |
| `~/.commandcode/skills/` | Skill discovery root (indexed by the engine) | set by settings.json ref |

**To uninstall:**
1. Remove the mod: `rm -f ~/.commandcode/mods/skill-concierge.ts`
2. Remove the settings entries: edit `~/.commandcode/settings.json` to delete the `hooks` block that references skill-concierge scripts and the `skills` array entry for skill-concierge root. Alternatively restore from a backup or delete the file if empty.
3. Remove the MCP server: edit `~/.commandcode/mcp.json` to delete the `skill-search` server entry.
4. Remove skill files: `rm -rf ~/.commandcode/skills/skill-concierge/`
5. Optionally drop the scope env pin: `SKILL_COMMANDCODE_ROOTS`.

### Oh My Pi (OMP)

Installed by [`adapters/omp/install.sh`](adapters/omp/install.sh) — two possible paths:

**Marketplace-installed** (detected by reading `~/.omp/plugins/installed_plugins.json` for `skill-concierge@skill-concierge`, `install.sh:50-63`):
- Extension module at the OMP plugin's own path, loaded via the plugin manifest's `omp.extensions`.
- MCP server imported from the plugin's `.mcp.json` (no separate MCP wiring — `install.sh:143-144` deliberately skips writing `~/.omp/agent/mcp.json` to avoid a duplicate-server hazard).

**Dev-mode** (no marketplace install, `install.sh:64-125`):
- `~/.omp/agent/config.yml` gets a `# skill-concierge extension entry (ADR-0039)` marker line and the extension module path appended to the `extensions:` list (`install.sh:46-47`, inline python edit).

**Shared for both paths:**
- Skill discovery roots: `~/.omp/agent/skills/` (`omp-personal` scope), `~/.omp/agent/managed-skills/` (`omp-managed` scope), `~/.omp/plugins/cache/plugins/**` (`omp-plugin` scope).

**To uninstall:**
1. Marketplace: remove the plugin via the OMP CLI marketplace interface (or `~/.omp/plugins/installed_plugins.json` → delete the `skill-concierge@skill-concierge` entry).
2. Dev-mode: edit `~/.omp/agent/config.yml` to delete the skill-concierge marker line and its extension path from the `extensions:` list.
3. Optionally remove skill files from OMP roots: `rm -rf ~/.omp/agent/skills/skill-concierge/ ~/.omp/agent/managed-skills/skill-concierge/` + check `~/.omp/plugins/cache/plugins/skill-concierge/`.
4. Optionally drop the scope env pins: `SKILL_OMP_ROOTS`.

After removing a harness, run `skill-concierge:doctor --fix` or `python3 scripts/doctor.py --fix` to reindex the shared catalogue (the harness's scope points are pruned at the next reindex).

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
