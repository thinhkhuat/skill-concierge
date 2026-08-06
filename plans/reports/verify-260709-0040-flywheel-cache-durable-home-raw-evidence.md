# RAW EVIDENCE — Flywheel regen cache → canonical durable home (v0.18.1)

Independent verification. Verifier did NOT build this. "Correct" derived from the artifacts below,
not from the builder's claim. Every verdict sits UNDER its raw bytes.

- **Artifact under test:** `/Users/thinhkhuat/.claude/plugins/cache/skill-concierge/skill-concierge/0.18.1/` (LIVE plugin)
- **Engine venv python:** `/Users/thinhkhuat/.claude/skill-concierge/venv/bin/python3`
- **Endpoint:** LM Studio `http://localhost:4310`, model `gemma-4-12b-it-qat-optiq`
- **Real durable home:** `~/.claude/skill-concierge/` — kept READ-ONLY throughout (temp homes used for all writes)

---

## Oracle (derived from artifacts, verbatim)

CHANGELOG `[0.18.1]` (repo `CHANGELOG.md` L8-17): cache "now resolves to
`~/.claude/skill-concierge/.flywheel-cache.json` (`SKILL_CONCIERGE_HOME`) instead of `ROOT/eval/` …
a cache under the ephemeral dir went cold after every update, so the next run treated all ~530 skills
as cache-misses and regenerated the whole catalogue … `flywheel_llm.py` now owns the path
(`CACHE_FILE`), shared by both generators."

Deployed `flywheel_llm.py` L22-30 (the owning definition):
```
ROOT = Path(__file__).resolve().parent.parent
...
HOME = Path(os.environ.get("SKILL_CONCIERGE_HOME", Path.home() / ".claude" / "skill-concierge"))
CACHE_FILE = HOME / ".flywheel-cache.json"
```
Deployed `llm_triggers.py` L36 & `llm_eval_gen.py` L26: `CACHE_FILE = flywheel_llm.CACHE_FILE`.

Skip predicate — deployed `llm_triggers.py` L149:
```
if cache.get(key) == h and "llm_triggers" in triggers.get(name, {}):
    continue  # unchanged + already merged
```
So a skill is skipped only when BOTH (a) the durable-home cache hash matches the live description hash
AND (b) the triggers file already carries an `llm_triggers` layer. `key = "triggers:"+name`, `h = md5(desc)`.

Live env (`~/.claude/settings.json`): `SKILL_TRIGGERS` → repo `eval/triggers.json`
(627 entries, 535 with `llm_triggers`); `FLYWHEEL_LLM_MODEL=gemma-4-12b-it-qat-optiq`.
NOTE: deployed `ROOT/eval/triggers.json` does NOT exist — triggers live only at the `SKILL_TRIGGERS` path.

---

## CASE 1 — Path resolution (deployed), default env

Command: import the three DEPLOYED modules (sys.path = 0.18.1/scripts) and print each `CACHE_FILE`.

```
flywheel_llm.CACHE_FILE : /Users/thinhkhuat/.claude/skill-concierge/.flywheel-cache.json
llm_triggers.CACHE_FILE : /Users/thinhkhuat/.claude/skill-concierge/.flywheel-cache.json
llm_eval_gen.CACHE_FILE : /Users/thinhkhuat/.claude/skill-concierge/.flywheel-cache.json
ALL_THREE_IDENTICAL: True
UNDER_DURABLE_HOME: True (home=/Users/thinhkhuat/.claude/skill-concierge)
EXIT=0
```
**PASS** — all three identical AND under the durable home. NOT `ROOT/eval/`.

---

## CASE 2 — Env override (adversarial) + unset fallback

2a. `SKILL_CONCIERGE_HOME=<scratchpad/fake-home-XYZ>`:
```
flywheel_llm.CACHE_FILE : …/scratchpad/fake-home-XYZ/.flywheel-cache.json
llm_triggers.CACHE_FILE : …/scratchpad/fake-home-XYZ/.flywheel-cache.json
llm_eval_gen.CACHE_FILE : …/scratchpad/fake-home-XYZ/.flywheel-cache.json
FOLLOWS_OVERRIDE: True
EXIT=0
```
2b. `env -u SKILL_CONCIERGE_HOME` (UNSET):
```
SKILL_CONCIERGE_HOME in env: False
flywheel_llm.CACHE_FILE : /Users/thinhkhuat/.claude/skill-concierge/.flywheel-cache.json
FALLS_BACK_TO_DEFAULT: True
EXIT=0
```
**PASS** — override honored by all three; unset falls back to `~/.claude/skill-concierge/`.

---

