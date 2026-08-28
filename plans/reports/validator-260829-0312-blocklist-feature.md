# Opus Validation Report

**Subject:** implementation — the v0.39.0 blocklist disable-tier feature (ADR-0046), four-layer enforcement
**Scope:** full change set (18 modified + 5 new paths), all four enforcement layers, tests/selftests, live state, docs/version parity, defect hunt
**Verdict:** FAIL (one blocking defect: `scripts/blocklist.py selftest` exits 1 on this machine; every other criterion passes)
**Date:** 2026-08-29
**Evidence Files Examined:** 23 (every file in the claimed change set, read directly or via `git diff`)

## Executive Summary

The feature is built as claimed and works: the PreToolUse guard, enforcer, engine, and
apply-overrides layers all enforce identical name semantics with correct fail-open behavior,
and docs/version parity is fully in sync. One blocking defect: the standalone
`blocklist.py selftest` fails on any machine where the real
`~/.claude/skill-concierge/blocklist.json` exists, because its final "absent blocklist" leg
sets `SKILL_CONCIERGE_HOME` mid-process while `_keepon.HOME` is frozen at import — the test
leaks to the real home file. Additionally, the claimed live state (`["resume-session"]`) is
stale: the live file holds 15 entries (edited 03:16, after the 03:12 handoff).

## Observable Truths

