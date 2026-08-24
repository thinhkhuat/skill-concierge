# Opus Validation Report — ADR-0034 cross-harness offer isolation

**Subject:** implementation (uncommitted working tree, branch `main`)
**Scope:** `hooks/scripts/enforcer.py`, `vendor/skill-search/skill_search/skills_discovery.py`, `hooks/scripts/auto_reindex.py`, ADR-0034 + CHANGELOG/README/AGENTS.md/CLAUDE.md, version bump 0.24.0 -> 0.25.0
**Verdict:** **FAIL** — two blocking defects
**Date:** 2026-08-24
**Evidence files examined:** 14 source/doc files + live Qdrant collection (24,893 points) + live plugin caches + 4 settings files

## Executive Summary

The mechanism is built correctly: the two queries are genuinely separate, displacement is structurally impossible, the kill-switch is a proven byte-identical revert, and the hook stays fail-silent under every import-time abuse I could construct. It fails on its **premise**. `scope == "codex-plugin"` does not mean "not invocable from Claude" on this machine: 24 `agent-skills:*` skills are enabled for this project via `.claude/settings.local.json`, are in this session's live skill catalog, and are now dropped from the installed offer and rendered under "NOT invocable here — do not use the Skill tool". Separately, `_running_under_codex()` probes the **current working directory** when `CLAUDE_PLUGIN_ROOT` is unset, which can invert the filter and exclude Claude's own plugin skills.

## Claim-by-claim

### A. No displacement — **CONFIRMED**

Two independent Qdrant calls; `_foreign` never enters `cands` and never reaches the ranking pipeline.

- `enforcer.py:918-940`: `_retrieve_foreign` is called after `cands` is fully resolved (`_drop_keepoff`, `_deterministic_hits`, getaway, intent gate all complete), its result flows only into `_ranked_mandate(..., foreign=)` and `_append_offer(xh=)`.
- `enforcer.py:710-712`: `total = sum(s for (_n,_d,s) in cands)` — the %-share denominator is installed-only; the foreign block renders no percentage.
- Selftest case (12) pins it: `"cross-harness: foreign must not join the installed %-share pool"`.
- Live: `_retrieve` returned **8 rows on every one of 5 probes** with the filter on (no shrinkage, the pool refills from installed skills).

One caveat, not a defect today: `_deterministic_hits` (`enforcer.py:435-450`) prepends arbitrary operator-configured names, so an armed route naming a foreign skill *would* place it in the installed list. Verified inert on this machine — `_ROUTES` count = 0.

### B. Fail-silent contract preserved — **CONFIRMED**

`_running_under_codex()` runs at import (`enforcer.py:106-119`). Every candidate is wrapped in `try/except Exception: continue`, and `Path.resolve()` is non-strict.

Executed at import with `CLAUDE_PLUGIN_ROOT` set to: a symlink loop (`b -> a -> b`, ELOOP), a nonexistent path, empty string, a relative path, and a 4000-char path. All five imported cleanly:

```
CPR=<symlink loop>   -> OK codex-plugin
CPR=/nonexistent/..  -> OK codex-plugin
CPR=                 -> OK codex-plugin
CPR=relative/path    -> OK codex-plugin
CPR=zzzz...(4000)    -> OK codex-plugin
```

End-to-end hook run: `EXIT=0` on a trivial prompt, `EXIT=0` on empty stdin, no stderr. `_retrieve_foreign` sits in its own `try/except` (`enforcer.py:936-939`) and the whole of `main()` in `except Exception: return 0`.

Residual (theoretical, unreachable via the hook): if `__file__` were undefined the module-level tuple would raise `NameError` before any guard. Not reachable for a script invoked by path.

### C. Kill-switch is a true byte-identical revert — **CONFIRMED**

Differential test against `git show HEAD:hooks/scripts/enforcer.py` with `ENFORCER_CROSS_HARNESS=0`, capturing every outbound request payload:

```
old calls: 2   new calls: 2
REQUEST PAYLOADS IDENTICAL: True
RENDER IDENTICAL: True
```

`_must_not` collapses to the single `tier=external` condition (`enforcer.py:609-611`); `_retrieve_foreign` returns `[]` before any HTTP (`enforcer.py:666-667`); `if foreign:` is false so `foreign_block = ""`; `xh=[] or None` omits the ledger key.

### D. Harness detection is correct — **REFUTED**

Correct in the normal cases. Verified live in a repo-checkout run: `FOREIGN_PLUGIN_SCOPE = codex-plugin`, `FOREIGN_HARNESS = codex` (falls through to Claude, as documented).

The bug is `os.environ.get("CLAUDE_PLUGIN_ROOT") or ""` at `enforcer.py:116`. An empty candidate becomes `Path("").resolve()`, which is **`os.getcwd()`** — turning the env check into a silent CWD probe. Proven:

```
cwd=~/.codex/agents, CLAUDE_PLUGIN_ROOT unset -> ('/Users/thinhkhuat/.codex/agents', True, 'claude', 'plugin')
cwd=~/.codex/agents, CLAUDE_PLUGIN_ROOT set   -> ('/Users/thinhkhuat/.codex/agents', False, 'codex', 'codex-plugin')
```

With the var unset and the CWD anywhere under `~/.codex/<subdir>`, a **Claude** session sets `FOREIGN_PLUGIN_SCOPE = "plugin"` and excludes Claude's own plugin skills from its own offer, annexing them as "NOT invocable here". Reachable whenever the hook is wired by absolute path rather than `${CLAUDE_PLUGIN_ROOT}` — precisely the case the docstring says the `__file__` fallback exists to cover.

Also: the loop is a **disjunction**, not the precedence the docstring and AGENTS.md describe ("checks the env var first, then this file's own resolved path"). If the two disagree, whichever contains `/.codex/` wins.

Symlinked plugin dir: `Path.resolve()` follows symlinks, so a Claude plugin dir symlinked into `~/.codex/**` misdetects as Codex. Narrow, but it is the same class.

Repo-checkout run: correct (falls through to Claude), verified.

### E. Latency budget — **PARTIALLY REFUTED / quantified**

The change adds a third Qdrant round-trip **and** roughly doubles the cost of the first one, because neither `scope` nor `tier` has a payload index.

Live collection schema (`GET /collections/claude_skills`), 24,893 points:

```
payload_schema: { "name": { "data_type": "keyword", "points": 24893 } }
```

Only `name` is indexed. `_ensure_collection` (`server.py:533-538`) creates exactly that one index; `scope` is not created anywhere.

Measured (idle machine, 25 iterations, 3 warm-ups, `QDRANT_TIMEOUT_S` lifted to measure true latency):

| query | median | p95 |
|---|---|---|
| installed, **unfiltered** (xh off) | 10.1 ms | 11.9 ms |
| installed, **scope-filtered** (xh on) | 21.1 ms | 24.7 ms |
| foreign annex (new) | 9.9 ms | 11.4 ms |
| external annex | 8.6 ms | 10.1 ms |
| intent gate (2 queries) | 4.4 ms | 6.1 ms |

Median added cost ≈ **+21 ms** per offer-bearing turn (+11 ms on the installed query, +10 ms for the new one). That is affordable.

The tail is not. My **first** sample, taken while the machine was under real contention (the embed shim also blew its 350 ms cap in that same run), gave:

| query | median | p95 | max |
|---|---|---|---|
| installed, scope-filtered | **105.2 ms** | **178.1 ms** | 182.7 ms |
| installed, unfiltered | 49.0 ms | 78.5 ms | 104.6 ms |

