# Codex-side validation — skill-concierge v0.25.1 dual-harness (ADR-0033 + ADR-0034)

**Date:** 2026-08-24 (Asia/Ho_Chi_Minh) · **Harness:** Codex CLI 0.149.1 (session `01a0336a-3adb-7771-bef5-9e34e95b7516`)
**Repo:** `main @ ae883cc` (= v0.25.1), working tree clean before and after this pass.
**Scope:** findings only. The only write in this pass is this report. Git state and the shared Qdrant index untouched (proven in Check 9).

## Context correction to the brief

The brief said the Codex plugin cache still held 0.24.0. That was already remediated before this pass:
the cache now contains **exactly one version dir, 0.25.1**. No update action was needed, so the
Check-1 stop branch ("operator must update") did not apply.

## Check 1 — UPDATE FIRST — **PASS**

```
$ grep '"version"' ~/.codex/plugins/cache/skill-concierge/skill-concierge/*/.codex-plugin/plugin.json
  "version": "0.25.1",
# ls ~/.codex/plugins/cache/skill-concierge/skill-concierge/  →  0.25.1   (only dir)
```

## Check 2 — Deploy integrity — **PASS**

```
OK hooks/scripts/enforcer.py
OK scripts/doctor.py
OK vendor/skill-search/skill_search/skills_discovery.py
```

Repo and cache copies are byte-identical (`cmp -s`) for all three load-bearing files.

## Check 3 — Harness detection under Codex — **PASS**

Imported the **cache** copy (`~/.codex/.../0.25.1/hooks/scripts/enforcer.py`) via `importlib`:

```
UNDER_CODEX: True | FOREIGN_HARNESS: claude | FOREIGN_SCOPES: ('plugin',)
twin(agent-skills:tdd): False
CTX RETRIEVE_LIMIT: 40 TOP_K: 8 CROSS_HARNESS: True
INVOCABLE_PLUGIN_IDS: {'claude-hud', 'effort-gate', 'selfcheck-gate', 'i-have-adhd', 'skill-concierge',
 'fablize', 'openwiki', 'superpowers-developing-for-claude-code', 'memsearch', 'mattpocock-skills',
 'smgrep', 'agent-skills'}
```

Exactly the expected constants (`True / claude / ('plugin',) / False`, `RETRIEVE_LIMIT=40`). The
twin test is intentionally Codex-blind (per ADR-0034: enablement truth lives in `config.toml`, TOML,
unreadable on the stdlib 3.10 floor) — see Defect D3 for the one visible consequence.

## Check 4 — Offer correctness from Codex — **PASS**

Method: `v = _embed(q); inst = _retrieve(v); fgn = _retrieve_foreign(v)`; each installed row's
`scope` then fetched from Qdrant (`POST /collections/claude_skills/points/scroll`, filter `name == row`,
`with_payload=["scope"]`). Embed shim 127.0.0.1:6363 (`{"status":"ok","model":"...mpnet-base-v2","dim":768}`)
and Qdrant :6333 both shared with Claude and up.

**Q1 "debug why my tests are failing in CI"** — installed rows (name, score, qdrant-scope):

```
agent-skills:debugging-and-error-recovery  0.7836  codex-plugin
superpowers:systematic-debugging           0.7003  codex-plugin
ak-fix                                     0.6852  personal
ak-debug                                   0.6699  personal
vercel:vercel-agent                        0.6345  codex-plugin
codexclaw:dev-debugging                    0.6105  codex-plugin
vercel:react-best-practices                0.6016  codex-plugin
vercel:observability                       0.5974  codex-plugin
--- foreign annex ---
mattpocock-skills:diagnosing-bugs          0.4969  plugin
memsearch:memory-recall                    0.4846  plugin
```

**Q2 "review this pull request for security issues"** — installed rows:

