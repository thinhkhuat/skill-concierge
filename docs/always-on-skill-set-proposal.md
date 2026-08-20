# Always-On Skill Set — 29 curated entries

**Status: APPLIED 2026-08-07 02:57.** `scripts/keep-on.py` reports **30 on / 380 name-only**
across 410 discovered skills — the 29 entries in §2 plus `skill-concierge:skill-search`
(plugin-scope, free, present only to satisfy the router guard). Full applied state in §8.

Drafted and applied 2026-08-07. Supersedes §16 of
`.handoff/handoff-2026-08-06-2122-always-on-budget-audit-and-yaml-scalar-fix.md`.

The always-on allowlist is the set of skills kept **fully described in every turn's model-facing
listing**. Everything else is name-only: the model sees the name and retrieves the description on
demand via `search_skills`. This document proposes what that set should contain and proves the
budget arithmetic behind it.

---

## 1. The selection rule

The allowlist serves **the agent, not the user**. A slash command works fine name-only — the user
types it by name. The description exists so the *model* can find the skill unprompted.

Two filters, both required:

**Filter A — capability, not encoded procedure.**
- A **capability** changes *how* the agent behaves while already doing something else. It fires
  mid-task, without being named. `vn-comm` fires on any Vietnamese the agent writes.
  `come-clean` fires when the agent has dodged.
- An **encoded procedure** is a multi-step pipeline the user starts deliberately — phases,
  artifacts, gates. `vn-canu-reporting`, `vn-bctt-report`, `ak-cook`, `plugin-scaffold`.
  These are workflows written in skill format for reuse and reproducibility. Name-only is correct
  for them: the user's request names the domain, and retrieval does the rest.

**Filter B — relevant but silent.**
A slot is *wasted* on a skill that already fires often while name-only. Measured over 70 days
(2,237 transcripts):

| Skill | model invocations **while name-only** | Verdict |
|---|---:|---|
| session-handoff | **60** | Retrieval finds it perfectly. No slot needed. |
| plugin-scaffold | 15 | Same |
| brief-me | 13 | Same |
| what-next | 11 | Same |
| transcript-miner | 8 | Same |
| zread-cli / opus-validate / study-extract-integrate | 6 each | Same |
| code-review | 4 | Same |

Slots go to skills that are **relevant to the logged work profile but near-silent** (≤2 model
invocations) — the ones retrieval is not surfacing because nothing prompts the agent to look.

Corollary, and it is counter-intuitive: for a governance or self-correction skill, **zero
invocations is evidence *for* the slot, not against it.** The agent never searches
"how do I catch myself asserting something I did not check."

**Evidence base.** Work profile and friction log from the Claude Code Insights report
`~/.claude/usage-data/report-2026-08-07-015617.html` (1,123 messages, 64 sessions,
2026-07-14 → 2026-08-06). Invocation counts from `~/.claude/audits/skill-usage-stats/latest.json`
(70-day window, both channels).

---

## 2. The proposed set (29 entries)

`cost` = `len(name) + min(len(description), 512) + 4` — the listing's own shape.
✳ = staged trim size from the handoff §5. ⚠ = still needs a trim.

