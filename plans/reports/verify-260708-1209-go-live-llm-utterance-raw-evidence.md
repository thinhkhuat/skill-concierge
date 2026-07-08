# Verify-as-claimed — skill-concierge v0.16.0 "LLM-utterance trigger layer" go-live

**Verifier:** independent (did not build this). **When:** 2026-07-08 ~12:09–12:15.
**Verdict: NO-GO.** The engine code and config flags are deployed correctly, and the
utterance DATA + LOADER work — but the **live index does NOT contain the utterance layer**.
It is the ADR-0016 baseline (body+desc, cap 12), not the ADR-0026 utterance build.
**Root cause (real defect):** the auto-reindex SessionStart hook — the process that WRITES
the index — does not forward `SKILL_LLM_TRIGGERS` / `TRIGGERS_MAX` from `.mcp.json`, so it
rebuilds at baseline and prunes the utterance points.

---

## Oracle (derived from the artifacts, not from the task summary)

From `docs/adr/0026`, `CHANGELOG [0.16.0]`, `VENDORED.md v0.16.0`:
- `_trigger_phrases` layers 3 sources in QUALITY order — **utterances FIRST**, then description,
  then body — deduped, capped COMBINED at `_TRIG_MAX`.
- Live deploy: `SKILL_LLM_TRIGGERS=1`, `TRIGGERS_MAX=16` (utterances add slots, not evict).
- **Author's own shadow at the SAME config (flag=1, cap=16): 532 base points, `7080 total`.**
  A correctly-built live index should be ≈7080. Baseline (ADR-0016, cap 12) ≈ 3570; the pre-utterance
  doctor figure ≈ 3916 triggers.
- Loader reads `eval/triggers.json` → each skill's `llm_triggers.triggers` block; `[]` if absent.
- Deploy requires re-copy into stable venv **+ a reindex WITH the flag on**.

**Falsifiable test:** a skill whose live-env `_trigger_phrases` yields > 12 phrases but whose
Qdrant trigger-point count is 12 = the index was built WITHOUT the flag = utterances DID NOT land.

---

## Check 1 — deployed == source  → PASS (code) / cache path note

```
venv server.py: /Users/thinhkhuat/.claude/skill-concierge/venv/lib/python3.12/site-packages/skill_search/server.py
diff venv vs vendor/skill-search/skill_search/server.py   -> diff_exit=0   (identical)
diff cache 0.16.0/vendor/.../server.py vs vendored          -> diff_exit=0   (identical)
```
Cache is version-pinned: `.../cache/skill-concierge/skill-concierge/0.16.0/…` (the task's bare
`.../skill-concierge/skill-concierge/vendor/...` path does not exist — it lives under the `0.16.0/`
version dir). The 0.16.0 cache server.py matches source.

**doctor.py raw (exit 0):**
```
  [✓] Engine freshness    venv engine matches deployed source
  [✓] Qdrant              http://localhost:6333
  [✓] Retrieval health    532 skills indexed; embedder + qdrant reachable (indexed 20m ago)
  [✓] Multi-vector layer  3916 trigger points (+ base) of 4448 total — MAX-pooled retrieval
  [✓] Actionability gate  962 labelled prompts in 'prompt_intent'
  [✓] Settings overrides  32 on / 500 name-only
status: OK
```
Note: doctor says `status: OK` and "3916 trigger points … 4448 total". Doctor has **no oracle for
the utterance layer** — 3916/4448 is exactly the pre-utterance baseline, and doctor green-lights it.
The green doctor is **not** evidence the utterance layer landed.

## Check 2 — config active  → PASS for the QUERY server, FAIL for the WRITE path

repo `.mcp.json` env (and identical `0.16.0/.mcp.json` in cache):
```
"SKILL_LLM_TRIGGERS": "1",
"TRIGGERS_MAX": "16",
"SKILL_EMBED_MODEL": "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
"SKILL_QDRANT_URL": "http://localhost:6333"
```
`~/.claude/settings.json` env — grep for the three keys:
```
76:  "SKILL_TRIGGERS": "/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/eval/triggers.json"
(NO SKILL_LLM_TRIGGERS, NO TRIGGERS_MAX in settings.json)
```
`SKILL_TRIGGERS` target exists:
```
-rw-r--r-- 1 thinhkhuat staff 750995 Jul  8 05:56 eval/triggers.json
```
So the persistent MCP **query** server gets the flags (from `.mcp.json`). But `.mcp.json` env is
ONLY injected into the MCP server process — **not** into the SessionStart reindex hook. See Check 4.

