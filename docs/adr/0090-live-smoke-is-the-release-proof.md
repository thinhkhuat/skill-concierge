# 0090 — A live smoke turn per harness is the release proof; hook definitions are pinned

- Status: accepted
- Date: 2026-10-10
- Deciders: Thinh ordered "work on proper solutions for those problems … propose your plan" (2026-10-10); the plan (`plans/261010-1859-proof-of-life-and-release-hardening/plan.md`) ran on its recommended options after his decision prompt went unanswered, under his standing never-block rule. Awaiting his review.
- Relates to: ADR-0072 (installers fail closed), ADR-0089 (OpenCode v2 live fixes). Changes the release order only;
  no earlier decision is reversed.

## Context

Doctor checks that files and config exist. It does not check that a harness runs the concierge. Two failures got past
a green doctor:

1. **OpenCode.** The plugin failed to load through two releases while doctor's OpenCode row stayed green (ADR-0089).
2. **Codex.** Codex has not run the per-turn enforcer since 0.59.0. That release raised the enforcer hook timeout from
   5 s to 10 s (commit `88a01c0`). Codex runs a plugin hook only while the hook's definition matches the hash the user
   trusted (`~/.codex/config.toml`, `[hooks.state]`). A changed definition is skipped silently until the user trusts it
   again. Codex has no command-line way to do that. Evidence: with a `python3` shim on PATH, Codex started `ledger.py`
   and never `enforcer.py`; with `--dangerously-bypass-hook-trust` the enforcer ran and wrote its offer row
   (`plans/261010-1859-proof-of-life-and-release-hardening/_RESEARCH_ARTIFACTS/probe-codex.txt`).

The old release order also pushed first and installed after, so a broken release reached GitHub before anyone ran it.

Some harnesses could not be observed at all. Command Code's print mode (`cmd -p`) never calls a mod's `transformInput`,
so headless turns ran without the enforcer. The DSH plugin dropped `search_skills` calls, so no DSH search row existed.

## Decision

1. **Release order.** Bump versions, run `python3 scripts/driftcheck.py driftcheck.json`, commit,
   run `adapters/install-all.sh`, push only when it ends green. `install-all.sh` installs the local commit into every
   harness and then runs the smoke, so a red smoke never reaches GitHub. Doctor stays a precondition; the smoke is the
   proof.
2. **One live turn per harness.** `scripts/smoke.py` runs one headless turn for each harness, in its own empty temp
   folder with its own `SKILL_CONCIERGE_LOG`. Nothing reaches the live ledger, badges or auto-promotion. The prompt
   asks the model to call `search_skills` once and name the top result.
3. **The pass rule is an offer row and a search row.**
   - The `offer` row is written by the per-turn enforcer. Its `band` must be `offer`, `jev_skip`, `getaway`
     or `intent_skip`: each is decided after the embedding and the index lookup, so it proves retrieval ran. Early-exit
     bands (`negation`, `harness_skip`, `selfref_skip`, `consult_route`) fail, because they never touch the index, and
     so does any row carrying an outage fallback (`embed_timeout`, `embed_down`, `qdrant_down`). The smoke prompt is neutral for this reason: an earlier prompt that said "do not invoke any
     skill" took the negation exit, and a broken index still passed.
   - The `search` row proves the skill-search tool reached the model and the post-tool hook logged the call.
   - A `turn` row does not count. `hooks/scripts/ledger.py` writes it without the enforcer, so a harness whose
     enforcer is dead (Codex since 0.59.0) still produces one.
   - A missing command line is FAIL. ZCode has no command line, so it is UNPROVEN; the run fails unless the caller
     names it as advisory (`--advisory`, default `$SMOKE_ADVISORY`). An advisory harness still runs and prints its
     FAIL or UNPROVEN row; it only stops blocking the release. Thinh set `SMOKE_ADVISORY=codex,dsh,zcode` on his
     machine on 2026-10-10 ("relax the procedural check on those 3"), while Codex awaits a hook re-trust and DSH a
     valid DeepSeek key.