| # | skill | cost | mdl | usr | why it earns a slot |
|---:|---|---:|---:|---:|---|
| **Proven slots — currently on, and firing because of it** |
| 1 | verify-as-claimed | 487✳ | 23 | 4 | Top logged win *and* top logged friction |
| 2 | come-clean | 406✳ | 20 | 0 | Fires when the agent has dodged — unsearchable by definition |
| 3 | vn-comm | 448✳ | 18 | 0 | Fires on any Vietnamese written, including unprompted narration |
| 4 | vn-editor | 387✳ | 8 | 1 | Editing existing Vietnamese |
| 5 | vn-author | 396✳ | 4 | 1 | Routing partner to vn-editor — without both, wrong pick |
| 6 | verification-before-completion | 194 | 1 | 0 | Fires on the word "done" |
| **Verification / anti-fabrication — the #1 friction category** |
| 7 | research-grounding | 375✳ | 0 | 0 | Live-source grounding — counters the fabricated TB 401/TB-VPCP class |
| 8 | behavior-validator | 136 | 0 | 0 | Source-blind validation against a written contract |
| 9 | vibe-code-auditor | 119 | 0 | 0 | Audits AI-produced code — 32 buggy-code friction events |
| 10 | root-cause-tracing | 193 | 0 | 0 | Traces backward instead of patching the symptom |
| 11 | diagnosing-bugs | 175 | 0 | 0 | Diagnosis loop for hard bugs and regressions |
| 12 | defense-in-depth | 188 | 0 | 0 | Validate at every layer data passes through |
| 13 | code-change-verification | 453 | 1 | 0 | Runs the repo's own format/lint/typecheck/test gates; rewritten harness-agnostic 2026-08-07 (§6.1) |
| **Harness engineering — the actual craft** |
| 14 | harness-engineering | 302 | 0 | 0 | *"turn agent failures into repo-level guardrails"* — literally skill-concierge, effort-gate, step-ledger |
| 15 | writing-for-agents | 125 | 2 | 0 | SKILL.md, AGENTS.md, CLAUDE.md |
| 16 | directional-prompting | 389✳ | 0 | 0 | Writing skill descriptions, agent directives, slash commands |
| 17 | tool-design | 256 | 0 | 0 | Tools agents can actually use |
| 18 | rules-distill | 135 | 1 | 0 | Scan skills, distill cross-cutting rules |
| 19 | which-skills | 194 | 3 | 2 | Routes the agent before it improvises |
| 20 | using-skills | 124 | 0 | 0 | Meta-routing |
| **Code discipline** |
| 21 | tdd | 156 | 0 | 0 | Test-first loops — the stated next-horizon workflow |
| 22 | conventional-commit | 285 | 1 | 0 | 51 commits in the window |
| 23 | python-tooling | 112 | 0 | 0 | Python 307 lines; venv work in nearly every session |
| 24 | architecture-decision-records | 211 | 2 | 0 | `docs/adr/` is live in this repo |
| **Writing — Markdown 791 lines vs Python 307** |
| 25 | writing-clearly-and-concisely | 237 | 1 | 0 | Docs, commit messages, error text |
| 26 | writing-plans | 101 | 3 | 0 | Before touching code |
| **Context and session hygiene — 405 session-hours** |
| 27 | context-map | 83 | 0 | 1 | Map relevant files *before* editing |
| 28 | strategic-compact | 155 | 0 | 4 | Compact at logical intervals, not arbitrary ones |
| 29 | rg_history | 172 | 2 | 11 | Search prior sessions before trusting a prior claim |
| | **TOTAL** | **6,994** | | | ~1,748 tok/turn |

All 29 verified present on disk, all personal scope, no duplicates. **29, not 30** — two entries were
cut on review (§3) and one added; the set is sized by the rule, not padded to a round number.

---

## 3. Demoted from the current 23

| Demoted | mdl / usr | Reason |
|---|---:|---|
| ak-debug, ak-fix, ak-problem-solving, ak-project-management, ak-research | 0 / 0 each | Zero invocations on both channels over 70 days |
| ak-brainstorm, ak-code-review, ak-scout | 1 / 0 each | Below the bar |
| ak-team | 0 / 1 | User channel only |
| ak-plan, ak-cook, ak-ask, ak-git | 2–7 | Encoded procedures the user starts, not behaviours the agent drifts on |
| vn-canu-reporting | 1 / 16 | Encoded workflow; the request names the domain |
| vn-bctt-report, vn-deep-dive-report | 0 / 0 each | Encoded workflows |
| skill-concierge:skill-search | 3 / 0 | Plugin scope — bypasses `skillOverrides` entirely, so the entry is decorative |

**Cut on review after the first draft of this document (2026-08-07):**

| Cut | cost | mdl / usr | Reason |
|---|---:|---:|---|
| skill-check | 146 | 3 / 2 | Fails **Filter B** — already fires 3× model-invoked while name-only, so the slot is provably unnecessary. Also a procedure by its own text: *"Use when user says 'check skill', 'skillcheck', or 'validate SKILL.md'"* — explicit user-trigger phrases. |
| check-work | 281 | 0 / 0 | Real gap coverage (subagent reviewing **code** diffs, which `verify-as-claimed` excludes by design), but `opus-validate` does the same job and already fires at **mdl 6 while name-only**. Its own triggers are slash-shaped (`/check-work`, `/check`, `/verify`). Redundant against a demoted skill that works without a slot. |

