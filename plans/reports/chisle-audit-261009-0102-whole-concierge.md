# Chisle audit of the whole concierge, and the cuts applied (2026-10-09)

Owner order, 01:02: "/chisle-audit the whole concierge and report findings then autonomously proceed to fixing
the worth fixing issues while i went on AFK mode now". Base: `main` 692cab1 (v0.64.0). Fixes: branch
`chore/chisle-audit-cuts`, commit db91b7c (v0.64.1).

## How it ran

Six read-only audit agents, one per area, under one brief (`plans/261009-0102-chisle-audit/BRIEF.md`): every
"no caller" claim needed a grep count, every stale-prose claim a contradicting `file:line`. Out of scope: `vendor/`,
`docs/adr/`, `docs/journals/`, `plans/`, `tests/`. Then six fix agents with disjoint file ownership in one
worktree, under one policy (`FIX-POLICY.md`): apply high-confidence and proven-dead/proven-stale medium findings that
keep behaviour the same; fix real defects with a failing-first test; skip feature cuts and structural moves.

## Findings and dispositions

| Area | Findings file | Disposition lines | Applied | Skipped |
|---|---|---|---|---|
| A — `hooks/scripts/enforcer.py` | `findings/A-enforcer.md` | `A-dispositions.md` | 23 (4 partial) | 10 |
| B — other hooks, `bin/`, `skills/` | `B-hooks-bin-skills.md` | `B-dispositions.md` | 11 | 11 |
| C — doctor, sieve_recall, calibrate, analyze, precision_eval, consult_fit | `C-scripts-big.md` | `C-dispositions.md` | 20 | 13 |
| D — every other script, archive of retired tooling | `D-scripts-rest.md` | `D-dispositions.md` | 25 | 4 |
| E — `adapters/`, `setup.sh` | `E-adapters.md` | `E-dispositions.md` | 13 | 13 |
| F — README, AGENTS, CLAUDE, docs/, openwiki/ | `F-docs.md` | `F-dispositions.md` | 36 | 5 |

Counts are disposition lines (a few findings were split into two lines). Every line names FIXED or SKIPPED with its reason.

Net diff: 91 files, +1,237 / −4,375 lines.

## Real defects the audit surfaced (all fixed, each with a test)

1. `enforcer.py` and `ledger.py` crashed at import on macOS's system Python 3.9 (`str | None` annotations).
   `hooks/hooks.json` runs plain `python3`; a harness whose PATH lacks Homebrew gets 3.9, so the turn had no menu and
   no ledger row, silently. Test: `tests/test_python39_hooks.py`.
2. Nothing ran the enforcer's or doctor's built-in `--selftest` under pytest (the enforcer one had been failing on
   main unnoticed). Test: `tests/test_builtin_selftests.py`.
3. `doctrine.py` did not recognise OpenCode and named Claude Code's search tool there.
4. `skill_exclusions.py` carried a drifted fallback copy of the ledger's tool names.
5. The ZCode installer's non-git export lacked the `.zcode`/`.unlazy` excludes its siblings have.
6. The DSH unlazy stop bridge read the session from the plugin context instead of the event (fixed with fallbacks;
   no DSH test harness exists, so it is verified by parse and by reading DSH's own plugin, not live).
7. The OpenCode `package.json` version had drifted to 0.62.0; driftcheck now mirrors both `package.json` files.
8. The README told users to `rm -f ~/.codex/hooks.json`, which could delete their own Codex hooks.
9. The 0.22.0 release notes existed only in the README history being cut; they are now a CHANGELOG entry.

## Left for the owner (decisions, not done)

Update 2026-10-09 ~03:03: Thinh approved items 1–4 ("do 1, 2, 3, 4"); all four shipped in v0.65.0 (ADR-0088,
`plans/261009-0305-maintenance-four/`). Item 5 stays open.

1. **Move `enforcer.py`'s 1,266-line `_selftest` (and doctor's 516-line one) into tests/.** Saves ~8.6 ms of compile
   on every prompt (measured: 26.3 vs 17.7 ms) and 27 % of the hot file. Skipped because the `--selftest` CLI is cited
   by immutable ADRs and it is a structural move of the hot file in an unattended run. Recommend: yes, as its own change.
2. **Delete the dominance-collapse and per-skill-tau features** (both default-off, never armed; the Sept 26 audit
   proposed the same). Feature cuts are the owner's call. Recommend: delete.
3. **One shared helper library for the installers** (~160 lines; one copy had already drifted). Skipped: installers are
   self-contained per harness by design. Recommend: yes, `adapters/lib/sync.sh`, with a test that every installer sources it.
4. **One shared harness detector** across enforcer, doctrine and ledger (~80 lines; the copies had drifted). Skipped
   because the ledger's Claude rows carry no harness today and would change. Recommend: yes, keeping that row shape.
5. `docs/plan.md` and `docs/anti-dodge-integration-v0.14.md` archiving; `CLAUDE.md` → `@AGENTS.md` import.

Verification, review and ship status: `plans/261009-0102-chisle-audit/GATES.md`.
