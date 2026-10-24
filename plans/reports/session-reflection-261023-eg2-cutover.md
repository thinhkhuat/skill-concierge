# Session Reflection: 2026-10-23

## Summary Statistics
- Session date range: 2026-10-22 20:17 ICT to 2026-10-23 01:26 ICT (JSONL timestamps are UTC: `2026-10-22T13:17:39Z` to `2026-10-22T18:26:29Z`). Cross-check: the index-owner log inside the arc prints `22:52:35 pid=13693 ready` for a rebuild the summary shows starting at `15:52` UTC — UTC+7 confirmed.
- Messages analyzed: 3,010 summary events (1,938 assistant rows, 1,072 user rows) from `/tmp/session-summary-eg2.jsonl`, which concatenates 11 session transcripts. After de-duplicating repeated rows, 733 distinct tool calls and 388 distinct assistant text blocks.
- In-scope arc tool calls: **443 distinct** in the `13:00–18:30Z` window — **371 Bash (84%)**, 16 Edit, 15 Read, 12 Skill, 9 ToolSearch, 5 Write, 4 `search_skills`, 3 `web_search`, 2 Agent, 2 SendMessage, 1 `get_skill`, 1 `web_fetch`, 1 ListAgents, 1 AskUserQuestion.
- In-scope user turns: ~22 (the embedder-research request through "close out and write session handoff pls & session-reflection-analysis too").
- Major inefficiencies found: **9** (3 high, 4 medium, 2 low).
- Out of scope, deliberately excluded: the limpet `0.7` / `0.5` threshold thread, the claude-hud park/restore thread, the mnemosyne Desktop-wiring thread (all `2026-10-17` / `2026-10-20` or interleaved noise from parallel sessions).

**Evidence limits, stated plainly.** The summary carries tool *names* and result *lengths* only — no tool arguments and no result text. Anything below that names a command, a file path or a line of code comes from the assistant's own 300-character text blocks, which are truncated. Two consequences: (a) I cannot count "same file re-read 5+ times" directly, because file reads went through Bash and Bash arguments are absent — the Bash share (84%) is the closest proxy; (b) the caller's claim that a CHANGELOG was corrected is **UNVERIFIED** in this data — I can see a README correction and two retracted claims, no CHANGELOG line. Findings resting only on the caller's prior knowledge are labelled as such.

---

## Proposed Improvements

### High Priority

#### 1. A gate oracle that keys on failure-only output turns a PASS into a FAIL

**Problem observed**: The G5 gate on the Command Code smoke was read as failing while the smoke itself had passed. Byte-exact, from the arc at `17:40:31`:

> **My oracle is at fault, not the system.** The smoke itself reports `[✓] commandcode PASS  49 s  offer + search` — the real pass. My checker grepped for `evidence kept:`, which the smoke only emits **on failure**, so a pass looked like zero rows.

Confirmed at the source, `scripts/smoke.py`:

```python
        if work and status == "PASS":
            shutil.rmtree(work, ignore_errors=True)
        elif work:
            print(f"      evidence kept: {work}")
```

`evidence kept:` is printed only on the non-PASS branch. Any checker grepping for it sees "zero rows" on a green run.

This was not a one-off. The same class of faulty oracle fed the 23-minute wrong-root-cause chase in finding 3: `17:26` "Still 0 — the agent still fabricates with that prompt", `17:29` "Tool called (real JSON), offer+turn logged, **still 0 search rows**". A second, milder instance of a self-contradicting signal: `17:03:51` "`apply-overrides` wrote `54 on / 909 name-only (963 discovered)` and then still reported drift — that contradiction is the thing to understand before I claim G2."

Cost: one full G5 verification cycle (~4 min) after the real fix, plus it kept a wrong diagnosis alive for two more rounds.

**Proposed solution**:

Make the marker symmetric, so PASS and FAIL both emit it. Patch `scripts/smoke.py`:

```python
        if work and status == "PASS":
            shutil.rmtree(work, ignore_errors=True)
            print(f"      evidence kept: <pass — scratch {work} removed>")
        elif work:
            print(f"      evidence kept: {work}")
        else:
            print(f"      evidence kept: <none captured>")
```

A gate may now grep `evidence kept:` and get a row on every outcome.

Then the durable rule, added to `AGENTS.md` → *Guardrails*:

```markdown
**A gate must key on what the tool prints on PASS.** A marker that only appears on
failure is not an oracle: grepping it reports a green run as empty. Before writing a
checker, open the tool's source and find the line that prints on the success path; grep
that. If the success path prints nothing, extend the tool to print a stable marker on
both outcomes, then gate on the marker. Applies to smoke, doctor, driftcheck and install
output alike. A gate that contradicts the tool it watches is a defect in the gate, never
in the system — fix the gate first, then re-run.
```

And the landmine record, appended to `docs/caveats.md`:

```markdown
## §32 — `evidence kept:` is a FAILURE-ONLY line; grepping it reads a PASS as empty (2026-10-22 incident)

`scripts/smoke.py` deletes its per-harness scratch dir on PASS and prints
`      evidence kept: <path>` **only** on the non-PASS branch, so a checker grepping it
reports zero on a harness that passed. Observed live on the 0.72.x Command Code gate:
the smoke printed `[✓] commandcode PASS  49 s  offer + search` while the checker read
"0 rows", and the false FAIL extended a root-cause chase that was already wrong.

Fix the generator, not the checker: `smoke.py` now prints the marker on every outcome.
Until your copy has it, gate on `smoke: OK` / `smoke: FAIL` and the `[✓] harness PASS`
row, never on `evidence kept:`.

**Class rule:** before grepping any tool's output in a gate, read the source line that
emits your marker and confirm it runs on the success path.
```

**File to modify**: `scripts/smoke.py`, `AGENTS.md` (Guardrails), `docs/caveats.md`

