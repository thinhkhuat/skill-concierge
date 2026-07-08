---
name: skill-concierge:flywheel
user-invocable: true
description: See the retrieval-flywheel status and trigger an incremental utterance-generation run. Use this skill when the user asks about the flywheel, "how many skills have utterances / triggers", "flywheel coverage", "which skills are missing utterances", "is the LLM endpoint configured/reachable", or wants to "generate triggers", "run the flywheel", "refresh utterances", or "index the new skills' utterances". The flywheel is the utterance layer (ADR-0026) that teaches the retriever how users actually ask for a skill (EN+VN), lifting recall. Runs scripts/flywheel.py — status mode (default, read-only) prints endpoint config + reachability and per-skill utterance coverage (N/M covered, and the missing skills by name); --generate runs the incremental generator (only new/changed skills hit the LLM) then reindexes so the new points go live, printing before/after coverage. Generation fails loud if the LLM endpoint is unreachable.
argument-hint: "[--generate] [--rate <seconds>]"
license: MIT
metadata:
  version: 0.1.1
---

# skill-concierge flywheel

Surface and drive the **retrieval flywheel** — the utterance layer (ADR-0026). For each
indexed skill the flywheel stores short, LLM-generated "how a user actually asks for this"
phrases (English + Vietnamese) under `llm_triggers` in `eval/triggers.json`; those phrases
lift retrieval recall. Generation is **offline and incremental** — the generator
content-hashes each skill, so only new or changed skills ever hit the LLM. Skills with no
utterances still work (graceful fallback to description+body retrieval); the flywheel just
makes them easier to find.

This skill is the seamless surface for two things: **seeing** where the flywheel stands, and
**running** an incremental generation pass.

## Steps

1. **Status (default, read-only)** — endpoint config + reachability and per-skill coverage:

   ```bash
   python3 "$CLAUDE_PLUGIN_ROOT/scripts/flywheel.py"
   ```

   It prints:
   - **Endpoint** — the configured `FLYWHEEL_LLM_ENDPOINT` + model, whether an API key is
     set, the schema mode, and a live `ping()` reachability result.
   - **Coverage** — `N/M indexed skills have utterances; K missing`, then the missing skills
     by name. Indexed names come from the live Qdrant `claude_skills` index (kind=base);
     covered = a non-empty `llm_triggers.triggers` in `eval/triggers.json`.

2. **Generate (`--generate`)** — fill utterances for new/changed skills, then reindex:

   ```bash
   python3 "$CLAUDE_PLUGIN_ROOT/scripts/flywheel.py" --generate
   ```

   It preflights the endpoint with `ping()` and **fails loud** if unreachable (pointing at
   the provider-setup doc — do not generate against a dead endpoint). On success it runs BOTH
   incremental generators — the eval scenarios (`llm_eval_gen.py`) and the utterance triggers
   (`llm_triggers.py`), under the engine venv — then `skill-search --reindex` so the new
   utterance points land live, and prints before/after coverage. Only new/changed skills call
   the LLM (each generator content-hashes the description), so re-running when nothing changed
   is cheap and safe. Every run is recorded to the global manifest (below).

   Flags: `--triggers-only` skips the measurement-only scenario pass (triggers are what serve
   retrieval); `--limit <N>` caps how many skills are processed in one pass; `--rate <seconds>`
   spaces out LLM calls when sharing a busy endpoint.

## Auto-flywheel (background, default ON) + the run manifest

You usually do **not** need to run `--generate` by hand. The **`auto_flywheel`** SessionStart
hook (ADR-0027, gated `SKILL_AUTO_FLYWHEEL`, **default ON**) does it for you: when an endpoint is
configured **and** reachable, on session start it detects skills missing utterances, generates for
just those, and reindexes — **detached and non-blocking** (it never delays the session), throttled
(`AUTO_FLYWHEEL_THROTTLE_S`, default 6h) and capped per run (`AUTO_FLYWHEEL_MAX_PER_RUN`, default 25).
If no endpoint is configured or it's unreachable, the hook is a **silent no-op** — the graceful
description+body fallback is untouched.

Because the run is a background process, its results are written to a **global manifest** at
`~/.claude/skill-concierge/flywheel-manifest.json` — timestamp, endpoint+model, per-skill status,
totals, coverage, last error (last 20 runs). Any agent or the user can read it to verify what the
flywheel did, without watching a live process. Status mode (above) prints the last run from it, and
`doctor` reports it too.

## When it can't run

- **Endpoint unreachable** → `--generate` fails loud. Configure a provider first; the three
  documented setups (LM-Studio, Ollama, OpenAI-compatible gateway) live in
  `references/flywheel-llm-providers.md`. The four `FLYWHEEL_LLM_*` env vars belong in
  `~/.claude/settings.json` env (durable). Status mode still works — it just reports NO.
- **Engine venv missing** → `--generate` points you at the **`skill-concierge:setup`** skill,
  which builds the venv. After a reindex, retrieval picks up the new points immediately (no
  restart needed).

Doctor's `check_flywheel()` reports the same coverage + reachability inside the normal health
workflow; this skill is the place to **act** on it.
