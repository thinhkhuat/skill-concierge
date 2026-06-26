# ADR-0001: Index model-invocable `SKILL.md` only — exclude built-in/user-only commands

**Status:** Accepted
**Date:** 2026-06-26
**Deciders:** owner (thinhkhuat)

## Context

skill-search exists to cut the native skill-listing token tax: it indexes the skill
catalogue semantically and frees most skills to `name-only` so their descriptions leave
the per-turn context. The model then *retrieves* the few skills that fit a task instead of
being handed all of them every turn.

That purpose fixes **what belongs in the index**: only things the *model* can invoke and
that *cost model context*. Claude Code surfaces several kinds of "command-like" things:

- **`SKILL.md` skills** — personal (`~/.claude/skills/`), project (`<cwd>/.claude/skills/`),
  and plugin-bundled. Model-invocable; their descriptions are injected into context → they
  carry the token tax skill-search is built to relieve.
- **Built-in / user-only slash-commands** — `loop`, `schedule`, `verify`, `run`,
  `code-review`, `update-config`, `keybindings-help`, etc. These are harness commands, not
  `SKILL.md` files. They are **user-invocable only**, carry **no model-context token tax**,
  and the model cannot fire them autonomously.

Indexing the second group would be pure pollution: nothing to retrieve *for the model*,
nothing to save, and false candidates in every search.

## Decision

The engine indexes **only `SKILL.md` files**. `skills_discovery.py` is the single source of
truth and globs exactly three roots:

```python
~/.claude/skills/*/SKILL.md          # personal
<cwd>/.claude/skills/*/SKILL.md      # project
~/.claude/plugins/cache/**/skills/*/SKILL.md   # installed plugin skills (cache, NOT marketplaces/)
```

Built-in/user-only commands are **never candidates** — they are not `SKILL.md` files, so
they fall outside the glob by construction. The design comment is explicit (lines 28–31):
the cache (installed copies) is scanned, **not** `~/.claude/plugins/marketplaces/**`, to
avoid *"polluting the index with un-invokable results."* Excluding un-invokable things is
the engine's intent, not an oversight.

Plugin skills are indexed under their **namespaced** id (`<plugin>:<skill>`, e.g.
`ck:worktree`), matching how Claude Code references and overrides them.

## Consequences

### Positive
- The index contains exactly the model-invocable, token-taxed catalogue — every result is
  actionable by the model, every freed skill saves real context.
- No false candidates from commands the model can't fire.

### Negative / caveats (LOUD — this bit us)
- **The vendored eval (`vendor/skill-search/eval/labeled_queries.jsonl`) is calibrated to the
  upstream author's environment.** Its ground-truth labels target skills that are *not in
  this index* — both the author's plugins (`gsd-*`, `superpowers:*`, `claude-mem:*`,
  `chrome-devtools-mcp:*`) **and built-in commands**. Running it here yields a near-zero
  recall@k that says **nothing** about retrieval quality — it's measuring a universe this
  engine deliberately excludes. **Do not trust that number.** See `../caveats.md` §1.
- Querying for a built-in command's job ("customize keyboard shortcuts", "run on a recurring
  interval") will surface the nearest *indexed skill*, never the built-in — by design. If a
  nudge/enforcer should ever point at built-ins, that is a **separate coverage decision**,
  not a retrieval bug.
- Look skills up by their **namespaced** id (`get_skill('ck:worktree')`, not `'worktree'`).

## Related

- ADR-0002 (fusion) — the enforcer sources candidates from *this* index.
- `../caveats.md` §1 (wrong-universe eval), §5 (namespacing).
- Source: `vendor/skill-search/skill_search/skills_discovery.py:24-32, 35-52`.
