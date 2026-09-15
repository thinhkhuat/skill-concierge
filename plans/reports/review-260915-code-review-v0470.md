# Code review — v0.47.0 uncommitted change set (ADR-0054)

Reviewer: v0470-code-reviewer (staff-engineer lane) · 2026-09-15 · read-only on the repo
Scope: `git diff` of 22 modified files + ADR-0054 + plan `plans/260915-0837-v0470-audit-implementation/plan.md`.
Checks run: `py_compile` ×5 OK · `enforcer.py --selftest` OK · `analyze.py --selftest` OK ·
`audit_skill_usage.py --selftest` OK · `pytest -q tests/` 19 passed · `driftcheck.py` IN SYNC ·
pyright HEAD-vs-working: no new findings (35 → 31; the 4 gone are import-resolution noise from
running the HEAD copies out of tree) · `doctor.py` (no --fix) run live · `build_keep_off.py --out /tmp/…` dry run.

**Verdict: APPROVE-WITH-FIXES** — two MAJORs (neither corrupts data or blocks a turn; one makes an
ADR-0054 promise unreachable as documented), four MINORs, three NITs.

---

## MAJOR-1 — Deterministic routes bypass the harness-invocability filter (ADR-0034 invariant)

- **Where:** `hooks/scripts/enforcer.py:1172-1186` (`_route_hits`) and `:1939` (call site).
- **Code:**
  ```python
  if sub in low and skill not in seen and skill not in keepoff and not _blocked(skill):
      out.append((skill, "named in the prompt — deterministic route", 1.0))
  ```
- **Why it matters:** `_retrieve` drops every row whose scope is in `FOREIGN_SCOPES` unless
  `_invocable_twin` rescues it (`:1416`). `_route_hits` has no such test, and a hit pins the skill
  at 1.0, bypasses the getaway and the intent gate, and renders `USING: <skill>`. Every seeded
  route names a bare `personal`-scope skill. Under Command Code and Cline `personal` is foreign
  (`_foreign_scopes` tuples) and neither root holds any of the seven targets (verified:
  `~/.cline/data/settings/skills` and `~/.ohdsh/skills` contain none; `~/.codex/skills` and
  `~/.agents/skills` are symlinks to `~/.claude/skills`, so Codex/ZCode-shared-shelf are fine).
  A Command Code prompt containing "commit and push" now gets a top-of-menu `ak-git` it cannot
  load. Ledger population is small (commandcode 45 rows, cline 13, dsh 1) but the invariant
  ("the installed offer holds only skills THIS harness can invoke") is broken by construction.
- **Fix:** reuse the existing pure, filesystem-only test — in `_route_hits`, add
  `and not ("personal" in FOREIGN_SCOPES and not _invocable_twin(skill))` (for `commandcode`
  `_invocable_twin` returns False → routes inert there; for `dsh`/`cline`/divergent `zcode` it
  does the SKILL.md stat it already does for foreign rows). Pin it: a selftest under
  `RUNNING_HARNESS = "commandcode"` asserting `_route_hits("commit and push") == []`.

## MAJOR-2 — Keep-off activation is WARN-on-every-machine, then never refreshes through doctor

- **Where:** `scripts/doctor.py:1610-1641` (`check_keepoff`), `:2153` (fix loop), `setup.sh:119-129`.
- **Evidence (live):** `doctor.py` on this machine now prints
  `[!] Keep-off   no generated map yet (empty seed in use) — doctor --fix builds it …` → `status: WARN`.
  `setup.sh` runs `enrich_index --reapply`, `build_prompt_intent`, `apply-overrides` only — it
  never calls the keep-off fixer, so every install and every upgrade lands non-green until an
  operator runs `doctor --fix` by hand. CLAUDE.md sets "a green `status: OK` is the bar".
- **Second half (the real defect):** after the first `--fix` writes the inert map, the OK branch
  returns `"fix": None` while its own detail text says `regenerates on doctor --fix`
  (`doctor.py:1634-1638`). The fix loop is
  `todo = [r for r in results if r["status"] in (FAIL, WARN) and r.get("fix") in AUTO_FIXERS]`
  (`:2153`), so an OK row is never re-run. The map therefore populates only if someone runs
  `scripts/build_keep_off.py` directly. ADR-0054 §4 ("wired into doctor … `--fix` regenerates")
  and `docs/epoch-watch.md` W4 ("re-run `doctor --fix`") both describe a path that does not exist
  after the first run.
- **Fix (both halves, small):**
  1. `setup.sh` after line 129: `"$VENV/bin/python" "$ROOT/scripts/build_keep_off.py" || echo "  (keep-off build skipped — enforcer fails open)"` — idempotent, writes to the durable home, inert while thin.
  2. `doctor.py`: keep `"fix": "keepoff"` on the inert-OK branch and let `--fix` refresh it:
     `REFRESH_FIXERS = {"keepoff"}` and
     `todo = [r for r in results if (r["status"] in (FAIL, WARN) or r.get("fix") in REFRESH_FIXERS) and r.get("fix") in AUTO_FIXERS]`.
     Alternatively WARN when `generated_at` is older than 7 days while `data_sufficient` is false. Either way, make the detail text true.