**Cost**: ~30 minutes. The `smoke.py` change alters a printed line, so any existing external checker that already greps `evidence kept:` for absence needs a look — `tests/` should be swept for the same grep. One new caveat section.

**Benefit**: Removes a whole failure class from release gating. Directly recovers ~4 min here and, more importantly, stops a false FAIL from steering diagnosis — in this arc that steering cost roughly 20 of the 31 minutes spent on the Command Code defect (finding 3). Recurs on every release, ~2 releases/day in this repo's recent history.

---

#### 2. Long index writes are not protected from the actions that kill them

**Problem observed**: Rebuild #1 was destroyed 4 minutes in by the release bookkeeping that was running alongside it. The owner log, quoted in the arc at `16:02:54`:

```
22:52:35 pid=13693 ready ... model=embeddinggemma-2:270m
22:56:35 pid=13693 venv stamp rewritten ('0.71.3' -> '0.72.0'): exiting for the new code
22:57:04 pid=93098 ready ... claude_skills:
```

And the agent's own framing:

> **Rebuild failed — cause found, and it is my sequencing error, not a crash.**

Timeline: rebuild #1 started `15:52:35` UTC, killed `15:56:35`, diagnosed `16:02:54`, rebuild #2 completed `16:12:50`. Cost ≈ 4 min of destroyed work + ~6 min diagnosis + a full ~15.5 min rebuild re-run ≈ **20 min**, plus writing the rule to two governing files at `16:08–16:11`.

The rule now exists — `AGENTS.md:54` and `CLAUDE.md:10`, "Never bump versions while an index rebuild is in flight." But it is prose. Nothing stops the next session from doing the same thing, and the arc shows the failure is a *sequencing* mistake made while multitasking, which is exactly the kind prose does not catch.

**Proposed solution**:

A deterministic PreToolUse(Bash) guard, modelled on the repo's existing `scripts/openwiki_parity_guard.py` (same shape, same fail-open posture, same wiring style). New file `scripts/rebuild_in_flight_guard.py`:

```python
#!/usr/bin/env python3
"""
rebuild_in_flight_guard.py — PreToolUse(Bash) gate: no version bump while an index write is live.

A version bump rewrites the venv stamp. The index owner reads a stamp change as a
restart signal and exits — dropping the in-flight writer's store connection and leaving
a partial collection. Observed 2026-10-22: rebuild #1 died 4 minutes in when release
bookkeeping bumped 0.71.3 -> 0.72.0 during the pass, costing the full rebuild again.
AGENTS.md forbids it in prose; prose does not catch a sequencing mistake made while
multitasking.

Fires on PreToolUse for Bash. Non-manifest commands exit 0 silently. A manifest edit
while a rebuild/reindex worker is live is denied, with the reason and the wait.
Deterministic, no LLM, sub-second. FAILS OPEN on any internal error (repo guard
culture: openwiki_parity_guard.py, graph_staleness_notice.py). "Live" = a process whose
argv matches a reindex/rebuild entry point; neither signal available -> proceed.
"""
import json
import os
import re
import subprocess
import sys

VERSION_MANIFESTS = (
    ".claude-plugin/plugin.json",
    ".claude-plugin/marketplace.json",
    ".codex-plugin/plugin.json",
    "package.json",
    "adapters/opencode/plugin/package.json",
    "setup.sh",
)

WORKER_PATTERNS = (
    r"[--]rebuild",
    r"[--]reindex",
    r"index_owner\.py",
    r"trigger_filter\.py\s+reindex",
)

BUMP_HINT = re.compile(r'version|__version__|"0\.\d+', re.IGNORECASE)


def _emit_deny(reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


def _touches_manifest(cmd: str) -> str | None:
    for m in VERSION_MANIFESTS:
        if m in cmd and BUMP_HINT.search(cmd):
            return m
    return None


def _live_worker() -> str | None:
    try:
        out = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True,
                             text=True, timeout=3).stdout
    except Exception:
        return None
    for line in out.splitlines():
        if "rebuild_in_flight_guard" in line:
            continue
        for pat in WORKER_PATTERNS:
            if re.search(pat, line):
                return line.strip()
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    cmd = (payload.get("tool_input") or {}).get("command", "")
    if not _touches_manifest(cmd):
        return 0
    worker = _live_worker()
    if not worker:
        return 0
    _emit_deny(
        "Blocked: a version/manifest edit while an index write is in flight. "
        "The bump rewrites the venv stamp; the index owner treats that as a restart "
        "signal and exits, dropping the writer's store connection and leaving a "
        "partial collection (AGENTS.md, Setup & verification). "
        f"Live worker: {worker[:200]}. "
        "Finish or abort the rebuild first (wait for it, or stop the owner cleanly), "
        "then rerun. Override with REBUILD_GUARD=0 if this detection is wrong."
    )
    return 0


if __name__ == "__main__":
    if os.environ.get("REBUILD_GUARD") == "0":
        sys.exit(0)
    try:
        main()
    except Exception:
        sys.exit(0)   # fail open
```

Wiring, appended to the existing `PreToolUse` → `Bash` → `hooks` array in `.claude/settings.json`, alongside the three guards already there:

```json
    {
      "type": "command",
      "command": "F=\"${CLAUDE_PROJECT_DIR}/scripts/rebuild_in_flight_guard.py\"; [ -f \"$F\" ] || exit 0; exec python3 \"$F\"",
      "timeout": 10
    }
```

Plus the landmine record in `docs/caveats.md`:

