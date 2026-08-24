# Codex live re-validation — skill-concierge v0.25.2 (ADR-0035 wiring)

**Date:** 2026-08-24 18:2x ICT · **Harness:** Codex CLI 0.149.1 (session `01a0336a-3adb-7771-bef5-9e34e95b7516`)
**Repo:** `main @ 6f3d47c` (= v0.25.2), tree clean before and after; only write in this pass is this report.
**Prior pass:** `plans/reports/codex-validation-260824-dual-harness-v0251.md` — retrieval organ marked FAIL, driven over raw stdio instead.

## Check 1 — Versions + integrity — **PASS**

```
$ grep '"version"' ~/.codex/plugins/cache/skill-concierge/skill-concierge/*/.codex-plugin/plugin.json
  "version": "0.25.2",
# cache holds exactly one version dir: 0.25.2
OK hooks/scripts/enforcer.py
OK scripts/doctor.py
OK .codex-plugin/mcp.json
```

The ADR-0035 fix is live in the wiring: `codex mcp get skill-search` now shows
`command: ./bin/skill-search-mcp` with `cwd: /Users/.../0.25.2/.` — relative, no unexpanded variable.

## Check 2 — In-session tool surface — **PASS** (the leg the first pass failed)

Session tool inventory (programmatic, 225 tools total) contains all four:

```
mcp__skill_search__get_skill
mcp__skill_search__health
mcp__skill_search__reindex
mcp__skill_search__search_skills
```

(First pass: zero of four — the unexpanded `${CLAUDE_PLUGIN_ROOT}` spawn.)

## Check 3 — REAL in-session retrieval — **PASS**

`search_skills(query="test driven development red green refactor", extra_queries=["write failing test first then implement"])`
answered in-session in 862 ms with 6 ranked results and the fusion echo `"queries": [both]`:

```
antigravity:wjttc-builder                  0.8332  external:"antigravity" + consume-note
superpowers:test-driven-development        0.8021  command:"/superpowers:test-driven-development"
superpowers:systematic-debugging           0.7843  command:"/superpowers:systematic-debugging"
antigravity:testing-patterns               0.7440  external:"antigravity"
antigravity:code-showcase-testing-patterns 0.7440  external:"antigravity"
antigravity:python-testing-patterns        0.7303  external:"antigravity"
```

Externals carry the `external` marker + note; installed rows carry `command`. The reply also carries
`"warning": "index manifest missing — run reindex() (results may be empty/stale)"` — a false positive,
root-caused below (Defect D2); ranking itself is correct and served from the shared live index.

## Check 4 — Foreign-skill consumption path — **PASS**

`get_skill({"name": "mattpocock-skills:diagnosing-bugs"})` returned the full SKILL.md —
**18,209 chars**, frontmatter through the final handoff:

```
---
name: diagnosing-bugs
description: Diagnosis loop for hard bugs and performance regressions. …
---
# Diagnosing Bugs
A discipline for hard bugs. …
[…]
… hand off to the `/improve-codebase-architecture` skill with the specifics. …
```

The exact path the `[claude]` annex instructs, exercised for real from Codex for the first time.
(A bare-string argument is rejected by the MCP layer — args must be a JSON object.)

## Check 5 — Telemetry frontier: does Codex fire PostToolUse? — **PASS** (intel; assumption HOLDS)

After the check-3/4 MCP calls, `tail -8` of the shared ledger. This session's rows (sid `01a0336a`):

```
{"t": 1787570971.769, "sid": "01a0336a-…", "ev": "turn", "q": "Goal: Full re-validation of skill-concierge v0.25.2 …"}
{"t": 1787570972.156, "sid": "01a0336a-…", "ev": "offer", "band": "offer",
 "offered": [["superpowers:verification-before-completion", 0.8113], ["vercel:investigation-mode", 0.8103],
             ["verification-before-completion", 0.7864], ["omo:debugging", 0.7828],
             ["@code-yeongyu:ulw-loop", 0.7787], ["vercel:verification", 0.7781],
             ["components:lcx-doctor", 0.7778], ["check-work", 0.7755]],
 "ext": [["antigravity:verification-before-completion", 0.804], ["antigravity:executing-plans", 0.7889]],
 "xh": [["skill-concierge:doctor", 0.8129], ["mattpocock-skills:diagnosing-bugs", 0.8064]],
 "embed_ms": 305, "qdrant_ms": 20}
```

**Event kinds Codex produced: `turn` and `offer` only.** My session has exactly 4 rows (2× turn +
2× offer, one pair per validation prompt) — **zero `search` / `get_skill` events**, while the ledger
globally carries 293 such rows (all Claude-side PostToolUse captures). ADR-0033's assumption
(auto-capture is Claude-only) is **NOT stale — it holds**. No `auto` rows either (Codex has no Skill
tool; inline consumption leaves no auto trace — consistent).

Latent second layer found (Defect D3): even if Codex fired PostToolUse for MCP calls, capture would
still miss — Codex normalizes the server name to underscores (`mcp__skill_search__search_skills`)
while `ledger.py` matches suffix `skill-search__search_skills` (hyphen), and the hooks.json matcher
`Skill|mcp__skill-search__search_skills` names a tool that does not exist under Codex.

