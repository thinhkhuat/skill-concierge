# Code Review — skill-concierge reproduction layer (vendored-MCP bootstrap)

Date: 2026-06-26 · Reviewer: code-reviewer (report only, no files modified)
Scope: `.mcp.json`, `setup.sh`, `scripts/apply-overrides.py`, `config/keep-on.json`, `vendor/skill-search/VENDORED.md`, `docs/skill-search-deployment-readme.md`

## Overall assessment

The customization layer is sound and the high-value safety properties asserted by the
author hold up under inspection: the applier targets `settings.json` (not
`settings.local.json`), uses the same `"on"/"name-only"` vocabulary the engine uses,
preserves every other settings key, refuses to write on empty discovery, and keeps
UTF-8. I verified these against the live engine and the live `~/.claude/settings.json`.

The defects are at the edges the dry-run could not exercise: **the write to the global
settings file is not atomic** (the one issue that can actually violate the non-negotiable
"never corrupt" property), the **double MCP registration is real and unaddressed at
go-live**, the **enable-before-setup ordering is a foot-gun**, and a **hand-edited
keep-on.json can silently produce a valid-but-wrong policy** that darkens the whole
retriever. None of these fail the happy path; all of them bite a real machine.

Verdict: **DONE_WITH_CONCERNS** — one blocker (atomic write), four should-fixes.

---

## Evidence verified (positive — for risk calibration)

- **Override vocabulary + target match the engine.** `apply-overrides.py:52` produces
  `{n: "on" if n in keep_on else "name-only"}` and writes `settings["skillOverrides"]`
  (`:62`) — byte-identical semantics to the engine's `generate_overrides.py:48,56`. The
  live `~/.claude/settings.json` confirms the schema: 508 entries, 477 `name-only` / 31
  `on`, matching the 31-entry `config/keep-on.json`. The applier correctly **diverges**
  from the engine default, which writes `settings.local.json` (`generate_overrides.py:66`)
  with a tiny argv keep-on — exactly the behavior VENDORED.md and the readme warn against.
- **Other-keys preservation is real.** The applier loads the whole dict, sets only
  `skillOverrides`, rewrites. The live file holds 40+ top-level keys (`permissions`,
  `hooks`, `mcpServers`, `env`, `enabledPlugins`, …) — all preserved. `ensure_ascii=False`
  (`:65`) preserves the UTF-8 `vn-*` names.
- **Discovery is the same source the index uses and is embedder-free.**
  `skills_discovery.py` imports only `re/glob/pathlib`; `discover_skills()` returns dicts
  keyed `name` (`:83,107`), so `s["name"]` (`apply-overrides.py:42`) is correct, and the
  applier never drags in the heavy ML deps.
- **Backup ordering is fail-safe.** The backup (`:58-59`) is taken *after* `json.loads`
  of the existing settings (`:57`), so a malformed existing `settings.json` raises before
  any backup or write — no corruption, nothing clobbered.
- **Empty-discovery guard works** (`:48-50`): a failed discovery returns 1 and never
  blanks the budget.
- **Entry point is correct.** `pyproject.toml [project.scripts] skill-search =
  skill_search.server:main`; `server.py:478-482` handles `--rebuild/--reindex/--health`.
  `.mcp.json` points at `vendor/.venv/bin/skill-search`, which the editable install
  (`setup.sh:24`) produces. `--health` exits non-zero when degraded, so `setup.sh:44`
  fails loud on a bad index.

---

## BLOCKER

### B1 — Write to the global `settings.json` is not atomic (torn-write corruption)
`scripts/apply-overrides.py:63-65`
```python
SETTINGS.parent.mkdir(parents=True, exist_ok=True)
SETTINGS.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
```
`write_text` truncates the target to zero, then writes. If the process dies between
truncate and full write — realistically **disk full**, also SIGKILL / power loss — the
live `~/.claude/settings.json` is left truncated or half-written. That file is not just
the skill budget: the live copy holds `permissions`, `hooks`, `mcpServers`, `env`, and
~35 other keys. A torn write breaks **all** of Claude Code, not just retrieval. This is
the single path that violates the stated non-negotiable "never corrupt the user's
settings" property.

