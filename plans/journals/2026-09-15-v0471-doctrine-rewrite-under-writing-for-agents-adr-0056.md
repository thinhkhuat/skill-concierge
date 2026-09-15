---
title: v0.47.1 — doctrine rewrite under writing-for-agents (ADR-0056)
date: 2026-09-15
summary: Audited every injected line; one lawful-skip definition; phantom find-skills retired; body halved; two-pass independent review APPROVE; OMP installer + doctrine.py selftest fixes
---

# v0.47.1 — doctrine rewrite under writing-for-agents (ADR-0056)

## What happened
Owner order: audit every line of the SKILL-FIRST doctrine and the enforcer's agent-facing strings with the writing-for-agents skill. Findings: the lawful-skip rule was stated in five places with three contents (rule 4 "one class — no task" vs library "positively-reasoned trivial earns a no-search skip" vs row 7's recap class, plus the getaway leg admitting "trivial"); `find-skills` was a phantom escalation target (no such installed skill); "~500" catalogue cache stale (index 2,714); ADR/version labels, "Skill tool" harness name, restatements and no-ops in an always-loaded body.

## Decision (ADR-0056)
One definition of a lawful skip (rule 4, two sources: a shown search whose hits fail the rule-3 bar, or an enforcer SKILL-CHECK line that itself states the turn's kind); checkable after-search skip criterion; escalation = term-rich search_skills re-query; rule 5 covers external + other-harness hits; body 8,074 → 4,238 chars. Enforcer: colons unified, MANDATE "No preview this turn", getaway leg drops "trivial", legs gain the "route it" tail, CONSULT footer/ADR label removed.

## Mechanisms fixed on the way
- doctrine.py OMP rewrite target had detached from the body wording; its selftest ran on a fixture — now runs on the live body. Slash-less harnesses drop the duplicate `or:` bullet.
- enforcer selftest 0041 read the live ENFORCER_MULTI_INTENT=0 (ADR-0055 trial) and failed on HEAD — now pins its flags locally.
- adapters/omp/install.sh fast path trusted the registry record while the cache held 0.47.0 content — now compares the cache manifest.
- tests/test_doctrine_text.py pins signature absence / no phantom pointer / no cached count.

## Verification
Independent reviewer (fresh agent): pass 1 APPROVE-WITH-FIXES (F1 OMP rewrite, F2 five-way contradiction — both HIGH), pass 2 APPROVE. Selftests (enforcer under both flag states, doctrine, audit), pytest 24, live probes off-ledger, driftcheck IN SYNC, unlazy 10/10 gates. Commit 5e00a28 pushed; adapters omp/dsh/cline/commandcode/zcode at 0.47.1 (OMP doctrine + enforcer byte-identical to HEAD).

## Next steps
- Owner: `/plugin marketplace update skill-concierge` + `/reload-plugins` in Claude Code (cache still 0.47.0) and Codex.
- Epoch-watch v0.47.1 W7 after ≥100 human-prompt turns: false-SKIPPING share and getaway follow-through (`skill-usage-audit --since "2026-09-15 11:50"`).
- Owner call, not done: the nine skills/*/SKILL.md descriptions are long always-loaded pointers; pruning trades context load vs the concierge's own-skill recall.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
