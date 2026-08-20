# The always-on allowlist, rebuilt — and the priority trap underneath it

2026-08-07 · skill-concierge · follows `journal-2026-08-07-engine-build-identity-arc-v0206-to-v0208.md`

The session started as an audit ("which skills are always-on, and can it be better?") and ended
somewhere more interesting: the selection criterion we spent four rounds refining turns out to
collide, structurally, with the mechanism Claude Code uses to decide what actually renders.

---

## 1. What "always-on" is, and the first surprise

The allowlist is the set of skills kept **fully described** in the model-facing listing every
turn. Everything else is name-only — the model sees a bare name and retrieves the description on
demand. It is the single highest-leverage context knob in the harness.

The first measurement broke the premise. Of the 23 curated always-on entries, **eight were
rendering as bare names anyway** — `come-clean`, `verify-as-claimed`, `vn-comm`, `vn-editor`,
`vn-author`, `vn-canu-reporting`, `vn-bctt-report`, `vn-deep-dive-report`. Every one of them sat
at the 512-char `skillListingMaxDescChars` cap. Every entry at ≤368 chars rendered; every entry at
≥490 was dropped.

Silently. `scripts/apply-overrides.py` reported "in sync, no drift" throughout, because it
compares its own map to itself, not to what the model actually receives.

## 2. Four selection criteria, each one wrong until the user corrected it

**Round 1 — rank by usage.** Sort the transcript store by invocation count, take the top 30. This
produced a list dominated by `session-handoff` (100 invocations), `brief-me`, `whereami`,
`what-next`.

**Round 2 — the user's reframe: "this list helps YOU, not me."** The allowlist serves the agent.
A slash command works fine name-only — the user types it by name. The description exists so the
*model* can find the skill unprompted. That inverted the ranking: user-channel usage stopped
counting, and skills with **zero** invocations became candidates, because a governance skill is
one the agent would never think to search for.

**Round 3 — a sharper filter fell out of the data.** `session-handoff` had been model-invoked
**60 times while name-only**. Retrieval finds it perfectly; a slot would be wasted. That
generalised: *any skill already firing often without a slot does not need one.* It also demoted
several of Round 2's picks, including some proposed an hour earlier.

**Round 4 — the user's second reframe: capability vs encoded procedure.** Most `vn-*` skills are
workflows written in skill format for reuse — `vn-canu-reporting`, `vn-bctt-report`,
`vn-deep-dive-report`. The user starts them deliberately and names the domain, so retrieval
handles them. Only `vn-comm`, `vn-editor`, `vn-author` are capabilities: they change *how* the
agent writes while it is already writing. That distinction cut the list again.

The final rule is two filters: **capability, not procedure** — and **relevant but silent**.

## 3. Three plugin-budget errors, in ascending order of embarrassment

**(a) Counting the cache instead of the config.** The plugin-cost scan globbed
`~/.claude/plugins/cache/`, which retains files for plugins that are *not loaded*. Published
figure: 23,502 chars. Actual live cost: 15,383. Over-reported by 8,119.

The rule that came out of it: **ground truth is `settings.json:enabledPlugins` cross-checked
against the live skill listing — never the cache directory.**

**(b) Proposing a lever the operator had already pulled.** `skill-creator` was recommended for
disabling; it had been disabled long before. Its cache directory vanished between two scans —
exactly −1,012 chars — which is how it got caught.

**(c) The model failed its first out-of-sample test.** The operator then disabled `fable`,
`effort-gate`, and `last30days` — **2,745 chars freed**, verified three ways. The budget model
predicted the cheapest bare entry (472 chars) would start rendering.

**None of the eight promoted. Not one.**

## 4. The real mechanism, and the trap

The driver is not total budget. It is **priority order**, and its input is
`~/.claude.json` → `skillUsage`:

```json
"vn-comm": { "lastUsedAt": 1782897000000, "usageCount": 1 }
```

Scored as `usageCount × max(0.5^(days/7), 0.1)` and, per the official docs, *"when the listing
overflows, Claude Code drops descriptions starting with the skills you invoke least."*

Two things fall out:

**Cost and score interact.** `verify-as-claimed` scores 16.87 and still loses its description,
while `ak-cook` at 10.81 keeps one — because the fitter walks in score order and *skips* an entry
that doesn't fit, while cheaper lower-ranked entries still land. A high-priority expensive entry
loses to a low-priority cheap one.

**And then the trap.** Scoring all 29 proposed entries:

