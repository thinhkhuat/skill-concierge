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

## Phase 2 — the auto-hook (BUILT in v0.18.0)
Shipped as `hooks/scripts/auto_flywheel.py` (SessionStart, mirrors `auto_reindex`) +
`scripts/flywheel_manifest.py` (global run manifest) + smart `--generate` (`--triggers-only`/`--limit`)
+ `doctor`/flywheel-skill manifest surfacing. Operator-firmed decisions, all implemented:

- **Default ON** (`SKILL_AUTO_FLYWHEEL=1`). Fully fail-open — unconfigured or `ping()` fails → silent
  no-op → today's description+body fallback, untouched.
- **Non-blocking background process** (detached, mirrors `auto_reindex`): the SessionStart hook returns
  immediately; generation + reindex run in a spawned process that outlives the hook. Throttled
  (`AUTO_FLYWHEEL_THROTTLE_S`, long — generation is heavier than a reindex), per-run capped so a bulk
  skill import can't stampede the LLM.
- **Global run manifest** at `~/.claude/skill-concierge/flywheel-manifest.json` (canonical durable home,
  ADR-0025). Every run appends/updates: timestamp, endpoint+model, per-skill `{status, when}`,
  totals, resulting coverage, and last error. Any agent or the user can read it to verify what the
  background flywheel did — no need to watch a live process. **Surfaced in both** the
  `skill-concierge:flywheel` skill (status shows the last-run manifest summary) and `doctor`
  (`check_flywheel` reports the last run + coverage from the manifest).
- **Smart `--generate` / auto-run scope** (uniform for the hook and the skill): the generators already
  detect new/modified skills by `body_hash(description)` and skip unchanged ones. Policy:
  **new skill → generate BOTH** (scenarios + triggers); **modified skill (description hash changed) →
  regenerate BOTH** (both are description-derived; the old ones describe the old skill); **unchanged →
  skip**. A `--triggers-only` flag skips the measurement-only scenario regen when the operator wants to
  economize LLM calls.
- **Coverage is index-driven** → symlinked skills (global `~/.claude/skills` + project
  `.claude/skills`, incl. dev-source symlinks) are automatically covered: they are discovered by the
  one-level `*/SKILL.md` globs and land in the live index, which is what the flywheel enumerates.
  Verified: 17/18 symlinked dirs indexed (the 1 miss is a non-skill helper dir); `cognee-memory-doctor`
  (symlinked) is in the index.

a/b/c (shipped in 0.17.0) are the prerequisites. Remaining open item: paid-gateway cost/latency budget
per run (the throttle + per-run cap matter most for metered endpoints; a local endpoint is free).

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
