# Code Review — P1 Semantic Skill-Enforcement Fusion

Date: 2026-06-26
Reviewer: code-reviewer (advisory, report-only)
Scope: enforcer.py, embed_server.py, bin/embed-shim, Dockerfile, .dockerignore, setup.sh, hooks.json, analyze.py, vendor pyproject.toml. Pattern comparison vs ledger.py + skill_first_nudge.py.

## Verdict

**The reviewed code is clean (0 code blockers, all 6 criteria met), but P1 is NOT shippable as-is: a live cutover BLOCKER means double mandate-injection is firing in production right now.** Do not treat "0 code blockers" as ship-clear — enabling the plugin without deregistering the old hook (already the current state) ships the defect.

Blocker count: **1** (cutover blocker — BL-1 below). It lives in `~/.claude/settings.json` (outside the reviewed files), but severity tracks production impact, not which file holds the fix.

In-code quality: all six acceptance criteria are met in the reviewed source. Remaining in-code items are 1 SHOULD-FIX (telemetry-join bug, SF-2) plus NITs; none breaks a turn.

## Acceptance criteria — verified

- (a) stdlib-only, fail-silent, never blocks, additive-only — **PASS.** enforcer.py imports only sys/os/json/time/socket/urllib/pathlib. Outer `try/except → return 0` (lines 202-204). Only ever emits `hookSpecificOutput.additionalContext` (`_inject`, lines 100-106). No exit-2, no `decision:block`.
- (b) ~90ms embed timeout is CLIENT-enforced — **PASS.** `EMBED_TIMEOUT_S=0.09` (line 58) passed to `urllib.request.urlopen(req, timeout=...)` (line 113). Socket timeout is enforced by the client regardless of shim health. (Caveat: it is a per-socket-operation timeout, not a hard wall-clock cap — see NIT-2.)
- (c) three fallbacks → mandate-only — **PASS.** embed timeout (lines 172-174), embed down (175-178), qdrant down (183-187) all `_inject(MANDATE)` + tagged telemetry, never silent/crash. Verified the live query path returns the exact `result.points[].{score,payload}` shape `_retrieve` parses.
- (d) no library.json read remains — **PASS.** enforcer.py and analyze.py both source the catalogue from the Qdrant index (analyze `known_skill_ids()` scroll, lines 47-74). No `library.json` reference in either.
- (e) parity contract intact — **PASS (empirically corroborated).** bin/embed-shim and embed_server.py reuse `skill_search.server.embed`; fastembed pinned `==0.8.0` in Dockerfile (line 16) and vendor/pyproject.toml (line 24); Dockerfile bake-step asserts dim==768 (line 29). Beyond the pins: embedding a real query through the live shim and querying the index returned *coherent* top results (supabase task → supabase skills at 0.48/0.46/0.43). A pooling/version desync would have produced garbage rankings, not coherent ones — so the shim's vectors are functionally consistent with the index. The phase-01 cosine≈1.0 check could not be re-run from here, so parity is functionally-corroborated, not independently re-verified.
- (f) no regression to ledger.py / MCP / shared paths — **MOSTLY PASS.** Shared LEDGER append is concurrency-safe in practice (see NIT-4). But see BL-1 (double mandate, live) and SF-2 (q-join telemetry bug).

Live verification performed:
- Hook runtime is Python 3.9.6; enforcer.py uses no 3.10+ syntax and `except (socket.timeout, TimeoutError)` correctly covers 3.9 (where `socket.timeout` is not aliased to `TimeoutError`). **3.9-compatible.**
- Qdrant `claude_skills` payload keys = `name, description, path, content_hash` — enforcer's `name`/`description` reads are valid.
- A real task ("deploy a supabase edge function…") returns scores 0.48/0.46/0.43 — comfortably above `GETAWAY_FLOOR=0.20`; calibration holds.

## BLOCKER

### BL-1 — Double mandate injection is LIVE: old lexical hook still registered while the plugin is enabled
Verified empirically, not inferred:
- `~/.claude/settings.json` `enabledPlugins["skill-concierge@skill-concierge"] = true` — the plugin is enabled.
- The cached plugin ships `~/.claude/plugins/cache/skill-concierge/skill-concierge/0.1.2/hooks/hooks.json`, which registers `enforcer.py` on `UserPromptSubmit`.
- `~/.claude/settings.json` ALSO still registers `python3 "$HOME/.claude/hooks/skill_first_nudge.py"` on `UserPromptSubmit`.

Therefore both hooks fire on every prompt right now and inject two competing "SKILL-FIRST (standing mandate)" blocks — token waste plus conflicting guidance (the old one routes to `which-skills` + the lexical `library.json` scorer; the new one routes to the semantic index). enforcer.py:5 explicitly claims to *supersede* skill_first_nudge.py, so the retirement is incomplete, not intentional coexistence.
Impact: defeats the core P1 goal ("retire a lexical skill-enforcement hook"), degrades context quality, and is already in effect in this environment.
Fix: deregister `skill_first_nudge.py` from the `settings.json` UserPromptSubmit array as part of cutover. The fix is a one-line settings edit (outside the reviewed source files) — its triviality is an argument for doing it now, not for downgrading severity.

