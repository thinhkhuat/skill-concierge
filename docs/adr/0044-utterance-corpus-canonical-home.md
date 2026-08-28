# ADR-0044: Utterance corpus canonicalized at the operator home

- **Status**: Accepted
- **Date**: 2026-08-28
- **Relates to**: ADR-0025/0030 (operator-owned durable home), ADR-0026 (utterance layer),
  ADR-0043 (catalog flywheel generation — the run that exposed the drift)

## Context

The generated utterance corpus existed in TWO places with silent drift: the dev-surface
`eval/triggers.json` (the ADR-0026-era default, when repo == deployment) and the
operator-owned durable home `~/.claude/skill-concierge/triggers.json` (the path `.mcp.json`
pins via `SKILL_TRIGGERS`). By 2026-08-28 the dev copy was ~160 keys ahead (Claude sessions'
`settings.json` env override kept steering generator writes there). Two facts made this
untenable: (a) the corpus is the ONLY full-text record of the utterances — Qdrant stores
embeddings plus phrase hashes, not recoverable text — and (b) the repo is **public**, so
committing the corpus was ruled out by the owner. The dual-copy seam was also a live trap:
a reindex launched with `.mcp.json`'s env (durable-home path) would rebuild from the stale
copy and prune the antigravity utterance layer (the ADR-0026 gap class).

## Decision

1. **One canonical copy: `~/.claude/skill-concierge/triggers.json`** — the operator home,
   outside the public repo. The dev-surface copy is retired (deleted; its `.gitignore`
   entry removed).
2. **Migration:** both pre-migration copies backed up to
   `~/.claude/skill-concierge/backups/triggers-20260828-2030/`; the dev copy (a strict
   superset — 3,406 keys incl. all 1,928 `antigravity:*` entries — became the new durable-home
   content via copy-over.
3. **Every path resolves env-first, then the durable home** (doctor's 0.25.1
   durable-home-first idiom, applied to `build_triggers.py`, `enrich_index.py`,
   `llm_triggers.py`, `flywheel.py`). The `settings.json` `SKILL_TRIGGERS` override is
   removed so no context steers writes away from the canonical file; `.mcp.json` already
   pins the durable home.
4. **Vendored engine joins the seam** (re-apply on re-vendor): `_LLM_TRIG_PATH` default in
   `vendor/skill-search/skill_search/server.py` becomes the durable home — the old
   vendored-tree default was never populated in deployed copies, making a bare env-less
   `skill-search --reindex` silently rebuild without utterances (pruning the layer).
   Deployed to the stable venv via force-reinstall.

## Consequences

- The corpus is machine-local personal data: it is NOT version-controlled. Losing the file
  loses the utterances (Qdrant cannot regenerate them). Backups live in the operator home's
  `backups/` directory; a scheduled-backup mechanism is a possible follow-up, not built here.
- Fresh clones start with no corpus and regenerate via the flywheel (graceful desc/body
  fallback unchanged).
- `enrich_index.py --reapply` and any tooling reading the legacy ROOT path keep working via
  the env override if ever needed; the defaults no longer reference it.

## Evidence

- Pre-migration diff: dev copy 1,478→3,406 keys (session's antigravity run), durable-home
  copy 1,318 keys stale; `only-in-live: 0` — dev was a strict superset (copy-over loses
  nothing). Both copies preserved under `backups/`.
- Post-migration, with NO env: status reads installed 728/728 + antigravity 1928/1928 from
  the durable home; selftests (llm_triggers, llm_eval_gen, flywheel_llm, doctor) PASS;
  driftcheck exit 0; deployed venv engine greps with the durable-home default.
