# OpenSpace Study B — Self-Evolution, Experience-Sharing & Recording

**Date:** 2026-07-04 · **Mode:** READ-ONLY innovation study · **Target:** `/Users/thinhkhuat/LANDING_ZONE/OpenSpace` (HKUDS/OpenSpace, v0.1.0)
**For:** skill-concierge (RETRIEVE + ENFORCE + LEDGER) · **Cluster:** self-evolving skills, agents experience sharing, recording

---

## Bottom line up front

OpenSpace's real, verifiable innovation is a **closed local feedback loop**: every task is recorded, an LLM analyzer judges whether each offered skill *actually helped*, those judgments update four per-skill quality rates in SQLite, and three triggers turn bad rates into an LLM-driven rewrite of the skill itself. This loop is genuinely wired end-to-end — I traced it in code and confirmed it ran (the shipped benchmark DB holds 226 skills across generations 0–3, with real FIX/DERIVED/CAPTURED lineage).

The two headline marketing claims are **overstated**. "Agents Experience Sharing / collective intelligence at scale" is in fact a manual, npm-style pull registry that ships the full skill folder — and it deliberately does **not** share the usage/quality signal that would make a network effect real. "Safety checks flag prompt injection and credential exfiltration" is a seven-line regex list where only **one** hardcoded string actually blocks anything.

For skill-concierge, the transferable gold is **the loop, not the sharing**. Our ledger records offers/takes/dodges and then dead-ends at allowlist curation. OpenSpace shows the missing half: judge effectiveness, store it as a rate, and let a threshold trigger an improvement to the thing that drives retrieval — in our case, the skill's **description / trigger points**, not the skill body. That converts our dead-end ledger into a feedback loop without adopting OpenSpace's risky auto-generation of new skills (which the same DB shows produces sprawl: 226 skills but only 132 total selections, and duplicate-named families like `document-gen-fallback-enhanced-enhanced-<hash>`).

---

## How a skill "self-evolves" in OpenSpace (the verified mechanism)

**1. Every run is recorded to a per-task directory** (`recording/recorder.py`, `manager.py`). Written under `./logs/recordings/<task_id>_<ts>/`:
- `traj.jsonl` — one line per tool call: `step, backend, tool, command, parameters, result, screenshot` (`recorder.py:100-137`).
- `conversations.jsonl` — the LLM dialogue; the **primary analysis source** (`analyzer.py:350`).
- `metadata.json` — includes `skill_selection` (which skills were offered, the selection prompt/response, which were selected — `manager.py:144-166`) and `execution_outcome` (`manager.py:556-576`).

**2. A post-execution LLM analyzer judges effectiveness** (`analyzer.py`). It reads the recording and emits, per skill, a `skill_applied` boolean plus typed `evolution_suggestions`, then calls `record_analysis()` (`analyzer.py:218`). "Applied" is category-specific: a WORKFLOW skill counts as applied only if its steps were followed; a TOOL_GUIDE only if the tool was used; a REFERENCE only if it influenced decisions (`types.py:171-174`).

**3. Judgments become four per-skill quality rates, updated atomically in SQL** (`store.py:572-595`, `types.py:380-398`):
- `applied_rate = applied / selections` — was an offered skill actually used?
- `completion_rate = completions / applied` — when used, did the task complete?
- `effective_rate = completions / selections` — end-to-end: offered → used → completed.
- `fallback_rate = fallbacks / selections` — offered but unusable (the degradation signal).

**4. Three independent triggers turn bad rates into an evolution** (`evolver.py:8-11`), each running an LLM agent loop that produces a minimal diff:
- **Trigger 1 · Post-analysis** — immediately after every task, any skill flagged `candidate_for_evolution` is evolved (`tool_layer.py:818-838`).
- **Trigger 2 · Tool degradation** — when a tool's success rate drops, every skill depending on that tool is found and FIXed (`tool_layer.py:896`).
- **Trigger 3 · Metric monitor** — every 5 executions, `_diagnose_skill_health` maps stored rates directly to an action (`evolver.py:1564`, thresholds `evolver.py:105-109`): `fallback_rate > 0.40` → **FIX**; `applied_rate > 0.40 AND completion_rate < 0.35` → **FIX**; `effective_rate < 0.55 AND applied_rate > 0.25` → **DERIVED**.