## SHOULD-FIX

### SF-2 — Telemetry join mismatch: offer.q is stripped, turn.q is not → hit@k silently undercounts
analyze.py attaches `offer` events to `turn` windows by `(sid, q)` and its comment (analyze.py:86, 118-119) claims "Offer.q and turn.q are both prompt[:120], so they match exactly." They do not always:
- ledger.py:66 logs `"q": prompt[:120]` where `prompt = d.get("prompt") or ""` — **unstripped**.
- enforcer.py:159 sets `prompt = (data.get("prompt") or "").strip()`, then logs that stripped value as `q` (enforcer.py:93, 174/178/186/195/201).
For any prompt with leading/trailing whitespace the two keys diverge and the offer never attaches → that turn drops out of `eligible`, so hit@k and band stats are silently wrong. Common case (no surrounding whitespace) matches, so it passes happy-path testing.
Fix: make both sides consistent — strip in ledger.py before slicing, or key the join on the same normalization. Cheapest: ledger.py log `s[:120]` (it already computes `s = prompt.strip()` at line 57) instead of `prompt[:120]`.

## NITs

- **NIT-1 — Stale "120ms" in docstring/comment.** Module docstring (enforcer.py:18) and the inline comment (enforcer.py:169) say "HARD ~120ms" but the actual default is 90ms (line 58), correctly explained in the tuning comment (lines 53-57). Update the two stale mentions to 90ms to avoid future confusion about the budget contract (criterion b).
- **NIT-2 — Timeout is per-operation, not wall-clock; telemetry can mislabel.** `urlopen(timeout=)` bounds each socket op, not total elapsed; a server dribbling bytes could exceed 90ms (benign for a trusted localhost shim). Separately, a *connect*-phase timeout surfaces as `urllib.error.URLError` wrapping the timeout, which is NOT caught by `except (socket.timeout, TimeoutError)` and falls through to the generic handler → tagged `embed_down` instead of `embed_timeout`. Functionally identical (both → mandate-only); only the telemetry label is wrong. Optionally inspect `e.reason` to reclassify.
- **NIT-3 — Shim binds 0.0.0.0 inside the container.** Dockerfile sets `EMBED_SHIM_HOST=0.0.0.0` (line 22). Off-host exposure is correctly prevented by setup.sh's `-p "127.0.0.1:$EPORT:6363"` publish (setup.sh:64), so the 127.0.0.1-only requirement holds at the host boundary. Residual: other containers on the same Docker bridge could reach it via container-IP:6363. Acceptable for this threat model; note it. (The host/dev launcher bin/embed-shim + embed_server.py default to 127.0.0.1 — correct.)
- **NIT-4 — Shared ledger append, no lock.** enforcer.py and ledger.py both `open("a")`+`write(one json line)` on the same file within the same UserPromptSubmit. POSIX `O_APPEND` writes under PIPE_BUF (~4096B) are atomic and each line is well under that, so interleaving won't occur in practice; analyze.py also tolerates corrupt rows (load() try/except). No action needed; documenting the assumption.
- **NIT-5 — Combined worst-case latency exceeds the ~150ms design goal.** embed(90ms)+qdrant(100ms)+cold-start(~50ms) can reach ~170-190ms on the qdrant-slow path. The docstring's "~140ms slow path" reasoning only covers the embed-slow branch, not qdrant-slow. Criterion (b) is about the embed timeout specifically and is met; this is just an honest note that the qdrant branch isn't inside the 150ms envelope. Consider tightening `QDRANT_TIMEOUT_S` if the total budget is hard.
- **NIT-6 — by_sid_q collision on duplicate prompts.** If the identical prompt text recurs in a session, `by_sid_q` (analyze.py:96) keeps last-wins; earlier offer attaches to the later window. Minor analytics edge only.
- **NIT-7 — embed_server single-threaded.** Acknowledged in the file's "ponytail" comment. Concurrent prompts (multiple sessions) serialize and the second may breach the 90ms client timeout → fallback. Fine for single-user; revisit only if measured.

## Positive observations (risk-relevant)

- Fail-silent discipline is consistent and correct across all three error surfaces; the design contract in the docstring matches the implementation.
- Reusing `skill_search.server.embed` for both the shim and the index build is the right parity choice and is enforced at three layers (pin in Dockerfile + pyproject, bake-time dim assert).
- analyze.py correctly handles the hook-array ordering problem (offer fires before turn) by deferring the join to (sid,q) instead of latest-window — sound design, undermined only by SF-2's key mismatch.

## Unresolved questions

1. RESOLVED — the plugin IS enabled (`enabledPlugins["skill-concierge@skill-concierge"]=true`) and its hooks.json registers enforcer.py, so BL-1's double-injection is live now. Deregister `skill_first_nudge.py` to complete cutover.
2. Is the ~150ms total-budget criterion a hard SLO or a target? If hard, NIT-5 (qdrant-slow path) needs `QDRANT_TIMEOUT_S` tightening.