`QDRANT_TIMEOUT_S = 0.1` is a **hard cap**, and a `_retrieve` timeout is caught at `enforcer.py:872-877` and collapses the turn to mandate-only (`fallback="qdrant_down"`). Under contention the filtered query crosses that cap where the unfiltered one does not. I could not reproduce the contended sample on demand, so I label it: **one observed contended sample, not a reproducible steady state** — but the mechanism (unindexed keyword filter over 24,893 points, hard 100 ms cap, whole-offer loss on timeout) is real and the fix is one line in `_ensure_collection`.

Budget accounting: the module docstring still says "200ms within a ≲300ms total per-turn budget" while `EMBED_TIMEOUT_S` is live at **0.35**. Worst case is now 350 (embed) + 100 (installed) + 200 (intent, 2 queries, non-imperative turns) + 100 (external) + 100 (foreign) ≈ **850 ms**, against a pre-change ≈ 750 ms. The stated budget was already stale before this change; ADR-0034 widens the gap by ~100 ms worst-case and never restates the number. The `POSITION IS LOAD-BEARING` comment (`enforcer.py:924-930`) reasons about the third round-trip but only for *suppressed* turns.

### F. Nested glob correctness — mostly CONFIRMED, one docstring claim REFUTED

**(i) never duplicate — REFUTED as a general claim, CONFIRMED in practice.**
The docstring asserts "The two patterns are disjoint by depth, so the concatenation cannot duplicate" (`skills_discovery.py:445-446`). False. A path ending `skills/skills/<x>/SKILL.md` matches the flat pattern (component[-3] == "skills") *and* the nested pattern (component[-4] == "skills"). The phantom guard misses it: the nested hit's grandparent is `.../skills/skills`, while the flat hit's dirname is `.../skills/skills/y`. Constructed and proven:

```
pathological skills/skills/y hits: 2 dupes: 1
```

No occurrence on this machine — live `discover_skill_paths()` reports **dupe paths: 0**. Impact is further bounded by `discover_skills`'s `found.setdefault` name dedup. Low severity; the docstring assertion is what is wrong.

**(ii) no phantom from a skill's own subdirectory — CONFIRMED.** The structural guard (`skills_discovery.py:454-457`) drops a nested hit whose grandparent already matched the flat glob. New test `test_nested_glob_does_not_mint_a_skills_own_subdirectory` passes. Live: exactly **35** nested-depth plugin paths, all `mattpocock-skills` — matching `find ~/.claude/plugins/cache -path "*mattpocock*" -name SKILL.md | wc -l` = 35. Zero phantoms.

**(iii) hermetic under the existing conftest — CONFIRMED.** `_nested_glob` is derived from the passed glob at call time, so the conftest's single `monkeypatch.setattr(sd, "CODEX_PLUGIN_GLOB", ...)` still pins everything. Full suite: **76 passed** in 162.55s; `test_discovery.py`: 38 passed.

**(iv) glob shapes with no `skills/*/SKILL.md` tail — CONFIRMED.** `_nested_glob` returns the input unchanged and `_glob_both_depths` globs once (`skills_discovery.py:450-452`). The conftest pins Codex to `.../none/**/SKILL.md`, which takes exactly this branch.

Note on the ternary at `skills_discovery.py:437-438`: `a + b if cond else c` parses as `(a + b) if cond else c` — correct, conditional-expression precedence is looser than `+`. Ugly, not a bug.

**Performance:** one extra full walk of each cache.

```
claude: flat 418 in 0.229s | both-depths 453 in 0.394s (x1.72)
codex:  flat 313 in 0.053s | both-depths 313 in 0.088s (x1.68)
```

≈ +200 ms per index build. Off the hot path (build/reindex only) — acceptable.

### G. Scope reasoning — CONFIRMED on this machine, failure mode named

`readlink ~/.codex/skills` -> `/Users/thinhkhuat/.claude/skills`. The symlink exists.

Live discovery scope census confirms the dedup works exactly as the ADR describes:

```
[('catalog:antigravity', 1928), ('personal', 350), ('codex-plugin', 205), ('plugin', 58)]
```