```
agent-skills:code-review-and-quality       0.7505  codex-plugin
superpowers:requesting-code-review         0.7418  codex-plugin
ak-review-pr                               0.7241  personal
vercel:vercel-agent                        0.7168  codex-plugin
omo:review-work                            0.6859  codex-plugin
cloudflare:cloudflare                      0.6800  codex-plugin
ak-security-scan                           0.6765  personal
ak-security                                0.6680  personal
--- foreign annex ---
mattpocock-skills:git-guardrails-claude-code 0.4389  plugin
mattpocock-skills:wizard                     0.4281  plugin
```

Verdict against the PASS bar: **zero** installed rows with `scope == "plugin"` in either query; every
foreign-annex row is a Claude-side plugin skill (`scope == "plugin"`); personal-scope rows are present
in the installed offer (`ak-fix`, `ak-debug`, `ak-review-pr`, `ak-security-scan`, `ak-security` — the
`~/.codex/skills → ~/.claude/skills` share working as designed).

## Check 5 — Render marker — **PASS**

`_ranked_mandate(inst[:3], foreign=fgn)` for Q1 renders:

```
SKILL-FIRST · reply line 1 = USING <skill> | SEARCH <query> | SKIPPING none.
Preview for this task (NOT the full ~500 shelf):
  • agent-skills:debugging-and-error-recovery (36%) — Guides systematic root-cause debugging…
  • superpowers:systematic-debugging (32%) — Use when encountering any bug, test failure…
  • ak-fix (32%) — Fix bugs, errors, test failures, and CI/CD issues with intelligent routing…
Shares are RELATIVE rank among these few…
Other-harness matches (installed under Claude, NOT invocable here — consume with get_skill, do not use the Skill tool):
  • mattpocock-skills:diagnosing-bugs [claude] — Diagnosis loop for hard bugs…
  • memsearch:memory-recall [claude] — Search and recall relevant memories from past sessions…
To use one: `USING: <name>` then get_skill("<name>") and follow its SKILL.md inline.
```

Annex headed "installed under Claude" ✓, every annex row tagged `[claude]` ✓, get_skill instruction ✓.

## Check 6 — Kill-switch (`CROSS_HARNESS = False`) — **PASS**

On the two mandated queries the installed lists happened to be identical with the flag on/off (the
dropped `plugin` rows scored below `TOP_K=8`'s window: annex floor rows 0.44–0.50 vs installed floor
0.60–0.70), so the toggle was additionally proven with a query where a `plugin`-scope skill is the
**overall top match**:

```
Q = "search my past session memories with memsearch"
CROSS_HARNESS=True  installed: omo:coding-agent-sessions .8584 / transcript-miner .8441 / rg_history .8090 /
                    codexclaw:recall .7402 / agent-skills:context-engineering .6779 / @sisyphuslabs:teammode .6396 /
                    skill-usage-tracker .6287 / feedbin-cli .5984     ← memsearch:memory-recall ABSENT
CROSS_HARNESS=True  foreign  : memsearch:memory-recall .9349 (plugin), memsearch:memory-to-skill .6117 (plugin)
CROSS_HARNESS=False installed: memsearch:memory-recall .9349 (plugin)  ← #1 row returns to the offer
                    + the same 7 codex-plugin/personal rows beneath it
CROSS_HARNESS=False foreign  : []
```

Filter-on drops `plugin`-scope rows from the offer and re-surfaces them in the annex; filter-off
reinstates them and the foreign call returns `[]`. Exactly the one-var revert ADR-0034 promises.

## Check 7 — Live hook wiring in THIS Codex session — **PASS**

`tail -5 ~/.claude/skill-concierge/logs/skill-invocation-ledger.log` — the last rows are **this session's**:

```
{"t": 1787569117.55,  "sid": "01a0336a-3adb-7771-bef5-9e34e95b7516", "ev": "turn", "q": "check why my skill-search mcp server failed (from skill-concierge plugin)…"}
{"t": 1787569117.897, "sid": "01a0336a-3adb-7771-bef5-9e34e95b7516", "ev": "offer", "band": "offer",
 "offered": [["vercel:investigation-mode", 0.8407], ["superpowers:verification-before-completion", 0.8299],
             ["components:lcx-doctor", 0.8236], ["skill-check", 0.8215], ["verification-before-completion", 0.8209],
             ["agent-skills:code-review-and-quality", 0.811], ["omo:lcx-doctor", 0.8097],
             ["agent-skills:shipping-and-launch", 0.806]],
 "ext": [["antigravity:verification-before-completion", 0.8323], ["antigravity:lint-and-validate", 0.8254]],
 "xh": [["mattpocock-skills:code-review", 0.8389], ["skill-concierge:doctor", 0.8327]],
 "embed_ms": 289, "qdrant_ms": 17}
```

