# OpenSpace Study C — Multi-Host / Platform Abstraction + Config + Prompts + LLM Layer

**Date:** 2026-07-04 · **Mode:** READ-ONLY innovation study · **Target:** `/Users/thinhkhuat/LANDING_ZONE/OpenSpace`
**For:** skill-concierge (CC-native skill-governance plugin) · **Ranked by impact-to-us**

---

## TL;DR — the one thing to internalize

OpenSpace and skill-concierge solve the **same problem in opposite directions**, and that difference is the whole story:

- **skill-concierge governs the host's *own* agent in-place** — it hooks Claude Code's per-turn loop (UserPromptSubmit, SessionStart, PostToolUse) and steers *that agent* toward the right skills.
- **OpenSpace does not govern the host at all.** It exposes itself as an **MCP sidecar worker** with 4 tools plus 2 tiny "host skills" that *teach* any host (nanobot / openclaw / Claude Code / Cursor) *when to hand a task off*. OpenSpace then runs its **own internal grounding agent** — its own LLM, its own skill selection, its own tool retrieval — to do the work.

So OpenSpace's "one command to evolve all your AI agents" portability is bought by **delegating work *out* of the host into a self-contained engine**, not by adapting enforcement to each host's hooks. That is the **exact opposite** of skill-concierge's value proposition. Chasing host-portability would mean abandoning the per-turn in-place governance that *is* skill-concierge.

**Bottom line: the headline multi-host abstraction is NON-transferable — and correctly so.** But three lower-level ideas inside the config/retrieval/prompt layers would sharpen skill-concierge even while it stays 100% CC-native.

---

## How OpenSpace actually abstracts across hosts (the mechanism, grounded)

**1. Host is decoupled via MCP + "host skills," not via host-specific enforcement.**
`openspace/host_skills/README.md:150-171` — the host connects over MCP (stdio | SSE | streamable-http) and gets 4 tools: `execute_task`, `search_skills`, `fix_skill`, `upload_skill`. Two SKILL.md files teach the host *when* to call them:

> "The two host skills teach the agent **when and how** to call these tools" (`host_skills/README.md:164`)

`skill-discovery/SKILL.md:33-41` even ships a decision tree the host follows:
> "Found a matching skill? ├── YES, and I can follow it myself → read SKILL.md … ├── YES, but I lack the capability → delegate via execute_task … └── NO match → handle it yourself, or delegate".

**2. Host *detection* is only used to auto-read that host's LLM credentials — not to inject behavior.**
`host_detection/__init__.py:44-66` — `read_host_mcp_env()` reads the OpenSpace env block from whichever host config exists:
> "1. nanobot — `tools.mcpServers.openspace.env`  2. openclaw — `skills.entries.openspace.env`  3. Empty dict". Callers "never need to know which host agent is active."

`host_detection/nanobot.py` and `openclaw.py` are just config-file readers (`~/.nanobot/config.json`, `~/.openclaw/openclaw.json`) that pull provider API keys. Detection exists so a user who already configured their host's LLM doesn't reconfigure OpenSpace — **it is credential convenience, not skill/enforcement injection.**

**3. Skills flow into OpenSpace's *own* engine, not into the host.**
`mcp_server.py:571-579` — `execute_task` reads `OPENSPACE_HOST_SKILL_DIRS`, re-scans those dirs every call, and registers the host's skills into OpenSpace's *own* SkillRegistry so *OpenSpace's* internal agent can select them. The host never runs a skill-selection loop; OpenSpace does.

**How does it inject enforcement into a non-Claude-Code host? It doesn't.** There is no per-turn hook, no doctrine injection, no ledger on the host side. The host just calls a tool when its host-skill tells it to. This is why the model ports trivially — and why it can't be borrowed wholesale for a per-turn governance plugin.

---

## Transferable ideas (ranked by impact-to-us)

### 1. Two-stage retrieval: over-fetch broad, then precise-rerank a smaller final set — **HIGH impact, MED effort**

**Innovation.** OpenSpace splits skill retrieval into two stages with different tools and different widths.
`mcp_server.py:376-384`:
> "Stage 1 (here): server-side embedding search → pick top-N to import locally. Stage 2 (tool_layer): local BM25 + LLM → select from ALL local skills … for injection. Stage 1 intentionally imports **more than will be used (default: 8)** so that stage 2 has a larger pool to choose from."

And a hard cap on final injection: `config/README.md:119` — `skills.max_select` "max skills injected per task (default: `2`)".

So the pipeline is: **cheap wide embedding recall (8 candidates) → precise narrow rerank (BM25 + LLM) → inject 2.**

**skill-concierge analog.** skill-concierge's RETRIEVE layer is Qdrant + mpnet — a single-stage vector search. This is exactly the surface where a second stage helps.