| # | Claim | Status | Evidence |
|---|-------|--------|----------|
| 1 | Change set = 18 modified + 5 new paths as listed | ✓ | `git status --porcelain`: 18 ` M` + 5 `??` (`docs/adr/0046…`, `hooks/scripts/skill_guard.py`, `scripts/blocklist.py`, `skills/blocklist/`, `tests/test_blocklist.py`) |
| 2 | Guard denies matching Skill calls via `hookSpecificOutput.permissionDecision: "deny"` | ✓ | 12 stdin probes: bare match, qualified twin, qualified-exact, leading-slash all deny; non-Skill tool, non-match, empty tool_input, invalid stdin all silent exit 0 |
| 3 | Guard pass-through on absent/corrupt file and `SKILL_BLOCKLIST=0` | ✓ | probes: absent file → no output; `NOT JSON{{{` → no output; `SKILL_BLOCKLIST=0` → no output; all exit 0 |
| 4 | Matcher semantics identical in guard / enforcer / engine | ✓ | `skill_guard.py:62-66` (`entry == name` or colon-free entry == `name.rsplit(":",1)[1]`); `enforcer.py:657-662`; `server.py:131-143`; `apply-overrides.py:75-83`. Suffix-after-last-colon can never contain a colon, so qualified entries are exact-only in all four — semantically identical (verified by reading + probes at each layer) |
| 5 | Enforcer filters every candidate path | ✓ | `_blocked(` call sites: main drop `enforcer.py:1626` via `_drop_blocklisted` (`:666-672`, rides the `dropped` ledger field at `:1627-1628`); chain-hint seed `:876` + successors `:884`; deterministic hits `:983`; foreign annex `:1237`; ROUTE successors `:1397`. Both `_route_of` call sites (`:1462`, `:1697`) take post-filter seeds |
| 6 | Engine: search filters AFTER fusion, get_skill refuses BEFORE any read | ✓ | `server.py:807` filters `_fuse_ranked(...)` output; `server.py:822` refuses before `_qdrant.retrieve` (`:829`) and the `discover_skills()` walk |
| 7 | Engine reads CONTENT live per call | ✓ | `server.py:131-143`: `_blocked()` re-reads the file and re-checks `SKILL_BLOCKLIST` on every call. Live proof: deployed-module probe flipped `blocked('resume-session')` True→False by setting the env var mid-process |
| 8 | Deployed venv engine carries the filter | ✓ | `diff -q vendor/.../server.py ~/.claude/skill-concierge/venv/lib/python3.12/site-packages/skill_search/server.py` → IDENTICAL; `grep -c "ADR-0046"` → 2 |
| 9 | All layers fail-open | ✓ | `skill_guard.py:116-121` catch-all `Exception` → exit 0; `:88-91` unreadable stdin → 0. `enforcer.py:644-653` catches OSError/UnicodeError/ValueError/AttributeError/TypeError. `server.py:135-137` same class. `apply-overrides.py:64-72` same class |
| 10 | `SKILL_BLOCKLIST=0` kills the feature at every layer | ✓ | `skill_guard.py:85`; `enforcer.py:645-646`; `server.py:132-133`; `apply-overrides.py:66-67`; each verified by probe or selftest |
| 11 | `SKILL_CONCIERGE_BLOCKLIST` exact-file seam everywhere | ✓ | `skill_guard.py:52-54`; `enforcer.py:639-642`; `server.py:126-129`; `_keepon.py:46-48`; exercised by every probe/selftest |
| 12 | apply-overrides forces blocked keep-on names name-only, keep-on.json untouched | ✓ | `apply-overrides.py:223-227` strip in main; selftest pins block→name-only and restore→`"on"` without touching keep-on.json; blocklist.py selftest + tests pin CLI remove round-trip |
| 13 | driftcheck exit 0 | ✓ | `python3 scripts/driftcheck.py driftcheck.json` → "IN SYNC", exit 0 |
| 14 | All 4 manifests at 0.39.0 | ✓ | `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `.codex-plugin/plugin.json`, `package.json` all `"version": "0.39.0"` |
| 15 | Docs consistent (CHANGELOG/README/AGENTS/CLAUDE/openwiki/VENDORED) | ✓ | All reviewed via `git diff`; no stale "one deliberate exception" anywhere (AGENTS.md now says "The two deliberate exceptions"); ADR indexed in `docs/adr/README.md:59` |
| 16 | pytest 19 pass | ✓ | `19 passed in 0.73s`, exit 0 |
| 17 | enforcer selftest green | ✓ | "enforcer --selftest OK: … + blocklist-drop (ADR-0046) + …", exit 0 |
| 18 | apply-overrides selftest green | ✓ | "selftest ok", exit 0; `_keepon.py selftest` also green |
| 19 | `blocklist.py selftest` green | ✗ | **exits 1**: `AssertionError: absent blocklist must load empty` (full trace below) |
| 20 | Live list shows exactly `["resume-session"]` | ✗ | `blocklist.py list` shows **15** entries (aside, autoresearch, checkpoint, commit, competitive-analysis, experience-skill-concierge, fact-check, git-hooks-setup, goal, read-only-mode, research, resume-session, save-session, summarize, wigolo). File mtime 03:16:34 — ~4 min after the 03:12 handoff, i.e. post-build live drift, not a code defect |
| 21 | Doctor shows Blocklist healthy | ✓ | `[✓] Blocklist  15 skill(s) disabled — ~/.claude/skill-concierge/blocklist.json` (`doctor.py:814` check, registered `:1499`) |
| 22 | hooks.json valid + PreToolUse(Skill) wired | ✓ | `python3 -m json.tool` OK; `hooks/hooks.json:52-63` matcher `"Skill"` → `skill_guard.py`, timeout 5 |
| 23 | New skill frontmatter valid, dir clean | ✓ | `skills/blocklist/SKILL.md` parses (name/description/argument-hint/license/metadata.version); dir contains only SKILL.md |

## Key Dependency Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| hooks/hooks.json:52-63 | hooks/scripts/skill_guard.py | PreToolUse matcher "Skill" | ✓ | script double-checks `tool_name == "Skill"` |
| enforcer.py main():1626 | `_drop_blocklisted`:666 | candidate drop | ✓ | rides `_dropped` ledger field |
| server.py search_skills:807 / get_skill:822 | `_blocked`:131 | row filter / body refusal | ✓ | post-fusion / pre-read respectively |
| apply-overrides.py main():223 | `_stripped_by_blocklist`:75 | keep-on strip | ✓ | runs before the router WARN check |
| scripts/blocklist.py:38 | `_keepon.blocklist_path` | path seam | ✓ | single-sourced with `SKILL_CONCIERGE_BLOCKLIST` override |
| doctor.py:1499 | `check_blocklist`:814 | CHECKS registration | ✓ | absent file = healthy; missing guard = FAIL |
| vendored server.py | deployed venv copy | pip re-copy | ✓ | byte-identical |

## Blocking Issues (FAIL)

1. **`scripts/blocklist.py selftest` exits 1 whenever the real blocklist file exists.**
   `scripts/blocklist.py:151-153` (final selftest leg):
   ```python
   del os.environ["SKILL_CONCIERGE_BLOCKLIST"]
   os.environ["SKILL_CONCIERGE_HOME"] = str(Path(td) / "home2")
   raw, names = _load()
   ```
   `SKILL_CONCIERGE_HOME` is only read at import time by `scripts/_keepon.py:23`
   (`HOME = Path(os.environ.get("SKILL_CONCIERGE_HOME", ...))`), so setting it mid-process is
   a no-op. `blocklist_path()` falls back to the frozen real home
   (`~/.claude/skill-concierge/blocklist.json`), which exists here (15 entries), so `_load()`
   returns non-empty and the assert fires. Exact observed output:
   ```
   AssertionError: absent blocklist must load empty
   TRUE_EXIT=1
   ```
   (trace: `blocklist.py", line 154, in cmd_selftest`). Environment-dependent — passes on a
   machine with no live blocklist, which is why the builder's run was green and why pytest
   (which never calls `cmd_selftest`; it uses subprocesses with env pre-set) stays green.
   Impact: acceptance criterion "all selftests green" fails; the selftest cannot be used as a
   regression gate on any machine actually using the feature. Fix (builder's side): assign
   `_keepon.HOME` directly inside the selftest, exactly as `_keepon._selftest` does at
   `scripts/_keepon.py:55,61` (`global HOME; HOME = td / "home"`).

## Advisory Suggestions (WARN)

1. **The running MCP server predates the deploy — restart needed for live engine filtering.**
   `get_skill("resume-session")` through this session's MCP returned plain
   `{"error": "skill 'resume-session' not found"}` (old-code terminal fallback), and even the
   non-blocklisted control `get_skill("keep-on")` fails, with the server's own warning: "the
   index was built by a different engine build than this server runs … this server's own
   build is what is in question." This is the documented ADR-0018-class consequence
   (`docs/adr/0046-blocklist-disable-tier.md:104-106`, VENDORED.md entry). Deployed bytes are
   correct (verified identical); a session restart picks them up. Not a code defect — an
   operational step that remains.
2. **Wrong-typed `blocked` value degrades to nonsense entries instead of empty.** If the file
   holds `"blocked": "abc"` (string) or a dict, the isinstance-filter iterates chars/keys and
   produces single-char/name-of-key entries in guard/enforcer/engine
   (e.g. `skill_guard.py:57`, `enforcer.py:650`, `server.py:136`). Doctor correctly FAILs this
   shape (`doctor.py` `isinstance(lst, list)`), and single-char skill names are unrealistic,
   so severity is low — but a `not isinstance(lst, list): return empty` guard would make the
   fail-open total rather than approximate.
3. **Post-fusion filtering lets blocked rows consume TOP_K slots.** `server.py:807` filters
   after `_fuse_ranked(group_lists, TOP_K)`, so a result page can come back short when
   blocked skills rank high. This matches the stated design (index-neutral, post-fusion), so
   it is a noted consequence, not a defect.
4. **Relative-path hint in the deny reason.** `skill_guard.py:109` suggests
   `python3 scripts/blocklist.py remove <entry>` — only runnable from the repo cwd. The
   reason also names the `skill-concierge:blocklist` skill, which mitigates it.
5. **CLI `add` accepts names that can never match** (e.g. a leading-slash entry; the guard
   strips leading slashes from invoked names but entries are stored raw). User-error
   tolerance, no validation or warning. Nit.
6. **Doctor shows an unrelated pre-existing WARN**: OMP cache v0.38.2 != SSOT v0.39.0 (clears
   via the user's `/plugin marketplace update`). Not caused by this change.

## Validation Dimensions

- [x] Hook contract (PreToolUse deny) — PASS
  - Evidence: 12 direct stdin probes (see Observable Truths #2-3)
- [x] Cross-layer matcher consistency — PASS
  - Evidence: all four implementations read line-by-line; semantic equivalence argued from the rsplit invariant and confirmed by probes at guard (subprocess), enforcer (fresh import via tests), engine (deployed-module probe)
- [x] Enforcer candidate-path coverage — PASS
  - Evidence: `grep -n "_blocked("` → 7 non-selftest sites covering every claimed path; ROUTE seeds confirmed post-filter
- [x] Engine wiring (post-fusion filter, pre-read refusal, live content read) — PASS
  - Evidence: `server.py:807,822,829`; live kill-switch flip mid-process
- [x] Fail-open doctrine — PASS
  - Evidence: exception tuples at `skill_guard.py:58,90,119`; `enforcer.py:651`; `server.py:137`; `apply-overrides.py:69`. No layer can raise into the hook protocol with a wedging effect (guard catch-all returns exit 0; enforcer crash = no injection, turn proceeds)
- [x] Version/docs parity — PASS
  - Evidence: driftcheck exit 0; 4 manifests 0.39.0; all six doc surfaces reviewed; hooks.json valid JSON; `SKILL_BLOCKLIST` correctly NOT in `.mcp.json` (so the forward-tuple invariant is not implicated; the ADR's index-neutral rationale at `0046:68-70` is sound)
- [x] Tests (pytest 19/19, enforcer selftest, apply-overrides selftest) — PASS
- [ ] Selftest battery fully green — FAIL (`blocklist.py selftest` exit 1; blocking issue #1)
- [x] Live state mechanism (list + doctor functional) — PASS; live content claim — STALE (15 entries vs claimed 1; mtime evidence attributes it to post-handoff edits)
- [x] Defect hunt (edge cases, round-trip, JSON/frontmatter validity, stale claims, dead paths) — PASS with advisories 2-5; no stale doctrine claim found; all driftcheck path checks resolve

## Unverifiable Items

1. **End-to-end engine filter through the live MCP process.** This session's server runs
   pre-0.39.0 bytes (its own staleness warning; control pull fails too). Verified instead at
   function level against the deployed module (identical bytes): `_blocked` returns True for
   `resume-session` and `someplugin:resume-session`, False for `keep-on`, and honors the
   kill-switch per call. Full in-server behavior becomes observable after a session restart.
2. **A live enforcer turn against the blocklist.** Deliberately not run: it would append
   rows to the epoch-scoped ledger and pollute telemetry (AGENTS.md hard rule). Semantics
   pinned instead by `tests/test_blocklist.py` fresh-import tests, which replicate exactly
   what a per-turn hook process does.

## Context Gaps

1. Who edited the live blocklist at 03:16 (user curation vs another process) cannot be
   determined from the filesystem; only the mtime is known.
2. Whether Codex/ZCode plugin hook surfaces fire `skill_guard.py` as claimed is asserted by
   the ADR's harness-coverage section but not testable from this session.

## Addendum — post-fix re-verification (2026-08-29, after commit b792f2a)

The blocking issue was fixed and shipped as part of `b792f2a feat(blocklist): user-ordered
disable tier, origin-agnostic (ADR-0046)` (HEAD of main, clean tree). Independently
re-verified by this validator after the fix:

- **Blocking issue #1 resolved.** `scripts/blocklist.py:155-162` now patches the
  `_keepon.HOME` module global in a save/restore block (the prescribed idiom).
  `python3 scripts/blocklist.py selftest` → `selftest ok`, exit 0, **with the live
  15-entry blocklist file present** — the exact environment that failed.
- **Advisory #2 resolved at all four layers.** Wrong-typed `blocked` values now fail open
  to empty: `skill_guard.py:57-60`, `apply-overrides.py:70-73`, `enforcer.py:649-652`,
  `server.py:136-139` each guard `isinstance(data, dict)` and `isinstance(lst, list)`.
  Probe: `"blocked": "abc"` file → guard silent, exit 0.
- **No regression.** Guard still denies `resume-session` (bare entry, live file); pytest
  19/19.

**Verdict after fix: PASS** (advisories 1, 3-6 remain as recorded — advisory 1, the MCP
restart, is operational and documented in ADR-0046). The original FAIL above stands as the
state at first validation; this addendum records the closure.
