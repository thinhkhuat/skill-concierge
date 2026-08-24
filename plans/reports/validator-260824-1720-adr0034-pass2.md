# Opus Validation Report — ADR-0034 pass 2 (commit 7c3d89d)

**Subject:** implementation (committed, `7c3d89d`, diffed against `6203001`)
**Scope:** `hooks/scripts/enforcer.py`, `scripts/analyze.py`, `vendor/skill-search/skill_search/server.py`, `skills_discovery.py`, ADR-0034 / CHANGELOG / README / openwiki
**Verdict:** **FAIL** — one blocking regression introduced by the fix, one high-severity inverted failure direction
**Date:** 2026-08-24
**Evidence:** 8 source files, live Qdrant (24,893 points), 30 live retrieval probes, 5,144 live ledger events, 6 filesystem-state fixtures, 7 settings-layer fixtures

## Executive Summary

Both pass-1 blockers are genuinely fixed and I could not break either one on its own terms: the twin rescue works live (48/48 offer rows invocable across the six named prompts, 236/236 across thirty), and the `Path("")`-is-cwd inversion is gone and pinned by the selftest. The redesign is better than the thing it replaces. But the fix introduced a new import-time crash — `_SETTINGS_LAYERS` calls `Path.cwd()` at module scope, outside every guard, so a deleted working directory takes the hook from "exit 0 with a full offer" (proven on `6203001`) to "exit 1 with a traceback" on every turn. And the `LOCAL_PLUGIN_IDS is None` branch does the exact opposite of what its own docstring promises: it filters everything foreign rather than nothing.

Context for severity: the deployed copy is still `6203001` (`md5 4169d58ecc`, plugin cache 0.24.0). Nothing below is live yet.

## Attack-by-attack

### 1. The twin test — **PARTIALLY REFUTED**

**Live effectiveness: CONFIRMED.** Six named prompts, `agent-skills:*` rescued, `superpowers:*`/`vercel:*`/`omo:*`/`codexclaw:*` correctly annexed:

```
debug this failing test        inst=8 rescued=['agent-skills:debugging-and-error-recovery']  bad=[]
review my code changes         inst=8 rescued=['agent-skills:code-review-and-quality']        bad=[]
docker build is broken         inst=8 rescued=['agent-skills:debugging-and-error-recovery',
                                               'agent-skills:test-driven-development']        bad=[]
write a plan for a new feature inst=8 rescued=['agent-skills:git-workflow-and-versioning']    bad=[]
audit the security ...         inst=8 rescued=['agent-skills:doubt-driven-development']       bad=[]
deploy to vercel               inst=8 rescued=['agent-skills:shipping-and-launch',
                                               'agent-skills:ci-cd-and-automation']           bad=[]
TOTAL installed rows: 48, genuinely non-invocable: 0
```

Widened to thirty prompts: **236 installed rows, 0 non-invocable.** `LOCAL_PLUGIN_IDS` resolves to the 12 ids I expect, and every one of them matches a plugin whose skills appear in this session's live catalog.

Now the breaks.

**(a) The None path filters EVERYTHING, not nothing. — REFUTED.**
`_invocable_twin` returns `False` when `LOCAL_PLUGIN_IDS is None` (`enforcer.py:190`), and the caller drops on `scope in FOREIGN_SCOPES and not _invocable_twin(name)` (`enforcer.py:713-715`). `not False` is `True`, so the row is dropped. Proven end-to-end with a stubbed transport and a foreign-scoped row:

```
nothing readable (LOCAL_PLUGIN_IDS=None)   installed offer=['local-skill']
real home (LOCAL_PLUGIN_IDS=12)            installed offer=['local-skill']
```

The `agent-skills:debugging-and-error-recovery` row (scope `codex-plugin`, score 0.9) is dropped in **both** runs — the None run behaves identically to a hard pre-filter. The docstring at `enforcer.py:176-178` says the opposite:

