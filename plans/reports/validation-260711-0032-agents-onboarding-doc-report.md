# Validation Report — AGENTS-ONBOARDING.md

**Method:** verify-as-claimed skill. Independent verifier (fresh context, not the doc's author)
ran the falsifiable-claim sweep with raw evidence; synthesizer (this agent) re-read the bytes and
reconciled. Read-only throughout — no state mutated.
**Subject:** `AGENTS-ONBOARDING.md` (repo root), a freshly-introduced 5-minute orientation doc.
**Oracle:** the repo itself. Every concrete claim (line counts, file existence, ADR count, command
validity, cross-references) must match reality.

## Verdict

**SHIP with one fix.** 14 of 15 checked claims PASS against raw bytes — line counts exact (not
off-by-one), all 28 ADRs and 15 caveat sections contiguous, `--selftest` and the epoch git-log
recipe execute and produce the claimed output. **One genuine doc defect:** the doc names
`skills/setup/SKILL.md` as the canonical skeleton for a required `argument-hint` key that file does
not contain.

## Summary table (each row cites a raw byte)

| # | Claim | Verdict | Evidence byte |
|---|---|---|---|
| 1 | skill-first.md = 112 lines | PASS | `112 hooks/doctrine/skill-first.md` (also confirmed by synthesizer's own read → L112 = `<!-- DOCTRINE-END -->`) |
| 2 | enforcer.py = 846 lines | PASS | `846 hooks/scripts/enforcer.py` |
| 3 | enforcer.py `--selftest`, repo-local, no env var | PASS | `enforcer --selftest OK ... EXIT=0` |
| 4 | 11 named files all exist | PASS | `ls` listed all 11, none missing |
| 5 | caveats.md = 15 landmines | PASS | `§1`…`§15` (synthesizer confirmed by own read) |
| 6 | 28 ADRs | PASS | `28` files, `0001`–`0028` contiguous |
| 7 | caveats §2/§5/§11/§14/§15 exist | PASS | all five headers grep-matched |
| 8 | three-organs.md:34-37 = in-generation, no post-hoc gate | PASS | "no Stop hook and no PostToolUse enforcement gate … rejected by design" (synthesizer confirmed by own read) |
| 9 | 6 scripts exist | PASS | analyze/apply-overrides/doctor/driftcheck/flywheel/keep-on all present |
| 10 | driftcheck.json at root | PASS | `driftcheck.json ... 1416 bytes` |
| 11 | `auto_reindex._mcp_env()` defined | PASS | `auto_reindex.py:40:def _mcp_env():` |
| 12 | ADR-0018 = launcher/venv resync; 0001/0005/0026/0028 exist | PASS | title "Self-healing launcher: auto-resync the venv engine…" |
| 13 | setup/SKILL.md is skeleton demonstrating name+user-invocable+argument-hint | **FAIL** | frontmatter = `name/user-invocable/description/license/metadata` — **no `argument-hint`** (rg: no match) |
| 14 | epoch git-log recipe runs; `scripts/embed_server.py` path valid | PASS | prints `2026-07-09 22:08:48`; path exists — no mismatch |
| 15 | repo-local selftest | PASS | (same as #3) EXIT=0 |

## The one defect (Claim 13) — genuine, not a fixture artifact

**Where:** AGENTS-ONBOARDING.md L85 ("Minimal skeleton: `skills/setup/SKILL.md`") and L138-139
("`skills/setup/SKILL.md` is the canonical minimal pattern. Required frontmatter keys: `name`,
`user-invocable`, `argument-hint`").

**Reality (firsthand bytes):**
- `skills/setup/SKILL.md` frontmatter = `name: skill-concierge:setup`, `user-invocable: true`,
  `description`, `license`, `metadata` — closes at the 2nd `---`. `rg 'argument-hint'` → no match.
- 5 of 6 skill-concierge skills DO carry `argument-hint`: skill-usage-audit, skill-search, keep-on,
  flywheel, doctor. `setup` is the lone one without.

**Why it's a real error:** the doc points a new-skill author at the one exemplar that omits the very
key it calls "required." Copy `setup/SKILL.md` as instructed → produce a non-conforming skill.
`setup` is argument-less, so its missing `argument-hint` is legitimate *for setup* — which is exactly
why it's a poor skeleton choice for that key.

**Fix options:**
1. Repoint the skeleton reference to a skill that actually carries `argument-hint` (e.g. `keep-on`
   or `flywheel`), OR
2. Keep `setup` but soften the claim — note `argument-hint` is required only for skills that take
   arguments (setup, being argument-less, legitimately omits it).

Option 2 is more accurate to the ClaudeKit pattern in caveats §15 and requires no cross-file check.

## Discrepancy the harness pre-flagged, cleared

The synthesizer flagged `scripts/embed_server.py` (referenced by the doc's L57 git-log command and
by CLAUDE.md) as a possible stale path. Verified: the file exists at exactly `scripts/embed_server.py`
and the command exits 0 printing a real datetime. **No mismatch — doc is correct.**

## Unresolved questions

None.
