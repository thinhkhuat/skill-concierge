# Adversarial review — skill-concierge 0.28.1 (5-lens, harness-agnostic arc)

**Date:** 2026-08-26 · **Reviewer:** Main (OMP session, concierge live) + 5 parallel read-only lenses
**Scope:** the harness-agnostic arc (ADR-0031→0039, commits `0b9ece6`…`4865428`, Aug 23–25) plus discipline, agent-compliance, helpfulness, and practicality in real agentic dev workflows.
**Method:** skill `spec-plan-adversarial-review` — 5 lenses (parity claim auditor / enforcement red-team / helpfulness measurer / over-engineering auditor / buildability oracle), shared output contract, all findings disk-verified; load-bearing claims re-verified by Main (delegate reports are claims).
**Epoch discipline:** current epoch = `4865428` (2026-08-25 16:50). All ledger rates below are epoch-windowed; windows are thin (54/55/35 turn-windows) — directional, not statistical.

---

## Verdict

**ship-with-fixes.**

What genuinely works — and is unusually strong:

- **The harness-parity claims hold on disk.** 8 of 9 load-bearing ADR-0039/0034/0033 claims verified line-by-line: all four `omp-*` scopes walk the claimed roots (`skills_discovery.py:66-78,600-617`), `_running_harness()` precedence matches the ADR (`enforcer.py:148-194`), absent-key=ENABLED semantics real (`enforcer.py:334`), byte-identical `=0` reverts confirmed, considered-options rejections honestly characterized (ADR-0034 documents its own first wrong implementation).
- **The per-turn machinery is honest and fast.** Hard budgets, fail-silent everywhere, floors documented, selftests assert inertness of dormant flags (`enforcer.py:1345-1350`).
- **The economics are real.** ~245 tokens per offer-bearing turn vs ~1,500 for the old all-skills listing (~6x cut at ~600 skills), ~0 on conversational turns. hit@k = 75% when a skill is actually taken.
- **Docs are currently truthful.** driftcheck exit 0; the doc mass is enormous but not drifting.

What fails the adversarial test — three measurement-layer defects, one naming fork, and one value question over the recent arc's flagship features:

1. **OMP ledger search-capture is dead — live-disproven this session.** All-time OMP-stamped events: `{turn: 128, auto: 7, search: 0, get_skill: 0}` — while this very OMP session called `search_skills` twice. The matcher in `adapters/omp/skill-concierge.ext.ts:252` tests only the hyphen/slash form (`skill-search/search_skills`); `ledger.py:34-40` already learned underscore-tolerant forms after the Codex incident — the OMP adapter did not inherit the lesson. Every OMP search-uptake number since 0.28.0 is a false negative; the epoch's "search 0%, dodge 92%" actively misclassifies compliant turns.
2. **No offer row carries a harness stamp — 2317/2317 missing.** `enforcer.py:765-789` `_append_offer` computes `RUNNING_HARNESS` (line 170) then drops it. Per-harness analytics — the entire point of the quadruple-harness arc — are not computable from the ledger as written.
3. **A silently-dead enforcer has unbounded mean-time-to-noticing.** Fail-silent per turn is the right hook doctrine, but nothing schedules an observer: no launchd/cron job exists, doctor is run only by hand, and analyze.py prints fallback rates with no threshold. The realized incident: between 0.26.2→0.27.0 the whole OMP surface was silently dead for a release cycle and was caught by a human, not a monitor (`docs/caveats.md` §22).

---

## Forks — owner decisions (not silently resolved)

**FORK 1 — "Enforcement" is a reminder. Rename it, or add the one deterministic gate.**
The line-1 USING/SEARCH/SKIPPING token is a self-claim verified nowhere, in any harness — the repo's own mental model says so outright (`docs/skill-first-enforcement-mental-model.md:61` "there is no such hook"; `hooks/doctrine/skill-first.md:5` "no post-turn checker"). Measured: 0 token declarations across the epoch's Claude-side turns; offered-turn non-take 94–96% across three epochs; and the headline compliance metric counts declaration as usage — 686 `USING:` declarations vs 266 actual Skill-tool calls since 2026-07-04 (audit script joins nothing). The Stop-hook was deliberately rejected (owner-set, coherent) — but then the honest name is **mandate + measure**, not "enforce-use" (README.md:10). Two lawful exits:
- (a) rename the claim everywhere (README/plugin.json/AGENTS.md) and keep the caveman architecture;
- (b) add the one deterministic generation-time check the architecture permits: a PreToolUse(Write/Edit) matcher that denies the first write of a turn whose session declared `SKIPPING:` without SKILL-CHECK authorization and without a same-turn search ledger row. OMP even has a real deny channel (fail-closed `tool_call` handlers, caveats §22.5) that today goes unused.
**Owner verdict 2026-08-26: (a) REJECTED — renaming would "officially endorse dodging"; the concierge exists to prevent it. Direction is (b): a deterministic generation-time gate. Reworked design (turn-state sidecar + PreToolUse(Write/Edit) gate in Claude Code, fail-closed tool_call deny in OMP, mandate-only stated factually where a harness has no pre-tool hook, plus the false-take detector) presented 2026-08-26 — build on approval.**