```markdown
## §33 — A version bump is a restart signal to the index owner: it kills an in-flight rebuild (2026-10-22 incident)

The venv stamp is the owner's code-change detector. Rewriting it (`setup.sh`, a
version bump, `install-all.sh`) makes the running owner exit so the new code loads.
Any index write in flight loses its store connection mid-write and leaves a partial
collection. Observed: rebuild #1 died at 4 minutes (`22:56:35 venv stamp rewritten
('0.71.3' -> '0.72.0'): exiting for the new code`), costing the full pass again.

Remedy, in order: **wait** (a full rebuild is ~15 min for a 46k-point catalogue, an
incremental reindex seconds); **abort deliberately** if you must (stop the owner
cleanly, then bump); **never** run release bookkeeping "while it runs" on the same tree.

`scripts/rebuild_in_flight_guard.py` denies the bump while a worker is live
(`REBUILD_GUARD=0` overrides). It fails open; the `AGENTS.md` prose rule is the backstop
when the guard cannot see the worker.
```

**File to modify**: `scripts/rebuild_in_flight_guard.py` (new), `.claude/settings.json`, `docs/caveats.md`

**Cost**: ~1 hour. Two risks: (a) the process scan may miss a rebuild started through a wrapper whose argv carries no `--rebuild`, which is why the guard also reads owner health and why the prose rule stays; (b) `ps` parsing is macOS-flavoured — keep the failure path silent.

**Benefit**: Removes a 20-minute, data-threatening failure from the release path. The arc shows it fires exactly where the mistake is made (the Bash call that bumps), not at the post-mortem.

---

#### 3. A missing telemetry row was diagnosed twice as someone else's fault

**Problem observed**: The Command Code defect was diagnosed as agent behaviour before anyone read the ledger. The chain, with timestamps:

| Time (UTC) | Stated root cause | Verdict |
|---|---|---|
| `16:41:12` | "Same fabricated completion … still no name, still no search row" | agent fabricates |
| `16:38:55` | "**commandcode is the blocker.**" → advisory escape applied, push proceeds | harness defect |
| `17:10:59` | "Command Code exposes the tool as `mcp__skill-search__search_skills` — and it also has a *different* builtin named `search_tools`. The smoke prompt … is ambiguous" | prompt ambiguity |
| `17:13:18` | "Testing whether MCP tool calls work at all in `cmd -p` headless mode — if they do not, the agent has nothing to report" | headless tool withholding |
| `17:16:17` | "`--tools-all` … enable every tool, including the ones a headless run withholds" | tool withholding |
| `17:16:48` | "`verdict()` checks only the **ledger**, never the output — so a bare-name reply invites fabrication" | prompt design |
| `17:20:52` | "**Real root cause — not the agent at all.** 10 commandcode `offer`/`turn` events, **zero search rows**, even though prompt 3 returned genuine search JSON. The tool *was* called; the logging is what's broken." | logging |
| `17:22:17` | "Command Code has only 3 skill-concierge hooks wired … The **PostToolUse `ledger.py` hook is absent**" | missing hook — fixed, still 0 rows |
| `17:32:11` | "Command Code routes MCP calls through a **`codemode`** script tool … The matcher runs against `tool_name` = `codemode`, so `mcp__…` never matches" | **actual root cause** |

Cost: `17:09:24` → `17:40:31` = **31 min** to a trustworthy verdict, of which ~23 min sat on false root causes and ~4 min on the faulty oracle (finding 1). The first wrong frame also survived a session boundary and produced a real release decision — `SMOKE_ADVISORY` was set to unblock the 0.72.0 push at `16:49`, then had to be removed at `18:17` ("One cleanup the config itself calls for: `SMOKE_ADVISORY`'s own comment says *"remove a name once that harness passes."* Command Code now passes, so its advisory should go.").

The decisive evidence was available from the first probe: the ledger is skill-concierge's own telemetry, and it already showed `offer`/`turn` rows with zero `search` rows. Every earlier hypothesis — agent, prompt, headless mode, tool withholding — was a story about *behaviour*; the ledger was a measurement of *the logging path*.

Two parser mistakes compounded it: `17:22:01` "My parse missed nested hook entries — the structure is `{'hooks': [{...}]}`. Re-parsing properly." and `17:25:34` "My parser reads `matcher` off the inner command dict rather than the entry — verifying at the correct level."

**Proposed solution**:

(a) The landmine record — the code fix is already in tree (`hooks/scripts/ledger.py:78-79, 184-199`; `adapters/commandcode/install.sh:288-294`), so this documents the shape for the next harness:

```markdown
## §34 — Command Code routes every MCP call through `codemode`, so hook matchers never see the tool name (2026-10-22 incident)

Command Code's PostToolUse payload carries `tool_name: "codemode"` and the real
retriever call only inside `tool_input.code`:

```json
"tool_name": "codemode",
"tool_input": {"code": "const r = await tools[\"mcp__skill-search__search_skills\"]({...});"}
```

A matcher written against `mcp__.*skill[-_]search__(search_skills|get_skill)` therefore
never fires, and no `search` row is ever written — even when the tool ran and returned
real results. Symptom: the smoke's commandcode arm reports a turn with an `offer` row
and no `search` row, and the agent is an easy false suspect because it answers "the
name was already given" with nothing to show.

Two independent gaps were involved; both are now fixed for Command Code:

1. **The hook was never registered.** `adapters/commandcode/install.sh` registered only
   SessionStart and PreToolUse. `hooks/hooks.json` registers the PostToolUse `ledger.py`
   for plugin-native harnesses; Command Code was outside that. The installer now
   registers PostToolUse (`codemode|Skill|activate_skill|skill|read` -> `ledger.py`,
   and `skill_exclusions.py`).
2. **The matcher and the classifier disagreed on the tool name.** `ledger.py` now
   classifies `codemode` and extracts the retriever name from `_CODEMODE_NAME_RE` out of
   `tool_input.code`; the adapter matcher must reach `codemode` too.

**Diagnostic order for a missing `search` row — do this first, always:**

1. Read the ledger. If `offer`/`turn` rows exist and `search` rows do not, the tool may
   have run fine and the *logging* is broken. Do not blame the agent or the prompt.
2. Run one probe that requires the tool and **paste its raw output**. If raw output is
   real but a short answer is not, the defect is in the verdict path, not the caller.
3. Only then inspect the hook wiring: which events are registered for that harness, and
   what `tool_name` the payload actually carries (`.*` probe, then read the payload).

**Class rule:** a wrapper tool (codemode, a bridge, an aggregator) hides the inner tool
name from every matcher. When you add a harness adapter, prove the PostToolUse matcher
fires with a probe hook before trusting a green row.
```

