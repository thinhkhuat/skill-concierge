# Make the retrieval flywheel a first-class feature (v0.17.0)

**Owner:** operator (thinhkhuat) · **Overseer:** MAX · **Date:** 2026-07-08
**Why:** the utterance layer (ADR-0026) is the highest-leverage 0.16.x gain — it teaches the
retriever how users *actually ask* for a skill (EN+VN), which is what lifts recall and should cut
the dodge rate. Today it is gated behind a **manual** offline generation step, so new skills get no
utterances until someone remembers to run a script. That buries the best part of the release. Make
it first-class: **advertised, multi-provider, self-service, and eventually "just works".**

The existing graceful fallback (no utterances → description+body retrieval, never a crash) stays as
the safety net. First-class does NOT mean mandatory — it means visible, easy, and broadly runnable.

---

## Scope this cut (implement now): a, b, c

### (c) Multi-provider LLM routing — `scripts/flywheel_llm.py`
The client already targets an OpenAI-compatible `/v1/chat/completions` via `FLYWHEEL_LLM_ENDPOINT`
(+ `FLYWHEEL_LLM_MODEL`). Gaps to cover the majority of users:
- **Add optional auth:** `FLYWHEEL_LLM_API_KEY` → send `Authorization: Bearer <key>` when set. This
  alone unlocks every 3rd-party **OpenAI-compatible gateway** (OpenAI, OpenRouter, Together, Groq,
  Anthropic-via-compat-proxy, self-hosted vLLM, …).
- **Add a schema-mode toggle:** `FLYWHEEL_LLM_SCHEMA_MODE = json_schema | json_object | off`
  (default `json_schema`). LM-Studio grammar-constrains with strict `json_schema`; Ollama's `/v1`
  and some gateways only honor `json_object`; `off` relies on the prompt. The generators already
  validate + retry the reply, so a looser mode degrades safely.
- **Add a preflight probe:** `ping()` → cheap reachability + model check (GET `…/models` or a 1-token
  chat) returning `(ok, detail)`. Consumed by doctor (b) and the skill (a).
- **Three documented setups** (a `references/flywheel-llm-providers.md` + README pointer):
  1. **LM-Studio** (default): `FLYWHEEL_LLM_ENDPOINT=http://localhost:4310/v1/chat/completions`, no key.
  2. **Ollama**: `…=http://localhost:11434/v1/chat/completions`, `SCHEMA_MODE=json_object`, no key.
  3. **OpenAI-compatible gateway**: `…=<base>/v1/chat/completions`, `FLYWHEEL_LLM_API_KEY=<key>`,
     `FLYWHEEL_LLM_MODEL=<model>`.
- All four env vars belong in `~/.claude/settings.json` env (durable, same home as `SKILL_TRIGGERS`).
- Keep it stdlib-only; keep `--selftest` network-free; keep thinking-OFF guidance.

### (b) Doctor integration — `scripts/doctor.py` `check_flywheel()`
A new read-only, **fail-open** check surfaced in the normal health workflow, so any fresh agent /
new user learns the flywheel exists and what it needs:
- **Configured?** report the endpoint + model (and whether a key is set), or "not configured
  (utterance layer runs in fallback = description+body only)".
- **Reachable?** call `flywheel_llm.ping()`; WARN (not FAIL) if configured-but-unreachable.
- **Coverage:** compare indexed skill names (live Qdrant) vs `eval/triggers.json` `llm_triggers`
  keys → "N/M skills have utterances; K missing: …". Names the fix.
- Never FAIL (flywheel is optional); INFO/WARN only. Include a one-line `fix:` → run the flywheel skill.

### (a) `skill-concierge:flywheel` skill (menu-visible, user-invocable)
A repo skill (mirror `skills/doctor/`), so it shows in the slash menu and the offered set:
- **Status mode (default):** print coverage, endpoint config + reachability (via `ping()`), and the
  list of skills missing utterances. Read-only.
- **Run mode (`--generate` / on confirm):** run the **incremental** generators
  (`llm_triggers.py`, optionally `llm_eval_gen.py`) — they already skip skills whose content hash is
  unchanged, so this only calls the LLM for new/changed skills — then trigger a reindex so the new
  utterance points land live. Print before/after coverage.