**FORK 2 — The annexes: zero *attributed* conversion over a ~4-day era, at full menu cost — re-measure clean, then decide.**
Corrected 2026-08-26 after owner pushback; re-derived from the raw ledger. What the first framing got wrong: realized annex sizes run **at cap, not thin** — ext annex ~3.2 of 4 slots (125/200 offer rows at 4-of-4), xh ~1.9 of 2 (132/164 at 2-of-2); `TOP_K=8 + 4 ext + 2 xh` matches the owner's design intent exactly, and ADR-0036's "annexes shrink to 0–1 with strong inventory" is *not* what realized. The era is **~4 days** (200 of 202 ext offers fall Aug 23–26), not "across every epoch." And `analyze.py`'s "external takes: 4" headline is **fixture-contaminated**: 3 of 4 take-sids are smoke-test fixtures (`vtest`, `smoke-apple`, `dep-take`); exactly **1 real external take** exists all-time (search-attributed, not annex-attributed). What stands: annex-attributed conversion is **0/31 sessions** (verified three ways after two buggy jq attempts to refute it) — but attribution was blinded by the capture bugs (OMP `get_skill` invisibility, unstamped offers). **Recommendation (unchanged, better grounded):** land the capture fixes, run one clean epoch with per-harness attribution, then decide keep vs default-off.

**FORK 3 — Declare the subagent scope of the gate.**
Claude Code: delegated Task work gets no gate at all (UserPromptSubmit never fires for subagent prompts; `doctrine.py` SUBAGENT_STOP default ON) — "spawn a subagent" is the cheapest dodge and it is simply the architecture. OMP is actually better than its own docs claim: subagent sessions **do** receive the doctrine (observed live this review — lens transcripts open with the standing order). **Recommendation:** state the scope in doctrine + ADR-0020 ("main-session prompts are the gated lane; delegated lanes carry doctrine only"), and scope dodge metrics accordingly. Extending per-turn enforcement into subagent turns is possible in OMP (session_start fires per subagent) but not worth it until FORK 1(b) exists.
**Owner verdict 2026-08-26: approved — record what is factual per harness; docs update in progress (delegated). Extending per-turn enforcement into subagent lanes stays deferred until FORK 1(b) exists.**

---

## Patches — bounded fixes (apply after forks decided, one pass)

| # | Fix | Evidence | Effort |
| 1 | **OMP capture:** fix BOTH matchers for OMP's all-single-underscore tool-name flattening (`ext.ts` + `ledger.py` SEARCH_TOOLS/GET_TOOLS, single-underscore suffix forms) — ✅ **APPLIED 2026-08-26**: matcher probes green, end-to-end ledger row `{"ev":"search","harness":"omp"}` verified, TS builds, enforcer selftest green | `ext.ts:252-266`; `ledger.py:36-43` | done |
| 2 | **Harness stamp:** `ev["harness"] = RUNNING_HARNESS` in `_append_offer` — ✅ **APPLIED 2026-08-26**: offer-stamp probe green, selftest green. New epoch begins here: per-harness analytics computable from this point | `enforcer.py:774-776` | done |
| 3 | **Flywheel backfill:** ✅ **COMPLETE 2026-08-26 — 645/645 skills (100%)**, from 556/645. Journey: first launch mis-targeted the dead local endpoint (killed; root cause fixed permanently via `flywheel_llm._cfg()` harness-env fallback); full regen timed out at 1h (43 generated); `--triggers-only` run covered most of the rest; the final 7 hit deterministic `finish_reason='length'` truncations → root cause fixed (`max_tokens` 4096→8192 — deepseek-v4-flash spends budget on reasoning before content) → rerun closed to 645/645. Reindex landed, points live | flywheel status: `645/645 … 0 missing`; manifest `generated 115+ error 0` | done |
| 4 | ~~keep-off refresh~~ — **RETRACTED 2026-08-26**: the claim read the frozen repo *seed* (`config/keep-off.json`, 2026-06-29 snapshot) instead of the canonical runtime home (`~/.claude/skill-concierge/keep-on.json`, mtime **2026-08-20** — refined 6 days before the review, exactly as the owner said). ADR-0025 names this very distinction. Optional nicety only: refresh the seed to match the refined runtime list | runtime file mtime + content drift vs seed | n/a |
| 5 | **Dead-enforcer detection:** (a) `check_embed_shim()` in doctor (absent — enforcement degrades to mandate-only with zero signal); (b) analyze.py health line: offers/turns < 0.9 → WARN; (c) weekly launchd doctor run into the existing log dir | `scripts/doctor.py` CHECKS (19 checks, no embed-shim); `ls ~/Library/LaunchAgents` empty | half day |
| 7 | **Doctor parity:** add `check_codex()` + `check_commandcode()` — 🔄 **in progress (delegated) 2026-08-26**. Correction: Claude Code is NOT excluded — the core checks (`check_mcp_wiring`, `check_mcp_enabled`, `check_dup_mcp`, `check_overrides`, `check_ledger`) all inspect `~/.claude/*`, i.e. claude is covered implicitly; the gap is codex + commandcode having zero checks | doctor.py:1260-1264 CHECKS list | half day |
| 9 | **Uninstall docs:** README + openwiki, all 4 harnesses + shared components — 🔄 **in progress (delegated) 2026-08-26** | README grep | an hour |
| 11 | ~~Log rotation~~ — **OWNER-DECLINED 2026-08-26**: logs retained deliberately during the dev cycle (57.5 MB immaterial). Revisit after 1.0 if ever | `wc -c` probe | n/a |
| 12 | **CJK/VN residuals:** trigger extractor `_SPLIT_RE` misses `。！？` so CJK descriptions split only at newlines; `_TRIG_MIN_WORDS` drops CJK-only phrases (`len(p.split())==1`); `_LABEL_RE` is English-only so Vietnamese `Khi nào dùng:`/`Ví dụ:` labels stay glued to triggers. Operator writes Vietnamese daily — same class as the 0.28.1 pre-gate bug | `server.py:473-488,474` | half day |
| 13 | **Flag inventory:** 76 env vars read by code; AGENTS.md documents ~8. The dormant ones are exemplary (default-inert, data-rationale in comments, selftested) — but three quarters of the config surface is undocumented | flag enumeration probe | an hour |
| 14 | **setup.sh pre-flight:** ports 6333/6334/6363 never checked before container start; embed-shim docker-build failure surfaces as a raw Docker error under `set -e` | `setup.sh:62-88` | minutes |
| 15 | **False-take detector:** mirror `_skip_verdicts` in `audit_skill_usage.py` — `USING:` with no same-turn Skill call or `skill://` read → false_take counter (~15 lines; machinery exists) | `audit_skill_usage.py:360-368` | an hour |
| 16 | **Ledger fixture hygiene:** smoke-test runs write synthetic rows into the PRODUCTION ledger (`vtest`, `smoke-apple`, `dep-take` sids), and `analyze.py` counts them as real "external takes: 4" (3 of 4 are fixtures — only 1 real take exists). Fix: smoke tests write to a temp `SKILL_CONCIERGE_LOG` dir, or `analyze.py` tags/excludes fixture sids. Found during the owner-mandated Fork-2 re-derivation 2026-08-26 | get_skill sid probe; `analyze.py:536` | an hour |

