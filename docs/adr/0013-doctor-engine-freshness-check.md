# ADR-0013 — doctor `Engine freshness` check (venv engine vs deployed source)

Status: Accepted (2026-07-01)
Relates to: ADR-0004 (bundled MCP launcher + stable venv), ADR-0007 (maintenance skills — doctor).

## Context
The MCP launcher (`bin/skill-search-mcp`) EXECs `skill-search` from a STABLE venv at
`~/.local/share/skill-concierge/venv`, deliberately OUTSIDE the wipe-on-reinstall plugin
cache so the MCP survives reinstalls (ADR-0004). `setup.sh` builds that venv by **copying**
the vendored engine into its `site-packages` — a regular install, **not** editable (`-e`).

The failure this ADR closes: `/plugin update` ships new engine code into the version-pinned
**cache**, but **never updates the venv's copied engine**. The MCP then keeps serving the OLD
engine while every existing doctor row is green — `Engine venv ✓` only proves the `skill-search`
bin *exists*, not that its code is *current*. Operators hit this in practice (a deployed engine
change was silently not live until a `setup.sh` rerun), and nothing surfaced it.

## Decision
Add a read-only **`Engine freshness`** check to `scripts/doctor.py`, run right after
`Engine venv`:
- Content-hash the venv's installed engine (`…/venv/lib/python*/site-packages/skill_search`)
  and the deployed vendored source (`$CLAUDE_PLUGIN_ROOT/vendor/skill-search/skill_search`)
  via `_tree_digest` — sorted `(relpath, bytes)` over every file except `__pycache__`/`*.pyc`.
- **Mismatch → WARN**, `fix="setup"`: "venv engine code DIFFERS from the deployed plugin
  source — the MCP is serving STALE engine code after a plugin update; rerun ./setup.sh, then
  restart." `setup` is NOT an auto-fixer (doctor never auto-builds the venv — ADR-0007), so it
  prints as a manual instruction.
- **Match → OK.** **Fail-open (N/A)** when either tree is absent (venv-missing is `check_venv`'s
  job; a missing vendored source means doctor is running outside a packaged checkout).

The check lives in **doctor** (cache-run, so it ships with `/plugin update`), NOT in the
launcher: the launcher is intentionally "EXEC-only, never builds" to avoid a slow first spawn
that times out the MCP connect (ADR-0004) — adding a hash diff to every spawn would tax the hot
path and risk that timeout. doctor is the right layer.

## Consequences
- The stale-engine blind spot is now detectable on demand (`doctor`) instead of silent.
- Pairs with the operator rule (caveats §11): an update that changed `vendor/skill-search/`
  needs a `setup.sh` rerun; a hooks/doctrine/scripts-only update does not.
- `--selftest` pins `_tree_digest` determinism (identical trees equal, 1-byte change diverges,
  absent → None) and that the check is wired into `CHECKS`.
- Not auto-fixed by design: rebuilding the venv is heavyweight and owned by `setup.sh` (ADR-0007).