**5. The evolution itself is an evidence-gathering agent loop, not blind generation** (`evolver.py:1084-1183`). Up to 5 iterations with tools enabled (`read_file`, `web_search`, `shell`) so the LLM can explore the codebase and find the root cause; the final iteration disables tools and forces a decision terminated by an explicit `EVOLUTION_COMPLETE`/`EVOLUTION_FAILED` token. Apply-retry runs up to 3× (`evolver.py:102-103`). Result is a new node in a version DAG:
- **FIX** — same name/path, new `skill_id`, parent deactivated, old content kept in `content_snapshot` (`store.py:602-637`).
- **DERIVED** — new name + directory, parent stays active, `generation = max(parents)+1`.
- **CAPTURED** — brand-new skill from a successful run, no parent, generation 0.

**Anti-loop guard is data-gated, not time-gated:** a freshly evolved skill starts at `total_selections = 0`, so it must accrue new runs before Trigger 3 can reconsider it (`evolver.py:445-450`); processed candidates are marked `evolution_processed_at` so they're not re-evolved (`store.py:829-853`).

**This loop is real and it ran.** Querying the shipped benchmark DB (`gdpval_bench/.openspace/openspace.db`):

| origin | count | | generation | count |
|---|---|---|---|---|
| captured | 141 | | 0 | 159 |
| derived | 45 | | 1 | 37 |
| fixed | 22 | | 2 | 23 |
| imported | 18 | | 3 | 7 |

The `document-gen-fallback` family really did iterate (`imported → -enhanced → -enhanced-merged → -enhanced-enhanced-<hash>…`). So the README's "13 versions" is directionally true. **But the same query exposes the failure mode:** 226 skills against only **132 total selections** and **45 completions** — most auto-captured skills were **never selected again**, and DERIVED evolution spawns near-duplicate names. Auto-generation buys evolution at the cost of sprawl.

---

## Experience sharing — claim vs. mechanism (HYPE CHECK)

The README sells "One agent learns, all agents benefit — collective intelligence at scale" and "network effects: more agents → richer data → faster evolution" (`README.md:73-77`). The shipped code is a **manual pull registry**:

- **Full skill folder crosses the wire, not experience.** Upload stages every file in the skill dir and POSTs a zip (`cloud/client.py:433-439`, `195-231`); download extracts the tree (`client.py:454-475`). No recordings, no telemetry — the payload is a versioned package (`client.py:330-347`).
- **No automatic propagation.** Sharing requires an explicit `openspace-upload-skill` CLI/tool call (a manual decision per `host_skills/delegate-task/SKILL.md:118-126`) and a cloud API key or it no-ops. Other agents benefit only when they *later* run a search whose `auto_import` pulls at most **3** public hits (`mcp_server.py:687-695`). No push, no subscription, no watch, no polling anywhere in the code.
- **The signal that would drive a network effect is never shared.** The quality rates (`applied_rate`, `effective_rate`, …) are computed from a machine-local store for local ranking only and are **absent from the upload payload** (`search.py:281-296` vs `client.py:331-347`). The cloud aggregates artifacts, lineage, and diffs — not cross-agent success rates. The advertised flywheel does not close in this repo.
- **"Team-only" is marketed but not shipped:** the client collapses `group_only → private` and offers only `public|private` (`client.py:104-109`, `cli/upload_skill.py:26`).
- **Lineage & diffs ARE shared** (`parent_skill_ids`, `origin`, `content_diff` in the payload; server validates DAG shape at `client.py:494-501`) — genuinely useful, but that's package metadata, not collective learning.

