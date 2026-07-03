---
name: skill-usage-audit
description: Use when measuring whether a skill-concierge gate-threshold change helped real skill usage or adoption — "did the new gate values help", "skill usage impact after the change", "assess skill helpfulness", "audit skill usage post-deploy", "which telemetry is valid for skill-usage analysis". Stops the reflex of using the skill-invocation-ledger or treating offer→take as usage; routes to the transcript SKILL-FIRST trail instead.
license: MIT
metadata:
  version: 0.2.0
---

# Skill Usage Audit

## Overview

Whether agents use the **right** skill is NOT the enforcer's offer→take. The invocation-ledger
measures **gate compliance** and is **INVALID for usage analysis** (operator-flagged). The real
signal lives in the **transcript store** — and most of it is the **SKILL-FIRST declaration trail**,
which no invocation counter records.

**Violating the letter here is violating the spirit:** "I'll just use the ledger, it has
invocations" is the exact failure this skill exists to stop.

## Pick the right source

| Source | Path | Measures | Use for |
|---|---|---|---|
| invocation-ledger | `~/.claude/skill-telemetry/logs/skill-invocation-ledger.log` | gate compliance (offer→take; `auto`/`manual`/`search`) | gate firing only — **NOT usage** |
| skill-usage-tracker | transcripts → `~/.claude/audits/skill-usage-stats/` | usage frequency (Skill tool + `/slash`) | how often each skill actually ran |
| **SKILL-FIRST trail** | assistant text in `~/.claude/projects/**/*.jsonl` | agent KNEW + chose a skill (`USING`/`SEARCH`/`SKIPPING` declarations) | **the operator's metric** |

Inline SKILL-FIRST use (declare `USING <skill>` → read its `SKILL.md` → execute) fires **no Skill
tool**, so the ledger AND the usage-tracker both miss it. The declaration trail is the proxy that
catches it; subagent/`Task` skill use is missed by all three.

## Run it

```bash
python3 scripts/audit_skill_usage.py --since "<ship/commit time, e.g. 2026-06-29 01:06:35>"
```

Outputs the scoped post-change counts (Skill-tool, `/slash`, and the `USING`/`SEARCH`/`SKIPPING`
trail), self/meta sessions flagged, plus a **false-SKIPPING** rate — per turn, a `SKIPPING`
declared with NO same-turn `search_skills` call (the doctrine's hardest rule). A turn carrying the
enforcer's `SKILL-CHECK:` marker (`AUTHORIZED_SKIP_MARKER`, injected on the enforcer's two silent
verdict legs — see `hooks/scripts/enforcer.py`) is a **lawful, hook-pre-authorized skip**: it is
excluded from the false-skip count and tallied separately as `authorized_skip`, reported alongside
the false-skip figure so "false-SKIPPING" stays honestly defined. Run `--help` for flags;
`--selftest` pins the false-SKIPPING verdict logic, including the authorized-skip case.

## Scope to reduce noise (post-change)

- **Window** to events at/after the ship/commit time (not calendar "since I deployed").
- **Drop fallback-band** offers (embed/Qdrant down — the gate never ran; not its decision).
- **Drop self/meta sessions** — work *on* the audited project itself (dogfooding/verification) is
  the agent testing the gate, not organic usage.
- **Canonicalize names** before any offered-vs-invoked join (`ck:journal` ≡ `journal`); raw
  set-intersection silently undercounts namespaced-vs-bare.
- **Gate the verdict on VOLUME, not calendar time** — need ~50–100+ organic offered turns before a
  few-point change clears noise.

## Right metric, not the trap

- Report **absolute coverage** (right skill surfaced-and-used ÷ applicable turns), NOT conditional
  offer→take: raising a floor fires fewer offers and **mechanically inflates** conditional
  conversion even if real routing drops.
- **Suppression cost is unobservable post-change** (a suppressed offer is never shown → never
  taken). Estimate it ONLY via a **backtest over history**: which taken offers would the new floor
  have blocked? (On the live ledger: taken offers score LOWER than dodged — cosine is
  anti-correlated with adoption.)

## Tuning thresholds (optimal values)

- Sweep candidate floors through the **real enforcer fns** (`_embed`/`_retrieve`/`_is_imperative`/
  `_intent_conversational`) over a labeled corpus — never reimplement the gate.
- **Held-out only:** `prompt_intent` is built from the same corpus, so `_intent_conversational`
  classifies in-sample (~73% noise-catch vs ~53% held-out). Build a temp collection on a train
  split (`SKILL_PROMPT_INTENT_COLLECTION=...heldout`), evaluate on the test split, delete it.
- Frame as **volume vs adoption**: a higher floor suppresses more (volume) but cuts the
  better-converting low-cosine offers (adoption). Re-confirm on the live ledger before recommending.
- Worked example: `skill-concierge/plans/reports/impact-analysis-260629-1020-*.md`.

> **v0.10.0 caveat (multi-vector, ADR-0012).** The "cosine anti-correlated with adoption /
> taken offers score LOWER than dodged" findings above were measured on the SINGLE-vector index.
> Multi-vector MAX-pool roughly doubled positive↔negative separation, so the cosine↔adoption
> relationship must be **re-measured on post-v0.10.0 traffic** before reuse — do not carry the old
> anti-correlation forward as fact. The methodology (held-out sweeps, absolute coverage, drop
> self/meta, gate on volume) is unchanged.

## Common mistakes (from baseline failures)

| Rationalization | Reality |
|---|---|
| "The ledger records invocations, so it's the source." | Ledger = gate compliance; operator flagged it INVALID for usage. Use transcripts. |
| "offer→take = how often the right skill is used." | Conditional on the gate firing; misses inline SKILL-FIRST use entirely. |
| "Post-change window is enough to judge." | Usually thin + dogfood-contaminated. Gate on organic volume; drop self/meta. |
| "Sweep the corpus through the intent gate as-is." | The intent corpus self-scores in-sample. Held-out split only. |
| "Compare pre vs post conversion." | Denominator shifts (the floor changes who is offered). Use within-population replay / absolute coverage. |
| "Offered `ck:journal` ≠ invoked `journal` → not used." | Canonicalize names before joining. |

## Red flags — STOP

- Reaching for `skill-invocation-ledger.log` to answer a **usage** question.
- Leading with offer→take / "accept rate".
- Reporting a post-change number without dropping self/meta sessions or checking volume.
- Sweeping the live `prompt_intent` collection in-sample.
