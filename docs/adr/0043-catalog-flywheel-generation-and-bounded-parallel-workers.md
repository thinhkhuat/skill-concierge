# ADR-0043: Catalog-Scoped Flywheel Generation + Bounded Parallel Workers

- **Status**: Accepted. **Amended by [ADR-0045](0045-catalog-tier-parity.md)
  (2026-08-28):** the installed-only DEFAULT is reversed — a bare `--generate` now covers
  EVERY scope (installed first, then each configured catalog, each capped by `--limit`);
  `--installed-only` restores this ADR's original default, `--catalog <alias>` still
  narrows, and manifest records carry an explicit `scope` field.
- **Date**: 2026-08-28
- **Relates to**: ADR-0031 Decision 10 (the deferral this lands), ADR-0026 (utterance
  layer), ADR-0027 (auto-flywheel + manifest)

## Context

Three facts converged on 2026-08-28:

1. **The deferral came due.** ADR-0031 D10 deferred flywheel utterances for external
   catalogs ("1,599 × LLM calls for search-only citizens is not day-one cost") —
   explicitly not ruled out. The owner commissioned the phase for the `antigravity`
   catalog in full (1,928 skills on disk, 16,527 indexed points).
2. **Sequential generation does not scale to a catalog.** Measured 16.0 s/skill
   (per-call latency + the per-call politeness sleep) → 8.4 h projected for one
   catalog. The bottleneck is wall-clock I/O wait, not model quality.
3. **The gateway hides transient upstream 503s inside HTTP 200 envelopes.** A failing
   call returns `finish_reason: "stop"` with content literally
   `[CommandCode error: {"type":"server_error","message":"Service temporarily
   unavailable…","statusCode":503,"isRetryable":true}]` (observed live on
   `cmc/minimax/minimax-m3-free` and its paid sibling). The HTTP-5xx retry ladder
   never sees it; the first catalog pass died when a ladder-exhausted reply surfaced
   as an opaque parse failure and the client raised a `RuntimeError` no per-skill
   handler catches — one bad skill killed ~4 minutes of work.

## Decision

1. **Catalog scope is an explicit, named opt-in.** `build_triggers.scroll_all_points(catalog=)`
   lifts the `tier=external` skip for exactly one alias (scope filter `catalog:<alias>`);
   `--catalog <alias>` threads through `llm_triggers` / `llm_eval_gen` / `flywheel.py`.
   The default path stays byte-identical — externals remain excluded from default
   coverage counts, so the 0.22.1 contract (no permanent false coverage gap in status
   and doctor) survives untouched. Manifest coverage for a catalog run scopes to that
   catalog; `--catalog` with zero indexed skills fails loud (exit 5) before any LLM call.
2. **Bounded parallelism with a single writer.** `--workers N` (default 1 — the
   sequential loop is kept verbatim) fans ONLY the network phase (chat + VN retry) out
   over a `ThreadPoolExecutor`; validate/merge/`triggers.json`/cache writes happen in
   the main thread as futures complete, so the files never see concurrent writers.
   Per-call `rate_s` politeness is unchanged, so effective gateway load scales with N;
   per-skill failure isolation is unchanged.
3. **The 200-wrapped 503 joins the transient class.** `flywheel_llm.chat()` detects the
   error envelope; `isRetryable` errors ride the existing 3-attempt/5s-10s ladder;
   ladder exhaustion raises `URLError` (an `OSError`, which every per-skill handler in
   both generators catches) — a sustained outage fails the skill, never the pass.
4. **Scenario layer excluded for catalogs in the commissioned run** (`--triggers-only`):
   the measurement layer has no external consumer today; the owner approved halving the
   gateway burn.
5. **Model choice stays operator env** (`FLYWHEEL_LLM_*` in `~/.config/harness-env.sh`);
   only the docstring's production-model mention tracks the live deployment
   (`cmc/MiniMaxAI/MiniMax-M3`).

## Consequences

- Trigger points grow by up to `TRIGGERS_MAX` per catalog skill (antigravity:
  ~+29k points at 16/skill) — one-time embed cost at the run's final reindex. The
  enforcer's `tier=external` exclusion is untouched: catalogs still never enter the
  per-turn offer by tier, only via the ADR-0036 annex.
- `--workers N` multiplies instantaneous gateway concurrency. N is the lever if the
  upstream pushes back; the ladder absorbs blips and cache-keyed resumes make any
  later catch-up pass cheap.
- The cache is description-keyed, not model-keyed: switching models mid-catalog mixes
  provenance within one catalog's utterances. Accepted (output shape is validated
  identically either way); a uniform regen is one `PROMPT_VERSION` bump away.
- `llm_eval_gen` gains the same workers seam for coherence even though catalog runs
  use `--triggers-only` today.

## Evidence

- Head-to-head model probe (4 real catalog skills, real prompt path):
  `cmc/MiniMaxAI/MiniMax-M3` 2.6–6.0 s/call, 0 validation errors;
  `cmc/xiaomi/mimo-v2.5` 25.4–40.7 s/call — rejected.
- Throughput: sequential 16.0 s/skill measured (5 skills/80 s); 4 workers measured
  1.9 s/skill effective (21 skills/40 s) with zero per-skill failures; projection
  improvement 8.4 h → ~50 min for the commissioned catalog.
- The run-1 crash class was reproduced (200-wrapped envelope on a live probe),
  fixed, and re-verified: the production pass shows 0 WARN lines across hundreds of
  skills.
- Selftests PASS (`llm_triggers`, `llm_eval_gen`), compile clean, live
  `--limit 4 --workers 4` smoke generated 4/4.

## Update — v0.35.1: the auto path covers catalogs too

Owner directive the same day: the flywheel must be autonomous and seamless —
"always run on skills that need a new flywheel run." The `auto_flywheel`
SessionStart hook now runs installed skills first, then one capped pass per
configured catalog alias in the same detached shell, with
`AUTO_FLYWHEEL_WORKERS` (default 4) riding the parallel path. Cost stays
bounded by the same three gates as before: the cache keys on skill content
(only new/changed skills reach the LLM), `AUTO_FLYWHEEL_MAX_PER_RUN`, and the
6h throttle + lock. Decision 4's "owner-commissioned" framing now applies to
full backfills only; steady-state catalog autonomy is the default.