- **15 (51%) are absent from `skillUsage` entirely** — priority zero
- 6 more sit at the 0.10–0.30 decay floor
- **21 of 29 (72%) are at or near the bottom of the drop order**

This is not bad luck. Filter B *deliberately selects skills that are relevant but silent*, on the
reasoning that anything already firing doesn't need a slot. Claude Code's priority function ranks
by exactly the opposite signal — how often you invoked it lately. **The criterion selects
precisely the entries the fitter drops first.**

There is no configuration escape. `skillOverrides: "on"` does not bypass the budget fitter —
proven, since all eight bare entries were explicitly `"on"`. And it is a bootstrap problem: a
skill needs recent use to earn priority, and needs a visible description to be found and used.

So trimming stopped being an optimisation and became **the mechanism by which a zero-priority
entry seats at all.**

## 5. Three skills rewritten, and one that taught the method

**`code-change-verification`** was hardcoded to a repository that isn't ours — the description
named "the OpenAI Agents Python repository", the Quick start hardcoded a Codex-layout
`.agents/skills/` path, and both runner scripts assumed `make format/lint/mypy/tests` plus `uv`.
Always-on would have made it misfire on every code change here.

Rewritten repository-driven: commands resolve from `CCV_*` env override → Makefile target →
`package.json` script → language-manifest default. Tested against five synthetic repos covering
every resolution branch, plus fail-fast, flag handling, and a non-git directory. The `.sh`/`.ps1`
pair became thin wrappers over one stdlib-Python runner, so there is a single implementation to
keep correct rather than two that drift.

One design point earned its keep: **a phase with no resolvable command reports SKIPPED, never
PASSED.** "No linter configured" and "the linter passed" are different facts, and the old script
had no way to say the first one. A usage-error exit code collision (both `2`) was found mid-test
and moved to `64`.

**`research-grounding`** dropped 534 → 375 by deleting one `Enforces:` clause that duplicated the
body verbatim — the key-loading step, the search rotation, the fetch priority list, the
cite-and-split rule. All four verified still present in the body before cutting.

**`directional-prompting`** is the one that taught the method. It is a skill *about how to write
descriptions*, so trimming it carelessly would be self-refuting. The first draft looked fine and
wasn't: it stated the same branch twice (a duplication its sibling skill `writing-great-skills`
names explicitly), folded "skill descriptions" — the highest-value trigger on this machine — into
a generic "skill instruction", and dropped the negation-rewrite branch that has two whole body
sections behind it.

The fix was to trim *against the skill's own `## Application checklist`*, which is its
authoritative statement of when it fires, then audit the result against its own five rules. Seven
of its eight branches are named in 364 chars; the eighth (IDE rulesets) is a deliberate omission,
recorded as such. It also gained a branch the original lacked — sub-agent prompts — which the
checklist has and the description never did.

**The generalisable lesson: when trimming a skill's description, the body is the specification.
Cut only what the body still carries, and check the cut against the skill's own rules if it has
any.**

## 6. Where it landed

The set is applied: **30 on / 380 name-only** across 410 discovered skills. The 29 curated entries
total 6,994 chars, down from a 7,582 first draft, with `research-grounding` and
`directional-prompting` trimmed and `code-change-verification` rewritten.

**The measurement the whole exercise exists to run has not been taken.** It needs
`/reload-plugins`, then a count of how many of the 29 render a description. Given §4.0.1, the
honest expectation is that many will not.

Which is the right place to stop. Three rounds of arithmetic predicted things that didn't happen;
the fourth shouldn't get the benefit of the doubt. Count first.

---

## Postscript — a retraction that was itself wrong

Early in the session a finding was recorded: `keep-on.py` emits a false-positive router warning.
Later it was **retracted** as "never a real defect", on the basis that `scripts/keep-on.py:98`
checks both the bare and namespaced router names.

Applying the new allowlist reproduced the warning live, with `skill-concierge:skill-search`
provably present in `keep-on.json`.

The retraction had inspected the wrong call site. `keep-on.py:98` is the *remove-path* guard; the
warning actually comes from **`scripts/apply-overrides.py:181`** — `if "skill-search" not in
keep_on:` — which tests only the bare name and is relayed through `keep-on.py:63`. The original
finding was right.

Reading one call site and generalising to "no defect" is the mistake worth remembering. A
retraction deserves the same standard of evidence as the claim it retracts — arguably more, since
it closes an issue rather than opening one.
