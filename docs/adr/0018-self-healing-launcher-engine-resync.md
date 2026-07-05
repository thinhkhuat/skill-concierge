# ADR-0018 — Self-healing launcher: auto-resync the venv engine on plugin-version change

**Status:** Accepted — **amends [ADR-0013](0013-doctor-engine-freshness-check.md)** (which only *detected* the staleness; this *auto-repairs* it). Doctor's freshness check stays as the belt-and-suspenders detector.
**Date:** 2026-07-05
**Deciders:** owner (thinhkhuat)

## Context

The MCP engine runs from a STABLE venv (`~/.local/share/skill-concierge/venv`) that holds a **copied** install of the vendored engine, deliberately outside the wipe-on-reinstall plugin cache so the MCP survives reinstalls ([ADR-0004](0004-bundled-mcp-launcher-stable-venv.md)). [ADR-0013](0013-doctor-engine-freshness-check.md) added a `doctor` check that *detects* when that copy drifts from the deployed source, and [ADR-0016](0016-body-derived-trigger-points.md) flagged the deploy dependency — but the repair was always manual (rerun `setup.sh`).

Real incident (this session): v0.13.0 shipped `search_skills` query fanout. `/plugin marketplace update` + a Claude Code restart refreshed the doctrine and hooks (they load from the deployed source), but the **engine stayed 0.12.x** — the fanout param was silently ignored and `doctor` reported `FAIL`, until a manual engine reinstall. Two compounding causes:

1. **The launcher was exec-only** — `bin/skill-search-mcp` never resynced; it just `exec`ed whatever was in the venv.
2. **The vendored package version is a static `0.1.0`** (`vendor/skill-search/pyproject.toml`) that never bumps, so even a plain `pip install <vendor>` on a re-run sees "already satisfied" and **skips re-copying the changed code**.

## Decision

1. **Self-healing launcher (`bin/skill-search-mcp`).** Stamp the deployed plugin version into `$VENV/.engine-plugin-version` at install time. On every spawn, read the deployed `.claude-plugin/plugin.json` version and compare to the stamp; on a mismatch, `pip install --force-reinstall --no-deps` the deployed `vendor/skill-search` into the venv, restamp, then `exec`. 
2. **`setup.sh` forces the engine copy fresh** with `--force-reinstall --no-deps` (defeating the static-0.1.0 pip-skip) and writes the same stamp.

### Cost & safety
- **Fast path preserved.** The guard is O(1) — two tiny reads (a `plugin.json` version parse + a stamp `cat`). The common in-version spawn does no build. This is what lets the check live in the launcher at all: ADR-0013 rejected a launcher-side *full tree hash* on every spawn (hot-path tax); a version-string compare is not that.
- **Resync is once-per-update**, and **best-effort + FAIL-OPEN**: a failed or slow resync falls through and execs the existing engine — it never blocks the MCP connect (ADR-0004's invariant). A stale engine still beats a dead MCP, and `doctor` still surfaces it.
- **stdout-clean.** This is a stdio MCP; every launcher message goes to stderr, `pip` output to `/dev/null`. Nothing reaches stdout before `exec`.

## Why this amends ADR-0013's "not in the launcher"
ADR-0013 put the freshness check in `doctor`, not the launcher, to avoid taxing the spawn hot path with a tree-hash diff. This ADR does not add a tree hash — it adds a cheap version-string guard that only pays the resync cost on an actual version change. The concern ADR-0013 raised is addressed, not ignored; its `doctor` detector remains as the out-of-band verifier.

## Consequences
- A `/plugin update` (which, per convention, always bumps the version) now auto-resyncs the engine on the next start — no manual `setup.sh`, no silent stale-engine.
- A version bump that does **not** touch the engine triggers one harmless re-copy of the same code (accepted; "version IS the update signal" — ADR-0004 / caveats §7).
- **Residual (flagged):** `--no-deps` keeps the resync fast and offline-safe, so a release that changes **dependencies** (not just engine code) still needs a `setup.sh` rerun. `doctor`'s freshness check hashes engine code only, not deps, so this case is out of scope here and remains manual.

## Verification
- Launcher test (this session): stale stamp `0.0.0` → launcher logged `resyncing engine… → engine resynced to v0.13.0` and restamped; a second run with a matching stamp did **zero** resyncs (fast path).
- `doctor.py` after the resync: `Engine freshness — venv engine matches deployed source`, `status: OK`.
- Shipped as **0.13.1** (PATCH — deploy-flow fix).

## Related
- [ADR-0004](0004-bundled-mcp-launcher-stable-venv.md) — the stable-venv launcher this extends (and whose fail-open invariant it preserves).
- [ADR-0013](0013-doctor-engine-freshness-check.md) — the freshness *detector* this ADR *amends* with an auto-repair.
- [ADR-0016](0016-body-derived-trigger-points.md) — first recorded the "reinstall the venv engine after an update" deploy dependency this eliminates.
