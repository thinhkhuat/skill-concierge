# ADR-0030 — Operator-owned chain overrides (upgrade-proof curation)

Status: Accepted (2026-08-20)

> Number note: an earlier drafted clause-split ADR-0030 (0.21.0 arc) was cut before ever landing
> as a file; this is the first ADR to actually hold the number. The stale citations in README /
> CHANGELOG / openwiki were retracted in 0.21.3.
Relates to: ADR-0029 (next-skill chain hints — this adds the authoring model for
third-party skills), ADR-0025 (keep-on's canonical durable home under
`~/.claude/skill-concierge/` — same ownership pattern), ADR-0011 (keep-off — same
"operator-owned overlay file" idiom), ADR-0005 (overrides target + applier precedent).
Source: owner-reported defect 2026-08-20 on the ADR-0029 deployment, same session as
the chain seeding recorded in `plans/reports/study-260820-2250-agent-playbook-router-portability.md`.

## Context

ADR-0029 authors chains in `SKILL.md` frontmatter (`next-skills:`). For skills the
operator owns (this repo's `skills/`, `skills-dev/`) that is durable: the file is the
dev surface. But for **third-party skills** the SKILL.md belongs to upstream:

- AgentKit skills are **plain-dir installs** in `~/.claude/skills/ak-*` — an AgentKit
  upgrade rewrites the directory and any frontmatter annotation with it.
- Plugin skills are read from the **versioned cache**
(`plugins/cache/<marketplace>/<plugin>/<version>/`) — a `/plugin marketplace update`
materializes a fresh version dir; curation in the old copy never reaches the new one.

Either way the failure is **silent**: upstream ships an upgrade → the annotated file is
replaced → the next reindex regenerates the sidecar from upstream's bytes → every
curated chain for that skill becomes `[]`. Nothing errors; nothing notices. Owner's
words: *"all of the curated next skill in a chain effort would be GONE without anyone
noticed, in a blink of an eye once the upstream decided an upgrade."*

The first seeding session (2026-08-20) hit exactly this: 8 chains were loaned into
frontmatter upstream owns, and the flaw was flagged as a "known limit" rather than
designed out. This ADR designs it out.

## Decision

- **Curation for third-party skills lives in an operator-owned file:**
  `~/.claude/skill-concierge/next-skills-overrides.json`, flat `{name: [successors]}`.
  Same durable-home pattern as keep-on (ADR-0025). Repathable via
  `SKILL_CONCIERGE_NEXT_SKILLS_OVERRIDES`. A `_note` key is ignored by the loader
  (only `str → list[str]` entries are merged).
- **Merged at READ time, reader-side.** `_visible_sidecar_names()` (the sidecar's ONLY
  consumer — verified by grep before implementation) applies
  `_apply_chain_overrides()` on top of the sidecar union. Semantics: **override-wins
  per whole name**; an empty list **deliberately suppresses** that skill's chain
  (local curation outranks upstream frontmatter); fail-open on absent/malformed file
  (curation config must never break a turn).
- **Reader-side on purpose, NOT an engine patch.** Alternatives rejected:
  - *Writer-side merge in the engine* (fold overrides into the sidecar at index time)
    costs a vendored patch + `VENDORED.md` entry + reindex coupling + an
    `auto_reindex` env-forwarding key — the exact ADR-0026 gap class. Since the
    enforcer is the only reader, merging there is behaviorally identical with none of
    that surface.
  - *Merge-don't-shrink sidecar* (preserve old entries when new frontmatter has none)
    masks genuine removals and breaks frontmatter-as-source-of-truth. Rejected.
  - *Symlinking the ak dirs to a dev farm* does not help — upstream still rewrites the
    file through whatever path it owns. The wipe mechanism is the rewrite, not the
    location.
- **All mechanized filters still apply to override chains:** hinted successors must be
  catalogue members (dangling override names — e.g. upstream renamed the successor —
  drop silently at hint time) and must clear keep-off. No floor is bypassed.
- **Frontmatter remains THE authoring surface for operator-owned skills.** Overrides
  are for third-party skills only. The 8 seeded ak chains were **migrated** to the
  overrides file and the loaned frontmatter lines reverted (7 from the seeding
  session, 1 — `ak-plan: ak-cook` — from the session before); upstream files are back
  to pristine.

## Consequences

- An upstream upgrade can no longer destroy chain curation: the overrides file is not
  in any path upstream writes. Survival by construction, not by detection.
- Known limit: a **renamed/removed successor** (dangling override name) drops silently.
  Correct behavior (a dead skill should not be hinted), but invisible; if it bites, the
  recorded upgrade is a doctor check diffing override names against sidecar keys.
- No version flag: absence of the file IS the off-switch (byte-identical behavior),
  matching how `keep-off.json` inertly defaults rather than adding an env per feature.
  The whole hint layer already has `ENFORCER_CHAIN_HINT=0`.
- `enforcer.py` changed → new ledger epoch; window chain-hint metrics from this
  commit, never pool across it (AGENTS.md epoch guardrail).

## Evidence

- `enforcer.py --selftest` extended (case 9b): override-wins over sidecar entry,
  dangling-name drop, keep-off drop of override successors, empty-list suppression,
  absent-file and malformed-file fail-open. All green alongside the 9 prior contract
  groups.
- End-to-end: after reverting all 8 frontmatter loans and reindexing, the sidecar holds
  only operator-owned chains (`verify-as-claimed→session-handoff`,
  `skill-concierge:doctor→skill-concierge:flywheel`) while `_chain_hint` still renders
  `CHAIN-HINT: after ak-cook, catalogue declares: ak-test, ak-code-review` — sourced
  solely from the overrides file.
