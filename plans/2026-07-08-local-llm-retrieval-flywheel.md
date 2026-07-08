# Local-LLM Retrieval Flywheel (#2 → #1) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Use the free, always-on local Qwen3.5-9B (LAN Ollama) to (a) generate a *dense* eval corpus so skill-concierge retrieval is finally **measurable** (#2), then (b) generate *utterance-style* trigger phrases that lift recall, proven against that corpus with no precision loss (#1).

**Architecture:** Two **offline** generator scripts call the LAN Qwen over the OpenAI-compatible endpoint and write into seams that **already exist** — `eval/scenarios/*.json` (per-skill positives/negatives, read by `precision_eval.py`) and `eval/triggers.json` (read by `enrich_index.py`). Nothing touches the hot per-turn gate; the generative model never enters the ≲300ms enforcer path. The embedding gate stays `mpnet-768`; the LLM only feeds the offline flywheel around it.

**Tech Stack:** Python 3 (stdlib `urllib` only — no new dep), the engine venv (`$HOME/.claude/skill-concierge/venv/bin/python3`), LAN Ollama `frob/qwen3.5-instruct:9b`, existing `enrich_index.py` / `precision_eval.py` / `run_eval.py`.

---

## Why #2 before #1 (do not reorder)

You cannot prove #1 helps without a way to measure. Today the eval corpus is **14 hand-authored** scenario files out of **498 skills** (`eval/scenarios/`, `precision_eval.py` gates on those 14). #2 densifies that to all 498 so recall/precision become real numbers. Then #1's triggers are proven by re-running the SAME measurement — recall must rise, true-negative precision must hold (no cannibalization). Build the ruler first, then the thing it measures.

## Ground truth (verified 2026-07-08, cite before trusting)

| Seam | Exact shape | Consumer |
|---|---|---|
| `eval/scenarios/<slug>.json` | `{"skill": "ns:name", "positive": [utterances], "negative": [near-miss utterances]}`; slug = skill name with `:`→`-`. VN + EN cases mixed. | `scripts/precision_eval.py` (`CORPUS = eval/scenarios`, `SKILL_SCENARIOS_DIR` override) |
| `vendor/skill-search/eval/labeled_queries.jsonl` | one obj/line `{"query": "...", "expect": ["skill-a"]}` | `vendor/skill-search/eval/run_eval.py` (recall@1/3/6) |
| `eval/triggers.json` | `{ name: {"source": "prose-phrase", "triggers": [...], "n": N} }`, 498 keys | `scripts/enrich_index.py` (centroids trigger embeddings into the vector) |

**LLM endpoint (from `~/.claude/settings.json` env):** `http://192.168.2.126:11434/v1/chat/completions`, model `frob/qwen3.5-instruct:9b`, header `Authorization: Bearer ollama`, body must carry `"reasoning_effort": "none"` (strips thinking on the `/v1` path). Ollama honors `"format"` for JSON output.

## Hard safety rules (inherited from `enrich_index.py` — do not violate)

1. The generators **only write JSON files** (`eval/scenarios/*`, `eval/triggers.json`). They **never** touch Qdrant. Only `enrich_index.py` writes vectors, and it does so **vector-only** (`PUT /points/vectors`, never upsert — an upsert clears the payload → skills go dark → doctor FAILs → auto-reindex reverts).
2. **Shadow before live, always.** New scenarios → a shadow dir first. Trigger enrichment → `enrich_index.py --shadow` → `precision_eval.py` → only `--live` if the gate passes. `--live` refuses without a verified Qdrant snapshot (atomic rollback).
3. **Embed parity is a HARD GATE.** Triggers are embedded via the engine path (`fastembed==0.8.0`, mpnet-768) — `enrich_index.py` re-asserts cosine=1.0 parity at runtime and aborts on drift. Don't bypass it.
4. **Never clobber the 14 gold scenarios.** They are hand-authored ground truth. Generated scenarios land in a separate dir and are promoted only after review.

## Operational constraint (live, 2026-07-08)

cognee is currently **hammering the same RTX 3080** draining its boot backlog (20rpm cap, shared GPU). A 498-skill generation run contends with it. Therefore:
- Endpoint/model/rate are **env-configurable** (`FLYWHEEL_LLM_ENDPOINT`, `FLYWHEEL_LLM_MODEL`, `--rate`), default to LAN Qwen.
- Default `--rate` conservative (e.g. 10 rpm) so the generators + cognee coexist; raise it once cognee's backlog is drained.
- **Body-hash cache** (`eval/.flywheel-cache.json`): skip regeneration for any skill whose SKILL.md body hash is unchanged, so reruns are cheap and idempotent and a mid-run interruption resumes.