> "None means 'unknown', and an unknown twin test filters nothing — failing toward ADR-0033's union, which is merely noisy and already shipped, never toward telling the agent a skill it CAN invoke is 'NOT invocable here'."

That is the intended design and it is not what the code does. Reachable: `~/.claude/settings.json` corrupt or mid-write (Claude Code rewrites it when a plugin is toggled) plus no readable project settings — verified case E below returns None.

**(b) `enabledPlugins` present but absent a key -> `set()`, same wrong direction. — REFUTED.**
`.get("enabledPlugins", {})` makes an empty/absent block a *readable* dict, so `seen=True` and the result is an empty set, not None:

```
D settings.json with NO enabledPlugins -> LOCAL_PLUGIN_IDS: set() | twin('vercel:x'): False
```

Every foreign-scoped row is then dropped. A bare `~/.claude/settings.json` with no `enabledPlugins` block is an ordinary configuration, and it silently restores the pass-1 defect-1 behaviour.

**(c) "absent from enabledPlugins" means ENABLED, and this test says otherwise.**
This repo already encodes Claude Code's rule at `skills_discovery.py:175`: *"A plugin absent from enabledPlugins is enabled by default."* `_local_plugin_ids` collects only explicit-`true` keys, so an installed, enabled-by-default plugin is not in `LOCAL_PLUGIN_IDS` and can never be rescued. Two conflicting truths in one codebase. Live blast radius is 1 of 39 installed plugins (`fablize@fablize`), because discovery drops a Claude copy mainly on explicit-`false`, which the layering does catch. Narrow today, wrong in principle.

**(d) Enablement is not installation. — docstring overstates.**
`_invocable_twin`'s docstring (`enforcer.py:186-187`) says "the same plugin is installed and enabled here". The code reads settings only. A plugin enabled in settings whose cache is absent yields a false twin: a genuinely non-invocable row kept in the installed offer. Failure direction is safe (pre-0034 noise), the claim is not.

**(e) Marketplace collision — CONFIRMED, and worse than a false positive.**
`out[str(key).split("@",1)[0]] = bool(on)` collapses `foo@mktA` and `foo@mktB` onto one `foo` key; last writer in dict-iteration order wins:

```
G  foo@mktA=True foo@mktB=False -> LOCAL_PLUGIN_IDS: []  | twin('foo:skill'): False
```

The enabled marketplace's plugin was silently lost. The outcome is arbitrary (JSON key order), not a principled default in either direction.

**(f) Cases that behave correctly.**
- No colon in the name -> `False` -> dropped. Correct: `codex-personal` names carry no namespace and are genuinely unreachable.
- `enabledPlugins` not a dict (a list) -> skipped, `seen` stays False -> `None` (case C). Correct handling; the None branch itself is defect (a).
- Corrupt JSON -> `None` (case E). Same.
- No `.claude/` in cwd -> falls back to the user layer, 9 ids (case A). Correct.
- Layering precedence -> proven exactly as specified (case F): user `p=T q=F`, project `q=T`, local `p=F` yields `['q']`.

**(g) `Path.cwd()`, not the hook payload's `cwd`.** `_SETTINGS_LAYERS` keys off the process working directory rather than the `cwd` field in the UserPromptSubmit JSON. Equal in practice for a hook child; noted because it is a silent assumption, and because the same line is the blocking crash below.

### 2. Over-fetch under-fill — **REFUTED**

`_retrieve` **can** return fewer than `TOP_K` where the old code returned `TOP_K`. Thirty live prompts:

```
offer-size distribution: {5: 1, 7: 1, 8: 28}
under-filled: [('vercel edge function cold start', 7), ('next.js app router streaming', 5)]
```

`TOP_K * 3 = 24` is measurably insufficient. Counting how many groups are actually needed to fill eight invocable rows:

```
next.js app router streaming     groups needed: 30   (RETRIEVE_LIMIT = 24)
vercel edge function cold start  groups needed: 25   (RETRIEVE_LIMIT = 24)
```

The mechanism: on this machine `codex-plugin` is 205 of the ~613 non-external indexed skills and is vercel/next-heavy, so a Vercel-domain query puts 19 of the top 24 in foreign scopes. `TOP_K * 4 = 32` would have covered both observed cases.

Three documents assert the opposite:
- `docs/adr/0034-...md:33` — "trims back to `TOP_K`. Offer width is unchanged."
- `README.md:322` — "offers still a full 8 rows"
- `openwiki/architecture/enforcement-gate.md:83` — "so offer width is unchanged"

The ADR's `:155` phrasing ("every probe still returning a full 8 rows") is true of its own six probes; the generalisation at `:33` and in openwiki is false.

Consequence is bounded — a narrower menu, every row invocable, no crash — but it is a real behavioural regression stated as an invariant.

### 3. Kill-switch byte-identity — **CONFIRMED**

Differential against `git show 6203001:hooks/scripts/enforcer.py` with `ENFORCER_CROSS_HARNESS=0`, capturing every outbound payload:

```
old calls: 2   new calls: 2
REQUEST PAYLOADS IDENTICAL: True
RENDER IDENTICAL: True
```

`limit` back to `TOP_K`, `with_payload` back to `["name","description"]`, no annex query, no annex block. Selftest case (12) pins the same two assertions independently.

### 4. `_foreign_scopes()` fail-silent — **CONFIRMED**

Six filesystem states for `~/.codex/skills` x both harness directions, twelve imports, zero exceptions:

```
symlink  False -> ('codex-plugin','codex-personal') | True -> ('plugin',)
broken   False -> ('codex-plugin','codex-personal') | True -> ('plugin','personal')
file     False -> ('codex-plugin','codex-personal') | True -> ('plugin','personal')
realdir  False -> ('codex-plugin','codex-personal') | True -> ('plugin','personal')
absent   False -> ('codex-plugin','codex-personal') | True -> ('plugin','personal')
loop     False -> ('codex-plugin','codex-personal') | True -> ('plugin',)
```

A symlink loop makes `.resolve()` raise `OSError`, caught, `shared = True` -> `personal` stays in the offer. That is the documented safe direction and it is what happens. The broken/file/absent cases correctly treat the roots as distinct, which is right: if `~/.codex/skills` is not a live pointer at `~/.claude/skills`, then `personal`-scoped files sit somewhere Codex cannot load them.

Live: `readlink ~/.codex/skills` -> `/Users/thinhkhuat/.claude/skills`, so this machine takes the shared branch.

*(The function itself is clean. The import-time crash lives one statement away, at `_SETTINGS_LAYERS` — see blocking defect 1.)*

### 5. Codex direction — **REFUTED as fully safe** (reasoned, not executed)

I cannot run under Codex, so this is derived from three files I did read, not from a run.

Under Codex with **distinct** personal roots — copied rather than symlinked, a normal setup — a skill present in *both* `~/.claude/skills/foo` and `~/.codex/skills/foo`:

1. `skills_discovery.SKILL_DIRS` is `[PERSONAL_ROOT, PROJECT_ROOT, CODEX_PERSONAL_ROOT, CODEX_PROJECT_ROOT]` (`skills_discovery.py:48-49`). That order is harness-independent — Codex sessions walk `~/.claude/skills` first too.
2. `discover_skills` is `found.setdefault(...)`, first writer wins, so the Claude copy claims the name and `_scope_for` tags it `personal`.
3. Under Codex `_foreign_scopes()` returns `("plugin", "personal")`.
4. `_invocable_twin` short-circuits to `False` on `UNDER_CODEX` (`enforcer.py:190`) — the rescue is deliberately disabled in that direction.