## MINOR-1 — 8 of 12 harness-shape alternatives have zero ledger evidence; `<command-name>` is dead

- **Where:** `hooks/scripts/enforcer.py:1330-1335`, mirrored `scripts/build_keep_off.py:39-44`.
- **Ledger head-of-`q` counts (entire ledger):** `<task-notification>` 1700 · omp-msum 1546 ·
  `<system-reminder>` 36 · `<cross-session-message` 20 · **all others 0** (`<teammate-message`,
  "Another Claude session sent a message", "[Request interrupted by user", "[SYSTEM NOTIFICATION",
  "This session is being continued…", `<local-command-stdout>`, `<local-command-caveat>`, `<command-name>`).
- **The lead's `<command-name>` question, decided from code:** `hooks/scripts/ledger.py:126`
  shows a user slash command reaches UserPromptSubmit as raw `/name …` (it is logged as a
  `manual` event); the enforcer pre-gate `prompt.startswith("/")` (`:1893`) returns before the
  lane. Zero `<command-name>` and zero `<command-message>` rows exist in the ledger, so the
  expanded form never arrives at the prompt head. **Consequence: the alternative cannot suppress
  a real slash-command turn; it is dead surface, not a regression.** The seven other zero-count
  shapes come from the audit's *transcript-record* definition (`audit-…md:26`), which is not the
  hook's input. The repo's own rule (epoch-watch W1 "Never widen from vibes"; ADR-0049 "widen only
  from replayed ledger evidence") argues for trimming to the four evidenced shapes, or citing the
  transcript source in the comment so W1 replay has something to check.
- **Anchoring safety:** `re.match` + `^\s*` on the stripped prompt. A block pasted mid-prompt
  does not match (pinned by selftest 14 `harness_off[2]`). A block pasted **at the head** followed
  by a question does match and is skipped without a preview; the injected text's escape hatch
  ("if the message itself hands you work…") covers it. Acceptable.

## MINOR-2 — ADR claims selftest 6b pins blocklist-vs-route; it pins keep-off only

- **Where:** ADR-0054 Consequences ("blocklisted or keep-off'd … pinned by selftest 6b");
  `enforcer.py:2238-2250` sets `keepoff = frozenset({"chronic"})` only. `_blocked(skill)` inside
  `_route_hits` has no positive control. Add a 6c: `BLOCKLIST = frozenset({"victim"})`,
  `_ROUTES = [("deploy", "victim")]`, assert `_route_hits("deploy now") == []`. Or correct the ADR line.

## MINOR-3 — Stale leg-count prose (RULES [75])

- `openwiki/architecture/enforcement-gate.md:120` header "The AUTHORIZED-SKIP tier (three legs, two
  formerly silent)" — now four; `openwiki/operations.md:116` links to that anchor and was edited in
  this change set. `CLAUDE.md:14` still says `ENFORCER_AUTHORIZED_SKIP` acts "on its two silent
  verdict legs" in the same line that gained the `ENFORCER_HARNESS_SKIP` entry.

## MINOR-4 — `_HARNESS_MSG_RE` is duplicated with no parity pin

- `build_keep_off.py:35-44` mirrors `enforcer.py:1330-1335`; identical today (diffed). Nothing
  fails when they drift. Add a test in `tests/` asserting the two `.pattern` strings are equal
  (the generator deliberately avoids importing the hook, so the test is the right place).

## NIT-1 — Worst-path arithmetic in the constant comment disagrees with the docstring and ADR

- `enforcer.py:67`: "Worst path ≈ 0.5 + 4×0.25 ≈ 1.5 s". Docstring `:12-16` and ADR §3 say ≈ 1.75 s
  (five Qdrant legs: installed + 2× gate + external + foreign). Fix the comment.

## NIT-2 — Fallback rows now carry `offered`; downstream is safe, conversion undercounts

- `analyze._offer_conversion` (`:143`) and `build_keep_off._windows` (`:78`) key on
  `band == "offer"`, so a route shown through an embed/Qdrant fallback is **not** an offered turn
  (undercount, never miscount); hit@k (`analyze.py:599`) does include it. `auto_promote.py` and
  `build_chains.py` read neither `offered` nor `fallback`. W2's "fallback/offer row" wording is
  consistent. No action required; note it in the ADR if the conversion figure is ever compared to W2.

## NIT-3 — `check_keepoff` renders `None` values for a hand-made `{"keep_off": []}` durable file

- `doctor.py:1634-1637` interpolates `window_offered_turns` / `min_window_offered_turns` unguarded.
  Cosmetic; the generator always writes them.

---