## Check 6 — Live offer isolation, fresh session — **PASS**

Scopes fetched from Qdrant (scroll by name) for every row of this session's offer (check-5 row):

```
INSTALLED (8):                                qdrant scope
  superpowers:verification-before-completion   codex-plugin
  vercel:investigation-mode                    codex-plugin
  verification-before-completion               personal
  omo:debugging                                codex-plugin
  @code-yeongyu:ulw-loop                       codex-plugin
  vercel:verification                          codex-plugin
  components:lcx-doctor                        codex-plugin
  check-work                                   personal
plugin-scope rows in installed block: 0

XH ANNEX (2):
  skill-concierge:doctor                       plugin       ← Claude-side
  mattpocock-skills:diagnosing-bugs            plugin       ← Claude-side
```

## Check 7 — Server-records + no-garbage — **PASS**

```
$ ls -d ~/.codex/plugins/cache/skill-concierge/skill-concierge/0.25.2/'${HOME}' 2>/dev/null || echo clean
clean
$ ls ~/.cache/skill-search/servers/ | tail -3
75658.json
75901.json
7816.json
```

The engine's `Path.home()` default is in use: this session's server wrote `servers/72634.json`
(`{"pid": 72634, "build": "3ff7c8639c2a", "started_at": 1787570908}` = 18:28:28 ICT, build matches the
on-disk engine). No literal-`${HOME}` directory was minted.

## Check 8 — Selftest + doctor + parity — **FAIL (selftest leg) · parity OK · doctor as-expected**

**Selftest (deployed cache copy) — FAIL, exit 1:**

```
$ python3 ~/.codex/plugins/cache/skill-concierge/.../0.25.2/hooks/scripts/enforcer.py --selftest
enforcer --selftest FAIL:
  cross-harness: an INVOCABLE twin must stay in the installed offer
  cross-harness: annex keeps only above-floor non-twins (0.31 below floor, twinpl:dup invocable here):
      [('otherpl:hi', 'd-otherpl:hi', 0.72), ('twinpl:dup', 'd-twinpl:dup', 0.71)]
  cross-harness: below-floor or twin row must not render in the annex
```