(b) A deterministic diagnostic command, so step 1 costs one call instead of a hunt. New file `.claude/commands/sc-diag-search-row.md`:

```markdown
---
description: Diagnose a missing skill-search ledger row before blaming any agent or harness
---

Diagnose a missing `search` row in the skill-concierge ledger. Read-only. No edits.

Run, in this order, and report each output verbatim:

1. `python3 scripts/analyze.py --since "24 hours ago" | tail -60`
2. `python3 scripts/analyze.py --since "24 hours ago" --chains | tail -40`
3. Count by event type in the same window:
   `python3 -c "import json,sys,collections; c=collections.Counter(json.loads(l).get('ev') for l in open('logs/ledger.jsonl') if l.strip()); print(c)"`
4. For the harness under suspicion, list its registered hooks and print the matcher of
   every PostToolUse entry (watch for nested `{"hooks": [...]}` — read `matcher` off the
   entry, not the inner command dict).
5. One probe that requires the tool and must **paste raw JSON output**.

Then decide from the counts:

- `offer`/`turn` rows present, `search` rows absent → **the logging path is broken, not
  the caller.** Go to `docs/caveats.md` §34 (codemode / wrapper tool names) and check the
  PostToolUse registration for that harness.
- `search` rows present but `harness: null` → the row is written but unattributed;
  stamp the harness id in `ledger.py`'s classification.
- no rows at all → the hook is not registered for that harness; re-run that harness's
  installer and diff its settings against `hooks/hooks.json`.
- rows present and attributed → the agent really did not call the tool; the smoke prompt
  is the suspect (a bare-name reply invites a plausible story; "paste raw JSON" forces
  the call).

Report: the counts, which branch fired, and the one next action. Never report a
diagnosis that the counts do not support.
```

**File to modify**: `docs/caveats.md`, `.claude/commands/sc-diag-search-row.md` (new)

**Cost**: ~45 minutes. Downside: one more caveat section and one more command to keep current; the `analyze.py` invocations in the command assume `logs/ledger.jsonl`, which the repo already documents.

**Benefit**: The first 23 minutes of this defect's diagnosis were spent on hypotheses the ledger would have refuted in one read. A one-call diagnostic makes step 1 cheaper than storytelling. Recurs every time a harness's telemetry goes quiet — this repo runs 8 harnesses and adds adapters.

---

### Medium Priority

#### 4. A test fixture did not pin the default its branch depends on

**Problem observed**: `17:53:11`:

> **1761 passed, 1 failed** — and the failure is mine: `test_check_embed_parity_reports_a_clean_timeout_instead_of_hanging`, the function I changed earlier.

`17:53:35`:

> The test exercises the **fastembed** timeout path but never pins `BACKEND` — and since the default is now `ollama`, it falls into my new branch and returns FAIL on the model-name mismatch (`test-model` vs `embeddinggemma-2:270m`). The fixture is incomplete.

Two changes combined: the cutover flipped `SKILL_EMBED_BACKEND`'s default to `ollama`, and `check_embed_parity` gained a branch. The fixture pinned neither, so it silently walked into the other branch. It survived the earlier green runs at `15:50` ("Sweep is complete and consistent. Running the test suite before touching the index." / "59 passed") and surfaced only 1.5 hours later, at the commit gate.

Cost: two full suites (`17:46:36`→`17:53:11` and `17:53:56`→`18:00:36`, ~13 min total) plus diagnosis, and the 0.72.1 commit slipped past 18:00.

This is the class the cutover made visible: the repo has `ENGINE_ENV_KEYS` as the single list of engine settings that shape behaviour, and `tests/conftest.py` already scrubs Jev env before collection — but nothing pins engine defaults per test, so a default change re-routes existing tests without failing them.

**Proposed solution**:

An autouse fixture in `tests/conftest.py` that pins every branch-shaping engine default to an explicit test value, so a test that wants a specific backend must say so:

```python
import os
import pytest

# Engine defaults that select code branches. A test that depends on one MUST set it
# explicitly; otherwise this sentinel applies and the intended branch is not the one
# that runs (2026-10-22: test_check_embed_parity_..._hanging walked into the new ollama
# branch because its fixture never pinned BACKEND).
_ENGINE_BRANCH_DEFAULTS = {
    "SKILL_EMBED_BACKEND": "TEST_PIN_SENTINEL_BACKEND",
    "SKILL_EMBED_MODEL": "TEST_PIN_SENTINEL_MODEL",
    "SKILL_VECTOR_SIZE": "137",
}


@pytest.fixture(autouse=True)
def pin_engine_branch_defaults(monkeypatch):
    for key, sentinel in _ENGINE_BRANCH_DEFAULTS.items():
        monkeypatch.setenv(key, sentinel)
    yield
```

Plus the invariant as a Conventions bullet in `AGENTS.md`:

```markdown
- **Fixtures pin every default their branch depends on.** A test that exercises a
  code path selected by an engine flag (`SKILL_EMBED_BACKEND`, `SKILL_EMBED_MODEL`,
  `SKILL_VECTOR_SIZE`, anything in `ENGINE_ENV_KEYS`) must set that flag itself;
  `tests/conftest.py` supplies a sentinel so an unpinned fixture takes a value the
  product never uses. A product default change must not silently re-route an existing
  test into a different branch — it must fail it. If a test needs the real default,
  set it in that test and say why in the test name.
```

**File to modify**: `tests/conftest.py`, `AGENTS.md` (Conventions)

