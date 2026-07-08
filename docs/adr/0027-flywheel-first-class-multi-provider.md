# ADR-0027 — Retrieval flywheel promoted to first-class (multi-provider, visible, self-service)

Status: Accepted (2026-07-08)
Relates to: ADR-0026 (the LLM-utterance trigger layer this operationalizes), ADR-0018 (self-healing
launcher / auto-resync — the pattern the deferred auto-hook mirrors), ADR-0007 (maintenance skills:
setup/doctor). Source: `plans/260708-1345-flywheel-first-class/plan.md`.

## Context
ADR-0026 shipped the utterance layer — offline LLM-generated "how a user actually asks for this
skill" phrases (EN+VN) that lift recall. But generation was **manual and single-endpoint**: it only
targeted a local LM-Studio, and a new skill got no utterances until someone remembered to run a
script. The highest-leverage 0.16.x gain was buried behind an invisible manual step, and locked to
one LLM host. The graceful fallback (no utterances → description+body retrieval, never a crash) made
the gap silent, which is exactly why it needed to be made visible.

## Decision
Make the flywheel **first-class**: broadly runnable, self-describing, and self-service — while keeping
the fallback as the safety net (first-class ≠ mandatory).

- **Multi-provider LLM routing (`scripts/flywheel_llm.py`).** One OpenAI-compatible client, not
  per-provider SDKs. New env: `FLYWHEEL_LLM_API_KEY` (optional `Authorization: Bearer` — unlocks any
  3rd-party gateway) and `FLYWHEEL_LLM_SCHEMA_MODE` (`json_schema` default | `json_object` | `off`,
  for endpoints that don't honor strict schemas). `ping()` preflight (`(ok, detail)`, never raises).
  Existing `FLYWHEEL_LLM_ENDPOINT`/`MODEL` unchanged. Covers **LM-Studio, Ollama (`/v1`), and any
  OpenAI-compatible gateway** — documented in `references/flywheel-llm-providers.md`. All four vars
  live in `~/.claude/settings.json` env (durable, same home as `SKILL_TRIGGERS`).
- **Doctor visibility (`scripts/doctor.py` `check_flywheel()`).** Read-only, **fail-open** (never
  FAIL — the flywheel is optional): reports configured? / reachable? (`ping()`) / coverage (indexed
  skills vs utterance-covered skills, naming the missing). So every future agent and new user is told
  the flywheel exists and what it needs.
- **Self-service skill (`skills/flywheel/`, registers as `skill-concierge:flywheel`).** Menu-visible.
  Status mode (default, read-only) shows endpoint health + coverage; `--generate` runs the
  **incremental** generator (only new/changed skills call the LLM) then reindexes, gated on a live
  `ping()` (fails loud at a dead endpoint, pointing at the providers doc). Bare `name: flywheel` per
  the component-building doc — the plugin supplies the `skill-concierge:` namespace.

## The deferred auto-hook (recorded, NOT built this cut)
The "just works" endpoint is a `hooks/scripts/auto_flywheel.py` SessionStart hook mirroring
`auto_reindex`: when an endpoint is configured AND `ping()` succeeds, detect skills missing
utterances, generate for just those, reindex — detached, throttled (longer than reindex; generation
is heavier), per-run capped, `SKILL_AUTO_FLYWHEEL`-gated, fully fail-open. **Deliberately deferred to
Phase 2** at the operator's direction (this cut = a/b/c; the auto-hook is the proposal). a/b/c are its
prerequisites and stand on their own. Open Phase-2 questions: default ON vs OFF; paid-gateway
cost/latency budget per run; triggers-only vs also refreshing the scenario eval corpus.

## Evidence (this cut, verified by the overseer live)
- `flywheel_llm.py --selftest` PASS; `ping()` live against LM-Studio `:4310` → `(True, '…/models
  reachable — gemma-4-12b-it-qat-optiq, …')`.
- `doctor.py` renders `[✓] Retrieval flywheel` across all three states (unconfigured / reachable /
  unreachable); `status: OK`, other checks unaffected.
- `skill-concierge:flywheel` status mode prints endpoint config + reachability + `532/532 covered`;
  `--generate` gates (venv-missing → exit 3, unreachable → exit 2 with the providers-doc pointer) with
  zero side effects.

## Consequences
- The flywheel is discoverable (menu + doctor), runnable by most users (local or gateway LLM), and
  self-service. The fallback is untouched — an unconfigured/unreachable endpoint degrades to
  description+body silently, exactly as before.
- **Deploy dependency (ADR-0013/0018):** the new skill + scripts reach the running plugin only after a
  push + `/plugin marketplace update` (+ the auto-reindex indexes the new skill so it appears in the
  offered set). The `FLYWHEEL_LLM_MODEL` must match the endpoint's exact served model name before a
  `--generate` run (e.g. the local host serves `gemma-4-12b-it-qat-optiq`, not the code placeholder).

## Open / to measure
- Whether making the flywheel visible + easy measurably lifts coverage-on-new-skills and lowers the
  dodge rate (the hypothesis behind first-classing it) — measure after real use, epoch-scoped.
- Phase-2 auto-hook go/no-go + its default state.
