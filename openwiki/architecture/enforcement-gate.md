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

Session-scoping (v0.14.0, H3, [ADR-0020](../../docs/adr/0020-subagent-session-scoping.md)): if
the SessionStart payload carries a positive `agent_id` field — present only inside a subagent
call — and `SKILL_SUBAGENT_STOP=1` (default), injection is suppressed: a scoped worker that
can't act on the doctrine isn't nagged, and the usage ledger stays clean. Any parse error or a
top-level `--agent`/persona session (`agent_type` only, no `agent_id`) still fails **toward**
injection — suppression needs positive proof, never absence of signal.

The standing order it injects — the **SKILL-FIRST doctrine**:

- **Line-1 token protocol.** Every task-bearing reply must open with one of
  `USING: <skill>` | `SEARCH: <query>` | `SKIPPING: none`, written *before* anything else. The
  forced pre-commitment is the mechanism: having written the token, the model is far likelier to
  actually follow it (self-coherence) than to drift into improvising and back-rationalize.
- **The shown skills are a top-few PREVIEW of ~500**, nearly all hidden. "The previewed few don't
  fit" is therefore the trigger to **SEARCH the full index**, never grounds to skip. A `SEARCH:`
  token is a promise to call `search_skills` **this reply**; narrating an un-run search is a
  forbidden FALSE REPORT.
- **The take-bar equals the skip-bar.** A loosely-adaptable fit is a `USING:`; closest-fit-adapted
  is the standard, perfect is not the bar. Naming an unfit skill just to pass the gate is a FALSE
  REPORT.
- **`SKIPPING` is lawful in one class only** — a genuine no-task turn (a harness/system
  notification, an await-only ping, an inbound message handing you no work). If the per-turn
  preview arrived *with* candidates, a task is present and this class does not apply.
- **The library doctrine** (the burden-of-proof clause): a skip is a *reasoning-based intent
  classification* (trivial vs real, unambiguous vs ambiguous), **not** a score threshold. Costs
  are asymmetric — a needless search is cheap; declaring "nothing fits" on real/ambiguous work
  while a ~500-skill catalogue and the `find-skills` meta-skill sit unused is the top-severity
  failure. **Burden of proof is on SKIP.**