**Verdict:** it behaves like PyPI/npm for skills. Legitimate and useful, but it is a manual registry with a small auto-pull convenience — not automatic, real-time collective intelligence.

**Safety hype:** README says evolution flags "prompt injection, credential exfiltration." Reality is `skill_utils.py:23-50` — seven regexes, of which only `blocked.malware` (matching the literal string `ClawdAuthenticatorTool`) actually rejects; everything else (`api_key`, `token`, `webhook`, …) is informational and non-blocking. There is **no prompt-injection detection at all**. Do not treat this as a model.

---

## Transferable ideas for skill-concierge (ranked by impact)

Context reminder: our ledger records `turn / manual / auto / search / offer` events and `analyze.py` computes uptake, dodge, and per-skill offer→take to curate a static always-on allowlist. Skills are hand-authored and static; **the ledger never improves a skill.** OpenSpace shows the missing half of the loop.

### 1. Close the loop: ledger metric → skill *description* rewrite (HIGH impact, MED effort)

**Innovation.** OpenSpace's Trigger 3 maps a computed quality rate to a concrete evolution action (`evolver.py:1564`, `_diagnose_skill_health`), and the evolution edits the skill itself.

**Our analog.** We already compute the equivalent of their `applied_rate`: per-skill **offer→take** in `scripts/analyze.py`. Today that number only nudges an allowlist. The transfer: when a skill is **repeatedly offered by RETRIEVE but rarely taken** (low offer→take) — or repeatedly **dodged** on turns where it was the top retrieval hit — that is a precise signal that the skill's **`description` / trigger points are miscalibrated** (retrieval matched, the agent disagreed). Fire a review that rewrites the *description frontmatter*, not the skill body. This is OpenSpace's FIX, retargeted at the one surface that actually drives our retrieval and enforcement.

**Why it meaningfully improves us.** This is the direct answer to "turn the dead-end ledger into a feedback loop." skill-concierge's entire precision depends on description quality, and nothing in the system currently improves descriptions from real usage. A skill that keeps getting offered-and-refused is silently poisoning retrieval for everyone; right now we'd only catch it by a human reading `analyze.py`. Note this stays safely inside our design: we FIX metadata of an existing hand-authored skill — we do **not** auto-generate new skills.

**Concrete application.** Extend `scripts/analyze.py` (or a new `scripts/skill_health.py`) to emit, per skill: offer count, offer→take, and top-hit dodge count over a window. Apply OpenSpace-style thresholds (start conservative, e.g. offers ≥ 10 AND offer→take < 0.25 → flag "description-review"). Output a ranked candidate list to `plans/reports/`. A human (or a scoped skill-editing subagent) then rewrites that skill's `description`. Re-window the ledger before/after (`analyze.py --since/--until` already supports this) to confirm offer→take rose. Store the old description + the metric that triggered the change so a bad rewrite can be reverted — a lightweight version record, borrowing OpenSpace's `content_snapshot` idea (`store.py`) without a full DAG.

### 2. Add an "actually helped?" effectiveness judgment (HIGH impact, MED effort)

**Innovation.** OpenSpace's analyzer separates *offered* from *applied* from *completed* via an LLM post-run judgment of `skill_applied` (`analyzer.py:864-875`, `types.py:171-174`), giving a true `effective_rate` instead of a raw take-count.

**Our analog & why it matters.** Our own `skill-usage-audit` skill already warns that **offer→take is not usage** — a take just means the Skill tool was invoked, not that it helped. OpenSpace has the exact instrument we're missing: a cheap post-turn LLM pass that reads the transcript and judges whether the taken skill actually shaped the outcome. That upgrades our headline metric from "take rate" (gameable, shallow) to "effective rate" (what we actually care about), and it feeds idea #1 with a far cleaner trigger signal.

