# ADR-0049 — Consult: a deliberation layer over the reflex layer

Status: Accepted + implemented (2026-08-29).
Source: owner order in session, 2026-08-29 — an opt-in "consult the best skill combo"
planning step where the agent reasons deeply over the catalogue (installed + external)
instead of relying on the per-turn embedding offer. Design dialogue + practice-run
evidence: [`docs/ideas/consult-mode.md`](../ideas/consult-mode.md); analyst artifact
`plans/reports/consult-analyst-260829-2230-consult-mode-fit.md`.

## Context

The enforcer offer is a **reflex**: it fires every turn under a hard token budget, so
it answers "which skill, fast" from embeddings over descriptions and trigger points.
It cannot read bodies, compose chains, or trade off overlaps. At ~500 indexed skills,
human curation is impossible. The 2026-08-29 practice run (the designed funnel executed
manually on a real task) produced the load-bearing evidence:

- The sieve **missed 4 of the top fits** — including the eventual #1 — purely on
  vocabulary mismatch between task phrasing and skill descriptions.
- Deep body reading **inverted two sieve verdicts**: an external scoring 0.86 on
  embeddings dropped to LOW on body content; one of three served externals was
  genuinely relevant.
- 11 full bodies + grounding fit a sonnet-class analyst subagent cleanly.
- The compose step needed session-context overrides twice (harness-enforced docs,
  repo ADR convention) — evidence the analyst must inform, never decide.

## Decision

Four locked decisions (owner, via AskUserQuestion 2026-08-29), implemented as v0.42.0:

1. **`skills/consult/`** — the funnel skill: distill sub-goals → wide sieve → admit
   sieve misses (manual admission is a designed step, not a hack) → **mandatory**
   analyst-subagent deep-read (`agents/analyst.md` template, strict JSON contract,
   sonnet-class, untrusted-bodies security) → compose with session context and
   repo-internal authority → RUN/⚠/ALSO card → verdict log → route by flag. The
   which-skills workflow pattern (delegation split, strict JSON, card render) is
   absorbed; retiring the owner's personal `which-skills` skill is an owner action,
   not this plugin's.
2. **`consult_candidates` engine tool** (`vendor/.../server.py`) — the deliberated-lane
   sibling of `search_skills` (which stays byte-identical): one query per sub-goal
   (≤5) MAX-pooled, `top_n` to 40, externals **first-class** with the read-inline
   marking (no annex gating — consult is the deliberate lane; the analyst ranks on
   body fit, origin is logistics), installed rows carry their body `path`
   (`_fuse_ranked` gains `with_paths`, default off), blocklist-filtered.
   `SKILL_CONSULT=0` is the kill-switch.
3. **Capsule dossiers** — `scripts/llm_capsules.py` generates a per-skill capsule
   (`purpose / capabilities / inputs / outputs / avoid_when`, ~150-300 tokens) into
   the canonical operator-home corpus `~/.claude/skill-concierge/capsules.json`
   (`SKILL_CAPSULES`), riding the shared `flywheel_llm` client + bounded-parallel
   worker pattern (ADR-0043) with the same single-writer contract. Incremental over
   a body+description fingerprint (content-not-mtime, ADR-0024 doctrine). Wired as an
   OPT-IN `flywheel.py --generate --capsules` third generator — the first bulk run is
   a whole-catalogue LLM pass and stays operator-commissioned (the ADR-0031 D10
   doctrine), never part of auto_flywheel in v1. The sieve attaches capsules LIVE-read
   (blocklist pattern: edits apply with no restart); an absent corpus degrades rows to
   description-only.
4. **Verdict telemetry** — `scripts/consult_log.py` appends an `ev:consult_verdict`
   row (shape / primary / chain / externals) to the invocation ledger, fail-silent.
   Uptake needs no new code: invoking the consult skill and each taken pick already
   log `auto` rows, so recommended-vs-taken closes without touching the analyzer.

**Phase 2 (not in this commit):** enforcer consult-intent phrase routing — a
consult-intent class on the turn emitting `USING: skill-concierge:consult` via the
existing mandate machinery, gated `SKILL_CONSULT_ROUTE`, never routing subagent
sessions. Sequenced after the core is verified live.
*(Status: implemented in v0.43.0 the same night, after the core verified live —
blind-tested PASS; two borderline over-fires parked as epoch-watch W1 replay items.
See the 0.43.0 CHANGELOG entry.)*

## Consequences

- **Zero per-turn cost change**: the enforcer offer path is untouched; consult is
  opt-in (explicit invocation until phase 2's routed phrases land).
- **Capsule corpus is a second freshness surface** — bounded by the fingerprint (body
  edits invalidate automatically at the next `--capsules` run) and reported as
  `capsule_coverage` on every sieve call; growth is incremental and operator-paced.
- The practice-run assumptions "capsule signal beats metadata" and "routing precision"
  remain OPEN — they are epoch-watch items, not settled by this ADR.
- The analyst spawn is Claude/ZCode-path with a documented inline fallback
  (`analysis: inline, no spawn primitive`) for harnesses without the primitive.

## Revert

One-var: `SKILL_CONSULT=0` disables the engine tool; omit `--capsules` and the
generator never runs; `git revert` the single v0.42.0 commit restores 0.41.0. No data
migrations — `capsules.json` is new and ignorable; ledger `consult_verdict` rows are
inert to current analyzers.

## Verification

`llm_capsules.py --selftest` and `consult_log.py --selftest` PASS (network-free);
`build_triggers.scroll_all_points(paths=True)` additive with byte-identical default;
engine compile OK + venv redeploy + live MCP probe; `consult` skill indexed; doctor
green; driftcheck exit 0; blind tester verdict. Details in the release report.