---

## What was checked and held up (credit where due)

- Post-filter (not Qdrant `must_not`) cross-harness isolation — verified `enforcer.py:889-895`.
- OMP never writes `~/.omp/agent/mcp.json`; the duplicate-server hazard is explicitly refused in the installer (`adapters/omp/install.sh:13-17,143-144`).
- `_invocable_twin()` absent-key=ENABLED, drop-nothing-on-unknown — matches ADR-0034 exactly.
- The doctrine text itself is first-rate behavioral engineering — the red-flags table, burden-of-proof-on-skip, and the commitment-token psychology (`skill-first.md:21-22`) are the best "caveman" enforcement writing I've reviewed; the gap is verification, not doctrine.
- Driftcheck mirrors: green today, 10 lifetime commits, no historical slip found.
- Ledger epoch guardrail (AGENTS.md) was respected by all lenses; windows honestly thin.

## Verification notes (what this review did to its own findings)

- Lens-3's BLOCKER ("flywheel 7.5% coverage") **refuted by live probe**: actual 556/645 (86%); the scout misread the status counters. Downgraded to the 89-skill backfill patch.
- Lens-3's "dodge" number needed semantic precision: `offered-turn dodge` = menu-shown turns where none of the *offered* skills was invoked (analyze.py:133-147) — it includes lawful search-then-skip outcomes; the honest statement is "offered skills go untaken 94–96%", not "agents break the rule 94%". The 0-token-declaration count and 686-vs-266 declaration gap carry the compliance-theater point regardless.
- OMP zero-search-rows and 2317 unstamped offers: independently re-probed from the ledger JSONL by Main.
- Lens 4 (over-engineering) died at final assembly after completing evidence-gathering (exit 1, 35 min). Per halt protocol it was not re-spawned; findings reconstructed from its transcript plus inline verification (flag count, keep-off staleness, log sizes, driftcheck, dormant-flag selftests).
- Over-engineering verdict, reconstructed: the honest read is **not** bloat — the dormant flags are disciplined opt-ins with data rationale, and doc claims verified true. The real debt is (a) 76-var flag surface vs 8 documented, (b) unbounded logs, (c) doc mass sustainable only while the single operator is its author, (d) fast-moving harness surfaces (the OMP tool-name breakage *is* the six-month-rot prediction, realized within one release).

## Unresolved questions (honest status)

- Whether offered-turn non-take is theater or lawful skipping cannot be fully distinguished until patches 1+2+15 land — the clean 4-harness compliance number does not currently exist.
- FORK 2's annex decision is deliberately deferred behind a clean re-measurement; both actions (floor raise vs default-off) are defensible on current data.
- OMP post-/compact doctrine re-injection: untested either way (no evidence in either direction).
- Sub-scope of FORK 1(b) in Codex/CommandCode (no PreToolUse equivalent confirmed) — would need adapter-specific design before any promise.
