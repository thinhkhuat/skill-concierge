# Caveats & Landmines — read before operating

The loud list. Each item is a real trap that has bitten (or is one config-slip from biting).
Symptom → cause → what to do. ADRs hold the *why*; this holds the *don't*.

> **Before reading the whole list:** run `skill-concierge:doctor` (or `python3 scripts/doctor.py`).
> It mechanically checks the deployment layer + retrieval health and auto-fixes the common
> ones (§3 Qdrant down, §6 reindex, the overrides applier) with `--fix`. This file is the
> human reference for what doctor can't or won't touch. (ADR-0007.)

---

## §1 — The vendored eval is calibrated to a DIFFERENT machine (do not trust its recall@k)

**Symptom:** `vendor/skill-search/eval/run_eval.py` prints recall@1/@3/@6 ≈ `0.00 / 0.08 / 0.08`.
Looks like the retriever is broken.

**Cause:** `eval/labeled_queries.jsonl` is the **upstream author's** label set. Its expected
answers target skills **not in this index** — both the author's plugins (`gsd-*`,
`superpowers:*`, `claude-mem:*`, `chrome-devtools-mcp:*`) and **built-in slash-commands**
(`loop`, `schedule`, `verify`, `run`, `code-review`, `update-config`, `keybindings-help`).
This engine **deliberately** indexes only model-invocable `SKILL.md` skills (ADR-0001), so
those labels can never be retrieved here. The number measures the wrong universe.

**Do:** Treat the vendored eval as a **harness smoke-test only** (does the pipeline run?), not
a quality bar. For a real number, **relabel** with ground truth drawn *only* from the indexed
catalogue (`get_skill` / `search_skills` to confirm membership; use **namespaced** ids — §5).
A near-zero score here is **not** evidence the embedder is weak.

> This one cost a whole analysis detour. It is the reason the ADRs and this file exist.

---

## §2 — Never run upstream `generate_overrides.py` against this deployment

**Symptom:** the curated always-on set collapses to ~2 skills; overrides appear in
`settings.local.json`.

**Cause:** `vendor/skill-search/skill_search/generate_overrides.py` targets
`~/.claude/settings.local.json` with a **2-item keep-on default**. A rerun nukes the curated
set and writes the wrong file.

**Do:** Apply overrides ONLY via `scripts/apply-overrides.py` (writes `~/.claude/settings.json`,
atomic, backs up, refuses empty keep-on — ADR-0005). Guard/avoid the upstream generator.

---

## §3 — Qdrant must be up

**Symptom:** search/health errors; MCP returns nothing useful.

**Cause:** the engine needs the `skill-search-qdrant` container (`localhost:6333`).

**Do:** `docker ps --filter name=skill-search-qdrant` → expect `Up`. Container is
`--restart unless-stopped`; if absent, `setup.sh` recreates it. In the live fusion, a Qdrant
outage degrades to mandate-only fallback (ADR-0002), not a crash.

---

## §4 — `setup.sh` picks the first `python3.12` — which may have broken `ensurepip`

**Symptom:** `setup.sh` venv creation fails on a fresh machine.

**Cause:** the picker takes the first `python3.12` on `PATH`. On this machine
`~/.local/bin/python3.12` has a **broken `ensurepip`**; the working build used
`/opt/homebrew/bin/python3.12`.