## Check 3 — live index rebuilt WITH utterances  → FAIL (utterances absent)

Qdrant `claude_skills`:
```
points_count: 4448
kind tally (full scroll of all 4448): {'base': 532, 'trigger': 3916}
```
- Live: **4448 total / 3916 trigger**.  ADR-0026 utterance shadow (flag=1, cap=16): **7080**.
  Shortfall ≈ 2632 points. Live matches the **baseline**, not the utterance build.

Per-skill proof, `come-clean`:
```
come-clean points in index: 13  → kind tally {'base': 1, 'trigger': 12}
```
- Live come-clean = **12 trigger points** → the OLD cap-12 ceiling.

`eval/triggers.json` DATA + LOADER are correct (not the problem):
```
come-clean value keys: ['source', 'triggers', 'n', 'prose_triggers', 'llm_triggers']
llm_triggers.triggers: ["Agent is dodging the rules", "Tôi phát hiện vi phạm quy tắc",
  "Force an honest self-correction", "Agent is being evasive again",
  "Hãy tự kiểm tra xem có sai không", "Stop the rule-dodging now"]

# server loader under LIVE env (flag=1, cap=16):
_llm_utterance_phrases('come-clean') -> 6 phrases (the six above)
_trigger_phrases(come-clean)         -> 16 phrases  (utterances FIRST, then desc/body, capped 16)
```
**Falsifiable test triggers:** live-env `_trigger_phrases` = **16**, but Qdrant holds **12**.
16 ≠ 12 → the live index was built with the flag OFF at cap 12. **Utterances DID NOT land.**

## Check 4 — auto_reindex clobber  → CONFIRMED (this is the root cause)

`hooks/scripts/auto_reindex.py` builds the reindex subprocess env via `_mcp_env()`:
```python
merged = dict(os.environ)
for k in ("SKILL_QDRANT_URL", "SKILL_EMBED_BACKEND", "SKILL_EMBED_MODEL"):
    if k in env and k not in os.environ:
        merged[k] = env[k]
...
subprocess.Popen([str(SS_BIN), "--reindex"], env=env, ...)
```
The `.mcp.json` merge whitelist is **only** the 3 embedder/store keys. `SKILL_LLM_TRIGGERS` and
`TRIGGERS_MAX` are **not forwarded**, and settings.json env doesn't carry them either → the reindex
subprocess runs with the engine defaults `SKILL_LLM_TRIGGERS="0"` (OFF) and `TRIGGERS_MAX="12"`.
So every auto-reindex that actually fires rebuilds the index at **baseline** and deletes utterance points.

auto-reindex.log — results mapped to session headers:
```
08:27:00 -> {"points":3900,"embedded":0,"deleted":0,"skipped":3900}   (skipped, sig unchanged)
08:58:30 -> {"points":3900,"embedded":0,"deleted":0,"skipped":3900}
09:29:39 -> {"points":3900,"embedded":0,"deleted":0,"skipped":3900}
10:03:23 -> {"points":3900,"embedded":0,"deleted":0,"skipped":3900}
11:16:51 -> {"points":3900,"embedded":0,"deleted":0,"skipped":3900}
11:48:36 -> {"points":3900,"embedded":3464,"deleted":2632,"skipped":436}   <-- REAL REBUILD
```
The 11:48:36 run rebuilt for real: **`deleted: 2632`** = 7080 (prior utterance build) − 4448
(current baseline) exactly — it pruned the utterance points and wrote 3900 baseline triggers.
This is the last write; doctor's "indexed 20m ago" (≈11:48 from 12:09) matches. The user's ~12:08
restart hit the 1800s throttle (stamp from 11:48) and did not re-run — and would not have fixed it
anyway (same missing-flag bug).

## Check 5 — behavioral proof (grouped MAX-pool, top-5, live index)