---

## Task 0: Confirm interfaces + shared client helper

**Files:**
- Create: `scripts/flywheel_llm.py` (shared Qwen client + skill-list loader)
- Test: `scripts/flywheel_llm.py` `--selftest`

**Step 1 — Read the constants you depend on.** Confirm still true (they move):
```bash
cd skill-concierge
rg -n "CORPUS *=|SKILL_SCENARIOS_DIR" scripts/precision_eval.py     # -> eval/scenarios
python3 -c "import json;print(len(json.load(open('eval/triggers.json'))))"   # -> 498
python3 -c "import json;d=json.load(open('eval/scenarios/ck-ai-artist.json'));print(list(d))"  # -> ['skill','positive','negative']
```

**Step 2 — Write the failing selftest** (`flywheel_llm.py --selftest`, network-free): asserts (a) `slug("ck:ai-artist") == "ck-ai-artist"`, (b) `parse_json_reply` strips a ```json fence and returns the object, (c) `live_skill_names()` reads the live index (`claude_skills` payloads — same source `build_triggers.py` uses, NOT disk) and returns ≥ 1 name.

**Step 3 — Implement `flywheel_llm.py`** (stdlib only):
```python
import hashlib, json, os, re, time, urllib.request

ENDPOINT = os.environ.get("FLYWHEEL_LLM_ENDPOINT", "http://192.168.2.126:11434/v1/chat/completions")
MODEL    = os.environ.get("FLYWHEEL_LLM_MODEL", "frob/qwen3.5-instruct:9b")

def slug(name): return name.replace(":", "-").replace("/", "-")

def chat(system, user, rate_s=6.0, timeout=120):
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "reasoning_effort": "none",          # strips thinking on the /v1 path (handoff 2026-07-08)
        "format": "json", "temperature": 0.4,
    }).encode()
    req = urllib.request.Request(ENDPOINT, data=body,
          headers={"Authorization": "Bearer ollama", "Content-Type": "application/json"})
    for attempt in range(3):                 # 503 = Ollama queue overflow -> backoff, don't hammer
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                out = json.loads(r.read())["choices"][0]["message"]["content"]
            time.sleep(rate_s)
            return parse_json_reply(out)
        except urllib.error.HTTPError as e:
            if e.code == 503 and attempt < 2: time.sleep(5 * (attempt + 1)); continue
            raise

def parse_json_reply(s):
    s = re.sub(r"^```(?:json)?|```$", "", s.strip(), flags=re.M).strip()
    return json.loads(s)