`codex-personal` count is **zero** — every Codex personal skill dedups into the one `personal` scope (SKILL_DIRS order puts `PERSONAL_ROOT` first, `found.setdefault` = first writer wins). The ADR's "350 skills on the dev machine" is exact.

**Failure mode without the symlink:** `codex-personal` becomes a populated, distinct scope. `_retrieve` filters only `FOREIGN_PLUGIN_SCOPE` (`enforcer.py:609-611`) — `codex-personal` is not excluded. A Claude session would then have its 8 installed slots contested by Codex-only personal skills that are not Skill-tool-invocable, and they would render in the **installed** block with a %-share, with no marker at all. That is the precise harm ADR-0034 exists to prevent, left open for any machine that does not happen to have this symlink. The ADR names `personal` mutuality as the reason but does not state what happens when the premise is absent.

### H. Docs match code — MOSTLY, three defects

| Claim | Status | Evidence |
|---|---|---|
| 2 foreign slots | CONFIRMED | `ENFORCER_FOREIGN_SLOTS` default `"2"`, live `FOREIGN_SLOTS = 2` |
| 0.40 floor | CONFIRMED | live `FOREIGN_FLOOR = 0.4`; probe dropped a 0.31 row, kept 0.72 |
| "35 mattpocock skills" | CONFIRMED | `find` = 35; nested-depth discovery = 35, all `mattpocock-skills`; `mattpocock-skills:tdd` now resolves to `plugin` scope |
| "2541 skills (2506 + exactly the 35)" | CONFIRMED | live `discover_skills()` = **2541**, dupe paths 0 |
| "zero duplicate paths, zero phantoms" | CONFIRMED | measured |
| ADR "3–5 of 8 offer rows" | **NOT REPRODUCIBLE** | live: debug **6**/8, review **1**/8, docker **5**/8, plan 2/8, security 4/8 |
| README "3–6 of 8 offer rows" | **NOT REPRODUCIBLE, and contradicts the ADR** | same run; the two docs shipped in one change state different ranges |
| ADR: `xh` "so cross-harness offer→take is measurable separately" | **OVER-CLAIM** | `grep -rn 'xh' scripts/ hooks/ --include=*.py` excluding enforcer.py: **no matches**. `analyze.py:189,196` handles `ext` only. The field is written, never read. |
| auto_reindex comment: "`SKILL_CODEX_ROOTS` … pinned to 0 in .mcp.json" | **FALSE** | `grep SKILL_CODEX_ROOTS .mcp.json` -> empty. Only `SKILL_LLM_TRIGGERS` is present. The code change is a correct defensive no-op; the comment states a pin that does not exist (contrast the CATALOG_ROOTS comment, correctly hedged with "if … is ever pinned"). |
| AGENTS.md "detection is path-derived (`CLAUDE_PLUGIN_ROOT`, then the hook's own `__file__`)" | **MISDESCRIBES CODE** | the code is a disjunction over both, and the empty-env branch probes the CWD (defect 2) |
| version 0.25.0 across 4 manifests + docs | CONFIRMED | `driftcheck.py driftcheck.json` -> **exit 0**, all 6 version facts `[ok]` |

### I. Anything the author missed

**Undisclosed in the brief:** the ADR-0032 external-annex query was **moved** from before the getaway/intent gates to after them (`enforcer.py`, hunk `@@ -779,18 +878,6 @@` + `@@ -826,13 +913,38 @@`). Output-neutral — neither suppressed leg passes `ext` to `_append_offer` — and documented in `CHANGELOG.md:31-33`, but absent from the ADR's Decision section. Verified harmless, flagged because it is a hot-path reordering the brief did not list.