**Would it meaningfully help us?** Yes — this is squarely on the "precise + cheap + actually-used" mission. Single-stage mpnet cosine is good at recall but blunt at fine ranking. Over-fetching (e.g. top-12 from Qdrant) then applying a cheap second-stage rerank (BM25 lexical, a cross-encoder, or a tiny LLM judge) before the gate decides which 1-2 skills to surface is a well-established precision win — it directly reduces the "wrong skill offered" and "right skill buried" failure modes. The cost stays low because stage 2 only ranks ~12 items, not the whole corpus.

**Transferability: MED.** Adds a rerank pass to an existing retrieval path; no host coupling. Effort is a scoped change to the retrieval module + a threshold/N knob.

**Concrete application.** In the RETRIEVE path: fetch `N_recall` (≈10-15) from Qdrant, run a lightweight reranker over just those, then let the existing budget/gate logic pick the final 1-2. Make `N_recall` and the reranker on/off a config flag so it's measurable against the skill-usage audit.

---

### 2. Granular env-var → temp-file config merge (override single keys without editing committed JSON) — **MED impact, LOW-MED effort**

**Innovation.** OpenSpace lets an operator override *individual* config keys via dedicated env vars that get deep-merged and written to a temp config file at runtime.
`host_detection/resolver.py:285-354` — `build_grounding_config_path()` reads `OPENSPACE_CONFIG_JSON` (inline JSON) or `OPENSPACE_CONFIG_PATH` (file), *then* layers granular overrides on top:
> `OPENSPACE_SHELL_CONDA_ENV`, `OPENSPACE_SHELL_WORKING_DIR`, `OPENSPACE_SKILLS_DIRS` (comma-split into `skills.skill_dirs`), `OPENSPACE_MCP_SERVERS_JSON`, `OPENSPACE_LOG_LEVEL` — merged, then `tempfile.mkstemp` → written → path returned.

Paired with a documented **layered file merge**: `config/loader.py:26-60` deep-merges `config_grounding → config_security → config_dev` (later wins), and `config/README.md:85-95` states plainly "Layered system — later files override earlier ones … `config_dev.json` … (highest priority)".

**skill-concierge analog.** skill-concierge already has one-var governance reverts (`ENFORCER_AUTHORIZED_SKIP`, `SKILL_BODY_TRIGGERS`) and curated skill-budget overrides applied by setup. But per-machine tuning of gate thresholds / budgets today means editing committed config or overrides.

**Would it meaningfully help us?** Moderately. A documented pattern of "granular `SKILLCONCIERGE_*` env var → merged into effective config → never touch the committed JSON" lets an operator tune a gate threshold or a per-skill budget on one machine without a repo edit and without the deploy-flow cost (bump plugin.json + marketplace.json + push + `/plugin update`). This is real friction reduction for experimentation on live gates.

**Transferability: MED.** The mechanism (env → deep-merge → effective config) is host-agnostic and matches skill-concierge's existing flag philosophy. Effort is small if there's already a config-load path to intercept.

**Concrete application.** Add a thin override layer: a handful of `SKILLCONCIERGE_GATE_*` / `SKILLCONCIERGE_BUDGET_*` env vars deep-merged over the committed config at load time, documented with an explicit precedence table (below).

---

### 3. Explicit, documented precedence ladder with a "higher tier *blocks* lower tier" doctrine — **MED impact, LOW effort**

**Innovation.** OpenSpace's credential resolution isn't just ordered — the ordering is a **named, documented contract** with a blocking rule.
`resolver.py:128-155` docstring defines Tier 1 (`OPENSPACE_LLM_*`) > Tier 2 (provider-native env) > Tier 3 (host config file), and `config/README.md:16-18` makes the sharp rule explicit:
> "**Tier 2 blocks Tier 3** — if `.env` has a provider key, host agent config is skipped."

The code enforces it literally: `resolver.py:173` only reads host config `if not has_explicit_llm_override and not provider_native_env_used`. The rationale is stated: local keys "take precedence over host-agent config so local/standalone launches are not hijacked by unrelated host config files" (`resolver.py:145-147`).

**skill-concierge analog.** skill-concierge has multiple config sources (committed overrides, governance flags, settings.json overrides applied by doctor/setup). The *precedence* between them is implied by ADRs but not surfaced as a single blocking-tier table.

**Would it meaningfully help us?** Yes, as **design discipline more than code**. When a machine misbehaves, "which config source won and why" is exactly the question doctor answers. A one-screen precedence table (env override > machine settings.json override > committed override > default) with an explicit blocking rule makes doctor's diagnostics sharper and prevents the "unrelated config hijacked my run" class of confusion that OpenSpace explicitly designed against.

**Transferability: MED (as a doctrine), LOW effort.** Mostly documentation + making doctor print the winning source, which is cheap and high-leverage for a debugging-heavy plugin.

**Concrete application.** Add a precedence table to skill-concierge's config docs and have `doctor.py` report, per effective setting, *which source supplied it* (mirrors `resolver.py:270-280`, which logs `source=` for every resolved LLM kwarg with the API key masked).

---