Net: a skill Codex can invoke at `~/.codex/skills/foo` is dropped from the Codex installed offer and annexed as "NOT invocable here". That is pass-1 defect 1, mirrored, with the rescue switched off.

The `UNDER_CODEX` short-circuit is justified in the docstring for `plugin` scope (Claude's cache genuinely is not on Codex's load path). The justification does not extend to `personal`, which was added to `FOREIGN_SCOPES` in this same commit. No effect on this machine (symlinked). No effect on a machine with no `~/.codex/skills` (nothing to rescue). It bites the copied-roots configuration.

### 6. Payload index — **CONFIRMED correct, NOT IN EFFECT**

Safety and idempotency verified on a scratch server-mode collection I created and deleted (the live collection was not touched):

```
create name: ok   create tier: ok   create scope: ok
re-create scope (idempotency): ok
schema: ['name','scope','tier']
```

Creating on an existing populated collection succeeds and takes effect without a rebuild; a re-create is a no-op, and the per-field `try/except` means an existing `name` index cannot block `tier`/`scope`.

But the live collection is unchanged:

```
points: 24893
payload_schema: {"name": {"data_type": "keyword", "points": 24893}}
```

`_ensure_collection()` has exactly one caller — `build_index()` at `server.py:613` — so the new indexes appear only at the next reindex. Nothing in the commit triggers one. It self-heals via the SessionStart auto-reindex, but until then the annex query's `must scope` filter is still a linear scan inside the 100 ms cap, which is the condition this change exists to remove.

Also: the pytest suite exercises `_ensure_collection` only against local Qdrant, which prints `UserWarning: Payload indexes have no effect in the local Qdrant`. The tests therefore prove the call does not raise; they do not prove the indexes are built.

### 7. `analyze.py` — **CONFIRMED**

- `--selftest` passes, including the exact-name conversion test and subagent exclusion.
- Live ledger: 5,144 events, **exit 0**, no throw. The `x-harness annex:` line correctly does not print — there are genuinely 0 `xh` rows on disk (`grep -c '"xh"'` = 0), because the deployed enforcer is still `6203001`.
- **No double-count.** An event carrying both `ext` and `xh` is counted once by each function, which is correct — two distinct annexes, two independent metrics: `external (1,1,1,1)` / `x-harness (1,1,1,1)`.
- Replaying the real ledger with `xh` injected onto every `ext`-bearing offer: `x-harness (26, 52, 0, 11)`, `external (26, 52, 0, 11)` — identical shape, neither perturbing the other.
- Malformed input does not throw: `xh: "notalist"`, `xh: [[], None, "str", ["ok",0.5]]`, `sid: None`, `xh: [["n"]]` all survive. One cosmetic flaw: `n_rows = sum(len(e.get("xh") or []))` does not type-check, so a string `xh` contributes its character count (my fixture inflated 6 rows to 14). The enforcer never writes that shape; same pattern already exists in `_external_annex_stats`.

### 8. Regressions from the fix

**Displacement invariant — still CONFIRMED.** `_foreign` is computed after `cands` is final and flows only into `_ranked_mandate(foreign=)` and `_append_offer(xh=)`. `_retrieve_foreign` additionally skips invocable twins, so no name can appear in both blocks. Selftest case (12) pins that (`"cross-harness: below-floor or twin row must not render in the annex"`).

**The `break` in `_retrieve` — harmless.** `out` is appended in group order (score-descending) and `break`s at `TOP_K`; that is exactly `[:TOP_K]`. No reordering, no side effect.

**`%`-share pool — still CONFIRMED.** `total = sum(s for (_n,_d,s) in cands)` is installed-only; the foreign block renders no percentage; selftest pins it.

**Fail-silent — BROKEN.** See defect 1.

**Test suite** — `76 passed` in 166.19s. `enforcer --selftest` OK, `analyze --selftest` OK, `driftcheck` exit 0.

## Ranked defects

### 1. BLOCKING — `Path.cwd()` at import breaks the fail-silent contract (new regression)