**`analyze.py` contract: intact.** `analyze.py:178` builds `w["offered"]` from the `offered` key only, so hit@k / conversion / dodge rates are **not** polluted by annex rows. `annex_offers` at :189 keys on `ext` and is unaffected by `xh`. `driftcheck.py` exit 0. `doctor.py` / `auto_promote.py`: no `xh` or `offered`-composition coupling found.

**`get_skill` consumption path works for foreign skills** (`server.py:757-775`) — path lookup by point id, no scope filter, disk-walk fallback. The annex's instruction is executable.

**CHAIN-HINT still routes at non-invocable skills.** The sidecar's top-level keys include `codex-plugin`; `_chain_hint` (`enforcer.py:351-370`) filters on catalogue membership and KEEPOFF only, and emits "candidates, fit still required" with **no** harness marker. ADR-0034 deliberately keeps chain hints on the ADR-0033 union, but its own rationale ("an offer row the agent cannot act on … invites a `USING:` the harness will then refuse") applies verbatim to a hint line. Currently low-impact: 11 of 625 sidecar entries carry successors.

**Selftest case (12) has a hidden dependency on case (11).** Line 1344 declares `global CROSS_HARNESS, FOREIGN_SLOTS, FOREIGN_FLOOR` but not `_post_json`; the `_post_json = _fake_xh_post` rebinding only reaches module scope because line 1274 already declared `global _post_json` for the whole function. Remove or reorder case (11) and case (12) raises `UnboundLocalError` at `_saved_xh = (..., _post_json)`.

**Category collision risk (latent, not live).** Nested discovery namespaces `<plugin>:<skill-dir>` and discards the category (`_namespaced_name` uses `sub.index("skills")`, `si - 2`). Two same-named skill dirs in different categories of one plugin would silently collide under `found.setdefault`. Verified absent in mattpocock 1.2.3 (no duplicate leaf names across its 5 categories). This matches how Claude Code itself namespaces them, so it is the correct behaviour — noting it only as a future sharp edge.

## Ranked defects

### 1. BLOCKING — the filter's premise is false: 24 invocable skills excluded and actively mislabeled

`scope == "codex-plugin"` does **not** imply "not invocable from Claude".

`_installed_plugin_roots()` (`skills_discovery.py:157-181`) reads `enabledPlugins` from `CLAUDE_SETTINGS_JSON` = `~/.claude/settings.json` **only**. It never reads project `.claude/settings.json` or `.claude/settings.local.json`.

State on this machine:
- `~/.claude/settings.json`: `"agent-skills@addy-agent-skills": False`
- `<repo>/.claude/settings.local.json`: `"agent-skills@addy-agent-skills": True`
- `installed_plugins.json`: `installPath = ~/.claude/plugins/cache/addy-agent-skills/agent-skills/0.6.7`
- That path exists and holds **24** skill dirs — the same 24 as the Codex copy at `~/.codex/plugins/cache/agent-skills/agent-skills/0.6.7`.

Consequence: discovery drops the Claude copy, the Codex twin wins the name, scope becomes `codex-plugin`. Verified live:

```
agent-skills:debugging-and-error-recovery  codex-plugin | /Users/thinhkhuat/.codex/plugins/cache/agent-skills/...
```

Failure scenario (reproduced, 4 of 5 probes):

| prompt | dropped from installed offer, annexed as "NOT invocable here" |
|---|---|
| "debug this failing test" | `agent-skills:debugging-and-error-recovery` |
| "review my code changes" | `agent-skills:code-review-and-quality` |
| "docker build is broken" | `agent-skills:debugging-and-error-recovery` |
| "write a plan for a new feature" | `agent-skills:git-workflow-and-versioning` |
| "audit the security of this endpoint" | `agent-skills:doubt-driven-development` |

**All five of those names are in this session's live Claude skill catalog.** They are invocable via the Skill tool right now. The enforcer now tells the agent the opposite, in the imperative: *"NOT invocable here — consume with get_skill, do not use the Skill tool"*.

