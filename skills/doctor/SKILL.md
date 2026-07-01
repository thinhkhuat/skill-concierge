---
name: doctor
description: Diagnose and repair a broken or degraded skill-concierge install. Use this skill when the skill-search MCP won't connect, search_skills returns nothing or stale results, skills have gone dark, the MCP seems to run old code after a plugin update, or anything about skill-concierge misbehaves after setup or a plugin update. Runs scripts/doctor.py to check the deployment layer (engine venv, engine freshness, Qdrant, MCP wiring, settings overrides, ledger) and delegates retrieval health to the engine; with --fix it applies safe repairs (start Qdrant, reindex, re-apply overrides).
license: MIT
metadata:
  version: 0.2.0
---

# skill-concierge doctor

A deployment-layer health check with safe auto-fixes. It diagnoses what `setup.sh`
provisions and delegates the retrieval diagnostic (embedder, index, dark/stale skills) to
the engine's own `skill-search --health`, so the two never drift.

## Steps

1. **Diagnose (read-only)** from the plugin root:

   ```bash
   python3 "$CLAUDE_PLUGIN_ROOT/scripts/doctor.py"
   ```

   It prints a check matrix and an overall `status: OK | WARN | FAIL` (exit `1` on FAIL).

2. **Read the matrix.** Each row is `[✓|!|✗] <check>  <detail>`:

   | Check | What it verifies |
   |-------|------------------|
   | Python 3.10-3.12 | a usable interpreter (only when the venv is missing) |
   | Engine venv | the stable venv + `skill-search` bin exist |
   | Engine freshness | the venv's COPIED engine matches the deployed vendored source — catches a **stale MCP serving old code after `/plugin update`** (the venv is built once by setup.sh and never refreshed by an update); WARN → rerun setup.sh |
   | MCP wiring | `.mcp.json` is valid + `bin/skill-search-mcp` is executable |
   | Qdrant | the vector store answers at its URL (or the container is stopped) |
   | Retrieval health | engine `--health`: embedder reachable, no dark/stale skills, index fresh |
   | Enrichment overlay | legacy MEAN overlay state (now superseded by the multi-vector layer) |
   | Multi-vector layer | trigger points present (MAX-pool retrieval, ADR-0012); WARNs if `SKILL_MULTIVECTOR` is on but none exist |
   | Corpus health | per-skill calibration `ok`/`weak`/`no-signal` counts from `eval/thresholds.json` |
   | Settings overrides | `skillOverrides` applied to `~/.claude/settings.json` |
   | Ledger dir | the telemetry log directory is writable |
   | Duplicate MCP | warns if a leftover user-scope `skill-search` MCP also exists |

3. **Auto-fix the safe failures:**

   ```bash
   python3 "$CLAUDE_PLUGIN_ROOT/scripts/doctor.py" --fix
   ```

   `--fix` applies only fast, safe repairs, then re-checks: start a stopped Qdrant
   container, `--reindex` a stale/dark index, and re-apply the settings overrides.

   > **Heads-up:** the overrides fix writes `~/.claude/settings.json` (backed up first) via
   > `scripts/apply-overrides.py`. The user invoking doctor is consent for that; mention it
   > before running `--fix` so the change isn't a surprise.

4. **Handle what `--fix` can't.** doctor never auto-builds the venv or the container
   (slow, heavyweight). If `Engine venv` is FAIL **or `Engine freshness` is WARN**, run the
   **`skill-concierge:setup`** skill (or `./setup.sh`) — that rebuilds/refreshes the stable
   venv from the deployed source. For a duplicate MCP, run the printed `claude mcp remove`
   command. After any fix, **restart Claude Code** if the MCP wiring or engine changed.

## Symptom → check shortcuts

- **`/mcp` shows skill-search not connected** → `Engine venv` / `MCP wiring`. Fix: run setup.
- **search behaves like an OLD version after a plugin update** → `Engine freshness`. The MCP venv
  is stale (copied engine, not refreshed by `/plugin update`). Fix: rerun setup.sh, then restart.
- **search returns nothing or stale** → `Qdrant` / `Retrieval health`. Fix: `--fix` (reindex)
  — note the SessionStart `auto_reindex` hook now self-heals index staleness in the background.
- **skills you expect aren't offered** → `Settings overrides`. Fix: `--fix` (re-apply).

Full landmine reference: `docs/caveats.md`.
