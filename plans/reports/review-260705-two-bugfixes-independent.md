# Independent Review: two bugfixes (analyze.py join bug, enforcer.py keep-off bypass)

Reviewer: independent, read-only. Did not write either fix. All claims are grounded in the file
as read (`git diff HEAD` + `Read`) plus a live `--selftest` run and hand-executed reproductions of
the pre-fix behavior. Root: `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge`.

**Verdict: APPROVE** (both fixes)

---

## Change 1 — `scripts/analyze.py` — dup-prefix offer/turn join

### The bug, confirmed

Old code (`git diff HEAD` old-side, shown in the diff output) kept `by_sid_q = {}` — a **plain
dict** keyed by `(sid, q)` — and matched offers to turns with `by_sid_q.get((sid,q))`. Two turns
in the same session sharing an identical 120-char prompt prefix (e.g. two consecutive `"continue"`
turns) both map to the *same* dict key, so the second `turn` event overwrites the first turn's
entry in `by_sid_q`. When offers are matched afterward, **both** offer events resolve to whatever
window is currently sitting in the dict — the last one written — silently collapsing turn 1's
offer onto turn 2's window and leaving turn 1's `offered` as `None`.

### The fix

`scripts/analyze.py:143` — `by_sid_q = defaultdict(deque)`; `scripts/analyze.py:152` — `by_sid_q[(sid, w["q"])].append(w)` (queue instead of overwrite); `scripts/analyze.py:172-178` — the offer-matching loop now does `q = by_sid_q.get(...)`, `if q: w = q.popleft()`, pairing each `offer` to the **oldest still-unmatched** turn with that `(sid,q)` key, in arrival order. Import added at `scripts/analyze.py:36`: `from collections import Counter, defaultdict, deque`.

### Is deque/popleft correct given the event ordering?

Verified directly from `hooks/hooks.json:20-34`: `UserPromptSubmit` runs `enforcer.py` (which
emits the `offer` event) **before** `ledger.py` (which emits the `turn` event) in the same hook
array, for the same prompt submission. So for a given turn, its `offer` is written strictly before
its `turn` in wall-clock/log order — matching the docstring at `scripts/analyze.py:138-142`
verbatim: *"`offer` fires in the SAME UserPromptSubmit as its `turn` but just BEFORE it (hook array
order)"*. Since `events.sort(key=lambda e: e.get("t", 0))` (line 253) is a **stable** sort and
offers/turns for the same prompt round-trip arrive in that order, first-offer-then-first-turn
pairs up correctly via FIFO `popleft()`. This is correct for the documented contract.

### Edge cases

- **Offers with no matching turn** (queue empty or key absent): `by_sid_q.get(key)` returns `None`
  for an absent key (plain `.get()` does not invoke `defaultdict`'s factory), and an **empty**
  `deque()` is falsy in Python, so `if q:` is `False` in both cases — the offer is silently
  dropped, same fail-open posture as the old code (old code: `if w is not None: ...`). No crash,
  no misattribution.
- **More offers than turns for the same `(sid,q)`** (e.g. 2 offers, 1 turn): I traced this by hand.
  New code: the *first* offer's `popleft()` consumes the one turn; the second offer's queue is now
  empty → dropped (turn keeps the **first** offer's data). Old code: dict `.get()` always returns
  the same single window regardless of how many offers hit it, so **each** offer would overwrite
  `w["offered"]`, and the window would end up holding the **last** offer's data. This is a genuine,
  if narrow, behavior change (first-wins vs. last-wins) for an anomalous case the docstring itself
  says shouldn't happen in the normal 1:1 hook contract. Not a regression against the stated bug,
  and arguably more defensible (first offer temporally corresponds to the one real turn), but worth
  a one-line docstring note since it wasn't called out. **Suggestion-level, not blocking.**
- **Manual events**: unaffected — only `ev == "turn"` populates `by_sid_q` (line 151), matching the
  pre-fix behavior; `manual` windows never receive `offered` data in either version.

### Does the extraction preserve prior behavior for the non-duplicate path?

Line-by-line diff of the removed `main()` block vs. the new `_segment_windows()` function shows
the **only** substantive changes are the dict→`defaultdict(deque)` swap and the
assign→append/`.get()`→popleft change described above; the turn/manual/auto/search branches are
copied verbatim. For the common case (each `(sid,q)` seen once), a 1-item deque behaves identically
to the old single dict value: `popleft()` on a single-element deque returns that element, same as
`.get()` would have. Confirmed no behavior change on the non-duplicate path.

### Selftest — genuine regression guard?

Ran directly: `python3 scripts/analyze.py --selftest` → `OK`. To confirm it's a real guard (not a
tautology), I hand-simulated the **old** dict-based join against the exact `dup_events` fixture
(`scripts/analyze.py:204-211`): with a plain dict, turn 1's window (`w1`) is opened, then
overwritten in `by_sid_q` when turn 2 opens; both offers (`a`, `b`) then resolve via `.get()` to
`w2` only, so `w1["offered"]` stays `None` and `w2["offered"]` ends up `["b"]` (last-write-wins).
The test's assertion `jt[0]["offered"] != ["a"]` (it'd be `None`) fires
`bad.append(...)` → selftest **FAILS** under the pre-fix dict logic. Confirmed by direct trace, not
assumed — this is a real regression guard, not a test that would pass either way.

