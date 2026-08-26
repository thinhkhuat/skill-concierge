---
title: Adversarial 5-lens review of 0.28.1 + owner-verdict remediation batch
date: 2026-08-26
summary: Review found 3 forks + 16 patches; owner verdicts executed; flywheel to 645/645; 4 commits landed (unpushed)
---

# Adversarial 5-lens review of 0.28.1 + owner-verdict remediation batch

## What happened
- Adversarial 5-lens review of v0.28.1 (report: plans/reports/review-260826-adversarial-5lens-0.28.1.md) -> verdict ship-with-fixes, 3 forks + 16 patches.
- Owner verdicts: Fork-1 rename REJECTED ("renaming would officially endorse dodging") -> direction is a deterministic generation-time gate; Fork-2 pushback CORRECT (re-derived from raw ledger); Fork-3 approved and shipped as docs.
- Fork-2 re-derivation from raw ledger (append-only): offers=2384, ext-annex-bearing=229 (153 at 4-slot cap, avg ~3.3/4), xh-bearing=192 (154 at 2-slot cap) -> annexes run AT CAP, matching design intent (TOP_K=8, max 4 external, dynamic); get_skill-attributed annex takes = 2, both fixture sids (vtest/smoke class), 0 real; ext annex era only 08-23..08-26. analyze.py "external takes: 4" was fixture-contaminated.
- OMP capture bug fixed twice over: ext.ts matchers + ledger.py SEARCH_TOOLS/GET_TOOLS accept OMP's all-underscore tool-name flattening; enforcer stamps ev["harness"] on offers.
- Flywheel utterance coverage 556/645 -> 645/645 via two root-cause fixes: (1) flywheel_llm._cfg() resolves endpoint/model/key from real env then ~/.config/harness-env.sh (detached paths saw a dead local default); (2) max_tokens 4096->8192 (deepseek-v4-flash spends budget on reasoning before content; 7 skills died deterministically finish_reason=length).
- doctor.py gained check_codex() + check_commandcode() -> all 4 harnesses covered, live-verified [ok] x3, exit 0, selftest ok.
- Keep-on "2 months stale" claim RETRACTED: runtime ~/.claude/skill-concierge/keep-on.json mtime 2026-08-20 (owner was right; review had read the frozen repo seed config/keep-on.json).

## Decision
- Enforcement must be deterministic at generation time (turn-state sidecar + PreToolUse(Write/Edit) deny in Claude Code, fail-closed tool_call deny in OMP, mandate-only stated factually where no pre-tool hook exists, false-take detector). Self-declaration never authorizes. Build awaits owner approval (blocks turns).
- Fixture hygiene patch 16 open: smoke tests (sids vtest*, smoke-*, dep-take, deployed-smoke1) write the production ledger and contaminate analyze.py counts.
- Logs retained (owner-declined cleanup; 57MB immaterial during dev cycle).

## Next steps
- Release pass: bump 4 manifests + package.json + CHANGELOG, push (owner-gated), /plugin marketplace update per harness.
- Fork-1 gate build on owner approval (~1 day).
- ./setup.sh + harness restart to clear 3 pre-existing doctor warnings (venv engine vs plugin cache drift) and load hook fixes live.
- After release: one clean week of harness-stamped ledger data, then Fork-2 conversion verdict.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
