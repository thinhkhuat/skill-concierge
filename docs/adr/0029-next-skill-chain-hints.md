# ADR-0029 — Next-skill chain hints (engine-side chaining primitive)

Status: Accepted (2026-08-19; revised same day after adversarial + scope review —
`plans/reports/validate-260819-2255-adr0029-0030-adversarial.md`,
`plans/reports/review-260819-2255-adr0029-0030-overengineering.md`; all four blocking
findings folded in before implementation, P1 validation gates passed)
Relates to: ADR-0009/0017 (gate thresholds — the hint must bypass NO floor), ADR-0011
(keep-off suppression outranks any hint), ADR-0012/0016 (vendored-engine patch pattern +
VENDORED.md), ADR-0015 (`SKILL-CHECK:` — what this ADR does NOT duplicate), ADR-0020
(subagent scoping — chain state must not bleed across lanes), ADR-0023 (trigger purity),
ADR-0026 (the `.mcp.json`-forwarding gap class this design avoids having), ADR-0028
(multi-session scoping — the sidecar MUST NOT repeat its incident).
Source: `plans/260819-2218-engine-skill-chaining/plan.md`; owner directed P0 drafting
2026-08-19 — ADR content itself is Pending owner approval, not yet approved.

## Context

Skill *sequences* are how complex requests get done (brainstorm → plan → cook → test →
ship), but the engine is strictly per-turn: the enforcer sees ONLY the user prompt
(`hooks/scripts/enforcer.py:128`), has no memory of the prior turn's USING line, and
retrieves a fresh top-k each turn. Chaining today is doctrine-only — the standing order
forces a re-SEARCH every turn (`hooks/doctrine/skill-first.md:63`) and the agent itself
re-queries as each skill completes. That works while the agent holds context; the honest
gap is **hint survival across context compaction** — after a long session compresses,
"which skill came next" is exactly the fact the agent loses and the engine can retain
cheaply.

The superpowers study deferred terminal-state routing as brittle — correct against
*hard routing* (one legal successor over ~500 skills), not against a *soft hint*: an
optional, per-skill, additive candidate line that passes every existing filter. This ADR
ships the soft version.

Hard constraints: the enforcer hot path (≲300ms) gets **no new network calls**
(enforcer.py:18-24, 63-64); hooks stay **fail-silent, additive-only, stdlib-only**
(enforcer.py:12-16); any shared file must respect **ADR-0028 multi-session scoping**.

## Decision

- **Authoring.** Optional SKILL.md frontmatter `next-skills: plan, cook, test`
  (comma/space separated). Absent → that skill is untouched. Opt-in per skill, so the
  corpus is never blanket-wired.
- **Extraction (vendored patch).** `skills_discovery.parse_skill` reads `next-skills`
  into the skill dict; index time writes a sidecar map
  `~/.claude/skill-concierge/next-skills.json`, **scope-keyed and merge-don't-replace**
  after ADR-0028's pattern: `{scope: {name: [successors]}}`, each reindex writes only
  the scopes visible from its CWD (`skills_discovery._scope_for`) and prunes only those
  scopes — never another session's project entries. Written **atomically**
  (tmp + `os.replace`, the `server.py:215-224` precedent) and **unconditionally**
  (content is flag-independent; the flag gates only the reader — no producer/consumer
  drift class to forward, contrast ADR-0026). No Qdrant payload carriage:
  `_fuse_ranked` renders `{name,command,description,score}` only (`server.py:648-652`)
  and `get_skill` already returns the full SKILL.md with frontmatter (`server.py:692-707`).
  Logged in `vendor/skill-search/VENDORED.md` for re-apply (ADR-0016 pattern).
- **Chain state = ledger tail-read, no new state file.** The enforcer reads the last
  64KB of the existing invocation ledger and takes the most recent `auto` OR `manual`
  event matching this `sid` within a **15-minute TTL**. This replaces the originally
  drafted chain-state.json because (a) the ledger already records t/sid/name for both
  event classes (`ledger.py:63,83-84`) — a dedicated file seeded only from
  PostToolUse(Skill) would have silently missed every slash-invoked chain; and (b) it
  removes a read-modify-write concurrency surface entirely.