`enforcer.py:169-171`:

```python
_SETTINGS_LAYERS = (Path.home() / ".claude" / "settings.json",
                    Path.cwd() / ".claude" / "settings.json",
                    Path.cwd() / ".claude" / "settings.local.json")
```

Module scope. Outside `main()`'s `try`. `Path.cwd()` calls `os.getcwd()`, which raises `FileNotFoundError` when the working directory has been removed.

Failure scenario, executed:

```
$ cd <dir> && rmdir <dir> && echo '{"session_id":"...","prompt":"..."}' | python enforcer.py
  File ".../pathlib.py", line 1216, in absolute
    cwd = os.getcwd()
FileNotFoundError: [Errno 2] No such file or directory
EXIT=1
```

Same command against `6203001`:

```
{"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "SKILL-FIRST ..."}}
PREV_EXIT=0
```

A full offer, exit 0. This is a clean before/after regression.

AST audit of statements that execute at import confirms these are the only two: lines 392/396 also call `Path.cwd()` but sit inside a function body, reached only under `main()`'s guard.

Reachability is not exotic. This repo ships worktree tooling and its own `CLAUDE.md` discusses worktrees being deleted out from under a session. Any session whose cwd is removed — worktree deleted, scratch dir cleaned, `rm -rf` of a build dir the shell was parked in — emits a Python traceback on **every** subsequent prompt and loses the offer every time. Exit 1 on `UserPromptSubmit` does not block the turn (only exit 2 does), so this degrades rather than halts, but the module docstring's contract is explicit: "FAIL-SILENT — any error exits 0", "never crashing", "telemetry must never surface".

`Path.home()` on line 169 is the same shape (raises `RuntimeError` when home cannot be resolved). Far less reachable, and lines 299/348/361 already do it pre-existing — but the whole tuple wants one guard.

Fix direction: build `_SETTINGS_LAYERS` lazily inside `_local_plugin_ids()`, which already has a per-file `try/except`, or wrap the tuple construction.

### 2. HIGH — the unknown-twin path fails toward the harm it was built to prevent

Proven in section 1(a)/(b): both `LOCAL_PLUGIN_IDS is None` and `LOCAL_PLUGIN_IDS == set()` cause every foreign-scoped row to be dropped and re-labelled "NOT invocable here". The docstring promises the opposite, and the ADR rests the whole redesign on that promise.

Failure scenario: `~/.claude/settings.json` is being rewritten by Claude Code as the user toggles a plugin; the hook reads a truncated file; no project `.claude/settings.json` exists. `LOCAL_PLUGIN_IDS = None`, and for that turn all 24 `agent-skills:*` skills — invocable, in the catalog — are removed from the offer and told not to use the Skill tool. Exactly pass-1 defect 1, for one turn, with no signal.

Second, more persistent scenario: a user whose `~/.claude/settings.json` has no `enabledPlugins` block at all. `set()`, permanently, every turn.

Fix direction: make the drop conditional on positive knowledge — `if CROSS_HARNESS and LOCAL_PLUGIN_IDS is not None and scope in FOREIGN_SCOPES and not _invocable_twin(name)` — so unknown genuinely filters nothing, and treat "key absent from `enabledPlugins`" as enabled, matching `skills_discovery.py:175`.

### 3. MEDIUM — offer under-fill, asserted in three docs as impossible

Measured 5 and 7 rows where `TOP_K` is 8; 30 and 25 groups needed against a `RETRIEVE_LIMIT` of 24. `docs/adr/0034-...md:33`, `README.md:322` and `openwiki/architecture/enforcement-gate.md:83` all state width is unchanged. Either raise the multiplier (32 covers both observed cases) or correct all three sentences.

### 4. MEDIUM — Codex direction drops invocable `personal` skills with no rescue