- Fail-loud if the endpoint is unreachable, pointing at the provider setup doc.
- **MUST follow** `~/.claude/docs/claude-code-component-building.md` (ENFORCED) when authoring the
  SKILL.md + wrapper script; build it in the repo `skills/` dir, never `~/.claude/skills`.

### Docs + release (this cut)
- **ADR-0027** — flywheel promoted to first-class: multi-provider routing, doctor visibility, the
  skill, and the deferred auto-hook (record the decision + the deferral rationale).
- CHANGELOG `[0.17.0]`; bump `plugin.json` + `marketplace.json` → **0.17.0** (this is a feature).
- README + AGENTS runtime-flags: the four `FLYWHEEL_LLM_*` vars + the new skill + doctor check.
- OpenWiki: operations.md flywheel section (defer to a follow-up openwiki:wiki run).

---

## Proposal — the NEXT integration: "just works" auto-flywheel (Phase 2, not this cut)

Mirror the proven `auto_reindex.py` pattern with a new **`hooks/scripts/auto_flywheel.py`**
SessionStart hook:
- **Gate:** only acts when a LLM endpoint is **configured AND `ping()` succeeds**. Unconfigured or
  unreachable → silent no-op (today's graceful fallback, untouched). This is the "insured with a
  fallback" the operator asked for.
- **Detect:** indexed skill names − `triggers.json` llm-covered names = the missing set.
- **Generate (incremental):** for just the missing/changed skills (the generators' content-hash cache
  already makes this cheap), merge into `triggers.json`.
- **Reindex:** hand off to the existing reindex so the new utterance points go live — auto-indexing,
  auto-generating, auto-updating, seamless.
- **Safety rails (mirror auto_reindex):** DETACHED + non-blocking; THROTTLED
  (`AUTO_FLYWHEEL_THROTTLE_S`, default long, e.g. 6h — generation is heavier than a reindex);
  stamp-before-spawn; a hard cap on skills-per-run so a bulk import can't stampede the LLM; all
  failures fail-open. Env-gated `SKILL_AUTO_FLYWHEEL` (default OFF until proven, then flip ON).
- **Open design questions for Phase 2** (decide before building): cost/latency budget per run for
  paid-gateway users (a local endpoint is free, a gateway is not — the throttle + per-run cap matter
  more there); whether `--generate` should also refresh the scenario corpus or only triggers; how to
  surface "flywheel is generating in the background" without noise.

Phase 2 turns the manual skill (a) into the automatic path; (a)+(b)+(c) are its prerequisites and
stand on their own value meanwhile.

---

## Delegation (specialists; overseer = MAX integrates + verifies + commits)
- **Backend specialist** → (c) `flywheel_llm.py` multi-provider + `ping()`, and (b) `doctor.py`
  `check_flywheel()`. Cohesive Python; ships `--selftest` coverage.
- **Skill builder** → (a) the `skill-concierge:flywheel` skill, per the ENFORCED component-building
  doc, wrapping the incremental generators + reindex.
- MAX → this plan, ADR-0027 + CHANGELOG + version bump + README/AGENTS, integration review, live
  verify (a real `ping()` against the running LM-Studio + a coverage read), commit/push.

## Decisions already made (overseer, on operator's behalf)
- **0.17.0** (feature minor bump), not a patch — a/b/c add user-facing capability.
- **Auto-hook deferred to Phase 2 proposal**, per the operator's explicit split ("tackle a/b/c +
  layout the proposal"). It is designed above and ready to build on greenlight.
- **Multi-provider via one OpenAI-compatible client** (not per-provider SDKs) — smallest change,
  covers LM-Studio + Ollama + any gateway. YAGNI on provider-specific code.

## Open questions for the operator
- Phase 2 auto-hook: green-light to build next, and default ON or OFF at first ship?
- Should the flywheel skill also (re)generate the **scenario eval corpus** (`eval/scenarios-shadow/`),
  or triggers-only? (Triggers are what serve retrieval; scenarios are for measurement.)
