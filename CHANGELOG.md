# Changelog

All notable changes to **skill-concierge**. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); this project is pre-1.0 and evolving.

## [Unreleased]

## [0.24.0] — 2026-08-24

### Added
- **Dual-harness Codex parity (ADR-0033).** skill-concierge now installs and governs in Codex
  as a first-class harness, not just Claude Code.
  - **Codex skill discovery:** the retriever indexes `~/.codex/skills` and
    `~/.codex/plugins/cache/**` alongside the Claude roots, under distinct `codex-personal` /
    `codex-plugin` / `codex-project:{root}` scopes — one shared Qdrant collection, no
    cross-harness point pruning. Codex cache hits are unfiltered (config.toml is TOML, not
    stdlib-parseable on the 3.10 floor); kill-switch `SKILL_CODEX_ROOTS=0` restores Claude-only
    discovery byte-identically (a reindex prunes the codex points).
  - **Codex plugin manifest:** new `.codex-plugin/plugin.json` (skills + mcpServers + interface;
    no hooks field — the validator rejects it, hooks are auto-discovered from
    `hooks/hooks.json`, same format and `${CLAUDE_PLUGIN_ROOT}` expansion). `.codex/hooks.json`
    mirrors the repo-dev openwiki commit gate for Codex sessions.
  - **Chain-hint mirror:** `enforcer.py`'s `_visible_sidecar_names` reads the codex scopes, so
    `next-skills:` chains fire for Codex-scope skills.
  - **Hermetic fixtures:** vendored-test conftest pins the Codex seams (and imports after the
    env-pinning block — `skills_discovery` reads seams at import time; the July branch's three
    failing tests now pass on machines with a populated `~/.codex`).
  - **Codex openwiki gate fails open:** the `.codex/hooks.json` parity-hook command carries a
    file-existence guard — a Codex session with `CLAUDE_PROJECT_DIR` unset no longer
    exit-2-blocks every Bash call (mirrors the `.claude/settings.json` wiring).

## [0.23.0] — 2026-08-23

