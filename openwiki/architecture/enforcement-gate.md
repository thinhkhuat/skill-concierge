# Architecture — the enforcement gate, the doctrine & the ledger (Enforce + Ledger)

Where [retrieval-engine.md](retrieval-engine.md) covers *which* skill, this page covers
**whether** the model uses one — the organ the project's own telemetry named as the real
bottleneck. The design reasoning (and the explicit rejection of a post-hoc detection gate) is in
[`docs/skill-first-enforcement-mental-model.md`](../../docs/skill-first-enforcement-mental-model.md);
this page is the *implementation* map.

Two invariants hold for everything below: **fail-silent** (any error → exit 0, turn proceeds
unchanged) and **additive-only** (hooks inject context, never block). A hook that appears to do
nothing may be swallowing an exception.

## The SessionStart doctrine — prevention by presence

[`hooks/scripts/doctrine.py`](../../hooks/scripts/doctrine.py) fires once at SessionStart. It
reads [`hooks/doctrine/skill-first.md`](../../hooks/doctrine/skill-first.md) **at runtime** (single
source of truth, no hardcoded copy), extracts the body between `<!-- DOCTRINE-START -->` /
`<!-- DOCTRINE-END -->` markers, and emits it as `additionalContext`. A malformed edit degrades to
over-injecting the whole file, never to silence.

The same hook warns when jevd answers on loopback but the session's `JEVD_URL` is unset or not a loopback `http`
URL: the enforcer reads `JEVD_URL` from the environment the harness started with and ignores any other
shape, so such a session bypasses jevd for every Jev call. The warning goes to the user (`systemMessage`) and to the agent (appended to the
context); `SKILL_JEVD_ENV_CHECK=0` turns it off.

