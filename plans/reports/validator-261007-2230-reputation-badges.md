# Opus Validation Report: ADR-0083 owner reputation badges (uncommitted working tree)

**Subject:** implementation
**Scope:** `git diff` of `hooks/scripts/enforcer.py`, `hooks/scripts/auto_promote.py`, the docs (`AGENTS.md`, `CHANGELOG.md`, `CLAUDE.md`, `README.md`, `docs/adr/README.md`, `docs/epoch-watch.md`, `openwiki/operations.md`), plus the new files `docs/adr/0083-owner-reputation-badges.md`, `scripts/reputation.py`, `skills/reputation/SKILL.md` and `tests/test_reputation_badges.py`.
**Verdict:** FAIL. **DO NOT SHIP** in the current state. With B1 fixed, the verdict becomes **SHIP WITH CHANGES** (fix M1, M3 and L1 before release; the rest are advisory).
**Date:** 2026-10-07, Asia/Saigon. Tree fingerprint at 22:24:34 +0700 (sha256, first 16 hex): enforcer.py `1d5864771444cd94`, auto_promote.py `7327df4334dc7502`, reputation.py `30ac8593bb61e371`, test_reputation_badges.py `e8cef3e85a40d76f`, SKILL.md `40dbd0dcd44f8549`, ADR `65855e14429c9533`. The builder may still be editing, so these hashes pin the tree this report describes.
**Evidence files examined:** 17

## Executive Summary

The feature itself is correct. I checked these four things and found no defect in any of them:
- **Resolution rule:** works as specified.
- **Pull-in selection:** the index mapping is right. 2,000 random permutations produced 0 mismatches, and the feature worked on a live Jev turn.
- **The five ranked rows:** they never move, and their % shares are byte-identical with and without pull-ins.
- **Fail-open behaviour:** 22 bad-file cases produced no badge and nothing on stderr.

It does not ship, because the repo test suite is red. `_jev_route` now returns a 4-tuple, and `tests/test_jev_history.py:270` still unpacks 3 values. Result: 1 failed, 1027 passed. The same test passes at HEAD, and the builder's own full-suite record shows the same failure.

Three more problems should be fixed before release:
- A typo in any of the new tunables kills the hook at import.
- Three documents say the standing order carries a choosing rule it does not carry.
- Skip-band ledger rows record "badges" for rows that were never shown.

## Observable Truths

| # | Claim (owner requirement / ADR) | Status | Evidence |
|---|---|---|---|
| 1 | ❤️/⭐ come from a curated `reputation.json`, exact names or patterns | VERIFIED | `enforcer.py:1009-1036`, edge run "regex-specials", "unicode" |
| 2 | An exact entry beats a family pattern; between two matches of one kind ❤️ wins | VERIFIED | `enforcer.py:1047-1064`; `test_exact_entry_beats_family_and_heart_beats_star` passed |
| 3 | Badges sit next to the name and never reorder the menu | VERIFIED | `enforcer.py:2921`; paths run: shares identical (pasted below) |
| 4 | Pull-in: ❤️/⭐ rows that Jev ranked 6-10 with `fits` ≥ 0.5, at most 2, never displacing the five | VERIFIED | `enforcer.py:2100-2117`; 2,000-permutation oracle, 0 mismatches; live turn pulled `ak-review-pr` |
| 5 | `fits::i` is indexed by shortlist order, not Choice rank | VERIFIED (code) / UNTESTED (repo tests) | `enforcer.py:2061-2062` and `2105,2113`; a mutation to rank indexing passes all 12 repo tests (L2) |
| 6 | The five rows' % shares are unchanged | VERIFIED | `enforcer.py:2895` (total over `cands` only); shares w/o == w/ pull |
| 7 | 🔥 = 5 distinct sessions in 30 days, subagents excluded | VERIFIED | `auto_promote.py:165-184`; real-ledger read-only scan: 169 / 28 / 11, which matches the ADR |
| 8 | 🔥 digest is written independently of catalog/PROMOTE settings, and throttled | VERIFIED | `auto_promote.py:204-219`; `PROMOTE_ENABLED=0` run wrote 28 names; second run throttled |
| 9 | Every menu path handles the 4-tuple and old 3-tuples | VERIFIED | paths run: embed_timeout, embed_down, qdrant_down and normal × {4-tuple, 3-tuple, skip} all rc=0 with empty stderr |
| 10 | Everything else that consumes the Jev result still works | **FAILED** | `tests/test_jev_history.py:270` raises ValueError (B1) |
| 11 | Hook never crashes or prints to stderr | **PARTIAL** | Bad files: pass. Bad env tunables: traceback at import (M1) |
| 12 | `SKILL_REPUTATION=0` turns everything off; `PULL_MAX=0` keeps badges and drops pull-in | VERIFIED | edge run "kill"; `test_pull_in_respects_bar_depth_cap_and_badges` |
| 13 | Offer events carry `badges` for every shown or pulled row (ADR §4) | **PARTIAL** | skip bands also record badges for rows never shown (L1) |
| 14 | The choosing rule rides with the legend, not the doctrine (ADR §2) | **PARTIAL** | the code does this; 3 docs say the opposite (M3) |
| 15 | Docs match the code defaults | PARTIAL | numbers all match; AGENTS.md names a non-reader, and SKILL.md omits DEPTH (L4) |
| 16 | Live drive writes no real state | VERIFIED | 0 rows with my session ids in the real ledger; no real reputation.json or proven.json |

