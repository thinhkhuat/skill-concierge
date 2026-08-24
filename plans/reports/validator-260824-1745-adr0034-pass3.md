# Opus Validation Report — ADR-0034 pass 3 (commit ed0e609)

**Subject:** implementation (committed, `ed0e609`, diffed against `7c3d89d`)
**Scope:** `hooks/scripts/enforcer.py`, `scripts/analyze.py`, ADR-0034 / CHANGELOG / README / AGENTS.md / openwiki
**Verdict:** **PASS with advisories** — both pass-2 blockers fixed and verified; no new blocker found
**Date:** 2026-08-24
**Evidence:** 2 source files, live Qdrant (24,893 points), 60 live retrieval probes (30 ordinary + 30 adversarial), 14 hostile-manifest fixtures, 9 hostile-env hook runs, before/after controls against `6203001` and `7c3d89d`

## Executive Summary

Both pass-2 blockers are genuinely fixed, and I could not break either. The deleted-cwd crash is gone — the hook now imports and emits a full offer from a removed working directory, exit 0, no traceback. The unknown-manifest path now filters nothing, proven end-to-end. The `_invocable_plugin_ids()` redesign survived every malformed input I could construct, and it fixes the absent-key, enablement-vs-installation, and collision defects with a demonstrable change in the live id set. Two things remain: `TOP_K * 4` is still not universally sufficient (I found a new counterexample), though the docs now correctly call it headroom rather than a guarantee; and `README.md:322` still describes the old symlink-conditional `_foreign_scopes()` that this commit deleted.

## Attack-by-attack

### 1. `_invocable_plugin_ids()` — **CONFIRMED**

Fourteen hostile inputs, zero raises:

```
plugins is a dict of NON-LISTS     -> 3 ids ['a','b','c']
key with NO @                      -> 1 ids ['bare']
key is not a string (int)          -> 2 ids ['5','x']
plugins is a LIST                  -> None
plugins key MISSING                -> None
top level is a list                -> None
corrupt json                       -> None
empty plugins dict                 -> set() [empty]
huge manifest (20k keys)           -> 20000 ids   (import 5.1 ms)
env points at a DIRECTORY          -> None
settings.json symlink LOOP         -> 12 ids
HOME unset                         -> 12 ids
HOME unreadable (chmod 000)        -> None
non-bool enabledPlugins values     -> ['zabsent','zfalsestr','zone']
```

**None means "filter nothing", proven end-to-end** with a stubbed transport and a mixed result set:

```
UNKNOWN manifest (corrupt) -> ids=None    offer=['agent-skills:debugging-and-error-recovery',
                                                 'vercel:vercel-agent','cx-only-skill','local-skill']
EMPTY manifest             -> ids=set()   offer=['local-skill']
agent-skills installed     -> ids=1       offer=['agent-skills:debugging-and-error-recovery','local-skill']
real manifest              -> ids=12      offer=['agent-skills:debugging-and-error-recovery','local-skill']
```

Every foreign row — `codex-plugin` *and* `codex-personal` — survives the None case. That is the exact inversion pass-2 refuted, and it is gone.

**`set()` now behaves correctly and differently from None.** A readable manifest with nothing installed means nothing is invocable, so dropping every foreign row is right, and it does. The two branches are no longer conflated: `_invocable_twin` short-circuits on `not INVOCABLE_PLUGIN_IDS` (covering both), while the *caller* drops only on `INVOCABLE_PLUGIN_IDS is not None`.

Three factual notes, none of them defects — each fails in the row-keeping direction:

- `not bool(v)` makes the JSON *string* `"false"` truthy, i.e. enabled. Claude Code writes real booleans, and `skills_discovery._installed_plugin_roots` uses the same truthiness test.
- The manifest's `installPath` is never checked for existence — "installed" means the key is present. Weaker than `skills_discovery`, safe direction.
- The reverse also holds: `caveman@caveman` has a real cache directory at `~/.claude/plugins/cache/caveman/caveman/` but **no key** in `installed_plugins.json`, so it is treated as not installed. An under-approximation that could refuse a legitimate twin. Inert here — see claim 4.

