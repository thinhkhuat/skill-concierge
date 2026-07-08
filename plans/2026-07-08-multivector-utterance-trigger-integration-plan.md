# Multivector LLM-Utterance Trigger Integration — Implementation Plan (review-first)

> **Status:** PLAN ONLY — no code written yet. Awaiting operator approval of the approach + the `_trigger_phrases` diff before touching the vendored engine or the live index.

**Goal:** Land the 532 generated `llm-utterance` trigger sets into the live multivector `claude_skills` index as MAX-pooled trigger points, gated by a real precision comparison, with a clean revert.

**Why the original plan's Task 4 is dead:** `enrich_index.py` centroids triggers into one vector — a single-vector-era path. The live index is multivector (each trigger = its own point, MAX-pooled). `enrich_index.py` can't reliably find the base point and its centroid model would dilute it. Proven: `come-clean` = 13 points, 1 base @ cos 1.000 + 12 trigger points @ 0.25–0.55; the parity gate correctly aborted at cos 0.329 (a trigger point). Doctor: "not enriched (no overlay in use)" — that path was never used here.

**Key upside of doing it the multivector way:** utterances become *separate points*, never centroided into the base → the code-review's "1/(N+1) description dilution" concern **disappears entirely.**

---

## Current state (inputs, all verified present)

- `eval/scenarios-shadow/` — 532 scenario files (test corpus), 100% VN. Backup dir `scenarios-shadow-gemma`.
- `eval/triggers.json` — 624 keys; 532 have an `llm_triggers` layer (`{"source":"llm-utterance","triggers":[…]}`), prose preserved. Backup `eval/triggers.json.bak-fullrun`.
- Live index `claude_skills` @ Qdrant :6333 — multivector, 768-dim, ~3900 points, built by `vendor/skill-search/skill_search/server.py` at reindex.
- Integration point: `server.py:283 _trigger_phrases(s)`; cap `_TRIG_MAX` = env `TRIGGERS_MAX` (default 12); toggle precedent `SKILL_BODY_TRIGGERS`.

## Decisions needed from operator (before coding)

1. **OK to modify the vendored engine** `vendor/skill-search/skill_search/server.py`? It "MIRRORS scripts/build_triggers.py, kept in sync by hand" (see VENDORED.md) — the change must be mirrored + deployed to the engine venv, then reindex.
2. **Cap allocation** — utterances are higher-quality than the auto-split desc/body phrases, but the current order (desc → body → …) would give utterances the *leftover* slots. Options:
   - (a) **Utterances FIRST**, then desc, then body, keep cap 12 — best phrases win the slots, index size unchanged. *(recommended)*
   - (b) **Raise the cap** (`TRIGGERS_MAX=16`) so utterances add without evicting — more recall signal, ~+point count.
   - (c) Blend (a)+(b): utterances first + modest cap raise. Let the gate pick.
3. **Reindex scope** — full `claude_skills` rebuild into a shadow collection is the mechanism; confirm that's acceptable (the live index is untouched until promote).

---

## Task 1: Add the llm-utterance source to `_trigger_phrases` (behind a toggle)

**Files:**
- Modify: `vendor/skill-search/skill_search/server.py` (`_trigger_phrases`, + a loader + a toggle)
- Mirror note: `scripts/build_triggers.py` (kept in sync by hand per VENDORED.md — update its `_trigger_phrases` equivalent OR document the intentional divergence)

**Step 1 — toggle + loader (new, near the other `SKILL_*` flags):**
```python
SKILL_LLM_TRIGGERS = os.environ.get("SKILL_LLM_TRIGGERS", "0") != "0"  # default OFF = byte-identical today
_LLM_TRIG_PATH = os.environ.get("SKILL_TRIGGERS", str(Path(__file__)... / "eval" / "triggers.json"))
_LLM_TRIG_CACHE = None
def _llm_utterance_phrases(name: str) -> list:
    """llm-utterance trigger phrases for `name` from eval/triggers.json (cached). [] if absent."""
    global _LLM_TRIG_CACHE
    if _LLM_TRIG_CACHE is None:
        try:
            d = json.loads(Path(_LLM_TRIG_PATH).read_text(encoding="utf-8"))
            _LLM_TRIG_CACHE = {k: (v.get("llm_triggers") or {}).get("triggers", []) for k, v in d.items() if isinstance(v, dict)}
        except Exception:
            _LLM_TRIG_CACHE = {}
    return _LLM_TRIG_CACHE.get(name, [])
```