## Key Dependency Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `docs/adr/0083-owner-reputation-badges.md` | repo | file | L1 ✓ L2 ✓ L3 ✓ | linked from `docs/adr/README.md`, AGENTS, CLAUDE, README, openwiki; driftcheck IN SYNC |
| `scripts/reputation.py` | `skills/reputation/SKILL.md` | CLI | L1 ✓ L2 ✓ (202 lines) L3 ✓ | invoked in SKILL.md steps 1-4 |
| `skills/reputation/SKILL.md` | plugin | skill dir | L1 ✓ L2 ✓ L3 ✓ | `skill-list-parity` check passed |
| `tests/test_reputation_badges.py` | enforcer, reputation.py | importlib | L1 ✓ L2 ✓ L3 ✓ | 12 tests pass |
| `enforcer._jev_pull_ins` | `_jev_route` → `main` / `_jev_serve` | 4th tuple element | ✓ | `enforcer.py:2356-2357, 2414-2422, 3220, 3278-3295` |
| `auto_promote._write_proven` | `enforcer._load_proven` | `proven.json` (`SKILL_CONCIERGE_PROVEN`) | ✓ | same default path in both files and in reputation.py |
| audit `_OFFER_ROW` | badged menu text | regex `^\s*•\s+([^\s(]+)` | ✓ | `_shelf_top` on a badged menu returned `code-review` |

## Raw evidence

### Test runs (Python 3.12.11, `~/.claude/skills/.venv/bin/python3`, `-p no:cacheprovider`, `PYTHONDONTWRITEBYTECODE=1`)

Focused set:
```
tests/test_reputation_badges.py tests/test_jev_router.py tests/test_doctrine_text.py tests/test_ruling_parsers.py
91 passed in 33.78s
```
Full suite (`/tmp/val-rep/fullsuite.txt`):
```
>       verdict, rows, best = res["result"]
E       ValueError: too many values to unpack (expected 3)
tests/test_jev_history.py:270: ValueError
FAILED tests/test_jev_history.py::test_history_alone_never_skips - ValueError...
1 failed, 1027 passed in 337.62s (0:05:37)
```
HEAD baseline (`git archive HEAD` → `/tmp/val-rep/head`):
```
tests/test_jev_history.py ... 27 passed in 1.59s
```
The builder's own record, `plans/261007-2205-reputation-badges/full-suite.txt`, written at 22:20, shows the same failure:
```
FAILED tests/test_jev_history.py::test_history_alone_never_skips - ValueError...
1 failed, 1027 passed in 305.56s (0:05:05)
```

### Selftests and driftcheck
```
enforcer --selftest OK: refusal guard (5 fire / 6 silent) + ranked-mandate %-share + ... + CJK word-count (...)
auto-promote --selftest OK            (3.12.11)
auto-promote --selftest OK            (/usr/bin/python3 3.9.6)
reputation selftest ok                (3.12 and 3.9)
IN SYNC: every fact matches its source of truth.
```
Note: the enforcer selftest has no ADR-0083 leg. The feature is covered only by the pytest file.

### Live drive through stdin (one Jev tier, `env -u JEVD_URL ENFORCER_JEV_BENCH="ts:jev-1.13.0"`; one turn = 2 Jev calls)

