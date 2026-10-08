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
| `ENFORCER_JEV_ROUTER` | ON | English prompts: Jev ranks the whole catalogue; the top 5 become the "Whole-shelf ranking". Best fit under 0.30 is an authorized skip (`jev_skip`). Any failure falls back to the embedding path. `ENFORCER_JEV_GATE=0` is an alias. | [0061](docs/adr/0061-jev-skill-router.md), [0062](docs/adr/0062-no-skill-ruling-and-whole-shelf-label.md) |
| `ENFORCER_JEV_BENCH` | unset = `ts:<ENFORCER_JEV_MODEL>` | Not on/off: the ordered Jev tiers (`ts`, `gw`, `cc`). A running jevd named by `JEVD_URL` that holds keys supplies the ladder instead. Command Code gets 5.5 s (`ENFORCER_JEV_CC_TIMEOUT`); the route budget is 7.8 s. | [0075](docs/adr/0075-jev-bench-tiered-systemone-endpoints.md), [0079](docs/adr/0079-command-code-jev-tier-and-timeout-fall-through.md), [0080](docs/adr/0080-jevd-as-the-jev-bench.md), [0081](docs/adr/0081-owner-relay-serves-command-code.md) |
| `ENFORCER_JEV_HISTORY` | OFF | The rerank call also sees redacted text-only history. Its gate failed; turning it on is the owner's call. | [0076](docs/adr/0076-jev-typed-questions-consult-triggers-history.md) |
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
| `SKILL_SYNCED_ROOTS` | OFF | Claude account-synced skills as `anthropic-skills:<name>`, scope `claude-synced`. Stays OFF until `doctor` shows every harness cache at `0.48.0` or later. | [0058](docs/adr/0058-off-list-rule-exclusion-echo-row-provenance-synced-default-off.md) |

**Scripts** (offline tools, never per turn)

| Flag | Default | Effect | ADR |
|---|---|---|---|
| `SKILL_CONSULT_JEV` | ON | `scripts/consult_fit.py`: `consult --fast` ranks candidates with a Jev fit matrix; evidence only. | [0076](docs/adr/0076-jev-typed-questions-consult-triggers-history.md) |
| `SKILL_CONSULT_JEV_WIDEN` | ON | `scripts/consult_fit.py widen`: Jev's whole-catalogue top 10 go ahead of the consult sieve rows. | [0078](docs/adr/0078-consult-sieve-jev-widening.md) |
| `SKILL_TRIGGER_JEV_FILTER` | ON but inert | `scripts/llm_triggers.py`, `scripts/trigger_filter.py`: drops weak flywheel utterances; does nothing until a calibrated thresholds file exists. | [0076](docs/adr/0076-jev-typed-questions-consult-triggers-history.md) |

`skills/skill-usage-audit/scripts/audit_skill_usage.py` counts a `SKILL-CHECK:` skip as `authorized_skip`, apart from false skips.
