"""One-shot: apply validator findings F1-F10, L2, L4 to parts/flags-compact.md (2026-10-08)."""
from pathlib import Path
p = Path("parts/flags-compact.md"); t = p.read_text()
R = [
 # F7 preamble + wider pointer trigger (validator L-section)
 ("Each flag turns one behavior on or off with one variable, and setting it to its off value restores the behavior before that change. This table is the index. The full text for each flag (mechanism, numbers, tests, gate history, revert path) is in [`docs/runtime-flags.md`](docs/runtime-flags.md): read a flag's entry there before you change its code or its default.",
  "Most flags turn one behavior on or off with one variable, and the off value restores the behavior before that change; a row says so where a flag differs. This table is the index. The full text for each flag (mechanism, numbers, tests, gate history, revert path, preconditions) is in [`docs/runtime-flags.md`](docs/runtime-flags.md). Read a flag's entry there before you change its code or default, set it in any env, or reason about how it behaves live."),
 # F10
 ("**`ENGINE_ENV_KEYS` in `scripts/engine_env.py` lists every engine setting that shapes the index**: the trigger layers, every harness-root flag, `SKILL_CONCIERGE_CATALOG_ROOTS` and `SKILL_SYNCED_ROOTS`. All five reindex paths (`auto_reindex.py`, `auto_flywheel.py`, `flywheel.py`, `doctor.py`, `setup.sh`) forward from that one list.",
  "**`ENGINE_ENV_KEYS` in `scripts/engine_env.py` lists every engine setting that shapes the index**, including the store and embedder, the trigger layers, every harness-root flag, `SKILL_CONCIERGE_CATALOG_ROOTS` and `SKILL_SYNCED_ROOTS`. Every reindex path (`auto_reindex.py`, `auto_flywheel.py`, `flywheel.py`, `doctor.py`, `setup.sh`, `trigger_filter.py reindex`) forwards from that one list."),
 # F2
 ("(`SKILL_ROW_ORIGIN`, `SKILL_BLOCKLIST`, `SKILL_CONSULT*`, `SKILL_REPUTATION`, `SKILL_FINDABILITY`, `SKILL_SEARCH_COMPLEMENT`, and the hook's `ENFORCER_*` flags). A query-time server flag takes effect only from that harness's MCP server env, after a server restart.",
  "(`SKILL_ROW_ORIGIN`, `SKILL_BLOCKLIST`, `SKILL_CONSULT*`, `SKILL_REPUTATION`, `SKILL_SEARCH_COMPLEMENT`, and the hook's `ENFORCER_*` flags). A query-time server flag takes effect only from that harness's MCP server env, after a server restart. `SKILL_FINDABILITY` is read at reindex time but does not shape the index, so it is not in the list either: set it where reindexes run (`~/.config/harness-env.sh`)."),
 # L4
 ("Set `ENFORCER_JEV_BENCH` and `SKILL_TRIGGER_JEV_FILTER` in `~/.config/harness-env.sh`, so every harness and the detached `auto_flywheel` see them.",
  "`ENFORCER_JEV_BENCH` is set in `~/.config/harness-env.sh` with the Command Code tier first; the Command Code and DSH adapters pass `ENFORCER_JEV_BUDGET=1.6`, so that tier is skipped there. Set `SKILL_TRIGGER_JEV_FILTER` in the same file, so every harness and the detached `auto_flywheel` see it."),
 # F8
 ("skips before any I/O; band `harness_skip`.", "skips before any embed or Qdrant I/O; band `harness_skip`."),
 ("`skill-concierge:consult`, before any I/O, never in subagents.", "`skill-concierge:consult`, before any embed or Qdrant I/O, never in subagents."),
 # F7 keep-off out of the DETERMINISTIC row
 ("pin a skill at 1.0 before the embed step. The keep-off map is consent-only. | [0054](docs/adr/0054-harness-message-lane-and-audit-fixes.md), [0077](docs/adr/0077-keep-off-map-is-consent-only.md) |",
  "pin a skill at 1.0 before the embed step. | [0054](docs/adr/0054-harness-message-lane-and-audit-fixes.md) |"),
 # F9 + F7 (not on/off)
 ("| `ENFORCER_JEV_BENCH` | unset = `ts:<ENFORCER_JEV_MODEL>` | The ordered Jev tiers (`ts`, `gw`, `cc`). A running jevd named by `JEVD_URL` supplies the ladder instead.",
  "| `ENFORCER_JEV_BENCH` | unset = `ts:<ENFORCER_JEV_MODEL>` | Not on/off: the ordered Jev tiers (`ts`, `gw`, `cc`). A running jevd named by `JEVD_URL` that holds keys supplies the ladder instead."),
 # F5
 ("never displaces an installed row. `=0` makes them search-only.",
  "never displaces an installed row. `=0` makes them search-only (`ENFORCER_EXTERNAL_OFFER` is an alias); `ENFORCER_ANNEX_COMPLEMENT=0` restores the ADR-0047 margin rule."),
 # F6
 ("Sizes the foreign annex by score margin from the installed top (0.08, cap 2).",
  "Sizes the foreign annex by score margin from the installed top (0.08, cap 2); also sets the external annex default (4 rows, or 2 when off)."),
 # F1 + F4
 ("| `SKILL_LLM_TRIGGERS` | OFF | Flywheel utterances from `triggers.json` (and `triggers-curated.json` first) join the trigger layer, capped by `TRIGGERS_MAX`. Index-shaping.",
  "| `SKILL_LLM_TRIGGERS` | OFF in code, ON in the shipped `.mcp.json` (`TRIGGERS_MAX` 16) | Flywheel utterances from `triggers.json` join the trigger layer after the operator-curated `triggers-curated.json` phrases, which apply whatever this flag is set to. Index-shaping."),
 # L2
 ("| `SKILL_SYNCED_ROOTS` | OFF | Claude account-synced skills as `anthropic-skills:<name>`, scope `claude-synced` |",
  "| `SKILL_SYNCED_ROOTS` | OFF | Claude account-synced skills as `anthropic-skills:<name>`, scope `claude-synced`. Stays OFF until `doctor` shows every harness cache at `0.48.0` or later. |"),
]
for a, b in R:
    assert t.count(a) == 1, a[:60]
    t = t.replace(a, b)
# F7: keep-off rule on its own line under the hook table (L1)
anchor = "| `SKILL_JEVD_ENV_CHECK` |"
i = t.index(anchor); j = t.index("\n", i)
t = t[:j+1] + "\nThe keep-off map (`~/.claude/skill-concierge/keep-off.json`) is consent-only and belongs to no flag: only `scripts/build_keep_off.py --apply` saves it, after Thinh says yes, and it hides nothing unless it carries `\"approved_by_user\": true` ([ADR-0077](docs/adr/0077-keep-off-map-is-consent-only.md)).\n" + t[j+1:]
p.write_text(t)
print("applied", len(R) + 1)
