# Validator report: AGENTS.md / CLAUDE.md trim draft

**Verdict: PROMOTE WITH FIXES**

- Date: 2026-10-08 (Asia/Saigon)
- Subject: `plans/261008-0643-agents-md-trim/draft/{AGENTS.md, CLAUDE.md, docs/runtime-flags.md, docs/repository-layout.md}` against the repo's current `AGENTS.md`, `CLAUDE.md` and code at HEAD `1e702d0`.
- Mode: read-only. The only file I wrote is this report.

## Summary

The draft is mechanically sound. The text moved word for word, every relative link resolves, the two parity guards pass, and the sections the trim left alone are byte-identical to the originals. No finding blocks promotion.

Ten claims in the new compact table or in the CLAUDE.md pointer are wrong, misleading or overstated against the code (F1–F10). F1–F4 should be fixed before promotion. F5–F10 are one-phrase fixes. A few owner rules and preconditions now sit only in `docs/runtime-flags.md` (L1–L4). The pointer to that file fires only on a code edit, not when someone flips a flag or reasons about one, so those rules are easy to miss.

## Evidence base (what I ran)

- `build_draft.py` run once. Before the run I confirmed that `parts/*-compact.md` appear verbatim in `draft/AGENTS.md`. All four draft files have the same sha1 before and after the run (`333ef801…`, `6538722d…`, `ec9ca1b6…`, `3479126f…`), so the draft is the deterministic build output and was not hand-edited. Output:
  ```
  [verbatim flags] lines lost: 0
  [verbatim layout] lines lost: 0
  [claude bullet] 199 tokens checked, missing: []
  skill-list-parity OK: AGENTS.md names the 10 on-disk skills [...]
  doc-parity OK: CLAUDE.md names the same scratch dirs as AGENTS.md ['.handoff/', '.ijfw/', 'graphify-out/', 'ijfw/', 'logs/']
  RESULT: PASS
  ```
