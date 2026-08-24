# Codex live validation — skill-concierge v0.26.2, round 3 (2026-08-24 19:04 +07)

Validator: independent Codex session (ocx harness), findings-only. Subject: the deployed Codex
plugin-cache copy of skill-concierge 0.26.2 vs repo `main @ 4e88dc2` (clean at start — 0
porcelain lines). Shared Qdrant collection `claude_skills`: 24786 points before everything,
24786 after (prompt-authoring baseline also 24786 — no intervening reindex anywhere).

Evidence grades: every verdict below is grounded in a probe run this turn (command + raw output
quoted). The D1–D4 defect *definitions* are CLAIMED BY the tasking brief / round-2 report (not
re-read this turn); only the fixes' present behavior was re-tested. MCP calls were read-only
(`health`, `search_skills`); `reindex` was never invoked; the only file written is this report.

## Check 1 — Deploy integrity — **PASS**

Exactly one cache dir, version 0.26.2, and all five engine/hook files byte-identical to the repo:

```
$ ls -d ~/.codex/plugins/cache/skill-concierge/skill-concierge/*/
/Users/thinhkhuat/.codex/plugins/cache/skill-concierge/skill-concierge/0.26.2/

$ grep '"version"' ~/.codex/plugins/cache/skill-concierge/skill-concierge/*/.codex-plugin/plugin.json
"version": "0.26.2",

$ for f in hooks/scripts/enforcer.py hooks/scripts/ledger.py hooks/hooks.json scripts/doctor.py vendor/skill-search/skill_search/server.py; do cmp -s <repo>/$f <cache>/0.26.2/$f && echo OK $f || echo DIFFERS $f; done
OK hooks/scripts/enforcer.py
OK hooks/scripts/ledger.py
OK hooks/hooks.json
OK scripts/doctor.py
OK vendor/skill-search/skill_search/server.py
```

## Check 2 — D2, borrowed-manifest freshness (ADR-0037) — **PASS**

