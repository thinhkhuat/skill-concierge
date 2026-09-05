# ADR-0053: Cross-harness plugin-offer gates — OMP enablement subtraction, DSH/Cline plugin-row drop

- Status: Accepted
- Date: 2026-09-06
- Drivers: owner order — plugin skills offered "only installed plugins and enabled, never installed but disabled throughout and strictly this way" — after the 2026-09-06 v0.45.0 cross-harness verification ([plans/reports/2026-09-06-v0.45.0-cross-harness-plugin-offer-verification.md](../plans/reports/2026-09-06-v0.45.0-cross-harness-plugin-offer-verification.md)); three live/code-proven violations
- Supersedes: nothing; amends ADR-0052's offer-time clause ("other harnesses untouched") and the ADR-0034 None-filters-nothing inertness for DSH/Cline plugin rows

## Context

The 2026-09-06 verification proved v0.45.0 enforces installed+enabled-only for **Claude**
(index-time union exclusion + `ENFORCER_PLUGIN_GATE` session subtraction) and **ZCode**
(index-time enablement filter + own-registry twin), but not throughout:

1. **OMP.** `plugin` and `omp-plugin` rows are non-foreign under omp, so they were offered on
   index membership alone — `_plugin_gate_ok` returned True for every non-claude harness and
   the OMP registry's per-entry `enabled` check fired only inside the foreign-twin test.
   Live-proven: repo-local-disabled `ponytail:*` offered at 0.886 top-of-menu in a real omp
   session (identical prompt, same cwd, correctly subtracted under claude); an OMP-registry
   `enabled:false` fixture (via `SKILL_OMP_INSTALLED_PLUGINS`) still offered
   `skill-concierge:doctor`. OMP's own provider honors both `entry.enabled === false` and
   claude `enabledPlugins` overrides — the offer claimed invocability the harness would refuse.
2. **DSH / Cline.** No skill-plugin registry exists (ADR-0050/0051), so
   `INVOCABLE_PLUGIN_IDS` is None and the ADR-0034 foreign filter is inert: indexed plugin
   rows of ANY provenance entered the main offer — not merely disabled ones; those rows are
   not invocable in those harnesses at all.

Root cause: ADR-0052 scoped the per-session gate to Claude deliberately; the owner's strict
rule demands the subtraction everywhere a plugin row can be offered.

## Decision

- **OMP joins the Claude gate.** `_plugin_gate_ok` under omp demands namespaced-row
  membership in `INVOCABLE_PLUGIN_IDS` — the set `_invocable_plugin_ids` already computes
  under omp: claude registry (merged user/project/local `enabledPlugins` layers) UNION OMP
  registry, minus claude-layer disables, minus all-entries-`enabled:false`. That set mirrors
  what OMP's provider actually loads, so offer and runtime agree. `None` (unreadable
  registries = UNKNOWN) still filters nothing — the ADR-0034 fail-open contract.
- **DSH and Cline drop namespaced plugin rows outright** — from the main offer AND from
  chain-hint/ROUTE successors. No registry can prove a plugin row invocable there; a
  `prefix:name` row is structurally never invocable. Non-namespaced rows pass; the foreign
  annex remains their labeled NOT-invocable surface (ADR-0034's designed lane).
- **Codex, Command Code, ZCode keep their lane semantics.** Codex/Command Code:
  claude-plugin rows are foreign with a structurally-false twin (dropped, annex-labeled).
  Codex's own `codex-plugin` scope stays ungated — enablement lives in config.toml, not
  stdlib-parseable on the enforcer's dependency-free floor (ADR-0033 rationale); recorded as
  a standing caveat, deliberately NOT widened here. ZCode: claude-plugin rows only enter via
  its own enablement-filtered registry twin; a second gate would be redundant.
- **Kill-switch unchanged:** `ENFORCER_PLUGIN_GATE=0` reverts every harness byte-identically.

### Rejected alternatives

- **Parse Codex config.toml enablement** — requires a TOML dependency on the stdlib-only
  enforcer; violates the repo's dependency invariant; deferred until a stdlib `tomllib`
  floor (3.11+) is acceptable.
- **Index-time exclusion for the OMP cache** — breaks the ADR-0034 division of labor
  (machine-wide index, per-session subtraction) and the ADR-0028 cross-session invariant
  (no session's enablement may prune the shared collection).
- **Full foreign-scope drop for DSH/Cline** — would also evict `personal`-scope rows
  (foreign there), gutting their main menus; the filesystem-twin annex already covers
  genuinely-invocable twins. The owner's rule concerns PLUGIN rows; scope held to plugin rows.

## Consequences

- OMP offers now match OMP's loader: installed+enabled only, per-session. A plugin disabled
  at a claude layer disappears from omp offers in that cwd even when the OMP registry says
  enabled (mirrors the provider's override precedence, helpers.ts:1088-1118, 1191-1192).
- DSH/Cline main offers lose plugin-scope rows they could never invoke; annex visibility
  unchanged.
- **Epoch boundary:** offer-composition metrics change epoch at v0.46.0 — never pool across
  it (AGENTS.md Guardrails). Watch items: `docs/epoch-watch.md` §v0.46.0.
- One flag from old behavior everywhere: `ENFORCER_PLUGIN_GATE=0`.

## Verification

- Enforcer selftest §plugin-enablement gate extended: claude AND omp (invocable survives /
  session-disabled drops / non-namespaced passes / UNKNOWN filters nothing / flag-off
  filters nothing); dsh+cline (namespaced drops, plain passes); codex/commandcode/zcode
  keep lane-pass semantics.
- Deterministic sims re-run green under omp: repo-local-disabled ponytail prompt no longer
  offers ponytail; the `SKILL_OMP_INSTALLED_PLUGINS` `enabled:false` fixture no longer
  offers `skill-concierge:doctor`; claude sims unchanged; repo-re-enabled `agent-skills:*`
  still offered under both harnesses.
- Full engine suite + root tests + driftcheck + doctor green at 0.46.0.