Session-scoping (v0.14.0, H3, [ADR-0020](../../docs/adr/0020-subagent-session-scoping.md)): if
the SessionStart payload carries a positive `agent_id` field — present only inside a subagent
call — and `SKILL_SUBAGENT_STOP=1` (default), injection is suppressed: a scoped worker that
can't act on the doctrine isn't nagged, and the usage ledger stays clean. Any parse error or a
top-level `--agent`/persona session (`agent_type` only, no `agent_id`) still fails **toward**
injection — suppression needs positive proof, never absence of signal.
Per-harness subagent doctrine scope — whether a delegated subagent receives the doctrine + per-turn mandate across each of the four harnesses (Claude Code, Codex, Command Code, OMP) — is documented factually in [§12 of the mental model](../../docs/skill-first-enforcement-mental-model.md#12-per-harness-subagent-doctrine-scope-factual-2026-08-26) with file:line citations and UNVERIFIED markers. Summary: Claude Code subagents never fire `UserPromptSubmit` so get no enforcement; OMP's `before_agent_start` fires per-agent so subagents DO get enforcement; Command Code and Codex are UNVERIFIED from the adapter surface.

The standing order it injects is the **SKILL-FIRST doctrine**; its text is
[`hooks/doctrine/skill-first.md`](../../hooks/doctrine/skill-first.md) and nothing here restates it.
In brief: every task-bearing reply opens with a line-1 ruling (`USING:`, `SEARCH:` or
`NO SKILL: <why>`); a skip has exactly three lawful sources (a shown search with nothing adaptable,
a whole-shelf ranking whose top row is ruled out by name, an enforcer `SKILL-CHECK:` line); the
take-bar equals the skip-bar; a loaded body that excludes the task forces an open re-rule, backed
by the deterministic exclusion echo in
[`hooks/scripts/skill_exclusions.py`](../../hooks/scripts/skill_exclusions.py) (reaching every
harness through its own adapter). The reasoning lives in the ADRs:
[0056](../../docs/adr/0056-doctrine-rewrite-writing-for-agents.md) (writing-for-agents rewrite),
[0058](../../docs/adr/0058-off-list-rule-exclusion-echo-row-provenance-synced-default-off.md) and
[0059](../../docs/adr/0059-harness-complete-offer-isolation-echo-everywhere.md) (hits the harness does
not list, the echo), [0062](../../docs/adr/0062-no-skill-ruling-and-whole-shelf-label.md) (the
`NO SKILL:` ruling and the two offer kinds), [0063](../../docs/adr/0063-continuing-a-skill-and-audit-reader-fixes.md)
to [0065](../../docs/adr/0065-continuation-counter-fixes-red-flag-idle-notice.md) (continuing a skill),
[0082](../../docs/adr/0082-whole-shelf-ranking-is-a-skip-source.md) (whole-shelf skip).

> EFFORT (the "work to done-and-proven" doctrine) was **decoupled in v0.4.0** into the standalone
> [`effort-gate`](https://github.com/thinhkhuat/effort-gate) plugin; the note no longer rides in
> the injected body. skill-first governs *which / whether a skill* only.

## The per-turn gate — `enforcer.py`

[`hooks/scripts/enforcer.py`](../../hooks/scripts/enforcer.py) runs on every `UserPromptSubmit`.
Its `main()` walks a fixed sequence; each early-return is a *verdict*:

1. **Cheap pre-gate (no I/O).** Empty prompt, a prompt starting with `/` (the user already chose a
   route), or a prompt of `≤ MAX_SHORT_WORDS` words → silent return. `MAX_SHORT_WORDS = 3`
   ([ADR-0010](../../docs/adr/0010-word-floor-5-to-3.md), lowered from 5 so the language-aware
   imperative veto still sees 4–5-word commands; ≤3-word trivia is skipped before any embed).
1b. **Harness-message lane (leg D, no I/O).** A prompt whose head is harness-generated —
   `<task-notification>`, `<system-reminder>`, `<cross-session-message`, `<teammate-message`,
   `[Cross-session idle notice]` (since 0.52.3), interrupted/continued-session banners, an OMP
   `omp-msum` summarizer wrapper — is not a user
   task: authorize the skip and stop here (`ENFORCER_HARNESS_SKIP`, ledger band `harness_skip`,
   no chain hint — [ADR-0054](../../docs/adr/0054-harness-message-lane-and-audit-fixes.md)).
   Anchored at the head, so a pasted block mid-prompt still routes normally.
2. **Refusal guard.** A regex anchoring negation + an invocation verb (use/invoke/apply/call/…)
   catches "don't use skill X" — mpnet cosine doesn't encode negation, so a refused skill still
   retrieves at full score. On match → mandate-only.
3. **Self-referential recap skip (leg C).** `_is_selfref(prompt)` — fires **here, before any I/O**
   (the `_is_selfref` call in `main()` of `enforcer.py`), so a pure "explain your last answer" turn never reaches the embed. Detail in
   [leg C](#the-authorized-skip-tier-five-legs) below.
3b. **Deterministic routes (pure, no I/O).** `_route_hits` matches
   [`config/deterministic-routes.json`](../../config/deterministic-routes.json) phrases as whole
   words (never inside a longer word: `/cook` must not fire on `…/cookbooks`) — a prompt that NAMES a skill (`/unlazy`, `cook --auto`, `progress-map`) — and the hits lead the
   menu at score 1.0 later in the flow (retrieved twin dropped, getaway and intent gate bypassed).
   Computed **before** the embed so a timeout cannot lose them: the fallback mandate carries the
   hits. Honours keep-off, the blocklist and the harness-invocability test. Default ON since
   [ADR-0054](../../docs/adr/0054-harness-message-lane-and-audit-fixes.md); `ENFORCER_DETERMINISTIC=0`.
3c. **Jev skill router (leg E, English prompts, two network calls in a worker thread).** With no
   deterministic hit, a worker thread starts before the embed step: Jev ranks the whole invocable
   catalogue (chunked Choice), then re-checks the top 10 with one `fits` Noul per candidate. It is
   joined after retrieval. Best fit < 0.30 → authorize the skip (band `jev_skip`); otherwise Jev's
   top 5 replace the embedding menu and the getaway/actionability gates. A non-English prompt, a
   missing key, any error or a blown budget leaves the embedding path to decide
   (`ENFORCER_JEV_ROUTER` — [ADR-0061](../../docs/adr/0061-jev-skill-router.md), which supersedes
   ADR-0060's yes/no leg).
4. **Embed.** POST the prompt to the local index owner's warm `/embed` (`http://127.0.0.1:6363/embed`) under a **hard
   500 ms** socket timeout (`EMBED_TIMEOUT_S = 0.5`). Timeout → mandate-only (plus any route hits),
   ledger band `fallback/embed_timeout`; other error → `fallback/embed_down`. (History: a 90 ms
   cap caused ~60% timeouts under CPU contention on a single-threaded shim → the shim was made
   threaded and the cap relaxed to 200 ms —
   [ADR-0008](../../docs/adr/0008-warm-embed-shim-timeout-calibration.md) — widened to 350 ms in
   `0.21.2` when live dogfooding still showed ~65% fallback, and to 500 ms / Qdrant 250 ms in
   `0.47.0` when the v0.46.0 epoch showed every timeout landing within 6–31 ms of the old caps —
   censoring, not outages ([ADR-0054](../../docs/adr/0054-harness-message-lane-and-audit-fixes.md)).
   Every network leg is separately capped, so the worst case is the sum of the caps
   (≈1.75 s) against a 5 s hook timeout, not an unbounded wait.)
5. **Retrieve.** POST the vector to Qdrant `points/query/groups` with `group_by:"name"`,
   `group_size:1` (the same MAX-pool retrieval as the tool), excluding `tier=external`
   ([ADR-0031](../../docs/adr/0031-external-catalog-roots.md)) — externals never enter the
   ranked list; since `0.41.0` ([ADR-0048](../../docs/adr/0048-complement-annex.md)) they
   annex as the builtin's complement: installed top ≥ `GETAWAY_FLOOR` requires an external
   to beat it by `ENFORCER_ANNEX_BEAT` (0.04), thin intents widen at the plain floor, and
   demonstrated takes (auto_promote's `external-takes.json` digest) rank first rendering
   `used N×` (kill-switch `ENFORCER_ANNEX_COMPLEMENT=0` restores the 0.40.0 margin rule).
   `TOP_K = 8` — widened from 5 by
   the operator on 2026-07-05 ([ADR-0017](../../docs/adr/0017-enforcer-gate-thresholds-v2-widen-offer-menu.md)).
   Since `0.25.0` ([ADR-0034](../../docs/adr/0034-cross-harness-offer-isolation.md)) the query
   asks for `RETRIEVE_LIMIT = TOP_K * 5` and the **running harness's non-invocable rows are
   dropped client-side**, then the list is trimmed back to `TOP_K` — so every row is something the
   Skill tool can actually invoke. The multiplier is headroom, not a guarantee: where the sibling
   harness dominates a domain the menu can come back short, and a shorter menu of invocable rows
   is the accepted trade. It is a post-filter rather than
   a Qdrant `scope` condition because scope records where a skill's indexed copy *lives*, not
   whether this harness can invoke it: a plugin enabled only for the current project is dropped
   from discovery, its sibling-harness twin wins the name, and `_invocable_twin()` is the
   per-session test that rescues it. Qdrant unreachable → mandate-only, `fallback/qdrant_down`.
   Since `0.49.0` ([ADR-0059](../../docs/adr/0059-harness-complete-offer-isolation-echo-everywhere.md))
   this filter is **harness-complete**: `_foreign_scopes()` (`enforcer.py`) names every scope tuple
   for every running harness — Claude's and OMP's own tuples had the same gap Codex's did, so
   `omp-managed`/`zcode-plugin` rows were entering their offers as if invocable — and a new test
   (`tests/test_foreign_scope_completeness.py`) walks every discovery scope so a forgotten root
   fails a test instead of leaking. **DSH and Cline get a real filter for the first time**: both
   have no skill-plugin registry (`_invocable_plugin_ids()` returns `None` there by design), and
   the pre-`0.49.0` "unknown registry → drop nothing" rule used to switch their whole foreign
   filter off; they now always run the scope check, reading the shared `~/.agents/skills`
   convention root the way ZCode already did — `personal` is foreign to them only when that root
   does *not* resolve to Claude's own `~/.claude/skills`. **Project isolation**
   (`ENFORCER_PROJECT_ISOLATION`, default ON) drops a project-scoped row (`<family>:<skills dir>`)
   whose project root is neither this session's cwd nor an ancestor/descendant of it, *unless* a
   same-named copy exists at the same relative path in the session dir or a parent — the index
   keeps one point per skill name, so a skill installed in two projects is otherwise scoped to
   whichever reindexed last. The `<project>/.agents/skills` convention root is foreign only under
   Claude Code; every other harness that reads it treats it as its own. The other half of the
   isolation, `_retrieve_foreign` (the cross-harness annex query below), now marks each row with
   the harness whose roots actually hold it (`_scope_harness`, rendered `[omp]`/`[zcode]`/…) instead
   of a hand-typed `[codex]`/`[claude]` label — the old label constant is deleted because nothing
   read it.
   Since `0.48.0` ([ADR-0058](../../docs/adr/0058-off-list-rule-exclusion-echo-row-provenance-synced-default-off.md))
   `claude-synced` (Claude account-synced skills) joins every non-Claude `_foreign_scopes()` tuple
   and is dropped client-side there like any foreign row, but it is deliberately EXCLUDED from
   `_retrieve_foreign`'s own scope filter — a synced skill never appears in the cross-harness
   foreign annex either, because Claude Code sanitizes synced bodies before serving them and a
   harness whose own loader does not should not receive a labeled "consume via get_skill"
   recommendation for one.
6. **Keep-off drop.** Remove chronic never-take skills from the menu **before** the floors,
   gate, and ranking ([ADR-0011](../../docs/adr/0011-ledger-derived-offer-suppression.md)). The
   map is read from the durable home `~/.claude/skill-concierge/keep-off.json` and honoured only
   when it carries `"approved_by_user": true` — saved by `scripts/build_keep_off.py --apply` after
   Thinh's yes, never built by `doctor --fix` / `setup.sh` (harness-shaped offers excluded,
   keep-on members exempt —
   [ADR-0054](../../docs/adr/0054-harness-message-lane-and-audit-fixes.md),
   [ADR-0077](../../docs/adr/0077-keep-off-map-is-consent-only.md)); any other map hides nothing.
   The shipped `config/keep-off.json` is the empty seed. Fail-open to the empty set.
7. **Deterministic routes** (`_route_hits`, computed in step 3b). **Default ON since ADR-0054**
   (`ENFORCER_DETERMINISTIC=0` disables): when a route hits, it leads the menu and **bypasses both
   the getaway floor and the intent gate** below (`if not det and …`).
8. **Getaway floor.** `GETAWAY_FLOOR = 0.45`: if the top candidate scores below it → **silent
   verdict leg A** (see AUTHORIZED-SKIP). This floor is **operator-set over the data that argued
   against it** (taken offers historically scored *lower* than dodged ones) — a pinned
   do-not-change note guards it; [ADR-0009](../../docs/adr/0009-operator-set-gate-thresholds.md).
9. **Actionability / imperative-veto intent gate.** Suppress an offer **only** when the prompt is
   *not* imperative **and** classified conversational. `_is_imperative()` skips leading fillers and
   "can you"-style openers (including Vietnamese `làm ơn` / `vui lòng`), then checks the leading
   token/bigram against English and Vietnamese verb lists — imperative turns are **never**
   suppressed. `_intent_conversational()` runs two label-filtered kNN queries over a `prompt_intent`
   corpus and suppresses only if conversational mean beats actionable mean by a margin. Fails
   **open** (offers) on any error. On suppress → **silent verdict leg B**.
10. **Offer.** Keep candidates `≥ ITEM_FLOOR = 0.18` (or fall back to top-1) and inject a ranked
   SKILL-FIRST mandate: a ranked preview with relative %-share (shown for 2+ candidates) plus the
   line-1 `USING/SEARCH/NO SKILL` instruction. A router turn's offer is headed "Whole-shelf ranking
   for this task" instead of "Preview … not the shelf". Ledger band `offer`.

### The AUTHORIZED-SKIP tier (five legs)

Legs A (getaway floor miss) and B (conversational) used to be **truly silent**, which backfired:
the agent, seeing no mandate, would re-run `search_skills` to re-derive a verdict the hook had
*already made*. So (default ON, `ENFORCER_AUTHORIZED_SKIP=1`) each leg now injects a one-line
**`SKILL-CHECK:`** authorization instead of nothing ([ADR-0015](../../docs/adr/0015-authorized-skip-tier-and-library-doctrine.md)):

- **Getaway leg** keeps the burden of proof on SKIP — it authorizes `NO SKILL: hook-cleared` *only if the
  turn is genuinely trivial*, else it orders a term-rich `search_skills` call (the raw prompt is
  what just scored below the floor) and a `get_skill` read when a hit's fit is unclear.
- **Intent leg** flatly pre-authorizes the skip (the turn was classified conversational).
- **Self-referential leg** (3rd, [ADR-0019](../../docs/adr/0019-over-fire-lane-and-gate-legibility.md), `ENFORCER_SELFREF_SKIP`): described under *Leg C* below.
- **Harness-message leg** (4th, [ADR-0054](../../docs/adr/0054-harness-message-lane-and-audit-fixes.md), `ENFORCER_HARNESS_SKIP`): a prompt whose head is harness-generated (task notification, monitor event, cross-session/teammate message, idle reminder, OMP summarizer wrapper) is pre-authorized **before any I/O** — no embed, no Qdrant, no chain hint; ledger band `harness_skip`.
- **Jev needs-a-skill leg** (5th, [ADR-0061](../../docs/adr/0061-jev-skill-router.md), `ENFORCER_JEV_ROUTER`; first shipped by ADR-0060 as a yes/no leg): the Jev router found no candidate skill whose `fits` reaches 0.30 — ledger band `jev_skip`, routing telemetry rides the row as `jev`. Fail-open: a non-English prompt, no key, a timeout or an error leaves the embedding path to decide.

`SKILL-CHECK:` is a **cross-file literal contract**: the string is emitted here, honored by the
doctrine (`skill-first.md`), and **joined on** by the usage audit
(`skills/skill-usage-audit/scripts/audit_skill_usage.py`) to exclude lawful hook-cleared skips
from the false-SKIPPING count. Changing the literal silently breaks both. Set
`ENFORCER_AUTHORIZED_SKIP=0` to restore the old silence.

**Leg C — the self-referential recap lane ([ADR-0019](../../docs/adr/0019-over-fire-lane-and-gate-legibility.md)).**
This leg was never silent — it ships already-authorized. The gate over-fired on
turns that only ask the agent to explain/rephrase its own immediately-prior message (no external
task, no skill applies), forcing a pointless search. `_is_selfref()` fires only when three gates
all hold: (1) the prompt opens with a recap verb on a 2nd-person/deictic object; (2) **no**
imperative verb (English or Vietnamese) appears **anywhere** in the prompt, not just the leading
token — the Red-Team fix for a task-tail bypass ("explain your answer and implement X"); (3) no
new-clause connector introduces an external object. Fails toward **not** firing: a missed case
costs one harmless forced search, a false-fire would bless real work. Default ON,
`ENFORCER_SELFREF_SKIP=0` reverts. The doctrine's rule 4 names the recap as lawful only with the
enforcer's `SKILL-CHECK:` line for it, so the agent doesn't mistake its own recap turns for a
self-authorized skip on a turn that actually carries a task tail.

> **Per-skill tau and the runner-up dominance collapse are gone.** Both levers
> (`ENFORCER_PER_SKILL_TAU`, `ENFORCER_DOMINANCE_RATIO`) were default-off and are removed in v0.65.0
> ([ADR-0088](../../docs/adr/0088-maintenance-consolidation-0650.md)); the getaway floor is always
> `GETAWAY_FLOOR`. `scripts/calibrate_thresholds.py` and `thresholds.json` stay, because doctor reads
> them. **Run `python3 hooks/scripts/enforcer.py --selftest` after any edit**; its body lives in
> [`tests/enforcer_selftest.py`](../../tests/enforcer_selftest.py) and pytest runs it through
> `tests/test_enforcer_selftest.py`.

## Chain hints — engine-side skill sequencing (ADR-0029)

Skills can declare optional `next-skills:` frontmatter (comma/space successor names, catalogue
ids exactly). The indexer writes a scope-keyed sidecar
`~/.claude/skill-concierge/next-skills.json` (`{scope: {name: [successors]}}`, every indexed
skill keyed, per-scope merge, atomic replace), and the enforcer appends one `CHAIN-HINT:`
candidate line to **every inject-bearing leg** — ranked mandate, mandate-only fallbacks, and all
AUTHORIZED-SKIP lines — when this session used a skill (auto OR slash-manual) within
`ENFORCER_CHAIN_TTL_S` (900 s). State comes from a bounded 64 KB ledger tail-read (sub-stamped
rows excluded), so there is zero new hot-path network and zero new state files.

The hint **bypasses nothing**: successor names are dropped unless present as a sidecar key in a
scope visible from the reading session and not in keep-off (ADR-0011 outranks resurfacing);
hinted names never enter the candidate set. ≤3-word turns stay hint-free — the ADR-0010 pre-gate
injects nothing at all (documented limit). `ENFORCER_CHAIN_HINT=0` reverts byte-identically.
Read-side measurement lives in `analyze.py --chains` (per-session sequences, successor bigrams,
length histogram). A drafted multi-intent clause-split companion was cut on review (its drafted
number was never issued; ADR-0030 below is a different, later decision) —
`extra_queries` MAX-pool fusion already provides per-intent retrieval, and doctrine rule 2 says
so.

**ADR-0030 — operator-owned chain overrides.** Frontmatter authoring is durable only for skills
the operator owns; an upstream upgrade rewrites third-party SKILL.md files and the next reindex
silently drops their chains. Curation for third-party skills therefore lives in
`~/.claude/skill-concierge/next-skills-overrides.json` (flat `{name: [successors]}`), merged
reader-side in `_visible_sidecar_names()` — override-wins per name, `[]` suppresses, fail-open,
no engine patch. Absent file = byte-identical behavior.

## The Ledger — *what actually got used*

[`hooks/scripts/ledger.py`](../../hooks/scripts/ledger.py) is registered for two events and writes
append-only JSONL to `~/.claude/skill-concierge/logs/skill-invocation-ledger.log`:

- **UserPromptSubmit** — a substantive prompt logs `{ev:"turn", q:<≤120c stripped>}`; a `/slash`
  prompt logs `{ev:"manual", name}` (the slash path never reaches PostToolUse). The prompt is
  stored **stripped** so `analyze.py` can join each `turn` to its enforcer `offer` by `(sid, q)`.
- **PostToolUse** (matcher `Skill|mcp__.*skill-search__search_skills`) — a `Skill` invocation logs
  `{ev:"auto", name, input_keys}`; a `search_skills` invocation logs `{ev:"search"}` (matched by
  **suffix** so plugin-namespacing doesn't break it — the bug fixed in v0.4.1).

**Two writers, one file:** the enforcer *also* appends `offer` events to the same ledger. So the
single log carries `offer` (enforcer) + `turn`/`manual`/`auto`/`search` (ledger.py). It compounds
forever — no rotation in code ([ADR-0006](../../docs/adr/0006-compounding-invocation-ledger.md); but
beware the external `logman` retention default — [caveats §8](../../docs/caveats.md)).

### Ledger ≠ usage (a hard line)

The ledger measures **gate compliance** (offer → take). It is **operator-flagged INVALID for
measuring real skill *usage***, for two reasons: (1) it is epoch-scoped — this repo changes what
the ledger measures almost daily, so a rate pooled across config changes describes no real
configuration; (2) an *inline* SKILL-FIRST use (the agent reads a skill's doctrine and acts
without firing the `Skill` tool) fires no PostToolUse event, so both the ledger and any tool-call
tracker miss it. **Real usage lives in the transcript SKILL-FIRST declaration trail** (the
`USING`/`SEARCH`/`NO SKILL` line-1 tokens — `SKIPPING` before `0.52.0` — in `~/.claude/projects/**/*.jsonl`), which the
`skill-usage-audit` skill reads. Using the ledger to answer a usage question is the exact mistake
that skill and [ADR guardrails](../../AGENTS.md) exist to stop. See
[operations.md](../operations.md#reading-the-ledger-the-epoch-scoped-trap).

## Index self-heal — `auto_reindex.py`

[`hooks/scripts/auto_reindex.py`](../../hooks/scripts/auto_reindex.py) runs at SessionStart to keep
the shared index fresh without anyone remembering. It: skips if the engine bin is missing (setup
not run); skips if the throttle stamp is younger than `THROTTLE_S = 1800`; reads the embedder /
Qdrant URL from `.mcp.json` (single source of truth); skips if Qdrant is down; **stamps before
spawning** (so a crash-looping engine can't re-spawn every session); then launches
`skill-search --reindex` fully **detached** (`start_new_session=True`, output to a log, not
waited on). The reindex is incremental (only changed skills re-embed). Silent and additive — it
injects no context. Disable by setting a huge `AUTO_REINDEX_THROTTLE_S`.
See [ADR-0014](../../docs/adr/0014-sessionstart-index-self-heal.md).

## Override self-heal — `auto_overrides.py`

The index self-heals, but the `~/.claude/settings.json` name-only **budget** did not — it was a
one-shot snapshot, so a newly installed skill leaked its full description every turn until someone
re-ran the applier (the 2026-07-06 audit found 42 such leaks + 11 dead keys).
[`hooks/scripts/auto_overrides.py`](../../hooks/scripts/auto_overrides.py) closes that: at SessionStart
it fires a detached, throttled (`AUTO_OVERRIDES_THROTTLE_S`, default 1800s) `apply-overrides.py
--if-changed` that reconciles the budget **only when the discovered catalogue drifted** (a no-op
session never rewrites settings or churns a backup). Offline (no Qdrant — discovery is SKILL.md
parsing), fail-silent, additive. `doctor`'s `Settings overrides` check now also **detects** the drift
(`apply-overrides.py --check`), so it is visible + auto-fixable meanwhile.
See [ADR-0025](../../docs/adr/0025-autonomous-override-freshness-and-keep-on-management.md).
## Utterance self-heal — `auto_flywheel.py`

The utterance layer (ADR-0026) was the biggest v0.16.x retrieval gain, but a new skill got no
flywheel-generated natural-utterance phrases until someone ran the manual generator.
[`hooks/scripts/auto_flywheel.py`](../../hooks/scripts/auto_flywheel.py) (v0.18.0,
[ADR-0027](../../docs/adr/0027-flywheel-first-class-multi-provider.md)) closes that: at SessionStart,
when a local LLM endpoint is configured **and** reachable (a `ping()` preflight), it detects skills
missing utterances, generates for just those (capped at `AUTO_FLYWHEEL_MAX_PER_RUN`, default 25),
and reindexes — fully **detached/non-blocking**, throttled (`AUTO_FLYWHEEL_THROTTLE_S`, default 6h),
gated `SKILL_AUTO_FLYWHEEL` (**default ON**). Unconfigured/unreachable → silent no-op → the
description+body fallback still serves. It defers **without stamping** when the index lags disk
(measured coverage before a reindex lands would false-report `0 missing`), and fails open on
unknown counts. Every run (auto or manual) is recorded in the global manifest
(`~/.claude/skill-concierge/flywheel-manifest.json`, `scripts/flywheel_manifest.py`).

## The plugin skills

The authoritative list of bundled skills is the `skills/{...}/SKILL.md` brace list in [`AGENTS.md`](../../AGENTS.md) (checked against the directories on disk by `scripts/check_skill_list_parity.py`).

| Skill | Role |
|-------|------|
| [`skills/skill-search/SKILL.md`](../../skills/skill-search/SKILL.md) | the always-on **router** — calls `search_skills` with a short intent query, reads names+desc, invokes 2–4 high-relevance skills, `get_skill` on thin descriptions. The tool the doctrine + enforcer push toward. |
| [`skills/setup/SKILL.md`](../../skills/setup/SKILL.md) | first-time **bootstrap** / post-update refresh — runs the idempotent `setup.sh`. Re-run after any plugin update. |
| [`skills/doctor/SKILL.md`](../../skills/doctor/SKILL.md) | deployment-layer **health check** + safe `--fix`. Includes the Engine-freshness check that catches a stale MCP serving old code. |
| [`skills/skill-usage-audit/SKILL.md`](../../skills/skill-usage-audit/SKILL.md) | measures whether a gate-threshold change helped **real usage**, from the transcript SKILL-FIRST trail — **not** the ledger. |
| [`skills/keep-on/SKILL.md`](../../skills/keep-on/SKILL.md) | curate the always-on **allowlist** — `list` / `add` / `remove` (via `scripts/keep-on.py`), editing the canonical `~/.claude/skill-concierge/keep-on.json` and re-applying the overrides ([ADR-0025](../../docs/adr/0025-autonomous-override-freshness-and-keep-on-management.md)). |
| [`skills/flywheel/SKILL.md`](../../skills/flywheel/SKILL.md) | **retrieval-flywheel** surface — status mode (default, read-only) shows endpoint health + per-skill utterance coverage; `--generate` runs the incremental utterance generator (only new/changed skills call the LLM) then reindexes ([ADR-0027](../../docs/adr/0027-flywheel-first-class-multi-provider.md)). |
| [`skills/blocklist/SKILL.md`](../../skills/blocklist/SKILL.md) | the user-ordered **disable tier** — `list` / `add` / `remove` via `scripts/blocklist.py`; a blocked skill is never offered, searched or served, and its Skill invocation is denied by the PreToolUse guard ([ADR-0046](../../docs/adr/0046-blocklist-disable-tier.md)). |
| [`skills/reputation/SKILL.md`](../../skills/reputation/SKILL.md) | the owner's **badge ranking** (❤️ favourite, ⭐ trusted, automatic 🔥) shown beside menu rows, via `scripts/reputation.py` ([ADR-0083](../../docs/adr/0083-owner-reputation-badges.md)). |
| [`skills/catalogs/SKILL.md`](../../skills/catalogs/SKILL.md) | register, list, remove and promote **external catalog roots** — third-party skill collections indexed without installing, via `scripts/catalogs.py` ([ADR-0031](../../docs/adr/0031-external-catalog-roots.md)). |
| [`skills/consult/SKILL.md`](../../skills/consult/SKILL.md) | the opt-in **deliberated curation** — a wide sieve over installed and external skills, capsule dossiers, a body-reading analyst and a ranked verdict, built on the `consult_candidates` tool ([ADR-0049](../../docs/adr/0049-consult-deliberation-layer.md)). |

Mechanics for setup/doctor/audit are in [operations.md](../operations.md).
