# skill-concierge

A **skill-governance layer** over Claude Code's default skill mechanism. Where the
default dumps every skill description into context every turn and hopes the model picks
one, skill-concierge replaces *hope* with **retrieve-precisely + enforce-use + measure**.

## Three organs

| Organ | Question it answers | Mechanism |
|-------|---------------------|-----------|
| **Retrieve** | *Which* skill fits this task? | semantic search over the full skill catalogue (Qdrant + multilingual embeddings) |
| **Enforce** | *Whether* the model uses a skill at all (vs winging it) | a per-turn hook that hands over the right candidates under a use-mandate |
| **Ledger** | *What actually got used* | a compounding, append-only skill-invocation log → data-backed always-on curation |

> Metaphor: skill-search is the library; skill-concierge is the concierge who knows which
> book fits, makes sure you actually open one, and remembers what you reached for.

## Status

`0.1.0` — scaffold, in active development. See [`docs/plan.md`](docs/plan.md) for the
build plan: **telemetry first** (bank a baseline) → **fusion** (enforcer sources its
candidates from the semantic index; retire the legacy lexical scorer) → **classifier
deferred**.

## Layout

```
skill-concierge/
├── .claude-plugin/{plugin,marketplace}.json   # manifests
├── vendor/skill-search/                        # vendored MCP engine (MIT · sowhan/skill-search) + LICENSE + VENDORED.md
├── skills/skill-search/SKILL.md                # router skill (always-on entry point)
├── hooks/        # ledger capture (PostToolUse) + enforcer (UserPromptSubmit, rewrite pending)
├── scripts/analyze.py                          # ledger analyzer
├── docs/                                       # plan.md + skill-search deployment readme + setup report
├── .mcp.json                                   # (next slice) registers the vendored skill-search MCP server
└── README.md
```

The engine source is vendored for portability; its Python deps, the Qdrant service, the
embedding model, the index, and the `settings.json` overrides are **reproduced by a setup
step** (next build slice), not embedded.

## Build & install

Developed **local-first** in the workbench (`MY-WORKBENCH/skill-concierge/`) — not
installed into any Claude path. Install to a marketplace only on explicit request.

Builds on [sowhan/skill-search](https://github.com/sowhan/skill-search) (MIT).