## CASE 4 — Cold-vs-warm skip predicate, DRY (no LLM)

Replicated the deployed skip predicate over the LIVE skill list with REAL cache vs EMPTY cache dict.

```
live_skills count: 533
WARM cache -> WOULD GENERATE: 5 / 533
  (skipped: 528 )
  first 15 to-generate: ['skill-concierge:flywheel', 'understand-anything:understand-chat',
   'understand-anything:understand-domain', 'understand-anything:understand-explain',
   'understand-anything:understand-knowledge']
COLD (empty cache) -> WOULD GENERATE: 533 / 533
  COLD==all: True
EXIT=0
```
**PASS** — WARM (durable cache) → 5 misses (drifted/new few). COLD (the old ephemeral-dir-after-update
behavior) → 533/533 = full-catalogue regen. This is exactly the regression the fix prevents.

---

## CASE 3 — Warm-cache = skip, ISOLATED live run against the LLM

Setup: temp home `scratchpad/temphome/` seeded with a COPY of the real durable-home cache
(`.flywheel-cache.json`, 1064 entries); `SKILL_TRIGGERS` redirected to a COPY of the repo triggers.json.
Called DEPLOYED `llm_triggers.run()` directly (NOT flywheel.py — avoids a live reindex).

Pre-state:
```
REAL cache: mtime=Jul  8 23:40:19 2026 size=70532  md5=a97af9548b39bee97ab5b9a291e3e79f
TEMP cache: size=70532  entries=1064
LM Studio completions BASELINE: 0   (log 2026-07-09.1.log)
endpoint ping: (True, 'http://localhost:4310/v1/models reachable — models: gemma-4-12b-it-qat-optiq, …')
```

Run:
```
run() CACHE_FILE:    …/scratchpad/temphome/.flywheel-cache.json
run() TRIGGERS_FILE: …/scratchpad/temp-triggers.json
elapsed_s: 41.3
results (skills ACTUALLY sent to LLM this run): 5
   generated skill-concierge:flywheel - None
   generated understand-anything:understand-chat - None
   generated understand-anything:understand-domain - None
   generated understand-anything:understand-explain - None
   generated understand-anything:understand-knowledge - None
EXIT=0
LM Studio completions AFTER: 5  (delta=5)
```

Post-state / side effects:
```
REAL cache POST: mtime=Jul  8 23:40:19 2026 size=70532  md5=a97af9548b39bee97ab5b9a291e3e79f  (UNCHANGED)
TEMP cache POST: mtime=Jul  9 00:46:30 2026 size=70607  entries=1065  (committed: +1 new key, 4 drifted updated in place)
temp triggers: skill-concierge:flywheel -> has llm_triggers: True | n=8
               understand-anything:understand-chat -> has llm_triggers: True | n=9
```
**PASS** — warm cache skipped 528/533; only 5 skills hit the LLM (corroborated by LM Studio log delta=5,
one POST per generated skill, no VN retries needed). Temp cache committed (new mtime, entry+size growth);
real durable-home cache byte-identical before/after (md5 `a97af954…`, mtime frozen at Jul 8 23:40).

Note on "+1 entry" (net, not +5): 4 of the 5 were description-drift UPDATES of existing `triggers:<name>`
keys (same key, new hash → no count change); only `skill-concierge:flywheel` was a brand-new key.
Consistent — the predicate covers BOTH new and changed skills. Not a defect.

---

## CASE 5 — Bundled selftests (corroboration)

```
###### flywheel_llm --selftest ######
live_skill_names(): 533 skills (live index reachable)
PASS
EXIT=0

###### llm_triggers --selftest ######
PASS
EXIT=0     (asserts before==after on the REAL eval/triggers.json → no real-state mutation)

###### llm_eval_gen --selftest ######
WARN: skipping test:bad: only 2 positives (need >=8)
PASS
EXIT=0
```

Deployed-vs-source path logic:
```
diff (deployed flywheel_llm.py  vs  repo scripts/flywheel_llm.py, HOME/CACHE_FILE/SKILL_CONCIERGE_HOME lines)
IDENTICAL path logic deployed==source
```

---

## Overall: PASS

The shipped fix behaves exactly as the CHANGELOG claims. The regen cache resolves to the canonical
durable home (env-overridable, correct default), shared identically by all three modules; a warm cache
under that home skips the whole catalogue and regenerates only the drifted/new few (5/533 measured live,
LM-log-corroborated), whereas an empty/cold cache — the pre-fix ephemeral-dir-after-update state — would
regenerate all 533. No discrepancies. Real state untouched (real cache md5 identical pre/post; selftests
assert no real-triggers mutation).
