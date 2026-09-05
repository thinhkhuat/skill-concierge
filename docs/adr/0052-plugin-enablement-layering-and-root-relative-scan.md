# ADR-0052: Layered plugin enablement + root-relative plugin scan

- Status: Accepted
- Date: 2026-09-05
- Drivers: live validation of plugin-skill first-class status (2026-09-05 session); owner order to fix everything causing or contributing to plugin-skill failure
- Supersedes: nothing; extends ADR-0033 (dual-harness discovery), ADR-0042 (ZCode), ADR-0034 (cross-harness offer isolation)

## Context

Three validated defects, all in the plugin-skill path:

1. **Single-scope enablement read.** `skills_discovery._installed_plugin_roots` read
   `enabledPlugins` from `~/.claude/settings.json` ONLY, while Claude Code layers
   enablement user → project → project-local (last writer wins PER SESSION). Live
   casualties: `agent-skills@addy-agent-skills` (user-false, re-enabled by this repo's
   `.claude/settings.local.json`) had 25 harness-invocable skills indexed NOWHERE;
   `ponytail` (user-absent, project-disabled) stayed indexed and offerable.
2. **Whole-cache glob + path arithmetic.** The Claude plugin scan globbed the entire
   cache then filtered by installPath prefix; nested hits under
   `<plugin>/examples/*/skills/` leaked in and the `sub[si-2]` heuristic minted
   `examples:workflow` as a top-level (un-invokable) skill; `temp_git_*` marketplace
   clones were glob candidates.
3. **No per-session enablement gate at offer time.** The enforcer's post-filter gated
   only FOREIGN_SCOPES rows; in Claude sessions `plugin`-scope rows flowed through
   ungated, so project-disabled plugins were offered (the ponytail half of #1).

The enforcer already computed the merged per-session view (`INVOCABLE_PLUGIN_IDS`:
user + cwd project + cwd local layers); only discovery lagged.

## Decision

- **Index time = machine-wide UNION.** A plugin is indexed iff installed AND NOT
  (user-explicit-false AND no layer anywhere explicitly re-enables it). Project-layer
  `false` alone never excludes. Project enumeration reads Claude Code's own registry
  `~/.claude.json` `projects` keys — deterministic and machine-wide, so no session can
  prune another's view (the ADR-0028 invariant). A readable-but-empty result is a
  POSITIVE empty (no fallback resurrection). Rationale: the Qdrant collection is
  machine-global; per-session precision must live at the session layer, exactly the
  ADR-0034 division of labor. Rejected: cwd-layer merge at discovery (reintroduces the
  cross-session prune fight); per-project indexes (redesign, no upside).
- **Root-relative scan, registry-derived ids.** Claude plugin skills are enumerated
  per `installPath` from the registry (`<root>/skills/*/SKILL.md` + one nested depth,
  phantom-guarded), named `<registry-key-id>:<dirname>`. Structurally unreachable:
  retained old versions, plugin payload trees (`examples/`, `docs/`), `temp_git_*`
  clones. The whole-cache glob + `_namespaced_name` heuristic survives only as the
  manifest-unreadable fallback (fail-open preserved) and under `SKILL_PLUGIN_FILTER=0`.
- **Offer time = per-session subtraction.** `ENFORCER_PLUGIN_GATE` (default ON): in
  Claude sessions, `plugin`-scope rows and chain-hint/ROUTE successors require
  membership in `INVOCABLE_PLUGIN_IDS` (already the merged view). `None` (unreadable
  manifest = UNKNOWN) filters nothing; non-namespaced rows pass; other harnesses
  untouched.
- **Kill-switches:** `SKILL_PLUGIN_LAYERED_ENABLEMENT=0` (user-file-only enablement),
  `SKILL_CLAUDE_PROJECTS_FILE` (projects-registry path, hermetic tests),
  `ENFORCER_PLUGIN_GATE=0` (ungated plugin offers).

## Consequences

- Project-enabled plugins become retrievable machine-wide but are OFFERED only where
  enabled — search stays a machine-wide surface by design (ADR-0034 precedent).
- Epoch boundary: the offer-composition ledger epoch changes at v0.45.0; no offer
  metrics may be pooled across it (AGENTS.md Guardrails).
- `~/.claude.json` is read once per reindex (keys-only use; reindex is not hot path).
- The 12 pre-existing engine-suite failures (ZCode/DSH/Cline seams unpinned in the
  hermetic conftest — fixture drift from ADR-0042/0050/0051) are closed in the same
  change; the suite is green before and after.

## Verification

- Unit: layered-enablement union cases, root-relative scan (examples/ excluded,
  registry-derived naming, temp clones unreachable), positive-empty semantics,
  fallback intact (`vendor/skill-search/tests/test_discovery.py`).
- Enforcer selftest §plugin-enablement gate: invocable survives / disabled drops /
  unknown passes / flag-off passes; chain-hint fixtures admit their fixture id.
- Dev-engine live probe: real-machine discovery shows `agent-skills:*`, zero
  `examples:*`, zero `temp_git_*`, `ponytail:*` still indexed (union semantics).
- Full engine suite + root tests + driftcheck green (GATES G1/G2/G7).