### 2. Did the crash move? — **CONFIRMED FIXED, and it did not move**

AST audit of statements that actually execute at import (function bodies excluded), for every filesystem-touching call:

```
line 179  home()     guarded_by_try=False   [_INSTALLED_PLUGINS_JSON = Path(os.environ.get(
line 328  home()     guarded_by_try=False   [LOG_DIR = Path(os.environ.get(
line 337  resolve()  guarded_by_try=False   [_KEEPOFF_PATH = Path(os.environ.get(
line 377  home()     guarded_by_try=False   [_SIDECAR_PATH = Path(os.environ.get(
line 390  home()     guarded_by_try=False   [_NEXT_SKILLS_OVERRIDES = Path(os.environ.get(
line 498  resolve()  guarded_by_try=False   [_THRESHOLDS_PATH = Path(os.environ.get(
line 531  resolve()  guarded_by_try=False   [_ROUTES_PATH = Path(os.environ.get(
```

No `Path.cwd()` at import. Line 179 is the only new one and it is `Path.home()`, the same shape as the six pre-existing ones. The `resolve()` calls operate on `Path(__file__)`, which is absolute under the `${CLAUDE_PLUGIN_ROOT}` wiring in `hooks/hooks.json`.

Deleted-cwd re-test:

```
IMPORT OK  INVOCABLE_PLUGIN_IDS= 39
IMPORT_EXIT=0
{"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "SKILL-FIRST ...
RUN_EXIT=0
```

Full hostile-environment battery, end-to-end hook, all exit 0 with a rendered offer and no traceback on stderr: symlink loop, nonexistent path, empty string, relative path, 4000-char path, a Codex-shaped `CLAUDE_PLUGIN_ROOT`, empty stdin, garbage stdin, `SKILL_INSTALLED_PLUGINS=/dev/null`.

**Residual, and it is NOT from this commit.** `_visible_sidecar_names()` calls `Path.cwd()` unguarded at line 421. From a deleted cwd, a session that already has a chain seed loses the entire offer — `_chain_hint(sid)` is evaluated before `_inject`, so its raise is swallowed by `main()`'s outer `try` and the turn injects nothing. The fail-silent contract holds (exit 0, clean stderr); the offer does not. Controlled against pre-ADR-0034:

```
ed0e609:  _chain_hint with a seed RAISED: FileNotFoundError  |  main() rc=0  injected=False  bytes=0
6203001:  _chain_hint with a seed RAISED: FileNotFoundError  |  main() rc=0  injected=False  bytes=0
```

Byte-for-byte the same behaviour before ADR-0034 existed. Pre-existing, reported for completeness, not attributable here.

Same root cause explains why `--selftest` still exits 1 from a deleted cwd: the traceback runs `enforcer.py:1320` (selftest case 9) → `_chain_hint:475` → `_visible_sidecar_names:421`. Case (12) is not involved, and `7c3d89d` fails identically.

### 3. Positive-knowledge drop completeness — **CONFIRMED**

The `codex-personal` premise in the new `_foreign_scopes()` docstring checks out against source: `SKILL_DIRS` is `[PERSONAL_ROOT, PROJECT_ROOT, CODEX_PERSONAL_ROOT, CODEX_PROJECT_ROOT]` (`skills_discovery.py:48-49`) and `discover_skills` is `found.setdefault` (first writer wins), so any name present in both personal roots is claimed as `personal`. A surviving `codex-personal` row is therefore genuinely unreachable from Claude, and dropping it on positive knowledge is correct. With None, nothing drops — verified in claim 1.

One scope is not covered either way: `codex-project:<...>` is absent from `FOREIGN_SCOPES`, so a Codex project skill would sit in a Claude offer as non-invocable noise. That is pre-ADR-0034 behaviour and inert on this machine — the live scope census is `catalog:antigravity 1928 / personal 350 / codex-plugin 205 / plugin 58`, with no `codex-project` points at all.

