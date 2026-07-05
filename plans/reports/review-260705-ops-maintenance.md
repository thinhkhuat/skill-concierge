# Review: install / health / telemetry / maintenance surface

Reviewer C — grounded review, read-only. Every claim below cites `path:line` plus a
verbatim quote from the actual file. Scope: `scripts/doctor.py`, `setup.sh`,
`scripts/analyze.py`, `scripts/driftcheck.py` + `driftcheck.json`,
`scripts/apply-overrides.py`, `config/*.json`, `skills/{skill-search,doctor,setup,
skill-usage-audit}/SKILL.md`, `skills/skill-usage-audit/scripts/audit_skill_usage.py`,
`Dockerfile`. Cross-referenced against `AGENTS.md` and `hooks/scripts/enforcer.py`
where the scope files claim a cross-file contract.

---

## 1. What each tool actually does (with line cites)

**`scripts/doctor.py`** — a read-only check matrix (`CHECKS` list, `scripts/doctor.py:468-470`:
`CHECKS = [check_python, check_venv, check_engine_freshness, check_mcp_wiring, check_qdrant, check_engine_health, check_enrichment, check_multivector, check_prompt_intent, check_corpus_health, check_overrides, check_ledger, check_dup_mcp]`) plus 5 auto-fixers gated behind `--fix` (`scripts/doctor.py:529-531`: `AUTO_FIXERS = {"docker": fix_docker_start, "reindex": fix_reindex, "reapply": fix_reapply, "overrides": fix_overrides, "prompt_intent": fix_prompt_intent}`). It intentionally delegates the retrieval diagnostic to the engine itself — `check_engine_health` (`scripts/doctor.py:259-260`: `"""Delegate the retrieval diagnostic to the engine itself (DRY)."""`) shells out to `skill-search --health` and classifies a stale-but-serving index as WARN not FAIL via `_stale_only` (`scripts/doctor.py:228-241`).

**`setup.sh`** — four idempotent steps (`setup.sh:40,46,74,90`: `[1/4] venv + deps`, `[2/4] Qdrant server`, `[3/4] build/refresh the multilingual index`, `[4/4] apply curated name-only overrides`), plus an unlabeled `[2b/4]` embed-shim step (`setup.sh:58`). Step 1 always reinstalls the vendored package non-editable — `setup.sh:44`: `"$VENV/bin/pip" -q install --upgrade pip >/dev/null` / `"$VENDOR" tiktoken   # non-editable: copies the engine in, so a cache wipe can't break it` — which is what makes re-running setup.sh the actual fix for the "Engine freshness" WARN doctor reports.

**`scripts/analyze.py`** — segments the append-only ledger into per-session "turn windows" (`scripts/analyze.py:192-224`), joins the enforcer's `offer` events onto their turn by `(sid, q)` (`scripts/analyze.py:226-233`), and reports uptake/search/dodge/hit@k/offered-turn-conversion. `--since`/`--until` parse epoch seconds or local ISO strings (`scripts/analyze.py:89-109`) and filter by event time (`scripts/analyze.py:183-189`).

**`scripts/driftcheck.py`** — three check kinds driven by `driftcheck.json`: (a) **facts** — a named SSOT regex extraction (`_extract_source`, `scripts/driftcheck.py:79-94`) compared against N mirror regexes (`_check_mirror`, `scripts/driftcheck.py:97-108`); (b) **paths_exist** (`scripts/driftcheck.py:127-132`); (c) **command_checks** — arbitrary shell commands whose exit code is pass/fail (`scripts/driftcheck.py:135-140`). `driftcheck.json` wires one fact (`version`, SSOT = `.claude-plugin/plugin.json`, mirrored to `marketplace.json`, `CHANGELOG.md`, `README.md` — `driftcheck.json:2-25`), 18 `paths_exist` entries, and 2 `command_checks` (`check_doc_parity.py`, `check_skill_list_parity.py` — `driftcheck.json:47-56`).

