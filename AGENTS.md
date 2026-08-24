# AGENTS.md

Agent-contributor instructions for **skill-concierge** — a skill-governance layer for
Claude Code: semantic retrieval (*which* skill) + use-enforcement (*whether* a skill is
used at all) + a compounding invocation ledger (*what* actually got used).

This file follows the open [AGENTS.md](https://agents.md/) convention and is the **canonical**
agent-instruction surface; platform adapters (e.g. [`CLAUDE.md`](CLAUDE.md)) point here. For
the full product overview see [`README.md`](README.md); for the *why* behind each decision see
[`docs/adr/`](docs/adr/README.md).

## Orientation — read before changing anything

| Source | For |
|--------|-----|
| [`README.md`](README.md) | what the plugin is, install/setup, usage, architecture |
| [`docs/adr/`](docs/adr/README.md) | accepted design decisions + rationale (immutable) |
| [`docs/caveats.md`](docs/caveats.md) | operational landmines — read before judging the engine |
| [`docs/plan.md`](docs/plan.md) | fusion build plan + dated build log |
| [`docs/anti-dodge-integration-v0.14.md`](docs/anti-dodge-integration-v0.14.md) | the v0.14.0 anti-dodge work: 5 mechanisms, decision arc, accepted caveats |

## Repository layout

The full tree is in the README's *Architecture* section. The parts you will touch most:

- `skills/{skill-search,setup,doctor,skill-usage-audit,keep-on,flywheel,catalogs}/SKILL.md` — the plugin skills (router + maintenance + usage-audit + keep-on allowlist manager + flywheel utterance coverage/generation ADR-0027 + external catalog-roots manager ADR-0031)
- `scripts/` — `doctor.py` (health check), `analyze.py` (ledger; `--since`/`--until` window it by event time for before/after compares — don't split the ledger by hand), `apply-overrides.py` (keep-on writer; `--check`/`--if-changed` drift modes), `keep-on.py` (view/add/remove the always-on allowlist), `catalogs.py` (external catalog roots: list/add/remove/promote, ADR-0031), `embed_server.py` (warm embed sidecar)
- `hooks/` — the in-generation governance layer: `enforcer.py` (per-turn SKILL-FIRST gate: embed→retrieve→floors/intent→ranked mandate, plus the AUTHORIZED-SKIP tier on its two silent legs — ADR-0015), `ledger.py` (invocation capture), `doctrine.py` (SessionStart standing-order injection), `auto_reindex.py` + `auto_overrides.py` + `auto_flywheel.py` (SessionStart self-heal: index + settings-override drift + utterance generation for new skills, ADR-0027 — fail-open, throttled, detached), `doctrine/skill-first.md` (the library doctrine text — burden of proof on SKIP, escalate to `find-skills`)
- `vendor/skill-search/` — vendored MCP engine (MIT · sowhan/skill-search) — **do not diverge silently**; the body-derived trigger points (`_extract_body_triggers`/`_trigger_phrases`, ADR-0016) are a direct engine-code patch, logged in [`VENDORED.md`](vendor/skill-search/VENDORED.md) — re-apply it if the engine is ever re-vendored from upstream
- `.claude-plugin/{plugin,marketplace}.json` — plugin manifests
- `.codex-plugin/plugin.json` + `.codex/hooks.json` — Codex adapter: manifest (no hooks field — auto-discovered) + repo-dev openwiki commit gate (ADR-0033)
- `config/keep-on.json` — the shipped SEED for the curated always-on allowlist (runtime copy seeded once into `~/.claude/skill-concierge/keep-on.json`, the canonical durable home; ADR-0025)

## Setup & verification

```bash
./setup.sh                  # idempotent: venv + Qdrant + reindex + apply-overrides
python3 scripts/doctor.py   # read-only health check (add --fix for safe repairs)
```

Run `doctor.py` (or the `skill-concierge:doctor` skill) before **and** after any change that
touches the engine, MCP wiring, or overrides. A green `status: OK` is the bar — claim "done"
only with that proof in hand.

**Doc/version drift guard:** `python3 scripts/driftcheck.py driftcheck.json` (exit 0 = synced). It
checks the version triple (`plugin.json` ↔ `marketplace.json` ↔ latest `CHANGELOG.md` heading), that
every doc-referenced path exists, and that this file and `CLAUDE.md` name the same scratch dirs. Run it
after a version bump or after editing a fact shared between these docs.

## Conventions

- **Python:** 3.10–3.12, `snake_case`. `analyze.py` and `doctor.py` are **stdlib-only** — keep them dependency-free.
- **Shell:** `setup.sh` and the `bin/` launchers target POSIX `sh`/`bash`; keep them portable and idempotent.
- **Versioning:** bump `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, AND `.codex-plugin/plugin.json` together, plus a `CHANGELOG.md` entry. Never bump one alone (`driftcheck.json` mirrors all of them).
- **ADRs are immutable.** Don't edit an accepted ADR — supersede it with a new one.
- **Vendored engine:** never patch `vendor/skill-search/` to diverge from upstream silently; record any customization in [`vendor/skill-search/VENDORED.md`](vendor/skill-search/VENDORED.md).
- **Tool state is not source.** `.ijfw/`, `ijfw/`, `.handoff/`, `logs/`, and `graphify-out/` are session/runtime scratch — gitignored, never committed. (`graphify-out/` is the knowledge-graph build: `graph.json`, `graph.html`, `GRAPH_REPORT.md`, and a per-file extraction cache — all rebuildable from source, so it is derived output, not source.)

## Runtime flags

Each is a one-var revert to the prior behavior (`ENFORCER_AUTHORIZED_SKIP`, `ENFORCER_CHAIN_HINT`, `ENFORCER_CROSS_HARNESS`, and `SKILL_BODY_TRIGGERS` default ON; `SKILL_LLM_TRIGGERS` default OFF):

- `SKILL_CODEX_ROOTS` (`vendor/skill-search/skill_search/skills_discovery.py`) — dual-harness discovery: index `~/.codex/skills` + `~/.codex/plugins/cache/**` alongside the Claude roots under distinct `codex-*` scopes (one shared collection; neither harness prunes the other's points). `=0` + a reindex restores Claude-only discovery byte-identically. The enforcer's chain-hint scope mirror honors the same flag. [ADR-0033](docs/adr/0033-dual-harness-codex-parity.md).

- `ENFORCER_CROSS_HARNESS` (`hooks/scripts/enforcer.py`) — keeps the per-turn INSTALLED offer to skills the running harness can actually invoke. `_retrieve` over-fetches to `RETRIEVE_LIMIT` (`TOP_K*5`, headroom not a guarantee — a foreign-dominated domain can return a short menu), drops foreign-scope rows, trims back to `TOP_K`; `_retrieve_foreign` re-surfaces the top `ENFORCER_FOREIGN_SLOTS` (2) scoring ≥ `ENFORCER_FOREIGN_FLOOR` (0.40) from a SEPARATE query as a marked `[codex]`/`[claude]` annex with the `get_skill` instruction — a dedicated query, so a foreign skill can never displace an installed slot. **A POST-filter, never a Qdrant `must_not scope`:** scope records where a skill's indexed copy LIVES, not invocability. Claude Code layers `enabledPlugins` across user → project → project-local settings while `_installed_plugin_roots()` reads only the user file, so a project-enabled plugin is dropped from discovery and its Codex twin wins the name — `_invocable_twin()` resolves installation (`installed_plugins.json`) plus the merged settings per session and keeps those rows in the offer — absent key = ENABLED (matching Claude Code), marketplace collisions resolve by union, and an unreadable manifest = "unknown" = **drop nothing** (the drop is conditioned on positive knowledge). That resolution stays in the hook, never in the machine-global index (ADR-0028 cwd-scoped-view hazard). Foreign scopes are DERIVED: from Claude `codex-plugin`+`codex-personal`; from Codex `plugin` ONLY — `personal` is not foreign there, because discovery walks the Claude root first so a skill in both personal roots is tagged `personal` while Codex can still invoke it. Harness detection uses PRECEDENCE (`CLAUDE_PLUGIN_ROOT`, else the hook's own `__file__`) and never resolves a falsy candidate — `Path("").resolve()` is the cwd and would invert the filter. `search_skills` and chain hints keep ADR-0033's union. `=0` reverts to the pre-change request shape and output. [ADR-0034](docs/adr/0034-cross-harness-offer-isolation.md).
- `ENFORCER_CHAIN_HINT` (`hooks/scripts/enforcer.py`) — appends a `CHAIN-HINT:` candidate line to every inject-bearing leg (mandate, mandate-only fallbacks, AUTHORIZED-SKIP lines) when this session used a skill declaring `next-skills:` within `ENFORCER_CHAIN_TTL_S` (900s). State = bounded ledger tail-read (auto + manual, sub-stamped rows excluded); successors = scope-keyed sidecar written at index time (`~/.claude/skill-concierge/next-skills.json`); hinted names pass keep-off + catalogue filters and bypass no floor. `=0` reverts byte-identically. [ADR-0029](docs/adr/0029-next-skill-chain-hints.md). Third-party-skill chains are curated in the operator-owned `~/.claude/skill-concierge/next-skills-overrides.json` (reader-side merge, override-wins — upstream upgrades cannot wipe them; absent file = byte-identical) — [ADR-0030](docs/adr/0030-operator-owned-chain-overrides.md).
- `ENFORCER_AUTHORIZED_SKIP` (`hooks/scripts/enforcer.py`) — injects a `SKILL-CHECK:` line on the enforcer's two previously-silent verdicts (getaway score-floor miss, conversational-intent skip) so the agent knows the hook already cleared the turn. `=0` restores the old silence. [ADR-0015](docs/adr/0015-authorized-skip-tier-and-library-doctrine.md).
- `SKILL_BODY_TRIGGERS` (`vendor/skill-search/skill_search/server.py`) — folds each skill body's labeled decision-section phrases into the MAX-pool trigger layer alongside the description-derived ones. `=0` + a reindex reverts to description-only. [ADR-0016](docs/adr/0016-body-derived-trigger-points.md).
- `SKILL_LLM_TRIGGERS` (`vendor/skill-search/skill_search/server.py`) — default **OFF**; layers the offline flywheel-generated natural-utterance phrases (`eval/triggers.json` `llm_triggers` block, EN+VN) FIRST in the MAX-pool trigger layer, ahead of description/body, capped COMBINED at `TRIGGERS_MAX` (live deploy uses `16` so utterances add slots rather than evict). Reads `SKILL_TRIGGERS` (path to the gitignored `eval/triggers.json`; absent → no utterances, graceful). `=1` + a reindex enables. [ADR-0026](docs/adr/0026-llm-utterance-trigger-layer.md). **Every engine-side flag above — `SKILL_CODEX_ROOTS`, `SKILL_BODY_TRIGGERS`, `SKILL_LLM_TRIGGERS` — plus `TRIGGERS_MAX`, `SKILL_TRIGGERS` and `SKILL_CONCIERGE_CATALOG_ROOTS` is forwarded by `auto_reindex._mcp_env()` to the detached SessionStart reindex (v0.16.1; `SKILL_CODEX_ROOTS` added in v0.25.0)** — without it, a background reindex rebuilds at engine defaults and prunes whatever layer the live query server was configured to serve. INVARIANT: every engine-side flag readable from `.mcp.json` belongs in that tuple; the count is not the rule, the completeness is.

`skills/skill-usage-audit/scripts/audit_skill_usage.py` recognizes the `SKILL-CHECK:` marker: a
hook-authorized skip is tallied separately as `authorized_skip` and excluded from the false-SKIPPING
count, so the doctrine's hardest-rule metric doesn't get inflated by lawful, hook-cleared skips.

## Guardrails

- The index holds **model-invocable `SKILL.md` skills only** — built-in slash-commands are excluded by design ([ADR-0001](docs/adr/0001-index-model-invocable-skills-only.md)). Don't "fix" their absence.
- The vendored `eval/` recall@k is calibrated to a *different* skill universe; a near-zero score is a wrong-universe artifact, not a weak retriever ([caveats §1](docs/caveats.md)).
- Hooks are **fail-silent and additive-only** — a telemetry failure must never block a turn. The one deliberate exception is the openwiki commit gate below, which is a *gate*, not telemetry, and blocks by design.
- **`git commit` is gated on openwiki parity.** `.claude/settings.json` wires a `PreToolUse(Bash)` hook to `scripts/openwiki_parity_guard.py`. Non-commit Bash calls pass through silently; a `git commit` (including compound `git add . && git commit` and `git -C <path> commit`) is **denied** if either deterministic check fails:
  1. **Version parity** — `openwiki/quickstart.md` is registered as a `driftcheck.json` mirror, so its `**Version:**` line must match `.claude-plugin/plugin.json` (the SSOT) alongside marketplace/CHANGELOG/README. There is no second version checker to drift.
  2. **Link integrity** — every relative link under `openwiki/` must resolve on disk. This catches the corrupted/half-finished-edit class that shipped a clobbered sentence and a dead link once already.

  It does **not** judge whether the wiki's prose is semantically current — nothing cheap can, and a guard pretending to would be theater; that is what `/openwiki:wiki update` is for. Verify locally with `python3 scripts/driftcheck.py driftcheck.json` (must exit 0). The guard **fails open** on any internal error — a broken guard must never wedge the repo — and `OPENWIKI_GUARD=0` is the emergency override. `.claude/settings.json` is un-ignored on purpose (`.gitignore`: `.claude/*` + `!.claude/settings.json`) so the wiring exists on every clone; the rest of `.claude/` stays ignored.
- **`git commit` also emits a graph-staleness NOTICE — a warning, never a block.** `.claude/settings.json` wires a second `PreToolUse(Bash)` hook to `scripts/graph_staleness_notice.py`. On a `git commit` it asks graphify's own `detect_incremental()` which **git-tracked** files are new or modified since `graphify-out/manifest.json`, and reports them as `additionalContext`. The commit proceeds.
  It **warns instead of denying, deliberately — do not "upgrade" it to a deny.** `openwiki/` is committed, so a stale wiki ships to every clone and the fix is a sub-second text edit: blocking is proportionate. `graphify-out/` is **gitignored** — it never ships, so a stale graph harms only the local session — and the fix is asymmetric: code staleness rebuilds via AST for free, but doc staleness costs LLM calls through the gateway. This repo is doc-heavy and writes plans/reports constantly, so a deny would tax every commit and buy nothing the post-commit rebuild doesn't already give.
  Scope is **git-tracked files only** — load-bearing: graphify indexes scratch dirs (`.remember/`, `.memsearch/`, `.gjc/`) that churn every turn, so an unscoped notice would fire on *every* commit forever, and a warning that always fires is one you train yourself to ignore. It never emits `permissionDecision` (an `"allow"` there would auto-approve every commit and silently disable the permission prompt). Code drift self-heals via graphify's **post-commit hook** (`graphify hook status`; installs post-commit + post-checkout, AST-only, no LLM); docs need `/graphify . --update`. **Fails open** — no graph on disk, no graphify installed, or any internal error → silent. Override: `GRAPH_NOTICE=0`.
  *Reconciles with the repo's fail-silent hook doctrine:* this one is telemetry, not a gate — it never blocks. The openwiki guard remains the sole deliberate exception that denies.
- **Ledger metrics are EPOCH-SCOPED — NEVER pool them across config changes.** This is the load-bearing
  trap: this repo changes the very things the ledger measures (gate floors, retrieval engine, doctrine,
  the embed shim) *almost daily*, so the invocation-ledger is a **sequence of short config epochs, not one
  dataset**. A rate pooled across them describes *no real configuration* and manufactures a false "measured"
  signal. Before citing ANY ledger rate (fallback / conversion / dodge / hit@k):
  1. **Find the current epoch start** — the last commit touching `hooks/scripts/enforcer.py` (thresholds/gates),
     `hooks/doctrine/skill-first.md`, `vendor/skill-search/skill_search/server.py` (retrieval), or
     `scripts/embed_server.py`: `git log --date=format:'%Y-%m-%d %H:%M' --pretty='%cd %h %s' -- <those paths>`.
  2. **Window to it:** `python3 scripts/analyze.py --since "<that datetime>"`. Never quote the all-time number.
  3. **Exclude contamination:** subagent / harness / `<task-notification>` traffic and your *own* meta/self-session
     turns are NOT representative (a heavy multi-agent session alone can swing the fallback rate 30+ points).
  4. **Respect sample size:** a fresh epoch may be too small to conclude — say **"insufficient data"** rather than
     pool backward to inflate n.
  5. **Design vs environment:** a metric shift that does NOT line up with a config commit (e.g. a per-day spike
     *between* releases) is **environmental** (shim/Docker/load), not a property of the code — do not attribute it
     to a design decision.
  This exact mistake — pooling ~15 epochs (v0.2→v0.12) and reading the aggregate as a current-state signal —
  already invalidated a full multi-agent analysis once (see the *Data-validity note* in
  `plans/reports/from-audit-and-openspace-syntheses-…-integrated-final-…-report.md`). Calibrate confidence to
  data-validity: an epoch-pooled or tiny-sample rate is **UNMEASURED**, never "measured".

## OpenWiki

This repository has documentation located in the /openwiki directory.

Start here:
- [OpenWiki quickstart](openwiki/quickstart.md)

OpenWiki includes repository overview, architecture notes, workflows, domain concepts, operations, integrations, testing guidance, and source maps.

When working in this repository, read the OpenWiki quickstart first, then follow its links to the relevant architecture, workflow, domain, operation, and testing notes.