The backup at `:58-59` makes it *recoverable* (find `~/.claude/settings.json.bak-skillconcierge-*`),
but recovery is not prevention, and the backup itself is written non-atomically — a
disk-full condition can tear the main file *and* leave a short backup.

**Fix (standard, trivial):** write to a temp file in the same directory, then
`os.replace(tmp, SETTINGS)` — atomic rename on the same filesystem guarantees readers
(including a concurrently-starting Claude session) always see either the complete old or
complete new file, never a torn one. Apply the same to the backup if you want belt-and-suspenders.

---

## SHOULD-FIX

### S1 — Double MCP registration is real and not reconciled at go-live
Confirmed live: `~/.claude.json → mcpServers.skill-search` already exists (user scope,
`command: "skill-search"` on PATH from pipx). The plugin's `.mcp.json` registers a
**second** `skill-search` pointing at `${CLAUDE_PLUGIN_ROOT}/vendor/.venv/bin/skill-search`.
`disabledMcpjsonServers` is `['human-mcp']` — skill-search is **not** disabled, so once
the plugin is enabled both registrations are live. Same name, two different binaries,
same Qdrant collection → at best one shadows the other, at worst two server processes
spawn for the same store. Wasteful and confusing.

`setup.sh:51-57` ("To go live") tells the user to *enable the plugin* (or add the reg
manually) but never to **remove** the pre-existing user-scope reg.

**Recommendation (cleanest reconciliation):** the plugin's whole point is
self-containment, so make `.mcp.json` the single source — instruct go-live to
`claude mcp remove skill-search -s user` (and drop `~/.claude.json` mcpServers.skill-search)
before/when enabling the plugin. Document it in `setup.sh`'s go-live block and the
readme's reverse/uninstall section. (Do not keep both "just in case" — same-name
collisions are exactly what bites here.)

### S2 — Plugin enabled before `setup.sh` runs → silent failed MCP
`.mcp.json:4` points at `vendor/.venv/bin/skill-search`, which exists **only after**
`setup.sh` creates the venv (`setup.sh:22-24`). Plugins are typically enabled at install
time, *before* a user runs any `setup.sh`. `enabledPlugins` confirms `skill-concierge`
isn't enabled yet, so the ordering is still controllable — but the natural marketplace
flow (install → enabled) makes the MCP fail-to-connect until setup runs.

Degradation is graceful in the safety sense (a failed MCP is non-fatal; no overrides are
applied either, so the native full listing still works) — but the failure is silent and
confusing ("skill-search ✘ Failed to connect" with no hint why). The ordering is only
implied by `setup.sh`'s tail text, not enforced or surfaced at the failure point.

**Recommendation:** document prominently (readme + setup output) "run `setup.sh` first,
then enable the plugin." Optionally ship a tiny wrapper as the `.mcp.json` command that,
when the venv binary is missing, prints "skill-concierge: run setup.sh first" instead of
a bare ENOENT.

### S3 — A hand-edited `keep-on.json` can silently apply a valid-but-wrong policy
`scripts/apply-overrides.py:46`
```python
keep_on = set(json.loads(KEEPON.read_text(encoding="utf-8")).get("keep_on", []))
```
- **Missing file / broken JSON** → uncaught `FileNotFoundError` / `JSONDecodeError`
  traceback. This fails *before* any write (line 46 precedes discovery and the write), so
  it is fail-safe (no corruption) — but it's an ugly abort at setup step [4/4].