**`scripts/apply-overrides.py`** — every discovered skill goes `"name-only"` except a curated `keep_on` allowlist (`scripts/apply-overrides.py:63`: `overrides = {n: ("on" if n in keep_on else "name-only") for n in names}`), written atomically to `~/.claude/settings.json` via temp-file + `os.replace()` (`scripts/apply-overrides.py:76-80`), after a timestamped backup (`scripts/apply-overrides.py:69-72`).

**`skills/skill-usage-audit/scripts/audit_skill_usage.py`** — parses `~/.claude/projects/**/*.jsonl` for three signals (Skill-tool calls, `/slash`, and the inline `USING`/`SEARCH`/`SKIPPING` declaration trail) and computes a false-SKIPPING rate per turn (`_skip_verdicts`, `scripts/…/audit_skill_usage.py:106-126`).

**`Dockerfile`** — bakes `fastembed==0.8.0` and the multilingual model into the embed-shim sidecar image (`Dockerfile:16,20,29`), matching `.mcp.json`'s `SKILL_EMBED_MODEL` (verified below).

---

## 2. Telemetry-discipline fidelity — verified against AGENTS.md's claims

**Claim (AGENTS.md:64-66):** `` `skills/skill-usage-audit/scripts/audit_skill_usage.py` recognizes the `SKILL-CHECK:` marker: a hook-authorized skip is tallied separately as `authorized_skip` and excluded from the false-SKIPPING count ``.

**Verified TRUE.** `audit_skill_usage.py:106-126` (`_skip_verdicts`):
```
if t.get("saw_marker"):
    authorized_skip += 1
elif t.get("saw_search"):
    lawful_skip += 1
else:
    false_skip += 1
```
`authorized_skip` is a distinct bucket, never added to `false_skip`. The `--selftest` (`audit_skill_usage.py:270-278`) pins exactly this branch (`{"saw_skip": True, "saw_search": False, "saw_marker": True}` → `az == 1`, not counted in `fs`).

**Cross-file contract, verified TRUE.** `audit_skill_usage.py:176-178` only sets `saw_marker` when the line contains `AUTHORIZED_SKIP_MARKER` *and* one of two anchor phrases: `"full-catalogue retrieval ran"` or `"intent-margin classifier"`. In `hooks/scripts/enforcer.py:312-313,319-320`:
```
GETAWAY_SKIP_MSG = (
    AUTHORIZED_SKIP_MARKER + " full-catalogue retrieval ran (top {top:.2f} < floor {floor:.2f}); "
...
INTENT_SKIP_MSG = (
    AUTHORIZED_SKIP_MARKER + " the intent-margin classifier judged this turn conversational/"
```
Both anchor substrings match exactly what the audit script looks for — the "keep in sync" comment (`audit_skill_usage.py:174-175`) is honored today, not just asserted.

**Claim (AGENTS.md:73-92):** ledger metrics are EPOCH-SCOPED; never pool across config changes.

**Verified as a procedural discipline, not a code invariant** — and that is consistent with how AGENTS.md itself frames it (a human/agent workflow: find the epoch-start commit via `git log`, then window). `analyze.py` supplies the *mechanism* (`--since`/`--until`, `scripts/analyze.py:168-171`) but does not itself discover epoch boundaries or refuse to print an unwindowed run — it will happily compute and print an all-time rate if invoked with no flags. This is not a bug (the discipline is explicitly the caller's job per AGENTS.md's own 5-step checklist), but it means **nothing in the code prevents re-introducing the exact "pooled 15 epochs" mistake AGENTS.md warns about** — the guard is entirely social/documentary. Flagging as a gap for awareness, not a defect (matches your own framing in AGENTS.md:89-92 that this already happened once).

---

## 3. Correctness findings (ranked, most severe first)

### 🔴 3.1 `analyze.py` offer→turn join can misattribute offers when a session repeats an identical first-120-char prompt

**File:** `scripts/analyze.py:197-233`

