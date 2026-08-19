# Engine-Side Skill Chaining — v0.21.0

**Status:** P1 COMPLETE (W1 implemented, selftested, E2E'd, engine deployed to venv +
sidecar live with 413 keys). ADR-0030/W2 **CUT — owner decision 2026-08-19** (both reviews
concurred; residue doctrine sentence shipped in P1). Hook-side go-live rides the next
plugin update (owner's `/plugin marketplace update`). P2 (analyze --chains) next.
**Date:** 2026-08-19 · **Baseline:** v0.20.8 · **Branch target:** `main`
**Origin:** validation request 2026-08-19 ("does skill-concierge support daisy-chaining?") → verdict PARTIAL
(doctrine-level emergent chaining only; engine-side chaining deferred as M2 in
`plans/reports/study-extract-superpowers-novelty-260706-1210-...-report.md:52,96`). Owner chose full scoping.
**Reviews:** adversarial `plans/reports/validate-260819-2255-adr0029-0030-adversarial.md` (FAIL-as-drafted,
4 blocking — all folded into ADR-0029 revision) · scope `plans/reports/review-260819-2255-adr0029-0030-overengineering.md`
(6 cuts — all accepted; W2 cut owner-ratified 2026-08-19).

## Outcome

A complex multi-step request gets engine support for **skill sequences**, not just per-turn
selection: skills can declare successors, the enforcer surfaces them at the right moment
(and they survive context compaction), and the ledger can measure real chains.

## Constraints (binding, from repo doctrine)

- Hooks stay **fail-silent, additive-only, stdlib-only** (AGENTS.md *Conventions*;
  enforcer.py:12-16). No new network calls on the per-turn hot path (≲300ms, enforcer.py:18-24).
- Any shared file respects **ADR-0028 multi-session scoping** (scope-keyed, merge-don't-replace).
- Vendored-engine edits are logged in `vendor/skill-search/VENDORED.md` and re-appliable (ADR-0016 pattern).
- Ledger telemetry is **epoch-scoped** — chain metrics start a NEW epoch at the ship commit (AGENTS.md guardrail).
- New enforcer behavior follows the flag pattern: additive/low-blast → default ON; false-fire risk → default OFF.

## Non-goals

- No engine-side DAG/workflow planner — hints are candidates, the agent keeps routing authority.
- No auto-invocation of successors (USING stays a judgment, per the library doctrine).
- No cross-session chains (state is per `sid`).
- `audit_skill_usage.py` untouched in v1.

## Ground truth (what exists today, cited)

| Surface | State |
|---|---|
| Retrieval | MAX-pool top-k over query variants, `server.py:637-670`; enforcer group_by name, payload `["name","description"]` only, `enforcer.py:395-412` |
| Per-turn menu | `_ranked_mandate` renders name+desc+relative share, `enforcer.py:425-446`; TOP_K=8 |
| Chaining today | Doctrine-only: forced re-SEARCH each turn (`hooks/doctrine/skill-first.md:63`); `SKILL-CHECK:` avoids verdict re-derivation (ADR-0015). Zero engine chaining |
| Skill metadata | `parse_skill` extracts `{name, description, body, body_triggers, path, scope}` — no successor field, `skills_discovery.py:261-315` |
| Ledger | `turn/manual/auto/search/offer`; `auto`+`manual` carry skill name + sid (`ledger.py:63,83-84`); windows per-turn, no cross-turn sequence view (`analyze.py:135-181`) |
| Result rendering | `_fuse_ranked` hardcodes `{name,command,description,score}` (`server.py:648-652`); `get_skill` returns full SKILL.md incl. frontmatter (`server.py:692-707`) |

## Design

### W1 — Next-skill hints — ADR-0029 (REVISED per reviews)

1. **Authoring:** optional frontmatter `next-skills: plan, cook, test`.
2. **Extraction (vendored):** `parse_skill` → **scope-keyed sidecar map**
   `~/.claude/skill-concierge/next-skills.json` `{scope: {name: [successors]}}` at index
   time — merge-don't-replace per scope (ADR-0028 pattern), atomic tmp+`os.replace`,
   written **unconditionally** (no producer flag, no `_mcp_env` forwarding — env inherits
   via `auto_reindex.py:48`; the forwarding class belongs to ADR-0026's `.mcp.json` gap).
   No Qdrant payload carriage (no renderer for it — ground-truth table above).
3. **Chain state:** enforcer **tail-reads the ledger** (last 64KB; most recent `auto` OR
   `manual` for this `sid` within 15-min TTL). No chain-state.json — the dedicated file
   would have missed slash-invoked chains and added an RMW concurrency surface
   (review Finding: `ledger.py:63` manual events seed chains too).
4. **Subagent hygiene:** `ledger.py` stamps `"sub": true` on events whose hook input
   carries `agent_id` (positive check, ADR-0020 rule); tail-read and analyze skip them.
5. **Hint injection:** one `CHAIN-HINT:` line appended to **every inject-bearing leg**
   (mandate, mandate-only fallback, all AUTHORIZED-SKIP lines) — the vague ≥4-word
   continuations it exists for land on getaway/intent legs, not the mandate
   (`enforcer.py:592-608`). The ≤3-word pre-gate (ADR-0010 operator floor) stays out of
   scope — documented known limit. Repeats within TTL (one line/turn);
   consume-on-fire is the recorded upgrade if the epoch shows push-noise.
6. **Mechanized filters at render:** successors dropped unless (a) present as a key in a
   scope visible to the reading session (kills dangling + cross-scope dead names) and
   (b) **not in `KEEPOFF`** (ADR-0011 outranks resurfacing — `_deterministic_hits`
   precedent `enforcer.py:262`, selftest 6b). Hint text never matches the audit's
   locked literals (parity-pinned).
7. **Doctrine row + flag:** `ENFORCER_CHAIN_HINT` default ON; `=0` byte-identical revert.

### W2 — Multi-intent decomposition — CUT (owner decision 2026-08-19)

Both reviews concurred: per-intent retrieval already exists at the tool layer
(`skill-first.md` rule 2 mandates 2-3 varied phrasings; `extra_queries` MAX-pool fuses
them, `server.py:670-681`); a default-OFF mechanism would have been the fourth inert
limb (per-skill-tau precedent, `enforcer.py:188-196`, still un-armed); and the budget
math fails beyond the embed leg (3 retrieves + up to 6 intent POSTs, serial 100ms caps).
ADR-0030 deleted; residue doctrine sentence shipped with P1's doctrine edit.

### W3 — Chain-level ledger view

1. `analyze.py --chains`: per-`sid` ordered `auto`+`manual` sequences → top successor
   bigrams, chain-length histogram; **subagent events excluded** via the new `sub` stamp.
2. Hint-follow rate **deferred** until a demotion decision needs it (scope review cut 6).

## Phases

| # | Phase | Deliverables | Validation (gate) |
|---|---|---|---|
| P0 | ADR drafts + review | 0029 revised; 0030 drafted | DONE — two reports on disk, findings folded |
| P1 | W1 impl | vendored extraction + scope-keyed atomic sidecar; enforcer ledger-tail + CHAIN-HINT on all inject-bearing legs + filters; `ledger.py` `sub` stamp; doctrine row + W2-residue sentence; VENDORED.md entry | DONE — selftest green (9 sections); `tests/test_chain_hint_e2e.py` 3/3; parse test green; ledger sub-stamp verified both arms; setup.sh deployed engine, sidecar live (413 keys) |
| P2 | W3 impl | `analyze.py --chains` + selftest (sequence join, sub exclusion) | DONE — selftest green; live run: 130 sessions / 67 chained, top bigrams real (doctor→flywheel ×3, verify-as-claimed→session-handoff ×4) |
| P4 | Docs + ship | README + AGENTS.md runtime-flags + CLAUDE.md flag line; openwiki (quickstart version + enforcement-gate chain-hints section); version **0.21.0** both manifests + CHANGELOG | DONE — driftcheck exit 0 (all mirrors 0.21.0); doctor green except the restart-only live-MCP WARN; commit/push + `/plugin marketplace update` remain owner actions |

Dependencies: P1 → P2. P4 last. Each phase lands as its own conventional commit
(on owner request — no git ops otherwise).

## Risks & rollback

- **Vendor drift wipes the patch** — VENDORED.md records re-apply steps (ADR-0016 pattern).
- **Hint noise depresses conversion** (ADR-0009 class) — one-var revert
  `ENFORCER_CHAIN_HINT=0`; demotion path recorded in ADR-0029.
- **Sidecar multi-session races** — scope-keyed merge + atomic replace (ADR-0028 lesson);
  a torn read fails open to no-hint, never an error.
- **Unbounded ledger growth vs tail-read** — bounded 64KB read window; TTL bounds match
  range (ADR-0006 keeps the ledger never-rotated by design).
- **Ledger schema growth** — additive `sub` key only; `analyze.py` already tolerates
  unknown keys.

## Acceptance criteria (whole plan)

1. A skill declaring `next-skills` makes the next same-session (≥4-word) prompt surface
   its successors as filtered candidates — reproducible E2E, on the ranked-mandate AND
   authorized-skip legs; `/skill` invocations seed the same way.
2. `analyze.py --chains` prints real successor bigrams from the live ledger, subagent-free.
3. With all flags at defaults and no `next-skills` authored, output is byte-identical to
   v0.20.8 on every leg (selftest + diff).
4. doctor green, driftcheck exit 0, both manifests at 0.21.0, CHANGELOG entry present.