### Scope

Diff is `+66/-43`, but the bulk is a pure extraction (move code into a named function) plus the
minimal container swap — no unrelated logic touched. Not scope creep.

---

## Change 2 — `hooks/scripts/enforcer.py` — keep-off bypass via deterministic route

### The bug, confirmed

`_drop_keepoff(cands, KEEPOFF)` runs first (`enforcer.py:502`) and strips any keep-off'd skill out
of `cands`. The old `_deterministic_hits(prompt, cands)` (2-arg signature) then computed
`have = {n for (n,_d,_s) in cands}` from the **already-filtered** `cands` — so a keep-off'd skill,
having just been removed, is by construction *not* in `have`, and a co-configured route pointing at
that same skill would re-add it at score `1.0`, a score that (per the comment at
`enforcer.py:504-506`) "bypasses both the getaway and the actionability gate." This exact
interaction was already identified in a prior read-only review
(`plans/reports/review-260705-enforcer-gate.md`, section "P5 keep-off hard-drop can be silently
un-dropped by a deterministic route"), which reproduced the same bypass against the live functions.
I independently re-verified it by monkeypatching a copy of `_deterministic_hits` with the *route
condition* reverted (`skill not in have` only, no keepoff check) while keeping the new 3-arg call
signature intact — confirmed the bypass reproduces: `det = [('chronic', 'deterministic route',
1.0)]`.

### The fix

`enforcer.py:220` — `_deterministic_hits(prompt, cands, keepoff=frozenset())`; `enforcer.py:232` —
route condition becomes `sub in low and skill not in have and skill not in keepoff`; call site at
`enforcer.py:507` — `_deterministic_hits(prompt, cands, KEEPOFF)`.

### `frozenset()` default — mutable-default trap?

No. `frozenset` is immutable in Python (no in-place mutators — `.add`/`.update`/etc. don't exist
on it), so there is no shared-mutable-default hazard here, unlike the classic `def f(x=[])` trap.
Confirmed by inspection; this is a safe default.

### Does passing `KEEPOFF` at the call site fully close the bypass, or is there another path?

`_deterministic_hits` is called from exactly **one** production call site
(`enforcer.py:507`, confirmed via `rg -n "_deterministic_hits" hooks/scripts/enforcer.py` — every
other hit is inside `_selftest`). `cands` reaching that call site has already been through
`_drop_keepoff` at line 502, so it's double-gated: filtered-out skills aren't in `cands`, and even
if a route names one, the new `skill not in keepoff` check blocks it from being prepended. I
looked for "routes added after keepoff elsewhere" as the task asked: there is no second place in
this file (or in `scripts/build_keep_off.py`, `config/deterministic-routes.json` is pure data, not
code) that mutates `cands`/`det` after this point before the getaway/actionability gates at lines
517/530. The bypass is closed at its only entry point. I did not find, and did not expect to find
(this repo's own architecture doc for ADR-0011 frames keep-off as a single suppression layer), any
other route-injection path.

### Fail-silent/additive contract preserved?

Yes — no exception paths were touched; the function still returns a plain list, the call site
still prepends to `cands` under the same `if det:` guard. No new I/O, no new exit/return paths
introduced.

### Selftest — genuine regression guard?

Ran directly: `python3 hooks/scripts/enforcer.py --selftest` → `OK`. New case `(6b)`
(`enforcer.py:665-677`) configures a route `"deploy the app" -> "chronic"`, keeps `"chronic"` in
`KEEPOFF`, and asserts `_deterministic_hits(..., surv, keepoff)` never contains `"chronic"`. As
shown above under "The bug, confirmed", reverting only the route-condition's `and skill not in
keepoff` clause (while keeping the new 3-arg signature, so it's an apples-to-apples comparison and
not just a `TypeError` from a stale 2-arg call) reproduces the resurfacing and trips
`bad.append("keep-off skill resurfaced via a deterministic route (ADR-0011 bypass)")` →
selftest **FAILS**. Genuine regression guard, confirmed by direct trace rather than assumed. (Note:
if instead the *entire* diff were reverted including the signature change, the test as now written
would raise an uncaught `TypeError` instead of a clean `bad.append` — still a non-zero exit / test
failure, just a noisier one. Not a defect, just worth knowing the failure *mode* differs depending
on how much of the diff is reverted.)

### Scope

Diff is `+20/-4`: signature + docstring + one added condition + one call-site arg + one new
selftest block. Clean, minimal, targeted at exactly the described bug. Not scope creep.

---

## Cross-cutting observations

- **Architecture**: both fixes stay inside the existing module boundary (pure functions,
  stdlib-only, no new dependencies). The `analyze.py` extraction is a reasonable, justified
  refactor (the block was already being reasoned about as a unit; naming it `_segment_windows`
  makes it independently testable, which the new selftest immediately exploits). Not
  over-engineered — no new abstraction beyond a name and a queue.
- **Security**: neither change touches user-input handling, secrets, or auth; not applicable.
- **Performance**: `deque.popleft()` is O(1); no change in asymptotic behavior of either hot path
  (`enforcer.py`'s per-turn hook remains stdlib-only with the same I/O calls; `analyze.py` remains
  an offline batch script).
- **Readability**: both diffs read cleanly; comments were updated in the same commit to describe
  the *new* behavior and *why* (not just what), matching the project's existing comment density and
  style (e.g. `enforcer.py:220-225`, `scripts/analyze.py:138-142`).

## What's done well

- Both fixes ship a selftest that actually pins the specific bug, not just a generic smoke test —
  and I independently verified both would fail against the pre-fix logic rather than taking that on
  faith.
- The `enforcer.py` fix cites and closes a bypass that a completely separate prior review
  (`review-260705-enforcer-gate.md`) had already found and described almost word-for-word,
  including the same suggested remedy ("`_deterministic_hits` should also check `name not in
  keepoff`") — good traceability between review and fix.
- Both diffs are minimal and stayed inside the boundary of the bug being fixed; no drive-by
  refactors bundled in.

## Suggestions (non-blocking)

- `scripts/analyze.py`: document (one line in the `_segment_windows` docstring) that when more
  offers than turns share a `(sid,q)` key, the **first** offer wins and the **last** offer(s) are
  silently dropped, since that's a behavior change from the old (last-wins) dict-based join, even
  though it only matters for events outside the documented 1:1 hook contract.
- `hooks/scripts/enforcer.py`: none beyond what's already in the diff — the fix is complete and
  narrowly scoped.

## Verification Story

- Tests reviewed: yes — both new selftest additions read and traced against hand-simulated pre-fix
  logic (not just executed as-is).
- Build verified: yes — `python3 scripts/analyze.py --selftest` and `python3
  hooks/scripts/enforcer.py --selftest` both run clean (`OK`) on the current tree.
- Security checked: yes — not applicable to either change (no user-input/auth/secret surface
  touched).
