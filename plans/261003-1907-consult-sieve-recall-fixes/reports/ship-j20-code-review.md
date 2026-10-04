# Ship J20 code review: `consult_fit.py widen`

Reviewed 2026-10-04 10:27 (Asia/Saigon). Read-only: no repo edits, no git writes. Scratch scripts in `/tmp/cr_j20/` (not the repo).

Scope: `git diff -- scripts/consult_fit.py skills/consult/SKILL.md skills/consult/agents/analyst.md` plus the new `tests/test_consult_widen.py`, against the gate code in `scripts/sieve_recall.py` (`jev_round_robin` 1580, `union_rows` 1594, `jev_top` 1606, `jev_setup` 1620, `clean_prompt`/`gen_text` 196/210, `run_case2` 1642) and the corpus builder `scripts/extract_turn_labels.py:418`.

## Verdict

Parity with the proven J20 arm holds. I checked it by running both code paths side by side, not by reading. The failure paths behave as specified. There are no Critical or High findings. Three Medium findings: one privacy edge case inherited from the gate, one agent-workflow risk in SKILL.md, and test gaps on the "3 s, one attempt" call shape.

## Evidence run

| Check | Command / harness | Result |
|---|---|---|
| Unit tests | `pytest -q tests/test_consult_widen.py tests/test_consult_fit.py` | `49 passed in 2.17s` |
| Selftest | `consult_fit.py widen --selftest` | `WIDEN-SELFTEST-OK` |
| Merge/order parity | 3000 random trials: 1-4 chunks, random probabilities, colliding names (`ak:cook`/`ak-cook`/`AK:Cook`, `/s6`, `s7 extra`), 0-45 sieve rows with externals. Compared `cf.widen(...)` keys against `sr.union_rows(sr.jev_top(...)[0], sieve, 20)` | `trials 3000 mismatches 0` (keys and order) |
| Text parity | 3000 random tasks up to ~900 tokens with reminders, injected blocks, secrets. Compared `cf.widen_clean(t)` against `sr.gen_text(t[:4000], len(t) > 4000)`, the gate's corpus pipeline (the corpus stored `prompt[:4000]` and set the truncated flag, `extract_turn_labels.py:418`, `sieve_recall.py:804`) | `mismatches: 0` |
| Real catalogue shape | `_jev_catalog()` against the live index owner (no Jev call) | `catalogue 569 chunks 3 batches 1 harness claude`: one HTTP request, so the 3 s per-request timeout bounds the Jev leg |
| Fallback width vs A0@20 | Read `server.py:1361-1387`. In the default path each query fetches `limit=top_n`, then rows merge by max score | The top 20 of a top_n-40 call equals a top_n-20 call (ties aside), so the fallback reproduces the gate's A0@20 baseline |
| CLI edge cases | key unset; `SKILL_CONSULT_JEV=0`; `candidates` = `{"error":...}`; non-string name | no key → `failed: true`, exit 0; error response / bad name → exit 2 with a JSON error |

## 1. Parity: holds