def body_hash(text): return hashlib.md5(text.encode()).hexdigest()
# live_skill_names(): reuse the loader build_triggers.py already uses (live claude_skills payloads)
```

**Step 4 — Run selftest:** `$HOME/.claude/skill-concierge/venv/bin/python3 scripts/flywheel_llm.py --selftest` → PASS.

**Step 5 — Commit:** `feat(flywheel): shared local-Qwen client + slug/parse helpers`

---

## Task 1 (#2): Generate the dense eval corpus

**Files:**
- Create: `scripts/llm_eval_gen.py`
- Output (shadow): `eval/scenarios-shadow/<slug>.json` (SKILL_SCENARIOS_DIR points here for the baseline run)
- Test: `scripts/llm_eval_gen.py --selftest`

**Step 1 — Failing selftest:** feed a canned Qwen reply (dict with `positive`/`negative` lists) to the writer; assert the emitted file matches the gold schema exactly (`skill`, `positive`, `negative` keys; ≥8 positives, ≥3 negatives; all strings).

**Step 2 — Implement.** Per skill (name + description from the live index):
- **System prompt:** *"You generate a retrieval eval set for a developer-tool skill. Output STRICT JSON: `{positive:[...], negative:[...]}`. positive = 10-12 realistic first-person user utterances that SHOULD trigger this skill, natural phrasing, a mix of English and Vietnamese (≥2 Vietnamese). negative = 4-6 utterances that are plausibly confusable but belong to a DIFFERENT skill (near-miss, same domain). No skill names in the utterances. No markdown."*
- **User prompt:** the skill `name` + full `description` (the indexed description, which already includes `when_to_use`).
- Write `{"skill": name, "positive": [...], "negative": [...]}` to `eval/scenarios-shadow/<slug>.json`.
- Honor body-hash cache; honor `--limit N` (smoke on 10 skills first), `--only <name>`, `--rate`.

**Step 3 — Smoke run (10 skills):**
```bash
$HOME/.claude/skill-concierge/venv/bin/python3 scripts/llm_eval_gen.py --limit 10 --out eval/scenarios-shadow
```
Expected: 10 well-formed files; manually read 2 — positives sound like real users, negatives are genuinely confusable (not random). If Qwen drifts (name leakage, off-domain negatives), tighten the prompt and regenerate those 2 only.

**Step 4 — Full run** (only after the smoke reads clean; mind cognee contention — low `--rate` or wait for backlog drain):
```bash
$HOME/.claude/skill-concierge/venv/bin/python3 scripts/llm_eval_gen.py --out eval/scenarios-shadow --rate 6
```

**Step 5 — Commit:** `feat(flywheel): llm_eval_gen -> dense per-skill scenarios (shadow)`

---

## Task 2 (#2): Establish the measurement baseline

**Files:** no new code — run the existing gates against the generated corpus.

**Step 1 — Baseline precision_eval on the dense corpus** (LIVE index, pre-enrichment):
```bash
SKILL_SCENARIOS_DIR=eval/scenarios-shadow \
PYTHONPATH=vendor/skill-search SKILL_EMBED_BACKEND=fastembed \
SKILL_EMBED_MODEL=sentence-transformers/paraphrase-multilingual-mpnet-base-v2 \
$HOME/.claude/skill-concierge/venv/bin/python3 scripts/precision_eval.py | tee plans/reports/flywheel-baseline-260708.txt
```
Record: rank-1 recall, top-5 recall, clears-floor rate, and which skills fail rank-1 (the confusion table). **This is the number #1 must beat.**

**Step 2 — Build a flat `labeled_queries.jsonl`** from the shadow scenarios (positives → `{query, expect:[skill]}`) for `run_eval.py` recall@k, and record recall@1/3/6.

**Step 3 — Commit:** `test(flywheel): baseline recall/precision on dense corpus`

> **Decision gate for the human:** review the baseline. If recall is already high, #1's headroom is small — say so honestly rather than manufacturing a lift. If the generated negatives make precision look fragile, fix the corpus before touching triggers.

---

## Task 3 (#1): Generate utterance triggers

**Files:**
- Create: `scripts/llm_triggers.py`
- Modify: `eval/triggers.json` (additive — new `source` layer, prose-phrase entries untouched)
- Test: `scripts/llm_triggers.py --selftest`

**Design:** `build_triggers.py` already flags this as the planned next layer (*"Utterances (the ceiling) are layered separately later to isolate the delta"*). Add, per skill, an entry keyed the same way but tagged `"source": "llm-utterance"`, so `enrich_index.py` centroids prose-phrase **and** utterance triggers together. Keep utterance count capped (same `build_triggers.MAX_TRIGGERS` bound — `build_triggers.py:38`, default 12) so the description's vector weight stays sane. NOTE (found at integration): the merged flat `triggers` list is prose∪utterance, so total N can reach ~24 — `enrich_index.py:7` weights description `1/(N+1)`, so a doubled N ~halves description weight and confounds the recall delta with trigger-count. Task 4's gate must read the lift with this in mind; if it regresses, cap the *combined* list at MAX_TRIGGERS.

**Step 1 — Failing selftest:** assert the merge is additive (existing prose-phrase entry for a skill is preserved; a `llm-utterance` block is added), and utterance count ≤ cap.

**Step 2 — Implement.** Per skill: reuse the Task-1 positives if present (don't pay twice) OR generate 6-8 short trigger phrases via Qwen (*"short intent phrases a user might type, EN + VN, no skill names"*). Merge into `eval/triggers.json` under the skill, tagged `llm-utterance`. Honor body-hash cache.

**Step 3 — Run:**
```bash
$HOME/.claude/skill-concierge/venv/bin/python3 scripts/llm_triggers.py --rate 6
```

**Step 4 — Commit:** `feat(flywheel): llm_triggers -> utterance layer in triggers.json`

---

## Task 4 (#1): Prove the lift, gate on precision

**Step 1 — Shadow-enrich** with the new triggers:
```bash
PYTHONPATH=vendor/skill-search SKILL_EMBED_BACKEND=fastembed \
SKILL_EMBED_MODEL=sentence-transformers/paraphrase-multilingual-mpnet-base-v2 \
$HOME/.claude/skill-concierge/venv/bin/python3 scripts/enrich_index.py --shadow
```
Expected: embed-parity gate passes (cosine=1.0), shadow vectors written, no `--live`.

**Step 2 — Re-run precision_eval LIVE vs SHADOW** on the Task-1 dense corpus:
```bash
SKILL_SCENARIOS_DIR=eval/scenarios-shadow \
PYTHONPATH=vendor/skill-search SKILL_EMBED_BACKEND=fastembed \
SKILL_EMBED_MODEL=sentence-transformers/paraphrase-multilingual-mpnet-base-v2 \
$HOME/.claude/skill-concierge/venv/bin/python3 scripts/precision_eval.py | tee plans/reports/flywheel-enriched-260708.txt
```

**Step 3 — Apply the gate (all three must hold, else STOP):**
- Rank-1 / top-5 recall **rises** vs the Task-2 baseline.
- True-negative precision **does not fall** (near-miss negatives still don't steal rank-1 — no cannibalization).
- No skill goes dark (clears-floor rate not worse).

**Step 4 — Promote to live ONLY if the gate passes:**
```bash
$HOME/.claude/skill-concierge/venv/bin/python3 scripts/enrich_index.py --live   # refuses without a Qdrant snapshot
$HOME/.claude/skill-concierge/venv/bin/python3 scripts/doctor.py                # must stay status: OK
```
If the gate fails: keep triggers shadow-only, report which skills regressed, iterate the prompt. Do **not** ship a lift you can't prove.

**Step 5 — Commit:** `feat(flywheel): promote utterance enrichment to live (gated)` — only after doctor is green.

---

## Task 5: Operational hardening + docs

- **Contention guard:** document (in `docs/`) that generation runs share the RTX 3080 with cognee; default low `--rate`; the 503-backoff in `flywheel_llm.chat` absorbs Ollama queue overflow.
- **Idempotency:** confirm a second full run with an unchanged catalog does ~zero LLM calls (body-hash cache hits).
- **Refresh trigger:** note when to regenerate — a skill's description/body changed, or a new skill installed. (Future: wire into `auto_reindex.py`; out of scope now — YAGNI.)
- **Promote gold scenarios:** decide per-skill whether any generated scenarios graduate into `eval/scenarios/` (the reviewed gold set) or stay shadow. Human call.
- **Commit:** `docs(flywheel): operating notes, contention + refresh policy`

---

## Scope boundaries (YAGNI — explicitly NOT in this plan)

- **No hot-path change.** The enforcer stays embedding-only, mpnet-768. The 9B never runs per-turn.
- **No embedder swap** (mpnet-768 → bge-m3). That's a separate, higher-blast-radius track (full reindex + threshold re-tune). Not here.
- **No #3 post-hoc miss auditor** (transcript LLM-judge feedback loop). It's the follow-on once #2+#1 land and the corpus/trigger seams are proven.
- **No new runtime dependency.** stdlib `urllib` only.

## Open questions

1. **Reuse Task-1 positives as Task-3 triggers, or generate fresh short phrases?** Reuse is cheaper (one generation pass); fresh short phrases may embed better (triggers are centroided, long utterances may dilute). Recommend: reuse first, measure; only generate fresh if the gate underperforms.
2. **How many generated scenarios graduate to the gold `eval/scenarios/` set?** Affects whether future threshold tuning trusts generated or hand-authored labels. Human review call at Task 5.
3. **cognee co-tenancy:** is a low `--rate` enough, or should generation wait for a drained backlog / run against a second model on the 3080? Decide from the Task-1 smoke run's observed 503 rate.
4. **`enrich_index.py --reapply` reverts the utterance layer (landmine, found in review):** `enrich_index.py:257-260` rewrites `triggers.json[n]` to prose-only, so running `--reapply` *after* this flywheel lands silently drops every `llm_triggers` layer. Not a defect in the 3 new scripts, but Task 5 must either teach `--reapply` to preserve the layer or document "re-run `llm_triggers.py` after any `--reapply`."