I put the owner's list in a temp file: `{"heart":["ak-*"],"star":["pstack:*","agent-skills:*"]}`. The temp 🔥 digest held `ak-git`, `unlazy` and `code-review`.
```
rc=0 stderr_bytes=       0
Whole-shelf ranking for this task (every skill you can use judged):
  • ak-code-review ❤️ (79%) — Review code quality with evidence-based rigor. ...
  • code-review 🔥 (9%) — Review the changes since a fixed point ...
  • agent-skills:code-review-and-quality ⭐ (9%) — Conducts multi-axis code review. ...
  • piv-review-changes (3%) — Performs a technical code review ...
  • ak-git ❤️🔥 (0%) — Git operations with conventional commits. ...
Shares are RELATIVE rank among these few ...
On the owner's list, ranked lower by Jev but judged a fit for this task:
  • ak-review-pr ❤️ — Review GitHub pull requests for correctness, regressions and security. ...
ROUTE: ...
Badges are the owner's ranking: ❤️ house favourite, ⭐ trusted, 🔥 used often here. Choose in two passes: ...
---LEDGER
{"band": "offer", "offered": [["ak-code-review", 0.79], ...], "pulled": [["ak-review-pr", 0.0]], "badges": {"ak-code-review": "❤️", "code-review": "🔥", "agent-skills:code-review-and-quality": "⭐", "ak-git": "❤️🔥", "ak-review-pr": "❤️"}, "jev": {... "model": "jev-1.13.0", "tier": 0, ... "pulled": ["ak-review-pr"]}}
```
Preview-path drive (`ENFORCER_JEV_ROUTER=0`): rc=0, empty stderr, and badges plus the legend rendered. Row 1 was `ak-github ❤️` on a code-review task.

The real ledger stayed clean:
```
real-ledger rows with my sids: 0
reputation.json / proven.json: No such file or directory   (real ~/.claude/skill-concierge)
```

### Every render path × result shape (in-process `main()`, embed/retrieve/Jev monkeypatched)
```
embed_timeout/4-tuple  rc=0 stderr='' whole_shelf=True pulled_block=True legend=True ev.band=offer ev.fallback=embed_timeout ev.pulled=[['ak-code-review', 0.03], ['pstack:interrogate', 0.02]]
embed_timeout/3-tuple(old) rc=0 stderr='' ... pulled_block=False ...
embed_down/*, qdrant_down/*, normal/*   all rc=0, stderr=''
normal/skip-4          rc=0 stderr='' ... ev.band=jev_skip ev.fallback=jev_no_fit ev.pulled=None ev.badges={'code-review': '🔥'}
shares w/o pull: [('code-review', '50'), ('refactor', '22'), ('tdd', '11'), ('ak-git', '11'), ('deslop', '6')]
shares w/  pull: [('code-review', '50'), ('refactor', '22'), ('tdd', '11'), ('ak-git', '11'), ('deslop', '6')]
identical: True
audit _shelf_top: code-review
```

### Pull-in index-mapping oracle (2,000 random Choice-vs-shortlist permutations, plus an unknown option name)
```
trials ok, mismatches: 0
```
A mutation test showed the repo tests cannot see this mapping. I copied the tree to `/tmp/val-rep/mut` and changed the code to index `fits::` by Choice rank. The result:
```
mutated
12 passed in 0.50s
```

### Fail-open matrix (22 file cases; abridged)
```
absent / not-json / list-root / string-root / null-root / heart-str / heart-dict / heart-null / binary / utf16 / bom : OK no badge, stderr=''
heart-mixed ([1,None,{..},["ak-git"]," ak-git ",""]) : OK ak-git ❤️
regex-specials ("[z-a]","[","a[b","(?",".*","\\","[!]","**",...) : OK, stderr=''
unicode / proven-str / proven-dict / proven-root-list / proven-mixed / proven-binary / proven-null / kill / dir-as-file : OK
env SKILL_REPUTATION_PULL_FIT=abc: RAISE ValueError
env SKILL_REPUTATION_PULL_MAX=two: RAISE ValueError
env SKILL_REPUTATION_PULL_DEPTH=1.5: RAISE ValueError
huge (50k exact + 5k patterns): render+ledger for 6 unbadged names 0.318s
```
On 3.12 and 3.11, fnmatch accepts every invalid-range pattern without error. On 3.9.6 it raises `re.error` for `[z-a]`, `[a-\]` and `[b-a-c]`.