The turn/offer join key is `(sid, q)` where `q` is the prompt truncated to 120 chars (comment confirms this design at `scripts/analyze.py:226-227`: `"Attach offers to their turn window by (sid, q-prefix). Offer.q and turn.q are both prompt[:120], so they match exactly."`). The dict is built here:
```python
if ev == "turn":
    by_sid_q[(sid, w["q"])] = w                    # analyze.py:206
```
This is a **plain dict assignment with no collision handling**. If the same session emits two `turn` events whose prompt agrees in its first 120 characters (a retried prompt, a repeated short instruction like "continue" or "try again", or two prompts that happen to share a long common prefix), the second `turn` **overwrites** the first's entry in `by_sid_q`. The offer-attachment pass runs afterward, over the *final* state of the dict:
```python
for e in offers:                                              # analyze.py:228
    w = by_sid_q.get((e.get("sid", ""), e.get("q", "")))       # analyze.py:229
    if w is not None:
        w["offered"] = [...]                                   # analyze.py:231
```
Both offer events — the one that belongs to the *first* turn and the one that belongs to the *second* — resolve to the same dict key and therefore both get attached to whichever turn was recorded **last**. The first turn's window is left with `offered=None` (silently dropped from `hit@k`/`offered_by_skill` denominators), while the second turn's window is double-counted or holds the wrong band/offered-set.

**Failure scenario:** a session where the user issues the same short prompt twice in a row (a real, unremarkable pattern) will have its first turn's offer silently vanish from every offer-based statistic (`hit@k`, `offered-turn conv/dodge`, per-skill offer→take), and the second turn's numbers absorb it. Given `skill-usage-audit`'s entire raison d'être is auditing these exact numbers post-config-change, a silent join collision undermines the "the real compliance signal is offered-turn conv/dodge" claim (`analyze.py:300-301`) for any contaminated session.

---

### 🟡 3.2 `doctor.py`'s "Read-only by default" claim is violated by `check_ledger()`

**File:** `scripts/doctor.py:10` (docstring) vs `scripts/doctor.py:358-365`

Docstring: `"""... Pure stdlib. Read-only by default. With --fix it attempts ONLY fast, safe repairs: ..."""` (`scripts/doctor.py:10`).

`check_ledger` runs unconditionally as part of `CHECKS` (`scripts/doctor.py:469`) on every invocation, `--fix` or not:
```python
def check_ledger():
    try:
        LOGDIR.mkdir(parents=True, exist_ok=True)     # doctor.py:360
        writable = os.access(LOGDIR, os.W_OK)
```
`Path.mkdir(parents=True, exist_ok=True)` **creates the directory tree on disk** (`~/.claude/skill-telemetry/logs` by default) as a side effect of a plain, no-`--fix` `python3 scripts/doctor.py` run. This is a real filesystem mutation, not a "check". It's low-risk (an empty log directory), but it directly contradicts the module's own stated contract ("Read-only by default") and the `skill-concierge:doctor` SKILL.md's framing of step 1 as `"**Diagnose (read-only)**"` (`skills/doctor/SKILL.md:17`). Worth either downgrading the docstring claim or making the mkdir conditional/lazy (only inside the `--fix` path, or only reporting missing-dir as WARN without creating it).

---

### 🟡 3.3 The embed-shim sidecar has no freshness check — a silent staleness vector `doctor.py` doesn't catch, parallel to (but *not covered by*) the venv landmine

**Files:** `setup.sh:58-72`, `scripts/doctor.py:165-192` (compare)

