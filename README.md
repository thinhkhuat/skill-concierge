# skill-concierge

[![version](https://img.shields.io/badge/version-0.65.0-blue.svg)](CHANGELOG.md)
[![license](https://img.shields.io/badge/license-MIT-green.svg)](#license)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-plugin-8A2BE2.svg)](https://docs.claude.com/en/docs/claude-code)
[![built on](https://img.shields.io/badge/built%20on-skill--search-orange.svg)](https://github.com/sowhan/skill-search)

A **skill-governance layer** over the default skill mechanisms of Claude Code, Codex, Command Code, Oh My Pi (OMP), ZCode, DeepSeek Harness (DSH), Cline, and OpenCode v2. Where the
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

The default skill discovery in the supported harnesses (see the [harness matrix](#harness-matrix)) injects **every** installed skill's description into
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
| **Retrieve** | *Which* skill fits this task? | semantic search over the skill catalogue (a local index owner speaking Qdrant's REST format + multilingual embeddings — [ADR-0070](docs/adr/0070-local-index-owner-replaces-qdrant-and-docker-embed-shim.md)), including a MAX-pool trigger layer mined from both each skill's description **and** its body's labeled decision sections (`## When to Use`, `Triggers:`, `Use when:`) — [ADR-0012](docs/adr/0012-multi-vector-max-pool-retrieval.md), [ADR-0016](docs/adr/0016-body-derived-trigger-points.md) |
| **Enforce** | *Whether* the model uses a skill at all (vs winging it) | a per-turn hook that hands over the right candidates under a use-mandate; on its silent verdicts (four legs: score-floor miss, conversational turn, self-recap, harness message) it injects a `SKILL-CHECK:` authorization instead of nothing — [ADR-0015](docs/adr/0015-authorized-skip-tier-and-library-doctrine.md), [ADR-0054](docs/adr/0054-harness-message-lane-and-audit-fixes.md) |
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
| [Claude Code](https://docs.claude.com/en/docs/claude-code), [Codex](https://codex.openai.com), [Command Code](https://github.com/sst/command-code), [Oh My Pi](https://ohmy.pi), [ZCode](https://z.ai), [OpenCode v2](https://opencode.ai/v2/docs/), DeepSeek Harness (DSH), or Cline | host for the plugin, hooks, and MCP server (one or more of the [harness matrix](#harness-matrix)) |
| Python | 3.10–3.12 (set `SKILL_PYTHON` to pin a specific interpreter) |

> No Docker. The vector store and the warm embedder are one local process — the index
> owner (`python -m skill_search.index_owner`, [ADR-0070](docs/adr/0070-local-index-owner-replaces-qdrant-and-docker-embed-shim.md))
> — that `setup.sh` starts itself. The embedding model (`paraphrase-multilingual-mpnet-base-v2`,
> 768-dim) downloads on first index build via `fastembed` — no API key, fully local.

## Install & setup

skill-concierge is developed **local-first** in a workbench and published as a Claude Code
plugin at <https://github.com/thinhkhuat/skill-concierge>.

```bash
git clone https://github.com/thinhkhuat/skill-concierge.git
cd skill-concierge
./setup.sh          # builds the stable venv, starts the index owner, reindexes, applies overrides
```

`setup.sh` is idempotent and safe to re-run. It performs four steps:

1. **Stable venv** — installs the vendored engine + deps into `~/.claude/skill-concierge/venv`
   (outside the plugin cache, so it survives reinstalls — [ADR-0004](docs/adr/0004-bundled-mcp-launcher-stable-venv.md)).
2. **Index owner** — starts the local index owner (`python -m skill_search.index_owner`, from
   the stable venv) on `127.0.0.1`/`::1`, port `6333` (Qdrant-compatible REST) and `6363`
   (`/embed`+`/health`+`/jev`) — no Docker, no container ([ADR-0070](docs/adr/0070-local-index-owner-replaces-qdrant-and-docker-embed-shim.md)).
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

For a **deliberated curation** — "which skills should I use for X", the best chain for a
multi-part task planned before work starts — run the `skill-concierge:consult` skill
([ADR-0049](docs/adr/0049-consult-deliberation-layer.md)): a wide sieve over installed
AND external-catalog skills, capsule dossiers, a body-reading analyst subagent, and a
ranked RUN/⚠/ALSO verdict with promote-ready external picks. The per-turn offer stays
untouched; consult is the opt-in planning step. Since 0.43.0 the enforcer also ROUTES
deliberation-shaped turns there ("which skills should I use for X") via a
`CONSULT-ROUTE` mandate (ADR-0049 phase 2, `SKILL_CONSULT_ROUTE=0` to disable).

### MCP tools

The vendored engine exposes five tools (`vendor/skill-search/skill_search/server.py`):

| Tool | Purpose |
|------|---------|
| `search_skills` | rank skills by semantic relevance to a query |
| `consult_candidates` | wide multi-sub-goal recall with capsule dossiers — the consult skill's sieve ([ADR-0049](docs/adr/0049-consult-deliberation-layer.md)) |
| `get_skill` | fetch one skill's full description (for thin-description tie-breaks) |
| `reindex` | rebuild the catalogue index after skills change |
| `health` | report index status (collection, count, embedder) |

Since `0.48.0` ([ADR-0058](docs/adr/0058-off-list-rule-exclusion-echo-row-provenance-synced-default-off.md))
`search_skills` and `consult_candidates` rows drop the slash `command` field on every non-catalog
row and gain `origin` (which harness's roots hold the indexed copy — `claude`, `codex`,
`commandcode`, `omp`, `zcode`, `dsh`, `cline`, `opencode`, or `claude-synced`) and `disabled_in` (present when
an installed Claude Code plugin has every installed copy switched off in its merged `enabledPlugins` layers — the per-turn hook's own rule, so a plugin Claude can run is never marked; account-synced rows list every non-Claude harness), plus one response-level `note`
explaining both. `SKILL_ROW_ORIGIN=0` restores the pre-`0.48.0` row shape exactly.

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

## Configuration

### MCP environment (`.mcp.json`)

The live MCP server and `setup.sh` read these from `.mcp.json` (single source of truth, so
the built index can't diverge from the model the server uses):

| Variable | Default | Meaning |
|----------|---------|---------|
| `SKILL_QDRANT_URL` | `http://localhost:6333` | the local index owner's Qdrant-compatible REST endpoint — the name and port are kept for compatibility (no rename, no config change; [ADR-0070](docs/adr/0070-local-index-owner-replaces-qdrant-and-docker-embed-shim.md)) |
| `SKILL_EMBED_BACKEND` | `fastembed` | embedding backend |
| `SKILL_EMBED_MODEL` | `sentence-transformers/paraphrase-multilingual-mpnet-base-v2` | embedding model |

### Setup overrides (environment)

`setup.sh` honours these for non-default machines:

| Variable | Default |
|----------|---------|
| `SKILL_PYTHON` | first of `python3.12/3.11/3.10` on `PATH` |
| `SKILL_CONCIERGE_VENV` | `~/.claude/skill-concierge/venv` |
| `SKILL_INDEX_DB` | `~/.cache/skill-search/index.sqlite` — the index owner's one SQLite file |
| `SKILL_CONCIERGE_LOG` | `~/.claude/skill-concierge/logs` (ledger directory) |

`SKILL_QDRANT_CONTAINER` (default `skill-search-qdrant`) and `SKILL_EMBED_CONTAINER`
(default `skill-concierge-embed-shim`) are no longer read by `setup.sh` — they only name the
two legacy Docker containers `doctor.py`/`doctor.py --fix` recognize and stop if an old harness
copy revives them onto the owner's ports (`SKILL_QDRANT_IMAGE` is unused; nothing pins an image
anymore).

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
| `SKILL_AUTO_FLYWHEEL` | `1` (ON) | the `auto_flywheel` SessionStart hook auto-generates utterances for new/changed skills when the endpoint is reachable (detached, throttled, fail-open — ADR-0027). The detached run covers installed skills first, then each configured external catalog via a per-alias serial loop, each pass capped (0.35.1 shape, reinstated by ADR-0047). `=0` disables; manual `skill-concierge:flywheel --generate` still works. |
| `AUTO_FLYWHEEL_THROTTLE_S` | `21600` (6h) | min seconds between background auto-flywheel runs. |
| `AUTO_FLYWHEEL_WORKERS` | `4` | concurrent LLM calls per auto-flywheel run — network phase only, file writes stay single-writer (0.35.1, ADR-0043). |
| `AUTO_FLYWHEEL_MAX_PER_RUN` | `25` | cap on skills generated per background run (protects metered endpoints). |

### Runtime governance flags

Every behavior-changing kill-switch, with its default, code owner and ADR, is indexed in
[`AGENTS.md`](AGENTS.md) → *Runtime flags*; each flag's full text, tuning knobs and preconditions
are in [`docs/runtime-flags.md`](docs/runtime-flags.md). Most flags turn one behavior on or off with
one variable; a few (`SKILL_TRIGGER_PURITY`, `ENFORCER_JEV_BENCH`, `ENFORCER_JEV_TIER`) take a value.
Index-shaping flags need a reindex after a change.

### Always-on policy (the keep-on allowlist)

A curated always-on allowlist (the seed holds 31 skills); every other skill is `name-only` (retrieved on demand).
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

### Blocklist (disable a skill)

A user-ordered **disable tier**, origin-agnostic ([ADR-0046](docs/adr/0046-blocklist-disable-tier.md)):
personal skills, plugin skills, external catalog entries, and command-files surfaced as
skills (`~/.claude/commands/*.md` — which the index deliberately excludes, so only the
invocation guard can catch them). A blocked skill is never offered, never returned by
`search_skills`, never served by `get_skill`, and its Skill-tool invocation is **denied**
by the PreToolUse guard — the repo's second deliberate denying gate. The flat list lives at
`~/.claude/skill-concierge/blocklist.json` and is read live (no reindex, no restart); a
**bare** entry blocks every qualified twin (`plugin:name`, `alias:name`), a **qualified**
entry blocks only that exact form.

```bash
python3 scripts/blocklist.py list                  # view the disabled set
python3 scripts/blocklist.py add <skill-name>…     # disable (forces keep-on name-only)
python3 scripts/blocklist.py remove <skill-name>…  # re-enable
```

Kill-switch: `SKILL_BLOCKLIST=0` turns the whole feature off everywhere (guard, enforcer,
engine, overrides). Doctor reports the list and fails if the deny guard is missing.

### Reputation (rank skills with badges)

The owner's own ranking, shown next to a skill on the menu ([ADR-0083](docs/adr/0083-owner-reputation-badges.md)):
❤️ house favourite and ⭐ trusted from `~/.claude/skill-concierge/reputation.json`, and 🔥 for a
skill used in at least 5 separate sessions in the last 30 days. A badge never moves a row; the
menu's legend tells the agent to choose among rows that do the job, ❤️ first, then ⭐. A ranked
skill Jev placed 6th-10th but judged a fit joins the menu under its five rows.

```bash
python3 scripts/reputation.py list                         # both tiers and the 🔥 list
python3 scripts/reputation.py add heart ak-code-review     # house favourite
python3 scripts/reputation.py add star 'pstack:*'          # trust a whole family
python3 scripts/reputation.py why ak-git                   # which badge, from which entry
python3 scripts/reputation.py suggest [--apply]             # tier changes from usage; --apply writes ⭐ adds and removals, never a ❤️
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
Embeddings + body triggers only by default — the flywheel utterance layer skips externals from
default coverage, but since `0.35.0` an owner-commissioned `flywheel --generate --catalog <alias>`
run generates them for one named catalog ([ADR-0043](docs/adr/0043-catalog-flywheel-generation-and-bounded-parallel-workers.md)).
A bare `--generate` covers installed skills only ([ADR-0043](docs/adr/0043-catalog-flywheel-generation-and-bounded-parallel-workers.md);
the one-day ADR-0045 every-scope default was reverted by
[ADR-0047](docs/adr/0047-revert-tier-parity-restore-annex.md)) — catalogs are covered by the
auto-flywheel's per-alias loop and by explicit `--catalog <alias>` runs.

Externals are **first-class in the per-turn offer**, not just explicit search
([ADR-0032](docs/adr/0032-external-catalogs-first-class-annex.md)): an **additive annex** that
never displaces an installed row. A separate query appends externals clearing
`ENFORCER_EXTERNAL_FLOOR` (0.32), marked `[external:<alias>]` with the `get_skill` consumption
instruction. The annex is the installed top's **complement, not its echo**
([ADR-0048](docs/adr/0048-complement-annex.md)): when the installed top is at or above
`GETAWAY_FLOOR` (0.45) an external must beat it by `ENFORCER_ANNEX_BEAT` (0.04), and below it the
annex widens at the plain floor. Externals with demonstrated usage float first and render
`used N×`; chain hints and mined chains are installed-only. An external used across
≥ `PROMOTE_MIN_TAKES` (3) distinct sessions **auto-graduates** to an installed skill
(`hooks/scripts/auto_promote.py`). Kill-switches: `ENFORCER_EXTERNAL_ANNEX=0` (search-only tier),
`ENFORCER_ANNEX_COMPLEMENT=0`. The one-day merged-pool "tier parity" experiment
([ADR-0045](docs/adr/0045-catalog-tier-parity.md)) was reverted by
[ADR-0047](docs/adr/0047-revert-tier-parity-restore-annex.md); the annex floor and margin keep the
friendlier ADR-0047 defaults.

## Architecture

The file layout lives in one place: [`docs/repository-layout.md`](docs/repository-layout.md) (one
line per area in [`AGENTS.md`](AGENTS.md)). The engine source is vendored for portability; its
Python deps, the local index owner, the embedding model, the index, and the `settings.json`
overrides are **reproduced by `setup.sh`**, not embedded.

### Harness matrix

skill-concierge is a first-class citizen in these eight harnesses. Enforcement rides whatever
each harness's extension mechanism supports (settings hooks for Claude Code, a mod adapter for
Command Code, a TS extension module for OMP — Codex auto-discovers hooks, no `hooks` field; ZCode
natively runs the Claude-format plugin hooks; DSH rides a Cordis `agent/pre-step` plugin; Cline
loads a native code plugin plus a generated Agent Plugin, with file hooks as the fallback;
OpenCode v2 loads a native plugin — the last three via
`adapters/dsh/`, `adapters/cline/` and `adapters/opencode/`);
discovery always indexes **all** harnesses' roots into one shared collection (served by the
local index owner in Qdrant's REST shape) under distinct per-harness scopes (fail-open — a
harness you don't run is simply absent from disk);
and the MCP server is wired per-harness from the shared descriptor, never duplicated.

| Harness | Discovery roots (scopes) | Enforcement vehicle | MCP wiring |
|---------|--------------------------|---------------------|------------|
| Claude Code | `~/.claude/skills`, `$CWD/.claude/skills`, `~/.claude/plugins/cache/**` (`personal`/`project`/`plugin`), `~/.claude/skills/synced/**` (`claude-synced`, default OFF) | `UserPromptSubmit` settings hook → `enforcer.py` + SessionStart doctrine | shared `.mcp.json` |
| Codex | `~/.codex/skills`, `$CWD/.codex/skills`, `~/.codex/plugins/cache/**` (`codex-*`) | auto-discovered settings hooks (no `hooks` field; ADR-0033) | `.codex-plugin/mcp.json` (relative command; ADR-0035) |
| Command Code | `~/.commandcode/skills`, `$CWD/.commandcode/skills` (`commandcode-*`) | mod adapter `transformInput` (`adapters/commandcode/skill-concierge.mod.ts`; ADR-0038) | `adapters/commandcode/mcp.json` (absolute paths; ADR-0038) |
| Oh My Pi (OMP) | `~/.omp/agent/skills`, `$CWD/.omp/skills`, `~/.omp/agent/managed-skills`, `~/.omp/plugins/cache/plugins/**` (`omp-*`) | extension module `before_agent_start` (`adapters/omp/skill-concierge.ext.ts` via `package.json` `omp.extensions`; ADR-0039) | plugin `.mcp.json` imported natively (`${CLAUDE_PLUGIN_ROOT}` expanded by OMP); `adapters/omp/mcp.json` manual fallback only |
| ZCode | `~/.zcode/skills`, `$CWD/.zcode/skills`, `$CWD/.agents/skills`, `~/.zcode/cli/plugins/cache/**` (registry-enumerated) (`zcode-*`) | **none needed** — ZCode natively runs the plugin `hooks/hooks.json` (ADR-0042) | plugin `.mcp.json` auto-connected (interpreter-form command, exec-bit-proof); `adapters/zcode/mcp.json` manual fallback only |
| DeepSeek Harness (DSH) | `DSH_HOME/skills`, `$CWD/.dsh/skills` (`dsh-*`) | Cordis plugin `agent/pre-step` (`adapters/dsh/skill-concierge.dsh.ts`; ADR-0050) | Cordis `cordis.patch.yml` row via the `dsh-mcp-client` bridge (`mcp__skill-search__*`); `adapters/dsh/mcp.json` reference |
| Cline | `~/.cline/data/settings/skills`, `$CWD/.cline/skills` (`cline-*`) | native code plugin (`adapters/cline/skill-concierge.cline-plugin.ts`, loaded through `~/.cline/plugins/skill-concierge.ts`) plus a generated Agent Plugin (`~/.agents/plugins/skill-concierge/`) (ADR-0086; the ADR-0051 file-hook vehicle is retired) | the Agent Plugin's `mcp.json`, which Cline starts itself |
| OpenCode v2 | `~/.config/opencode/skills`, `$CWD/.opencode/skills` (`opencode-*`); `personal` invocable via OpenCode's documented compat read of `~/.claude/skills` | native v2 plugin — `session.hook("prompt")` + `context` system-part doctrine/enforcer, `permission.hook` blocklist deny, `tool.hook("execute.after")` ledger+echo (`adapters/opencode/plugin/`; ADR-0085) | `ctx.mcp.transform` registers the server from the shared `.mcp.json` (no manual config at all) |

`SKILL_CODEX_ROOTS` / `SKILL_COMMANDCODE_ROOTS` / `SKILL_OMP_ROOTS` / `SKILL_ZCODE_ROOTS` /
`SKILL_DSH_ROOTS` / `SKILL_CLINE_ROOTS` / `SKILL_OPENCODE_ROOTS`
(all default ON) are one-var reverts that drop that harness's roots + scopes byte-identically.
`SKILL_SYNCED_ROOTS` is the one root flag that ships the other way — **default OFF** — because
Claude's own account-synced skills would render as installed in a harness cache still below
`0.48.0`; `=1` (a separate, reviewed step) + a reindex adds the `claude-synced` scope
(see AGENTS.md → Runtime flags).

### How a request flows

SessionStart doctrine and self-heals, the per-turn `UserPromptSubmit` gate, on-demand
`search_skills`, the PostToolUse ledger and the "not for" echo (`skill_exclusions.py`, ADR-0058),
and curation are walked through in
[`openwiki/architecture/three-organs.md`](openwiki/architecture/three-organs.md) (the per-turn
gate in detail: [`enforcement-gate.md`](openwiki/architecture/enforcement-gate.md)).

## Status & roadmap

Current release: `0.65.0` — **published**. Per-version history, including every release since
`0.1.0`, lives in [`CHANGELOG.md`](CHANGELOG.md); the decisions behind them are in
[`docs/adr/`](docs/adr/README.md). Per-epoch watch items (what to monitor after a release,
triggers, env-first actions): [`docs/epoch-watch.md`](docs/epoch-watch.md) — the single canonical
reference.

The deployment **self-guards against staleness**: doctor's `Engine freshness` check (ADR-0013)
catches a stale MCP venv engine after a `/plugin update`, and three SessionStart hooks self-heal in
the background — `auto_reindex` (ADR-0014) refreshes a stale index, `auto_overrides` (ADR-0025)
reconciles the name-only budget on catalogue drift, and `auto_flywheel` (ADR-0027) generates
utterances for new skills.

## Troubleshooting

**Start here:** run the **`skill-concierge:doctor`** skill (or `python3 scripts/doctor.py`) —
it diagnoses the venv, the local index owner, MCP wiring, overrides, and retrieval health, and
`--fix` auto-repairs most of the rows below (start the index owner, reindex, re-apply overrides).

| Symptom | Cause & fix |
|---------|-------------|
| `/mcp` shows skill-search **not connected** (`-32000` / ENOENT) | The engine venv is missing. Run `bash setup.sh` once, then restart Claude Code. The launcher only execs a **stable** venv — it never builds on spawn ([ADR-0004](docs/adr/0004-bundled-mcp-launcher-stable-venv.md)). |
| Two `skill-search` servers listed | A leftover user-scope MCP. Remove it: `claude mcp remove skill-search -s user`. |
| `setup.sh` aborts at step 2 ("index owner did not come up") | See `~/.claude/skill-concierge/logs/index-owner.log` for the reason (port already held by something else, a crashed model load, …); no Docker daemon is involved. |
| Vendored eval prints recall@k ≈ `0.00` | **Not a bug.** The eval labels target a different skill universe — see [caveats §1](docs/caveats.md). |

Full landmine list: [`docs/caveats.md`](docs/caveats.md).

## Uninstall

Removing skill-concierge requires cleaning up each harness you installed it into (the [harness matrix](#harness-matrix) lists all eight) plus the shared infrastructure. Each section below names what the installer created and the reversal steps.

### Shared components

Created by [`setup.sh`](setup.sh):

| Component | What is created | Reversal |
|-----------|-----------------|----------|
| Stable venv | `~/.claude/skill-concierge/venv/` — vendored engine + Python deps (`setup.sh`, step 1) | `rm -rf ~/.claude/skill-concierge/venv/` |
| Durable home | `~/.claude/skill-concierge/` — logs, keep-on policy (`keep-on.json`), telemetry ledger, utterance triggers (`triggers.json`), per-skill thresholds (`thresholds.json`), flywheel manifest, chain overrides (`next-skills-overrides.json`) | `rm -rf ~/.claude/skill-concierge/` |
| Index owner | A local process (`python -m skill_search.index_owner`, `setup.sh`, step 2) started from the stable venv — no container, no image ([ADR-0070](docs/adr/0070-local-index-owner-replaces-qdrant-and-docker-embed-shim.md)); its data is one SQLite file at `~/.cache/skill-search/index.sqlite` (`SKILL_INDEX_DB`) | Confirm the listener is the owner (`curl -s 127.0.0.1:6333/` shows the owner's title), then stop it: `kill $(lsof -nP -t -iTCP:6333 -sTCP:LISTEN)` (listening socket only — a bare `lsof -ti :6333` also matches clients and whatever publishes the port). Then `rm -rf ~/.cache/skill-search/` |
| Old ledger migration | If the old path `~/.local/share/skill-concierge/` or `~/.claude/skill-telemetry/` exists from a pre-0.13 install, it is orphaned after setup. | `rm -rf ~/.local/share/skill-concierge/ ~/.claude/skill-telemetry/` |
| MCP launcher records (if enabled) | `~/.cache/skill-search/servers/<pid>.json` — per-launch build-id record | `rm -rf ~/.cache/skill-search/` |

No launchd agents are created — the index owner is started on demand by `bin/skill-search-mcp`,
the enforcer hook, and `setup.sh` (ADR-0070), never by a launchd plist. If an older install left
`skill-search-qdrant` and/or `skill-concierge-embed-shim` Docker containers behind, remove them
too: `docker rm -f skill-search-qdrant skill-concierge-embed-shim` (image names vary by install
date; `docker images` lists what is left to `docker rmi`).

### Claude Code

Installed via the plugin marketplace. The plugin bundle (`.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`) is not written by a local installer — it is placed by the marketplace or by `cp` into `~/.claude/plugins/cache/skill-concierge/skill-concierge/<version>/`. The hooks wiring (`hooks/hooks.json` → `UserPromptSubmit` enforcer + ledger, `SessionStart` doctrine + self-heal, `PostToolUse` ledger) and MCP wiring (`.mcp.json` → shared `skill-search` server) ship with the plugin package.

Once installed once via `claude plugin marketplace add` + `claude plugin install`, [`adapters/claude-code/install.sh`](adapters/claude-code/install.sh) keeps the cached copy in sync with this checkout's SSOT version: it runs `claude plugin update skill-concierge@skill-concierge --json -y`, and — only when the marketplace remote hasn't caught up to this checkout yet — falls back to a local `git archive` sync plus a backed-up `installed_plugins.json` repoint. It never touches `enabledPlugins` in `settings.json` or the shared venv/Qdrant stamp, and a session restart is required to pick up a freshly-synced version. Whether Claude Code's own update/session-start logic accepts a hand-repointed registry entry is **unverified** — treat the fallback path as provisional until confirmed by a real update + restart.

**To uninstall:**
1. Disable the plugin: `/plugin disable skill-concierge` in Claude Code. This removes the hooks and MCP server from the running session without deleting data.
2. Fully remove: `/plugin uninstall skill-concierge` — deletes the versioned cache dir.
3. After either, clean shared components (venv, index owner, durable home) as described above.

### Codex

Wired by the plugin manifest `.codex-plugin/plugin.json` and the matching MCP descriptor `.codex-plugin/mcp.json`. The hooks file `.codex/hooks.json` provides the openwiki-parity commit guard only (enforcement hooks auto-discover from the plugin cache per ADR-0033). Skill discovery indexes `~/.codex/skills/` and `~/.codex/plugins/cache/`.

Once registered once via `codex plugin marketplace add` + `codex plugin add skill-concierge@skill-concierge`, [`adapters/codex/install.sh`](adapters/codex/install.sh) keeps the cached copy in sync with this checkout's version; how it does that and what it refuses is explained in [`docs/repository-layout.md`](docs/repository-layout.md) (`adapters/`) and the installer's own header.

**To uninstall:**
1. Remove the plugin and its cache with Codex's own CLI: `codex plugin remove skill-concierge@skill-concierge`. The plugin's enforcement hooks are auto-discovered from the plugin, so they go with it; the installer writes no hooks file under `~/.codex/` (the repo's `.codex/hooks.json` is the openwiki commit gate, used only inside a checkout).
2. Optionally drop the marketplace source: `codex plugin marketplace remove skill-concierge`.
3. Remove any skill-concierge skill files you copied into Codex roots: `rm -rf ~/.codex/skills/skill-concierge/`.
4. Optionally drop the scope env pins: `SKILL_CODEX_ROOTS` (revert from machine env or settings).

### Command Code

Installed by [`adapters/commandcode/install.sh`](adapters/commandcode/install.sh) — creates four things:

| File | Purpose | Installer step |
|------|---------|----------------|
| `~/.commandcode/mods/skill-concierge.ts` | Mod adapter — per-turn enforcer via `transformInput` | (step 1) |
| `~/.commandcode/settings.json` | Hook entries (SessionStart, skill-concierge skills array) | (step 2, inline python) |
| `~/.commandcode/mcp.json` | Skill-search MCP server (absolute paths) | (step 3, inline python) |
| `~/.commandcode/skills/` | Skill discovery root (indexed by the engine) | set by settings.json ref |

**To uninstall:**
1. Remove the mod: `rm -f ~/.commandcode/mods/skill-concierge.ts`
2. Remove the settings entries: edit `~/.commandcode/settings.json` to delete the `hooks` block that references skill-concierge scripts and the `skills` array entry for skill-concierge root. Alternatively restore from a backup or delete the file if empty.
3. Remove the MCP server: edit `~/.commandcode/mcp.json` to delete the `skill-search` server entry.
4. Remove skill files: `rm -rf ~/.commandcode/skills/skill-concierge/`
5. Optionally drop the scope env pin: `SKILL_COMMANDCODE_ROOTS`.

### Oh My Pi (OMP)

Installed by [`adapters/omp/install.sh`](adapters/omp/install.sh) — two possible paths:

**Marketplace-installed** (detected by reading `~/.omp/plugins/installed_plugins.json` for `skill-concierge@skill-concierge`):
- Extension module at the OMP plugin's own path, loaded via the plugin manifest's `omp.extensions`.
- MCP server imported from the plugin's `.mcp.json` (no separate MCP wiring — the installer deliberately skips writing `~/.omp/agent/mcp.json` to avoid a duplicate-server hazard).

**Dev-mode** (no marketplace install):
- `~/.omp/agent/config.yml` gets a `# skill-concierge extension entry (ADR-0039)` marker line and the extension module path appended to the `extensions:` list (inline python edit).

**Shared for both paths:**
- Skill discovery roots: `~/.omp/agent/skills/` (`omp-personal` scope), `~/.omp/agent/managed-skills/` (`omp-managed` scope), `~/.omp/plugins/cache/plugins/**` (`omp-plugin` scope).

**To uninstall:**
1. Marketplace: remove the plugin via the OMP CLI marketplace interface (or `~/.omp/plugins/installed_plugins.json` → delete the `skill-concierge@skill-concierge` entry).
2. Dev-mode: edit `~/.omp/agent/config.yml` to delete the skill-concierge marker line and its extension path from the `extensions:` list.
3. Optionally remove skill files from OMP roots: `rm -rf ~/.omp/agent/skills/skill-concierge/ ~/.omp/agent/managed-skills/skill-concierge/` + check `~/.omp/plugins/cache/plugins/skill-concierge/`.
4. Optionally drop the scope env pins: `SKILL_OMP_ROOTS`.

### ZCode

Installed through ZCode's own plugin marketplace (it natively reads the `.claude-plugin/` manifest — no adapter files are written outside the plugin cache; ADR-0042). The cached copy lives under `~/.zcode/cli/plugins/cache/skill-concierge/skill-concierge/<version>/`; the optional manual MCP fallback (only if `adapters/zcode/install.sh --mcp-fallback` was run) lives in `~/.zcode/cli/config.json` → `mcp.servers.skill-search`.

**To uninstall:**
1. Remove the plugin: ZCode **Settings → Plugin Management** → uninstall skill-concierge (deletes the versioned cache dir), or `rm -rf ~/.zcode/cli/plugins/cache/skill-concierge/` + delete the `skill-concierge@skill-concierge` entry from `~/.zcode/cli/plugins/installed_plugins.json` and the `"skill-concierge@skill-concierge": true` key from `~/.zcode/cli/config.json` → `plugins.enabledPlugins`.
2. If the manual MCP fallback was merged: delete the `skill-search` entry from `~/.zcode/cli/config.json` → `mcp.servers`.
3. Optionally drop the scope env pin: `SKILL_ZCODE_ROOTS`.

### DeepSeek Harness (DSH), Cline, OpenCode v2

Each installer touches only skill-concierge-owned entries (the installer's header is the authoritative list):

- **DSH** ([`adapters/dsh/install.sh`](adapters/dsh/install.sh)): delete the skill-concierge `- insert:` patches (the `skill-search` MCP row, the unlazy stop-hook and the enforcement plugin) from `cordis.patch.yml` in each DSH profile it wired (`~/.ohdsh/profiles/desktop/`, `~/.ohdsh/profiles/tui/`, or under `DSH_HOME`).
- **Cline** ([`adapters/cline/install.sh`](adapters/cline/install.sh)): remove `~/.cline/plugins/skill-concierge.ts` and the directory `~/.agents/plugins/skill-concierge/`.
- **OpenCode v2** ([`adapters/opencode/install.sh`](adapters/opencode/install.sh)): remove the plugin path from the `plugins` array of `~/.config/opencode/opencode.json`, delete the skills it re-rooted into `~/.config/opencode/skills/` (the names are listed in `.skill-concierge-managed.json` there; leave your own skills), and restart the OpenCode service.
- For all three, optionally drop the scope env pin (`SKILL_DSH_ROOTS`, `SKILL_CLINE_ROOTS`, `SKILL_OPENCODE_ROOTS`).

After removing a harness, run `skill-concierge:doctor --fix` or `python3 scripts/doctor.py --fix` to reindex the shared catalogue (the harness's scope points are pruned at the next reindex).

## Contributing

This is a pre-1.0, evolving project. Before opening a change:

- Read the relevant [ADR](docs/adr/README.md) — accepted ADRs are immutable; supersede with a
  new one rather than editing.
- Bump the plugin manifests together and add a `CHANGELOG.md` entry — the exact list is in
  [`AGENTS.md`](AGENTS.md) → *Conventions*.
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
