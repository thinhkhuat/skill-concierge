# Review: in-generation governance gate (enforcer.py / doctrine.py / ADR-0015)

Reviewer: A (advisory, read-only). Scope: `hooks/scripts/enforcer.py`, `hooks/scripts/doctrine.py`,
`hooks/doctrine/skill-first.md`, `hooks/scripts/ledger.py`, `hooks/hooks.json`,
`docs/adr/0015-authorized-skip-tier-and-library-doctrine.md`. All line numbers cite the files as
read on 2026-07-05. `enforcer.py --selftest` was run (read-only, no source edits) for empirical
verification; output quoted below.

---

## 1. What it actually does

**Wiring** (`hooks/hooks.json:4-49`): `SessionStart` runs `doctrine.py` then `auto_reindex.py`;
`UserPromptSubmit` runs `enforcer.py` then `ledger.py`; `PostToolUse` (matcher
`"Skill|mcp__.*skill-search__search_skills"`) runs `ledger.py` again. Confirms the doc comment
at `enforcer.py:12-16`: "mirrors the sibling ledger hook."

**SessionStart doctrine** (`doctrine.py:49-63`): reads `hooks/doctrine/skill-first.md` at runtime
(`doctrine.py:31`, resolved as `Path(__file__).resolve().parent.parent / "doctrine" /
"skill-first.md"` — verified this resolves correctly: script lives at `hooks/scripts/doctrine.py`,
so `parent.parent` = `hooks/`, landing on the real file I read), extracts only the text between
`<!-- DOCTRINE-START -->` / `<!-- DOCTRINE-END -->` (`doctrine.py:35-46`), and emits it as
`hookSpecificOutput.additionalContext`. If the markers are missing it falls back to the **whole
file** rather than silence (`doctrine.py:44-46`: "a malformed edit degrades to over-injecting,
never to silence") — deliberate fail-open bias.

**Per-turn gate** (`enforcer.py:main`, `455-541`):
1. Cheap pre-gate, no I/O (`461-469`): empty prompt or prompt starting with `/` → return 0. Prompt
   of `≤ MAX_SHORT_WORDS` (3) words → return 0. **Neither of these paths ever calls `_inject` or
   `_append_offer`** — genuinely silent, no `SKILL-CHECK:` marker, no ledger entry.
2. Explicit skill-refusal (`_REFUSAL_RE`, `473-476`): negation + invocation-meta verb → inject
   plain `MANDATE`, log `_append_offer(..., "negation", [], "skill_refusal", prompt)`.
3. Embed (`478-488`) and retrieve (`490-496`): on timeout/down for either, inject `MANDATE`, log a
   `"fallback"` offer event (`embed_timeout` / `embed_down` / `qdrant_down`), return 0.
4. Keep-off hard-drop (`498-500`, ADR-0011): strip chronic never-take names from `cands` before any
   gate.
5. Deterministic routes (`502-507`, default-inert unless `ENFORCER_DETERMINISTIC=1`): prepend any
   exact-substring hit not already in `cands` at score `1.0`.
6. **Getaway** (`509-522`): `top = cands[0][2]`; `floor = _floor_for(cands[0][0])` (per-skill tau if
   armed+`ok`, else global `GETAWAY_FLOOR=0.45`). If `not det and top < floor`: log a `"getaway"`
   offer, then `_authorized_skip_inject("getaway", top=top, floor=floor)`, return 0.
7. **Actionability gate** (`524-531`): if `not det and not _is_imperative(prompt) and
   _intent_conversational(vector)`: log `"intent_skip"` offer, `_authorized_skip_inject("intent_skip")`,
   return 0.
8. Otherwise: filter to `ITEM_FLOOR`-clearing candidates (fallback to top-1), collapse via
   `_apply_dominance` (default-inert), inject `_ranked_mandate(shown)`, log an `"offer"` event.

**AUTHORIZED-SKIP tier** (`71-81`, `309-335`): `AUTHORIZED_SKIP = os.environ.get(
"ENFORCER_AUTHORIZED_SKIP", "1") != "0"` — **default ON**, matching ADR-0015's stated default
exactly ("default ON; `=0` restores prior silence", ADR §Decision). `AUTHORIZED_SKIP_MARKER =
"SKILL-CHECK:"` (`enforcer.py:81`) is the literal the audit script joins on
(`skills/skill-usage-audit/scripts/audit_skill_usage.py:55`: `AUTHORIZED_SKIP_MARKER =
"SKILL-CHECK:"` — confirmed byte-identical, cross-file contract intact). `_authorized_skip_inject`
(`325-335`) wraps the whole body in `try/except: pass`, so a bad format kwarg or stdout error can
never propagate.

---

## 2. Correctness / logic findings

### 🟡 P5 keep-off hard-drop can be silently un-dropped by a deterministic route (verified by execution)

`_drop_keepoff` runs first (`enforcer.py:500`) and strips a chronic never-take skill from `cands`.
`_deterministic_hits` then runs *against the already-filtered `cands`* (`enforcer.py:505`,
`_deterministic_hits(prompt, cands)`), and its own dedup check is `have = {n for (n,_d,_s) in
cands}` (`enforcer.py:227`) — a name that was just keep-off-dropped is, by construction, **not**
in `have` anymore, so a matching route re-adds it at score `1.0`, which then (per `enforcer.py:194
-195`) "bypasses both the getaway and the actionability gate."

I reproduced this directly against the live functions (not just by reading):

```
post-keepoff survivors: [('other-skill', 'other desc', 0.2)] dropped: ['chronic-skill']
deterministic hits (should be empty if keepoff is respected): [('chronic-skill', 'deterministic route', 1.0)]
```

So a `chronic-skill` explicitly hard-dropped by ADR-0011's keep-off list resurfaces at maximum
confidence, gate-bypassing, the moment an operator adds a deterministic route whose substring
matches the same intent. Neither `_drop_keepoff`'s comment (`enforcer.py:151-152`, "order-preserving
so P6's later gap-collapse runs over the POST-suppression set") nor `_deterministic_hits`'s comment
(`enforcer.py:220-223`) mentions this interaction, and the self-test (`enforcer.py:610-661`)
exercises keep-off and deterministic routes only in isolation, never together — so this is an
untested seam, not a deliberately accepted trade-off.

**Blast radius is narrow today**: both features are opt-in (`ENFORCER_DETERMINISTIC` is unset by
default, `_ROUTES` defaults to `[]`, `enforcer.py:206-207`; keep-off is populated only via
`config/keep-off.json`, fail-open empty otherwise). It only bites an operator who curates *both* a
keep-off entry and a deterministic route for the same skill — plausible, since deterministic routes
exist precisely to force-surface a skill the operator already has strong opinions about, which is
the same population keep-off entries are drawn from ("chronic never-take"). Worth a one-line
guard (`_deterministic_hits` should also check `name not in keepoff`, or `_drop_keepoff` should run
again after route injection) or an explicit comment disclaiming the interaction as accepted.

### 💭 `MAX_SHORT_WORDS` pre-gate is a *third* silent-return path outside ADR-0015's stated scope

ADR-0015's own docstring (`enforcer.py:72-73`) frames the fix as covering "the two silent verdict
paths below (getaway... intent_skip...)". The `≤3`-word pre-gate (`enforcer.py:468-469`) is a
**third** path that returns 0 with zero `additionalContext` and zero ledger entry — no
`SKILL-CHECK:` marker at all, unlike getaway/intent_skip. This looks intentional (comment at
`enforcer.py:464-465`: "Cheap pre-gate (no I/O)... These never embed", and `ITEM 3` design note in
`_selftest`, `enforcer.py:585-587`, explicitly acknowledges production drops these before
`_is_imperative` even runs) rather than an oversight, since sub-4-word prompts are the clearest
"genuinely trivial" case the library doctrine (`skill-first.md:83-86`) describes. Flagging only
because a reader of ADR-0015 alone (which enumerates exactly two legs) could reasonably assume
*every* enforcer no-op now carries the marker — it doesn't. Not a defect, just a scope note worth
one sentence in the ADR or the docstring.

No other off-by-one, wrong-branch, or flag-default mismatch found. Specifically checked and
**confirmed correct**:
- `top` is computed *after* deterministic-hit prepending (`enforcer.py:505-509`), so a det hit's
  score of `1.0` always clears any floor — the `not det` guards at `515`/`528` are technically
  redundant (det score can't be `< floor`) but not wrong.
- `GETAWAY_SKIP_MSG` / `INTENT_SKIP_MSG` text matches the ADR's stated intent verbatim: burden of
  proof stays on SKIP, `find-skills` escalation + `get_skill()` nudge present in the getaway
  message, conversational rationale present in intent_skip (`enforcer.py:312-322`, ADR §Decision
  bullet 1).
- `_selftest`'s authorized-skip assertions (`enforcer.py:663-697`) pin exactly this content and
  pass — see empirical run below.

---

## 3. Fail-silence guarantee

Verified by reading every exit path, not assumed from the docstrings:

- **`enforcer.py`**: `main()`'s entire body (`456-538`) sits inside one `try/except Exception:
  return 0` (`539-540`) — any unhandled exception anywhere in the per-turn logic (keepoff, routes,
  floors, actionability gate, rendering) degrades to a silent no-op turn, never a block. The three
  known-risky I/O calls (`_embed`, `_retrieve`, `_intent_conversational`) each have their *own*
  nested `try/except` that falls back to `MANDATE`-only or `False` before the outer catch would
  even need to fire (`480-488`, `491-496`, `445-452`). `_authorized_skip_inject` additionally
  self-wraps (`330-335`) so a bad `.format()` kwarg can't escape. `_load_keepoff` (`140-144`),
  `_load_per_skill_tau` (`172-180`), `_load_routes` (`205-214`) each catch `Exception` and return an
  empty/default container — config-file corruption degrades to "feature inert," never a crash.
- **`ledger.py`**: same shape — `main()`'s body wrapped `try/except Exception: return 0` (`46-89`),
  and the log-append helper `_append` independently wraps its own write in `try/except: pass`
  (`36-42`).
- **`doctrine.py`**: `main()` wrapped `try/except Exception: return 0` (`50-63`); the one failure
  mode that isn't silence-by-omission (missing/garbled doctrine markers) is explicitly designed to
  **fail open to over-injection**, not under-injection (`44-46`), which the docstring names as a
  deliberate choice, not an oversight.
- No exit path in any of the three governance hooks returns a non-zero code or emits
  `"decision":"block"` — grepped for both literals across all three files, no hits. This matches
  the "NEVER BLOCKS" contract stated at `enforcer.py:15` and `AGENTS.md:72` ("Hooks are fail-silent
  and additive-only — a telemetry failure must never block a turn").

**Empirical spot-check** — ran `python3 hooks/scripts/enforcer.py --selftest` (read-only, exercises
the pinned contracts including the two AUTHORIZED-SKIP legs' inject-on/silent-off behavior):

```
enforcer --selftest OK: refusal guard (5 fire / 6 silent) + ranked-mandate %-share
+ actionability imperative-veto (17 fire / 12 off) + keepoff-drop + gap-collapse
+ per-skill-tau/deterministic-routes (default-inert) + authorized-skip tier
(inject-on/silent-off)
```
Exit code 0. This confirms the selftest's own claims are currently true on this checkout; it does
**not** independently confirm production behavior beyond what the selftest asserts (see gaps below).

---

## 4. Confidence + gaps (could not verify)

- **UNVERIFIED**: whether Claude Code's harness actually surfaces `hookSpecificOutput.
  additionalContext` text (including the `SKILL-CHECK:` marker) into the transcript in a form
  `audit_skill_usage.py`'s line-grep can see. I read the enforcer/audit source only; I did not trace
  the harness-side hook→transcript plumbing (out of this repo).
- **UNVERIFIED**: live Qdrant/embed-shim behavior (score distributions, actual `prompt_intent`
  collection health) — I read the code paths and the calibration commentary in comments only, not
  live telemetry or the ledger contents.
- Did not review `auto_reindex.py` in depth against ADR-0015 (out of assigned scope; skimmed only to
  confirm its SessionStart wiring doesn't interfere with the doctrine injection — it doesn't, it
  emits no context at all per `auto_reindex.py:18`).
- Did not attempt to independently re-derive the ADR-0009 score↔adoption numbers the ADR cites as
  contested ("taken offers median 0.414 < dodged 0.457") — took the ADR's own text as given per the
  grounding contract (report on what's in the file, not a re-analysis of prior ledger data).

## Ranked summary

1. 🟡 Keep-off (ADR-0011) can be bypassed by a co-configured deterministic route for the same skill —
   verified by direct execution, not just reading. Narrow blast radius (both features opt-in) but
   undocumented and untested in combination.
2. 💭 The `≤3`-word pre-gate is a third silent-return path not covered by ADR-0015's "two legs"
   framing — apparently intentional, worth a one-line doc clarification.
3. Core AUTHORIZED-SKIP mechanism (flag default, marker literal, both message bodies, cross-file
   audit contract) matches ADR-0015's stated design exactly; no defects found there.
4. Fail-silence contract holds across all three governance hooks — every exit path traced, no block
   path exists, empirically confirmed via `--selftest`.