Classification (code-read, quoted in full during the pass): the selftest pins `FOREIGN_SCOPES` /
`INVOCABLE_PLUGIN_IDS` to simulate the **Claude-side** twin-rescue world but never recomputes
`UNDER_CODEX`. Run from the Codex cache, `UNDER_CODEX=True` (derived from the file's own path), so
`_invocable_twin` is blind by design and exactly the three twin-dependent assertions fail. Every
non-twin cross-harness assertion passed (over-fetch to RETRIEVE_LIMIT, scope payload requested,
post-filter never a query condition, refill to TOP_K, unknown-manifest filters nothing, annex scope-set
filter, floor, harness marker + get_skill render, %-share isolation, kill-switch both directions).
This is a harness-blind selftest (Defect D1), not a retrieval failure — live behavior is proven correct
by checks 3/4/6. Related to, but distinct from, the recorded D3-prior (twin-blind labeling).

**Parity — OK:** `mcp-env-parity OK: 7 shared keys in lockstep; codex omits ['SKILL_SERVER_RECORDS']
(deliberate — see descriptor comment)` (exit 0).

**Doctor — rows as expected:** Corpus health **present** (`12/14 ok · 1 weak · 1 no-signal`, the
durable-home thresholds row new in 0.25.1) ✓; Retrieval health **2541 skills indexed**, embedder+qdrant
reachable, "indexed 4m ago" ✓; `status: WARN` comes from the **known** stale-engine row (pid 59600,
another live session's server, per the Known list) — my session's engine (72634) matches the on-disk
build; MCP-reachable row reports Claude's wiring by design (known). One misleading row noted as
Defect D4: `Trigger hygiene … no triggers file at <cache>/eval/triggers.json — utterance layer unused`
— the live server consumes the durable home via env (`~/.claude/skill-concierge/triggers.json`, 1.47 MB,
exists; the cache path does not and shouldn't).

## Check 9 — Shared-index safety — **PASS**

```
points_count BEFORE everything: 24786
points_count AFTER everything:  24786
git status --porcelain | wc -l → 0   (HEAD 6f3d47c unchanged)
```

## Root cause of the false "never indexed" (evidence chain)

`manifest_key() = md5(str(PROJECT_ROOT))[:8]` with `PROJECT_ROOT = Path.cwd()/".claude"/"skills"` —
the manifest is **per project root**. This session:

```
md5("<repo>/.claude/skills")                = 964df33f   ← written 18:29:36 ICT, indexed 2541,
                                                           engine 3ff7c8639c2a — by THIS session's
                                                           SessionStart auto_reindex (cwd=repo);
                                                           ADR-0033 auto-discovery works under Codex
md5("<plugin-cache>/.claude/skills")        = 41eef40e   ← what my MCP server (cwd=0.25.2/. per
                                                           ADR-0035) looks for; never written by anyone
```

So health from any Codex session reports `degraded: no index manifest — never indexed` forever, and
the false warning rides every `search_skills` reply — while the index itself is fresh (written 5 s
after my session's first prompt, by my own session hook).

## Ranked defects

**D1 — MEDIUM · deployed `enforcer --selftest` fails from the Codex cache (harness-blind test).**
Evidence: check-8 raw output, exit 1, three twin-dependent assertions; classification above. Failure
scenario: an operator updates the plugin on Codex and runs the runbook's selftest from the cache —
the documented verification command fails with a false alarm, blocking rollout or burning a debugging
cycle on behavior that is by-design (twin-blind under Codex, ADR-0034/-0035). Fix direction: gate the
twin assertions on `not UNDER_CODEX` (or recompute/pin `UNDER_CODEX=False` inside the selftest block,
as is already done for `FOREIGN_SCOPES`/`INVOCABLE_PLUGIN_IDS`).

**D2 — MEDIUM · `health` permanently `degraded` from Codex + false "never indexed" warning on every
search reply.** Evidence: check-3 warning string; check-8 health/`indexed_at: null`; the md5 chain
above. Failure scenario: every Codex-side health check reports degraded and every search reply tells
the agent the index may be stale — crying wolf that trains operators to ignore real staleness; worse,
following the warning's own advice ("run reindex()") from Codex would execute a reindex with
`PROJECT_ROOT = <plugin-cache>/.claude/skills` — an unintended root, writing a manifest for a phantom
project scope (consequences for shared points deliberately untested — findings only; I did not run
reindex). Fix direction: pin `SKILL_META_PATH` (or a manifest-stable cwd) in the Codex descriptor.

**D3 — LOW · MCP-invocation ledger capture is impossible under Codex on two independent layers.**
Evidence: check-5 (zero `search`/`get_skill` rows from my calls vs 293 Claude-side rows in the same
ledger); hooks matcher `Skill|mcp__skill-search__search_skills` vs my session's actual ids
`mcp__skill_search__*`; `ledger.py` suffix constants `skill-search__search_skills`/`skill-search__get_skill`.
Failure scenario: Codex-side usage of search_skills/get_skill is invisible to `analyze.py`, so usage
metrics and the always-on flywheel under-measure the Codex harness; and if Codex later starts firing
PostToolUse for MCP calls, capture would STILL silently miss on the hyphen/underscore mismatch.
ADR-0033's assumption remains accurate today (no events fired).

**D4 — LOW · doctor's Trigger-hygiene row is misleading when run from the Codex cache.** Evidence:
`no triggers file at <cache>/eval/triggers.json — utterance layer unused` while the live server's env
points at the durable home (`~/.claude/skill-concierge/triggers.json`, 1.47 MB, present). Failure
scenario: an operator auditing from Codex concludes the utterance layer is off and "fixes" a working
config. Fix direction: hygiene check should honor the same `SKILL_TRIGGERS` default the descriptor
sets.

**Known items recorded (not re-reported):** D3-prior twin-blind annex labeling (ADR-0034/-0035 —
visible again this session as `skill-concierge:doctor` in the `xh` annex); doctor's MCP-reachable row
reporting Claude's wiring by design; the stale-engine WARN naming pid 59600 (another session's live
server, not mine — my engine build matches disk).

## Verdict table

| # | Check | Verdict |
|---|-------|---------|
| 1 | Version + byte-integrity | PASS |
| 2 | In-session tool surface (4/4) | PASS |
| 3 | Real in-session retrieval | PASS |
| 4 | get_skill consumption path | PASS |
| 5 | Telemetry frontier | PASS (intel: turn/offer only) |
| 6 | Live offer isolation | PASS |
| 7 | Server-records + no garbage | PASS |
| 8 | Selftest / parity / doctor | **FAIL** / OK / as-expected |
| 9 | Shared-index safety | PASS |

**Status: DONE_WITH_CONCERNS**

**Summary:** v0.25.2 fixes the first pass's headline failure — all four MCP tools mount in a live
Codex session and the retrieval organ works end-to-end (ranked search, external markers, full-body
get_skill, correct offer isolation, shared index untouched). The concerns are all telemetry/test
harness, not retrieval: the deployed selftest fails spuriously from the Codex cache, health is
permanently "degraded" on a false manifest-key mismatch, and MCP-invocation capture is impossible
under Codex (no events + a hyphen/underscore name mismatch waiting even if events arrive).

**Unresolved questions:**

1. Whether Codex fires PostToolUse for MCP tool calls at all — ledger silence cannot distinguish
   "no event" from "event fired, name mismatch filtered it" (D3); needs a name-agnostic probe hook.
2. What a `reindex()` run from inside the Codex MCP server (cwd=plugin cache) would actually do to
   shared points — deliberately untested (findings-only pass; the risk scenario is described in D2).
3. D2's fix shape (pin `SKILL_META_PATH` in the Codex descriptor vs a manifest-stable cwd) is a
   product decision; either way the Claude side must stay byte-identical.