## Acceptance criteria (ADR "Decision" §1-7 ↔ audit R1-R8)

| ADR § | Audit | Implemented as described | Evidence |
|---|---|---|---|
| 1 harness lane | R1 | Yes | `enforcer.py:1905-1908` before refusal/consult/selfref/embed; band `harness_skip`, `fallback="harness_message"`, `hint=False`; signature at `:1339`; selftest 14 (10 fire / 6 off) + selftest 7 (unique signature, no CHAIN-HINT) |
| 2 routes ON, pre-embed | R2 | Yes | `_load_routes` `:1168` (`=="0"` kill-switch); `_route_hits` `:1939` before `_embed`; three fallback branches inject `_ranked_mandate(_hits)` (`:1950,1955,1966`); `_merge_route_hits` drops the twin, keeps the real description (selftest 6); getaway/intent bypass `if not det` (`:1990,2005`). 14 routes → 7 skills, all present in `~/.claude/skills`. Gap: MAJOR-1 |
| 3 timeouts | R3 | Yes | `:69-70` 0.5 / 0.25 with revert comment |
| 4 keep-off | R4 | Partly | durable home (`_keepoff_path` `:806`, generator `OUT_DEFAULT`, doctor `KEEPOFF_DURABLE` — same env var); harness filter `:80`; keep-on exemption `:113`; window `2026-09-15`; doctor check + fixer wired. Gap: MAJOR-2 (refresh path). Dry run: offered-turns=4, inert |
| 5 dsh/cline foreign | R7 | Yes | every `_foreign_scopes` tuple + labels; `_retrieve_foreign(installed_bare=)` `:1516`; selftest pins per harness |
| 6 analyze outage-only | R6 | Yes | `OUTAGE_FALLBACKS` at both sites `:541`, `:604`; `--selftest` OK |
| 7 operator config | R5, R8 | Yes | all 7 names in `~/.claude/skill-concierge/keep-on.json`; `~/.claude/settings.json:65` `ENFORCER_ANNEX_MARGIN: "0.0"` |
| R10 hygiene | R10 | Yes | 4 manifests + quickstart at 0.47.0; CHANGELOG; ADR index; driftcheck IN SYNC |

## Touchpoint regressions checked (b)

- `main()` order verified byte-for-byte: pre-gate → harness → refusal → consult → selfref → routes → embed → retrieve → keep-off → blocklist → route merge → getaway → intent gate → annexes (`:1893-2058`).
- `_deterministic_hits`: **zero** references remain anywhere (hooks, scripts, skills, tests).
- `_retrieve_foreign` callers: `:2031` (new kwarg) and selftests `:2785`, `:2973` (default) — fine.
- `_authorized_skip_inject` callers: `:1907` (harness, `hint=False`), `:1933`, `:1998`, `:2007`, selftests — the `**fmt` `.format()` path is safe (no braces in `HARNESS_SKIP_MSG`).
- `_KEEPOFF_PATH`: single consumer `_load_keepoff` `:822`.
- `_ranked_mandate(cands, annex=None, foreign=None, takes=None)` renders a 1-item list without share/note (selftest 2 "lone" pin).
- `doctor._run` = `subprocess.run(capture_output=True, text=True)` — matches `fix_keepoff`'s `.returncode/.stdout/.stderr` use; `PY_BIN`, `JSON_READ_ERRORS`, `OK/WARN/FAIL` all exist.

## Public contracts (c)

- Env: `ENFORCER_HARNESS_SKIP` (`!= "0"`), `ENFORCER_DETERMINISTIC` (`== "0"` off — a prior `=1` stays ON; nothing in `~/.claude/settings.json` or `harness-env.sh` sets it), timeouts, `SKILL_CONCIERGE_KEEPOFF` (same path in all three consumers), `SKILL_CONCIERGE_KEEPON` (generator only). All documented in AGENTS.md / CLAUDE.md / operations.md.
- Ledger: new band `harness_skip` flows into `analyze`'s band Counter unchanged; `offered` on fallback rows — see NIT-2.
- Config JSON: `deterministic-routes.json` schema unchanged (`contains`/`skill`), loader validates types, fail-open.
- Signature lock: "harness-message lane" present in `HARNESS_SKIP_MSG` (`:1339`), absent from `hooks/doctrine/skill-first.md`, present in `_AUTHORIZED_SIGNATURES` (`audit_skill_usage.py:90`).

## Patterns (d)

Fail-open everywhere new (`_keepoff_path` OSError, `_keep_on_names`, `_load_routes`), stdlib-only, env kill-switches, ADR named in every new comment, selftests carry positive controls (`harness_off`, `_merge_route_hits([], …)`). Consistent with the file.

## Not checked

The TS adapters (untouched), `docs/multivector-retrieval-arc.md` and the 2026-09-06 report one-liners, other openwiki pages beyond grep, and no live prompt was fired through the hook end-to-end.