`doctor.py` explicitly diagnoses one class of staleness — the stable venv's copied engine going stale after `/plugin update` — with a whole dedicated check and a documented landmine writeup:
```python
def check_engine_freshness():
    """Does the engine CODE the MCP actually runs match the DEPLOYED plugin source?
    Landmine (ADR-0004, ADR-0013): the MCP launcher EXECs `skill-search` from the STABLE
    venv, where the engine is COPIED into site-packages by setup.sh — not an editable
    install. So `/plugin update` ships new code into the version-pinned cache but NEVER
    updates the venv copy...                                          # doctor.py:165-176
```
But the embed-shim sidecar (a second copy of the *same* vendored engine, baked into a Docker image — `Dockerfile:15-16`: `COPY vendor/skill-search /app/skill-search` / `RUN pip install --no-cache-dir /app/skill-search "fastembed==0.8.0"`) is subject to the **exact same class of staleness**, and `setup.sh` explicitly skips rebuilding it whenever it's already up:
```bash
if ! curl -s -m 2 "http://127.0.0.1:$EPORT/health" >/dev/null 2>&1; then
  docker build -t "$EIMAGE" "$ROOT"
  ...
else
  echo "  embed shim already listening on 127.0.0.1:$EPORT — leaving it."   # setup.sh:71
fi
```
There is **no check in `doctor.py`'s `CHECKS` list** (`scripts/doctor.py:468-470`) that compares the running shim's baked engine/model against the current vendored source, the way `check_engine_freshness` does for the venv. Re-running `./setup.sh` after a plugin update — the exact remediation doctor recommends for venv staleness — will **not** refresh the shim if it's already listening, so a code or model change to `scripts/embed_server.py` or the vendored `skill_search` package can silently keep serving from the old image indefinitely, with nothing in the health-check matrix ever turning red (or even WARN) to reveal it.

---

### 🟡 3.4 `driftcheck.py`: mirror-check exception handling is narrower than source-check exception handling — a malformed mirror spec crashes the whole run instead of reporting one drift

**File:** `scripts/driftcheck.py:111-124`

```python
def check_facts(root, facts):
    for fact in facts:
        name = fact.get("name", "?")
        try:
            ssot, where = _extract_source(root, fact["source"])
        except Exception as e:                                    # driftcheck.py:116 — catches ANY exception
            drift(f"{name}: cannot derive SSOT — {e}")
            continue
        info(f"{name}: SSOT = {ssot!r} (from {where})")
        for mir in fact.get("mirrors", []):
            try:
                _check_mirror(root, name, ssot, where, mir)
            except FileNotFoundError:                              # driftcheck.py:123 — catches ONLY this
                drift(f"{name}: mirror file not found: {mir['file']}")
```
The SSOT-extraction path deliberately catches `Exception` broadly (any bad regex, missing key, subprocess failure becomes a clean `drift()` line and the tool continues). The mirror-check path only catches `FileNotFoundError`. A mirror entry with a malformed regex (`re.error`), a missing `"regex"`/`"file"` key (`KeyError`), or any other exception **propagates uncaught and crashes the entire driftcheck run** with a Python traceback instead of the tool's own designed failure mode ("each mismatch printed", per the module docstring at `driftcheck.py:21`: `"Exit 0 = everything in sync. Exit 1 = drift (each mismatch printed)."`). This is a config-parse fragility: a single bad mirror entry anywhere in `driftcheck.json` takes down every other fact's reporting in the same run, rather than degrading gracefully to "N problems" like the rest of the tool is designed to do. (Not currently triggered — I verified the live `driftcheck.json` config is well-formed and all `paths_exist`/version-mirror entries currently resolve and match; see §4.)

---

### 💭 3.5 `check_qdrant`'s "stopped" label is imprecise for a container that was never created

**File:** `scripts/doctor.py:100-106`, `214-225`

```python
def _qdrant_container_running():
    """True/False if docker is present; None if docker is unavailable."""
    docker = shutil.which("docker")
    if not docker:
        return None
    r = _run([docker, "ps", "--format", "{{.Names}}"])   # doctor.py:105 — NOT `-a`, only RUNNING containers
    return QNAME in r.stdout.split()
```
`docker ps` (no `-a`) only lists running containers, so a container that was **never created** and one that exists-but-is-stopped are indistinguishable — both yield `running is False`, and `check_qdrant` reports `detail=f"container '{QNAME}' is stopped"` (`doctor.py:220`) even when it never existed. Low severity: `fix_docker_start` (`doctor.py:475-484`) still surfaces Docker's own error text if `docker start` fails on a nonexistent container, so the auto-fix path degrades gracefully — this is purely a misleading diagnostic message, not a functional bug.

---

### 💭 3.6 Two different "skill catalogue" sources of truth between `apply-overrides.py` and `analyze.py`