- **Worse: valid JSON, missing/misspelled `keep_on` key** → `.get("keep_on", [])` returns
  `[]` → `keep_on` is empty → **every** skill, including the `skill-search` router itself,
  is set to `name-only`. The router's description then leaves context and the whole
  indirection goes dark (name-only keeps the name, drops the "call search_skills first"
  instruction). The empty-overrides guard (`:48`) does **not** catch this — `overrides` is
  non-empty (it's full of name-only entries); only `names` being empty trips the guard.

`config/keep-on.json`'s `_note` explicitly invites "Edit to taste," so a malformed hand
edit is a plausible, not theoretical, input.

**Fix:** validate the loaded shape (a dict with a non-empty `keep_on` list), and
sanity-check that the router (`skill-search`) resolves to `"on"`, before writing. Refuse
+ explain on failure, the same way the empty-discovery case already does.

### S4 — Setup-time `SKILL_EMBED_MODEL` override silently diverges from the static `.mcp.json`
`setup.sh:9-10,17` invites "Override `SKILL_QDRANT_URL` / `SKILL_EMBED_MODEL` via env" and
builds the index with that model (`:42-43`). But `.mcp.json:10` **hardcodes** mpnet. If a
user sets a different model at setup, the index is built with model A while the live MCP
queries with model B → vector-dimension/model mismatch. This isn't silent *corruption*
(the engine's guards surface it: `server.py:296,444` raise "embedder changed; run
`--rebuild`", and `--health` flags it), but retrieval is **dead** until someone rebuilds
with matching env — and the mismatch is created by following the script's own advice.
Same half-truth for `SKILL_EMBED_BACKEND`: `env_run` hardcodes `fastembed` (`:42`), so the
"override via env" invitation doesn't actually apply to the backend.

**Fix:** either drop the model/backend-override invitation, or state that `.mcp.json` must
be edited to match any setup-time model change (single source of truth for the runtime
model is the `.mcp.json` env, and the index must be built with the same).

### S5 — `setup.sh` does not pin or check the Python version (defeats portability on macOS)
`setup.sh:22` creates the venv with **bare `python3`**:
```bash
[ -d "$VENV" ] || python3 -m venv "$VENV"
```
The reproduction goal is "run on any machine," but the engine pins
`requires-python = ">=3.10"` (`pyproject.toml`) and the deployment readme's own decision
log documents this exact hazard on the target platform: *"macOS system Python is 3.9;
pipx default (3.14) risks missing onnxruntime/fastembed wheels"* — which is why the manual
deploy pinned `python3.12`. The reproduction script drops that constraint:
- system `python3` = 3.9 (stock macOS) → `pip install -e` (`:24`) aborts on the
  `requires-python` floor, after already creating a dead venv. Fails loud but confusing.
- `python3` = 3.13/3.14 → the documented `onnxruntime`/`fastembed` wheel-gap risk; if it
  bites, it bites at dependency install, again after a half-built venv.

So the script fails to reproduce the single environmental constraint the doc calls
load-bearing, on the platform where the deploy actually lives.

**Fix:** check the interpreter is 3.10–3.12 (or whatever the tested ceiling is) before
`venv`, with a `SKILL_PYTHON` env override to pin (e.g. `SKILL_PYTHON=python3.12`), and
fail with a clear message naming the supported range.

---

## NITS

### N1 — Docker daemon not pre-checked (`setup.sh:27`)
`command -v docker` proves the CLI is installed, not that the daemon/OrbStack is up. On
macOS the CLI commonly exists while the daemon is down → `docker ps -a` / `docker run`
fail with a cryptic "Cannot connect to the Docker daemon" and `set -e` aborts. Fail-loud
is preserved, but a `docker info >/dev/null 2>&1` preflight with a clear message ("start
OrbStack/Docker and re-run") is friendlier.

### N2 — Backup proliferation + same-second collision (`apply-overrides.py:58`)
`setup.sh` is advertised idempotent/re-runnable; every re-run drops another
`~/.claude/settings.json.bak-skillconcierge-<epoch>`. Over time these accumulate in
`~/.claude/`. Two runs in the same wall-clock second share a filename (`int(time.time())`)
→ the second overwrites the first (harmless: identical pre-state). Consider keep-last-N or
a higher-resolution suffix. Minor housekeeping; also note each backup is a full copy of
settings.json (incl. `mcpServers` env, permissions) — same directory perms, so not a new
exposure, just clutter.

### N3 — `keep-on.json` ships a personal, catalogue-specific default
The list is this machine's `ck:`/`vn:` policy. On a target with a *different* skill set,
every local skill goes `name-only` with none kept `on` except literal name matches. The
`missing` reporting (`:53,70-72`) handles absent keep-on entries well and the `_note`
flags the coupling — acceptable for a personal-deployment reproduction, but worth a
one-line "review `config/keep-on.json` before first apply" in the setup output so a new
operator doesn't unknowingly demote skills they rely on.

---

## Idempotency verdict (task asked "re-run safe?")

**Yes, re-run-safe — but not free.** `setup.sh` guards each step: venv created only if
absent (`:22`), the `skill-search-qdrant` container is reused not duplicated (`:28-35`,
exact-name `grep -qx` + `docker start || true`), and `apply-overrides.py` re-derives a
deterministic policy and backs up before writing. No step double-creates or corrupts on
re-run. Caveat: step [3/4] runs `--rebuild` (`:43`), a **full** re-embed of all ~507
skills every time, where `--reindex` (incremental) would skip unchanged skills — wasteful,
not unsafe. Consider `--reindex` on re-runs and reserve `--rebuild` for first build /
embedder change.

## Behavioral checklist (relevant items)

- **Concurrency:** no file locking. Concurrent *applier* runs are idempotent (output is
  deterministic from discovery + keep-on), so they don't corrupt each other — but the
  applier-vs-Claude-reading race and the torn-write window both motivate B1's atomic
  rename. Handled by fixing B1.
- **Input validation at boundary:** `keep-on.json` shape is unvalidated (S3); setup-time
  env vs static `.mcp.json` is unreconciled (S4).
- **Backwards compat / data exposure:** other settings keys preserved (verified). Backups
  contain the full settings file — not a *new* leak (same `~/.claude` perms), just
  accumulation (N2). No secrets in any reviewed file.
- **Error propagation:** `setup.sh` `set -euo pipefail` + `--health` gate are correct and
  fail loud. The applier's uncaught traceback paths (S3) all occur before the write, so
  they fail safe.

---

## Recommended actions (priority order)

1. **B1** — atomic write (`tmp` + `os.replace`) for `settings.json`. Non-negotiable.
2. **S1** — remove the user-scope `skill-search` MCP at go-live; make `.mcp.json` the
   single registration; document in `setup.sh` + readme.
3. **S2** — document/enforce "setup.sh before enable"; optionally a missing-venv wrapper.
4. **S3** — validate `keep-on.json` shape and that the router stays `on` before writing.
5. **S4** — reconcile setup-time model override with the static `.mcp.json`, or drop the
   override invitation.
6. **S5** — pin/check the Python version (3.10–3.12) with a `SKILL_PYTHON` override.
7. **N1–N3** — daemon preflight, backup retention, "review keep-on.json" hint.

## Unresolved questions

- **MCP name-collision precedence** (S1): I did not find authoritative confirmation of how
  Claude Code resolves the *same* MCP name across user scope (`~/.claude.json`) and plugin
  scope (`.mcp.json`) — shadow vs double-spawn. The recommendation (one registration) is
  correct regardless, but the exact current behavior on this machine is unverified.
- **Index model on the live machine** (S4): the live deployment was built with mpnet; I did
  not re-run `--health` to confirm the *current* Qdrant collection dim, since that would
  touch the running system.

Status: DONE_WITH_CONCERNS — reproduction layer is sound on the happy path; one blocker (non-atomic global-settings write), plus double-MCP-registration, enable-before-setup ordering, and keep-on.json validation need fixing before go-live.