### Added
- **External catalogs first-class in the per-turn offer (ADR-0032).** External catalog skills
  (ADR-0031) are promoted from the search-only tier to an **additive annex** in the enforcer
  offer — discovered by intent-match, at near-zero resident cost (the offer is an on-demand
  query, not the resident skill listing; mass-installing would blow the 3% listing budget).
  - **Zero displacement (hard invariant):** the installed offer is produced by the UNCHANGED
    installed query (`must_not tier=external`, limit `TOP_K`) — byte-identical whether the
    annex is on or off. A SEPARATE `_retrieve_external` query supplies the annex, so an external
    can never take an installed slot. (Two small queries beat one widened query, which would
    silently drop installed skills when externals ranked high.)
  - **Quota + floor:** at most `ENFORCER_EXTERNAL_SLOTS` (2) externals annex, only those
    ≥ `ENFORCER_EXTERNAL_FLOOR` (0.40, higher than installed's 0.18) — most turns show zero;
    the annex appears only on strong intent-match (the injection-surface safeguard). Rendered
    as a distinct `[external:<alias>]` block with the `get_skill` read-inline instruction.
  - **Usage-promotion (`hooks/scripts/auto_promote.py`, SessionStart):** an external skill used
    across ≥ `PROMOTE_MIN_TAKES` (3) DISTINCT sessions auto-graduates to a real installed skill
    via `catalogs.py promote` (symlink). Organic curation — the resident set grows only by
    demonstrated usage, never mass install. Idempotent, throttled, kill-switch `PROMOTE_ENABLED=0`.
  - **Telemetry:** the `offer` ledger event gains `ext`; `analyze.py` reports external annex
    offers + external offer→take session-conversion, distinct from installed, epoch-scoped.
  - **Kill-switch `ENFORCER_EXTERNAL_ANNEX=0`** restores ADR-0031 search-only exactly.
  - Enforcer selftest cases 10 (installed query byte-identical) + 11 (annex query/floor/slots/
    render/kill-switch); `auto_promote.py --selftest`; `analyze.py` external-annex case.

## [0.22.1] — 2026-08-23

### Fixed
- **doctor flywheel coverage no longer counts external catalog skills as "missing
  utterances."** `_indexed_skill_names()` (`scripts/doctor.py`) now excludes
  `tier: external` points, matching the flywheel/trigger generators that skip externals
  by design (ADR-0031). Without this, a registered catalog made doctor report every
  catalog skill as a permanent false coverage gap (e.g. "1604 missing"); it now reports
  only genuinely-uncovered installed skills. Also cleans the trigger-hygiene scan, which
  shares the same enumerator. Surfaced by validating the 0.22.0 deploy.

### Added
- **External catalog roots — multi-catalog retrieval without import (ADR-0031).** Third-party
  skill collections (e.g. a cloned awesome-skills repo of 1,600 skills) are now indexable for
  semantic retrieval **without installing anything** and at **zero per-turn context cost**.
  Eleven owner decisions from a design interview 2026-08-23; highlights:
  - Operator-owned config `~/.claude/skill-concierge/catalog-roots.json`
    (`{alias: {path, include?, exclude?}}`, env seam `SKILL_CONCIERGE_CATALOG_ROOTS`); absent
    file = byte-identical behavior. Engine discovery folds catalogs in LAST (installed name
    always wins; a promoted symlink's catalog twin is suppressed by realpath), names minted
    `<alias>:<dirname>`, scope `catalog:<alias>` wired into `visible_scopes()` (machine-wide;
    root removal prunes via the existing scope mechanism).
  - **Search-only tier:** every catalog point carries `tier: external`; the enforcer's per-turn
    retrieval excludes the tier with one `must_not` (selftest case 10), so externals never
    enter the offer preview. `search_skills` merges them into the ranking marked
    `external: <alias>` + a `get_skill` consumption note (no `/command` — nothing installed).
  - **Consumption both ways:** read-inline via `get_skill` (payload-path fast lookup), or
    explicit promotion `catalogs.py promote <alias>:<name>` (symlink into `~/.claude/skills`,
    refuses collisions, broken promotions reported by `list` and doctor).
  - New management surface: `scripts/catalogs.py` (list/add/remove/promote, `--selftest`) +
    `skill-concierge:catalogs` skill; doctor gains a `check_catalogs` probe (missing root paths
    WARN). First registered catalog: `antigravity` (1,603 skills).
  - **Telemetry:** ledger logs `get_skill` deep pulls (PostToolUse matcher extended);
    `analyze.py` reports external takes split by catalog alias. Epoch note: window external
    metrics from this deploy.
  - **Exclusions by design:** skillOverrides generation skips catalog scopes (no dead budget
    entries), the next-skills sidecar skips them (chain hints are preview-layer), and the
    flywheel/trigger generators skip `tier: external` points — the utterance layer for
    externals is an explicitly deferred phase, not dropped.
  - SKILL-FIRST doctrine: external hits are `USING:`-eligible via the get_skill read-inline
    path (same take-bar; alias marks provenance, not a lower obligation).

## [0.21.3] — 2026-08-20

### Changed
- **Operator-owned chain overrides (ADR-0030, `hooks/scripts/enforcer.py`).** Owner-reported
  critical flaw in ADR-0029's authoring model: `next-skills:` frontmatter lives in the SKILL.md
  upstream owns — an AgentKit upgrade or `/plugin marketplace update` rewrites the file and the
  next reindex silently wipes every curated chain ("GONE without anyone noticed"). Fix: chains
  for third-party skills are curated in `~/.claude/skill-concierge/next-skills-overrides.json`
  (flat `{name: [successors]}`, same durable-home pattern as keep-on), merged READER-SIDE in
  `_visible_sidecar_names()` — the sidecar's only consumer — so no engine patch, no reindex
  coupling, none of the ADR-0026 env-forwarding gap class. Override-wins per name, `[]`
  suppresses, fail-open; catalogue-membership + keep-off filters still apply to override
  successors. Absent file = byte-identical behavior; `--selftest` case 9b pins override-wins /
  dangling-drop / keep-off / suppress / absent-file / malformed-file.
- **8 ak workflow chains seeded in the overrides file.** brainstorm→plan→cook→test→code-review→
  ship→journal plus debug→fix→test (from the agent-playbook router study,
  `plans/reports/study-260820-2250-agent-playbook-router-portability.md`); all loaned frontmatter
  lines in `~/.claude/skills/ak-*` reverted — upstream files pristine, hints verified firing from
  overrides alone with a clean sidecar. `enforcer.py` changed → new ledger epoch.
- **`skills/setup/SKILL.md` declares `next-skills: skill-concierge:doctor`** — activates when
  the 0.21.3 cache materializes on `/plugin marketplace update` + reindex.

### Fixed
- **Keep-on router-guard false gap (prior session's fix, now shipped).** The guard warned about
  a bare `skill-search` entry that no longer exists as a catalogue name; `config/keep-on.json`
  drops it and `apply-overrides.py`/`keep-on.py` accept the namespaced `*:skill-search` form.
  Ships with the 08-07 allowlist proposal + journal and the 260820-0027 plan dir.
- **Dead "ADR-0030" citations retracted** (README / CHANGELOG / openwiki): the drafted
  clause-split number never issued; the real ADR-0030 is the chain-overrides decision above.

## [0.21.2] — 2026-08-20

### Changed
- **Enforcer timing + latency telemetry (`hooks/scripts/enforcer.py`).** Embed cap `0.20s -> 0.35s` (hook budget is `5s`, so the extra `150ms` is cheap) to cut the `65%` fallback rate where turns fell mute with no candidates. Every `offer` ledger event now carries `embed_ms`/`qdrant_ms` so `scripts/analyze.py --latency` can histogram per-epoch latency without guessing. Probe on this epoch: `embed 64ms p90 ~64ms`, `qdrant 13ms` — shim is healthy, timeout was the culprit. Wire-through covers `fallback`/`getaway`/`intent_skip`/`offer`.
- **Flywheel `max_tokens` `2048 -> 4096` (`scripts/flywheel_llm.py`).** Private gateway `api.thinhkhuat.com/deepseek-v4-flash` (confirmed permanent) was truncating `22` generations with `finish_reason=length`; the larger window lets the JSON schema close cleanly.
- **Menu breadth `TOP_K` `10 -> 6` (`.mcp.json`).** Aligns with the code default (`server.py:79`); cuts choice overload behind the `88%` offered-turn dodge (`analyze.py` `574/656`).
- **Chain hint `ak-plan -> ak-cook` (`~/.claude/skills/ak-plan/SKILL.md` `next-skills:`) + reindex.** Sidecar now `3` non-empty chains (`verify->handoff`, `doctor->flywheel`, `ak-plan->ak-cook`); complements the prior incremental win (`389` indexed, `1` changed -> `688` embedded / `5146` skipped vs full rebuild).
- **`scripts/analyze.py --latency`.** Histogram + `50ms` bucket view over `embed_ms`/`qdrant_ms`, epoch-windowed via `--since`/`--until`.

### Fixed
- **Overrides drift `-24` stale `caveman:*` keys** (`config/keep-on.json` vs `~/.claude/settings.json`) cleared via `apply-overrides.py`; `doctor.py` `status: OK` (was `WARN`). `39 on / 350 name-only`, no drift.



## [0.21.1] — 2026-08-19

### Fixed
- **SKILL_TRIGGERS pinned to the durable home (`.mcp.json`) + flywheel `_engine_env` forwards
  all 7 trigger-layer keys.** Audit finding: every automatic reindex built WITHOUT the
  utterance layer (the engine default path points into the versioned plugin cache, absent
  for the deployed venv), so the SessionStart auto-reindex pruned ~2-4k utterance points and
  the next env-corrected run re-embedded nearly everything — a prune/rebuild flip-flop across
  three call sites (auto_reindex, setup.sh, and flywheel's own post-generate reindex).
  Incremental core and flywheel scoping were proven sound by identical-env probes
  (embedded:0 / skipped:all). The path is ABSOLUTE, not ${HOME} — the raw literal survives
  only Claude Code's MCP launcher, not the json.load readers.

### Added
- **`skill-concierge:doctor` declares `next-skills: skill-concierge:flywheel`** — first live
  ADR-0029 authoring (the third-most-frequent observed successor in the ledger chains).

## [0.21.0] — 2026-08-19

### Added
- **Next-skill chain hints (ADR-0029) — engine-side skill chaining.** Skills can declare optional
  `next-skills:` frontmatter (comma/space successor names, catalogue ids exactly). The indexer
  writes a scope-keyed sidecar `~/.claude/skill-concierge/next-skills.json`
  (`{scope: {name: [successors]}}` — per-scope MERGE so concurrent sessions cannot
  last-writer-wins each other, ADR-0028's incident class; atomic `os.replace`; every indexed
  skill keyed so key presence doubles as catalogue membership), and the enforcer appends one
  `CHAIN-HINT:` candidate line to EVERY inject-bearing leg (ranked mandate, mandate-only
  fallbacks, all three AUTHORIZED-SKIP lines) when this session used a skill (auto OR
  slash-manual) within 15 min — a bounded 64KB ledger tail-read, zero new network, zero new
  state files. The hint bypasses nothing: successors are filtered through keep-off (ADR-0011
  outranks any resurfacing path) and catalogue/scope membership, and never enter the candidate
  set. ≤3-word turns stay hint-free (the ADR-0010 pre-gate injects nothing — documented limit).
  `ENFORCER_CHAIN_HINT=0` reverts byte-identically; `ENFORCER_CHAIN_TTL_S` (900) tunes the
  window. Doctrine gains a Red-Flags row (a hint is a preview, not a mandate). Vendored patch
  recorded in VENDORED.md — re-copy the venv engine + reindex to deploy (done: sidecar live
  with 413 keys). Pinned by `tests/test_chain_hint_e2e.py`, the enforcer selftest §9, and
  `test_parse_skill_next_skills_list`.
- **`ledger.py` sub-stamp.** `auto`/`manual` events carry `"sub": true` when the hook input
  has an `agent_id` (ADR-0020 positive proof), so subagent lanes are excluded from chain
  state and chain metrics instead of steering the main session's hint.
- **`analyze.py --chains`.** Cross-turn chain view over existing ledger events: per-session
  skill sequences (sub rows excluded, consecutive repeats collapsed, built-in slashes filtered
  via the live catalogue), successor bigrams, length histogram, longest chains — same
  `--since`/`--until` epoch-windowing as the uptake report. First live run: 130 sessions with
  skill use, 67 with chains (len ≥ 2); top pairs `verify-as-claimed → session-handoff` (×4),
  `skill-concierge:doctor → skill-concierge:flywheel` (×3), longest 15-deep.

### Cut
- **Multi-intent clause-split decomposition (drafted number never issued; the later ADR-0030 is a different decision) — cut on dual review,
  owner-ratified.** Per-intent retrieval already exists (`extra_queries` MAX-pool fusion;
  doctrine rule 2 now says so explicitly); the drafted enforcer-side mechanism failed its
  budget math beyond the embed leg (3 retrieves + up to 6 intent-gate POSTs under serial
  100ms caps) and would have been a fourth default-off limb.

## [0.20.8] — 2026-08-07

### Fixed
- **The engine-drift message named a cause it could not observe, and ruled out the remedy that
  usually works.** One symptom — the manifest was written by a different engine build — hides two
  causes with opposite fixes: a server still live on the old build (only a **restart** helps; a
  reindex writes our build and that server hands the mismatch straight back), or a manifest merely
  left over from the previous release (a **reindex** re-stamps it and clears). The text asserted
  the first — *"a live MCP server is on a different build … reindexing will not fix it"* — while
  **every engine upgrade lands in the second**, because changing the engine necessarily changes
  the build id. Seen on 0.20.7's own deploy: doctor printed `Running engine: 3 servers publish no
  build id` directly above `Retrieval health: a live MCP server is on an older build; restart
  (reindex will not fix it)` — two rows of one pass contradicting each other, one blaming the
  wrong remedy. An engine process can see its own build and no other process, so both emitters
  (`_staleness_warning`, `_health`) now state the observation, name **no** remedy, and route to
  doctor — which holds the live-server records and decides.
  **They must not swing to the opposite error either, and the first draft did.** Offering "run
  `reindex()`" reads as an instruction to the *model*: `_staleness_warning` rides in every
  `search_skills` reply, and `reindex()` is an MCP tool that runs **inside the very process whose
  build is in question**. Build ids are unordered md5 hashes, so a server cannot tell whether its
  own build is the newer or the older one — and if it is the older one, reindexing there re-embeds
  with the stale parser and re-stamps the manifest **backward**, flip-flopping against the
  session-start rebuild. The deleted "reindexing will not fix it" had been the only brake on that.
  Both emitters now say plainly not to reindex from the suspect process. Caught in adversarial
  review before release. Pinned by `test_drift_text_never_rules_out_a_reindex`,
  `test_drift_text_never_orders_a_reindex_from_the_suspect_process`, and
  `test_drift_text_never_asserts_a_live_old_server`.
- **`_write_manifest` truncated a file that a live server reads concurrently.** The SessionStart
  reindex rewrites the manifest while a server may be reading it; a plain `write_text` truncates
  first, so a reader could parse nothing and report "no index manifest — never indexed" on a
  perfectly good index. Write-then-`os.replace` now, matching the server records.
- **`doctor --selftest` mutated real state.** It called the live `_running_engine_state()`, which
  spawns the engine, scans `ps`, and **deletes files from `~/.cache/skill-search/servers/`** — a
  diagnostic self-test with side effects on the thing it diagnoses, and one that could hang on the
  un-timed subprocess. Everything in that assertion is stubbed now: 2.43s → 0.15s, records dir
  untouched.
- **doctor's `Running engine` row could report a server population its own classification never
  saw.** It scanned `ps` a second time for the row's count, after the classification had already
  scanned it — so a server starting or dying between the two calls put the count and the
  drift/unknown split out of step. One scan per pass now, with the live list carried alongside
  the classification it produced.

### Changed
- **doctor decides the drift remedy instead of relaying the engine's guess.** It holds the
  live-server evidence in the same pass, so `_drift_remedy` resolves which of the two causes
  applies and prints only that one — naming the specific pids. When the fleet is proven entirely
  on the current build it also becomes auto-fixable (`fix="reindex"`), so `doctor --fix` clears a
  leftover manifest. That is the **only** state that auto-fixes: a live server on an older build,
  an unproven fleet, and absent evidence all stay `fix=None`, because auto-reindexing past a live
  old server is the v0.20.6 defect re-armed. Any **other** issue in the same report (Qdrant
  unreachable, an embedder dim mismatch) also drops the auto-fix and is surfaced alongside —
  firing a reindex into a broken store repairs nothing and hides the real fault.
- **`_running_engine_state()` returns a named tuple, and the seam it feeds is tested.** The shape
  grew a `live` field mid-change and every consumer had to be renumbered by hand; named fields make
  that class of mis-wire impossible. The seam itself — `check_engine_health` handing the right
  fields to `_drift_remedy` — is now pinned by a stubbed `_selftest` case, after review reproduced a
  plausible mis-wire that reported "pid 11, 22 still run an older build" on a **clean** fleet with
  the selftest green: the same failure shape this release exists to retire, one layer up.
- **The two per-pass caches are cleared from one place** (`_reset_pass_caches`, called at the top
  of `run_all()`), and `_selftest` now asserts the **wiring** rather than the helper: it drives the
  real `run_all()` with a probe check that records what a check actually observes. The previous
  assertion called the reset helper directly and stayed green while `run_all()` referenced a
  renamed function — verified with a negative control, which fails as intended when the reset call
  is removed.

## [0.20.7] — 2026-08-07

### Fixed
- **doctor's `Running engine` check accused every live server after a routine `setup.sh`.**
  0.20.6 added the check to catch a server executing an engine build older than the one on
  disk. It answered that question with timestamps: each process's start time (from
  `ps -o etime=`) against `max(st_ctime, st_mtime)` of the venv engine's `*.py` files. But
  `setup.sh` re-copies the engine on EVERY run — it is idempotent by design — so those
  timestamps advance even when the bytes do not move. The first deploy of 0.20.6 proved it
  within minutes: engine content unchanged (`server.py` md5 identical before and after), mtime
  pushed to 23:30:54, a server started 23:28:43 → three servers flagged, while the engine's own
  `health()` correctly reported `stale: false`. Two diagnostics of the same fact, disagreeing.
  The check now compares **build identity**, which moves only when the code moves. Each MCP
  server publishes the build it runs to `~/.cache/skill-search/servers/<pid>.json` at startup
  (`SKILL_SERVER_RECORDS`), and doctor looks it up instead of inferring it. A no-op re-copy is
  invisible here by construction. `started_at` in each record guards pid reuse — a dead
  server's leftover record can no longer lend its build to whatever process inherits the
  number, which would have been the same false accusation one layer down. CLI runs are
  excluded by their flags: a `skill-search --reindex` can run for minutes and matches the same
  binary path, but writes no record, so counting it would report a permanent unknown-build
  server that is really just a busy reindex. Fail-open (N/A) against an engine too old to
  publish an id, so upgrading doctor ahead of the venv reports nothing rather than everything.
  Pinned by `doctor.py --selftest` (`_classify_servers`, `_parse_server_lines`).
  Adversarial review of the fix itself caught three more instances of the same class before
  release, each now pinned by a selftest case: a record naming **no** build (the engine's own
  `"unknown"` fail-open sentinel) was reported as *proven* drift, so the remedy — restart — would
  re-derive the same sentinel and never clear it; the pid-reuse guard used a **symmetric**
  time window, but the gap it must absorb is one-sided (a record is stamped after the launcher's
  prelude, which contains the ADR-0018 pip resync — long exactly when a plugin update makes
  drift matter most), so a slow start filed a healthy server as unprovable for its whole life;
  and the unknown-build warning **asserted a cause** ("started before this engine") that four of
  its five paths do not share, sending users to restart on the ones a restart cannot fix.
- **`doctor --fix` could report failure after a successful repair.** The `--health` memo added
  above was module-scoped and never invalidated, so the post-fix re-check — whose entire purpose
  is to observe what changed — replayed the report captured *before* the fix ran. Starting a
  stopped Qdrant container or reindexing a stale index would repair the system, then reprint the
  identical failure and exit 1. The memo is now cleared at the top of `run_all()`, keeping the
  within-pass saving (two checks, one engine spawn) and dropping the across-pass staleness.
  Caught in review before release; pinned by `doctor.py --selftest`.

### Added
- **`SKILL_SERVER_RECORDS` is pinned in `.mcp.json`** and doctor resolves the pin **before** any
  environment variable — inverted from every other seam on purpose. Doctor is reading an artifact
  the *server* writes, and the server's environment is the one `.mcp.json` hands it, so a shell
  export on the reader's side could only split the two: doctor would read an empty directory and
  report every live server as unproven. This repo has shipped that writer/reader split twice
  (`auto_reindex._mcp_env()` v0.16.1, `setup.sh env_run()` v0.20.5). Records are written
  write-then-`os.replace`, since they are read by a concurrent process by design and a truncating
  write would let a reader see a torn file and call the build unknown.

### Changed
- **`health()` publishes `engine_build` on every report, not only under drift.** Which build a
  process runs is a fact about that process, true with or without an index; emitting it only
  when something is already wrong made it a drift flag, so the one reader that needs a *healthy*
  process's build — doctor, measuring every live server against it — could not get it, and
  would have had to re-derive `_engine_build()`'s hashing rule in a second copy free to stop
  agreeing. Shape is unchanged, `{running, index_written_by}`; `index_written_by` is now `null`
  when there is no drift. Consumers must key on `index_written_by`, **not** on the field's
  presence — `doctor.py::_is_engine_drift` does, and mere-presence keying would flag every
  healthy run. Pinned by `test_health_always_reports_running_engine_build` and
  `test_health_reports_running_build_even_without_a_manifest`.

## [0.20.6] — 2026-08-06

### Fixed
- **Frontmatter values were embedded with their YAML scalar syntax attached.**
  `skills_discovery.parse_skill` took the regex capture verbatim, so `description: >-`
  carried the literal `">-"` plus every continuation line's newline and indent into the
  indexed text, and `description: "…"` kept its surrounding quotes. That text IS the base
  vector, so the retriever was scoring skills partly on punctuation. New `_unwrap_scalar`
  handles the three shapes frontmatter uses — block scalars (`|` literal keeps line breaks,
  `>` folded folds to spaces on paragraph boundaries; chomping and indent indicators
  tolerated), quoted flow scalars (quotes stripped, `\"` / `''` unescaped), and plain wrapped
  scalars (newline+indent folded to one space) — and is applied to `description:` **and**
  `when_to_use:`. Still dependency-free: not a YAML parser.
  **Measured on the maintainer's catalogue: 210 of 416 skills carried the leak → 0.**
  Distinct from 0.20.4, which fixed the value TERMINATOR (hyphenated next-keys being
  swallowed); this fixes the value's own syntax. Pinned by
  `tests/test_discovery.py::test_parse_skill_description_unwraps_yaml_scalars`.
  **Deploying needs a FORCED reindex** — the parsed text changes while the file content hash
  does not, so the incremental path skips every skill.
- **A replaced engine under a running server was reported as "disk changed".**
  A long-lived MCP server keeps executing the engine bytes it imported at start. When the venv
  engine is replaced underneath it — a `setup.sh` re-copy, or a repo build overwriting the
  deployed one — that server and every fresh CLI process parse the same `SKILL.md` files with
  DIFFERENT parsers, so they derive different `_disk_signature()` values from an UNCHANGED
  disk. Whichever writes the manifest last hands the other a false `disk changed since last
  index — run reindex()`, for the life of that process; the reindex then hands it straight
  back. Observed three times in one evening while deploying this release's own `_unwrap_scalar`
  change (which moves parsed text by design): the server computed `c197a923` while a fresh CLI
  computed `aa2c4f1d` — same CWD, same env, same manifest file.
  `_write_manifest` now stamps the writing engine's build id (`_ENGINE_BUILD`, hashed at import
  from `server.py` + `skills_discovery.py`; computing it lazily would hash the NEW bytes the
  process is not running and the check would be inert). On a mismatch `health()` reports
  `engine_build {running, index_written_by}`, sets `stale` to `null` — unknowable across
  builds, not false — and names the remedy: **restart**, not reindex. Legacy manifests with no
  `engine` key, and an `"unknown"` sentinel on either side, are never treated as drift.
  Pinned by `tests/test_indexing.py::test_health_reports_drift_not_false_disk_changed`.
- **The commit-gate hooks wedged every Bash call when `CLAUDE_PROJECT_DIR` pointed elsewhere.**
  `.claude/settings.json` ran both guards as `python3 "${CLAUDE_PROJECT_DIR}/scripts/…"` on
  matcher `Bash`. In a session launched from another directory that path does not exist, python
  exits non-zero, and a PreToolUse hook error rejects the tool call — so every shell command in
  this repo failed, including the verification the guard exists to protect. Each script's own
  fail-open never applied, because the script never started. Both now no-op when the file is
  absent and `exec` it otherwise, so exit code and stdout still pass through untouched and the
  gate is unchanged wherever the script exists.

### Added
- **doctor: `Running engine`** — flags live MCP servers that started before the current venv
  engine build, naming their pids. `Engine freshness` compares two files on disk (venv vs
  deployed source) and is blind to the process dimension: a server that started before the
  refresh keeps executing the old bytes, and no amount of re-copying changes that. Reported as
  WARN with **no auto-fix**, because the remedy is a restart — routing it through the reindex
  auto-fixer would clear the CLI-side symptom while the live server stayed broken. Compares
  process start time against `max(ctime, mtime)` of the venv engine (`cp -p`, `rsync -a`,
  `tar -x` and `shutil.copytree` all PRESERVE mtimes, which would date the engine to its build
  time and yield a false all-clear), and runs `ps -A -ww` so BSD width-truncation cannot clip
  the match target when stdout is a pipe.

### Documentation
- **`docs/caveats.md` §16 — the always-on allowlist is a budget, not a list.** Two upstream
  behaviours were silently defeating curated keep-on sets, both confirmed against the official
  Claude Code docs (`skills.md`, `settings.md`) and the 2.1.223 binary:
  (1) **`skillOverrides` does not apply to plugin skills at all** — the resolver returns `"on"`
  for anything plugin-sourced before reading the map, so no key format works; measured 63
  plugin skills ≈ 5,280 tok/turn that only `/plugin disable` can reclaim. `apply-overrides.py`
  still reports "in sync" the whole time.
  (2) **Over budget, descriptions are DROPPED, not truncated** — `skillListingBudgetFraction`
  yields `contextWindow × 4 × fraction`; past it, entries are sorted by
  `usageCount × 0.5^(daysSinceUse/7)` (from Claude Code's own `skillUsage` in `~/.claude.json`,
  not this repo's ledger) and greedily fitted, so a long description loses its slot to a shorter,
  less-used skill. Records the remedy order (trim at source → demote → raise the fraction) and
  the measurement paths (`/doctor`, the `/context` Skills row, `--debug`). Also corrects the
  keep-on skill's timing note: overrides apply on the **next turn**, not the next session.


## [0.20.5] — 2026-07-31

### Fixed
- **`setup.sh` rebuilt the index without the trigger layer the server queries with.**
  `env_run()` forwarded only `SKILL_QDRANT_URL` / `SKILL_EMBED_BACKEND` / `SKILL_EMBED_MODEL`
  from `.mcp.json`, so `--reindex` ran at engine defaults — `SKILL_LLM_TRIGGERS` **off**
  (default `"0"`) and `TRIGGERS_MAX` **12** (server: `1` and `16`). Every setup run therefore
  pruned the utterance points and built a layer composition the query server does not serve.
  Observed: trigger points dropped 4605 → 4520, and the MCP reported `stale: true` with
  "disk changed since last index" on a *freshly built* index — so every `search_skills`
  reply carried a spurious "run reindex()" warning while `dark_skills` and `stale_points`
  were both empty.
  This is the same gap `auto_reindex._mcp_env()` closed in 0.16.1 (ADR-0026); `setup.sh`
  was never updated. It now resolves `SKILL_LLM_TRIGGERS`, `TRIGGERS_MAX`, `SKILL_TRIGGERS`
  and `SKILL_BODY_TRIGGERS` through the existing `read_mcp()` single-source-of-truth helper
  — the same key list `auto_reindex` uses — and exports each only when non-empty, because an
  empty `SKILL_LLM_TRIGGERS` reads as `"" != "0"` and would switch the layer ON by accident.


## [0.20.4] — 2026-07-31

### Fixed
- **Frontmatter values no longer swallow the next key when that key is hyphenated.**
  `parse_skill()` ended a `description:` / `when_to_use:` value at `(?=\n\w+:|\Z)`. `\w` is
  `[A-Za-z0-9_]` and excludes `-`, so a hyphenated key did not terminate the capture and its
  raw key/value line was folded into the value. Common offenders on a real catalogue:
  `user-invocable:` (97), `argument-hint:` (31), `allowed-tools:` (23),
  `disable-model-invocation:` (16), `compatible-tools:` (1).
  The damage was twofold: the polluted text went into the skill listing, and — the part that
  matters — into the text that gets EMBEDDED. A skill vector carrying the literal
  "user-invocable: true" is retrieval noise, so this quietly degraded ranking for every
  affected skill. Measured before the fix: **168 of 356** personal skills polluted, ~6.8k
  characters (~1.7k est. tokens) of frontmatter junk in the index. After: **0**.
  The terminator is now the named `_FM_NEXT_KEY = r"(?=\n[\w-]+:|\Z)"`, shared by both
  patterns so they cannot drift apart. Regression test pins all four offending key shapes.

  **Requires a full reindex** (`--reindex --force`) to re-embed the cleaned descriptions —
  an incremental pass will skip unchanged files and keep the polluted vectors.


## [0.20.3] — 2026-07-30

### Fixed
- **Skill identity is the DIRECTORY name — `skillOverrides` finally apply.** `parse_skill()`
  read frontmatter `name:` and fell back to the directory, with a comment claiming that
  "matches Claude Code rule". It does not: Claude Code identifies a skill by its directory and
  ignores frontmatter `name:` entirely. Verified against a live catalogue — `~/.claude/skills/zread-cli`
  ships `name: zread`, a perfectly valid slug rather than an unparseable one, and Claude Code
  still lists and overrides it as `zread-cli`.
  Every skill whose two names differed therefore had its name-only budget override written under
  a key Claude Code never looks up. The override silently never applied and the skill's full
  description stayed resident in every turn — while `apply-overrides --check` reported
  "in sync, no drift", because it only ever compared its own computed map against itself.
  Measured on a 606-skill catalogue before the fix: **122 skills mismatched** (121 personal,
  1 plugin), **~9.6k est. tokens** of description resident per session, and **21 of 32** curated
  `keep-on` entries silently unmatched ("not present on this machine"). After: 0 mismatches,
  all 32 keep-on entries resolve.
  Regression test added covering all three shapes seen in the wild — a valid slug that simply
  differs (`zread` / `zread-cli`), a legacy namespace (`ak:plan` / `ak-plan`), and a spaced
  display name (`Excel Analysis` / `excel-analysis`).

### Changed
- `driftcheck.json` no longer mirrors the version into `.codex-plugin/plugin.json`. That file is
  part of the in-flight dual-harness work and is not in this release; the declaration had been
  committed ahead of the file, leaving the drift guard red at HEAD. The dual-harness branch
  restores it.
- `README.md` version badge and Status lead corrected — both had been bumped to `0.21.0` ahead
  of the release they describe.


## [0.20.2] — 2026-07-17

### Added
- **`doctor` now audits junk ALREADY AT REST in the utterance layer** (`Trigger hygiene`).
  0.20.1 stopped a degraded model from *writing* junk; nothing audited what earlier runs had
  already stored. Found in the wild immediately after: 5 skills held empty strings, one-char
  noise and a phrase repeated three times, written by a degraded model before the write-side
  filter existed.
  The reason it hid so well is the load-bearing part: **coverage measures presence, not
  validity.** A skill whose utterances are all junk still has a non-empty `llm_triggers`
  block, so it counts toward `N/M skills have utterances`, never appears in the "missing"
  list — and the generator then skips it *forever* (cache-hit + layer present). A green
  `467/467` was hiding junk. The check re-runs `clean_triggers()` over each live skill's
  stored layer and WARNs when the layer would not survive generation today; the junk
  definition is imported, never restated, so the check cannot drift from the generator.
- **`doctor --fix` purges junk utterance layers.** Drops the poisoned layer (keeping any
  prose layer), clears the skill's generation-cache key, and reindexes — backing up
  `eval/triggers.json` first. It deliberately does **not** regenerate: doctor never calls the
  LLM. Purging IS the repair — a purged skill falls back to description+body retrieval (no
  worse than junk phrases pointing the wrong way) and, with the cache key gone, the next
  flywheel run rewrites it properly instead of skipping it as already covered.
  Known limit, unchanged from 0.20.1: this is a *mechanical* junk filter. Semantically-wrong
  but well-formed output (a degraded model echoing the prompt's own example vocabulary) still
  passes — utterance quality depends on a healthy endpoint, and no check substitutes for that.

## [0.20.1] — 2026-07-17

### Fixed
- **The flywheel could never reach an uncovered skill.** `auto_flywheel` runs
  `flywheel.py --generate --limit 25`, but `llm_triggers.run()` / `llm_eval_gen.run()` sliced the
  *alphabetically sorted full skill list* to `limit` **before** filtering out the skills that were
  already covered. The first 25 names alphabetically were all covered, so every capped run spent its
  entire budget on no-ops and reported `generated=0` while 29 skills sat with no utterances —
  permanently, no matter how often the hook fired. The cap now applies **after** filtering to
  work-needed skills (measured on the live index: 0/25 → 25/25 slots doing real work). This restores
  the behaviour `openwiki/architecture/enforcement-gate.md` already documented ("generates for just
  those"); the docs were right and the code never matched them.
- **`doctor` reported `0/467` utterance coverage on a fully-covered install.** `check_flywheel()`
  read `ROOT/eval/triggers.json` while every other tool honours the `SKILL_TRIGGERS` env seam. Run
  from the plugin cache — which has no `eval/` — it read an absent file, took the empty set as
  "nothing covered", and contradicted the last-run record it printed on the same line. It now honours
  `SKILL_TRIGGERS`, and reports **"coverage unknown"** (WARN) when the file is missing or unreadable
  instead of miscounting: an absent file is not evidence of zero coverage.
- **A degraded local model could poison the live index.** `validate_reply()` only checked "a list of
  ≥4 strings", so a model that had gone off the rails passed schema validation with empty strings,
  one-character noise (`'>'`, `'Đ'`) and the same phrase repeated — and those merged into
  `triggers.json` and were reindexed into retrieval. The Vietnamese-parity retry made it worse:
  pressed for Vietnamese, a degraded model echoed the literal words `'tiếng Việt'`, which then
  counted as a Vietnamese trigger and satisfied the retry. Validation now runs on *cleaned* phrases
  (`clean_triggers()`): empties, sub-4-character noise, low-variety strings, duplicates and that VN
  echo are dropped before both the count check and the merge. Known limit: this catches malformed
  junk, **not** semantically-wrong-but-well-formed output (a degraded model echoing the prompt's own
  example vocabulary still passes) — utterance quality still depends on a healthy endpoint.

### Added
- **`git commit` is gated on openwiki parity** — a `PreToolUse(Bash)` hook (`scripts/openwiki_parity_guard.py`,
  wired in `.claude/settings.json`) **denies** the agent's `git commit` tool call when `openwiki/quickstart.md`
  names a different version than `.claude-plugin/plugin.json`, or when any relative link under `openwiki/` is
  broken. Version parity is delegated to `driftcheck.py` (the wiki's `**Version:**` line is registered as one
  more mirror) rather than reimplemented, so there is no second checker to drift against. Matches on `Bash`, not
  `Bash(git commit*)`, so the compound `git add . && git commit` cannot bypass it. Fails open on internal error;
  `OPENWIKI_GUARD=0` overrides. A stale wiki gets read as authoritative — the commit is the checkpoint.
- **Graph-staleness NOTICE on `git commit`** — a second `PreToolUse(Bash)` hook
  (`scripts/graph_staleness_notice.py`) reports which **git-tracked** files have moved ahead of
  `graphify-out/manifest.json`, using graphify's own `detect_incremental()` rather than a second staleness
  definition. It **warns and never blocks**, and never emits `permissionDecision` (an `"allow"` there would
  auto-approve every commit and silently disable the permission prompt). Deliberately not a deny: `graphify-out/`
  is gitignored so a stale graph never ships, and doc refreshes cost LLM calls — a gate must be proportionate to
  the harm and the cost of the fix. Scoped to tracked files because graphify indexes scratch dirs that churn every
  turn, and a warning that always fires is one you learn to ignore. `GRAPH_NOTICE=0` overrides.
- **graphify post-commit / post-checkout hooks** (`graphify hook install`) — auto-rebuild the knowledge graph's
  code layer (AST only, no LLM) after each commit. Doc changes are deliberately ignored by that hook; the notice
  above covers that gap.

### Changed
- **`graphify-out/` is gitignored scratch** — the knowledge-graph build (`graph.json`, `graph.html`,
  `GRAPH_REPORT.md`, per-file extraction cache) is derived output, rebuildable from source. Added to the
  tool-state line in `AGENTS.md` / `CLAUDE.md` / `openwiki/operations.md` (kept in parity by
  `scripts/check_doc_parity.py`).
- **Flywheel generation model set to `gemma-4-12b-it-qat-optiq`** via `FLYWHEEL_LLM_MODEL` in
  `~/.claude/settings.json`. This **reverses the 0.20.0 swap to `gemma-4-e4b-it-qat-optiq`** on
  reliability grounds, not on retrieval quality: the e4b model degraded mid-run, emitting junk and
  then regurgitating the system prompt's own example words (`triage`/`sort`/`backlog`/`incoming`)
  as triggers for unrelated skills. 0.20.0's measured case for e4b (MRR `0.231 → 0.462`) is **not**
  refuted here and no re-measurement was run — this is an operational fix for an endpoint that was
  producing unusable output. The code default in `scripts/flywheel_llm.py` is deliberately left at
  e4b; the env var is the live seam and overrides it.

## [0.20.0] — 2026-07-10

### Changed
- **Flywheel generation model is now `gemma-4-e4b-it-qat-optiq`** (was `gemma-4-12b-it-qat-optiq`).
  Set it via `FLYWHEEL_LLM_MODEL`; the code default in `scripts/flywheel_llm.py` follows. Measured on a
  full `--generate` pass (408 skills, 0 errors) plus a 20-probe held-out retrieval eval scored 433-way
  offline against both trigger sets: MRR `0.231 → 0.462`, mean rank `56.6 → 13.1`, top-3 `5/20 → 13/20`.
  Prompt compliance improved too — triggers/skill `7.70 → 9.05`, Vietnamese phrases/skill `2.32 → 3.33`.
  False-fire pressure on true-negative chit-chat queries did **not** rise (mean max-score `0.545 → 0.525`).
  Caveats: on the 14 like-for-like probes (skills both models wrote triggers for) 7 improved and 5
  regressed (`come-clean` 1→7, `git-commit` 9→22); the headline MRR gain is partly carried by 6 newly
  added skills that previously had no utterances at all. `precision_eval.py` could not adjudicate this
  swap because the same run regenerated `eval/scenarios`, making it circular.

### Fixed
- **A truncated completion no longer silently drops a skill from the utterance layer.**
  `flywheel_llm.chat()` read only `choices[0].message.content` and never inspected
  `finish_reason`; its retry loop fires on HTTP 503 alone. So a completion cut short at
  `max_tokens` surfaced as an opaque `JSONDecodeError`, which `llm_triggers.run()` catches with
  a bare `except`, prints `WARN`, and skips — costing that skill its triggers with no signal
  beyond a stdout line. `chat()` now raises `TruncatedCompletion` on any explicit
  `finish_reason != "stop"` (an *absent* field is tolerated: some OpenAI-compatible gateways
  omit it, and absence is not evidence of truncation). The guard keys on the field, never on
  whether the body parses — a `length` cut can leave syntactically valid but semantically short
  JSON that `json.loads` accepts happily. Regression tests: `tests/test_flywheel_llm_truncation.py`.

  Root cause, reproduced and independently validated: LM Studio enforces `json_schema` strictly,
  `pattern` and `minItems` included. A regex the model is unlikely to satisfy (e.g. requiring a
  Vietnamese character while the prompt asks for English) masks the string-closing quote until
  that obligation is met; the model emits non-quote characters until the token cap. Confirmed on
  `gemma-4-e4b-it-qat-optiq` and `gemma-4-12b-it-qat-optiq`. It is **not** unicode-specific — an
  ASCII regex requiring a digit reproduces it — and **not** a broken grammar: the same regex with
  a Vietnamese prompt returns valid JSON at `finish_reason: stop`. The live SCHEMA carries no
  `pattern`, so this was dormant, not active. Analysis:
  `plans/reports/library-fit-evaluation-260710-1634-chonkie-outlines-recommendation-report.md`.
- **The `FLYWHEEL_LLM_MODEL` code default pointed at a model no endpoint serves.** It was
  `gemma-4-12b-it-optiq`; the LM-Studio host serves the `-qat-` variant (`gemma-4-12b-it-qat-optiq`).
  Any machine that never set the env var was configured against a non-existent model. README and
  `references/flywheel-llm-providers.md` documented the same dead default.
- Module docstrings in `flywheel_llm.py`, `llm_eval_gen.py`, and `llm_triggers.py` still described a
  "LAN Qwen client"; Qwen was dropped as the generator well before this swap (32% Vietnamese coverage).

## [0.19.1] — 2026-07-09

### Fixed
- **The global override map is no longer built from a CWD-scoped view.** `skillOverrides` lives in the
  global `~/.claude/settings.json`, but `discover_skill_names()` fed it from `discover_skills()`, whose
  project dir is `Path.cwd()/.claude/skills`. A map computed in one project and a map computed in
  another differ by that project's skills, so each session saw the other's keys as drift and rewrote
  the global file — churning a backup every time. This is the same failure the index had before
  [ADR-0028](docs/adr/0028-multi-session-index-scoping-and-installed-plugin-filter.md): a CWD-scoped
  view driving a globally shared artifact. Project-scoped skills are now excluded; the map is
  identical from every CWD (verified: 427 names from three different working directories).

### Notes
- `doctor`'s `-121 stale` override warning in 0.19.0 was **not** an `auto_overrides` bug. The hook runs
  the *installed* plugin copy, which at 0.18.1 had no installed/enabled plugin filter and so discovered
  548 skills — no drift from its own vantage point. It heals on its own once `/plugin update` lands
  0.19.x. The stale keys were pruned here (548 → 427; the 32 keep-on entries preserved).

## [0.19.0] — 2026-07-09

Concurrent Claude Code sessions each run their own MCP server against one shared Qdrant collection.
They were quietly deleting each other's project skills, and the index described plugin versions
nobody had installed. See [ADR-0028](docs/adr/0028-multi-session-index-scoping-and-installed-plugin-filter.md).

### Fixed
- **Sessions no longer prune each other's skills.** `SKILL_DIRS[1]` is `Path.cwd()/.claude/skills`, so
  every session saw a different skill set, while `build_index()` deleted any indexed point absent from
  *its* view. A reindex from one project reported `"deleted": 32` and wiped the project points another
  had just written; last writer won, forever, on a 30-minute hook throttle. Points now carry an owning
  `scope` (`personal` | `plugin` | `project:<root>`), `_prunable()` deletes only within
  `visible_scopes()`, and `search_skills` / `_indexed_names` filter to them. Verified live: a reindex
  from a foreign CWD reports `deleted: 0` and leaves all foreign project points intact.
- **Only the installed, enabled plugin version is indexed.** The plugin cache is append-only: 587
  `SKILL.md` collapsed to 256 unique `(plugin, skill)` pairs, 89 of them served by multiple versions
  and resolved by arbitrary glob order. `skill-concierge:doctor` was being scored against its **0.3.0**
  description while **0.18.1** was installed (31 versions cached), and `superpowers:*` was recommended
  while `enabledPlugins` had it `false`. `_installed_plugin_roots()` now reads Claude Code's own
  `installed_plugins.json` + `enabledPlugins`. **Fails open** (unreadable manifests → unfiltered cache
  + warning); `SKILL_PLUGIN_FILTER=0` reverts. Index: 548 → 427 skills, nothing invocable lost.
- **`health()` stops false-alarming.** It diffed a CWD-scoped disk view against the shared index and
  reported another project's skills as `dark_skills` — the alarm that invited the destructive reindex.
- **Per-project index manifest.** `_disk_signature()` is CWD-scoped but the manifest was one global
  file, so sessions overwrote each other and all reported a permanent `skills changed on disk since
  last index`. `META_PATH` → `index_meta-<md5(PROJECT_ROOT)[:8]>.json`; `SKILL_META_PATH` still wins.
- **`auto_flywheel` no longer arms its throttle against a stale index.** It and `auto_reindex` fire
  detached and unordered; coverage measured before the reindex lands reports a false `0 missing`, and
  stamping on that silenced the flywheel for 6h — a dozen new skills went a whole morning without
  utterances while the hook ran exactly as written. It now defers **without stamping**, and fails open
  on unknown counts.

### Changed
- **Utterance prompt v2 (ADR-0026 layer).** v1 asked for phrases "a user might type **to invoke this
  skill**", which primed the model to restate the description: ~1.0 against queries that already echoed
  the skill name, 0.5731 against a real paraphrase. Measured on the live embedder, long first-person
  sentences score *worse* (0.34–0.50 each); short phrases with **deliberately different vocabulary**
  score **0.7558** and take rank 1. The lever is vocabulary distance, not sentence-likeness.
- **`PROMPT_VERSION` namespaces the utterance cache key.** It hashed only the skill description, so a
  prompt rewrite regenerated nothing. Bumping it invalidates the cache; `auto_flywheel` regenerates
  `AUTO_FLYWHEEL_MAX_PER_RUN` (25) per session rather than one long GPU burn.

### Added
- `tests/test_auto_flywheel.py` — first tests for the hook layer (stale-index deferral, fail-open).
- Engine tests for scope tagging, scope-bounded pruning, installed/enabled filtering, and a regression
  guard pinning `SKILL_DIRS` to a **non-recursive** glob (a `**` there would walk the whole project
  tree — 6,334 `SKILL.md` under `CLONED/` on the dev machine).

## [0.18.1] — 2026-07-09

### Fixed
- **Flywheel regen cache moved to the canonical durable home.** `.flywheel-cache.json` now resolves to
  `~/.claude/skill-concierge/.flywheel-cache.json` (`SKILL_CONCIERGE_HOME`,
  [ADR-0025](docs/adr/0025-autonomous-override-freshness-and-keep-on-management.md)) instead of
  `ROOT/eval/` — the versioned plugin cache dir that `/plugin update` wipes. A cache under the ephemeral
  dir went cold after every update, so the next run treated all ~530 skills as cache-misses and
  regenerated the whole catalogue against the local LLM. `flywheel_llm.py` now owns the path
  (`CACHE_FILE`), shared by both generators (`llm_triggers.py`, `llm_eval_gen.py`).

## [0.18.0] — 2026-07-08

Flywheel Phase 2 ([ADR-0027](docs/adr/0027-flywheel-first-class-multi-provider.md)): the "just works"
auto-flywheel + a first-class slash surface. Utterances now flow to new skills automatically, with a
readable audit trail, and every skill-concierge slash command shows its argument hint.

### Added
- **`auto_flywheel` SessionStart hook** (`hooks/scripts/auto_flywheel.py`): when a LLM endpoint is
  configured **and** reachable, it detects skills missing utterances, generates for just those, and
  reindexes — **detached/non-blocking**, throttled (`AUTO_FLYWHEEL_THROTTLE_S`, default 6h), per-run
  capped (`AUTO_FLYWHEEL_MAX_PER_RUN`, default 25), gated `SKILL_AUTO_FLYWHEEL` (**default ON**), fully
  fail-open (unconfigured/unreachable → silent no-op → description+body fallback).
- **Global run manifest** (`~/.claude/skill-concierge/flywheel-manifest.json`, `scripts/flywheel_manifest.py`):
  every run (auto or manual) records timestamp, endpoint+model, per-skill status, totals, coverage,
  last error (last 20 runs). Any agent or user can read what the background flywheel did. Surfaced in
  the flywheel skill's status output and in `doctor`.
- **Smart `--generate`**: runs BOTH scenarios + triggers for new/changed skills (each generator
  content-hashes the description); `--triggers-only` skips the measurement-only scenario pass;
  `--limit <N>` caps skills per pass.
- **Namespaced slash commands + argument hints on all six skills**: `name: skill-concierge:<skill>` +
  `user-invocable: true` + `argument-hint` (the ClaudeKit pattern) so the hint surfaces on the
  `/skill-concierge:<skill>` form the menu shows (fixes the bare-`name:` hint-invisibility, CC #22063).

### Changed
- `doctor` `check_flywheel()` now also reports the last flywheel run from the manifest.

## [0.17.0] — 2026-07-08

Retrieval flywheel promoted to **first-class** ([ADR-0027](docs/adr/0027-flywheel-first-class-multi-provider.md)).
The utterance layer (ADR-0026) was the biggest 0.16.x gain but was buried behind a manual,
single-endpoint generation step. Now it's multi-provider, visible in `doctor`, and self-service via a
menu skill. The graceful fallback (no utterances → description+body) is unchanged — first-class is not
mandatory.

### Added
- **Multi-provider flywheel LLM routing** (`scripts/flywheel_llm.py`): `FLYWHEEL_LLM_API_KEY`
  (optional `Authorization: Bearer` → any OpenAI-compatible gateway) and `FLYWHEEL_LLM_SCHEMA_MODE`
  (`json_schema` | `json_object` | `off`, for endpoints that don't honor strict schemas), plus a
  `ping()` reachability preflight. Covers LM-Studio, Ollama (`/v1`), and 3rd-party gateways — see
  `references/flywheel-llm-providers.md`.
- **`skill-concierge:flywheel` skill** (`skills/flywheel/`): menu-visible. Status mode (default,
  read-only) shows endpoint health + per-skill utterance coverage; `--generate` runs the incremental
  generator (only new/changed skills call the LLM) then reindexes, gated on a live `ping()`.
- **`doctor` flywheel check** (`scripts/doctor.py` `check_flywheel()`): read-only, fail-open — reports
  configured? / reachable? / coverage (which skills lack utterances), so the flywheel is discoverable.

### Deferred (proposed, not shipped)
- The "just works" `auto_flywheel` SessionStart hook (auto-generate utterances for new skills when a
  LLM endpoint is configured + reachable), mirroring `auto_reindex`. Designed in ADR-0027 / the plan;
  Phase 2 pending operator green-light.

## [0.16.1] — 2026-07-08

### Fixed
- **Utterance layer was unstable across reindexes** ([ADR-0026](docs/adr/0026-llm-utterance-trigger-layer.md)):
  the detached SessionStart `auto_reindex` hook forwarded only the embedder/store keys from `.mcp.json`,
  so it rebuilt the index at engine defaults (`SKILL_LLM_TRIGGERS` off, `TRIGGERS_MAX` 12) and pruned the
  utterance points on every run. `hooks/scripts/auto_reindex.py` `_mcp_env()` now also forwards
  `SKILL_LLM_TRIGGERS`, `TRIGGERS_MAX`, `SKILL_TRIGGERS`, `SKILL_BODY_TRIGGERS` so the indexer builds the
  same index the query server serves. Found by the v0.16.0 go-live verification.

## [0.16.0] — 2026-07-08

LLM-utterance trigger layer landed live ([ADR-0026](docs/adr/0026-llm-utterance-trigger-layer.md)).
An offline free-local-LLM flywheel generated per-skill natural-utterance trigger phrases (532/532
skills, 100% bilingual EN+VN); these now feed the multivector index as MAX-pooled trigger points,
lifting retrieval recall without diluting the base vector. The generative model never touches the
≤300ms enforcer hot path — it runs offline at generation time only.

### Added
- **LLM-utterance trigger source** (`vendor/skill-search/skill_search/server.py` `_trigger_phrases`,
  behind `SKILL_LLM_TRIGGERS`, default OFF = byte-identical): layers the offline-generated utterance
  phrases (`eval/triggers.json` `llm_triggers` block) FIRST in the MAX-pool trigger layer, ahead of
  description- and body-derived phrases, deduped and capped COMBINED at `TRIGGERS_MAX` (raised to 16
  in the live deploy so utterances add slots rather than evict). Mirrors ADR-0016's engine-only fold;
  `build_triggers.py` carries a sync note. [VENDORED.md v0.16.0].
- **Flywheel generators** (`scripts/flywheel_llm.py`, `llm_eval_gen.py`, `llm_triggers.py`): offline
  LM-Studio client producing the per-skill eval corpus (`eval/scenarios-shadow/`) and utterance-trigger
  layer. Strict `json_schema`, thinking-off. Generated data is gitignored (regenerates from the scripts).

### Changed
- **`scripts/precision_eval.py` ranks skills, not points** — `search()` now uses `group_by name`
  MAX-pool (`/points/query/groups`), mirroring the live engine, so the shadow-vs-live gate measures
  skill-rank correctly on the multivector index (a raw point-search inflated rank/floor/crowding).

## [0.15.0] — 2026-07-06

Autonomous `skillOverrides` freshness + seamless keep-on management
([ADR-0025](docs/adr/0025-autonomous-override-freshness-and-keep-on-management.md)). Closes the
gap the 2026-07-06 name-only audit exposed: the retrieval index self-healed but the settings
budget never did, so newly installed skills leaked their full description on every turn until
someone re-ran apply-overrides. Additive, default-ON; no retrieval-scoring change (epoch anchor untouched).

### Added
- **Autonomous override self-heal** (`hooks/scripts/auto_overrides.py`): a SessionStart hook
  mirroring `auto_reindex.py` (fail-silent, throttled `AUTO_OVERRIDES_THROTTLE_S`=1800, detached)
  that reconciles `~/.claude/settings.json` `skillOverrides` **only when the discovered catalogue
  drifted** — the name-only budget stays fresh with zero human discipline, and a no-op session
  never rewrites settings or churns a backup.
- **`apply-overrides.py --check / --if-changed`**: `--check` reports drift and exits 1 without
  writing (the read-only detector); `--if-changed` reconciles only on real drift (the hook path).
  Shared compute-diff core; all existing safety (backup, atomic write, refuse-empty) preserved.
- **`scripts/keep-on.py` + the `keep-on` skill**: view / add / remove the always-ON allowlist
  (`config/keep-on.json`); add/remove re-apply the overrides immediately. The seamless surface
  for curating what stays fully-described vs name-only.

### Changed
- **`doctor` now detects override drift.** `check_overrides()` was existence-only — the blind
  spot that hid the 42-skill leak. It now runs `apply-overrides.py --check` and WARNs
  (auto-fixable) when the override map has drifted from the installed catalogue.
- **Single canonical durable home — `~/.claude/skill-concierge/`.** All state that must survive a
  `/plugin update` now lives under one user-owned dir, resolved in `scripts/_keepon.py`: the
  keep-on allowlist (`keep-on.json`, seeded once from the shipped default), the engine venv
  (`venv/`, was `~/.local/share/skill-concierge/venv`), and the ledger/logs/stamps (`logs/`, was
  `~/.claude/skill-telemetry/logs`). Supersedes the storage paths in ADR-0004/0006.
  **One-time deploy step:** the update carrying this needs a single `setup` run — it copies the
  old ledger over and rebuilds the venv at the new home (a venv can't be moved); after that the
  self-heal is normal.

## [0.14.1] — 2026-07-06

### Fixed
- **Chronic false `disk changed since last index` — root-caused and fixed** ([ADR-0024](docs/adr/0024-staleness-detector-content-not-mtime.md)).
  `doctor`'s retrieval-health check FAILed constantly and every `search_skills` warned stale, cleared only
  briefly by a reindex. Cause: the staleness detector (`server.py:_disk_signature`) fingerprinted
  `(path, mtime)` while reindex skips on `_content_hash` — so any mtime-only event (`/plugin update`
  re-materializing the version-pinned cache dirs, a re-clone, `touch`, a formatting-only save) tripped
  "stale" forever, and a reindex only masked it by rewriting the mtime snapshot. Fix: `_disk_signature`
  now fingerprints CONTENT (deduped skill name + `_content_hash`), the SAME signal reindex uses, so the
  detector stops false-firing and the all-cached-versions path churn (852 paths) collapses to the deduped
  indexed set (~530). Deploy runs a reindex (rewrites the manifest signature into the new content format).

## [0.14.0] — 2026-07-06

Anti-dodge integration — five superpowers-derived mechanisms fold anti-skip **doctrine craft** + a
**measurement loop** into the enforcement layer. Full arc + accepted caveats:
[`docs/anti-dodge-integration-v0.14.md`](docs/anti-dodge-integration-v0.14.md). Each ships default-ON
behind a one-var revert, with a selftest and an ADR.

### Added
- **H5 — over-fire authorized-skip lane** (`ENFORCER_SELFREF_SKIP`, default-ON): a narrow self-referential
  lane so the gate stops forcing pointless `search_skills` on trivial recap turns, guarded by a
  whole-prompt task-verb veto ([ADR-0019](docs/adr/0019-over-fire-lane-and-gate-legibility.md)).
- **H3 — subagent session-scoping** (`SKILL_SUBAGENT_STOP`, default-ON): `doctrine.py` suppresses
  injection inside subagents via the hook payload's `agent_id`; the audit excludes subagent/dispatch
  transcripts from the usage denominator ([ADR-0020](docs/adr/0020-subagent-session-scoping.md)).
- **H1 — rationalization harvest loop**: the audit captures verbatim false-skip rationalizations
  (scrubbed, gitignored) to feed doctrine, keeping `_skip_verdicts` pure
  ([ADR-0021](docs/adr/0021-rationalization-harvest-loop.md)).
- **H2 — Red Flags table**: `skill-first.md` rule-6/4 rationalizations rendered as a symptom→refutation
  table ([ADR-0022](docs/adr/0022-red-flags-rationalization-table.md)).
- **H4 — trigger-purity lint** (`SKILL_TRIGGER_PURITY`, shadow default / inert at release): rejects
  workflow-summary phrases from the MAX-pool trigger surface; ships shadow-only
  ([ADR-0023](docs/adr/0023-trigger-purity-lint.md)).

### Changed
- The `SKILL-CHECK` cross-file contract now recognizes the H5 SELFREF signature; count-side and
  harvest-side share one `_AUTHORIZED_SIGNATURES` tuple (anti-drift).

## [0.13.1] — 2026-07-05

Deploy-flow fix — the MCP engine can no longer go stale after a plugin update.

### Fixed
- **Self-healing launcher: `/plugin update` now refreshes the MCP engine automatically**
  (`bin/skill-search-mcp`, `setup.sh`, [ADR-0018](docs/adr/0018-self-healing-launcher-engine-resync.md)).
  The stable venv holds a COPIED engine (ADR-0004); an update ships new engine code to the cache but
  never touched the copy, so the MCP silently served STALE code until a manual `setup.sh` — exactly
  what left v0.13.0's query fanout dark after `/plugin update` + restart (doctor caught it, ADR-0013).
  Two causes fixed: (1) the launcher now stamps the deployed plugin version and, on a mismatch at
  spawn, resyncs the engine into the venv before exec — O(1) guard on the fast path, once-per-update
  resync, best-effort + fail-open (never blocks the MCP connect), stdout-clean; (2) `setup.sh`
  force-reinstalls the engine (`--force-reinstall --no-deps`), since the vendored package version is a
  static `0.1.0` that made plain `pip install` "already satisfied"-skip the changed copy. Residual: a
  dependency change (not just engine code) still needs a `setup.sh` rerun.

## [0.13.0] — 2026-07-05

Recall upgrades — help the right skill surface when a single conversational query would bury it,
and let the automatic offer show more of what retrieval found.

### Added
- **Query fanout / MAX-pool fusion in `search_skills`** (`vendor/skill-search/skill_search/server.py`).
  The tool now takes an optional `extra_queries: list[str]` — the caller passes 2–3 varied phrasings of
  the same need, the server embeds each and scores every skill by its single best-matching phrasing
  across the union (MAX-pool), so a skill a single phrasing buries still surfaces. Backward-compatible:
  omitting `extra_queries` is byte-identical to the old single-query top-k. Verified live (fusion lifts
  `codebase-onboarding` from below the cut to rank 3) and by new unit tests (`tests/test_fusion.py`).

### Changed
- **Enforcer offer-menu breadth `ENFORCER_TOP_K` default 5 → 8** ([ADR-0017](docs/adr/0017-enforcer-gate-thresholds-v2-widen-offer-menu.md),
  supersedes ADR-0009). A fired offer may now list up to 8 candidates (those clearing `ITEM_FLOOR`).
  Trades more visibility for more push-noise — env-overridable, revert default 5.
- **`search_skills` deployed `SKILL_TOP_K=10`** (`.mcp.json`, was default 6) — a 488-skill catalogue with
  near-synonym clusters needs a wider pull window; the precise skill often ranks 7+.
- **SKILL-FIRST doctrine** (`hooks/doctrine/skill-first.md`) — instruct querying by intent + domain terms
  with 2–3 phrasings via `extra_queries`, not the raw user sentence.

## [0.12.1] — 2026-07-05

Two correctness fixes from a grounded review of the enforcer + ledger, each landed
test-first (failing selftest → fix → green) and independently reviewed.

### Fixed
- **Keep-off suppression can no longer be bypassed by a deterministic route**
  (`hooks/scripts/enforcer.py`, ADR-0011). `_deterministic_hits` now takes the keep-off set
  and skips any route whose skill is keep-off'd, so a chronic never-take skill can't resurface
  at score 1.0 (gate-bypassing) when an operator co-configures a matching route. Both features
  are opt-in/off by default, so this closes a latent interaction, not a live regression. New
  combined selftest case (6b) guards it.
- **Ledger offer→turn join no longer misattributes offers on duplicate prompt-prefixes**
  (`scripts/analyze.py`). The join keyed on `(sid, prompt[:120])` with a plain dict, so two
  turns in one session sharing a 120-char prefix (e.g. a retried "continue") collapsed both
  offers onto the last turn — silently corrupting `hit@k`, offered-turn conversion, and
  per-skill offer→take. The segmentation loop is now a `_segment_windows()` function pairing
  each offer to its own turn in arrival order (`defaultdict(deque)` + `popleft`). New
  dup-prefix selftest case guards it.

## [0.12.0] — 2026-07-04

Usefulness-rate upgrades — surface the verdict the enforcer already computes, and get
each skill's BODY-level "when to use" signal into retrieval. Implements the Opus-validated
proposal `plans/reports/proposal-260704-0244-…`. **Operator directive: everything ships
DEFAULT-ON**, each behind an ON-default env kill-switch (rationale + the ADR-0009 risk this
overrides are recorded in `plans/260704-0415-usefulness-rate-upgrades/decisions-audit-log.md`).

### Added
- **AUTHORIZED-SKIP enforcer tier** (`hooks/scripts/enforcer.py`, ADR-0015). The two silent
  verdict legs (getaway `top<floor`, intent_skip conversational) now inject a one-line
  `SKILL-CHECK:` authorization instead of nothing, so the agent stops re-running
  `search_skills` to re-derive a verdict the hook already made. The getaway line keeps the
  burden of proof on SKIP (escalate real/ambiguous work to `find-skills`; `get_skill` nudge).
  Env `ENFORCER_AUTHORIZED_SKIP` (default ON). Fail-silent, additive.
- **Library doctrine** (`hooks/doctrine/skill-first.md`, ADR-0015). Skip = reasoning-based
  intent classification with asymmetric cost; burden of proof on SKIP; ambiguous/no-fit
  escalates to `find-skills`, never a self-declared skip.
- **Body-derived trigger points** (`vendor/skill-search/…`, ADR-0016). Each skill body's
  labeled decision sections (`## When to Use`, `Triggers:`, `Use when:`) are mined for short
  phrases and folded into the existing MAX-pool trigger layer (previously description-only) —
  separate points, deduped, capped COMBINED at `_TRIG_MAX`. Env `SKILL_BODY_TRIGGERS`
  (default ON). Live reindex added +1339 points (2231→3570). Recorded in `VENDORED.md`.

### Changed
- **skill-usage audit** (`skills/skill-usage-audit/…`) now recognises the `SKILL-CHECK:`
  marker: a hook-authorized skip is tallied as `authorized_skip`, excluded from
  false-SKIPPING, keeping the doctrine's hardest-rule metric honest.

## [0.11.1] — 2026-07-01

Staleness self-guards — make two latent staleness vectors impossible to miss, so freshness
never depends on someone remembering to run a command.

### Added
- **doctor `Engine freshness` check** (`scripts/doctor.py`, ADR-0013). Content-hashes the engine
  COPIED into the stable venv against the deployed `vendor/skill-search/skill_search` source. The
  MCP launcher EXECs the engine from that venv (built once by `setup.sh`, not editable), so a
  `/plugin update` ships new code to the cache but never refreshes the venv copy — the MCP could
  serve STALE engine code while `Engine venv ✓`. A mismatch now WARNs → rerun `setup.sh`. Pinned
  by `--selftest`.
- **SessionStart index self-heal** (`hooks/scripts/auto_reindex.py`, ADR-0014). A detached,
  throttled (`AUTO_REINDEX_THROTTLE_S`, default 1800s), incremental reindex fires on session start,
  so a stale index re-freshens itself — no manual reindex, no reliance on discipline. Fail-silent,
  non-blocking; guarded on engine-present + Qdrant-up.

### Changed
- **doctor** SKILL.md (→ 0.2.0): documents the `Engine freshness` row + the "search behaves like an
  old version after an update" symptom shortcut.
- **caveats §6** downgraded to "self-heals" (auto_reindex); new **§11** documents the stale-engine
  landmine + the `diff -rq` decisive test + the `setup.sh` remedy.
- **README** refreshed to `0.11.1` (badge + status), recent trajectory (`0.5.0`→`0.11.1`) and the
  compliance open-question filled in.

### Fixed
- **Docs staleness:** the ADR index was missing `0011` and `0012` (existed on disk, unlisted) —
  added, along with `0013`/`0014`.

## [0.11.0] — 2026-07-01

Gate-prompt upgrade driven by a 5-day transcript analysis: the SKILL-FIRST gate was
~93% compliant on *form* (the line-1 token) but only ~47% on *behavior*. This release
closes the dominant failure modes and adds the telemetry to keep measuring them.

### Changed
- **SKILL-FIRST doctrine rewritten** (`hooks/doctrine/skill-first.md`):
  - **Task-gated the obligation.** `SKIPPING: none` is now lawful on a genuinely no-task turn
    (harness/system notification, await-only ping, an inbound message that hands you no work)
    *without* a search. The old absolute "every reply, no exception" rule was being routed
    around — most skips classified a real task as "exempt" and skipped the required search.
  - **Named the dodges that are NOT exemptions** — self-confident domain judgment, a prior
    turn's search, "you told me to use <tool>" — and stated that a shown candidate means a
    task is present (the no-task class then does not apply). Hardened the agent-dispatch case:
    dispatching work *to* another agent is itself a task.
  - **`SEARCH:` now requires the `search_skills` call in the SAME reply.** Narrating an
    imagined or earlier search ("Search returned nothing…") is a disguised skip.
  - **Prohibited `USING: none`** — an invalid hybrid token agents were emitting; a no-skill
    outcome is `SKIPPING: none`.
  - Welded the skip-bar to the take-bar (a loosely-adaptable fit is a `USING:`, not a skip);
    replaced the unbacked "no token = no reply" line with a self-imposed-protocol framing.
- **Per-turn enforcer strings trimmed** (`hooks/scripts/enforcer.py` `MANDATE` /
  `_ranked_mandate`) toward the per-turn budget — the reasoning lives in the SessionStart
  doctrine. The candidate %-share is relabeled as RELATIVE rank, not confidence.

### Added
- **False-SKIPPING telemetry** (`skills/skill-usage-audit/scripts/audit_skill_usage.py`):
  per-turn detection of a `SKIPPING` declared with no same-turn `search_skills` call — the
  doctrine's hardest rule — plus a `--selftest`. Reproduces the independent diagnostic (~68%).
- **Substantive-compliance line** in `scripts/analyze.py` (used-or-searched vs pure dodge).

### Notes
- **`config/keep-off.json` unchanged by design.** Re-running the auto-generator over its
  post-enrichment window yields no suppressions: the v0.5.0 enrichment already resolved the
  chronic 0-take offers. Hand-editing the auto-generated map is contraindicated (ADR-0011).

## [0.10.2] — 2026-06-30

### Fixed
- **Plugin skills no longer double-prefixed (`ck:ck:…`).** `skills_discovery._namespaced_name`
  unconditionally prepended the plugin id, so a plugin whose frontmatter `name:` already self-namespaces
  (ClaudeKit ships `name: ck:plan`) was indexed as `ck:ck:plan` — 81 live skills, invisible to anything
  keying the correct `ck:<skill>` name (eval corpus, per-skill τ, search/enforcer display). Now skips the
  prefix when the name already starts with `<plugin_id>:`. A reindex applies it (drops the doubles).
- **Per-skill τ calibration now mirrors live MAX-pool.** `calibrate_thresholds.py` scored each prompt
  against a skill's single `base` vector — no longer matching live retrieval (max over base+trigger
  points). Now takes the max cosine over all of a skill's indexed points, and drops the prior `limit:50`
  fetch truncation. With the double-prefix fixed, the eval corpus resolves 14/14 skills (was 4):
  12 ok · 1 weak · 1 no-signal. Per-skill τ stays default-INERT (`ENFORCER_PER_SKILL_TAU` off) — only
  1 of the 12 ok skills clears the 0.45 floor.

## [0.10.1] — 2026-06-30

### Fixed
- **`setup.sh` no longer corrupts the multi-vector index.** It ran `enrich_index.py --reapply`
  unconditionally; on a multi-vector index that MEAN-enriches (corrupts) the base vectors on top of
  the trigger layer. Now guarded behind `SKILL_MULTIVECTOR=0`, mirroring `doctor`'s `fix_reindex`.
  This mattered because re-running `setup.sh` is REQUIRED to refresh the stable venv after the 0.10.0
  update (the venv holds a non-editable COPY of the engine — ADR-0004), so without the guard the very
  step that activates 0.10.0 would have corrupted the index.

### Changed (docs)
- `doctor` SKILL.md check-matrix: added the Enrichment overlay, Multi-vector layer, and Corpus-health
  rows (the table had drifted behind the actual checks).
- `skill-usage-audit` SKILL.md: caveat that the "cosine anti-correlated with adoption" findings were
  measured on the single-vector index; multi-vector ~doubled separation, so re-measure before reuse.

### Notes
- **Activation reality:** the stable venv at `~/.local/share/skill-concierge/venv` is a COPY, refreshed
  only by `setup.sh` — `/plugin marketplace update` + `/reload-plugins` do NOT refresh it. So 0.10.0's
  new retrieval code reaches the live MCP only after re-running `setup.sh` (now safe) + reloading.

## [0.10.0] — 2026-06-30

### Added
- **Multi-vector MAX-pool retrieval — ADR-0012 (the headline).** Each skill is now indexed as a base
  point (`name+desc+body`) PLUS one trigger point per intent phrase from its description, and scored at
  query time by its single BEST point (Qdrant `query/groups`, `group_by=name`, `group_size=1`). This
  imports the BM25-routing design's MAX-pool mechanism the project had missed (it shipped the opposite —
  a dormant MEAN-centroid overlay). Validated on a shadow A/B: **rank-1 2.2×, top-5 1.8×, separation
  2.2×, false-fire flat**. Live index 500→2312 points; groups query ~2 ms. `build_index` builds the
  trigger layer natively (reindex-safe, per-chunk upsert), with a keyword payload index on `name`.
  Gated by `SKILL_MULTIVECTOR` (default ON; `=0` + reindex reverts to one bare vector per skill).
- **`doctor` checks: Multi-vector layer + Corpus health.** The former counts trigger points (and WARNs
  if `SKILL_MULTIVECTOR` is on but the index has none — silent single-vector degradation); the latter
  surfaces the per-skill calibration `ok`/`weak`/`no-signal` fix-list from `eval/thresholds.json`.
- **Per-skill calibrated τ + deterministic route tier — wired, default-INERT.** `enforcer.py` can gate
  an `ok`-calibrated skill on its own τ (`ENFORCER_PER_SKILL_TAU`) or guarantee an exact-substring →
  skill route (`ENFORCER_DETERMINISTIC`, `config/deterministic-routes.json`). Both OFF by default and
  selftested: on the current compressed-cosine band all 5 `ok`-τ sit below the 0.45 floor, so arming τ
  today would add false offers — recalibrate against multi-vector scores first.

### Changed
- **`analyze.py` offered-turn denominator unified to `band=="offer"` — ADR-0011 Open→Resolved.**
  `_offer_conversion` now counts only actually-SHOWN menus (getaway/intent_skip excluded), matching
  `build_keep_off.py`; the shared band-filter is stamped in build_keep_off's window builder so the two
  can never diverge. The global all-turn `dodge` line is unchanged (still a labelled proxy).
- **Getaway floor kept at 0.45.** A floor sweep showed the multi-vector "flooding" was a 0.20-floor
  artifact; at 0.45 crowd-median is 11 (< bare's 34 @0.20) with 64.9% positive-clear, so no re-tune.
- The legacy MEAN enrichment overlay is superseded by the trigger layer; `doctor --fix` no longer runs
  the reapply step when `SKILL_MULTIVECTOR` is on (it would mean-corrupt base vectors).

### Notes
- **Activation:** the persistent skill-search MCP must restart/reconnect to load the new groups code —
  until then its `search_skills` returns duplicate points on the multi-vector index (the enforcer, a
  per-prompt subprocess, already uses the new code).
- Recall lever is proven; the adoption payoff (offered-turn conversion) needs a post-deployment traffic
  window to judge. Independent code-review: no blockers; tester: all selftests green.

## [0.9.0] — 2026-06-29

### Added
- **Ledger-derived offer suppression ("keep-off" map) — ADR-0011.** `scripts/build_keep_off.py`
  derives chronic never-take skills (offered ≥15, take-rate ≤5%) from a POST-ENRICHMENT clean
  window into `config/keep-off.json`; `enforcer.py` hard-drops those names from the offer menu
  (still search-reachable), fail-open. Reuses `analyze._offer_conversion` and counts only
  `band=="offer"` (actually-shown) menus. Ships INERT — on the current clean window zero skills
  qualify (the never-takers were a pre-enrichment artifact), so `keep_off: []`.
- **Runner-up-gap menu collapse (default-OFF).** `enforcer.py` can collapse the offer to the top
  skill when its raw-score gap over the runner-up ≥ `ENFORCER_DOMINANCE_RATIO` (off unless the env
  is set; %-share never concentrates). Collapse decided in `_apply_dominance` so the ledger logs the
  post-collapse menu.

### Notes
- Both features are behavior-inert on merge. Independent review: SHIP-WITH-FIXES (all applied).
  Auto-regen wiring and the `analyze.py` headline-denominator question are deferred operator
  decisions (see ADR-0011 → Open).

## [0.8.0] — 2026-06-29

### Added
- **Vietnamese support in the actionability gate's imperative-veto.** `_is_imperative` now recognizes
  Vietnamese task prompts — a Unicode+NFC tokenizer that keeps diacritics, a VN single-verb +
  two-syllable-bigram lexicon, and VN polite openers (hãy / xin / làm ơn / vui lòng). It was
  English-only, so Vietnamese commands could be wrongly suppressed by the intent gate. (commit 0b065e0)

### Changed
- **Word floor `MAX_SHORT_WORDS` 5 → 3 — ADR-0010 (supersedes ADR-0009's word floor).** Prompts of
  4–5 words now reach the language-aware veto instead of a silent getaway, so short commands (incl.
  Vietnamese) get skill offers; ≤3-word ultra-short trivia is still skipped. Score floor 0.45 unchanged.

## [0.7.1] — 2026-06-29

### Fixed
- **Docs reconciled with the 0.7.0 runtime.** README "How a request flows" now includes the
  enforcer / doctrine / actionability-gate layer (it described only the pre-0.6 ledger→retrieve→curate
  path); Status 0.4.2→0.7.0; AGENTS.md now lists four bundled skills + the in-generation hook layer
  (was "three skills" / "ledger capture").
- **Gate-knob comments de-footgunned** — `enforcer.py` GETAWAY_FLOOR / MAX_SHORT_WORDS no longer say
  "revert to 0.40 / 2" (which invited silently undoing ADR-0009); they point to the ADR.
- **ADR-0008 timeout reconciled** — note added for the 90ms→200ms relaxation (no decision reopened).
- **`build_prompt_intent.py`** documents the in-sample caveat for threshold tuning.

### Added
- **driftcheck guards the prose that drifted** — README Status is now a version mirror, and a
  `skill-list-parity` command-check asserts AGENTS.md names exactly the on-disk bundled skills.

## [0.7.0] — 2026-06-29

### Added
- **`skill-usage-audit` bundled skill — a *valid* usage-measurement arm.** The invocation
  ledger measures gate compliance (offer→take), which the operator flagged INVALID for
  skill-USAGE analysis. This skill ships the correction beside the ledger that tempts the
  misuse: it routes usage questions to the transcript SKILL-FIRST declaration trail
  (`USING`/`SEARCH`/`SKIPPING`) — the signal that captures inline skill use the ledger and
  the usage-tracker both miss — and bundles `scripts/audit_skill_usage.py` (windowed by
  ship-time, self/meta dogfood sessions flagged, builtin slashes excluded). Auto-discovered
  on install; no manifest wiring needed.

## [0.6.1] — 2026-06-29

### Changed
- **Gate thresholds re-tuned by operator order (ADR-0009), against the data-backed
  recommendation.** `MAX_SHORT_WORDS` 2→5 (pre-gate now skips ≤5-word prompts) and
  `GETAWAY_FLOOR` 0.40→0.45 (an offer needs top cosine ≥0.45). Both floors raised to cut
  perceived offer-noise. The ledger+corpus analysis argued against both: the score floor is
  anti-correlated with adoption (taken offers score lower than dodged), and the word floor
  misses the long-form noise (~93% of it is >5 words) while nicking short commands. See
  ADR-0009 for the evidence and the one-line revert (set 2 / 0.40, or
  `ENFORCER_GETAWAY_FLOOR=0.40`). Behaviour change only; both stay env-overridable.

## [0.6.0] — 2026-06-28

### Added
- **Actionability gate (the headline).** A new per-turn gate in the enforcer suppresses an offer
  when the prompt is non-imperative AND leans CONVERSATIONAL over ACTIONABLE in embedding space —
  the conversational/status/meta turns that clear the relevance floor topically but reliably get
  dodged. Prior-independent class-margin rule (mean top-K cosine to each class over a *balanced*
  `prompt_intent` corpus), tuned to ~2% false-suppression of actionable turns on a held-out
  transcript backtest and validated to fire on out-of-distribution prompts. Fail-OPEN everywhere
  (missing collection / imperative / any error -> offer). Logs a new `intent_skip` ledger band.
  Tunable via `ENFORCER_INTENT_MARGIN` / `ENFORCER_INTENT_K`.
- **`scripts/build_prompt_intent.py`** — reproducible build of the gate's grounding corpus: mines
  the transcript store for (prompt -> agent-action) pairs, labels by outcome (Edit/Write or >=3
  tools = actionable; 0 tools = conversational), balances the classes, embeds via the warm shim,
  and (re)builds the `prompt_intent` Qdrant collection. Stdlib, idempotent, fail-soft (too little
  history -> gate fails-open). Wired into `setup.sh` and `doctor.py --fix`.
- `doctor.py` — "Actionability gate" health check (warns when `prompt_intent` is missing/empty and
  the gate is silently failing-open; auto-fixable by rebuilding).

## [0.5.0] — 2026-06-28

### Added
- **Retrieval enrichment (the headline).** Each skill's indexed vector is now enriched with
  query-style trigger phrases (centroid of the stored vector + per-phrase embeddings), so the
  router discriminates the right skill far better. `scripts/build_triggers.py` derives per-skill
  prose-phrase triggers from each skill's description; `scripts/enrich_index.py` applies them via
  the engine fastembed path with an embed-parity gate (cos=1.0 vs the live index), vector-only
  updates (never payload-wiping upsert), a Qdrant snapshot before any live swap, and
  `--shadow`/`--live`/`--revert`/`--reapply` modes. Measured on the eval corpus: correct-skill
  rank-1 ~12%->30% (prose floor; utterance ceiling ~67%), clears-floor and offer quality up.
- `scripts/precision_eval.py` — full 495-way recall + offer-set crowding gate (cross-skill
  confusion matrix + cross-domain true-negatives).
- `eval/scenarios/` labeled corpus + `scripts/calibrate_thresholds.py` per-skill separation harness.
- **Reindex-safe enrichment re-apply.** `enrich_index.py --reapply` (idempotent; recomputes the
  bare base from source text so it cannot double-enrich) is wired into `doctor.py --fix`
  (reindex -> reapply) and `setup.sh`, so a reindex never silently drops the enrichment overlay.
- `doctor.py` — "Enrichment overlay" freshness check (warns when points are un-enriched after a
  reindex, auto-fixable).
- **Drift guard.** `scripts/driftcheck.py` + `driftcheck.json` verify the version triple
  (`plugin.json` <-> `marketplace.json` <-> latest CHANGELOG), that doc-referenced paths exist, and
  that `CLAUDE.md` and `AGENTS.md` name the same scratch dirs (`scripts/check_doc_parity.py`).

### Changed
- **Enforcer offer floor `GETAWAY_FLOOR` 0.20 -> 0.40**, tuned for the enriched score distribution
  (centroid enrichment shifts cosines up; at 0.20 the enriched index over-offers ~2/3 of all
  skills per query). At 0.40 the enriched index offers a live-comparable set with ~79%
  correct-skill-offered vs ~54% before enrichment.

### Fixed
- `doctor.py` duplicate-MCP false positive: the repo's own root `.mcp.json` (unexpanded
  `${CLAUDE_PLUGIN_ROOT}`, auto-loaded as a project MCP only when CWD is the source repo) was
  miscounted as a second install, and the line parser split namespaced server names on the first
  colon. Now excludes template projections and splits on the name/command separator.
- `.gitignore`: added `.handoff/`, generated `eval/` artifacts (`triggers.json`, `thresholds.json`),
  `.pytest_cache/`, `.env`.

## [0.4.2] — 2026-06-27

### Added
- `scripts/analyze.py` — `--since WHEN` / `--until WHEN` flags window the ledger by event
  time (`WHEN` = epoch seconds or local ISO `YYYY-MM-DD[ HH:MM:SS]`), so before/after
  compares (e.g. around a fix or go-live commit time) no longer need hand-splitting the
  ledger. Prints a `window` header; positional-path and no-flag invocations are unchanged;
  stays stdlib-only. Documented in `README.md`, `AGENTS.md`, and the mental-model doc.

### Fixed
- `README.md` ledger example claimed `hit@k` was "pending (needs offer events)" — stale:
  `offer` events land and hit@k computes. Updated the example line and the note.

## [0.4.1] — 2026-06-27

### Fixed
- **`search` events were never logged (0% across all ledger history).** The PostToolUse
  matcher (`hooks/hooks.json`) and the `SEARCH_TOOL` constant (`hooks/scripts/ledger.py`)
  expected the bare `mcp__skill-search__search_skills`, but the live MCP tool is
  plugin-namespaced `mcp__plugin_skill-concierge_skill-search__search_skills` — so the hook
  never fired on searches, blinding the gate's primary "SEARCH before SKIP" lever. Now matches
  by suffix (`endswith`) + a namespace-tolerant matcher regex, so a future namespace change
  can't silently break logging again.
- `analyze.py` docstring freshened: hit@k computes once `offer` events land (they do), no
  longer "pending".

## [0.4.0] — 2026-06-27

### Changed
- **EFFORT decoupled into its own standalone `effort-gate` plugin.** The EFFORT doctrine was
  promoted to a universal plugin applicable to every task, not just skill selection. Removed
  from skill-concierge: the `EFFORT — STANDING ORDER` section of `hooks/doctrine/skill-first.md`,
  the `EFFORT_TRIGGER` from `hooks/scripts/enforcer.py` (per-turn message is SKILL-FIRST only
  again), with the extraction noted in the mental-model doc as design origin. Division of labor:
  **skill-concierge governs which/whether a skill; effort-gate governs how much work.**

## [0.3.1] — 2026-06-27

### Changed
- EFFORT given co-equal per-turn presence: a shared `EFFORT_TRIGGER` re-asserted its gate every
  turn (run every step, cutting work to "save tokens" forbidden, a cut must be named and halted)
  on both the fallback and offer paths. In-generation only, no detection. (Superseded in 0.4.0,
  which extracted EFFORT entirely.)

## [0.3.0] — 2026-06-27

### Added
- **Caveman-style SKILL-FIRST doctrine gate — the other half of caveman's split.** A SessionStart
  hook (`hooks/scripts/doctrine.py`, mirrors `caveman-activate.js`) injects the rich SKILL-FIRST
  standing order, read at runtime from a single-source doctrine file (`hooks/doctrine/skill-first.md`).
  The per-turn enforcer message was reworded from soft persuasion into a cheap **gate trigger**
  (forced line-1 token; "previewed few don't fit → SEARCH the full index, never skip"). Retrieval,
  fallback, and telemetry paths untouched.

### Notes
- Governance is **in-generation only** — no Stop/PostToolUse detection gate. A post-hoc gate was
  rejected by design because it polices already-spent tokens instead of shaping disposition (the
  anti-caveman). The hard finding driving this redesign: retrieval was never the bottleneck —
  compliance is. See `docs/skill-first-enforcement-mental-model.md`.

## [0.2.1] — 2026-06-26

### Changed
- **Enforcer embed timeout 90ms → 200ms, total per-turn budget ≲150ms → ≲300ms**, and the
  embed shim is now **threaded** (`ThreadingHTTPServer`). Live dogfooding (the plugin's own
  ledger) showed ~60% of real turns were hitting `embed_timeout` → mandate-only: the
  single-threaded shim's mpnet inference, under real in-turn CPU contention (concurrent
  UserPromptSubmit hooks + overlapping sessions), slipped past 90ms even though it's ~18ms idle.
  Threading flattens concurrent embeds (8 parallel: 288ms serial → 65ms wall) and the wider
  budget recovers the semantic candidates on the common path; the hook is non-blocking additive
  context so ~250ms worst-case is imperceptible. Both knobs env-overridable
  (`ENFORCER_EMBED_TIMEOUT` float-seconds, `ENFORCER_QDRANT_TIMEOUT`). See ADR-0008.

## [0.2.0] — 2026-06-26

### Added
- **P1 fusion — semantic skill-enforcement (the headline of 0.2.0).** Retires the lexical
  per-turn enforcement hook and points it at the SAME semantic Qdrant index `skill-search` serves:
  - **Warm embed shim** — `scripts/embed_server.py` (stdlib http.server holding fastembed
    mpnet-768 in memory; `POST /embed`, `GET /health`), shipped as a Docker sidecar next to the
    Qdrant container on `127.0.0.1:6363` (`Dockerfile`, `bin/embed-shim`, `setup.sh`). Reuses the
    engine embed path; `vendor/skill-search/pyproject.toml` pins `fastembed==0.8.0` for index
    parity (cosine 1.000000 verified, EN+VN).
  - **Semantic enforcer** — `hooks/scripts/enforcer.py` (UserPromptSubmit): embed → Qdrant top-k →
    inject mandate + semantic candidates; fail-silent, additive-only, never blocks. Hard ~90ms
    client-side embed timeout → mandate-only fallback on embed/Qdrant down or slow (see ADR-0008
    for the 90ms calibration). Replaces the lexical scorer + `library.json`.
  - **Telemetry** — `scripts/analyze.py` catalogue repointed off `library.json` onto the Qdrant
    index; now reports hit@k / fallback rate / bands from new `offer` events.
  - Go-live: lexical `skill_first_nudge.py` deregistered from `~/.claude/settings.json`; this
    plugin version is the live enforcement layer.
- **Maintenance skills** — `skill-concierge:setup` and `skill-concierge:doctor`:
  - `setup` — wraps the idempotent `setup.sh` bootstrap (stable venv, Qdrant, index,
    overrides) for first-time install and post-update refresh, then verifies with doctor.
  - `doctor` — `scripts/doctor.py`, a pure-stdlib deployment-layer health check with safe
    `--fix` (start Qdrant, reindex, re-apply overrides). Delegates the retrieval diagnostic
    to the engine's own `skill-search --health` so the two never drift.
- `scripts/doctor.py` — the diagnostic engine behind the doctor skill (has a `--selftest`).
- `docs/adr/` — Architecture Decision Records (0001–0006) capturing the design rationale:
  model-invocable-only indexing, the WHICH×WHETHER fusion, embedder/Qdrant choice, the MCP
  launcher + stable venv, the overrides applier, and the compounding ledger.
- `docs/caveats.md` — operational landmines (wrong-universe eval, override-generator nuke,
  Qdrant dependency, python-picker, namespacing, reindex, version sync, logman retention).
- `vendor/skill-search/eval/README-LOCAL.md` — loud note that the vendored eval is calibrated
  to the upstream author's environment and its recall@k is not a quality bar here.
- `CHANGELOG.md`.

### Notes
- Both maintenance skills declare `name:` (matching the directory) so Claude Code registers
  them as `skill-concierge:setup` / `skill-concierge:doctor` — the registration pattern proven
  by the existing `skill-search` skill in this deployment (158/159 installed plugin skills use
  it). Descriptions are single-line because the vendored engine parses frontmatter with a regex,
  not a YAML parser, so a `>-` block scalar would leak into the indexed text.
- The ADR/caveats docs slice documents existing reality; the P1 fusion (above) is the
  behavioural change in 0.2.0 — the enforcement organ moved from the lexical scorer to the
  semantic index. See `docs/plan.md` build log, ADR-0002, and ADR-0008.

## [0.1.2] — 2026-06-26

### Fixed
- Keep the bundled router skill `skill-concierge:skill-search` always-on: added it to
  `config/keep-on.json` (32-skill keep-on policy). Without it a cache `setup.sh` rerun could
  revert the router to `name-only`.

## [0.1.1] — 2026-06-26

### Fixed
- Bundled MCP failed to connect (`-32000` / ENOENT). `.mcp.json` had pointed at a venv inside
  the plugin **cache** (wiped on every reinstall). Now `.mcp.json` points at a launcher
  (`bin/skill-search-mcp`) that execs a **stable** venv at `~/.local/share/skill-concierge/venv`,
  surviving plugin cache wipes. (See ADR-0004.)

## [0.1.0] — 2026-06-26

### Added
- Initial scaffold: plugin manifests, README, `.gitignore`.
- Vendored skill-search MCP engine (MIT · sowhan/skill-search) under `vendor/skill-search/`
  with `LICENSE` + `VENDORED.md` attribution and customization log.
- Router skill `skills/skill-search/SKILL.md`.
- Telemetry ledger: `hooks/scripts/ledger.py` + `scripts/analyze.py` (reviewed + tested).
- Reproduction layer: `.mcp.json`, `setup.sh`, `scripts/apply-overrides.py`,
  `config/keep-on.json`.
- Build plan + ops docs under `docs/`.

[Unreleased]: https://github.com/thinhkhuat/skill-concierge/compare/v0.4.2...HEAD
[0.4.2]: https://github.com/thinhkhuat/skill-concierge/compare/v0.4.1...v0.4.2
[0.4.1]: https://github.com/thinhkhuat/skill-concierge/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/thinhkhuat/skill-concierge/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/thinhkhuat/skill-concierge/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/thinhkhuat/skill-concierge/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/thinhkhuat/skill-concierge/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/thinhkhuat/skill-concierge/releases/tag/v0.2.0
[0.1.2]: https://github.com/thinhkhuat/skill-concierge/releases/tag/v0.1.2
[0.1.1]: https://github.com/thinhkhuat/skill-concierge/releases/tag/v0.1.1
[0.1.0]: https://github.com/thinhkhuat/skill-concierge/releases/tag/v0.1.0