### 4. Union semantics — **CONFIRMED structurally, NOT exercised by live data**

The union change is correct by construction: `disabled_by_key` is keyed on the full `<id>@<marketplace>` string and looked up with the full string, so no collision occurs in the *lookup*; the bare-id set comprehension then unions across marketplaces. But there is nothing to test it on here:

```
installed keys: 39 | distinct bare ids: 39
```

No two installed plugins share a bare id, so the union branch never fires on this machine. I am reporting that as untested rather than verified.

What *did* change, and it is exactly the two defects it was meant to fix:

```
pass-2 set: 12  ['agent-skills','caveman','claude-hud','effort-gate','i-have-adhd',
                 'mattpocock-skills','memsearch','openwiki','selfcheck-gate',
                 'skill-concierge','smgrep','superpowers-developing-for-claude-code']
pass-3 set: 12  [... 'fablize' ... ] (no 'caveman')
GREW BY:   ['fablize']   — absent from enabledPlugins, so enabled by default (fixes 1(c))
SHRANK BY: ['caveman']   — enabled in project settings, absent from the manifest (fixes 1(d))
EXCLUDED (explicitly disabled): 27
```

**No genuinely non-invocable row re-entered the offer.** Neither `fablize` nor `caveman` appears among the 21 distinct `codex-plugin` bare ids in the index, so the composition change is behaviourally inert today. The 30-prompt sweep confirms:

```
offer-size distribution: {8: 30}
TOTAL rows: 240 | genuinely non-invocable: 0
```

### 5. `TOP_K * 4` under-fill — **PARTIALLY REFUTED**

My own 30-prompt set from pass 2, including both prior failures, is now clean: `{8: 30}`, zero under-fill.

But x4 is not universally sufficient. Thirty fresh prompts aimed squarely at the namespaces where the Codex cache is densest (vercel, cloudflare, gmail, google-drive, omo, codexclaw, browser, components) produced one new counterexample:

```
offer-size distribution: {7: 1, 8: 29}
UNDER-FILLED: [('vercel edge config feature flags', 7, needed 35)]
top-5 hungriest (groups needed to fill 8):
   need=35  got=7  vercel edge config feature flags
   need=26  got=8  vercel domains dns configuration
   need=25  got=8  cloudflare d1 database query
   need=24  got=8  next.js middleware edge runtime
   need=19  got=8  last30days changelog digest
```

`RETRIEVE_LIMIT` is 32; that query needs 35.

This is materially different from the pass-2 finding. There, three documents asserted "offer width is unchanged" while the code violated it. Here the ADR (`:33-38`), CHANGELOG, AGENTS.md and openwiki all say **headroom, not a guarantee**, and the code comment states under-fill is "the accepted degradation rather than a bug to pad around". The behaviour now matches the documentation. Rate across everything I ran: **1 of 60 prompts, short by one row.**

### 6. Codex direction — **CONFIRMED, strictly pre-0034 noise**

`_foreign_scopes()` is now `("plugin",) if UNDER_CODEX else ("codex-plugin", "codex-personal")` — no filesystem call, no symlink probe. Under Codex, `personal` and `project:` rows stay in the offer. Where the personal roots are distinct, some Claude-only personal skills will appear that Codex cannot invoke. That is exactly the pre-ADR-0034 union noise, not something worse, and it is the direction the docstring argues for: keeping a noisy row beats telling the agent a skill it *can* invoke is uninvocable.

Residual, hypothetical and unverified: `plugin` is unconditionally foreign under Codex, with the twin rescue short-circuited off. If an operator symlinked the two plugin caches together, Codex-invocable rows would be dropped and mislabelled — the same shape as the `personal` case this commit removed. I have no evidence anyone does that, and on this machine the caches are separate real directories (`~/.claude/plugins` 2.7G, `~/.codex/plugins` 1.7G, neither a symlink). Noted as the residual asymmetry, not as a finding.