**Considered and blocked, not rejected: `writing-great-skills`.** It carries
`disable-model-invocation: true`, which per the official spec *"prevent[s] Claude from
automatically loading this skill"* — it never enters the model-facing listing at all, and
`skillOverrides` cannot override that. Verified empirically: the name is absent from the live
skill listing entirely, not merely name-only. Its own body documents the trade-off it is making
(*"a user-invoked skill strips the description from the agent's reach… zero context load, but it
spends cognitive load: you are the index"*), so the setting reads as deliberate. Making it
always-on requires two edits to the skill itself — drop `disable-model-invocation`, and rewrite
the description from human-facing to trigger-bearing (est. 132 → ~280 chars). Not done.

**Keep `skill-concierge:skill-search` in the file anyway.** It costs nothing against the curated
budget (plugin skills render regardless) and it silences `scripts/keep-on.py:98`'s router guard.

**Caveat on the two `vn-*` zeros.** `vn-bctt-report` and `vn-deep-dive-report` are high-stakes,
low-frequency government-report skills. Zero in 70 days means "not needed recently", not "not
needed". Their sibling `vn-canu-reporting` ran 17 times, so the family is live. They are demoted
here because they are **encoded workflows**, not because of the zero — the classification is the
reason, the number is only corroboration.

---

## 4. Budget arithmetic

### 4.0 The budget model failed its first out-of-sample test — read this before §4.1

On 2026-08-07 the operator disabled three plugins: `fable` (2,030), `effort-gate` (444),
`last30days` (271) — **2,745 chars freed**, verified: all three vanished from `enabledPlugins`,
from the live skill listing, and from the plugin cache.

**Prediction from §4.1's model:** the cheapest of the eight bare entries (`vn-bctt-report`, 472)
should now render.
**Observed:** *none* of the eight promoted. All still bare.

The total-budget model is therefore incomplete. The real driver is **priority order**, whose input
is `~/.claude.json` → `skillUsage`, a counter Claude Code maintains itself:

```json
"vn-comm": { "lastUsedAt": 1782897000000, "usageCount": 1 }
```

Priority decays with time since last use — `usageCount × max(0.5^(days/7), 0.1)` — and per
`skills.md:943`, *"when the listing overflows, Claude Code drops descriptions starting with the
skills you invoke least."* Measured for the current always-on set:

| skill | CC score | count | days since use | renders? |
|---|---:|---:|---:|---|
| session-handoff | **45.67** | 46 | 0.1 | n/a — not always-on |
| verify-as-claimed | 16.88 | 18 | 0.6 | **no** — costs 533 |
| ak-cook | 10.81 | 11 | 0.2 | yes — costs 212 |
| vn-canu-reporting | 5.70 | 6 | 0.5 | no |
| come-clean | 4.10 | 7 | 5.4 | no |
| ak-git | 2.96 | 3 | 0.1 | yes |
| vn-author | 1.76 | 3 | 5.4 | no |
| ak-ask | 1.61 | 2 | 2.2 | yes |
| vn-editor | 0.95 | 1 | 0.5 | no |
| **vn-comm** | **0.10** | 1 | **25.1** | no — at the decay floor |
| vn-bctt-report · vn-deep-dive-report · verification-before-completion | **absent from `skillUsage`** | — | — | mixed |

**Three consequences that change the recommendation:**

1. **`skillUsage` counts are not the transcript counts used in §2.** `vn-comm` shows 18 model
   invocations over 70 days in the transcript store but `usageCount: 1` here, last used 25 days
   ago — decayed to the 0.1 floor. The two channels measure different things. §2's ranking remains
   the right basis for *which skills deserve a slot*; `skillUsage` decides *which ones get one*.
2. **Cost and score interact.** `verify-as-claimed` outranks `ak-cook` (16.88 vs 10.81) and still
   loses, because the fitter walks in score order and **skips** an entry that doesn't fit while
   cheaper lower-ranked ones still land. A low-score skill needs a **cheap** description; an
   expensive description needs a **high** score. `vn-comm` at 0.10 will not seat at any realistic
   size until it is used again.
3. **Disabling further plugins is not the lever.** 2,745 freed chars bought zero promotions.
   Chasing the remaining blocks (`agent-skills` 7,234, `memsearch` 1,252) would cost real
   functionality on an unproven theory. **Stop predicting. Trim descriptions, apply the set,
   reload, count.**

#### 4.0.1 The structural tension in this whole proposal — read before judging the result

Scoring all 29 proposed entries against `skillUsage` (2026-08-07, after the set was applied):

| band | entries | examples |
|---|---:|---|
| **absent — priority 0** | **15 (51%)** | verification-before-completion, research-grounding, behavior-validator, vibe-code-auditor, root-cause-tracing, diagnosing-bugs, defense-in-depth, harness-engineering, directional-prompting, tool-design, which-skills, using-skills, tdd, python-tooling, strategic-compact |
| 0.10 – 0.30 (decay floor) | 6 | vn-comm 0.10 · rules-distill 0.10 · architecture-decision-records 0.10 · writing-clearly-and-concisely 0.26 · context-map 0.29 · conventional-commit 0.30 |
| 0.9 – 2.0 | 4 | code-change-verification 0.98 · vn-editor 0.95 · vn-author 1.76 · writing-for-agents 1.97 |
| above 4 | 4 | verify-as-claimed 16.87 · rg_history 8.78 · come-clean 4.10 |

**21 of 29 (72%) sit at or near the bottom of the drop order.**

This is not an accident of selection — it is the selection criterion colliding with the mechanism.
§1 Filter B deliberately picks skills that are **relevant but silent**, on the reasoning that a
skill already firing while name-only does not need a slot. Claude Code's priority function ranks
by exactly the opposite signal: *how often you have invoked it lately*. **The criterion selects
precisely the entries the fitter drops first.**

There is no way around it by configuration alone:

- **`skillOverrides: "on"` does not bypass the budget fitter.** Proven: all eight bare entries were
  explicitly `"on"` and were dropped anyway.
- **It is a bootstrap problem.** A skill needs recent use to earn priority; it needs a visible
  description to be found and used. Zero-priority entries cannot climb out on their own.

**Therefore the only reliable lever for a zero-priority entry is a *cheap* description.** Trimming
stops being an optimisation and becomes the mechanism by which these entries seat at all. That is
the justification for the trim work in §2 — and the argument for extending it to every entry in
the set still above ~350 chars, not just the two that were over 500.

### 4.1 The measured ceiling

Cost bands, measured against which of the 23 current always-on entries actually rendered a
description in a live session:

| Cost band | Entries | Rendered? |
|---|---|---|
| 194 – 368 chars | 15 | **all render** |
| 490 – 535 chars | 8 | **all dropped** |

- Seated today: **3,776 chars across 15 entries.**
- Rejected today: **4,190 chars across 8 entries** — and those 8 are exactly the ones sitting at
  the 512-char `skillListingMaxDescChars` cap.
- The true ceiling lies in **[3,776, 4,265]**. The exact constant cannot be derived from outside
  the binary; the observed listing size is inconsistent with a naive `contextWindow × 4 × 0.03`
  reading at 200k context. **Measure it, do not compute it.**

Live knobs (`~/.claude/settings.json`): `skillListingBudgetFraction: 0.03`,
`skillListingMaxDescChars: 512`, `skillOverrides` = 418 entries (23 on / 395 name-only).

### 4.2 Closing the gap

**The arithmetic below is retained for reference only. §4.0 shows it does not predict behaviour —
freeing 2,745 chars promoted nothing. Do not act on these numbers alone.**

| Step | Effect | Running position |
|---|---|---|
| List as proposed (29 entries) | | **7,142** |
| `research-grounding` trimmed 534 → **375**, installed 2026-08-07 | already in the total | **7,142** |
| Trim `directional-prompting` (537) to ≤380 — still pending | −157 | **6,985** |
| Plugins disabled 2026-08-07 (`fable`, `effort-gate`, `last30days`) | +2,745 headroom | **[6,521 – 7,010]** nominal |

Nominally 6,985 now lands inside the range — 25 chars under the optimistic ceiling, 464 over the
conservative floor. **But the same model predicted the three disables would promote at least one
entry, and none moved.** Treat the range as a rough sanity check, not a decision input.

**The decision procedure is empirical, in this order:**

1. Trim `directional-prompting` (the last entry over 500).
2. Apply the set with `scripts/keep-on.py`, `/reload-plugins`, and **count how many of the 29
   render a description.** That count is the only ground truth.
3. For any entry still bare, check its `skillUsage` score (§4.0). A low score means it needs a
   *cheaper* description, not more global budget — that is a per-entry fix, not a config change.
4. Only if entries with **high** scores are still bare does `skillListingBudgetFraction` become
   the right lever.

> **Correction, 2026-08-07 — an earlier draft of this section was wrong.** It claimed a
> **+3,042** headroom gain from disabling `fable` *and* `skill-creator`. Two errors: (a) the
> plugin-cost scan globbed `~/.claude/plugins/cache/`, which retains files for plugins that are
> **not loaded**, so it counted disabled plugins as if they cost context; and (b) `skill-creator`
> was already disabled by the operator long before this analysis, so its 1,012 chars were never
> a lever — they were already reflected in the measured headroom. Corrected figures in §4.3.
> **Ground truth for "is this plugin costing me context" is `settings.json:enabledPlugins`
> cross-checked against the live skill listing — never the cache directory.**

If it comes up short, cut in this order — cheapest loss of coverage first:

1. **Trim a mid-range entry** rather than dropping one: `harness-engineering` (302),
   `conventional-commit` (285), `tool-design` (256).
2. **Drop `using-skills` (124) or `context-map` (83)** — both are thin routing helpers whose
   function partly duplicates `which-skills`.
3. **Nudge `skillListingBudgetFraction` `0.03 → 0.032`** and remeasure. Loses nothing, but changes
   a global knob, so try it after the cheaper moves.

Do **not** cut from the six proven slots (§2 rows 1–6). Those are the only entries with measured
evidence that the slot itself is producing the invocations.

### 4.3 What plugin budget actually exists (corrected)

**Only enabled plugins cost context.** Enablement is read from `settings.json:enabledPlugins`
and cross-checked against the live skill listing. A plugin's files stay in
`~/.claude/plugins/cache/` after it is disabled, so a cache scan over-reports — that is the error
noted in §4.2.

**Live and costing context:**

| Plugin | Listing cost | 70-day uses | Ships | Disable? |
|---|---:|---:|---|---|
| `agent-skills` | 7,234 | 11 | hooks + 4 agents | no — biggest block, but load-bearing |
| `skill-concierge` | 2,827 | 42 | hooks + MCP | no — the system itself |
| `memsearch` | 1,252 | 6 | hooks | no |
| `superpowers-developing-for-claude-code` | 524 | 28 | nothing | no — 28 uses |
| `smgrep` | 271 | 0 | MCP | no — provides the semantic-search MCP |
| `i-have-adhd` | 269 | 0 | hooks | no — output-shaping is active |
| `prompt-improver` | 261 | 0 | hooks | no |
| **live total** | **12,638** | | | ~3,159 tok/turn |

**Disabled 2026-08-07 by the operator** — `fable` (2,030), `effort-gate` (444),
`last30days` (271) = **2,745 chars freed**. All three left `enabledPlugins`, the live listing, and
the plugin cache. **This freed budget promoted nothing — see §4.0.**

**Disabled earlier, already reflected in the measured headroom:** `skill-creator` (1,012),
`caveman` (2,525), `ponytail` (2,410), `plugins` (1,598), `fablize` (456), `examples` (118).
None appear in `enabledPlugins` or the live listing. **8,119 chars the original cache-derived
figure wrongly counted.**

None of the live plugin cost is reachable by `skillOverrides`, which returns `"on"` for
plugin-scoped skills before consulting the map. Disabling the whole plugin is the only control.

---

## 5. Rollout order

1. **Disable `fable` and `skill-creator`** — reversible, no functionality lost, 2 min.
   `/reload-plugins`, then count how many curated entries render.
2. **Install the 8 staged trims** from handoff §5 — frees 915 chars, already prepared, 2 min.
3. **Trim `research-grounding` and `directional-prompting`** to ≤380 chars — not yet drafted,
   ~10 min.
4. **Apply the new allowlist** via `python3 scripts/keep-on.py add/remove …`, then
   `/reload-plugins` and recount.
5. **If entries still render bare**, trim one mid-range entry or bump
   `skillListingBudgetFraction` one step and remeasure.

Verification after each step: count how many of the 30 render a description in the model-facing
skill listing. That count is the only ground truth.

---

## 6. Findings worth keeping

1. **`code-change-verification` was repo-specific — now fixed, and eligible again.**
   Its description read *"…in the OpenAI Agents Python repository"*, and both runner scripts
   hardcoded `make format / lint / mypy / tests` plus `uv`. Always-on would have made it misfire on
   every code change here, so it was cut from this list.
   **Rewritten 2026-08-07 to v2.0.0** (local source:
   `CONSTITUTION-RULES-CC_HARNESS/skills-synced/code-change-verification/`): commands are now
   resolved from the repository itself — `CCV_*` env override → Makefile target → `package.json`
   script → language-manifest default (`pyproject.toml` / `Cargo.toml` / `go.mod`) — with an
   unresolvable phase reported **SKIPPED, never PASSED**. The `.sh`/`.ps1` pair became thin
   wrappers over one stdlib-Python runner, so there is a single implementation to keep correct.
   Frontmatter reduced to the five Agent-Skills-spec fields, which also makes it packageable for
   claude.ai / the Skills API.
   **New cost: 453 chars** (was 168 — the honest, repo-neutral description is longer).
   **Installed 2026-08-07** to `~/.claude/skills/code-change-verification/`; the prior version is
   archived at `~/.claude/_Archived/code-change-verification-20260807-0234-pre-v2.0.0/`.
   **Now included in the set at §2 row 13.**
2. **Plugin skills bypass `skillOverrides` entirely** (documented behaviour). Any plugin-namespaced
   entry in `keep-on.json` is decorative. Only personal- and project-scoped skills are steerable.
3. **The budget fitter drops descriptions wholesale; it does not truncate.** An entry that does not
   fit renders as a bare `- name`. This failure is silent — `scripts/apply-overrides.py` reports
   "in sync, no drift" throughout, because it compares its own map to itself, not to what rendered.
4. **The eight entries currently rendering bare are exactly the eight at the 512-char cap.** The
   staged trims in handoff §5 were correctly targeted.

---

## 7. Unresolved questions

1. **The exact listing-budget constant.** Must be established empirically by bumping
   `skillListingBudgetFraction` one step at a time and observing which entries render. Not
   derivable from outside the binary.
2. **How far `skillListingBudgetFraction` has to move.** Disabling `fable` alone leaves the set
   ~690 chars short of even the optimistic ceiling, so the fraction has to rise. How far is not
   derivable — bump one step, reload, count what renders, repeat.
3. **`directional-prompting` (537) has not been trimmed** — only costed. `research-grounding` was
   trimmed 534 → **375** on 2026-08-07 by deleting its `Enforces:` clause, every element of which
   was verified still present in the skill body (Step 0, the SEARCH rotation, the FETCH priority
   list, and the cite-and-split honesty rule). The same treatment should work for
   `directional-prompting`, but its description has not been read for body-duplication yet.
4. **Whether `vn-bctt-report` and `vn-deep-dive-report` should be reinstated** despite the
   workflow classification. Costs 356 + 387 = 743 chars at staged sizes.

---

## 8. Applied state — 2026-08-07 02:57

| Item | State |
|---|---|
| `keep-on.json` | **30 entries** — the 29 in §2 plus `skill-concierge:skill-search` |
| Effective | **30 on / 380 name-only**, 410 skills discovered (410 not 418: disabled plugins' cache dirs were removed) |
| Backups | `~/.claude/settings.json.bak-skillconcierge-20260807-025754-70576` and `-70623` (one per operation) · `keep-on.json` backed up before the edit |
| `research-grounding` | trimmed 534 → **375**, installed. Prior version: `~/.claude/_Archived/research-grounding-20260807-0249-pre-desc-trim/` |
| `directional-prompting` | trimmed 537 → **389**, installed. Prior version: `~/.claude/_Archived/directional-prompting-20260807-0256-pre-desc-trim/` |
| `code-change-verification` | rewritten harness- and platform-agnostic, v2.0.0, installed (§6 finding 1). Prior version: `~/.claude/_Archived/code-change-verification-20260807-0234-pre-v2.0.0/` |
| The 8 staged trims from handoff §5 | **still uninstalled** — that decision is unchanged |
| `skillListingBudgetFraction` | **unchanged at 0.03** |

**The measurement this document exists to run has not been taken yet.** It needs
`/reload-plugins`, then a count of how many of the 29 render a description in the model-facing
listing. Per §4.0.1 the expectation is that many will not — 51% carry no priority signal at all.
Whatever that count is, it settles what three rounds of arithmetic could not.

### 8.1 A defect confirmed while applying the set

`scripts/apply-overrides.py:181` reads `if "skill-search" not in keep_on:` — testing only the
**bare** name. The router is registered here as `skill-concierge:skill-search`, so the check never
matches and a false WARN fires on every apply. Reproduced live during this apply, with the
namespaced entry provably present in `keep-on.json`.

One-line fix:

```python
if not any(n == "skill-search" or n.endswith(":skill-search") for n in keep_on):
```

**Not applied.** A source change here needs the repo's version + CHANGELOG bump; that is a release,
and out of scope for the allowlist work that surfaced it.

**Note on an earlier retraction.** The handoff document briefly recorded this warning as "never a
real defect" after inspecting `scripts/keep-on.py:98`, which *does* accept both name forms — but
that is the remove-path guard, a different check. Reading one call site and generalising to "no
defect" was the error. The handoff entry has been un-retracted with the correct `file:line`.
