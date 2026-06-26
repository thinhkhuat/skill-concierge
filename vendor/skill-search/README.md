# skill-search

[![PyPI](https://img.shields.io/pypi/v/skill-search-mcp)](https://pypi.org/project/skill-search-mcp/)
[![tests](https://github.com/sowhan/skill-search/actions/workflows/test.yml/badge.svg)](https://github.com/sowhan/skill-search/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Semantic, on-demand skill retrieval for Claude Code.** Claude Code injects a
short blurb for every installed skill into context on *every* turn so it can
decide which to use. As your skill count grows, that listing becomes a large
recurring token tax — and because the match is essentially name/description
keyword overlap, a skill whose name doesn't echo the user's words quietly never
fires.

skill-search replaces that with a vector retriever over the **full** skill
descriptions. Skills are set to `name-only` (name stays visible and invocable,
the description leaves the budget), and an MCP tool returns just the few skills
that semantically match the task at hand.

> **Where it shines:** this pays off once you have a lot of skills installed —
> roughly hundreds. With only a handful, the native listing is already cheap and
> you don't need the extra round-trip.

---

## Proof of value

All numbers below are **measured**, not estimated by vibes — on a real setup of
**117 active skills**. You can reproduce them (see [Reproduce](#reproduce-the-numbers)).

### 1. It reclaims a measurable chunk of every turn

The native skill listing injects name + description for all skills, every turn.
At `name-only`, only the names remain and the retriever supplies descriptions
on demand. Counted with a real BPE tokenizer (`tiktoken` cl100k_base), modeling
each skill as it appears in the listing (`- name: description`):

| | Tokens injected per turn | % of a 200K window |
|---|---:|---:|
| Native full listing (name + description) | 7,267 | 3.63% |
| `name-only` + skill-search | 887 | 0.44% |
| **Saved, every turn** | **6,380** | **3.19%** |

That's ~53 tokens/skill of description you stop paying for on turns that don't
need them. The worst offenders are generic-named skills whose value lives
entirely in the description (`context-mode:context-mode` alone is 235 tokens) —
exactly the skills `name-only` + retrieval handles best. (cl100k_base
approximates Claude's tokenizer; reproduce with
[`scripts/measure_tokens.py`](scripts/measure_tokens.py).)

### 2. It fixes the name-bias miss (real, unedited output)

`search_skills` ranks by meaning, so skills match even when they share no words
with the query:

```
$ query: "debug a failing test"
   0.672  gsd-debug
   0.659  superpowers:systematic-debugging
   0.658  gsd-forensics

$ query: "review my UI for accessibility"
   0.689  chrome-devtools-mcp:a11y-debugging     ← "a11y" never appears in the query
   0.667  frontend-design:frontend-design
   0.653  web-design-guidelines                  ← no shared keywords at all

$ query: "set up a supabase database with auth"
   0.717  supabase:supabase
   0.575  supabase:supabase-postgres-best-practices
   0.542  superpowers:executing-plans
```

Beyond cherry-picked examples: on a 24-query labeled set
([`eval/labeled_queries.jsonl`](eval/labeled_queries.jsonl)) the default
service-free embedder (`bge-small`, 384-dim) scores:

| | recall@1 | recall@3 | recall@6 |
|---|---:|---:|---:|
| bge-small (default) | 0.67 | 0.79 | 0.79 |

That's a conservative floor — a few counted "misses" are arguably valid
alternatives the strict labels don't list (e.g. `gsd-verify-work` for "confirm
my change works"). The genuine misses are short, generic-named skills
(`keybindings-help`, `loop`) where a small embedder struggles; the opt-in Ollama
tier (768-dim) typically lifts recall further. Reproduce — and the misses —
with `python eval/run_eval.py`.

### 3. It stays fast as the index grows

Reindex is incremental: each point stores a content hash, so only changed skills
re-embed and deleted skills are dropped.

| Operation (117 skills) | Time |
|---|---:|
| Full rebuild (`--rebuild`) | ~18.8s¹ |
| Incremental reindex, nothing changed | **~0.07s** |

¹ includes the one-time embedding-model download on first run.

### 4. It fails loudly, not silently

Because the retriever becomes the *only* discovery path, a stale or broken index
would otherwise hide skills with no symptom. Guards:

- `search_skills` appends a `warning` when skills changed on disk since the last index.
- `health` reports embedder/store reachability and lists any **dark** (on-disk
  but unindexed) or **stale** (indexed but deleted) skills, and exits non-zero
  when degraded (cron/CI-safe).

---

## "But isn't the skill listing prompt-cached?"

Fair question, and worth being precise about. Claude Code keeps the skill listing
in its cached prefix, so on a cache hit you're billed only ~10% for those tokens —
the ~7,300-token listing costs closer to ~700 token-equivalents on a cached turn.
That genuinely softens the **dollar** cost, and the savings table above is best
read as the *uncached* (worst-case) figure.

But caching is a **billing** optimization, not a **context-window** one. Cached or
not, those tokens still occupy your 200K window on **every** turn — crowding out the
codebase, the diff, the long conversation. The window-occupancy win above is
**unaffected by caching**, and for long or context-heavy sessions that headroom is
the whole point.

Two details that keep skill-search itself cache-friendly:

- **`name-only` is a one-time, stable change** to the prefix — cached exactly like the
  full listing was. The MCP tool definitions are a small, stable addition to the
  cached `tools` block. Nothing here forces repeated cache writes.
- **The only dynamic piece is the `search_skills` result** — a few hundred tokens
  appended like any tool result, which then caches into the prefix for later turns.
  It doesn't invalidate the cache.

Net: on cache-hit turns the **price** saving is ~10% of the token delta; on cache
misses (first turn, after the ~5-min cache TTL lapses, or whenever the prefix
changes) you save the full amount. Either way, the **context space** comes back
every turn.

---

## How it works (two pieces, useless apart)

1. **`generate_overrides.py`** → sets ~all skills to `name-only` in
   `.claude/settings.local.json` → frees the budget. A tiny allowlist
   (the router skill) stays fully `"on"`.
2. **`server.py`** (MCP) → embeds full descriptions into a vector store; returns
   the top-k relevant skills → Claude invokes them by name (works at `name-only`).

Skip step 1 and you pay the native tax **and** the retriever. Do both.

| File | Role |
|---|---|
| `skill_search/server.py` | MCP server: `search_skills`, `get_skill`, `reindex`, `health` |
| `skill_search/skills_discovery.py` | Shared skill discovery — one source of truth for both halves |
| `skill_search/generate_overrides.py` | Frees the budget by setting skills to `name-only` |

---

## Install

The **default tier is service-free** — embedded on-disk Qdrant + local ONNX
embeddings ([fastembed](https://github.com/qdrant/fastembed)). No Docker, no
Ollama, no manual model pull (the model downloads once, then runs offline).

```bash
pipx install skill-search-mcp   # one command — installs the skill-search CLI

# 1. build the index once (incremental afterwards; --force for a full rebuild)
skill-search --reindex

# 2. register the MCP with Claude Code (no-arg console script = stdio server)
claude mcp add --transport stdio skill-search -- skill-search

# 3. install the router skill (the always-on trigger — see "The router skill")
mkdir -p ~/.claude/skills/skill-search
curl -sL https://raw.githubusercontent.com/sowhan/skill-search/main/skills/skill-search/SKILL.md \
  -o ~/.claude/skills/skill-search/SKILL.md

# 4. free the budget: set all OTHER skills to name-only
skill-search-overrides  # project scope; --global targets ~/.claude

# 5. (optional) confirm inside a Claude Code session
#    /mcp     and     /doctor
```

**Opt into the faster tier** (only if you already run them):

```bash
docker run -p 6333:6333 qdrant/qdrant
export SKILL_QDRANT_URL=http://localhost:6333          # Qdrant server
ollama pull embeddinggemma
export SKILL_EMBED_BACKEND=ollama                      # Ollama embeddings
```

Pin these as `--env` flags on `claude mcp add` to keep them for the registered server.

**From source** (dev / contributing): `git clone https://github.com/sowhan/skill-search && cd skill-search && pipx install .` — then `cp -r skills/skill-search ~/.claude/skills/` for the router skill.

---

## The router skill (keep this one `"on"`)

The always-visible entry point that tells Claude to retrieve before guessing
ships in this repo as an installable skill at [`skills/skill-search/`](skills/skill-search/SKILL.md).
Install it (done automatically by step 4 of [Install](#install)):

```bash
cp -r skills/skill-search ~/.claude/skills/
```

It's deliberately tiny — frontmatter plus a few lines of instruction — so it
costs almost nothing to keep `"on"` while every other skill goes `name-only`.
Its whole job: on a new task, call `search_skills`, then invoke the 2-4 genuinely
relevant results by name. Keep this skill (and `skill-search` itself) in the
`generate_overrides` keep-on allowlist.

---

## Configuration

All config is env-var overridable (`SKILL_*` prefix). Selection: set
`SKILL_QDRANT_URL` for a Qdrant server (else embedded); `SKILL_EMBED_BACKEND`
defaults to `fastembed`.

| Concern | Default (service-free) | Opt-in (faster) |
|---|---|---|
| Vector store | embedded on-disk Qdrant at `~/.cache/skill-search/qdrant` (`SKILL_QDRANT_PATH`) | `SKILL_QDRANT_URL` → Qdrant server |
| Embedder | fastembed `BAAI/bge-small-en-v1.5` (384-dim) | `SKILL_EMBED_BACKEND=ollama`, `SKILL_EMBED_MODEL` (`embeddinggemma`, 768-dim) |
| Results | `SKILL_TOP_K=6` | — |

Switching embedders changes the vector dimension; an existing collection can't
take it. This is guarded both ways — `reindex` raises a clear "run `--rebuild`"
error, and `health` flags the mismatch.

---

## Tests

```bash
pip install -e ".[dev]"
pytest -m "not integration"     # fast, offline (no network/model) — 13 tests
pytest -m integration           # end-to-end: real embed → search → incremental skip
```

Unit tests pin the highest-risk logic: skill discovery (parsing, plugin
namespacing, dedup precedence — the shared source of truth both halves depend on),
point-ID validity, content-hash determinism, and the staleness/manifest guards.
The `integration` marker gates the one test that loads the embedder.

> If a broken third-party pytest plugin in your env fails collection, run with
> `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`.

---

## Reproduce the numbers

```bash
# token savings on YOUR skill set (chars/3.7 proxy; descriptions-only, so a floor)
python3 -c "
import skills_discovery as d
s = d.discover_skills()
tok = lambda x: round(len(x)/3.7)
desc = sum(tok(x['description']) for x in s)
print(f'{len(s)} skills | ~{desc} tokens saved/turn | {desc/200000*100:.2f}% of 200K')
"

# semantic ranking + incremental-reindex timing
skill-search --reindex          # full build, then run again to see the incremental skip
skill-search --health           # indexed vs on-disk, dark/stale skills, dims
```

---

## Caveats

- **Retriever is the sole discovery path.** At `name-only`, Claude can't
  auto-match on description. If `search_skills` misses, the skill goes dark.
  Tune `SKILL_TOP_K` up if recall feels low; keep critical skills `"on"`.
- **Re-index on change.** New/edited skills aren't searchable until `reindex`
  runs — but it's incremental and cheap, and drift is surfaced by `search_skills`
  warnings + `health`, so the failure mode is visible, not silent.
- **Embedded Qdrant locks its dir to one process.** Don't run a CLI `--reindex`
  while the MCP server is up in that mode — use the `reindex()` tool, or the
  Qdrant-server tier.
- **Tail-scale.** The payoff scales with how many skills you have installed —
  worth it at hundreds, overkill at a handful.

## License

MIT — see [LICENSE](LICENSE).