- My own link checker (separate from the build's) resolves each link against the file's final repo path:
  ```
  AGENTS.md links 66 broken []
  CLAUDE.md links 10 broken []
  docs/runtime-flags.md links 43 broken []
  docs/repository-layout.md links 1 broken []
  ```
  No link has a `#fragment` or a space in it, so there are no anchors to check.
- I diffed the original against the draft with the two replaced sections removed. AGENTS.md: `AGENTS-rest-identical`. CLAUDE.md: 2 changed lines, which are the Governance-flags bullet only.
- Every flag row was checked against its `os.environ.get(...)` default in `hooks/scripts/`, `vendor/skill-search/skill_search/`, `scripts/` and `bin/`. All table defaults match code, with the deployment caveat in F4.
- Every file path named in the compact layout and table exists on disk (none missing).
- `ENGINE_ENV_KEYS` (`scripts/engine_env.py:19-34`) contains every flag the table calls index-shaping, and none of the flags it says stay out.
- Machine-local settings: `~/.claude/settings.json:43` has `"ENFORCER_MULTI_INTENT": "0",`. `~/.config/harness-env.sh:85` exports `ENFORCER_JEV_BENCH`. `~/.claude/skill-concierge/trigger-jev-thresholds.json` is absent, so the "inert" claim holds.

## Findings, ranked by severity

### Medium (fix before promotion)

**F1. `SKILL_LLM_TRIGGERS` row says the curated layer depends on this flag. It does not.**
- Draft `AGENTS.md:101`: "| `SKILL_LLM_TRIGGERS` | OFF | Flywheel utterances from `triggers.json` (and `triggers-curated.json` first) join the trigger layer, capped by `TRIGGERS_MAX`. Index-shaping. |"
- Code `vendor/skill-search/skill_search/server.py:866-867`:
  ```
      _add(_curated_phrases(s["name"]))
      if SKILL_LLM_TRIGGERS:
  ```
  Curated phrases are added whatever this flag is set to. `server.py:754-755` says so too: "in triggers-curated.json beside / the utterance corpus (no env var of its own)".
- Impact: an agent turning the flag off expects curated phrases to go away too. They stay.
- Fix: "Flywheel utterances from `triggers.json` join the trigger layer after the operator-curated `triggers-curated.json` phrases, which apply regardless of this flag; …".

**F2. `SKILL_FINDABILITY` is listed as a query-time flag. It is a reindex-time flag.**
- Draft `AGENTS.md:68`: "**Query-time and hook-side flags stay out of that list** (`SKILL_ROW_ORIGIN`, `SKILL_BLOCKLIST`, `SKILL_CONSULT*`, `SKILL_REPUTATION`, `SKILL_FINDABILITY`, `SKILL_SEARCH_COMPLEMENT`, and the hook's `ENFORCER_*` flags). A query-time server flag takes effect only from that harness's MCP server env, after a server restart."
- Code: `server.py:164` `SKILL_FINDABILITY = os.environ.get("SKILL_FINDABILITY", "1") != "0"` is read inside `_launch_findability_sweep` (`server.py:1092` `if not SKILL_FINDABILITY:`). Its docstring says "Every reindex / path converges here through build_index". The background reindex paths run in their own process, through `engine_env.py`, which does not forward this key.
- Impact: following the draft's sentence, someone sets `SKILL_FINDABILITY=0` in the MCP server env and restarts. Sweeps launched by background reindexes (for example the SessionStart auto-reindex) keep running. The original wording, "Not index-shaping, so not in `ENGINE_ENV_KEYS`", was accurate.
- Fix: take `SKILL_FINDABILITY` out of the "query-time" list and describe it as "reindex-time, not index-shaping; set it where the reindex runs (`~/.config/harness-env.sh`)".

**F3. `SKILL_COMMANDCODE_ROOTS` has a table row but no text in `docs/runtime-flags.md`, though both draft files promise full text for every flag.**
- Draft `AGENTS.md:63`: "The full text for each flag (mechanism, numbers, tests, gate history, revert path) is in [`docs/runtime-flags.md`](docs/runtime-flags.md)". Draft `CLAUDE.md:14`: "each flag's full text is in [`docs/runtime-flags.md`](docs/runtime-flags.md)".
- `grep -n "SKILL_COMMANDCODE" draft/docs/runtime-flags.md | wc -l` returns `0`.
- The row itself is correct and is a real improvement: `skills_discovery.py:52` `COMMANDCODE_ROOTS = os.environ.get("SKILL_COMMANDCODE_ROOTS", "1") != "0"`, it is in `ENGINE_ENV_KEYS` (`engine_env.py:27`), and ADR-0038 exists. The original AGENTS.md never documented this flag.
- Fix: add a short `SKILL_COMMANDCODE_ROOTS` entry to `docs/runtime-flags.md`, with roots `~/.commandcode/skills` and `<cwd>/.commandcode/skills` (`skills_discovery.py:53-54`), `=0` plus a reindex to revert, and ADR-0038. Otherwise, soften the promise.

**F4. "Default" column for `SKILL_LLM_TRIGGERS` shows OFF, but the committed `.mcp.json` turns it ON.**
- Draft `AGENTS.md:101`: "| `SKILL_LLM_TRIGGERS` | OFF |".
- Tracked `.mcp.json` (`git show HEAD:.mcp.json`), lines 11-12: `"SKILL_LLM_TRIGGERS": "1",` and `"TRIGGERS_MAX": "16",`.
- The draft annotates the same kind of override for `ENFORCER_MULTI_INTENT` ("ON in code, OFF on this machine's Claude Code", `AGENTS.md:88`) but not here. An agent reading "OFF" will assume utterance triggers are not being served, and they are. The original prose said "live deploy uses `16`" but not that the flag ships ON.
- Fix: "OFF in code, ON in the shipped `.mcp.json` (`TRIGGERS_MAX` 16)".

### Low (one-phrase fixes; promotion can carry them, but they are cheap)

**F5. CLAUDE.md overstates what the AGENTS.md table covers.**
- Draft `CLAUDE.md:14`: "every runtime flag, its default, its code and its ADR are in [`AGENTS.md`](AGENTS.md) → *Runtime flags*".
- Two revert toggles from the original CLAUDE.md bullet are missing from draft AGENTS.md:
  - `ENFORCER_ANNEX_COMPLEMENT`: `enforcer.py:164` `ANNEX_COMPLEMENT = os.environ.get("ENFORCER_ANNEX_COMPLEMENT", "1") != "0"`. Its `=0` restores the ADR-0047 margin rule.
  - The alias `ENFORCER_EXTERNAL_OFFER`: `enforcer.py:122` `os.environ.get("ENFORCER_EXTERNAL_OFFER", "1")) != "0"`.

  The table does note the matching alias for `ENFORCER_JEV_GATE`.
- Fix: add `ENFORCER_ANNEX_COMPLEMENT` to the `ENFORCER_EXTERNAL_ANNEX` row and name the alias, or say "every on/off flag; tuning knobs are in docs/runtime-flags.md".

**F6. `ENFORCER_ANNEX_DYNAMIC` row understates what the flag controls.**
- Draft `AGENTS.md:85`: "Sizes the foreign annex by score margin from the installed top (0.08, cap 2)."
- Code `enforcer.py:149`: `EXTERNAL_SLOTS = int(os.environ.get("ENFORCER_EXTERNAL_SLOTS", "4" if ANNEX_DYNAMIC else "2"))`. Setting `=0` also halves the external annex default from 4 to 2.
- Fix: append "; also sets the external annex default (4, or 2 when off)".

**F7. The preamble claims something three rows contradict.**
- Draft `AGENTS.md:63`: "Each flag turns one behavior on or off with one variable, and setting it to its off value restores the behavior before that change."
- Draft `AGENTS.md:93`: "`=0` stops only the autostart; there is no earlier behavior to restore."
- `ENFORCER_JEV_BENCH` (`AGENTS.md:80`) is not an on/off switch. It is an ordered list of tiers (`enforcer.py:2177`).
- `ENFORCER_DETERMINISTIC`'s row also carries "The keep-off map is consent-only." (`AGENTS.md:78`). Keep-off is not governed by that flag. It is read from `~/.claude/skill-concierge/keep-off.json` and gated by `approved_by_user` (`enforcer.py:914-918`). Putting it in this row suggests the flag controls keep-off.
- Fix: preamble "Most flags … (exceptions noted in the row)". Then move the keep-off sentence to its own line under the table.

**F8. "Before any I/O" overstates two rows.**
- Draft `AGENTS.md:77`: "skips before any I/O; band `harness_skip`." Draft `AGENTS.md:90`: "before any I/O, never in subagents."
- The full text (`runtime-flags.md`, carried verbatim from the original) says the skip is "before the refusal guard, consult route, embed and every Qdrant call". The route is "BEFORE any embed/retrieve I/O". Both legs still write a ledger row (band `harness_skip`, kind `consult_route`).
- Fix: "before any embed or Qdrant I/O".

**F9. `ENFORCER_JEV_BENCH` row: jevd replaces the bench only when it holds keys.**
- Draft `AGENTS.md:80`: "A running jevd named by `JEVD_URL` supplies the ladder instead."
- Code `enforcer.py:2174`: `if jevd is not None and any(t["keyed"] for t in jevd):   # a jevd without keys must not switch Jev off`. The full text says: "A jevd that holds no keys leaves the variable below in charge".
- Fix: "A running jevd that holds keys …".

**F10. Two inaccuracies carried over from the original into invariant 1.**
- Draft `AGENTS.md:67`: "All five reindex paths (`auto_reindex.py`, `auto_flywheel.py`, `flywheel.py`, `doctor.py`, `setup.sh`) forward from that one list."
  - A sixth path also exists: `scripts/trigger_filter.py:649-651` `def reindex():` … `subprocess.run([sys.executable, str(ROOT / "scripts" / "engine_env.py"), "--exec", str(ss_bin),` with `"--reindex"]`.
- Same line: "lists every engine setting that shapes the index**: the trigger layers, every harness-root flag, `SKILL_CONCIERGE_CATALOG_ROOTS` and `SKILL_SYNCED_ROOTS`."
  - The actual list (`engine_env.py:19-34`) also holds the store and embedder keys (`SKILL_QDRANT_URL`, `SKILL_EMBED_MODEL`, …), the plugin-enablement keys (`SKILL_PLUGIN_FILTER`, `SKILL_INSTALLED_PLUGINS`, …) and the sidecar paths (`SKILL_CONCIERGE_NEXT_SKILLS`, `SKILL_META_PATH`). The colon makes an incomplete list read as complete.
- Neither problem is new; both are in the original text. The trim is a good moment to fix them: "Every reindex path (…, `trigger_filter.py reindex`)" and "including the trigger layers, …".

### Pre-existing, not introduced by the draft (report only)

- **P1.** `docs/runtime-flags.md` (`ENFORCER_JEV_ROUTER` entry, verbatim from the original) lists "`TYPESAFE_API_KEY` set, no named deterministic route" as a condition for the router to run. Since the bench, keys are per tier (`enforcer.py:2193-2201`: `ENFORCER_JEV_KEY`/`FLYWHEEL_LLM_API_KEY` for `gw`, `CMD_API_KEY` for `cc`). That condition looks stale. UNVERIFIED whether some other code path still requires `TYPESAFE_API_KEY` for the router; I did not trace the router entry gate end to end.
- **P2.** `vendor/skill-search/skill_search/ports.py:23` says "see AGENTS.md's \"Runtime flags\" / the port-agreement test suite for the full caller list". Neither the original nor the draft Runtime-flags section names any port caller, so the pointer was already stale.

## Load-bearing content no longer visible by default (point 2)

Context first. In this session Claude Code loaded both `CLAUDE.md` and `AGENTS.md` for this repo by default (seen in my own context), so the compact table is visible by default. Codex reads `AGENTS.md`. Neither docs file is loaded by default.

Nothing was lost outright. Every line of the original sections exists in the new docs, and every token from the old CLAUDE.md bullet exists somewhere in the four files (build check 2). What changed is visibility. The items below are rules or preconditions an agent can act against without editing code, so the draft's trigger "read a flag's entry there before you change its code or its default" (`AGENTS.md:63`) does not reliably send the agent to them:

- **L1. Keep-off consent procedure.** The full text says "saved only by `scripts/build_keep_off.py --apply` after Thinh's yes". The default view now keeps only "The keep-off map is consent-only." Partly mitigated: the script's own usage line says "--apply  save the list, marked approved_by_user — run only after Thinh said yes to that list" (`scripts/build_keep_off.py:14`).
- **L2. Precondition and security invariant for enabling `SKILL_SYNCED_ROOTS`.** The full text says "Ships OFF until `doctor` shows every harness cache ≥`0.48.0`" and "never on the `anthropic-skills:` name alone". The table row gives neither. `README.md:430` still sends readers to "(see AGENTS.md → Runtime flags)" for this.
- **L3. Change discipline for the consult route.** The full text says "widen `_CONSULT_RE` only from replayed evidence". This is a rule about editing code, so the existing trigger does cover it.
- **L4. Machine facts for the Jev bench.** The full text says "on this machine it is set in `~/.config/harness-env.sh`" (verified: `harness-env.sh:85`, `cc:` tier first) and "The Command Code and DSH adapters kill the enforcer at 2.5 s and pass `ENFORCER_JEV_BUDGET=1.6`, so the `cc` tier is skipped there" (verified: `adapters/commandcode/skill-concierge.mod.ts:85-86`, `adapters/dsh/skill-concierge.dsh.ts:152-153`). Draft `AGENTS.md:70` turns the first fact into an instruction: "Set `ENFORCER_JEV_BENCH` and `SKILL_TRIGGER_JEV_FILTER` in `~/.config/harness-env.sh`, so every harness and the detached `auto_flywheel` see them." It no longer says the bench IS set there with Command Code first. The table's "unset = `ts:<ENFORCER_JEV_MODEL>`" can mislead someone reasoning about live router behavior.
- **L5. `vendor/skill-search/` re-vendor instruction.** The original layout bullet said the body-trigger patch must be re-applied on any re-vendor. That now sits only in `docs/repository-layout.md:10`. Mitigated: `VENDORED.md` mentions the body-trigger patch (3 matches for `_extract_body_triggers|body-derived|ADR-0016`), and the compact bullet says to record every patch there.

Recommended pointer fix: widen the trigger in `AGENTS.md:63` to "before you change a flag's code or default, flip it in any env, or reason about its live behavior". Add "(L2 precondition: …)" to the `SKILL_SYNCED_ROOTS` row. Restore "on this machine set in `~/.config/harness-env.sh`, `cc` first" as a fact in the machine-local line.

## Link resolution (point 3)

PASS. All 120 relative links across the four files resolve from their final repo paths (counts above). The two links between the new docs and AGENTS.md / CLAUDE.md are correct. Two follow-ups for promotion, neither of which is a broken link:
- `README.md:430` "(see AGENTS.md → Runtime flags)" still resolves, through the table and its link. Pointing it straight at `docs/runtime-flags.md` would be more direct.
- `driftcheck.json` `paths_exist` does not list the two new docs files. Adding them would catch an accidental deletion.

## Contradictions (point 4)

- Draft AGENTS.md against itself: the preamble against the `SKILL_OWNER_AUTOSTART` row and the non-switch `ENFORCER_JEV_BENCH` (F7). The "full text for each flag" promise against `SKILL_COMMANDCODE_ROOTS` (F3).
- Draft CLAUDE.md against draft AGENTS.md: "every runtime flag … are in AGENTS.md" against the missing `ENFORCER_ANNEX_COMPLEMENT` / `ENFORCER_EXTERNAL_OFFER` (F5). CLAUDE.md:17 "Repo layout, full conventions, and guardrails are all in [`AGENTS.md`](AGENTS.md)." is now only partly true, since per-file layout detail moved to `docs/repository-layout.md`. AGENTS.md links to it, so this is a mild issue.
- Where they agree: `ENFORCER_MULTI_INTENT` machine trial (CLAUDE.md:14, AGENTS.md:70 and :88), versioning list, scratch dirs (doc-parity OK), openwiki guard and graph notice text (unchanged), epoch rule (unchanged).

## What I did not check

- Prose in `docs/runtime-flags.md` against code beyond what the table rows needed. That file is a verbatim move, so its claims are as accurate as the original's. I sampled them only where a table row compresses them, which is how I found P1.
- Whether `CHANGELOG.md`, a version bump, or an openwiki update is needed when this doc-only change is promoted. That is the repo's release convention; I did not judge it.
- I ran no tests, `doctor.py` or `driftcheck.py` against a promoted tree. The build's parity checks ran against the draft only.

## Unresolved questions

1. Should the "Default" column show the code default or the shipped/deployed value? F4 and `ENFORCER_MULTI_INTENT` currently use different conventions. My pick is code default plus a "shipped/this machine" note wherever they differ, because that is what the `ENFORCER_MULTI_INTENT` row already does.
2. Should the compact table list every revert toggle (F5) or only top-level features? My pick is to list `ENFORCER_ANNEX_COMPLEMENT` inside the `ENFORCER_EXTERNAL_ANNEX` row. It is a real one-variable revert that the old CLAUDE.md surfaced.

Status: DONE_WITH_CONCERNS
