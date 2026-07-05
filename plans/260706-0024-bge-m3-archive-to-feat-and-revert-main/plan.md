---
title: "Archive bge-m3/Ollama migration to a feat branch, revert main to clean mpnet"
description: "The bge-m3 dense migration is fully staged (uncommitted) on main. Measured verdict: lateral retrieval quality, no cross-lingual win, a weakened getaway-suppression layer, at real always-on-daemon + epoch-reset cost — defer deploy. This plan preserves the complete work on feat/bge-m3-ollama-migration (deployable later) and restores main to clean mpnet, with a fix-before-deploy list from the code review and a turnkey cutover runbook."
status: executed — archived on feat/bge-m3-ollama-migration (a86d3d6); main reverted to clean mpnet 0.13.1; Phase 6 (deploy) deferred
priority: P2
branch: main
tags: [embedder, bge-m3, ollama, revert, archive, feat-branch, deferred, deploy-later]
created: "2026-07-06T00:24:00+07:00"
createdBy: cook (deferred outcome)
source: skill
---

# Archive bge-m3/Ollama migration → feat branch; revert main to clean mpnet

## Why (decision context)

The migration was built and **measured** this session, not asserted. Verdict — **defer deploy**:

- **No cross-lingual win** (the stated goal). bge-m3 ≈ mpnet on the top-1 band (mean 0.738 vs 0.734); the incumbent is already multilingual and beat bge-m3's margin on a native-VN query.
- **Weakens the enforcer.** bge-m3's cosine band rides high → `GETAWAY_FLOOR=0.45` goes inert; suppression falls entirely on the relative actionability gate (measured 15/19 vs mpnet 17/19) → more skill-offers on chitchat turns.
- **Real cost.** A formerly offline plugin gains an always-on Ollama dependency on the per-turn hot path, ~2× embed compute, and a telemetry epoch reset.
- Feasibility is fine (p95 159ms ≤ cap; dim 1024) — this is a *deferral*, not an abandonment. bge-m3 becomes the substrate to revisit when sparse-hybrid or a substrate change makes it pay.

Nothing was cut over live: `claude_skills` is still 768/mpnet, the shim container is still mpnet, the MCP is still mpnet. All migration edits are **uncommitted working-tree changes** — archiving is a clean branch-and-restore, no history surgery.

## Current state (verified 2026-07-06)