**Step 2 — extend `_trigger_phrases`** (order per decision #2; showing option (a) — utterances first):
```python
def _trigger_phrases(s: dict) -> list:
    phrases, seen = [], set()
    def _add(src):
        for p in src:
            if p.lower() not in seen:
                seen.add(p.lower()); phrases.append(p)
    if SKILL_LLM_TRIGGERS:
        _add(_llm_utterance_phrases(s["name"]))     # highest-quality first
    _add(_split_phrases(s["description"]))
    if SKILL_BODY_TRIGGERS:
        _add(_split_phrases("\n".join(s.get("body_triggers") or [])))
    return phrases[:_TRIG_MAX]
```

**Step 3 — selftest (no network, no index):** feed a stub skill + a temp triggers.json; assert with `SKILL_LLM_TRIGGERS=1` the utterances appear first and the list is capped at `_TRIG_MAX`; with the flag off, output is byte-identical to today.

**Step 4 — commit** (conventional, no AI attribution).

## Task 2: Reindex into a SHADOW collection (live untouched)

**Step 1** — deploy the engine change to the engine venv (the venv runs the *deployed* engine, not the repo working copy — confirm the deploy path via `doctor.py`'s "engine freshness" check; likely a sync/reinstall step).
**Step 2** — reindex into a shadow collection, flag ON:
```bash
SKILL_COLLECTION=claude_skills_shadow SKILL_LLM_TRIGGERS=1 TRIGGERS_MAX=<12|16> \
  <engine-venv>/python -c "from skill_search import server; print(server.reindex(force=True))"
```
**Step 3** — sanity: shadow point count > live (utterance points added), base points still 1/skill @ cos 1.0.

## Task 3: Real precision gate (shadow vs live)

**Step 1** — verify `precision_eval.py` works comparing two *multivector* collections (it was written for the enrich single-vector shadow — it may need `SKILL_SHADOW_COLLECTION` wiring or a small adaptation; confirm before trusting numbers).
**Step 2** — run on the 532-scenario corpus:
```bash
SKILL_SCENARIOS_DIR=eval/scenarios-shadow <engine-env> precision_eval.py | tee plans/reports/utterance-gate-260708.txt
```
**Step 3 — gate (all must hold):** rank-1/top-5 recall **rises** vs live; true-negative precision **holds** (no cannibalization); no skill drops below floor. Record numbers.

## Task 4: Promote to live — ONLY on a passing gate + operator OK

**Step 1** — snapshot `claude_skills` (rollback point).
**Step 2** — promote (swap shadow→live, or reindex live with the flag on).
**Step 3** — `doctor.py` must stay `status: OK` (skills indexed, multivector layer healthy).
**Rollback:** restore the snapshot / reindex with `SKILL_LLM_TRIGGERS=0`.

---

## Risks / open questions

1. **Vendored-code sync** — `server._trigger_phrases` and `scripts/build_triggers.py` are hand-mirrored. This change intentionally makes the engine read an external file; decide whether build_triggers mirrors it or is documented as divergent.
2. **Engine deploy mechanism** — the running MCP uses the *deployed* engine venv; the repo edit must reach it (setup/sync). Exact step to confirm before reindex.
3. **`precision_eval` multivector fitness** — verify it compares two multivector collections correctly before trusting the gate (Task 3 Step 1).
4. **Cap tuning** — 12 vs 16 is a recall/precision/index-size tradeoff; the gate at both settings decides.
5. **`TRIGGERS_MAX` / `SKILL_LLM_TRIGGERS` durability** — if kept ON, wire into `settings.json`/engine env so reindexes stay consistent.

## Data already banked (reusable regardless of route)

532 scenarios + 532 utterance-trigger sets, 100% VN, quality-verified. Independent of this integration — if the approach changes, the generated data still stands.
