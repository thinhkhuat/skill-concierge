# ADR-0005: Keep-on overrides → `~/.claude/settings.json`, atomic applier (not upstream generator)

**Status:** Accepted
**Date:** 2026-06-26
**Deciders:** owner (thinhkhuat)

## Context

skill-search's token saving comes from setting most skills to **`name-only`** (name stays
visible + invocable, description leaves context) while keeping a **curated set always-on**
(full description retained) — the routing `ck:*`, `vn-*`, guardrail, and router skills the
owner always wants live. Two ways to write those overrides existed:

1. **Upstream `generate_overrides.py`** — targets `settings.local.json` with a **2-item
   keep-on default**. Running it would **revert the curated always-on set** to two skills
   and write to the wrong file. A live landmine.
2. **A purpose-built applier** writing the curated policy to the **real** settings file.

The override values also share one budget with the index (`skills_discovery.py` is the
single source for both — index a skill you never free, or free one you never index, and you
get silent budget leaks).

## Decision

Ship `scripts/apply-overrides.py`. It writes `name-only` overrides + the curated keep-on set
to **`~/.claude/settings.json`** (NOT `settings.local.json`, NOT via the upstream generator).
Hard requirements baked in:

- **Atomic write** — temp file + `os.replace` (never a partial settings.json).
- **Backs up first** — timestamped + pid-stamped (no collision on rapid reruns).
- **Preserves other keys** — merges, never clobbers unrelated settings.
- **Refuses empty/invalid keep-on** — won't nuke the always-on set on a bad config.
- **Warns** if skill-search is absent / a keep-on entry is missing from the catalogue.
- **UTF-8**, `ensure_ascii=False`.
- Requires **Python 3.10+** (imports vendored `skills_discovery`, which uses `dict | None`).

The policy snapshot is `config/keep-on.json` (32 skills, incl. the namespaced router
`skill-concierge:skill-search`).

## Consequences

### Positive
- The curated always-on set is applied safely and idempotently; a crash mid-write can't
  corrupt settings; a bad keep-on can't silently empty it.

### Negative / caveats (LOUD)
- **Never run upstream `generate_overrides.py` against this deployment** — it targets
  `settings.local.json` with a 2-item default and would wipe the curated set. Guard before
  any override regeneration. (`../caveats.md` §2.)
- **Run the applier with Python 3.10+** (the stable venv's python). System `python3.9`
  throws `TypeError` on `dict | None` in the vendored discovery module.
- Keep-on lives in `~/.claude/settings.json`. The cached plugin copy of `keep-on.json` must
  track the source version, or a cache `setup.sh` re-run reverts the router to `name-only`
  (`../caveats.md` §7).

## Related

- ADR-0001 (the index + overrides share one discovery source).
- ADR-0004 (`setup.sh` calls this as its last step).
- `../caveats.md` §2 (override-generator landmine), §7 (cache version sync).