- Branch `main` @ `413f827`. Live system unchanged (mpnet 768 everywhere).
- **Migration = 10 modified (uncommitted)** — `.mcp.json`, `scripts/embed_server.py`, `bin/embed-shim`, `setup.sh`, `Dockerfile`, `scripts/doctor.py`, `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `CHANGELOG.md`, `docs/adr/README.md`.
- **Migration = untracked** — `docs/adr/0019-embedder-bge-m3-via-ollama.md`, `plans/260705-2240-bge-m3-ollama-dense-migration/`, and 6 bge-m3 reports in `plans/reports/`.
- **UNRELATED, leave on main** — `openwiki/{.last-update.json,operations.md,quickstart.md}` (pre-existing in-flight doc work; NOT part of this migration).
- Scratch Qdrant collections to drop: `claude_skills_bge_scratch`, `prompt_intent_bge_scratch` (throwaway; `claude_skills_shadow` is pre-existing/unrelated — leave it).

## Target end state

- `feat/bge-m3-ollama-migration` — the complete migration (10 files + ADR-0019 + original plan dir + 6 reports) as clean commit(s). Deployable later.
- `main` — clean mpnet (migration files back to `413f827`, version 0.13.1), openwiki changes retained, plus **this** archive-plan as the decision breadcrumb pointing to the feat branch.
- Live system: mpnet, `doctor` green, scratch collections dropped.

## Phases

### Phase 1 — Pre-flight safety (no mutation)
1. Confirm branch=main, no in-progress rebase/merge, and the exact modified/untracked sets above (`git status --porcelain`).
2. Record `git rev-parse HEAD` (= `413f827…`) as the restore anchor.
3. Acceptance: state matches "Current state" above; nothing else modified.

### Phase 2 — Harden the archived work (RECOMMENDED, apply the cheap review fixes before committing)
Fold the code-review's low-risk, unambiguous findings so the shelved branch is deploy-ready-minus-the-cutover-design items. Apply **on the working tree before the feat commit**:
- **I3 (driftcheck RED):** bump `README.md` 0.13.1→0.14.0 and `openwiki/quickstart.md` to 0.14.0; re-run `python3 scripts/driftcheck.py driftcheck.json` → exit 0. *(NOTE: the openwiki bump touches an otherwise-unrelated file — stage it with the migration only if we accept that coupling; else defer to deploy time.)*
- **I2 (doctor false-OK):** in `check_ollama_shim_parity`, when `shim_dim` is known but `coll_dim` is None → return WARN/FAIL, never an OK claiming `== None`.
- **M1 (SSOT gap):** add `SKILL_OLLAMA_URL` to the key list in `auto_reindex.py:_mcp_env()`.
- **L1/L2 (stale comments):** `embed_server.py` threading rationale (no onnxruntime now); `setup.sh:92` "`--reindex`"→"`--rebuild`".
Acceptance: `driftcheck` green; `doctor.py --selftest` passes.

### Phase 3 — Archive to feat branch
```bash
cd /Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge
git switch -c feat/bge-m3-ollama-migration          # uncommitted changes ride along
# stage ONLY migration paths (NOT openwiki, NOT this new archive-plan dir):
git add .mcp.json scripts/embed_server.py bin/embed-shim setup.sh Dockerfile scripts/doctor.py \
        .claude-plugin/plugin.json .claude-plugin/marketplace.json CHANGELOG.md docs/adr/README.md \
        docs/adr/0019-embedder-bge-m3-via-ollama.md \
        plans/260705-2240-bge-m3-ollama-dense-migration/ \
        plans/reports/ck:code-reviewer-260705-2301-bge-m3-ollama-migration-red-team-failure-mode-analyst-plan-review-report.md \
        plans/reports/ck:code-reviewer-260705-2302-bge-m3-ollama-migration-red-team-scope-complexity-critic-plan-review-report.md \
        plans/reports/from-code-reviewer-to-planner-red-team-assumption-destroyer-plan-review-report.md \
        plans/reports/from-code-reviewer-to-planner-red-team-security-adversary-plan-review-report.md \
        plans/reports/research-260705-2229-bge-m3-blast-radius-and-gate-calibration-report.md \
        plans/reports/research-260705-2229-bge-m3-fastembed-hybrid-external-report.md
git commit -m "feat(embedder): bge-m3 (1024d dense) via Ollama — archived, not deployed