Section 5. Reasoned from `skills_discovery.py:48-49`, `_scope_for`, and the `UNDER_CODEX` short-circuit at `enforcer.py:190`. Inert on this machine (symlinked roots); live on any machine with copied personal roots. The short-circuit's stated justification covers `plugin`, not the `personal` entry this commit added.

### 5. LOW — payload indexes shipped but not applied

Live `claude_skills` still has only `name`. Correct and idempotent when it runs; runs only at the next `build_index()`. Nothing in the commit forces one, and the tests cannot prove the index is built because they use local Qdrant.

### 6. LOW — "absent from `enabledPlugins`" is treated as disabled

Contradicts `skills_discovery.py:175` in the same repo. 1 of 39 installed plugins affected today.

### 7. LOW — the twin test reads enablement, not installation

Docstring says "installed and enabled"; the code checks only settings. Safe direction, inaccurate claim.

### 8. LOW — marketplace-name collision collapses to a bare plugin id

`foo@mktA=true, foo@mktB=false` -> arbitrary winner by dict order; proven to lose the enabled one.

### 9. LOW — "18 of 48" measured as 17 of 48

My six prompts give `before=17/48, after=0/48`. The "-> 0" half reproduces exactly. The ADR does not list its six prompts, so the one-row gap is unattributable rather than wrong.

### 10. LOW — `n_rows` in `_cross_harness_annex_stats` does not type-check `xh`

A string `xh` contributes its character count. Unreachable from the enforcer; mirrors the existing `_external_annex_stats` shape.

## What I did not check

- **Any actual Codex run.** Defect 4 is reasoned from source, not executed. I have no Codex install to run under, and I did not simulate one beyond forcing `CLAUDE_PLUGIN_ROOT`.
- **The deployed copy.** `~/.claude/plugins/cache/skill-concierge/skill-concierge/0.24.0/hooks/scripts/enforcer.py` md5-matches `6203001` exactly, so nothing in `7c3d89d` is live. I did not install it and did not verify post-install behaviour.
- **Latency after the payload indexes exist.** I measured nothing post-index because the index does not exist yet on the live collection. Pass-1's numbers still stand for the current state.
- **Whether `create_payload_index`'s background build perturbs query latency while running** on a 25k-point collection.
- **openwiki link integrity** beyond what `driftcheck.py` covers, and the `openwiki/architecture/retrieval-engine.md` prose (I read only the width claim).
- **`_glob_both_depths` de-dup fix** — I confirmed the code now de-duplicates and the docstring concedes the counterexample, and the 76-test suite passes, but I did not re-run my pass-1 pathological fixture against it.

---

Status: DONE_WITH_CONCERNS
Summary: Both pass-1 blockers are genuinely fixed and verified live — 236 of 236 installed offer rows across thirty probes are invocable, the twin rescue restores all 24 `agent-skills:*`, and the harness-detection inversion is gone and pinned. The fix introduced one new blocking regression (`Path.cwd()` at import breaks fail-silent; proven crash where `6203001` returns a full offer) and one high-severity inverted failure direction (the unknown-twin path filters everything foreign, the opposite of its docstring).
Concerns/Blockers: (1) `enforcer.py:169-171` calls `Path.cwd()` at module scope outside every guard — deleted cwd yields exit 1 plus a traceback on every turn; `6203001` survives the same test. (2) `LOCAL_PLUGIN_IDS is None` and `== set()` both drop every foreign row instead of none, restoring pass-1 defect 1 whenever settings are unreadable or carry no `enabledPlugins` block. (3) Offer under-fill is real (5 and 7 rows measured) while three documents assert width is unchanged; `TOP_K*3` needs to be `TOP_K*4`. (4) Under Codex, `personal`-scoped skills that Codex can invoke are dropped with the twin rescue short-circuited off. (5) The new payload indexes are not on the live collection and nothing in the commit triggers the reindex that would create them. Nothing here is live yet — the deployed enforcer is still `6203001` — so this is a follow-up commit, not an incident.
