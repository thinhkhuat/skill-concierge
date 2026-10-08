# AGENTS.md

Agent-contributor instructions for **skill-concierge** — a skill-governance layer for
Claude Code, Codex, Command Code, Oh My Pi (OMP), ZCode, DeepSeek Harness (DSH), Cline, and OpenCode v2: semantic retrieval (*which* skill) +
use-enforcement (*whether* a skill is used at all) + a compounding invocation ledger
(*what* actually got used).

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

The full tree is in the README's *Architecture* section. One line per area here; the per-file detail (every script, hook, and adapter's behavior and its ADR) is in [`docs/repository-layout.md`](docs/repository-layout.md). Read that file before you edit a hook, a script, or an adapter.

- `skills/{skill-search,setup,doctor,skill-usage-audit,keep-on,blocklist,reputation,flywheel,catalogs,consult}/SKILL.md` — the plugin skills.
- `scripts/` — maintenance CLIs: `doctor.py` (health), `analyze.py` (ledger; window with `--since`/`--until`, never split the ledger by hand), the list managers (`keep-on.py`, `blocklist.py`, `reputation.py`, `catalogs.py`), the Jev tools, and `engine_env.py` (the one `ENGINE_ENV_KEYS` list, see *Runtime flags*).
- `hooks/` — the in-generation governance layer: `enforcer.py` (the per-turn SKILL-FIRST gate), `skill_guard.py` (blocklist deny), `skill_exclusions.py` ("not for" echo), `ledger.py` (invocation capture), `doctrine.py` + `doctrine/skill-first.md` (the standing order), and the SessionStart self-heal hooks.
- `vendor/skill-search/` — vendored MCP engine (MIT · sowhan/skill-search). **Do not diverge silently**: record every patch in [`VENDORED.md`](vendor/skill-search/VENDORED.md).
- `adapters/` — one module per harness: `codex/`, `claude-code/`, `commandcode/`, `omp/`, `zcode/`, `dsh/`, `cline/` (a code plugin + a generated Agent Plugin, ADR-0086), `opencode/` (a native v2 plugin package + installer, ADR-0085). The `codex/` and `claude-code/` installers refuse to downgrade a newer cache; ZCode needs no adapter vehicle (its `install.sh` only verifies and repairs).
- Manifests: `.claude-plugin/{plugin,marketplace}.json`, `.codex-plugin/plugin.json` + `.codex/hooks.json`, and root `package.json` (carries the OMP extension hook `omp.extensions`).
- `config/keep-on.json` — the shipped seed for the always-on allowlist; the runtime copy lives in `~/.claude/skill-concierge/keep-on.json` (ADR-0025).

## Setup & verification

```bash
./setup.sh                  # idempotent: venv + start the index owner + reindex + apply-overrides
python3 scripts/doctor.py   # read-only health check (add --fix for safe repairs)
```

Run `doctor.py` (or the `skill-concierge:doctor` skill) before **and** after any change that
touches the engine, MCP wiring, or overrides. A green `status: OK` is the bar — claim "done"
only with that proof in hand.

**Doc/version drift guard:** `python3 scripts/driftcheck.py driftcheck.json` (exit 0 = synced). It
checks the version across the mirror set (`plugin.json` ↔ `marketplace.json` ↔ `.codex-plugin/plugin.json` ↔ latest `CHANGELOG.md` heading ↔ `README.md` ↔ `openwiki/quickstart.md`), that
every doc-referenced path exists, and it runs every `command_checks` script listed in `driftcheck.json`
(each script's docstring says what it guards; among them, this file and `CLAUDE.md` name the same scratch
dirs, and the *Runtime flags* table, `docs/runtime-flags.md` and the code agree on every flag and its
default). Run it after a version bump, after editing a fact shared between these docs, or after changing a
flag or its default.

## Conventions