**Cost**: ~1 hour, and one risk worth naming: the sentinel will break any test that currently *relies* on the real default without pinning it. That breakage is the point — expect a handful of fixes on first run, each one a latent finding. Batch them as one commit.

**Benefit**: Removes a silent-failure mode from 1,764 tests. The observed cost was ~13 min of suite time at the release gate; the unobserved cost is larger — a default change that re-routes tests without failing them means green is not evidence.

---

#### 5. Self-checks with hand-guessed expected values produced six defects in one evaluation harness

**Problem observed**: Between `14:38` and `15:34` the recall-trial harness produced six defects of its own before it produced a usable number:

1. `14:38:51` — a fastembed pooling warning on the baseline arm would have made the trial compare against a non-live system. Caught: "Baseline validated: live stored vectors are cos=1.000000 against fresh embeds from this venv."
2. ~`14:44` — "30 of 970 'installed' names are blocklisted, and **one probe's entire `expect[]` is unreachable** (`handoff`, `ak-handoff` — the live path filters both via `_blocked`, `server.py:220`)."
3. `14:5x` — "my bug in the final rename: `np.save` appends `.npy`, so it wrote `emb_eg2_768.npy.partial.npy`" — reported as a dead embed job until the 134.9 MiB payload was found complete.
4. `14:5x` — "my self-check assertion contradicts its own next assertion".
5. `14:5x` — "Case D was a test-design error too: with only 4 docs the graded ones can't fall out of top-6."
6. `14:5x` — "Code is right, my hand-math was wrong — I mis-assigned the ideal order. Fixing the test to recompute NDCG from the observed ranking instead of a hand-guessed value." And a real metric bug: "`miss` only fired when a target was absent from the *entire* ranking, not when it fell outside top-6 — so a bad ranking looked better than it is."

Two roots run through all six:

- **Hand-written expected values.** Defects 4, 5 and 6 are all "I guessed what the number should be". The fix that actually landed — "recompute NDCG from the observed ranking instead of a hand-guessed value" — is the general rule.
- **The pool was not filtered through the production path before labeling.** Defect 2, and it fed the blind validator's later correction at `16:13`: "Pool sizes: I was wrong. 940 installed / 2,934 full after blocklist. I reported 970 / 2,966 — those are the counts *before* blocklist subtraction."

Separately, the harness itself was judged over-built. The read-only over-engineering audit at `15:43:55`:

> Total in scope: 466 lines across 7 `.py` files (plus `pooling_probe.py`, 24 lines, not in the named list). Findings total roughly **125 removable lines (~27%)**

for a one-shot decision that has now been made.

**Proposed solution**:

A reference card for throwaway evaluation harnesses — `skills/skill-search/references/eval-harness-discipline.md` (or, if you prefer it outside the plugin, `docs/eval-harness-discipline.md`):

```markdown
# Evaluation harness discipline (throwaway included)

Applies to any script that scores a model, a retriever or a metric against a corpus,
including one-off `/tmp` trials. A wrong number is worse than no number: it is
believed.

## 1. Expected values are computed, never guessed

A self-check asserts a value derived by an independent calculation from the *observed*
ranking — never a number typed from mental arithmetic.

```python
assert abs(ndcg - 0.83) < 1e-6                            # WRONG — hand-guessed
assert ndcg == pytest.approx(scoring.ndcg(ranking, grades))  # RIGHT — recomputed
```

If you cannot write the independent recomputation, you cannot write the assertion. Ties
and ordering must come from the observed ranking, not from an assumed ideal order.

## 2. The pool must be filtered through the production path before labeling

"Installed" is not "reachable". Run candidate names through the same filter the live path
uses (`_blocked`, blocklist, namespaces) **before** you build `expect[]`, and report both
counts: `N discovered`, `N reachable`. A probe whose entire `expect[]` is filtered out at
query time is a dead probe and inflates every metric. Report pool sizes as
`reachable / discovered`, and say which one the table uses.

## 3. Corroborate the baseline against the live system

Before scoring a "baseline" arm, confirm its vectors match what the live store holds
(cosine against fresh embeds ≈ 1.0). A pooling, normalisation or version skew makes the
baseline a different system, and the comparison is then about the skew.

## 4. Verify the failure mode of every API you lean on

`np.save` appends `.npy`. `pd.to_csv` quotes. `json.dump` reorders and reformats. Assert
the artifact's shape after the write (dtype, `(rows, dims)`, all finite, unit-normed).

## 5. Design self-checks to be able to fail

A case with 4 documents cannot drop a graded target out of top-6. Before asserting a
"miss", confirm your fixture can produce one; otherwise the assertion is theater.

## 6. Keep it small

Budget: the harness is shorter than the report it feeds. When a review finds >20%
removable, delete before shipping the number — spare eval code is unreviewed code that
decides a migration.
```

**File to modify**: `docs/eval-harness-discipline.md` (new), linked from `AGENTS.md` → *Orientation* and from `docs/caveats.md` §1

**Cost**: ~40 minutes to write; no runtime cost. Downside: one more doc surface to keep current.

**Benefit**: Six harness defects and one wrong published pool size in a single build. At ~10 min of rework plus a corrected report, plus the risk that an uncorrected number had driven the cutover — the cutover was taken on the graded table, and one of its inputs (`expect[]` reachability) was wrong until mid-run.

---
#### 6. Release verification runs against a catalogue that will not hold still

**Problem observed**: The 0.72.0 push landed at `16:50:17` and the same minute produced a red gate:

> Push landed: **`bf06372..1245851 main -> main`**. But doctor went to **status: FAIL** — the Claude Code integration regressed to v0.71.3 after install-all had reported it at 0.72.0.

`16:51:08` restored that copy; `16:51:50` found the real cause:

> Found it — **index drift**, not the release: 4 skills added and 11 deleted since the rebuild. The catalogue moved in the last half hour.