In-session `health` MCP call (this session's own skill-search server), verbatim:

```json
{
  "status": "ok",
  "issues": [],
  "embedder": { "backend": "fastembed", "model": "sentence-transformers/paraphrase-multilingual-mpnet-base-v2", "reachable": true, "dim": 768 },
  "qdrant": { "store": "http://localhost:6333", "reachable": true, "indexed": 2541, "dim": 768 },
  "disk_skills": 2541,
  "dark_skills": [],
  "stale_points": [],
  "engine_build": { "running": "6e5bfc5347a3", "index_written_by": null },
  "indexed_at": 1787573718.2876081,
  "stale": null,
  "freshness_from": "964df33f"
}
```

All three criteria hold: status `ok` (not degraded), `indexed_at` non-null (= 2026-08-24T19:15:18
+07:00, minutes before this probe), and `freshness_from: "964df33f"` — the borrowed root key
ADR-0037's own live validation named as the real fresh manifest. `stale: null` is the ADR's
honest-unknowable, as designed.

One `search_skills` call ("debug a failing ci pipeline") returned 6 scored results (top:
`antigravity:odoo-automated-tests` 0.8898, `ak-fix` 0.8568, …). The complete reply was scanned
for `/index manifest missing/i`: **no match** — the wolf-cry is gone.

Was the in-session server old code? No — proven, not assumed. `_engine_build()`
(server.py:161) is md5 over `server.py`+`skills_discovery.py` bytes; recomputed over the
deployed 0.26.2 cache files this turn:

```
DEPLOYED_BUILD_ID 6e5bfc5347a3   == engine_build.running reported by the in-session server
```

So this session's server executes exactly the deployed 0.26.2 engine, and doctor's stale-engine
WARN (pid 59600, below) belongs to a different, older live server — another session's, per the
known list. The stdio-spawn fallback was therefore not needed.

## Check 3 — D1, enforcer selftest — **PASS**

```
$ python3 <cache>/0.26.2/hooks/scripts/enforcer.py --selftest
enforcer --selftest OK: refusal guard (5 fire / 6 silent) + ranked-mandate %-share + actionability imperative-veto (17 fire / 12 off) + keepoff-drop + gap-collapse + per-skill-tau/deterministic-routes (default-inert) + authorized-skip tier (3 injects on / silent-off) + selfref over-fire lane (6 fire / 6 off) + chain-overrides (override-wins / keep-off / suppress / fail-open) + retrieval-shape (ADR-0031 off / ADR-0032 annex on) + dynamic annex floor (ADR-0036 fixed/competitive/clamped/fallback + end-to-end prune-and-keep) + cross-harness annex (ADR-0034 filter+annex on / union off) + external annex (partition / floor / slots / render / kill-switch)
EXIT=0
```

Exit 0 (round 2: exit 1, three twin assertions), and the banner names the cross-harness case
explicitly ("cross-harness annex (ADR-0034 filter+annex on / union off)") plus the new
"dynamic annex floor (ADR-0036 …)" case.

## Check 4 — D4, doctor trigger hygiene + corpus health — **PASS**

```
$ python3 <cache>/0.26.2/scripts/doctor.py
  [✓] Engine venv         /Users/thinhkhuat/.claude/skill-concierge/venv
  [✓] Engine freshness    venv engine matches deployed source
  [!] Running engine      1 live MCP server(s) run a DIFFERENT engine build than the one on disk (6e5bfc5347a3) — pid 59600. They execute the OLD code, which shows up as a false 'disk changed since last index'. Restart Claude Code; reindexing will not fix it
  [✓] MCP wiring          launcher + .mcp.json present
  [✓] Qdrant              http://localhost:6333
  [✓] Retrieval health    2541 skills indexed; embedder + qdrant reachable (indexed 4m ago)
  [✓] Enrichment overlay  not enriched (no overlay in use)
  [✓] Multi-vector layer  22245 trigger points (+ base) of 24786 total — MAX-pooled retrieval
  [✓] Actionability gate  1480 labelled prompts in 'prompt_intent'
  [✓] Corpus health       12/14 ok · 1 weak · 1 no-signal — weak/no-signal need contrastive negatives or richer index (multi-vector), not a threshold
  [✓] Retrieval flywheel  not configured — utterance layer runs in fallback (description+body only); last run 2026-08-24T07:44:43Z: generated=46 error=2 skipped=530, coverage 543/578
  [✓] Trigger hygiene     no junk phrases stored in the utterance layer
  [✓] Settings overrides  40 on / 573 name-only
  [✓] External catalogs   antigravity: 1928 skills
  [✓] Ledger dir          /Users/thinhkhuat/.claude/skill-concierge/logs
  [✓] Duplicate MCP       single skill-search MCP
  [✓] MCP reachable       plugin:skill-concierge:skill-search connected

status: WARN
EXIT=0
```

Both D4 criteria hold: `Trigger hygiene` reads the durable home ("no junk phrases stored in the
utterance layer" — the round-2 "no triggers file / utterance layer unused" false alarm is gone)
and `Corpus health` is present with real data. The single WARN is the known case: a stale live
server (pid 59600) that is NOT this session's (build-id equality in Check 2 proves this
session's server is current) — recorded, not re-reported.

## Check 5 — D3, dormant underscore armor — **PASS**

```
$ python3 <cache>/0.26.2/hooks/scripts/ledger.py --selftest
ledger --selftest OK: get_skill/auto/search/manual classification
EXIT=0
```

Selftest OK, and the fixtures are real, not banner-deep — ledger.py:38-39 accept both spellings
and the selftest exercises the underscore forms at ledger.py:152/154:

```
38:  SEARCH_TOOLS = ("skill-search__search_skills", "skill_search__search_skills")
39:  GET_TOOLS = ("skill-search__get_skill", "skill_search__get_skill")
152:                  "tool_name": "mcp__skill_search__search_skills"})
154:                  "tool_name": "mcp__skill_search__get_skill",
```

Deployed matcher (hooks.json:54) reads exactly as specified:

```
54:        "matcher": "Skill|mcp__.*skill[-_]search__(search_skills|get_skill)",
```

As expected from the known list, Codex fires no PostToolUse, so no ledger rows from this
session's own MCP calls — the armor is verified by selftest + matcher, not by live rows.

## Check 6 — ADR-0036 dynamic annex sizing, from the Codex harness — **PASS**

Cache enforcer imported via importlib (path under `~/.codex/plugins/cache/…/0.26.2/`, which the
`/.codex/` marker itself classifies). Constants, verbatim:

```
ANNEX_DYNAMIC True
ANNEX_MARGIN 0.05
EXTERNAL_SLOTS 4
FOREIGN_SLOTS 2
UNDER_CODEX True
FOREIGN_SCOPES ('plugin',)
```

Two contrasting prompts, live embed + Qdrant, verbatim probe output:

```
PROMPT 'review this pull request for security issues'
  installed_top 0.7505 agent-skills:code-review-and-quality
  floors ext=0.7005 fgn=0.7005
  ext_width 1 [('antigravity:code-review-checklist', 0.7672)]
  fgn_width 0 []
  all_annex_ge True thresh 0.7005
  installed_menu [('agent-skills:code-review-and-quality', 0.75), ('superpowers:requesting-code-review', 0.742), ('ak-review-pr', 0.724), ('vercel:vercel-agent', 0.717), ('omo:review-work', 0.686), ('cloudflare:cloudflare', 0.68), ('ak-security-scan', 0.677), ('ak-security', 0.668)]

PROMPT 'build an odoo module with automated tests'
  installed_top 0.6732 ak-test
  floors ext=0.6232 fgn=0.6232
  ext_width 4 [('antigravity:odoo-module-developer', 0.7561), ('antigravity:odoo-automated-tests', 0.7495), ('antigravity:github-actions-templates', 0.6994), ('antigravity:odoo-upgrade-advisor', 0.6756)]
  fgn_width 0 []
  all_annex_ge True thresh 0.6232
  installed_menu [('ak-test', 0.673), ('ak-web-testing', 0.671), ('cloudflare:building-mcp-server-on-cloudflare', 0.624), ('opus-validate', 0.622), ('check-work', 0.606), ('codexclaw:qa', 0.603), ('autoresearch', 0.581), ('vercel:sign-in-with-vercel', 0.558)]
```

PASS on both criteria: widths differ with intent (external 1 → 4 as the installed inventory
thins, exactly ADR-0036's measured 1-and-cap pattern) and every annex row scores
≥ max(0.40, top−0.05) on both prompts. Corroboration from this validator's own injected turns:
the current turn's offer carried a 4-row external annex and a 2-row claude annex — varying
width, not the old constant 2.

Observation (not a defect): the foreign annex returned 0 rows on both prompts — no
Claude-plugin-scope row cleared the per-turn floor (0.7005 / 0.6232), or those that did were
invocable twins (skipped by design). ADR-0036's own validation saw foreign=2 from the Claude
direction, where the foreign pool is the Codex scopes — direction-dependent pools make this
expected variance, and the empty set is floor-compliant.

## Check 7 — Shared-index safety — **PASS**

```
before everything: 24786
after everything:  24786
```

Identical — and identical to the prompt-authoring baseline. The shared index was not touched by
this validation.

## Ranked defects

No defects found. All seven checks PASS; the two WARN-shaped observations (doctor's stale pid
59600, foreign-annex zero from the Codex direction) are the known/expected items or designed
behavior, argued above with bytes.

Status: DONE

Summary: v0.26.2 is deployed byte-identically and all four round-2 defects are verifiably fixed
in the live Codex path — D2's borrowed-manifest freshness answers with a real fresh manifest
and a silenced wolf-cry, D1/D3's selftests pass with the cross-harness and underscore cases
pinned, and D4's doctor reads the durable trigger home with corpus health present. ADR-0036's
competitive-margin annexes behave exactly as designed from this harness, varying 1→4 with
inventory strength at margin 0.05, caps 4/2, every row above the per-turn floor.

Unresolved questions: none.

grounded: git status --porcelain (0 lines, pre) · grep version · cmp ×5 · health MCP ·
search_skills MCP + warning scan · md5 build-id recompute · enforcer --selftest (exit 0) ·
doctor.py · ledger.py --selftest (exit 0) + fixture grep · hooks.json:54 grep · importlib annex
probe (2 prompts) · points_count ×2 · as of 2026-08-24T19:2x+07:00 · 1 claim grade: D1–D4
definitions CLAIMED BY tasking brief (fixes re-probed, histories not re-read)