- Ordering: `jev_round_robin` (`consult_fit.py:368-378`) is byte-identical logic to `sieve_recall.py:1580-1591`.
- Top 10: `consult_fit.py:394`. Dedupe key `_skill_key` (`enforcer.py:1626`, the same function the gate's `skill_key` wraps). Cut 20: `consult_fit.py:416`.
- Call shape: ts tier only, `retries=0`, 3.0 s, empty `recent_context`, `_jev_wide_questions(_jev_catalog())` (`consult_fit.py:384-392`). Same as `jev_setup`/`jev_top`.
- Catalogue: the same `_jev_catalog` through the same `jc.load_enforcer()`, which sets the relay to None, as the gate did. The catalogue depends on the session's harness and cwd (`_row_invocable`). That is correct per-session behaviour, but the gate proved it only for Claude (Inference: the corpus is Claude Code transcripts).
- One allowed difference: a Jev pick that is also a sieve row keeps the sieve row's fields (`consult_fit.py:409`). The gate kept the Jev name with `external: False`. Recall cannot change because the key is the same. See L2 for the one side effect.

## Findings

### Medium

**M1. A system-reminder block that crosses the 4000-character cut reaches Jev.** `scripts/consult_fit.py:360-363`
`widen_clean` cuts the raw task to 4000 characters before it strips `<system-reminder>…</system-reminder>`. `_JEV_REMINDER_RE` (`enforcer.py:1576`) needs the closing tag. If the cut lands inside a block, the opening tag and the reminder body survive into `state.request`. Ran:
- A reminder opening at char 3800 in a 4507-char task: `widen leaks reminder: True`.
- A 4800-char reminder up front, then the real request: production sends 3996 characters of reminder text and the user's request is cut away entirely.

`_jev_redact` still masks secret-shaped strings, so this exposes non-secret injected context: CLAUDE.md text, memory recalls. It does not expose keys. It is parity-exact with the gate: the gate's corpus did the same cut-then-strip, so the gate had the same hole offline. It only fires when the agent pastes injected blocks into `task`, which SKILL.md tells it not to do. Even so, the strip exists for exactly that mistake, and right now it fails open on long input.
Fix: strip and redact the full text first, then cut to 4000 and drop the last token:
```python
text = enf._JEV_REMINDER_RE.sub("", task or "")
for rx in enf._JEV_INJECTED_RES: text = rx.sub("", text)
text = re.sub(r"\s+", " ", enf._jev_redact(text)).strip()
if len(text) > WIDEN_TASK_CAP: text = re.sub(r"\S*$", "", text[:WIDEN_TASK_CAP]).rstrip()
```
This departs from the gate only for tasks over 4000 characters that carry injected blocks, a negligible slice of the gated population. Add a test with a reminder that crosses the cut.

**M2. Step 2 has the agent retype about 28 KB of JSON and the user's raw text into a shell command, with no safe-quoting rule.** `skills/consult/SKILL.md:46-50`
The smoke input `~/_ARCHIVE/consult-widen-261004/widen-in.json` is 28k for 39 rows, because capsules are large. The agent has to re-emit the whole `consult_candidates` response verbatim inside a Bash call. Two risks:
- (a) The agent drops or summarizes rows, or reorders them. The gated sieve order then changes silently and nothing detects it.
- (b) The request text sits inside shell quoting. A `'` in the user's words breaks `echo '…'`, and pasted text could inject a command.

The live smoke fed rows from `smoke_candidates.py`, not from an agent, so no agent has run step 2 end to end (implementation report, line 21). The `--fast` fit call at line 83 already has the same pattern; that one predates this change.
Fix: tell the agent to use a quoted heredoc (`<<'JSON'`) or to write the input to a file and pass it. Better: let `widen` accept only `{"task", "names": [...]}`, return the order, and have the agent keep the rows from its own context. Run one blind agent through step 2 before calling the workflow verified.

**M3. Tests do not pin the call shape the gate proved.** `tests/test_consult_widen.py`
I mutated a temp copy of `consult_fit.py` and ran the test file:
- `retries=1`: 15 passed
- timeout `30.0`: 15 passed
- any tier instead of ts-only: 15 passed
- non-empty `recent_context`: 15 passed
- top 12 instead of top 10: 1 failed
- chunk concatenation instead of round-robin: 1 failed

Round-robin across chunks is covered only by the selftest (the pytest fake has one chunk of 30). The "3 s, one attempt, ts tier, empty context" promise has no test behind it.
Fix: one test that wraps `ask_fn` and asserts `timeout == 3.0`, `retries == 0`, `tiers == [{"ep": "ts", ...}]` under `ENFORCER_JEV_BENCH="gw:x ts:y"`, and `state["recent_context"] == ""`. Also add a two-chunk pytest case.

### Low

- **L1. A request that is empty after cleaning still calls Jev.** `consult_fit.py:422-431`. A task that holds only an injected block passes the non-empty check. It goes out as `request: ''` and Jev's picks still go first. Ran: `empty-after-clean request sent: '' jev rows added: 1`. With the real catalogue, up to 10 noise rows would push sieve rows out. Fix: if `widen_clean(task)` is empty, skip Jev and return `failed: true`.
- **L2. A "both" row inherits the sieve row's `external`.** `consult_fit.py:409`. An installed Jev pick can share a key with an external catalog row (e.g. the same `alias:name` form). The merged row then says `external`, and the analyst reads the external copy with `get_skill` instead of the installed one. The gate counted that row as installed. Recall is unaffected. Fix: for a Jev pick, prefer the first installed (`not external`) sieve row with that key.
- **L3. `SKILL_CONSULT_JEV=0` does not stop `widen`'s Jev call.** `main` dispatches to `widen` before that check (`consult_fit.py:504-515`). The module docstring (`consult_fit.py:15`) still says exit 3 means disabled, which `widen` never returns. README treats `SKILL_CONSULT_JEV_WIDEN` as its own switch, so this is a design choice. The docstring should say the exit codes apply to fit mode only.
- **L4. SKILL.md wording gaps.**
  - `--top N` (line 157) says it sets the width when widen is off or fails. But step 2 hard-codes `top_n=40` and the fallback text (line 57) says "first 20", so `--top N` now governs nothing.
  - Step 4 (line 72) still says `{{CANDIDATES_JSON}}` is "the sieve rows + manual admissions". It should say the `widen` results.
  - The card wording for the kill-switch case (`jev.disabled: true`) is not stated.
  - The kill-switch output also has a different row shape from the other paths: no `source`, no dedupe (`consult_fit.py:428`).
- **L5. `widen_selftest` pops `ENFORCER_JEV_BENCH` and `SKILL_CONSULT_JEV_WIDEN` without restoring them.** `consult_fit.py:442-443, 479`. Harmless for the CLI. It leaks into an in-process caller; pytest's monkeypatch masks it.
- **L6. "3 s, no infinite wait" is a per-request socket timeout, not a total.** The catalogue scroll runs first and has its own 1.5 s per page (`enforcer.py:1897-1898`, `JEV_TIMEOUT_S`). urllib applies the 3 s per socket operation (`jev_client.py:171-172` comment). `ask`'s default deadline is 60 s, but with one batch and `retries=0` that never comes into play. Same as the gate. The worst case is a few seconds, never unbounded.
- **L7. The analyst template does not say Jev rows are installed.** `agents/analyst.md:15-17, 36`. The catalogue excludes externals, so every `source: "jev"` row is installed. The template does not say so, and the analyst may set `"installed": false` for a row with no `path`.

## 2. Privacy

- Only `state.request` (the cleaned task) and the installed catalogue's names and 160-char descriptions leave the machine. The catalogue already goes out on every routed turn. `recent_context` is `""` and `skills_already_loaded_this_session` is `[]` (`consult_fit.py:390`).
- Secret shapes are redacted (test plus my run: `use [redacted] now`, `fix the hook [redacted]`).
- No key is printed: `widen` swallows every exception without a message (`consult_fit.py:432`), `_fail` echoes only `ValueError` text from input validation, and `JevError` messages are class names only.
- The key travels only to the host-pinned URL (`_jev_direct_url`).
- Gap: M1.

## 3. Failure handling

- Timeout, no key, empty catalogue, and any exception inside `jev_top` or `widen_clean` all give the deduped sieve rows cut to 20, `failed: true`, exit 0. The test is parametrized over these modes, and I re-ran the no-key case by CLI.
- Kill switch: `rows[:20]`, exit 0, no Jev call (tested).
- Malformed input exits 2 with a JSON error. That includes a `consult_candidates` error object passed as `candidates`. SKILL.md covers a non-zero exit.
- One uncaught path: if `jc.load_enforcer()` itself fails, `widen_rows` (`consult_fit.py:400`, outside the try) re-raises, `widen_main` catches only `OSError`/`ValueError`, and the run ends in a traceback with exit 1. SKILL.md's non-zero rule still applies, so the agent still falls back. Unlikely, because the enforcer ships in the same plugin.

## 4. SKILL.md / analyst.md

- Step 2 does name the user's verbatim words (not the sub-goals) as `task`, top_n 40, and the use of `results` for every later step.
- `jev` rows have no `path`. Both SKILL.md (line 56) and analyst.md (lines 15-17) route them to `get_skill(name)`. `server.py:1424-1445` resolves installed names through the index payload path, so the analyst can read them.
- Gaps: M2, L4, L7.

## 5. Tests

- The tests bite on order, top-k, dedupe, cut, redaction, half-token drop, kill switch, fallback, and bad input. The implementer's mutation list matches what I re-checked for top-k and round-robin.
- Gaps: M3 (call shape), M1 (crossing reminder), L1 (empty-after-clean), and any test with a real multi-chunk catalogue in pytest.

## 6. Out of scope

- The three reviewed files carry only the widen work. The `consult_fit.py` diff is additive: hunks at docstring lines 11-12, the block at 345-501, and dispatch at 503-505, with no deletions.
- The working tree also has uncommitted changes to the manifests, AGENTS.md, CLAUDE.md, README.md, CHANGELOG.md, docs/adr/README.md, docs/epoch-watch.md, openwiki/quickstart.md, package.json, GATES.md and a decisions report. They appear to belong to the release lane. I did not review them.

## Not checked

- Live Jev behaviour: no real TypeSafe call was made.
- Behaviour under Codex, OMP, ZCode, DSH or Cline.
- A blind agent following step 2 end to end.
- The gate corpus's language mix (the raw output does not report it).
- Whether `docs/adr/0078` exists and matches. README cites it; that is release-lane work.

Status: DONE_WITH_CONCERNS
Summary: 0 Critical, 0 High, 3 Medium, 7 Low. Parity with J20 verified by differential runs (3000/3000 merge, 3000/3000 text). Top finding M1: the cut-then-strip order lets a system-reminder block that crosses the 4000-character cut reach Jev (inherited from the gate; fix by stripping and redacting before the cut).

---

# Re-review (2026-10-04, after "Review fixes")

Read-only, same method. Scratch in `/tmp/cr_j20/`. Files: `scripts/consult_fit.py`, `scripts/consult_log.py`, `skills/consult/SKILL.md`, `skills/consult/agents/analyst.md`, `tests/test_consult_widen.py`. I ignored the 20 installer-test failures, as instructed.

## Runs

| Check | Result |
|---|---|
| `pytest tests/test_consult_widen.py tests/test_consult_fit.py` | `68 passed in 3.09s` |
| `consult_fit.py widen --selftest` / `consult_log.py --selftest` | `WIDEN-SELFTEST-OK` / OK (the selftest writes to a temp ledger) |
| Merge parity, 3000 random trials vs `sieve_recall.jev_top` + `union_rows` (now called with keyword args, since the third positional argument is now `queries`) | `trials 3000 mismatches 0` |
| Text parity vs the gate pipeline `gen_text(t[:4000], len(t) > 4000)` | raw ≤ 4000 chars: `926 cases, 0 differ`. Raw > 4000: `2074 cases, 2037 differ` (expected after the M1 change; see L9) |
| M1 cases | crossing reminder: `straddle leak: False`. 4800-char leading block: `'build a docx report from the csv'`. Text that is only a block: `''` (Jev skipped) |
| Engine child vs an MCP-like call with the same cwd: venv python, full `.mcp.json` env, slots/RRF 0, top_n 40 | rows identical in order (`same order as widen child: True`). Live latency 0.4 s |
| Engine child (cwd = home) vs an MCP-like call from a project with project skills (`MY-WORKBENCH/Diep.Wealth`, 52 `project:` points) | `identical: False`. Missing from widen's sieve: `['ak-assets-organizing', 'ak-storage']`, ranks `[8, 22]` in the project view |
| `consult_log.py --sieve bogus` / `--jev-added abc` | `exit 2 rows=0` for both: the whole verdict row is lost |

## Status of the earlier findings

- **M1 fixed.** `widen_clean` strips and redacts the whole text first, then cuts. Two new tests cover it (a crossing reminder, a long leading block).
- **M2 fixed, but the fix introduced H1 below.** Step 2 no longer has the agent retype rows; `widen` runs the sieve itself from `queries`.
- **M3 fixed.** The call shape is pinned by `test_jev_call_shape_is_one_attempt_3s_ts_tier_empty_context`, plus tests for top 10 and two-chunk round-robin. The implementer reports a mutation run; I did not repeat it this round.
- **L1, L3, L4, L5, L7 fixed.** Empty request skips Jev. Docstring now covers exit codes and the `SKILL_CONSULT_JEV` note. `--top N` removed and card wording added. The selftest restores the environment. The analyst template marks Jev rows as installed.
- **L2 changed, not fully fixed.** See L10.

## New findings

### High

**H1. `widen`'s sieve runs from the home directory, so it drops the current project's own skills. The MCP tool would return them.** `scripts/consult_fit.py`, `_ENGINE_CHILD` (`os.chdir(os.path.expanduser('~'))`) and `sieve_rows_from_engine` (`cwd=str(Path.home())`).
- `consult_candidates` filters by `_scope_filter()` → `sd.visible_scopes()`, which includes `project:{PROJECT_ROOT}`. `PROJECT_ROOT` is computed from the cwd at import (`skills_discovery.py:1048`).
- With cwd = home, the session's project-scoped skills are invisible to the sieve. The MCP server runs in the session's project dir and sees them.
- Measured from `Diep.Wealth` with an asset-organizing query: the MCP-like call ranks `ak-assets-organizing` 8th and `ak-storage` 22nd. Widen's sieve has neither.
- They can still come back through Jev, whose catalogue is built in `consult_fit`'s own process (session cwd, where `project:<cwd>` is never foreign). That only happens if Jev puts them in its top 10.
- This matches the gate: `sieve_recall.load_engine` also did `chdir(home)`, so the gate never measured project skills. It is still a silent regression against the pre-change step 2 (an MCP call from the session cwd), and it fails the coordinator's "same rows as the MCP tool" check.
- Fix: run the child in the caller's cwd (`cwd=os.getcwd()`, or `CLAUDE_PROJECT_DIR` when set) and drop the `chdir`. Add a test where a fake `server.py` echoes `os.getcwd()`.

### Medium

**M4. An invalid `--sieve` or `--jev-added` value now loses the whole verdict row.** `scripts/consult_log.py`, the argparse additions (`choices=list(_SIEVE) + [""]`, `type=int`).
argparse exits 2 before `append_verdict` runs (my runs above: `rows=0`). The implementation report says "invalid values are dropped, never an error", which is true only for the library function, not the CLI. One agent typo (`--sieve not_widened`) costs the record the consult loop relies on.
Fix: take both as plain strings, with no `choices` and no `type=int`. Let `append_verdict` validate them, as it already does. Add a CLI test with a bad value that asserts the row is still written.

### Low

- **L8. The heredoc delimiter is the generic `EOF`.** `skills/consult/SKILL.md:36-39`. The quoted delimiter correctly stops all expansion, and valid JSON keeps the payload on one line, so no line can equal `EOF`. But if an agent writes the user's newlines raw (invalid JSON) and a user line is exactly `EOF`, the heredoc ends early and the remaining lines run as shell commands. Fix: use an unlikely delimiter (e.g. `<<'CONSULT_WIDEN_JSON'`) and say "one line; escape newlines as `\n`".
- **L9. The docstring overstates parity.** `widen_clean` docstring says the two pipelines "differ only for a request over 4000 characters that carries an injected block". In fact any raw request over 4000 characters can differ, because whitespace collapse and redaction move the cut point (2037 of 2074 random long cases differ). The behaviour is correct; the sentence is wrong.
- **L10. A Jev pick that collides with an external sieve row becomes a hybrid.** `widen_rows` keeps the external row's description, capsule and `origin`, drops `external`, and has no `path`. `test_an_installed_jev_pick_beats_an_external_sieve_row_of_the_same_key` pins exactly this (`description == "ext copy"`). The analyst then sees an "installed" row described by the external copy. Fix: when the colliding sieve row is external, emit the Jev row (catalogue name and description, `source: "jev"`). Rare in practice.
- **L11. The engine child inherits the full environment** (`engine_env()` returns `dict(os.environ)` plus `.mcp.json` keys). That includes `TYPESAFE_API_KEY` and `FLYWHEEL_LLM_API_KEY`, which the engine never uses. This is no wider than what the MCP server already gets from the harness, and the child is local plugin code, so the risk is low. Dropping `*_API_KEY` and `ENFORCER_JEV_KEY` from the child env costs one line.
- **L12. The engine timeout of 120 s equals the agent Bash tool's default 2-minute limit.** Normally the child answers in 0.4 s. If the index owner does not serve the model, though, `embed_queries` loads fastembed in-process, and a cold start can take tens of seconds. At 120 s the Bash call is killed before `widen` can print its exit-4 JSON. The agent still falls back on the non-zero result, so nothing hangs forever. A 30 s engine timeout would keep the fallback inside `widen`'s own contract. The Jev leg stays bounded: one batch, 3 s per request, `retries=0`. `pool.shutdown(wait=True)` waits at most for that.

## Answers to the four questions

1. **M1 and parity.** M1 is confirmed fixed. Merge parity holds (3000 of 3000 trials). Text parity is exact for every raw request up to 4000 characters. Over 4000 it differs by design (L9).
2. **New engine path.** Same engine code as the MCP server (the venv's installed `skill_search`), same index-shaping env (`.mcp.json` via `engine_env`), same top_n 40, slots/RRF forced off. Rows come out identical when the cwd is the same, but the cwd is not the same (H1). Engine failure gives exit 4 with a JSON error (tested), and SKILL.md sends the agent to `consult_candidates(top_n=20)`. Hang risk is bounded (L12). Secrets reaching the child: L11.
3. **Heredoc.** Safe for any user text that is properly JSON-escaped; the edge case is L8. The agent ends up with `results`, at most 20 rows, each tagged with a `source`. The fallback row set is the gate's A0@20 baseline.
4. **New issues from the fixes.** H1 (from the M2 fix), M4 (from the logging change), and L8-L12.

## Not checked

- A blind agent running step 2 end to end.
- A live Jev call (all Jev runs used fakes).
- The `CLAUDE_PROJECT_DIR` handling of each harness.
- The other harnesses' MCP spawn cwd. Claude Code spawning the MCP server from the project dir is an inference from the project-scope design, not something I verified in this run.

Status: DONE_WITH_CONCERNS
Summary (re-review): 0 Critical, 1 High, 1 Medium, 5 Low (new). M1, M3 and five of the earlier Lows are fixed; M2 is fixed but created H1; L2 is now L10. Top finding H1: `widen` runs the sieve from the home directory, so the session's project-scoped skills drop out of the 40 rows (measured: `ak-assets-organizing` rank 8 in the MCP view, absent from widen's). Fix: use the caller's cwd.
