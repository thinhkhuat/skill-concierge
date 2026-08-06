# Journal — the engine-build identity arc (v0.20.6 → v0.20.8)

2026-08-06 evening → 2026-08-07 early. Three releases, one bug class: **a diagnostic that
answers a question it cannot actually observe.** Each release fixed the previous one's version
of that mistake. Writing the shape down because it recurred three times in one night, and twice
the guard meant to catch it was itself an instance of it.

## The underlying mechanism

A long-lived MCP server keeps executing the engine bytes it imported at startup. Replace the
venv engine underneath it and the server and every fresh process now parse the same `SKILL.md`
files with **different parsers**, deriving different `_disk_signature()` values from an
unchanged disk. Whichever writes the manifest last hands the other a permanent, false
`disk changed since last index — run reindex()`. The reindex hands it straight back.

Nothing about the disk is wrong. The disk is the one thing that did not move.

## v0.20.6 — name the writer

`_write_manifest` began stamping `engine: _ENGINE_BUILD` (md5 of `server.py` +
`skills_discovery.py`, first 12 hex). `_engine_drift()` compares. On mismatch `_health()` sets
`stale` to `None` — unknowable across builds, not negative — and says restart, not reindex.

Two decisions that carried the whole arc:

- **`_ENGINE_BUILD` is computed at import, deliberately.** A lazy call would hash whatever is on
  disk *at call time*, which after a venv swap is the NEW code — precisely the code the process
  is not running. The mechanism would be inert with no test failing.
- **A sentinel on either side is never drift.** Legacy manifests with no `engine` key, and the
  `"unknown"` fail-open value, are treated as "cannot tell". Accusing them would relocate the
  same permanent false alarm one field over.

Also shipped `check_running_engine` in doctor, to cover the process dimension the file-vs-file
freshness check is blind to. That check was the next bug.

## v0.20.7 — identity, not timestamps

`check_running_engine` dated each live process against `max(st_ctime, st_mtime)` of the venv
engine's `*.py`. `setup.sh` re-copies the engine on **every** run — it is idempotent by design —
so those timestamps advance even when the bytes do not. First deploy of 0.20.6 proved it within
twenty minutes: `server.py` md5 identical before and after, mtime pushed to 23:30:54, a server
started 23:28:43 → three false accusations, while the engine's own `health()` correctly said
`stale: false`. Two diagnostics of one fact, disagreeing.

Timestamps were a proxy for identity. The fix was to stop proxying: each MCP server publishes
the build it runs to `~/.cache/skill-search/servers/<pid>.json` at startup, and doctor **looks it
up**. A no-op re-copy moves no build id, so it is invisible to the check by construction.

Supporting decisions, each one a failure mode closed:

- `started_at` in every record guards pid reuse — a dead server's leftover record must not lend
  its build to whatever process inherits the number. Same false accusation, one layer down.
- The window is **one-sided**: tight floor, generous ceiling. A record is stamped *after* the
  launcher's prelude, which contains the ADR-0018 pip resync — longest exactly when a plugin
  update makes drift matter most. A symmetric window filed a healthy server as unprovable for
  its whole life.
- CLI runs are excluded by their flags. A `skill-search --reindex` runs for minutes and matches
  the same binary path but writes no record; counting it reports a permanent unknown-build
  server that is really just a busy reindex.
- Pruning keys on **pid liveness**, not the `ps` scan. The records dir is machine-wide while `ps`
  matches only this venv's binary, so scan-keyed pruning would delete a second install's live
  record.
- Fail-open N/A against an engine too old to publish an id, so upgrading doctor ahead of the
  venv reports nothing rather than everything.

Review caught a CRITICAL before the tag: the `--health` memo I added was module-scoped and never
invalidated, so `doctor --fix` replayed the pre-fix report and would exit 1 on a system it had
just repaired.

## v0.20.8 — the message must not claim what the emitter cannot see

One symptom, two causes, **opposite** remedies:

| State | Remedy |
|---|---|
| a server still live on the old build | restart — a reindex writes our build and that server hands the mismatch back |
| manifest left over from the previous release, no old server alive | reindex — it re-stamps and clears |

