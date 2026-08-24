# skill-concierge

[![version](https://img.shields.io/badge/version-0.24.0-blue.svg)](CHANGELOG.md)
[![license](https://img.shields.io/badge/license-MIT-green.svg)](#license)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-plugin-8A2BE2.svg)](https://docs.claude.com/en/docs/claude-code)
[![built on](https://img.shields.io/badge/built%20on-skill--search-orange.svg)](https://github.com/sowhan/skill-search)

A **skill-governance layer** over Claude Code and Codex's default skill mechanisms. Where the
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

Claude Code and Codex's default skill discovery injects **every** installed skill's description into
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
| [Claude Code](https://docs.claude.com/en/docs/claude-code) or [Codex](https://codex.openai.com) | host for the plugin, hooks, and MCP server |
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
├── .claude-plugin/{plugin,marketplace}.json   # Claude Code manifests (bump ALL THREE versions together)
├── .codex-plugin/plugin.json                  # Codex manifest (dual-harness, ADR-0033; no hooks field — hooks auto-discovered)
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

`0.25.0` — **published, ADR-0034 cross-harness offer isolation (amends ADR-0033): the per-turn installed offer now holds only skills the RUNNING harness can invoke — measured live over six prompts, 18 of 48 rows named skills the Skill tool cannot invoke here; after, 0 of 48, offers still a full 8 rows. `_retrieve` over-fetches to `TOP_K*3` and POST-filters, because scope records where a skill's indexed copy LIVES, not whether this harness can invoke it: Claude Code layers plugin enablement across user/project/local settings while discovery reads only the user file, so 24 `agent-skills:*` skills Claude invokes fine carry `scope: codex-plugin` — a query-side filter deleted all 24 and labelled them 'NOT invocable here'. `_invocable_twin()` resolves the merged settings per session, in the hook rather than the machine-global index. The rest re-surface from a separate query as a marked `[codex]`/`[claude]` annex consumed via `get_skill` (≤`ENFORCER_FOREIGN_SLOTS`=2, ≥`ENFORCER_FOREIGN_FLOOR`=0.40). Foreign scopes are derived per harness (`codex-personal` / `personal` included only when the two personal roots are distinct dirs); harness detection uses precedence and never resolves a falsy path (`Path("")` is the cwd, which would invert the filter); both annex queries moved past the getaway/actionability gates; `search_skills` and chain hints keep the ADR-0033 union; ledger `xh` field + `analyze.py` consumer; kill-switch `ENFORCER_CROSS_HARNESS=0`. Same release fixes three blind spots: category-grouped plugin skills (`skills/<category>/<skill>/`) were never globbed — 35 installed, invocable `mattpocock-skills` unretrievable — now globbed at both depths with a structural phantom guard; `scope` and `tier` gained the payload indexes only `name` had, so the enforcer's filters stop linear-scanning ~25k points inside a hard 100ms cap; and `SKILL_CODEX_ROOTS` is now forwarded to the detached reindex (the ADR-0026 env-forwarding gap class).**

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