**Concrete application.** A `Stop`/`SubagentStop`-hook (or an offline batch over recent sessions) runs one small-model call per skill-taken turn: "did skill X materially contribute to satisfying the user's request? applied / not-applied / harmful." Append the verdict to the ledger as a new `effect` event (additive-only, fail-silent — same contract as `ledger.py:13-16`). `analyze.py` then reports effective-rate alongside offer→take. Keep it cheap and off the hot path; this is telemetry, not a gate.

### 3. Rate→action thresholds as an explicit, tunable policy (MED impact, LOW effort)

**Innovation.** OpenSpace externalizes its evolution policy as named constants (`evolver.py:105-110`) and a single mapping function, so "when does a skill need attention" is one auditable place, not scattered judgment.

**Our analog.** Codify skill-concierge's own promote/demote/description-review thresholds as a small config block (we already have curated budget overrides and governance flags per `CLAUDE.md`). This makes the allowlist-curation and the new description-review trigger reproducible and A/B-testable rather than hand-eyeballed. Low effort, and it makes ideas #1–#2 operational instead of ad-hoc.

### 4. Version-snapshot descriptions before rewriting (MED impact, LOW effort)

**Innovation.** Every OpenSpace evolution preserves the predecessor (`content_snapshot`, FIX deactivates-not-deletes — `store.py:602-637`) so a regression is reversible and lineage is auditable.

**Our analog.** When idea #1 rewrites a description, snapshot the prior text + the triggering metric. We don't need OpenSpace's full DAG — a JSONL append (old description, new description, trigger metric, timestamp) is enough to revert a rewrite that *lowered* offer→take. Cheap insurance for an automated edit to a retrieval-critical field.

### Explicitly NOT recommended

- **Cloud experience sharing (LOW / anti-goal).** Our ledger is deliberately private and single-machine by mission. OpenSpace's "sharing" is a manual package registry that doesn't even share the quality signal — there is nothing here worth importing, and adopting it would violate our privacy posture for no mechanistic gain.
- **CAPTURED-style auto-generation of new skills (LOW / cautionary).** The benchmark DB is the counter-evidence: auto-capture produced 226 skills with ~132 selections and duplicate-named families. Our skills are hand-authored on purpose; auto-generation would import exactly the sprawl OpenSpace suffers. If ever revisited, gate hard on a reuse metric before a captured skill is allowed to persist.
- **Their safety regex.** Weak (one real blocking rule, no injection detection). Not a model.

---

## Unresolved / honest caveats

- The `open-space.cloud` **server** is a black box; whether the backend aggregates cross-agent signals cannot be verified from this repo. All sharing findings are about the shipped **client**.
- The analyzer's exact LLM prompt that sets `skill_applied` / `candidate_for_evolution` was inferred from its inputs and sink, not read line-by-line — the mechanism (recording → judgment → `record_analysis` → metric update) is confirmed; the prompt wording is not quoted.
- GDPVal's "4.2× income / 46% fewer tokens" headline was not independently reproduced; my evidence for the loop working is the lineage/generation structure in the shipped DBs, which is strong but is not the benchmark result itself.

---

**Status:** DONE
**Summary:** OpenSpace's real innovation is a closed local loop (record → LLM effectiveness judgment → per-skill quality rates → threshold-triggered self-rewrite), confirmed in code and in the shipped DB; its "experience sharing" and "safety" headlines are hype (manual pull registry that omits the quality signal; a 1-rule regex). The loop — not the sharing — is what skill-concierge should borrow.
**Top 3 transferable ideas:** (1) Close our ledger loop by mapping low offer→take / top-hit dodge into an automated *description/trigger-point* rewrite of the offending skill (their FIX, retargeted at metadata). (2) Add an LLM "did the taken skill actually help?" post-turn judgment to replace shallow take-rate with a true effective-rate (answers our own skill-usage-audit critique). (3) Externalize rate→action thresholds as a tunable, snapshot-backed policy so both allowlist curation and description-review are reproducible and reversible.