**Do (workaround):** point the build at a known-good interpreter, or pre-create the stable
venv (`~/.claude/skill-concierge/venv`) with brew python, then rerun `setup.sh`.
**Deferred fix:** harden the picker to test `venv`+`pip` per candidate and fall through
(portability-only — the owner's machine already works).

---

## §5 — Plugin skills are NAMESPACED in the index

**Symptom:** `get_skill('worktree')` → not found, even though the skill exists.

**Cause:** plugin-bundled skills are indexed as `<plugin>:<skill>` (e.g. `ck:worktree`),
matching how Claude Code references them (`skills_discovery.py:35-52`).

**Do:** look up / label with the prefix — `get_skill('ck:worktree')`, `ck:deploy`,
`skill-concierge:skill-search`. Personal/project skills keep their bare name.

---

## §6 — `disk changed since last index — run reindex()`

**Symptom:** `--health` reports `degraded`; `search_skills` results carry a
`skills changed on disk since last index` warning.

**Cause:** skill files changed/were re-touched on disk since the last index build
(e.g. after `/reload-plugins` re-attaches skills).

**Do:** **nothing — this now self-heals.** The SessionStart `auto_reindex.py` hook
(ADR-0014) fires a detached, throttled, incremental reindex every session, so a stale index
re-freshens on its own without anyone remembering. Manual paths still exist if you want it
*now*: `skill-search --reindex` (with the `.mcp.json` env), the MCP `reindex` tool, or
`doctor --fix`. Incremental either way: unchanged skills are skipped (`embedded: 0, skipped: N`).
Throttle: `AUTO_REINDEX_THROTTLE_S` (default 1800s).

---

## §7 — Version is the update signal (keep-on drift now self-heals)

**Symptom:** a `/plugin marketplace update` does nothing.

**Cause:** downstream update keys on the version — if `plugin.json` and `marketplace.json`
versions aren't bumped **together**, the update is a silent no-op.

**Do:** bump **both** manifests' versions on any shippable change.

> **The old cache/source keep-on drift is gone (v0.15.0, [ADR-0025](adr/0025-autonomous-override-freshness-and-keep-on-management.md)).**
> The live allowlist no longer lives in the wipe-on-update plugin cache — it is seeded once into
> the canonical home `~/.claude/skill-concierge/keep-on.json`, and the SessionStart
> `auto_overrides.py` hook reconciles `settings.json` whenever the installed catalogue drifts, so
> a new/removed skill no longer leaks its full description until someone re-runs the applier.

---

## §8 — logman will DELETE the ledger after 90 days unless `RETENTION_DAYS=0`

**Symptom (latent):** the compounding invocation ledger loses history after 90 days.

**Cause:** the ledger (`~/.claude/skill-concierge/logs/skill-invocation-ledger.log`) is
designed to compound forever (ADR-0006), but its downstream archiver **logman** defaults to
`RETENTION_DAYS=90`, which **deletes** old archives.

**Do:** when wiring logman to this `logs/` dir, run it with **`RETENTION_DAYS=0`** (unlimited).
The ledger code itself never rotates/caps/deletes — the risk is entirely in logman's default.

---

## §9 — Embed shim must be running (Docker sidecar, `skill-concierge-embed-shim`)

**Symptom:** per-turn latency spikes over budget; enforcer telemetry shows
high `fallback: true` rate in `offer` events.

**Cause:** the warm embedding shim (`scripts/embed_server.py`) runs as a Docker sidecar
(`skill-concierge-embed-shim` container, `127.0.0.1:6363`; overridable via
`SKILL_EMBED_CONTAINER` — `setup.sh:21`). If the container is stopped or
crashed, or the model fails to load in-memory, the enforcer hook hits the 200ms timeout
(`EMBED_TIMEOUT_S`, `enforcer.py:63` — relaxed from 90ms per ADR-0008) and
falls back to mandate-only. The fallback works (never crashes), but enforcement degrades.

**Do:** `docker ps --filter name=skill-concierge-embed-shim` → expect `Up`. Container is
`--restart unless-stopped`, so restart Docker or run `setup.sh` to recreate it.
`skill-concierge:doctor --fix` auto-restarts the container if down. Monitor fallback rate
in `~/.claude/skill-concierge/logs/skill-invocation-ledger.log` (`offer` events with
`fallback: true`); sustained high rate signals a shim health problem.

---

## §10 — This repo is workbench-write-guarded

**Symptom:** an agent's `Write` into `skill-concierge/` is blocked
(`Root-anchoring: artifacts are inert data`).

**Cause:** MY-WORKBENCH treats any dir with its own `.git/` as an inert **artifact** and
blocks writes; the `.ckignore` also blocks Bash commands containing the literal `.git`.

**Do:** the owner's bypass is to rename `.git` → `git` (no-dot) while editing, then back to
`.git` before committing. (Context for agents operating from the workbench root; irrelevant
once the repo is cloned standalone elsewhere.)

---

## §11 — The MCP can serve STALE engine code after a `/plugin update` (venv ≠ cache)

**Symptom:** a plugin update + restart is done, the new version is installed, `doctor` shows
`Engine venv ✓` — yet the MCP *behaves like the old version* (a retrieval/engine fix you
shipped isn't live). `/mcp` shows skill-search connected; nothing looks broken.

**Cause:** the MCP launcher EXECs `skill-search` from the **stable venv**
(`~/.claude/skill-concierge/venv`, ADR-0004), where the engine is **COPIED into
site-packages by `setup.sh` — not an editable install.** `/plugin update` ships new code into
the version-pinned **cache** but **never touches the venv copy**. So the cache is new and the
venv engine is old; the MCP runs the old one. `Engine venv ✓` only proves the bin *exists*,
not that it's *current* — the original blind spot.

**Detect:** `doctor` now has an **`Engine freshness`** check (ADR-0013) that content-hashes the
venv's installed engine against the deployed vendored source and WARNs on a mismatch. Manual
equivalent — the decisive test:

```bash
diff -rq \
  "$CLAUDE_PLUGIN_ROOT/vendor/skill-search/skill_search" \
  "$HOME/.claude/skill-concierge/venv/lib/python3.*/site-packages/skill_search"
```

Empty output = fresh; any difference = stale.

**Do:** rerun **`setup.sh`** (the `skill-concierge:setup` skill) — it rebuilds/refreshes the
stable venv from the deployed source — then **restart Claude Code**. Rule of thumb: a
`/plugin update` that changed engine code under `vendor/skill-search/` requires a `setup.sh`
rerun; a change that only touched hooks/doctrine/scripts (cache-run) does not. (Hooks read
their code straight from the cache, so they update with the plugin; only the venv-resident
engine needs the rerun.)

---

## §12 — bge-m3/Ollama dense-embedder migration: built, measured, then explicitly SUSPENDED by the operator — do not re-propose without new evidence

**Symptom:** someone (agent or human) proposes swapping the embedder to a dense/Ollama model
(bge-m3 or similar), assuming the idea is unexplored or was merely a technical dead end.

**Cause:** it was already fully built and measured end-to-end on `feat/bge-m3-ollama-migration`
(`a86d3d6`) — **feasible** on latency (159ms p95 warm, under the 200ms enforcer cap) but
**lateral, not a win**, on retrieval quality (mean 0.738 vs mpnet's 0.734; the targeted
cross-lingual EN→VN win never materialized), and it **weakens the getaway-suppression floor**
(measured 10/10 non-task fire on bge-m3's cosine band vs mpnet's 4/10). **The operator personally
decided to suspend/defer** the migration on that evidence — a human call, not an automated verdict
or an agent's own judgment. `main` was reverted to clean mpnet 0.13.1; nothing was ever cut over
live.

**Do:** read the full journal
(`docs/journals/journal-2026-07-06-bge-m3-migration-built-measured-lateral-archived.md`) and the
archive plan (`plans/260706-0024-bge-m3-archive-to-feat-and-revert-main/plan.md`) before
re-raising this migration. The work is **preserved, not abandoned** — deployable later via the
runbook on the feat branch — but re-proposing it needs new evidence, not a repeat of the same
measurement. A verified operator decision does not reverse on an abstract concern alone.

## §13 — The LIVE plugin code is the VERSIONED cache dir, not `marketplaces/` and not the repo

**Symptom:** you verify a deployed fix by reading
`~/.claude/plugins/cache/skill-concierge/skill-concierge/<version>/` — or worse
`~/.claude/plugins/marketplaces/skill-concierge/` — and get a wrong/absent answer.

**Cause:** there are THREE copies and only one is live. (1) the **repo working copy**
(`in-PROD/.../skill-concierge/`) is your source you edit + push; (2)
`~/.claude/plugins/marketplaces/skill-concierge/` is the **marketplace registration** checkout,
NOT what the harness runs; (3) the harness actually runs the **versioned cache** at
`~/.claude/plugins/cache/skill-concierge/skill-concierge/<version>/` (e.g. `.../0.16.1/`) — that
is the live, in-use code (its `bin/skill-search-mcp` is what `.mcp.json` launches, and the stable
venv is stamped to that version in `~/.claude/skill-concierge/venv/.engine-plugin-version`).

**Do:** to check deployed state, read the **versioned cache** dir for that version and confirm the
venv `.engine-plugin-version` stamp matches. A repo edit only reaches the cache after a push +
`/plugin marketplace update` (+ reload/restart). Note the DISCOVERY scope is the opposite nuance
(skills are indexed from `cache/**/skills/`, deliberately **not** `marketplaces/**` — see
[retrieval-engine.md](retrieval-engine.md) / §5); §13 is about which PLUGIN CODE runs, §5 is about
which SKILL files get indexed.

## §14 — A background reindex must receive the engine flags, or it silently reverts them (v0.16.1)

**Symptom:** you enable an engine trigger flag (`SKILL_LLM_TRIGGERS`, `TRIGGERS_MAX`) in
`.mcp.json`, reindex, confirm the index is right — and a session or two later the index is back to
the old shape (utterance points gone), with no error.

**Cause:** the query MCP is launched by Claude Code with the FULL `.mcp.json` env, but the
`auto_reindex.py` SessionStart hook runs the reindex via its own `_mcp_env()`, which historically
forwarded only `SKILL_QDRANT_URL`/`SKILL_EMBED_BACKEND`/`SKILL_EMBED_MODEL` from `.mcp.json`. So
the detached reindex rebuilt at engine DEFAULTS (`SKILL_LLM_TRIGGERS` off, `TRIGGERS_MAX` 12) and
pruned the utterance points — an index unstable by design. Fixed in **v0.16.1**: the `_mcp_env()`
whitelist now also forwards `SKILL_LLM_TRIGGERS`/`TRIGGERS_MAX`/`SKILL_TRIGGERS`/`SKILL_BODY_TRIGGERS`.

**Do:** any engine-config env that must shape the INDEX has to reach the DETACHED indexer, not just
the query MCP. Two durable layers: (a) forward it in `auto_reindex._mcp_env()` (portable, in the
plugin), and (b) put it in `~/.claude/settings.json` env → `os.environ` → `merged = dict(os.environ)`
wins over `.mcp.json` regardless of the whitelist. The machine-local `SKILL_TRIGGERS` path (the
gitignored ~733K `eval/triggers.json`) lives in settings.json env for exactly this reason —
absent elsewhere it degrades gracefully to description+body. [ADR-0026](adr/0026-llm-utterance-trigger-layer.md), CHANGELOG [0.16.1].

## §15 — Plugin skill argument-hints need the SELF-NAMESPACED `name:` (the ClaudeKit pattern)

**Symptom:** you add `argument-hint:` to a plugin skill's `SKILL.md`, but the muted hint never shows
when you type the `/skill-concierge:<skill>` form the menu displays.

**Cause + fix (proven against ClaudeKit, which does this right):** CC uses the frontmatter `name:`
field *directly* as the slash command (issue #22063). A **bare** `name: flywheel` therefore registers
`/flywheel` (with the hint) plus a separate auto-namespaced `/skill-concierge:flywheel` **without** the
hint — so the hint is invisible on the form users actually see. The fix is NOT to omit `name:` (that
risks losing the hint entirely per #43401). It is to put the FULL namespaced name in the field, exactly
like ck: `name: skill-concierge:<skill>` + `user-invocable: true` + `argument-hint: "…"`. Then the slash
command *is* `/skill-concierge:<skill>` and the hint rides on it. skill-concierge's own engine already
supports this — `skills_discovery._namespaced_name` skips re-prefixing when `name:` already starts with
the plugin id (v0.10.2 guard), so the indexed name stays `skill-concierge:<skill>` (no double-prefix).

**Do:** all six skill-concierge skills use `name: skill-concierge:<dir>` (v0.18.0). The ENFORCED
`~/.claude/docs/claude-code-component-building.md` entry on #22063 recommends *omitting* `name:` — that
is the weaker branch; prefer the self-namespaced-name pattern (verified live to surface the hint). Note:
personal/project skills (not plugin-installed) keep their bare `name:` — this applies to plugin skills.

---

## §16 — `skillOverrides` CANNOT demote a plugin skill, and the listing silently drops descriptions when over budget

**Symptom:** `apply-overrides.py` reports "in sync: N on / M name-only, no drift", yet every
plugin-bundled skill still ships its full description in the turn's skill listing — and, worse,
some skills you deliberately kept `on` render as a bare `- name` with no description at all.

**Cause — two separate mechanisms in Claude Code. Both are DOCUMENTED upstream; neither is a bug,
and neither is anything `apply-overrides.py` can fix.** Sources: the official `skills.md`
(*"Override skill visibility from settings"* and *"Skill descriptions are cut short"*) and
`settings.md`, both carried in the `working-with-claude-code` skill's `references/`; mechanism
below confirmed against the 2.1.223 binary.

**1. Plugin skills bypass overrides entirely.** Upstream states it plainly — *"Plugin skills are not
affected by `skillOverrides`. Manage those through `/plugin` instead."* The resolver returns `"on"`
for anything plugin-sourced before it ever reads the map:

```js
function $3e(e){
  if(e.type!=="prompt" || e.source==="plugin") return "on";   // ← plugin skills never consult skillOverrides
  let n = r?.[e.name] ?? (e.unqualifiedName!=null ? r?.[e.unqualifiedName] : void 0) ?? "on";
  ...
}
```

This is **not** a key-format mismatch — writing `plugin:skill`, the bare `skill`, or both changes
nothing. For personal/project skills the same line shows the lookup *does* fall back from the
qualified name to `unqualifiedName`, so those keys are forgiving; plugin skills simply never reach
that code. Measured cost on the maintainer's machine: 63 plugin skills ≈ 21,100 chars ≈ **5,280
tokens/turn** that no allowlist can touch. The only lever is `/plugin disable` on plugins whose
skills do not earn their listing cost. Note this cost is NOT inert: plugin skills are contenders in
the same budget as your curated keep-on set (mechanism 2), so a dormant plugin actively evicts
descriptions you paid to keep.

**2. Over budget, descriptions are DROPPED, not truncated.** `skillListingBudgetFraction` (default
`0.01`, this deployment `0.03`) yields `budget = contextWindow × 4 × fraction`. If the rendered
listing exceeds it, Claude Code switches to `budgetMode: "priority"`: name-only and bundled skills
are exempt, the rest are sorted by a usage score and greedily fitted, and every skill that does not
fit renders as a bare `- name`. The score is:

```js
Q4t(name) = usageCount × max(0.5 ^ (daysSinceLastUse / 7), 0.1)     // 0 if never invoked
```

read from `skillUsage` in `~/.claude.json` — Claude Code's own counter, **not** skill-concierge's
ledger and not the transcript trail. The fit is greedy *with continuation*: an expensive entry that
does not fit is skipped while cheaper, lower-priority ones still land. So a 512-char description is
structurally disadvantaged — a high-usage skill can lose its description to a never-used one that is
simply shorter.

**Consequences that bite:**
- A skill being `on` guarantees nothing. Confirm by reading the actual listing, never by trusting
  `apply-overrides.py`'s "in sync".
- Long descriptions are the failure mode. `skillListingMaxDescChars` (512 here, upstream default
  1536) caps the render, but a capped-length entry is exactly the one greedy fitting drops first.
  Keep an always-on description **well under the cap** — the goal is to be cheap, not to be maximal.
- Demoting a never-used skill helps twice: it leaves the contender pool AND frees budget for the
  ones that matter.
- Raising `skillListingBudgetFraction` ends truncation but bills the full listing every turn,
  including the plugin block you cannot demote. Trim descriptions first.

**Do:** treat the always-on set as a **budget**, not a list — upstream's own remedies, in the order
they cost least:

1. **Trim `description` + `when_to_use` at the source, key use case first.** Upstream's wording:
   *"put the key use case first, since each entry's combined text is capped … regardless of budget."*
   Cheapest fix, and the only one that shrinks the listing rather than paying more for it.
2. **Demote low-priority entries to `name-only`.** They leave the contender pool AND free budget.
3. **Raise `skillListingBudgetFraction`** (or set `SLASH_COMMAND_TOOL_CHAR_BUDGET` to a fixed char
   count). Last resort: it bills the full listing every turn, including the plugin block you cannot
   demote.

**Measure, don't infer:** `/doctor` estimates the listing's context cost and names its biggest
contributors, and the Skills row in `/context` reports the size *after* the budget is applied (so it
matches what the model actually receives). An over-budget listing also writes a warning to the debug
log, visible with `--debug`. Confirm from one of these — never from `apply-overrides.py`'s "in sync".

**Timing:** `skillOverrides` is applied **on the next turn**, not the next session. The keep-on
skill's own note ("takes effect next session") is conservative; a demotion lands almost immediately.

---

## §17 — A file timestamp is not a build identity: `setup.sh` re-copies the engine on EVERY run

**Symptom:** doctor's `Running engine` row accuses live MCP servers of executing an older engine
build, right after a routine `setup.sh` — while the engine's own `health()` reports `stale: false`
in the same minute. Two diagnostics of the same fact, disagreeing. Restarting "fixes" it, so the
alarm looks real; it is not.

**Cause:** `setup.sh` is idempotent by design and re-copies the engine into the stable venv on
every run, whether or not the bytes changed. `st_mtime` and `st_ctime` therefore advance on a
no-op re-copy. Any check that dates a process against those timestamps concludes that every
server predating the copy is running old code — including servers running the exact same bytes.
Measured 2026-08-06 while deploying v0.20.6: `server.py` md5 identical before and after the
re-copy, mtime pushed to 23:30:54, a live server started 23:28:43 → three false accusations.

**The general rule:** "did the code change?" is a question about **content**, never about
timestamps. `check_engine_freshness` was always right for the same reason — it content-hashes
two trees. The process dimension needs the same discipline, which is why each MCP server now
publishes its own build id (`~/.cache/skill-search/servers/<pid>.json`, seam
`SKILL_SERVER_RECORDS`) and doctor **looks it up** rather than inferring it. A no-op re-copy
moves no id, so it is invisible to the check by construction (v0.20.7).

**Do NOT "fix" a false alarm here by loosening the comparison** (a tolerance window, a
"recently copied" grace period). That trades a false positive for a false negative on the same
axis and leaves the real bug — the permanent false `stale: true` of §11's cousin — undetected.
Compare identities, or report N/A.

**Corollary for anything reading `health()`:** `engine_build` is emitted on **every** report
since v0.20.7, not only under drift. Key on `engine_build.index_written_by` being non-null.
Keying on the block's *presence* — which was sufficient in v0.20.6 — now flags every healthy run.

**`SKILL_SERVER_RECORDS` is pinned in `.mcp.json`, and doctor reads the pin FIRST — do not
"fix" that to an env-var-wins precedence.** It is the one seam where the reader must resolve
what the *writer* used, and the writer's environment is the one `.mcp.json` hands it. An env
export in the reader's shell would only split the two, and doctor would then find an empty
directory and report every live server as unproven, permanently. This repo has already shipped
that writer/reader split twice — `auto_reindex._mcp_env()` (v0.16.1) and `setup.sh env_run()`
(v0.20.5) — both recorded as "a seam honoured by one side and not the other".

**Related trap when reading a diagnostic twice:** doctor memoizes `skill-search --health` for
one check pass, because two checks need it and spawning the engine is its slowest step. That
memo is cleared at the top of `run_all()` and must stay cleared there. `doctor --fix` runs a
second pass whose whole purpose is to observe what the fix changed; a memo carried across that
boundary makes the re-check reprint the failure it just repaired and exit 1 on a healthy system.

---

## §18 — One drift symptom, two causes, opposite remedies — and the engine can see neither

**Symptom:** after any engine release, `health()` (or a `search_skills` reply) says the index was
built by a different engine build. The v0.20.7 text went on to assert *"a live MCP server is on a
different build … reindexing will not fix it"*. Both halves are usually false at that moment.

**Cause:** manifest drift means only that `manifest["engine"] != _ENGINE_BUILD`. Two very different
states produce it:

| State | Remedy | Why |
|---|---|---|
| A server is still live on the old build | **restart** | a reindex writes *our* build; that server keeps computing its own signature and hands the mismatch back — flip-flop |
| The manifest is left over from the previous release, no old server survives | **reindex** | it re-stamps the manifest with the running build and clears |

**Every engine upgrade lands in the second state first**, because `_ENGINE_BUILD` hashes
`server.py` + `skills_discovery.py` — so changing the engine at all changes the build id, and the
manifest written by the previous release is instantly "drift". Asserting state A is therefore wrong
on the commonest path.

**The structural point: an engine process cannot tell them apart.** It knows its own build and
nothing about other processes. So the engine states the observation and offers both remedies as
alternatives — it must not pick one. **doctor** picks, because it holds the live-server evidence
(§17's `<pid>.json` records) in the same check pass: `_drift_remedy()` resolves the state, names the
pids, and prints only the remedy that applies.

**`fix="reindex"` is returned for exactly ONE state — a fleet proven entirely on the current
build.** Drift pids, unknown pids, and absent evidence all stay `fix=None`. Auto-reindexing while an
older server is live is the v0.20.6 defect re-armed: it clears the CLI-side symptom, re-embeds every
point whose text moved under the new parser, and leaves that server exactly as broken.

**The engine must name NO remedy — not even as an option.** `_staleness_warning` rides in every
`search_skills` reply and `_health` surfaces through the `health()` tool, so both are read by the
MODEL. `reindex()` is an MCP tool that runs **inside the process whose build is in question**, and
build ids are unordered md5 hashes: a server cannot tell whether its own build is the newer or the
older one. If it is the older one, reindexing from there re-embeds with the stale parser and
re-stamps the manifest BACKWARD, fighting the session-start rebuild. So "reindexing will not fix
it" was wrong, and the obvious correction — "run `reindex()` if every server is on this build" —
is worse, because the model cannot evaluate the condition and will just call the tool. Both
emitters state the observation and route to doctor. Nothing else is safe from inside the engine.

**Do not "simplify" this back into one unconditional message.** The two rows must agree; a doctor
run that says *"3 servers publish no build id"* directly above *"a live server is on an older build,
reindex will not fix it"* is two diagnostics of one fact contradicting each other, which is the
failure this and §17 both exist to end.

**Testing lesson banked here, worth more than the fix:** the guard that was supposed to prevent a
regression in this area passed while the code was broken, because it exercised the reset *helper*
instead of the *wiring* — `run_all()` referenced a renamed function and doctor died with a
`NameError` on the first real run, selftest still green. Assertions about a pass boundary must drive
the real entry point (`run_all()`), with a probe check observing the state a check actually sees.
Verify any such guard with a negative control: break the wiring on purpose and watch it fail.

## §19 — Dual-harness: the Codex cache is indexed UNFILTERED, and Codex skill-use is invisible to the ledger

ADR-0033 indexes `~/.codex/plugins/cache/**` wholesale. Claude's cache is filtered to
installed+enabled plugins via `installed_plugins.json` + `settings.json`; Codex tracks
enablement in `config.toml` (TOML, not stdlib-parseable on the 3.10 floor), so the filter
cannot be reused without a TOML dependency. Consequence: a disabled Codex plugin or a stale
version dir CAN appear in retrieval until a later reindex prunes it. Accepted trade — a few
stale results beat a blind spot over Codex's whole skill universe. `SKILL_CODEX_ROOTS=0` +
a reindex restores Claude-only discovery if this ever bites.

Second: Codex has no `Skill` tool-call event, so the ledger's `auto` rows (skill-invocation
capture via PostToolUse) are Claude-only. Codex sessions still log `turn`/`offer` rows
(the enforcement trail works — doctrine + enforcer + search uptake), but offer→take
conversion for Codex must be read from `search_skills` calls, not `Skill` invocations.
And per the epoch rule: enabling skill-concierge in Codex is a config change — start a new
`analyze.py --since` epoch; never pool across it.

## §20 — `settings.json` `env` is a CLAUDE-ONLY environment; cross-harness env has one canonical home

The `env` block in `~/.claude/settings.json` injects variables into **Claude Code sessions and
nothing else**. Codex (and any other harness) never reads it. Three incidents on 2026-08-24, one
day, all this class:

1. **The flywheel went invisible from Codex.** `FLYWHEEL_LLM_*` lived in the settings env, so
   doctor run inside a Codex session honestly reported *"not configured"* against a fully
   configured machine, and `auto_flywheel`'s SessionStart self-heal silently no-opped in every
   Codex session while Claude sessions kept the shared utterance layer fresh.
2. **A literal that can never expand.** `CLAUDE_PLUGIN_ROOT: "$HOME/.claude"` — JSON env values
   do not shell-expand, so every Claude session carried the literal string. It masked a real
   Codex-side selftest failure (harness detection trusted the env candidate) and is the likely
   origin of a transient `'$HOME/...'` ENOENT MCP entry. **But it is NOT debris**: it is the
   deliberate hookify workaround (upstream claude-code#46915) feeding `${CLAUDE_PLUGIN_ROOT}` to
   the USER-level hooks in `~/.claude/hooks/hooks.json`, whose commands are expanded by the
   hook's own shell — two-stage expansion that works for shell-form hook commands and poisons
   anything reading `os.environ` directly. The enforcer defends itself by skipping non-absolute
   candidates (v0.26.1); the entry stays.
3. **A shell-rc export of the expanded path.** `~/.bash_profile` exported the EXPANDED absolute
   `CLAUDE_PLUGIN_ROOT` — redundant for Claude (settings supplies it) and a live inversion
   hazard for any other harness launched from a bash login shell. Commented out with a dated
   revert note.

**The rule:** env that more than one harness needs goes in `~/.config/harness-env.sh`
(mode 0600; sourced from `~/.zshenv` — every zsh: interactive, non-interactive, login, scripts —
plus `~/.bashrc` and `~/.bash_profile`). Exported values propagate to every child process, so
coverage is everything descended from a shell; the only residual is launchd/GUI processes with no
shell ancestor, which need the env in their own plist. Harness-specific env stays in that
harness's own config **by design** — exporting an absolute Claude path machine-wide is exactly
incident 3. Verified from clean `env -i` environments across six launch shapes (zsh -c/-lic,
bash -lc/-ic, bash-under-zsh, python child) on 2026-08-24.

## §21 — Triple-harness: Command Code uses mods for per-turn enforcement, not settings hooks

Command Code (`cmd`) supports four settings hook events (`PreToolUse`, `PostToolUse`, `Stop`, `SessionStart`),
with tool matchers restricted to built-in commands (`SHELL`, `READ`, `WRITE`, `EDIT`).

Consequences:
1. **`UserPromptSubmit` does not exist in cmd settings hooks:** Attempting to wire `enforcer.py` or
   `ledger.py` under `UserPromptSubmit` in `~/.commandcode/settings.json` is a silent dead-end.
   Enforcement and prompt-turn telemetry MUST run via a Command Code **mod** (`cmd.hooks({ transformInput })`).
2. **MCP tool calls are not intercepted by settings hooks:** `PostToolUse` matchers in cmd do not fire on
   MCP tools or `activate_skill`. Tool invocation telemetry MUST run via mod event observers
   (`cmd.on('skill_loaded')`, `cmd.on('tool_completed')`).
3. **SessionStart hooks work natively:** `doctrine.py`, `auto_reindex.py`, `auto_overrides.py`,
   `auto_flywheel.py`, and `auto_promote.py` run from `~/.commandcode/settings.json` `SessionStart` hooks
   with native tool name adaptation.
4. **`${CLAUDE_PLUGIN_ROOT}` literal in `.mcp.json` is unresolvable by cmd:** Command Code does not
   expand plugin root variables in `.mcp.json`. The `adapters/commandcode/install.sh` script writes
   absolute paths to `~/.commandcode/mcp.json` and local project overrides to avoid this failure class.

## §22 — Quadruple-harness: OMP ignores Claude-format hooks.json; enforcement is an extension module (ADR-0039)

Oh My Pi (OMP) accepts the Claude plugin *package* (skills surface, `.mcp.json` with native
`${CLAUDE_PLUGIN_ROOT}` expansion, marketplace install) but **does not execute Claude-format
`hooks/hooks.json` command hooks**. Between v0.26.2 and v0.27.0 the OMP-installed plugin therefore
looked healthy (skills listed, MCP connected) while doctrine, per-turn enforcement, ledger capture,
and SessionStart self-heal were all silently dead. OMP's hook surface is TS/JS factory modules
(`pi.on(...)` events) loaded from `package.json` `omp.extensions` manifests — enforcement rides
`adapters/omp/skill-concierge.ext.ts` (`before_agent_start` is the UserPromptSubmit equivalent).

Landmines verified live 2026-08-25:

1. **`OMPCODE=1` AND `CLAUDECODE=1` are both set under OMP.** `CLAUDECODE=1` alone is NOT proof of
   Claude Code — harness detection must key on `OMPCODE` (or `SKILL_CONCIERGE_HARNESS=omp`).
   `_running_harness()` checks OMPCODE before path markers for exactly this reason.
2. **OMP's codex skill provider reads no plugin cache** (`pi-coding-agent src/discovery/codex.ts`
   scans only `~/.codex/skills` + `<cwd>/.codex/skills`). `codex-plugin` skills are therefore
   foreign under omp: `_foreign_scopes()` for omp is `("codex-plugin", "commandcode-personal")`.
3. **OMP auto-imports every other harness's MCP declarations.** Never declare `skill-search` in
   `~/.omp/agent/mcp.json` while the marketplace plugin is installed — two same-server entries
   launch twice. The plugin's own `.mcp.json` is the single declaration; `adapters/omp/mcp.json`
   is a manual fallback for plugin-less setups only.
4. **Extensions snapshot at session start.** Config/marketplace changes require a session restart
   (or `/reload-plugins` for skills/MCP; extension modules need the restart).
5. **Extension `tool_call` handlers are fail-closed** (a throw blocks the tool) — all telemetry
   observation lives in `tool_result`, fully try/caught. Same doctrine as the repo's hook rules,
   but enforced by OMP's runtime rather than our discipline.
6. **`omp-plugin` scope is EMPTY when every OMP plugin twins a Claude install — by design, not a
   wiring failure.** Discovery dedups by NAME (first writer wins; precedence personal → project →
   plugin → catalog; `skills_discovery.discover_skills()`), and `discover_skill_paths()` yields
   Claude hits before OMP hits. `skill-concierge:doctor`, memsearch, effort-gate etc. exist in
   both `~/.claude/plugins/cache` and `~/.omp/plugins/cache`, so ONE `plugin`-scope point survives
   and the OMP twin collapses into it. Benign: OMP's claude-plugins provider reads the Claude
   cache, so the collapsed point stays invocable under OMP (verified live — `skill-concierge:doctor`
   offered to an OMP session, 2026-08-25 smoke probe). `omp-plugin` fills only for OMP-ONLY
   plugins. Diagnosing "why is omp-plugin empty?" without this note costs a full false-bug hunt.