> EFFORT (the "work to done-and-proven" doctrine) was **decoupled in v0.4.0** into the standalone
> [`effort-gate`](https://github.com/thinhkhuat/effort-gate) plugin. skill-first now governs
> *which / whether a skill* only.

## The per-turn gate — `enforcer.py`

[`hooks/scripts/enforcer.py`](../../hooks/scripts/enforcer.py) runs on every `UserPromptSubmit`.
Its `main()` walks a fixed sequence; each early-return is a *verdict*:

1. **Cheap pre-gate (no I/O).** Empty prompt, a prompt starting with `/` (the user already chose a
   route), or a prompt of `≤ MAX_SHORT_WORDS` words → silent return. `MAX_SHORT_WORDS = 3`
   ([ADR-0010](../../docs/adr/0010-word-floor-5-to-3.md), lowered from 5 so the language-aware
   imperative veto still sees 4–5-word commands; ≤3-word trivia is skipped before any embed).
2. **Refusal guard.** A regex anchoring negation + an invocation verb (use/invoke/apply/call/…)
   catches "don't use skill X" — mpnet cosine doesn't encode negation, so a refused skill still
   retrieves at full score. On match → mandate-only.
3. **Self-referential recap skip (leg C).** `_is_selfref(prompt)` — fires **here, before any I/O**
   (`enforcer.py:550`), so a pure "explain your last answer" turn never reaches the embed. Detail in
   [leg C](#the-authorized-skip-tier-three-legs-two-formerly-silent) below.
4. **Embed.** POST the prompt to the warm shim (`http://127.0.0.1:6363/embed`) under a **hard
   200 ms** socket timeout (`EMBED_TIMEOUT_S = 0.20`). Timeout → mandate-only, ledger band
   `fallback/embed_timeout`; other error → `fallback/embed_down`. (History: a 90 ms cap caused
   ~60% timeouts under CPU contention on a single-threaded shim → the shim was made threaded and
   the cap relaxed to 200 ms within a ≲300 ms budget — [ADR-0008](../../docs/adr/0008-warm-embed-shim-timeout-calibration.md).)
5. **Retrieve.** POST the vector to Qdrant `points/query/groups` with `group_by:"name"`,
   `limit=TOP_K`, `group_size:1` (the same MAX-pool retrieval as the tool). `TOP_K = 8` — widened
   from 5 by the operator on 2026-07-05 ([ADR-0017](../../docs/adr/0017-enforcer-gate-thresholds-v2-widen-offer-menu.md)).
   Qdrant unreachable → mandate-only, `fallback/qdrant_down`.
6. **Keep-off drop.** Remove chronic never-take skills (`config/keep-off.json`,
   [ADR-0011](../../docs/adr/0011-ledger-derived-offer-suppression.md)) from the menu **before**
   the floors, gate, and ranking. Fail-open to the empty set.
7. **Deterministic routes** (`_deterministic_hits`, `enforcer.py:582`). **Inert unless
   `ENFORCER_DETERMINISTIC` is set** — but when a route *does* hit, it leads the menu and
   **bypasses both the getaway floor and the intent gate** below (`if not det and …`). Worth knowing
   the step exists in the sequence even though it ships off.
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
   line-1 `USING/SEARCH/SKIPPING` instruction. Ledger band `offer`.

### The AUTHORIZED-SKIP tier (three legs, two formerly silent)

Legs A (getaway floor miss) and B (conversational) used to be **truly silent**, which backfired:
the agent, seeing no mandate, would re-run `search_skills` to re-derive a verdict the hook had
*already made*. So (default ON, `ENFORCER_AUTHORIZED_SKIP=1`) each leg now injects a one-line
**`SKILL-CHECK:`** authorization instead of nothing ([ADR-0015](../../docs/adr/0015-authorized-skip-tier-and-library-doctrine.md)):

- **Getaway leg** keeps the burden of proof on SKIP — it authorizes `SKIPPING: none` *only if the
  turn is genuinely trivial*, else it tells the agent to escalate to `find-skills` / `get_skill`.
- **Intent leg** flatly pre-authorizes the skip (the turn was classified conversational).

`SKILL-CHECK:` is a **cross-file literal contract**: the string is emitted here, honored by the
doctrine (`skill-first.md`), and **joined on** by the usage audit
(`skills/skill-usage-audit/scripts/audit_skill_usage.py`) to exclude lawful hook-cleared skips
from the false-SKIPPING count. Changing the literal silently breaks both. Set
`ENFORCER_AUTHORIZED_SKIP=0` to restore the old silence.

**Leg C — the self-referential recap lane (v0.14.0, H5, [ADR-0019](../../docs/adr/0019-over-fire-lane-and-gate-legibility.md)).**
Unlike legs A/B, this leg was never silent — it ships already-authorized. The gate over-fired on
turns that only ask the agent to explain/rephrase its own immediately-prior message (no external
task, no skill applies), forcing a pointless search. `_is_selfref()` fires only when three gates
all hold: (1) the prompt opens with a recap verb on a 2nd-person/deictic object; (2) **no**
imperative verb (English or Vietnamese) appears **anywhere** in the prompt, not just the leading
token — the Red-Team fix for a task-tail bypass ("explain your answer and implement X"); (3) no
new-clause connector introduces an external object. Fails toward **not** firing: a missed case
costs one harmless forced search, a false-fire would bless real work. Default ON,
`ENFORCER_SELFREF_SKIP=0` reverts. The doctrine's Red Flags table (below) carries a matching row
so the agent doesn't mistake its own recap turns for a self-authorized skip on a turn that
actually carries a task tail.

> **Many enforcer levers are default-INERT and env-gated** — per-skill tau
> (`ENFORCER_PER_SKILL_TAU`), deterministic routes (`ENFORCER_DETERMINISTIC`), and the P6
> runner-up dominance collapse (`ENFORCER_DOMINANCE_RATIO`). The data reasons for keeping them off
> are pinned in source comments, and `python3 enforcer.py --selftest` asserts they stay inert by
> default. **Run `--selftest` after any edit.**

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
`USING`/`SEARCH`/`SKIPPING` line-1 tokens in `~/.claude/projects/**/*.jsonl`), which the
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

## The six plugin skills

| Skill | Role |
|-------|------|
| [`skills/skill-search/SKILL.md`](../../skills/skill-search/SKILL.md) | the always-on **router** — calls `search_skills` with a short intent query, reads names+desc, invokes 2–4 high-relevance skills, `get_skill` on thin descriptions. The tool the doctrine + enforcer push toward. |
| [`skills/setup/SKILL.md`](../../skills/setup/SKILL.md) | first-time **bootstrap** / post-update refresh — runs the idempotent `setup.sh`. Re-run after any plugin update. |
| [`skills/doctor/SKILL.md`](../../skills/doctor/SKILL.md) | deployment-layer **health check** + safe `--fix`. Includes the Engine-freshness check that catches a stale MCP serving old code. |
| [`skills/skill-usage-audit/SKILL.md`](../../skills/skill-usage-audit/SKILL.md) | measures whether a gate-threshold change helped **real usage**, from the transcript SKILL-FIRST trail — **not** the ledger. |
| [`skills/keep-on/SKILL.md`](../../skills/keep-on/SKILL.md) | curate the always-on **allowlist** — `list` / `add` / `remove` (via `scripts/keep-on.py`), editing the canonical `~/.claude/skill-concierge/keep-on.json` and re-applying the overrides ([ADR-0025](../../docs/adr/0025-autonomous-override-freshness-and-keep-on-management.md)). |
| [`skills/flywheel/SKILL.md`](../../skills/flywheel/SKILL.md) | **retrieval-flywheel** surface — status mode (default, read-only) shows endpoint health + per-skill utterance coverage; `--generate` runs the incremental utterance generator (only new/changed skills call the LLM) then reindexes ([ADR-0027](../../docs/adr/0027-flywheel-first-class-multi-provider.md)). |

Mechanics for setup/doctor/audit are in [operations.md](../operations.md).