### auto_promote (read-only scan of the real 5.2 MB ledger; `main()` on a temp copy with `PROMOTE_ENABLED=0`)
```
3.9.6  scan 12 ms; skills used in window 169; >=5 sessions 28; >=8 11
3.12.11 scan 10 ms; ...same...
Python 3.9.6  rc=0 real 0.04 proven=28 5 30
Python 3.12.11 rc=0 real 0.19 proven=28 5 30
--- throttled second run: rc=0 proven2 exists? no
--- SKILL_REPUTATION=0 + PROMOTE_ENABLED=0: rc=0 stamp=none proven3=none
```

## Blocking Issues (FAIL)

1. **B1: the repo test suite is red (maps to Truth #10).**
   - **Where:** `enforcer.py:2357` changed `_jev_route`'s result to `(verdict, rows, best, pulled)`, but `tests/test_jev_history.py:270` still does `verdict, rows, best = res["result"]`.
   - **Evidence:** full suite 1 failed / 1027 passed. The same file passes at HEAD (27 passed). The builder's own `plans/261007-2205-reputation-badges/full-suite.txt` records the same failure, so this went past the builder's own check.
   - **Stale docstrings, same cause:** `_jev_route` (`enforcer.py:2278`, `-> {"result": (verdict, rows, best_fit) | None ...}`) and `_jev_join` (`enforcer.py:2392`, `-> (verdict, rows, best_fit) or None`) still describe the 3-tuple.
   - **Fix:** in the test, unpack `verdict, rows, best = res["result"][:3]` (or `*_`), and assert the pulled element too. Update both docstrings to the 4-tuple.

## Advisory Suggestions (WARN), ranked by severity

### Medium. Fix before release.

**M1: a typo in a new tunable kills the hook at import (Truth #11).**

These lines parse with raw `float()` and `int()` at module level:
- `enforcer.py:2095-2097` (`SKILL_REPUTATION_PULL_FIT`, `_MAX`, `_DEPTH`)
- `auto_promote.py:161-162` (`SKILL_PROVEN_MIN_SESSIONS`, `_WINDOW_DAYS`)

The repo already has the guard for this: `_env_int` at `enforcer.py:1809`, whose docstring reads "A malformed tunable falls back to its default: a hook never dies at import over an env typo." The new code did not use it.

Failure scenario: the ADR and W41 tell the owner to set `SKILL_REPUTATION_PULL_FIT=0.7` in `~/.config/harness-env.sh`, which reaches every harness. A typo such as `0,7` then removes the menu on every turn, in every harness, and prints this:
```
  File ".../hooks/scripts/enforcer.py", line 2095, in <module>
    REPUTATION_PULL_FIT = float(os.environ.get("SKILL_REPUTATION_PULL_FIT", "0.5"))
ValueError: could not convert string to float: '0,5'
rc=1
...
  File ".../hooks/scripts/auto_promote.py", line 161, in <module>
    PROVEN_MIN_SESSIONS = int(os.environ.get("SKILL_PROVEN_MIN_SESSIONS", "5"))
ValueError: invalid literal for int() with base 10: 'five'
rc=1
```
Fix: use `_env_int` and add a matching `_env_float` in both files. Also clamp `PULL_DEPTH` to ≥ 0, because `-1` makes the slice `order[5:-1]` and pulls from far below rank 10 (L7). The older knobs at `enforcer.py:99-165` have the same flaw. That is pre-existing, but it is the same defect class.

**M2: the legend fires on 🔥 alone, and 🔥 is automatic.**

`enforcer.py:2970` adds the full legend (352 characters, 370 UTF-8 bytes, 65 words, roughly 80-100 tokens by estimate) whenever any shown row has any badge.

With an empty `reputation.json`, today's 28-name digest alone would put the legend on 219 of the 311 offer-band rows from the last 7 days (70%). That figure is indicative only: it pools epochs. The current epoch, since `3e2f522` at 21:10, has 9 of 10 rows, which is insufficient data.

So the ADR's line "a turn without badges should pay nothing" is true on paper, but in practice the legend is near always-on before the owner curates anything. On those turns it explains ❤️/⭐ tiers that do not appear.

Fix (the owner's call): print the ❤️/⭐ rule only when a ❤️ or ⭐ row is shown, and use a one-clause 🔥 note otherwise.

**M3: three documents say the standing order carries the choosing rule; it does not (Truth #14).**

ADR §2 says "The choosing rule rides with the badges, not the doctrine". The doctrine `hooks/doctrine/skill-first.md` is unchanged and says nothing about badges. These three places contradict that:
- `enforcer.py:992`, comment: "The doctrine tells the agent how to choose with them."
- `scripts/reputation.py:11`, docstring: "The standing order tells the agent how to choose with them".
- `skills/reputation/SKILL.md:21`, which an agent reads: "The standing order tells the agent how to choose".

Fix: say "the menu's legend".

### Low

**L1: skip rows record `badges` for rows that were never shown (Truth #13).**

`_append_offer` (`enforcer.py:1488-1492`) badges every name in `offered`. The `getaway` (`:3233`), `intent_skip` (`:3242`) and `jev_skip` (`:3215`) callers pass retrieval candidates that were never shown. Evidence: `normal/skip-4 ... ev.band=jev_skip ... ev.badges={'code-review': '🔥'}`.

Every row is `ev:"offer"`, so a W41 query for "offer events with `badges`" that forgets `band == "offer"` counts skipped turns.

Fix: compute `badges` only when `band == "offer"`.

**L2: the tests cannot see the `fits::` index mapping.**

`tests/test_reputation_badges.py:104-109` builds answers whose Choice order equals shortlist order. The rank-indexing mutation above passes all 12 tests. The code is correct (the oracle found 0 mismatches).

Fix: add a test with a permuted Choice order.

**L3: `scripts/reputation.py` disagrees with the hook on hand-edited files and crashes on some of them.**

Raw output:
```
padded " ak-git " entry: hook {'ak-git': ' ❤️'}  vs  why → "ak-git: (no badge)"
non-str entry 7: why → TypeError: argument of type 'int' is not iterable
               add → TypeError: '<' not supported between instances of 'int' and 'str'
malformed JSON: list → json.decoder.JSONDecodeError traceback
SKILL_REPUTATION=0: why → "ak-git: ❤️ — heart via exact entry" (hook shows nothing)
/usr/bin/python3 3.9, entry "[z-a]*": why → re.error: bad character range z-a at position 5
```
SKILL.md calls it with bare `python3`, so the 3.9 crash is reachable.

The test that "holds them equal" (`test_reputation_badges.py:163-171`) uses only a clean dict.

Fix: share the hook's normalization (str-filter, strip), print a clean error on bad JSON, honour the kill switch in `why`, and catch `re.error`.

**L4: two documentation gaps.**
- `AGENTS.md` (SKILL_REPUTATION entry) lists `scripts/reputation.py` as a consumer of `SKILL_REPUTATION`. The script never reads it.
- The switches table in `skills/reputation/SKILL.md:67-72` omits `SKILL_REPUTATION_PULL_DEPTH` (10).

**L5: a pulled skill can also appear in the "Other-harness … NOT invocable" block.**

`enforcer.py:3268` builds `_retrieve_foreign`'s `installed_bare` from `_jev_rows + cands`, not from the pulled rows. A re-rooted twin of a pulled skill (the ADR-0054 case at `:2664-2668`) could then render under "Other-harness … NOT invocable".

Fix: add the `_pulled` names to that set. The window is narrow.

**L6: `_jev_pull_ins` runs outside the per-tier `try` (`enforcer.py:2356`).**

It cannot raise on an answer that `_jev_decide` accepted today, because both read the same validated keys. A future change that raises there would turn a valid Jev verdict into a thread-boundary error (`enforcer.py:2384`), and the embedding path would decide the turn.

Fix: move it inside the `try`, or wrap it to return `[]`.

**L7: a negative `PULL_DEPTH` widens the pull window.** Covered by M1's clamp.

**L8: a UTF-8 BOM or UTF-16 `reputation.json` silently shows no badge.** Edge runs "bom" and "utf16" confirm it. No doctor row reports it. A Windows-edited file would turn the owner's ranking off with no signal.

**L9: builder scratch file.** `plans/261007-2205-reputation-badges/enforcer.pre-mutation.py` (4,572 lines, mode 755) is an untracked scratch copy. Archive it before any broad `git add`.

### Design WARN (owner's call; no code defect)

**W1: the legend can steer the agent to a badged row that does not do the job.**

The live turn showed it. Row 5, `ak-git ❤️🔥`, had a 0% share. The legend says 🔥 breaks a tie inside the ❤️ tier, so an agent that stretches "before I merge them" into ak-git's job would choose it over row 1, `ak-code-review ❤️`.

The preview drive showed the same thing: `ak-github ❤️` sat at row 1 for a code-review task.

The only guard is the agent's own first pass ("does this task's job as its main purpose"). That is the risk the ADR accepted and W41 watches. It is recorded here as observed, not hypothetical.

**W2: does 🔥 break ties among unranked rows?**

The owner's rule says "🔥 breaks a tie only inside one tier; same badge → menu order". The legend says "then the highest row, and let 🔥 break a tie inside one tier". Neither says whether "no badge" counts as a tier.

So when row 1 has no badge and row 3 carries only 🔥, and both do the job, the legend allows either reading. The legend also never says outright that rows with the same badge go in menu order.

This needs the owner's ruling. Then make the legend say it.

**W3: the doctrine and the legend pull in different directions.**

Doctrine rule 3 says "Closest fit, adapted, is the standard". The legend picks a lower ❤️ row over a closer fit. Rule 3 covers search hits, so there is no literal contradiction on the menu. But the doctrine never mentions badges, and the legend's first-pass bar ("main purpose") is stricter than the doctrine's take bar ("loosely adapted"). When no row passes the strict pass, the legend is silent and the doctrine governs.

Worth one line in the W41 hand-read rubric.

**W4: pre-existing, out of scope.** `hooks/scripts/enforcer.py` already fails on `/usr/bin/python3` 3.9.6 at HEAD (line 756: `TypeError: unsupported operand type(s) for |`). `hooks.json` runs bare `python3`, and it works only because PATH resolves to pyenv 3.12. The new `_owner_tier` signature adds more 3.10+ syntax of the same kind. `auto_promote.py` and `reputation.py` run on 3.9 (verified).

**W5: large lists are slow.** 50,000 exact entries plus 5,000 patterns cost 0.32 s for 6 names, because exact entries are scanned linearly through a tuple. Realistic lists are tiny. Optional fix: use a frozenset for exact entries.

## Validation Dimensions

- [x] Resolution rule: PASS. Evidence: `enforcer.py:1047-1064`, tests, edge runs.
- [x] Pull-in selection, index mapping, cap, depth and bar: PASS in code; WARN for test coverage (L2). Evidence: oracle with 0 mismatches; live pull.
- [x] The five rows never move and shares are unchanged: PASS. Evidence: shares identical.
- [ ] Consumers of the Jev result: FAIL (B1).
- [x] Render paths (main, `_jev_serve` × 3 outages, preview), 3- and 4-tuples: PASS.
- [x] Fail-open on files: PASS (22 cases, empty stderr). [ ] Fail-open on env: FAIL (M1).
- [x] auto_promote (independence, throttle, 3.9, scan cost 12 ms on 5.2 MB): PASS.
- [x] Token cost and steering: WARN (M2, W1, W2, W3).
- [x] Doctrine contradiction: no literal contradiction (W3); doctrine unchanged, `test_doctrine_text` passes.
- [x] Docs vs code numbers: PASS for every number. WARN on wording (M3, L4).
- [x] Selftests and driftcheck: PASS.
- [x] Live stdin drive with temp state and no real ledger rows: PASS.
- [x] Anti-pattern scan of new files: no credentials and no TODO/FIXME in the new code. The `print` calls in `reputation.py` are its CLI output.

## Unverifiable Items

- **Agent behaviour under the legend.** Only a live W41 sample can measure whether agents stretch the first pass. I showed the menus that create the risk, not how often agents fall for it.
- **The token count of the legend** is an estimate from character and word counts. I had no tokenizer offline.
- **The 70% legend frequency** pools epochs. The current epoch has 10 rows, which is insufficient data.
- **Other harnesses.** I ran nothing through the Codex, OMP, Command Code, ZCode, DSH or Cline adapters. They forward the enforcer's stdout, and the change does not touch them.

## Context Gaps

- **Whether "no badge" is a tier for 🔥 tie-breaks (W2).** This needs the owner's ruling.
- **Whether the owner wants the full legend on 🔥-only turns (M2).**

## What I did not check

- The Codex/OMP/other harness adapters.
- graft/ index files modified during the run. I did not invoke graft; something else refreshed them.
- Every pre-existing env knob beyond noting the M1 class.

---
Status: DONE_WITH_CONCERNS
Summary: The feature logic is correct (resolution, pull-in mapping, shares, every render path, fail-open on files, auto_promote on 3.9). The release is blocked by one failing repo test (`test_jev_history.py:270`, 3-tuple unpack), and env typos crash the hook at import. Verdict: DO NOT SHIP until B1 is fixed; then SHIP WITH CHANGES (M1, M3, L1).