### 7. Regressions from this commit — **none found**

- **Kill-switch byte-identity vs `6203001`:** `REQUEST PAYLOADS IDENTICAL: True`, `RENDER IDENTICAL: True`, 2 calls each.
- **Displacement / %-share / render:** foreign block present, `%` on installed rows only and absent from the foreign block, `[codex]` marker and `get_skill` instruction present, foreign name absent from the installed lines.
- **Case (12) cwd handling:** `_selftest()` returns 0 and leaves the process where it started — `cwd preserved: True`. `finally: os.chdir(_cwd)` covers every failure inside the block. `_cwd = os.getcwd()` and `tempfile.mkdtemp()` sit outside the `try`, so `_tmpd` leaks if `os.chdir` raises — cosmetic, in a dev-only command.
- **`import tempfile` added at module scope**, against the docstring's "no heavy imports". Measured: full enforcer import `24.7 ms` on `7c3d89d` vs `24.9 ms` on `ed0e609` — within noise, because `tempfile`'s dependencies are already pulled in by `urllib.request`. No cost.
- **`analyze.py` `n_rows` walrus fix:** correct. Comprehension clause order evaluates the `if` before the yield expression; `r` leaks into the enclosing function scope, which is standard and harmless.
- **Test suite:** `76 passed` in 161.25s. `enforcer --selftest` OK, `analyze --selftest` OK, `driftcheck` exit 0.

### 8. Docs vs code — **one defect**

**"18 of 48 -> 0" now reproduces exactly.** The ADR names its six prompts, so I ran precisely those:

```
debug this failing test              OFF 5/8  ON 0/8
review my code changes               OFF 0/8  ON 0/8
docker build is broken               OFF 4/8  ON 0/8
write a plan for a new feature       OFF 1/8  ON 0/8
audit the security of this endpoint  OFF 3/8  ON 0/8
help me plan a database migration    OFF 5/8  ON 0/8
TOTAL: 18 of 48 -> 0 of 48
```

Exact. My pass-2 count of 17 was a different sixth prompt; naming them resolved it.

**`README.md:322` is stale — the only place.** It still reads:

> Foreign scopes are derived per harness (`codex-personal` / `personal` included only when the two personal roots are distinct dirs)

`_foreign_scopes()` on `ed0e609` has no conditionality and no filesystem call: `codex-personal` is unconditional, and `personal` is never foreign. AGENTS.md, the ADR, CHANGELOG and openwiki were all updated correctly for this change; README was not. Given this repo's `NO STALENESS` rule and its doc-parity guard (which does not cover prose), worth a follow-up line.

**"160 rows, 0 non-invocable, 8 rows every time"** — the 20 prompts are not listed, so unlike the six I cannot reproduce it. My 30-prompt sweep is consistent (240 rows, 0 non-invocable, 8 every time). The phrase "8 rows every time" reads as absolute inside a validation bullet, and my adversarial probe found a 7-row case; the ADR does carry the correct "headroom, not a guarantee" caveat 150 lines earlier, so this is a phrasing nit rather than a contradiction.

Everything else checked out: `TOP_K*4` in ADR/CHANGELOG/AGENTS/openwiki matches `RETRIEVE_LIMIT = TOP_K * 4`; the CHANGELOG's description of union resolution, absent-key-is-enabled, unknown-drops-nothing, and the Codex `personal` reasoning all match the code as written.

## Ranked defects

### 1. ADVISORY — `README.md:322` describes the deleted symlink-conditional `_foreign_scopes()`

Doc-vs-code mismatch introduced by this commit's own simplification. Concrete failure: a reader (or agent) trusting the README concludes `personal` can be foreign under Codex and that the two personal roots are probed at import — neither is true on `ed0e609`. Sole straggler; four other documents are correct.

### 2. ADVISORY — `TOP_K * 4` still under-fills in the densest foreign domain