Full dense-migration: shim-as-Ollama-proxy, backend SSOT, --rebuild reindex,
doctor Ollama-tier parity check, ADR-0019, v0.14.0. Measured lateral quality +
weakened getaway floor -> deferred (see plan). Deploy runbook + fix-before-deploy
list in plans/260706-0024-bge-m3-archive-to-feat-and-revert-main/plan.md on main."
```
Acceptance: `git show --stat` lists only the migration paths; openwiki + the archive-plan dir are NOT in the commit.

### Phase 4 — Revert main to clean
```bash
git switch main
```
On switch, the committed migration files snap back to main's mpnet versions; the untracked-now-committed artifacts (ADR-0019, plan dir, reports) leave main's working tree (they live on feat); openwiki changes and the untracked archive-plan carry back.
1. Verify: `git status --porcelain` shows ONLY the openwiki trio (modified) + `plans/260706-0024-…/` (untracked). No migration files.
2. Verify mpnet: `.mcp.json` backend=`fastembed`, `plugin.json` version `0.13.1`, `grep 0.14.0` in tracked files → none.
3. If any migration file lingers modified: `git checkout HEAD -- <file>`.
Acceptance: main clean of bge-m3; openwiki retained; version 0.13.1.

### Phase 5 — Clean live scratch state
1. Drop scratch collections: `curl -X DELETE localhost:6333/collections/claude_skills_bge_scratch` and `…/prompt_intent_bge_scratch`.
2. Kill any orphan scratch shim on :6399 (the spike shims trap-exit, but confirm `lsof -i:6399` empty).
3. `python3 scripts/doctor.py` on main → `status: OK` (mpnet, no ollama check present here).
Acceptance: only `claude_skills` (768), `prompt_intent` (768), `claude_skills_shadow` remain; doctor green.

### Phase 6 — Deploy-later runbook (reference; DO NOT run now)
When bge-m3 is worth shipping, from `feat/bge-m3-ollama-migration`:
1. **Resolve the two cutover-design blockers first** (see Fix-before-deploy): C1 shim-strand, I1 live-drop.
2. Merge/rebase feat onto main; push to GitHub (bump already at 0.14.0).
3. **Force-replace the shim container** (this is C1): `docker rm -f skill-concierge-embed-shim` BEFORE `setup.sh` (its health-gated block skips a rebuild of a still-healthy container → strands the old mpnet shim).
4. Rerun `setup.sh` (rebuilds the bge shim image + host-networked container, `--rebuild` reindex to 1024 in a **~103s maintenance window**, rebuilds `prompt_intent` at 1024, stamps the model digest, applies overrides).
5. `/plugin update` + restart Claude Code (reloads `.mcp.json` → MCP on ollama).
6. Verify: `doctor.py` → OK incl. the new Ollama-tier check (daemon/model/dim parity + digest); `driftcheck.py` IN SYNC; money-test through the live MCP; acknowledge the telemetry epoch reset.

## Fix-before-deploy checklist (from the 2026-07-06 code review — FAIL to land as-is)
- **C1 (CRITICAL):** `setup.sh` shim block is health-gated → a still-healthy old shim is left in place while the index rebuilds at the new dim → dim desync → mandate-only. Force-replace the container (unconditional `docker rm -f` on a version/image change) and add it to the ADR/CHANGELOG rollback+cutover checklist.
- **I1 (IMPORTANT):** `setup.sh` `--rebuild` drops the live `claude_skills` in place on *every* rerun. Gate force to actual dim-change (else `--reindex`), or document reruns as a maintenance-window op; fix the `setup.sh:88-89` "same-dim rerun just re-embeds" comment (it drops-then-rebuilds).
- **I2 (IMPORTANT):** doctor `check_ollama_shim_parity` false-OK when `coll_dim=None`. *(Phase 2 fix.)*
- **I3 (IMPORTANT):** driftcheck RED — `README.md`/`openwiki/quickstart.md` not at 0.14.0. *(Phase 2 fix.)*
- **M1/M2 (MODERATE):** `auto_reindex.py` drops `SKILL_OLLAMA_URL` *(Phase 2 fix)*; digest-drift WARN's `fix=reindex` (incremental) can't clear the drift + never re-stamps → point the remedy at a `setup.sh` rerun.
- **M3 (MODERATE):** keep the openwiki regen OUT of the migration commit so the "single revertable commit" story holds (handled by Phase 3's explicit paths).

## Rollback of THIS reversal (if we change our mind)
The migration is intact on `feat/bge-m3-ollama-migration`; `git switch feat/bge-m3-ollama-migration` restores every artifact. No work is lost by archiving.

## Open questions
1. **Breadcrumb scope:** keep the original plan dir + 6 reports ONLY on feat (this plan's default), or also copy the plan dir onto main for at-a-glance history? Default: feat only; main carries this archive-plan as the pointer.
2. **openwiki 0.14.0 bump (I3):** the driftcheck fix touches `openwiki/quickstart.md`, which is otherwise unrelated in-flight work. Apply it on feat with the migration (accept minor coupling) or leave openwiki alone and let the deploy-time run own the version bump? Default: leave openwiki out of the archive; fix driftcheck at deploy.
3. **Execute now or plan-only?** This plan touches `main` (load-bearing) — awaiting go before running Phases 3-5.