- **Subagent hygiene.** `ledger.py` stamps `auto`/`manual` events with a `"sub": true`
  key when the hook input carries an `agent_id` (positive check, mirroring
  `doctrine.py`'s ADR-0020 rule). The tail-read skips `sub` events — a scoped worker's
  invocation must not steer the main session's hint — and `analyze.py` gains the same
  exclusion (AGENTS.md contamination guardrail). Additive key; existing rows parse
  unchanged.
- **Hint injection — placement (review Blocking 1).** The hint is NOT bound to the
  ranked mandate. It appends one line to **every inject-bearing leg** — ranked mandate,
  mandate-only fallback, and all three AUTHORIZED-SKIP lines — because the turns it
  exists for (≥4-word vague continuations) land on the getaway/intent-skip legs
  (`enforcer.py:592-608`), not the mandate. The ≤3-word pre-gate (`enforcer.py:537-538`,
  ADR-0010 operator floor) stays **out of scope**: two-word "go ahead" turns get
  nothing, recorded here as a known limit rather than carving an exception into an
  operator-set floor. Repetition semantics: the line repeats on each inject-bearing
  turn within the TTL (bounded, one line); consume-on-fire is the recorded upgrade if
  the new epoch shows push-noise — it is not built now because it would require
  re-introducing persistent hint state.
- **Hint construction — mechanized filters (review Blocking 3).** Before rendering,
  successor names are dropped unless they (1) resolve to a key in a scope **visible to
  the reading session** (kills dangling names AND other-scope dead recommendations,
  `_scope_filter`'s problem, `server.py:671-673`), and (2) are **not in `KEEPOFF`**
  (`enforcer.py:177`, the `_deterministic_hits` refusal at `enforcer.py:262` and its
  selftest 6b pin the precedent: suppression outranks any resurfacing path). The line
  itself: `CHAIN-HINT: after <A>, catalogue declares: <b>, <c> — candidates, fit still
  required.` It bypasses no floor and no gate — hinted names never enter `cands`; the
  line is context only. Wording stays clear of the audit's locked literals
  (`SKILL-CHECK:`, the three `_AUTHORIZED_SIGNATURES` phrases — parity pinned by
  selftest, `enforcer.py:781-789` precedent).
- **Doctrine.** `hooks/doctrine/skill-first.md` gains one rule-6-area row: a chain hint
  is a preview, not a mandate; USING still requires fit; a hint does not authorize
  skipping the search.
- **Toggle.** `ENFORCER_CHAIN_HINT` (default **ON** — additive, low blast, mirrors the
  AUTHORIZED-SKIP default-on precedent). `=0` reverts to byte-identical behavior. The
  env is inherited by the detached reindex automatically (`auto_reindex.py:48` builds
  from `dict(os.environ)`); no forwarding entry is needed because the sidecar write is
  unconditional.

## What this ADR deliberately does NOT do

- No auto-invocation, no hard routing, no DAG — the agent keeps routing authority.
- No duplication of ADR-0015: `SKILL-CHECK:` authorizes *skips*; CHAIN-HINT proposes
  *candidates*. Different lanes, no marker collision.
- No cross-session chains — state is per `sid`, TTL-bounded.

## Evidence (validation plan — Proposed until P1 passes)

- `enforcer.py --selftest` extended: hint fires on fresh same-sid state across ALL
  inject-bearing legs; silent on TTL-expired / other-sid / `sub`-stamped events /
  no-successors / unreadable files / flag-off; **keep-off'd successor is dropped**
  (mirror of selftest 6b); **out-of-scope successor is dropped**; audit-parity pin
  (CHAIN-HINT and the doctrine row never match `_is_authorized_skip_line`).
- Byte-identity: with no `next-skills` authored anywhere, output byte-identical to
  v0.20.8 on every leg.
- E2E: fixture skill with `next-skills`; next same-session prompt (≥4 words) carries
  the hint; a `/skill` manual invocation also seeds it.

## Consequences

- Skills can express "after me, X"; the engine honors it one turn later at the cost of
  one bounded local tail-read + one local map read, zero new network, zero new
  state file.
- `analyze.py --chains` (W3) ships read-side over existing events, subagent-excluded;
  the hint-follow metric is **deferred** until a demotion decision needs the number.
- New telemetry epoch at ship — chain measurements never pool backward.
- If the hint depresses offered-turn conversion in the new epoch, `ENFORCER_CHAIN_HINT=0`
  is the one-var revert; demotion to default-off is a superseding-ADR decision.
- Vendored surface grows by one field + one sidecar writer: re-vendoring requires
  re-applying (VENDORED.md recipe).