`"vercel edge config feature flags"` returns 7 rows and needs 35 groups. 1 of 60 prompts. Now a documented, accepted degradation rather than a contradicted invariant, so this is a note on the residual rate, not a correctness finding. `TOP_K * 5 = 40` would cover the observed worst case; whether that is worth the extra groups is a judgement call, not a defect.

### 3. ADVISORY (pre-existing, not this commit) — `_visible_sidecar_names()` silently costs the whole offer from a deleted cwd

`Path.cwd()` at `enforcer.py:421`, reached via `_chain_hint`, which is evaluated before `_inject`. A session with a chain seed running from a removed working directory injects nothing, exit 0. Proven identical on `6203001`. If the deleted-cwd scenario is worth guarding at all — and this commit decided it was — this is the other half of it.

### 4. NOTE — union branch untested by live data

39 installed keys, 39 distinct bare ids: no marketplace collision exists here, so the fix for pass-2's defect 8 is verified by reading, not by running.

### 5. NOTE — `_invocable_plugin_ids()` trusts manifest keys, not installPath

A plugin physically installed but absent from `installed_plugins.json` (live example: `caveman@caveman`, which has a cache directory) is treated as not invocable. Would refuse a legitimate twin; inert here because no `caveman:*` row carries a foreign scope.

### 6. NOTE — `codex-project:` is never foreign

A Codex project skill would remain in a Claude offer as non-invocable noise. Pre-ADR-0034 behaviour; no such points exist in the live index.

### 7. NOTE — selftest case (12) leaks a tempdir if `os.chdir` raises

`_tmpd = tempfile.mkdtemp()` is outside the `try`; only `os.rmdir` inside it removes the directory. Dev-only command, cosmetic.

## What I did not check

- **Any actual Codex run.** Claims 3 and 6 are reasoned from `skills_discovery.py:48-49`, `_scope_for`, and the `UNDER_CODEX` short-circuit — not executed under Codex.
- **The ADR's own 20-prompt sweep.** The prompts are not listed; I ran 60 of my own instead and report those numbers as mine.
- **The deployed copy.** I did not re-check whether `ed0e609` has been installed; as of pass 2 the plugin cache held `6203001`. Nothing in this pass assumes it is live.
- **Payload-index effect.** Still not applied to the live collection (pass-2 finding 5, documented in the ADR as landing at the next reindex). I did not force a reindex and did not re-measure latency.
- **The marketplace-collision branch under real conditions** — no collision exists on this machine.
- **openwiki link integrity** beyond `driftcheck.py`, and `openwiki/architecture/retrieval-engine.md` prose.
- **`_glob_both_depths`** — unchanged since pass 2; I did not re-run the pathological fixture.

---

Status: DONE_WITH_CONCERNS
Summary: Both pass-2 blockers are fixed and verified — the hook imports and emits a full offer from a deleted working directory (exit 0, no traceback, controlled against `6203001` and `7c3d89d`), and an unreadable manifest now filters nothing, proven end-to-end on both foreign scopes. `_invocable_plugin_ids()` survived fourteen malformed inputs without raising, and its live id set changed exactly as the absent-key and enablement-vs-installation fixes predict. No new blocker.
Concerns/Blockers: No blockers. Three advisories: (1) `README.md:322` still describes the symlink-conditional `_foreign_scopes()` this commit deleted — the only stale copy, with AGENTS.md/ADR/CHANGELOG/openwiki all correct. (2) `TOP_K*4` still under-fills on `"vercel edge config feature flags"` (7 rows, needs 35 groups), 1 of 60 prompts — now a documented accepted degradation rather than a contradicted invariant. (3) Pre-existing and not from this commit: `_visible_sidecar_names()` calls `Path.cwd()` unguarded, so a session with a chain seed running from a deleted cwd silently injects no offer at all; identical on `6203001`. Two things I could not test rather than chose not to: the marketplace-union branch (no collision exists on this machine) and anything under a real Codex harness.