**Files:** `scripts/apply-overrides.py:34-42` vs `scripts/analyze.py:59-86`

`apply-overrides.py` discovers the skill set from disk via the vendored discovery function: `sys.path.insert(0, str(VENDOR)); from skill_search.skills_discovery import discover_skills` (`apply-overrides.py:40-41`) — this is what decides every skill's on/name-only budget. `analyze.py`'s `known_skill_ids()` instead scrolls the **live Qdrant index** (`analyze.py:64-84`) to split manual invocations into "real skill" vs "built-in", explicitly citing this as a fix for a past drift bug: `"""...so the manual real-skill-vs-builtin split can't drift from what the retriever knows (kills the old 585/508/512 library.json drift)."""` (`analyze.py:60-62`). These are two different SSOTs answering "what skills exist" — disk-discovery vs. index-contents — that can disagree whenever a skill is added/removed on disk but not yet reindexed, or present in the index but removed from disk. Not a bug in either script individually, but worth naming since both docstrings independently claim to be the drift-proof source.

---

## 4. Confidence + gaps (what I could NOT verify)

- **`driftcheck.json`'s currently-live state** — I confirmed (via read-only `ls`/`grep`, not by running driftcheck.py) that all 18 `paths_exist` entries currently resolve, the `version` fact's SSOT (`plugin.json` = `0.12.0`) matches all three mirrors (`marketplace.json`, `CHANGELOG.md`'s first numeric `## [x.y.z]` entry — correctly skipping `## [Unreleased]` — and `README.md`'s `` `0.12.0` **published** `` line), and both `command_checks` (`check_doc_parity.py`, `check_skill_list_parity.py`) would currently pass — I verified their logic by reading source and grepping the exact strings/tokens they match against (`AGENTS.md:55` / `CLAUDE.md:11` for doc-parity; `AGENTS.md:25`'s brace list vs the 4 `skills/*/SKILL.md` directories on disk for skill-list-parity) rather than executing them, per the read-only constraint. I did **not** execute `driftcheck.py`, `doctor.py`, or `setup.sh` themselves.
- **`config/keep-off.json`** (`keep_off: []`, `window_offered_turns: 71`) — I read it but did not verify `build_keep_off.py` (not in scope) actually reproduces this file from the ledger; taking its own `"_note"` at face value.
- **`config/deterministic-routes.json`** — currently `routes: []`, gated by `ENFORCER_DETERMINISTIC=1` per its own `_note`; I did not read `hooks/scripts/enforcer.py`'s consumption of this file beyond confirming the `AUTHORIZED_SKIP_MARKER` contract (out of my assigned scope beyond that one cross-check).
- I did not read `vendor/skill-search/skill_search/skills_discovery.py`, `scripts/build_prompt_intent.py`, `scripts/enrich_index.py`, `scripts/embed_server.py`, or `scripts/build_keep_off.py` — cited only where their *callers'* (doctor.py/setup.sh/apply-overrides.py) contracts with them are visible from the scoped files.
- Severity ranking (§3) reflects correctness/fidelity impact only, per the assignment; I did not weigh over-engineering (explicitly another agent's scope).

---

Status: DONE_WITH_CONCERNS
Summary: Read every file in scope plus the two driftcheck command-check scripts and the enforcer.py cross-file contract; the telemetry-discipline claims in AGENTS.md (authorized_skip separation, epoch-scoping-as-discipline) hold up against the actual code. Found one real correctness bug (analyze.py's offer→turn join can misattribute offers on duplicate-prefix prompts within a session) plus three fidelity/robustness gaps (doctor.py's "read-only by default" contradicted by check_ledger's mkdir; the embed-shim has no freshness check parallel to the venv's; driftcheck.py's mirror-exception handling is narrower than its source-exception handling) and two low-severity notes.
Concerns: The analyze.py join bug (§3.1) is the one finding I'd want a second pair of eyes on before treating as certain — I traced the dict-overwrite logic carefully but did not have a live ledger with a genuine duplicate-prompt session to reproduce it against.