4. **OpenCode runs through its HTTP API.** The smoke starts a fresh private `opencode serve` (port
   `SMOKE_OPENCODE_PORT`, default 4473) and drives it over HTTP, because `opencode run --server` sometimes stalls
   before it creates a session (three stalls on 2026-10-09; the HTTP API never stalled). A fresh server connects its
   MCP servers after the session's folder is first used, and a model call made before that has no `search_skills` tool.
   The smoke waits until skill-search reports connected for the folder, then creates the session.
5. **Every harness must be observable in the ledger.** Command Code's mod governs only in `transformContext`, which
   runs in print mode and the TUI alike (`transformInput` is skipped by `cmd -p`); the DSH plugin logs
   `search_skills` calls, and DSH and OMP log nothing for a failed or blocked call; OpenCode turn rows carry
   `parent_lookup: "pending"` when the turn was governed before the subagent check landed, a landed lookup logs
   `child` true or false, and `scripts/analyze.py` prints both counts.
6. **Hook definitions are pinned.** `tests/test_hook_definitions_pinned.py` hashes the whole `hooks` block of
   `hooks/hooks.json`, so a changed command, matcher or timeout, a moved group or a new field all count. Changing one fails the test until the author updates the pin and adds a
   `CHANGELOG.md` line telling Codex users to open Codex and trust the changed hooks again. The guard cannot make Codex
   trust a hook; it makes the cost of a change visible.
7. **Installers that write their own path refuse a plugin-cache copy.** The Cline, Command Code, DSH and OMP (dev
   mode) installers exit 1 when run from `*/plugins/cache/*`, because the next plugin update deletes that copy
   (`tests/test_installer_cache_guard.py`). OMP dev mode keeps one `extensions` entry when the checkout moves. This is
   the rule ADR-0089 gave OpenCode, applied to the other four.

## Rejected alternatives

- **Count a `turn` row as a pass.** Rejected: it is written by the ledger hook alone and hides a dead enforcer.
- **Make doctor run a model turn.** Rejected: doctor is read-only and fast, and runs after every repair. A model call
  per harness belongs in the release step.
- **Push first, install after.** Rejected: it ships the break before it is seen.
- **Run the smoke against the live ledger.** Rejected: smoke turns would change badges, auto-promotion and the
  per-epoch metrics in `docs/epoch-watch.md`.

## Consequences

- Each release spends one short model call per harness, on that harness's own configured model. A harness whose
  provider cannot answer fails the release until it is fixed or the run is told otherwise.
- The smoke needs every harness CLI on PATH. It reports a missing one as FAIL, not as a skip.
- The Codex hooks stay skipped on any machine whose user has not trusted them again. The smoke's Codex row turns FAIL
  there and prints that hint (`HINTS` in `scripts/smoke.py`).
- Known limit, unproven cause: one OpenCode smoke run in 14, after the wait was added, ended with the model reporting no
  `search_skills` tool. Before the wait, 2 of 7 runs produced no assistant message for 300 s; a plain prompt passed 12
  of 12 with and without the plugin (`_RESEARCH_ARTIFACTS/opencode-hang/ab-results.jsonl`). A red OpenCode row should
  be re-run once before it is read as a regression.
- Long-running OpenCode services are not affected the same way as a fresh server. That was not re-probed for this ADR.
- The pending count alone is an upper bound on misgoverned child sessions; the `child` rows give the real number.
- A smoke run must not write live state. On 2026-10-10 smoke runs emptied the live 🔥 badges and external-take counts
  through the session-start `auto_promote.py`. It now writes beside the ledger it reads, and the smoke seeds throttle
  stamps in each run's folder (`docs/caveats.md` §30).

## Revert

Remove the `scripts/smoke.py` call from `adapters/install-all.sh` to return to doctor-only verification. Delete
`tests/test_hook_definitions_pinned.py` to drop the hook pin. The cache-copy guards are short, independent blocks in
each installer.