Blast radius: **44** codex-plugin-scoped skills have a Claude on-disk twin (`agent-skills` 24, `superpowers` 14, `codex` 3, `supabase` 2, `last30days` 1). The `superpowers` group is genuinely disabled everywhere and is correctly annexed — the mechanism works where enablement is honest. The 24 `agent-skills:*` are the false negatives.

Before ADR-0034 this was a benign mislabel: the skill still appeared in the offer, just sourced from the Codex path. ADR-0034 converts a labelling bug into active mis-routing, and it is the ADR's central invariant that breaks.

Fix direction (not applied): teach `_installed_plugin_roots()` to layer project `.claude/settings.json` and `.claude/settings.local.json` over the user file, the way Claude Code itself resolves `enabledPlugins`. Until then `ENFORCER_CROSS_HARNESS=0` is the honest posture on this machine.

### 2. BLOCKING — `_running_under_codex()` probes the CWD, and can invert the filter

`enforcer.py:116`: `for cand in (os.environ.get("CLAUDE_PLUGIN_ROOT") or "", __file__)`. The `or ""` fallback makes `Path("").resolve()` return `os.getcwd()`.

Failure scenario (proven above): hooks wired by absolute path (repo-checkout install, the case the docstring's `__file__` fallback exists for) + CWD anywhere under `~/.codex/<subdir>` -> `_running_under_codex() == True` -> `FOREIGN_PLUGIN_SCOPE == "plugin"` -> a **Claude** session excludes **Claude's own** plugin skills from its offer and annexes them as non-invocable. Complete inversion of the feature, silent, no log line.

Fix direction: skip falsy candidates (`for cand in (os.environ.get("CLAUDE_PLUGIN_ROOT"), __file__): if not cand: continue`), and make the precedence match the docstring instead of OR-ing.

### 3. MEDIUM — no payload index on `scope`; two unindexed filters land on the hot path

Only `name` is indexed (`server.py:533-538`, live schema confirms). The change adds `must_not scope` to the installed query and `must scope` to a new one. Measured cost: installed query 10.1 ms -> 21.1 ms median idle; one contended sample at 105 ms median / 178 ms p95 against a hard 100 ms cap, where a timeout costs the **entire** offer. `_ensure_collection` already has the pattern; adding `scope` is one line and removes the tail risk.

### 4. MEDIUM — stated latency budget is stale and now further exceeded

Docstring says "200ms … ≲300ms total"; `EMBED_TIMEOUT_S` is live at 0.35 and the worst-case path is now ≈850 ms across up to 5 Qdrant round-trips. Pre-existing drift that this change widens by ~100 ms without restating the number.

### 5. LOW — `_glob_both_depths` docstring claim "cannot duplicate" is provably false

Constructed counterexample returns the same path twice; the phantom guard does not catch it. Zero occurrences live; `discover_skills` name-dedup bounds the impact.

### 6. LOW — ADR says "3–5 of 8", README says "3–6 of 8", live shows 1–6 of 8

Two docs in one change disagree, and neither range reproduces on the live index.

### 7. LOW — `xh` is written but has no consumer

The ADR's "measurable separately" is aspirational. No `analyze.py` support shipped.

### 8. LOW — `auto_reindex.py` comment asserts a `.mcp.json` pin that does not exist

The code addition is correct and defensive; the comment states a false current fact.

### 9. LOW — CHAIN-HINT can still name a `codex-plugin` skill with no invocability marker

Deliberate per the ADR, but inconsistent with its own stated rationale. 11 of 625 sidecar entries affected.

### 10. LOW — selftest case (12) silently depends on case (11)'s `global _post_json`

Reordering or removing case (11) turns case (12) into an `UnboundLocalError`.

### 11. LOW — docstring / AGENTS.md describe precedence the code does not implement

"env first, then `__file__`" vs an actual disjunction.

## Validation dimensions

- [x] Displacement invariant — PASS (structural + 5 live probes)
- [x] Fail-silent / never-block — PASS (5 hostile import cases, 2 end-to-end runs, all exit 0)
- [x] Kill-switch byte-identity — PASS (differential payload + render equality vs `HEAD`)
- [x] Harness detection — **FAIL** (CWD probe inversion, proven)
- [x] Scope-premise correctness — **FAIL** (24 invocable skills excluded, proven)
- [x] Latency — WARN (quantified; +21 ms median, unindexed-filter tail risk against a hard cap)
- [x] Nested glob: duplication — WARN (docstring claim refuted; zero live impact)
- [x] Nested glob: phantoms — PASS (structural guard, live 35/35 exact)
- [x] Nested glob: hermeticity — PASS (76 tests pass, derived-not-constant)
- [x] Nested glob: no-tail shapes — PASS
- [x] Nested glob: build cost — PASS (+~200 ms, off hot path)
- [x] Symlink premise — PASS on this machine; failure mode named for machines without it
- [x] Doc/code parity — WARN (3 false or unreproducible claims; driftcheck exit 0)
- [x] Consumer contracts (`analyze.py`, `driftcheck.py`, `get_skill`) — PASS
- [x] Test suite — PASS (76 passed, 162.55s; enforcer `--selftest` OK, exit 0)

## Unverifiable items

- Behaviour of the code when actually **installed under Codex** (`~/.codex/plugins/cache/**/skill-concierge`). No such install exists on this machine; I validated the detection logic by injecting paths, not by running under Codex.
- The author's original "3–5 of 8" measurement. The live index predates the glob fix (`mattpocock-skills:tdd` is absent from Qdrant), so the author's numbers may come from a different index state. I report only what reproduces now.
- Whether the contended-latency sample (105 ms median filtered) recurs under normal session load. I saw it once and could not reproduce it on demand. Reported as one observation plus a mechanism, not as a steady state.

## Not checked

- The `catalog:antigravity` scope (1,928 of 2,541 skills) beyond confirming it is excluded via `tier=external` as before — no ADR-0032 regression testing was in scope.
- Actual Skill-tool invocation of an annexed skill (I did not invoke any skill to test the harness's refusal behaviour).
- `openwiki/` link integrity beyond what `driftcheck.py` covers.
- Codex-side hook wiring (`.codex/hooks.json`) behaviour at runtime.

## Context gaps

Whether the operator intends `.claude/settings.local.json` plugin enablement to be authoritative for discovery. If yes, defect 1 requires a `_installed_plugin_roots()` fix. If the operator instead considers the project-local enable a mistake, defect 1 collapses to a documentation note — but the mechanism's premise still needs to be stated as "enabled per the **user** settings file", not "invocable".

---

Status: DONE
Summary: The mechanism is sound — separate queries, zero displacement, proven byte-identical kill-switch, fail-silent under every hostile import I could build, and 76 engine tests plus the enforcer selftest pass. It fails on its premise: `codex-plugin` scope does not mean non-invocable, and 24 `agent-skills:*` skills that this very session can invoke are now dropped from the offer and told "do not use the Skill tool"; separately, `_running_under_codex()` probes the CWD when `CLAUDE_PLUGIN_ROOT` is unset and can invert the filter against Claude's own plugins.
Concerns/Blockers: (1) `_installed_plugin_roots()` ignores project-level `enabledPlugins`, so 24 invocable skills are mislabeled `codex-plugin` and excluded — proven on 4 of 5 live probes. (2) `Path("") .resolve()` == CWD makes harness detection invertible. (3) No `scope` payload index: the filtered installed query costs ~2x and, under contention, was measured crossing the hard 100 ms `QDRANT_TIMEOUT_S` that costs the whole offer. (4) ADR "3–5 of 8" and README "3–6 of 8" contradict each other and neither reproduces (live 1–6). Do not ship until (1) and (2) are fixed or `ENFORCER_CROSS_HARNESS` is defaulted OFF.