- **Python:** 3.10–3.12, `snake_case`. `analyze.py` and `doctor.py` are **stdlib-only** — keep them dependency-free.
- **Shell:** `setup.sh` and the `bin/` launchers target POSIX `sh`/`bash`; keep them portable and idempotent.
- **Versioning:** bump `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `.codex-plugin/plugin.json`, AND root `package.json` together, plus a `CHANGELOG.md` entry. Never bump one alone — `driftcheck.json` mirrors the manifest/CHANGELOG/README/quickstart set, and `package.json` carries the OMP extension hook (`omp.extensions`), so its version must stay in lockstep even though driftcheck does not regex it.
- **Tests run with a clean Jev environment.** `tests/conftest.py` removes every `ENFORCER_JEV_*` variable plus `TYPESAFE_API_KEY` and `CMD_API_KEY` before collection; without it, a shell that has loaded the machine's `harness-env.sh` fails 13 router/history tests.
- **ADRs are immutable.** Don't edit an accepted ADR — supersede it with a new one.
- **Vendored engine:** never patch `vendor/skill-search/` to diverge from upstream silently; record any customization in [`vendor/skill-search/VENDORED.md`](vendor/skill-search/VENDORED.md).
- **Tool state is not source.** `.ijfw/`, `ijfw/`, `.handoff/`, `logs/`, and `graphify-out/` are session/runtime scratch — gitignored, never committed. (`graphify-out/` is the knowledge-graph build: `graph.json`, `graph.html`, `GRAPH_REPORT.md`, and a per-file extraction cache — all rebuildable from source, so it is derived output, not source.)

## Runtime flags

Most flags turn one behavior on or off with one variable, and the off value restores the behavior before that change; a row says so where a flag differs. This table is the index. The full text for each flag (mechanism, numbers, tests, gate history, revert path, preconditions) is in [`docs/runtime-flags.md`](docs/runtime-flags.md). Read a flag's entry there before you change its code or default, set it in any env, or reason about how it behaves live.

Two invariants hold for every flag:

- **`ENGINE_ENV_KEYS` in `scripts/engine_env.py` lists every engine setting that shapes the index**, including the store and embedder, the trigger layers, every harness-root flag, `SKILL_CONCIERGE_CATALOG_ROOTS` and `SKILL_SYNCED_ROOTS`. Every reindex path (`auto_reindex.py`, `auto_flywheel.py`, `flywheel.py`, `doctor.py`, `setup.sh`, `trigger_filter.py reindex`) forwards from that one list. A missing key makes a background reindex rebuild at engine defaults and prune the layer the live server serves. The rule is completeness, not a count.
- **Query-time and hook-side flags stay out of that list** (`SKILL_ROW_ORIGIN`, `SKILL_BLOCKLIST`, `SKILL_CONSULT*`, `SKILL_REPUTATION`, `SKILL_SEARCH_COMPLEMENT`, and the hook's `ENFORCER_*` flags). A query-time server flag takes effect only from that harness's MCP server env, after a server restart. `SKILL_FINDABILITY` is read at reindex time but does not shape the index, so it is not in the list either: set it where reindexes run (`~/.config/harness-env.sh`).

Machine-local settings: `ENFORCER_MULTI_INTENT=0` is set in `~/.claude/settings.json` env as a trial ([ADR-0055](docs/adr/0055-multi-intent-off-projection-pending.md)). `ENFORCER_JEV_BENCH` is set in `~/.config/harness-env.sh` with the Command Code tier first; the Command Code and DSH adapters pass `ENFORCER_JEV_BUDGET=1.6`, so that tier is skipped there. Set `SKILL_TRIGGER_JEV_FILTER` in the same file, so every harness and the detached `auto_flywheel` see it.

**Per-turn hook** (`hooks/scripts/enforcer.py` unless noted)

| Flag | Default | Effect | ADR |
|---|---|---|---|
| `ENFORCER_AUTHORIZED_SKIP` | ON | A `SKILL-CHECK:` line on the skip verdicts that used to be silent. | [0015](docs/adr/0015-authorized-skip-tier-and-library-doctrine.md) |
| `ENFORCER_HARNESS_SKIP` | ON | A harness-generated prompt (task notification, system reminder, teammate message, resume banner, `omp-msum`) skips before any embed or Qdrant I/O; band `harness_skip`. | [0054](docs/adr/0054-harness-message-lane-and-audit-fixes.md) |
| `ENFORCER_DETERMINISTIC` | ON | Whole-word phrases in `config/deterministic-routes.json` pin a skill at 1.0 before the embed step. | [0054](docs/adr/0054-harness-message-lane-and-audit-fixes.md) |
| `ENFORCER_JEV_ROUTER` | ON | English prompts: Jev ranks the whole catalogue; the top 5 become the "Whole-shelf ranking". Best fit under 0.30 is an authorized skip (`jev_skip`). A failed, late or budget-cut rerank keeps the wide pass's own menu (rows ordered by lift) before any fallback to the embedding path; the event records `stage` `full` or `wide`. Any other failure falls back to the embedding path. `ENFORCER_JEV_GATE=0` is an alias. | [0061](docs/adr/0061-jev-skill-router.md), [0062](docs/adr/0062-no-skill-ruling-and-whole-shelf-label.md), [0087](docs/adr/0087-staged-jev-menu-and-honest-cline-offer-row.md) |
| `ENFORCER_JEV_BENCH` | unset = `ts:<ENFORCER_JEV_MODEL>` | Not on/off: the ordered Jev tiers (`ts`, `gw`, `cc`). A running jevd named by `JEVD_URL` that holds keys supplies the ladder instead. Command Code gets 5.5 s (`ENFORCER_JEV_CC_TIMEOUT`); the route budget is 7.8 s. | [0075](docs/adr/0075-jev-bench-tiered-systemone-endpoints.md), [0079](docs/adr/0079-command-code-jev-tier-and-timeout-fall-through.md), [0080](docs/adr/0080-jevd-as-the-jev-bench.md), [0081](docs/adr/0081-owner-relay-serves-command-code.md) |
| `ENFORCER_JEV_HISTORY` | OFF | The rerank call also sees redacted text-only history. Its gate failed; turning it on is the owner's call. | [0076](docs/adr/0076-jev-typed-questions-consult-triggers-history.md) |
| `ENFORCER_LEDGER` | ON | Each run appends its offer row to the ledger. `=0` writes none. `=defer` (the Cline plugin's setting on every pass) writes none and returns the row in the hook output as `skillConciergeOffer`, so the plugin logs the menu its first model call carried (`seen`: `full` or `preview`; a later full row is `offer_late`). Not an operator switch. | [0086](docs/adr/0086-cline-native-plugin-and-agent-plugin.md), [0087](docs/adr/0087-staged-jev-menu-and-honest-cline-offer-row.md) |
| `ENFORCER_JEV_TIER` | unset = (empty) | Not on/off: limits the Jev route to one tier, by jevd provider name or model id (with jevd down, `typesafe`, `commandcode`, `gateway` match the `ts`, `cc`, `gw` bench tiers); empty = every tier. The Cline plugin pins its full pass to `typesafe`, so Cline turns never call Command Code. | [0087](docs/adr/0087-staged-jev-menu-and-honest-cline-offer-row.md) |
| `ENFORCER_CROSS_HARNESS` | ON | The installed offer holds only skills this harness can invoke; the rest appear in a `get_skill` annex marked with their harness. | [0034](docs/adr/0034-cross-harness-offer-isolation.md), [0059](docs/adr/0059-harness-complete-offer-isolation-echo-everywhere.md) |
| `ENFORCER_PROJECT_ISOLATION` | ON | Drops a project-scoped row that belongs to another project. | [0059](docs/adr/0059-harness-complete-offer-isolation-echo-everywhere.md) |
| `ENFORCER_EXTERNAL_ANNEX` | ON | External-catalog skills appear in a separate annex that never displaces an installed row. `=0` makes them search-only (`ENFORCER_EXTERNAL_OFFER` is an alias); `ENFORCER_ANNEX_COMPLEMENT=0` restores the ADR-0047 margin rule. | [0032](docs/adr/0032-external-catalogs-first-class-annex.md), [0047](docs/adr/0047-revert-tier-parity-restore-annex.md), [0048](docs/adr/0048-complement-annex.md) |
| `ENFORCER_ANNEX_DYNAMIC` | ON | Sizes the foreign annex by score margin from the installed top (0.08, cap 2); also sets the external annex default (4 rows, or 2 when off). | [0036](docs/adr/0036-dynamic-annex-sizing.md), [0048](docs/adr/0048-complement-annex.md) |
| `ENFORCER_CHAIN_HINT` | ON | A `CHAIN-HINT:` line naming the next skills declared by the skill used last. | [0029](docs/adr/0029-next-skill-chain-hints.md), [0030](docs/adr/0030-operator-owned-chain-overrides.md) |
| `ENFORCER_MINED_CHAINS` | ON | Chain successors mined from the ledger, used as the lowest layer. | [0040](docs/adr/0040-behavior-mined-skill-chains.md) |
| `ENFORCER_MULTI_INTENT` | ON in code, OFF on this machine's Claude Code | Several primary rows when a prompt holds two or more separate intents. | [0041](docs/adr/0041-multi-intent-offers-and-route-projection.md), [0055](docs/adr/0055-multi-intent-off-projection-pending.md) |
| `ENFORCER_CHAIN_PROJECTION` | ON | A `ROUTE` continuation line for the top candidate. | [0041](docs/adr/0041-multi-intent-offers-and-route-projection.md) |
| `SKILL_CONSULT_ROUTE` | ON | A deliberation-shaped turn gets a `CONSULT-ROUTE` to `skill-concierge:consult`, before any embed or Qdrant I/O, never in subagents. | [0049](docs/adr/0049-consult-deliberation-layer.md) |
| `SKILL_REPUTATION` | ON | The owner's ❤️/⭐ and the computed 🔥 render as badges; up to 2 ranked skills are pulled under Jev's five rows. Also `hooks/scripts/auto_promote.py`. Manage with `scripts/reputation.py` or the `skill-concierge:reputation` skill. | [0083](docs/adr/0083-owner-reputation-badges.md) |
| `SKILL_BLOCKLIST` | ON | The user-ordered disable tier, enforced by `skill_guard.py`, the hook, the engine and `apply-overrides.py`. | [0046](docs/adr/0046-blocklist-disable-tier.md) |
| `SKILL_OWNER_AUTOSTART` | ON | Hook-side autostart of the local index owner. `=0` stops only the autostart; there is no earlier behavior to restore. Also `bin/skill-search-mcp`. | [0070](docs/adr/0070-local-index-owner-replaces-qdrant-and-docker-embed-shim.md) |
| `SKILL_JEVD_ENV_CHECK` | ON | `hooks/scripts/doctrine.py`: a SessionStart warning when jevd runs but this session's `JEVD_URL` would bypass it. | — |

The keep-off map (`~/.claude/skill-concierge/keep-off.json`) is consent-only and belongs to no flag: only `scripts/build_keep_off.py --apply` saves it, after Thinh says yes, and it hides nothing unless it carries `"approved_by_user": true` ([ADR-0077](docs/adr/0077-keep-off-map-is-consent-only.md)).

**Engine** (`vendor/skill-search/skill_search/server.py`)

| Flag | Default | Effect | ADR |
|---|---|---|---|
| `SKILL_BODY_TRIGGERS` | ON | Phrases from a skill body's decision sections join the trigger layer. Index-shaping. | [0016](docs/adr/0016-body-derived-trigger-points.md) |
| `SKILL_LLM_TRIGGERS` | OFF in code, ON in the shipped `.mcp.json` (`TRIGGERS_MAX` 16) | Flywheel utterances from `triggers.json` join the trigger layer after the operator-curated `triggers-curated.json` phrases, which apply whatever this flag is set to. Index-shaping. | [0026](docs/adr/0026-llm-utterance-trigger-layer.md), [0058](docs/adr/0058-off-list-rule-exclusion-echo-row-provenance-synced-default-off.md) |
| `SKILL_DECLARED_TRIGGERS` | OFF | Drops "Not for" sentences from triggers and splits list-form `when_to_use`. Index-shaping. | [0074](docs/adr/0074-findability-is-a-ratcheted-invariant.md) |
| `SKILL_SEARCH_COMPLEMENT` | OFF | `search_skills` ranks an installed row ahead of an external one within 0.08. | [0074](docs/adr/0074-findability-is-a-ratcheted-invariant.md) |
| `SKILL_FINDABILITY` | ON | A detached findability sweep after an index-changing reindex feeds doctor's "Findability" row. | [0074](docs/adr/0074-findability-is-a-ratcheted-invariant.md) |
| `SKILL_ROW_ORIGIN` | ON | Search rows carry `origin` and `disabled_in` and drop `command`. | [0058](docs/adr/0058-off-list-rule-exclusion-echo-row-provenance-synced-default-off.md) |
| `SKILL_CONSULT` | ON | Kill-switch for the `consult_candidates` tool. Capsule dossiers come from `scripts/llm_capsules.py` via `flywheel.py --generate --capsules`. | [0049](docs/adr/0049-consult-deliberation-layer.md) |
| `SKILL_CONSULT_SLOTS` | OFF | Reserves about 70% of consult rows for installed skills. Two held-out gates failed. | [0078](docs/adr/0078-consult-sieve-jev-widening.md) |
| `SKILL_CONSULT_RRF` | OFF | Merges consult result lists by reciprocal-rank fusion. The same gates failed. | [0078](docs/adr/0078-consult-sieve-jev-widening.md) |

**Discovery roots** (`vendor/skill-search/skill_search/skills_discovery.py`; index-shaping, so a change needs a reindex)

| Flag | Default | Indexes | ADR |
|---|---|---|---|
| `SKILL_CODEX_ROOTS` | ON | Codex skills, scopes `codex-*` | [0033](docs/adr/0033-dual-harness-codex-parity.md) |
| `SKILL_COMMANDCODE_ROOTS` | ON | Command Code skills | [0038](docs/adr/0038-command-code-triple-harness-parity.md) |
| `SKILL_OMP_ROOTS` | ON | Oh My Pi skills, scopes `omp-*` | [0039](docs/adr/0039-omp-quadruple-harness-parity.md) |
| `SKILL_ZCODE_ROOTS` | ON | ZCode skills, scopes `zcode-*` | [0042](docs/adr/0042-zcode-quintuple-harness-parity.md) |
| `SKILL_DSH_ROOTS` | ON | DeepSeek Harness skills, scopes `dsh-*` | [0050](docs/adr/0050-dsh-hexa-harness-parity.md) |
| `SKILL_CLINE_ROOTS` | ON | Cline skills, scopes `cline-*` | [0051](docs/adr/0051-cline-hepta-harness-parity.md) |
| `SKILL_OPENCODE_ROOTS` | ON | OpenCode v2 skills, scopes `opencode-*` | [0085](docs/adr/0085-opencode-octa-harness-parity.md) |
| `SKILL_SYNCED_ROOTS` | OFF | Claude account-synced skills as `anthropic-skills:<name>`, scope `claude-synced`. Stays OFF until `doctor` shows every harness cache at `0.48.0` or later. | [0058](docs/adr/0058-off-list-rule-exclusion-echo-row-provenance-synced-default-off.md) |

**Scripts** (offline tools, never per turn)

| Flag | Default | Effect | ADR |
|---|---|---|---|
| `SKILL_CONSULT_JEV` | ON | `scripts/consult_fit.py`: `consult --fast` ranks candidates with a Jev fit matrix; evidence only. | [0076](docs/adr/0076-jev-typed-questions-consult-triggers-history.md) |
| `SKILL_CONSULT_JEV_WIDEN` | ON | `scripts/consult_fit.py widen`: Jev's whole-catalogue top 10 go ahead of the consult sieve rows. | [0078](docs/adr/0078-consult-sieve-jev-widening.md) |
| `SKILL_TRIGGER_JEV_FILTER` | ON but inert | `scripts/llm_triggers.py`, `scripts/trigger_filter.py`: drops weak flywheel utterances; does nothing until a calibrated thresholds file exists. | [0076](docs/adr/0076-jev-typed-questions-consult-triggers-history.md) |

`skills/skill-usage-audit/scripts/audit_skill_usage.py` counts a `SKILL-CHECK:` skip as `authorized_skip`, apart from false skips.

## Guardrails

- The index holds **model-invocable `SKILL.md` skills only** — built-in slash-commands are excluded by design ([ADR-0001](docs/adr/0001-index-model-invocable-skills-only.md)). Don't "fix" their absence.
- The vendored `eval/` recall@k is calibrated to a *different* skill universe; a near-zero score is a wrong-universe artifact, not a weak retriever ([caveats §1](docs/caveats.md)).
- Hooks are **fail-silent and additive-only** — a telemetry failure must never block a turn. The three deliberate exceptions are the gates below: the openwiki commit parity guard, the blocklist `skill_guard.py` (a user-ordered disable is a gate, not telemetry — ADR-0046), and the git-stash guard `scripts/git_stash_guard.py`. All three block by design; all three fail OPEN on internal error so a broken guard can never wedge the repo or skill invocation.
- **`git commit` is gated on openwiki parity.** `.claude/settings.json` wires a `PreToolUse(Bash)` hook to `scripts/openwiki_parity_guard.py`. Non-commit Bash calls pass through silently; a `git commit` (including compound `git add . && git commit` and `git -C <path> commit`) is **denied** if either deterministic check fails:
  1. **Version parity** — `openwiki/quickstart.md` is registered as a `driftcheck.json` mirror, so its `**Version:**` line must match `.claude-plugin/plugin.json` (the SSOT) alongside marketplace/CHANGELOG/README. There is no second version checker to drift.
  2. **Link integrity** — every relative link under `openwiki/` must resolve on disk. This catches the corrupted/half-finished-edit class that shipped a clobbered sentence and a dead link once already.

  It does **not** judge whether the wiki's prose is semantically current — nothing cheap can, and a guard pretending to would be theater; that is what `/openwiki:wiki update` is for. Verify locally with `python3 scripts/driftcheck.py driftcheck.json` (must exit 0). The guard **fails open** on any internal error — a broken guard must never wedge the repo — and `OPENWIKI_GUARD=0` is the emergency override. `.claude/settings.json` is un-ignored on purpose (`.gitignore`: `.claude/*` + `!.claude/settings.json`) so the wiring exists on every clone; the rest of `.claude/` stays ignored.
- **`git commit` also emits a graph-staleness NOTICE — a warning, never a block.** `.claude/settings.json` wires a second `PreToolUse(Bash)` hook to `scripts/graph_staleness_notice.py`. On a `git commit` it asks graphify's own `detect_incremental()` which **git-tracked** files are new or modified since `graphify-out/manifest.json`, and reports them as `additionalContext`. The commit proceeds.
  It **warns instead of denying, deliberately — do not "upgrade" it to a deny.** `openwiki/` is committed, so a stale wiki ships to every clone and the fix is a sub-second text edit: blocking is proportionate. `graphify-out/` is **gitignored** — it never ships, so a stale graph harms only the local session — and the fix is asymmetric: code staleness rebuilds via AST for free, but doc staleness costs LLM calls through the gateway. This repo is doc-heavy and writes plans/reports constantly, so a deny would tax every commit and buy nothing the post-commit rebuild doesn't already give.
  Scope is **git-tracked files only** — load-bearing: graphify indexes scratch dirs (`.remember/`, `.memsearch/`, `.gjc/`) that churn every turn, so an unscoped notice would fire on *every* commit forever, and a warning that always fires is one you train yourself to ignore. It never emits `permissionDecision` (an `"allow"` there would auto-approve every commit and silently disable the permission prompt). Code drift self-heals via graphify's **post-commit hook** (`graphify hook status`; installs post-commit + post-checkout, AST-only, no LLM); docs need `/graphify . --update`. **Fails open** — no graph on disk, no graphify installed, or any internal error → silent. Override: `GRAPH_NOTICE=0`.
  *Reconciles with the repo's fail-silent hook doctrine:* this one is telemetry, not a gate — it never blocks.
- **`git stash` (any state-changing form) is denied outright.** `.claude/settings.json` wires a third `PreToolUse(Bash)` hook to `scripts/git_stash_guard.py`. Non-git and non-stash Bash calls pass through silently; `git stash push`/`save`/bare `git stash`/`pop`/`apply`/`drop`/`clear`/`store`/`create`/`branch` (any `-u`/`-a`/`-p`/`--keep-index` variant), a compound command carrying one (`git add . && git stash`), and `git -C <path> stash` are all **denied**, naming the alternatives: `git show <ref>:<path>` / `git diff <ref>` for a before/after comparison, a WIP commit on a branch to keep work, `git worktree add` to isolate it. Read-only `git stash list` / `git stash show` pass through. The check also follows a shell's `-c` string (`bash -lc`, `zsh -ic`, `sh -xc`, a shell named by a variable like `$SHELL -c`) and `eval`'s arguments, recursively, under a work cap — a command too large or too deeply nested to check within that cap is **denied** (not let through) with its own message, so a hook that would otherwise time out never fails open. A heredoc body is checked the same way as a command, so writing prose that merely mentions the stash command through a heredoc (e.g. a journal entry or commit message) is also denied — write that text to a file first instead. Added directly after two accidental stash uses during v0.54.2 release work turned a prompt-level rule into a hook-level one — a rule that lives only in a prompt is a symptom-level control. **Fails open** on any internal error or unparseable stdin. Override: `GIT_STASH_GUARD=0`. Tests: `tests/test_git_stash_guard.py`.
- **Ledger metrics are EPOCH-SCOPED — NEVER pool them across config changes.** This is the load-bearing
  trap: this repo changes the very things the ledger measures (gate floors, retrieval engine, doctrine,
  the index owner) *almost daily*, so the invocation-ledger is a **sequence of short config epochs, not one
  dataset**. A rate pooled across them describes *no real configuration* and manufactures a false "measured"
  signal. The standing watch items per epoch (what to monitor, triggers, env-first actions) live in
  **[`docs/epoch-watch.md`](docs/epoch-watch.md)** — the single canonical reference; this rule governs HOW
  to measure, that doc governs WHAT to watch. Before citing ANY ledger rate (fallback / conversion / dodge / hit@k):
  1. **Find the current epoch start** — the last commit touching `hooks/scripts/enforcer.py` (thresholds/gates),
     `hooks/doctrine/skill-first.md`, `vendor/skill-search/skill_search/server.py` (retrieval), or
     `vendor/skill-search/skill_search/index_owner.py` (the local index owner, ADR-0070; `scripts/embed_server.py`
     is retired): `git log --date=format:'%Y-%m-%d %H:%M' --pretty='%cd %h %s' -- <those paths>`.
     A ledger event `{"ev": "corpus_epoch"}` (written by `scripts/trigger_filter.py backfill` and `reindex`) also starts
     an epoch for retrieval metrics: the trigger corpus changed without a code commit (ADR-0076).
  2. **Window to it:** `python3 scripts/analyze.py --since "<that datetime>"`. Never quote the all-time number.
  3. **Exclude contamination:** subagent / harness / `<task-notification>` traffic and your *own* meta/self-session
     turns are NOT representative (a heavy multi-agent session alone can swing the fallback rate 30+ points).
  4. **Respect sample size:** a fresh epoch may be too small to conclude — say **"insufficient data"** rather than
     pool backward to inflate n.
  5. **Design vs environment:** a metric shift that does NOT line up with a config commit (e.g. a per-day spike
     *between* releases) is **environmental** (owner load/contention), not a property of the code — do not
     attribute it to a design decision.
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