Recent `turn`/`offer` events from this Codex session exist ✓; the offer's `xh` annex names Claude-side
plugin skills ✓ (and note the installed offer contains zero `plugin`-scope names — the live hook
reproduces Check 4's lab result). ADR-0033's auto-discovery claim holds for **hooks**: UserPromptSubmit
fired and injected the SKILL-FIRST doctrine into this very turn.

## Check 8 — MCP + thresholds — **FAIL (in-session MCP) · server PASS at protocol level · thresholds PASS**

**In-session MCP:** the session's full tool surface was enumerated programmatically — **248 tools,
zero skill-search matches** (`search_skills`/`get_skill`/`reindex`/`health` all absent). The failure
mechanism, from `codex mcp get skill-search`:

```
skill-search
  enabled: true
  transport: stdio
  command: ${CLAUDE_PLUGIN_ROOT}/bin/skill-search-mcp     ← LITERAL, never expanded
```

Codex registered the plugin's MCP entry (from `.codex-plugin/plugin.json` → `./.mcp.json`) without
substituting `${CLAUDE_PLUGIN_ROOT}`, so the spawn targets a path that cannot exist → the server never
starts in any Codex session. This is Defect D1.

**Server health (fallback evidence):** driven directly over stdio, the same launcher answers a full
JSON-RPC session — `initialize` → `serverInfo {skill-search, 1.29.0}`, then
`tools/call search_skills {"query":"debug why my tests are failing in CI"}` → ranked results
(`ak-fix` 0.7646, `diagnose`, …). The engine, venv and Qdrant path are healthy; only the wiring is broken.

**Thresholds:**

```
_THRESHOLDS_PATH: /Users/thinhkhuat/.claude/skill-concierge/thresholds.json exists: True
```

## Check 9 — Shared-index safety — **PASS**

```
points_count BEFORE all probes: 24786
points_count AFTER all probes:  24786
git status --porcelain | wc -l → 0    (before and after the pass; HEAD ae883cc unchanged)
```

Nothing was deleted from Claude's scopes and the repo tree is byte-clean.

---

## MCP failure diagnosis (both harnesses — the standing question)

**Codex (current, reproduces):** root cause is the unexpanded `${CLAUDE_PLUGIN_ROOT}` in the
plugin-declared MCP command under Codex CLI 0.149.1. Registration succeeds (server listed, "enabled"),
but the spawn path is the literal string, so the process can never start. The plugin's own
`.codex/hooks.json` description claims "Codex … expands the same `${CLAUDE_PLUGIN_ROOT}` variable
(ADR-0033)" — true for **hooks** (they fired this session), demonstrably false for **mcpServers**.

**Claude Code (earlier today, transient):** `mcp-logs-skill-search/2026-08-24T08-44-47-482Z.jsonl`
records, at 09:12:46Z:

```
Connection failed after 3ms (ENOENT): posix_spawn '$HOME/.claude/bin/skill-search-mcp'
```

Same bug class — an unexpanded variable — in a then-existing **non-plugin** `skill-search` entry. That
entry is now gone from every scope (user `~/.claude.json`: no skill-search; project-local: `{}`;
project `.mcp.json`: untouched since Aug 20 and contains only the `${CLAUDE_PLUGIN_ROOT}` form;
`.claude/settings.json`: no mcpServers block), and the path `~/.claude/bin/skill-search-mcp` does not
exist. The plugin-scoped server has been healthy since 10:12Z; its logs also show ADR-0018 self-heal
working in the wild at 10:43Z ("plugin at v0.25.1, venv engine stamped '0.25.0' — resyncing engine…
engine resynced to v0.25.1", connect in 2957 ms).

## Ranked defects

**D1 — HIGH · Codex MCP wiring: `${CLAUDE_PLUGIN_ROOT}` never expanded in plugin MCP commands.**
Evidence: `codex mcp get skill-search` literal command; 248-tool enumeration with zero skill-search
tools; launcher + `tools/call` proven healthy over stdio. Failure scenario: in **every** Codex session,
the always-on `skill-concierge:skill-search` router and the injected SKILL-FIRST doctrine mandate
`search_skills` — a tool that does not exist in the session. The retrieval organ is silently dead on
the Codex side while hooks and the ledger keep working, so the outage is invisible in ledger metrics;
agents either improvise (violating the doctrine) or stall. Fix direction (not applied — findings
only): ship a Codex-native MCP descriptor whose command is an absolute path or a wrapper that
self-locates (the launcher already resolves its ROOT via `BASH_SOURCE`; only the registered entry
point is broken), or document a post-install `codex mcp add` step with the real path.

**D2 — MEDIUM (transient, already resolved) · stale duplicate `skill-search` entry with unexpanded
`$HOME` broke Claude Code at 09:12Z.** Failure scenario: any entry registered as
`'$HOME/.claude/bin/skill-search-mcp'` (single-quoted) ENOENTs on every launch until removed — which
is exactly the failure observed and later cleaned up today. Attribution of who/what created it is
unresolved (see below). Not a live defect; reported because it cost a real debugging cycle and is the
same failure class as D1.

**D3 — LOW · dual-installed plugin skills mislabelled "NOT invocable here" from Codex.** Because
`_invocable_twin` is Codex-blind by design, a plugin installed on **both** harnesses surfaces its
skills only in the `[claude]` annex when the Claude-side point wins index dedup. Live example from
this session's own offer: `skill-concierge:doctor` appeared in `xh` as a Claude-only skill, while the
identical skill sits in the Codex plugin cache and is directly readable. Failure scenario: an agent
obeys the annex, consumes the skill via `get_skill` inline — it still works, so the impact is a false
"NOT invocable" label and a lost installed-offer row, not a broken path. Documented fail-direction in
ADR-0034; noting it because `skill-concierge` itself is the first plugin to hit it.

## Verdict table

| # | Check | Verdict |
|---|-------|---------|
| 1 | Cache version = 0.25.1 | PASS |
| 2 | Deploy integrity (3 files) | PASS |
| 3 | Harness detection constants | PASS |
| 4 | Offer isolation from Codex | PASS |
| 5 | Annex render marker | PASS |
| 6 | Kill-switch revert | PASS |
| 7 | Live hooks + ledger in Codex | PASS |
| 8 | MCP in-session / server / thresholds | **FAIL** / PASS (protocol) / PASS |
| 9 | Shared-index safety | PASS |

**Status: DONE_WITH_CONCERNS**

**Summary:** All nine checks carry evidence-backed verdicts; v0.25.1's dual-harness behavior is
correct everywhere the code runs — deploy, detection, offer isolation, annex render, kill-switch,
live hooks and index safety all PASS. The single failure is environmental wiring, not product logic:
Codex never expands `${CLAUDE_PLUGIN_ROOT}` in plugin MCP commands, so the skill-search server —
proven healthy over stdio — is unreachable from every Codex session (D1); the earlier Claude failure
was the same unexpanded-variable class in a since-removed duplicate entry (D2).

**Unresolved questions:**

1. Who/what created the transient `$HOME/.claude/bin/skill-search-mcp` entry that failed at 09:12Z —
   it appears in no current scope and no on-disk config; logs prove it existed, nothing proves its origin.
2. Whether any Codex CLI version expands `${CLAUDE_PLUGIN_ROOT}` in plugin-declared `mcpServers`
   (observed only on 0.149.1) — decides whether D1's fix belongs in the plugin manifest or in Codex docs.
3. D3's fix (Codex-side twin test would need a TOML-readable path or a sidecar manifest) is a product
   decision, deliberately out of scope for this findings-only pass.