0.20.6's text asserted the first. **Every engine upgrade lands in the second**, because
`_ENGINE_BUILD` hashes those two modules, so changing the engine at all makes the previous
release's manifest instantly "drift". Observed on 0.20.7's own deploy: `Running engine: 3 servers
publish no build id` printed directly above `Retrieval health: a live MCP server is on an older
build; restart (reindex will not fix it)`.

My first correction traded one error for a worse one, and the review caught it. Offering
*"run `reindex()` if every server is on this build"* reads as an instruction to **the model** —
`_staleness_warning` rides in every `search_skills` reply — and `reindex()` is an MCP tool that
executes **inside the process whose build is in question**. Build ids are unordered md5 hashes,
so a server cannot tell whether its own build is the newer or the older one. If it is the older
one, reindexing there re-embeds with the stale parser and re-stamps the manifest *backward*,
flip-flopping against the SessionStart rebuild. The sentence 0.20.8 deleted had been the only
brake on that.

Offering it conditionally is no safer: the model cannot evaluate the condition, it just calls the
tool.

**Resolution — put the answer where the evidence is.** The engine states the observation and
names no remedy. doctor holds the live-server records in the same check pass, so `_drift_remedy`
resolves which cause applies, names the specific pids, and prints only that remedy.
`fix="reindex"` is returned for exactly one state: a fleet proven entirely on the current build.
Drift pids, unknown pids, absent evidence, and any co-occurring issue all stay `fix=None` —
auto-reindexing past a live old server is the v0.20.6 defect re-armed.

## The lesson that outlasts all three fixes

**Twice, a guard passed while the code it guarded was broken, because it exercised a *helper*
instead of the *wiring*.**

1. I renamed the cache-reset helper and left `run_all()` calling the old name. `--selftest` called
   the helper directly, stayed green, and doctor died with a `NameError` on the first real run.
2. The `check_engine_health → _drift_remedy` seam was untested. Review reproduced a plausible
   mis-wire reporting *"pid 11, 22 still run an older build"* on a **clean** fleet — the exact
   failure the release existed to retire, one function up, with the selftest green.

Both are now driven through the real entry point, and the reset guard is verified by a **negative
control**: remove the `_reset_pass_caches()` call and the selftest fails; restore it and it
passes. An assertion nobody has watched fail is not evidence.

Second lesson, process rather than code: both 0.20.6 and 0.20.7 were verified against the repo
tree, shipped, and *then* found broken by dogfooding the deployed artifact. Before tagging
0.20.8 I rehearsed all four reachable states against real `ps`, real records and a real manifest
— including full `--fix` convergence — because three of the four had only ever been unit-tested.
That rehearsal is where a 0.20.9 would otherwise have come from.

## Confirmation, unstaged

Minutes after 0.20.8 deployed, a server that predated the resync produced genuine drift on its
own:

```
[!] Running engine     pid 75244 runs a DIFFERENT engine build than the one on disk
[!] Retrieval health   pid 75244 still runs an older build, so a reindex would hand
                       the mismatch back. Restart Claude Code
```

Two rows, one pass, same pid, agreeing — auto-fix correctly withheld. The contradiction the arc
set out to end, resolved on a case nobody arranged.

## Known, deliberately unfixed

Ranked LOW by review and held rather than cascaded into a fourth release:

- `_drift_remedy` says "still runs an **older** build" from evidence that only proves *different*;
  `check_running_engine` correctly says "DIFFERENT". Two rows disagreeing in kind — the miniature
  of the bug this arc fixed. One word.
- "Proven clean" is scoped to this venv's servers while the manifest is machine-wide. Measured as
  theoretical here (one install, one binary path, zero alive records unmatched by `ps`), but
  `_prune_server_records`'s own comment asserts the opposite reasoning.
- `_health_run`'s docstring still references the renamed `_reset_health_memo`.
- The unknown branch advises "if it persists, reindex", while the persistent causes it names
  (unwritable records dir, `SKILL_SERVER_RECORDS` seam mismatch) are not fixed by a reindex.
- No lock around concurrent reindexes. `_write_manifest` is now atomic; the lock is not.