### 4. Prompt-as-code registry with sentinel self-assessment tokens — **LOW-MED impact, LOW-MED effort (largely convergent)**

**Innovation.** `prompts/skill_engine_prompts.py:3-115` — a single `SkillEnginePrompts` class holds all engine prompts as typed static builder methods (`evolution_fix`, `evolution_derived`, `evolution_captured`, `evolution_confirm`), and defines **sentinel tokens** the LLM must emit for machine-parseable self-assessment:
> `EVOLUTION_COMPLETE = "<EVOLUTION_COMPLETE>"` / `EVOLUTION_FAILED = "<EVOLUTION_FAILED>"` (`skill_engine_prompts.py:6-8`), injected into every template so the caller parses a clean signal instead of scraping prose.

**skill-concierge analog.** skill-concierge's enforcer already emits structured `SKILL-CHECK:` verdicts and injects SessionStart doctrine — so this is **largely convergent, confirming skill-concierge's existing design**. The transferable delta is the *centralized typed-builder registry* discipline (one module, one place, each prompt a function with named args) versus prompts scattered inline.

**Would it meaningfully help us?** Marginally. If skill-concierge's enforcer/doctrine prompt text is currently inline, consolidating into one typed registry with sentinel tokens eases evolution and testing. Low novelty for us.

**Transferability: LOW-MED.** Refactor-shaped, host-agnostic, no urgency.

---

### 5. "Host skill" teaching decision-tree (delegate / follow / skip) — **LOW impact, informational**

**Innovation.** Rather than hardcoding tool-call timing, OpenSpace ships a SKILL.md that teaches the agent a three-way decision: follow the skill yourself / delegate / skip (`skill-discovery/SKILL.md:33-41`).

**skill-concierge analog.** This mirrors skill-concierge's offer→take model — but skill-concierge enforces the choice via a **hook**, deterministically, not via a teaching skill the model may ignore. skill-concierge's approach is *stronger* for a CC-native tool (hooks can't be talked out of; a SKILL.md can). Worth noting only as confirmation that skill-concierge's hook-enforced choice is a deliberate upgrade over prompt-taught choice.

**Transferability: LOW.** Documented as a contrast that validates the current design.

---

## Explicitly NON-transferable (and why that's the right call)

| OpenSpace feature | Why we don't want it |
|---|---|
| **Multi-host detection** (`host_detection/nanobot.py`, `openclaw.py`, `resolver.py` tiered credential reader) | Solves "read whatever host's LLM key" for a portable sidecar. skill-concierge is deliberately CC-native; its governance *is* the CC hook mechanism. There is no second host to detect. |
| **Delegated-sidecar worker model** (`execute_task` runs OpenSpace's own agent loop) | skill-concierge's value is governing the host's *own* per-turn loop in place. A sidecar that runs a *separate* agent would abandon per-turn UserPromptSubmit/PostToolUse governance — i.e. abandon the product. |
| **Cloud skill community + auto-evolution upload** (`upload_skill`, FIX/DERIVED/CAPTURED) | Tangential to config/host/prompt scope; a different (interesting) axis handled elsewhere. Not a host-abstraction lever. |

**Honest read on "is host-portability worth pursuing for skill-concierge?"** No. skill-concierge's CC-coupling is not a limitation to escape — it's the substrate that makes deterministic per-turn enforcement possible. OpenSpace only achieves portability by *giving up* in-host enforcement. The two designs are not on the same spectrum.

---

## Status line

- **Status:** DONE — full-coverage read of assigned cluster (host_detection, host_skills, config, prompts, llm, local_server surface).
- **Summary:** OpenSpace's multi-host abstraction is a delegated MCP-sidecar model — the exact inverse of skill-concierge's in-place CC-hook governance; the headline portability is non-transferable and correctly so, but three sub-layer ideas (two-stage retrieval, granular env-config merge, documented precedence ladder) sharpen us while staying CC-native.
- **Top 3 transferable:** (1) **Two-stage retrieval** — over-fetch broad from Qdrant then precise-rerank to 1-2, HIGH/MED, directly serves "precise + cheap"; (2) **Granular env-var → temp-file config merge**, MED/LOW-MED, tune gates/budgets per-machine without a repo edit + deploy; (3) **Documented "higher tier blocks lower tier" precedence ladder** + doctor printing the winning source, MED/LOW.

### Unresolved / caveats
- I did not confirm skill-concierge's RETRIEVE path is currently *single*-stage (inferred from the task brief's "RETRIEVE via Qdrant+mpnet"); the two-stage recommendation assumes no existing rerank — verify before implementing.
- Idea #2's payoff depends on skill-concierge having a single config-load choke point to intercept; not verified in this study (study was read-only on OpenSpace, not skill-concierge internals).
- `llm/client.py` (910 lines) and `local_server/` platform adapters were surveyed structurally, not line-audited — they are OpenSpace's own execution plumbing (litellm client, Flask shell/gui server) with no host-abstraction novelty beyond what's captured above.