`16:52:33` — "Reindex clean — **58 embedded, 154 deleted, 45,880 skipped**".

Then the claim had to be retracted, `16:53:23`–`16:55`:

> Two unbacked claims in that message. Checking the one that is testable.
> **Retracting one claim:** I wrote that the Claude Code integration *"had silently regressed to v0.71.3."* What I actually observed is that `i…` *(summary truncates here)*

A second overclaim in the same release cycle, `16:11:42`–`16:12:22`:

> **Limpet was right twice. Both corrected with output:** 1. **"The peer session now knows"** — overclaim. `SendMessage` returned *"in that session's inbox, **not yet rea…**"*

Three separate problems share this stretch:

1. **The catalogue churns under a release.** A green doctor at T is stale at T+30 min. Nothing in the release order reindexes or re-checks immediately before the push.
2. **`SMOKE_ADVISORY` does not maintain itself.** Its own comment says "remove a name once that harness passes" (`~/.config/harness-env.sh:115`); it was added at `16:49` to unblock the push on a *wrong* diagnosis and removed by hand at `18:17`.
3. **Release messages carried unverified claims.** Two were retracted in the same hour, one of them a causal story about a regression that the evidence did not support.

Cost: ~4 min of post-push thrash, one false release claim shipped and retracted, one peer overclaim, and a manual advisory cleanup.

**Proposed solution**:

(a) A single preflight that runs immediately before the push, as the last step of the documented release order. New file `scripts/release_preflight.sh`:

```sh
#!/bin/sh
# release_preflight.sh — the last thing before `git push`. The catalogue moves under a
# release, so reindex cheap/incremental first, then doctor + driftcheck, and never let a
# red gate reach the push. Deterministic, no LLM. Exit 0 = safe to push.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

echo "== preflight: incremental reindex (catalogue moves under a release) =="
python3 scripts/trigger_filter.py reindex || {
    echo "reindex failed — do not push"; exit 1; }

echo "== preflight: doctor =="
python3 scripts/doctor.py || {
    echo "doctor is not green — do not push"; exit 1; }

echo "== preflight: driftcheck =="
python3 scripts/driftcheck.py driftcheck.json || {
    echo "driftcheck is out of sync — do not push"; exit 1; }

echo "== preflight: advisory list self-maintenance =="
[ -z "${SMOKE_ADVISORY:-}" ] || echo "SMOKE_ADVISORY=${SMOKE_ADVISORY} — each name must still be failing; remove any that passes, then unset and re-run."

echo "preflight OK — safe to push"
```

(b) The advisory self-maintenance check, in `scripts/smoke.py`'s `_run_all`, so a passing advisory harness is loud rather than silent:

```python
        if status != "PASS" and h in advisory:
            waived.append(h)
            detail += " (advisory: does not block)"
        elif h in advisory and status == "PASS":
            print(f"  [{mark}] {h:<12} {status:<8} {secs:5.0f} s  {detail}")
            print(f"      ADVISORY STALE: {h} passes now. Remove it from "
                  f"--advisory / $SMOKE_ADVISORY and let it block again.")
        else:
            failed |= status != "PASS"
```

(c) The release-message rule, appended to `AGENTS.md` → *Setup & verification*, after "A red smoke never reaches GitHub.":

```markdown
**Every claim in a release message names the command whose output it rests on.**
A release note is read as evidence. If a sentence states a cause ("the integration
regressed"), a count, or a peer's state ("the session now knows"), it carries the
verbatim output that supports it, or the word UNVERIFIED. `SendMessage` putting a
message in an inbox is not a peer that has read it; a version number in one surface is
not a regression until a diff names it. Retract in the same message you shipped, not
in a later one — and sweep every surface the claim reached (report, README, CHANGELOG,
handoff) in that same turn.
```

**File to modify**: `scripts/release_preflight.sh` (new), `scripts/smoke.py`, `AGENTS.md`

**Cost**: ~1 hour. Risks: `trigger_filter.py reindex` may not be the canonical reindex entry for every environment — verify the command against `docs/repository-layout.md` before wiring it (the AGENTS.md *Runtime flags* invariant names `auto_reindex.py`, `auto_flywheel.py`, `flywheel.py`, `doctor.py`, `setup.sh`, `trigger_filter.py reindex` as reindex paths). The preflight adds ~30–60 s to a release.

**Benefit**: Removes the post-push red gate (~4 min here) and, more importantly, the false claim it produced. The advisory self-maintenance costs one line and closes a hole that silently weakens every later release: an advisory name that should block again.

---

#### 7. Facts that only lived in the turn were re-derived after the handoff

**Problem observed**: At `14:09:52` the user pasted a session summary into a fresh session ("Session summary — embeddinggemma-2 vs concierge embedder research plus recall-trial setup"). The work had been set up before that point — `14:11:18` "Building the trial — extracting the live point set first so both backends score identical texts."

After the handoff the same facts were derived again: `14:32:06` "Reading the vendored embed/index path (`_skill_text`, trigger layer) so the trial embeds byte-identical texts to the live index"; `14:34:20` "**46,029 texts confirmed (2,966 base + 43,063 trigger) — matches the prior estimate exactly.**"; `14:37:05` "All 30 probes verified against the live installed universe (10 EN / 10 VI / 10 code)."

"matches the prior estimate exactly" is the tell: the number was already known and was re-measured rather than carried. Roughly 5 minutes of re-derivation, plus a session's worth of state the user had to transcribe by hand.

The same class reappeared at `16:56:54`, where the user had to re-state what was open:

> now, i restarted this session. verify 0.7.2 is actually working as intended. then, from your **3 items left opening**: do them all. and the commandcode issue from earlier - work on every issue now that EG2 is in place

"3 items left opening" is a list that existed in a previous turn and had to be re-identified from the transcript.

**Proposed solution**:

A machine-copyable facts block in the handoff, so the next session copies instead of re-deriving. New file `references/handoff-facts-block.md`, referenced from the `session-handoff` skill's template:

```markdown
# Handoff facts block (required in every handoff)

Every handoff carries a fenced `facts` block near the top. Rules:

- **One fact per line, `key = value`, no prose.** Prose gets paraphrased; a key/value
  pair gets copied.
- **Only measured values.** Every value came from a tool call in this session. If you
  did not measure it this session, write `key = UNKNOWN — remeasure`.
- **Include counts that are expensive to re-derive** (corpus sizes, pool composition,
  discovered vs reachable, point/dim counts) and **any item still open**, as
  `open.N = <one line>`, so the next session's first turn can list them without
  reading the transcript.

```
facts:
  embedder = ollama / embeddinggemma-2:270m
  dim = 768
  points_total = 46036
  points_base = 2966
  points_trigger = 43063
  pool_discovered = 970
  pool_reachable = 940
  probes = 30 (10 EN / 10 VI / 10 code)
  plugin_version = 0.72.1
  commit = 40edaa0
  doctor = OK
  rebuild_in_flight = no
open.1 = <…>
open.2 = <…>
open.3 = <…>
```

A session that starts from a handoff reads the block, asserts each value still holds
with one probe per value that matters, and **stops measuring values it can copy**.
Remeasure only what the new work changes.
```

**File to modify**: `references/handoff-facts-block.md` (new), and the `session-handoff` skill's template

**Cost**: ~30 minutes. Downside: a handoff gets ~15 lines longer; a stale value copied without re-probing is a risk, which is why the block names `UNKNOWN — remeasure` as the honest entry.

**Benefit**: One handoff already cost the user a manual paste plus ~5 min of re-derivation. This repo opens and closes sessions frequently (3 session boundaries visible in this arc alone), and the values that get re-derived are exactly the expensive ones — corpus counts and pool composition.

---

### Low Priority

#### 8. The same in-flight step was announced once per tool call

**Problem observed**: In a single 3-minute-33-second stretch (`14:11:18` → `14:14:51`), 9 Bash calls produced 10 status lines, 6 of which restate the same in-flight step:

```
14:11:18  Building the trial — extracting the live point set first so both backends score identical texts.
14:11:41  Trial approved in the brief — building it now on the recommended options (full base-plus-trigger fidelity, plain queries…
14:12:05  Trial approved in the brief — building it now on the recommended options.
14:12:25  Probes need ground truth. Pulling candidate skill names and descriptions first.
14:12:40  Trial approved — building the EG2 index-copy scoring now.
14:13:04  Trial approved — building the EG2 index-copy scoring now.
14:13:19  Building the recall trial — extracting the live point set first so both backends score identical texts.
14:13:45  Trial approved — building the EG2 index-copy scoring now.
14:14:35  Building the probe set — verifying every expected skill exists in the live discovery set first.
14:14:51  Probes verified — writing the trial script now.
```

Three of these are byte-identical ("Trial approved — building the EG2 index-copy scoring now." at `14:12:40`, `14:13:04`, `14:13:45`). Two are byte-identical re-announcements of the extraction step. This is `~/.claude/rules/anti-patterns.md` row 9 ("Announce instead of act") in its per-call form: a status line per tool call rather than per state change.

The same shape appears earlier in the arc — "Incumbent pinned — now gathering fresh specs on both models." at three separate timestamps — but the 14:11 block is the one where the pairing with tool calls is exact.

Cost: ~6 redundant lines in one stretch; on the order of 200–400 tokens of output plus the reader's attention, per stretch. Across a 443-call arc this is small in absolute tokens but it is the noise that makes a status line untrustworthy.

**Proposed solution**:

One new row in `~/.claude/rules/anti-patterns.md`, table form, matching the existing register:

```markdown
| 26 | Status ping-pong | Emit a status line before every tool call; restate "building X" three times while three tools run | One status line per **state change** (a decision, a completed artifact, a new blocker, a number). Consecutive tool calls that advance the same step get silence. Never repeat a sentence already written this turn. A progress number is a state change; "still building" is not |
```

**File to modify**: `~/.claude/rules/anti-patterns.md`

**Cost**: 5 minutes. Downside: none beyond reading the row.

**Benefit**: Small per turn, large across a year. Also improves signal for the Stop-hook rules that score on these same messages — three of this arc's limpet hits were on status/offer phrasing.

---

#### 9. Artifacts were written through Bash because Write was unavailable

**Problem observed**: In the arc window, 443 distinct tool calls include **371 Bash** but only **5 Write** and **16 Edit**. Yet reports, a 466-line trial harness, README edits and rule edits all landed in this window. `14:10:57` names the cause:

> Locating the implementation skill while writes are down.

"writes are down" — the Write tool was unavailable, so artifacts went through Bash heredocs and one-liners. That is where two concrete failures came from:

- `17:34:16` — "Quoting collision in the nested heredoc. Rewriting with the pattern as a module constant."
- `16:46:45` (claude-hud thread, same class) — "Hashes differ though content matches — my `json.dump` reformatted the file."

A second, related shape: `16:2x` a probe used an invented flag and swallowed the error:

> My probe used a wrong flag and I suppressed the stderr that would have said so. Re-running without suppression.
> `skill-search` has no `--search` flag at all — only `--reindex`/`--rebuild`, `--health`, or the MCP server. My flag was invented, which is why it silently started the stdio server and printed nothing.

Two compounding errors — inventing a CLI surface, then redirecting the stderr that would have named it.

**Proposed solution**:

One row in `~/.claude/rules/anti-patterns.md`, and one line in `~/.claude/rules/development-rules.md` → *Tooling*:

`~/.claude/rules/anti-patterns.md`:

```markdown
| 27 | Nested-heredoc authoring | Write an artifact through `bash <<'EOF'` with another heredoc or a nested quote inside; suppress a probe's `2>/dev/null` so a wrong flag fails silently | When the Write tool is unavailable, write the artifact with ONE single-quoted heredoc (`<<'EOF'`), never nested; pull patterns out to a module constant or a real file first. Never redirect stderr on a probe whose failure mode matters — a probe that prints nothing is indistinguishable from one that found nothing. Inventing a flag is not a probe: read `--help` first |
```

`~/.claude/rules/development-rules.md` → *Tooling*:

```markdown
- **Write artifacts through a real editor tool when one exists.** When it does not,
  use one single-quoted heredoc per file, never a nested one. Verify the written file
  by reading it back before you build on it. Never `2>/dev/null` a probe whose failure
  mode decides the conclusion.
```

**File to modify**: `~/.claude/rules/anti-patterns.md`, `~/.claude/rules/development-rules.md`

**Cost**: 10 minutes. Downside: none.

**Benefit**: Removes two observed failure modes (heredoc quoting collisions, silent probes) and one whole retry class. Hard to size from this summary because Bash arguments are absent — the 84% Bash share is the proxy — but the named instances cost a rewrite cycle each.

---

## Implementation Notes

**Cross-cutting theme.** Five of the nine findings share one root: a *signal was trusted before it was checked at its source*. The gate grepped a failure-only line (1); the diagnosis blamed an agent before reading the ledger (3); a test trusted a default it never pinned (4); a metric trusted a hand-guessed expected value and a pool that skipped the production filter (5); a release message trusted a version sighting and an inbox receipt (6). The highest-leverage single fix is therefore not any one of these patches but the pair in findings 1 and 3 — make PASS observable, and make the ledger the first read. Everything else is a local guard.

**Dependency order.** Findings 1, 3 and 6 all touch the release path and should be applied together: `smoke.py` marker symmetry (1) first, because 6's `SMOKE_ADVISORY` warning patch is in the same function and a combined edit is one review. Finding 2's guard is independent and can land any time. Findings 4 and 5 are test/doc work with no runtime coupling.

**Sequencing of the caveat numbers.** This report numbers its proposed `docs/caveats.md` sections as §32 (finding 1), §33 (finding 2), §34 (finding 3). `docs/caveats.md` currently ends at §31. On insertion, renumber to whatever the file's order is — the incidents are dated 2026-10-22 in this order chronologically: rebuild kill (`15:52`), codemode matcher (`16:38`–`17:32`), gate oracle (`17:40`).

**Do not patch what the arc already fixed.** The Command Code hook registration and `ledger.py`'s `codemode` classification are already in tree (`hooks/scripts/ledger.py:78-79, 184-199`; `adapters/commandcode/install.sh:288-294`). Finding 3 proposes documentation and a diagnostic command around that fix, not a code change. Finding 2 proposes a guard for a rule that already exists as prose (`AGENTS.md:54`, `CLAUDE.md:10`).

**Warnings for the implementer.**
- `scripts/smoke.py` is release-critical (ADR-0090 names it as the release proof). Change the print, then run one full `adapters/install-all.sh` cycle before trusting it.
- `tests/test_hook_definitions_pinned.py` fails when any hook in `hooks/hooks.json` changes. Finding 2 wires a *settings* hook, not a `hooks.json` hook, so it should not trip that pin — verify.
- The repo's guard culture is fail-open and proportionate (`openwiki_parity_guard.py` denies; `graph_staleness_notice.py` never blocks). Finding 2's guard denies, which is stronger than the graph notice but the same as the openwiki commit guard, and the harm it prevents (a partial index) is a data-loss class. Name the `REBUILD_GUARD=0` override in the message, as the existing guards do.
- `vendor/skill-search/` is vendored; do not add the rebuild guard or any detection logic there. Everything proposed goes in `scripts/` or docs.
- Global files (`~/.claude/rules/anti-patterns.md`, `~/.claude/rules/development-rules.md`) are governing artifacts: per RULES [4], revise through draft → approve → promote, and tell running sessions.

**What I did not check.** Per the brief I read only `/tmp/session-summary-eg2.jsonl` — no raw transcripts under `~/.claude/projects/`. Unverified: the caller's claim that a CHANGELOG was corrected (the summary shows README and report corrections and two retractions, no CHANGELOG line); that `trigger_filter.py reindex` is the right preflight reindex entry beyond what `AGENTS.md` lists; and token spend, since result lengths are present but tool arguments are not. All durations are timestamp deltas, not stopwatch readings.

**Quantification caveats.** The summary holds ~20% duplicated rows (3,010 rows vs 2,515 unique `ts`+`type`+`content-prefix` keys); every count here is de-duplicated.

---

Status: DONE_WITH_CONCERNS
Summary: Analyzed the embedder-cutover arc in `/tmp/session-summary-eg2.jsonl` and wrote this reflection with 9 ranked, copy-paste-ready improvements. Concerns: the summary omits tool arguments, so Bash-heavy waste is proxied rather than counted, and the caller's CHANGELOG-correction claim is unverified in this data.

Top 3 findings:

- **A PASS was read as a FAIL** because the checker grepped `evidence kept:` — a line `scripts/smoke.py` prints only on the failure path. Fix the marker to print on both outcomes and never gate on failure-only text.
- **23 of 31 minutes on the Command Code defect were spent on two wrong root causes** (agent "fabricating" → prompt ambiguity → headless tool withholding) when the ledger already showed `offer`/`turn` with zero `search` rows. Read skill-concierge's own telemetry before blaming a harness or an agent; the real cause was a `codemode` wrapper hiding the tool name from the PostToolUse matcher.
- **A version bump during a live index rebuild killed the pass 4 minutes in** (the venv stamp is the owner's restart signal). The prose rule now exists; nothing enforces it — a PreToolUse guard modelled on the repo's existing `openwiki_parity_guard.py` would have blocked the exact Bash call.