```
Q: "caught the agent weaseling around my rules again"
   1. come-clean 0.8479   2. google-agents-cli-workflow 0.5797  ...
Q: "tôi phát hiện agent đang lách luật, bắt nó tự sửa đi"  (VN)
   1. come-clean 0.7670   2. google-agents-cli-workflow 0.5907  ...
Q: "chạy demo giúp tôi cái này với"  (VN casual)
   1. prototype 0.5916    2. ck:show-off 0.59  (no clean demo/run skill; weak)
Q: "help me onboard onto this unfamiliar codebase"
   1. codebase-onboarding 0.6984   2. zread 0.6371  ...
```
Retrieval is **functional** — the right skill surfaces rank-1 for the strong queries. But this does
NOT demonstrate the utterance layer: come-clean's ranking is carried by its description prose (which
already contains "weaseling around rules"), and the VN score (0.767) comes from the multilingual base
vector, not a landed utterance point. The behavioral test cannot show the claimed uplift because the
utterance points are absent from the index (Checks 3–4).

---

## Discrepancy classification
- **REAL DEFECT** — utterance layer absent from live index (Check 3); auto_reindex env whitelist omits
  the two trigger flags (Check 4). The layer is not merely missing, it is **unstable by design**: any
  auto-reindex that fires reverts it to baseline. Deploying the flag only in `.mcp.json` configures the
  reader, never the writer.
- **Not a fixture artifact** — the `claude_skills_shadow` collection was ignored; all counts are the
  live `claude_skills`. Data file and loader are correct, isolating the fault to the write path.

## Fix direction (for the builder, not applied here)
Add `SKILL_LLM_TRIGGERS` and `TRIGGERS_MAX` to the `_mcp_env()` whitelist in `auto_reindex.py`
(and confirm the go-live reindex ran with them), then reindex — expect ≈7080 points and come-clean at
16 trigger points.

---

## POST-FIX RE-VERIFICATION (12:31) — VERDICT: GO

Root cause (indexer never received the flags — `auto_reindex._mcp_env` 3-key whitelist) fixed two ways:
- `~/.claude/settings.json` env now carries `SKILL_LLM_TRIGGERS=1`, `TRIGGERS_MAX=16`, `SKILL_TRIGGERS` → reaches the indexer via `merged = dict(os.environ)` (durable, survives plugin updates).
- `hooks/scripts/auto_reindex.py` whitelist widened to forward the trigger keys from `.mcp.json` (commit `600093b`, pushed) — unit-verified it now forwards `SKILL_LLM_TRIGGERS=1`+`TRIGGERS_MAX=16`.

Then a deterministic `skill-search --rebuild` with the flags. Raw bytes:

- rebuild result: `{"indexed":532,"points":7080,"embedded":7080,"deleted":0,"skipped":0}`
- live `claude_skills`: `points_count 7080` · kind tally `{base:532, trigger:6548}` (matches the ADR-0026 shadow exactly)
- per-skill trigger points: come-clean **16**, supabase **13**, git-commit **9**, deep-research **14** (was 12/6/3/8 at old cap-12/no-utterances)
- behavioral (live grouped MAX-pool):
  - EN "caught the agent weaseling around my rules" → come-clean #1 `0.8451`
  - VN "phát hiện agent lách luật, bắt nó tự sửa" → come-clean #1 `0.6456` (VN utterance surfaces the right skill first)
  - EN "onboard me onto this unfamiliar codebase" → codebase-onboarding #1 `0.7720`
  - VN "giúp tôi dựng bản demo nhanh cái app này" → app-builder #3 `0.6833` (ambiguous; prototype not top-5 — reasonable hit, not a clean win)

| Check | Before fix | After fix |
|---|---|---|
| index shape | 4448 pts, come-clean 12, no utterances | **7080 pts, come-clean 16, utterances first** |
| indexer gets flags | NO (whitelist dropped them) | **YES (settings.json os.environ + widened whitelist)** |
| stable across reindex | NO (auto_reindex pruned them) | **YES (flags now in os.environ + whitelist)** |

Residual: durability across a full `/plugin update` needs the pushed `auto_reindex.py` + `.mcp.json` to reach the cache; `settings.json` env covers the interim regardless. `SKILL_TRIGGERS` path is machine-local (gitignored 733K data) — absent elsewhere → graceful degrade, no crash.
