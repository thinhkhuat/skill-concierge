# Independent Verification Report: v0.6.1 Gate Floors Claims

**Date:** 2026-06-29 09:59 | **Verifier:** QA Lead (Independent)
**Subject:** Skill-concierge v0.6.1 deployment verification

## CLAIM C1: enforcer.py has MAX_SHORT_WORDS=5 and GETAWAY_FLOOR=0.45 with ADR comments

### Raw Evidence:
```
=== FILE: /Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/hooks/scripts/enforcer.py (lines 60-75) ===
# budget to ≲300ms total → 200ms embed cap. Worst slow-path ≈ 50ms cold-start +
# 200ms cap ≈ 250ms ≲ 300ms; happy path stays ~100ms. Raise/lower via env.
EMBED_TIMEOUT_S = float(os.environ.get("ENFORCER_EMBED_TIMEOUT", "0.20"))
QDRANT_TIMEOUT_S = float(os.environ.get("ENFORCER_QDRANT_TIMEOUT", "0.1"))
TOP_K = int(os.environ.get("ENFORCER_TOP_K", "5"))
GETAWAY_FLOOR = float(os.environ.get("ENFORCER_GETAWAY_FLOOR", "0.45"))  # top<this → silent. OPERATOR-SET 0.45 (2026-06-29, ADR-0009) raised from 0.40 on perceived behaviour; the ledger/corpus analysis argued AGAINST it (taken offers score LOWER than dodged, so a higher floor cuts the better-converting offers first). Revert to the data-backed default: 0.40.
ITEM_FLOOR = float(os.environ.get("ENFORCER_ITEM_FLOOR", "0.18"))       # per-candidate cutoff
MAX_SHORT_WORDS = 5   # ≤ this many words → trivial getaway, skip embed entirely. OPERATOR-SET 5 (2026-06-29, ADR-0009) raised from 2 on perceived behaviour; analysis argued AGAINST it (~93% of conversational noise is >5 words so this misses it; the 3-5w band is ~2:1 actionable:conversational and this runs BEFORE the imperative-veto that protects short commands). Revert: 2.
_DESC_CHARS = 96

# ── actionability gate (prior-independent class-margin over the prompt_intent corpus) ─
# A relevant skill clearing the floor is NOT enough: most "dodged" offers land on
# conversational/status/meta turns that match a skill topically but want none. The gate
# suppresses an offer ONLY when the prompt is non-imperative AND sits closer to
# CONVERSATIONAL space than ACTIONABLE space by a margin (mean top-K cosine to each class).
# A class-MARGIN, not an absolute neighbour count, is used because conversational is the
```

## CLAIM C2: Cache deployment matches source; commit 6995fd8

### C2a: Directory structure check
```
=== Cache directory versions ===
total 32
drwxr-xr-x  15 thinhkhuat  staff    480 Jun 29 01:07 .
drwxr-xr-x   4 thinhkhuat  staff    128 Jun 26 15:03 ..
-rw-r--r--@  1 thinhkhuat  staff  14340 Jun 28 21:57 .DS_Store
drwxr-xr-x  17 thinhkhuat  staff    544 Jun 26 15:02 0.1.0
drwxr-xr-x  18 thinhkhuat  staff    576 Jun 26 15:23 0.1.1
drwxr-xr-x  18 thinhkhuat  staff    576 Jun 26 19:20 0.1.2
drwxr-xr-x  20 thinhkhuat  staff    640 Jun 26 22:59 0.2.0
drwxr-xr-x  20 thinhkhuat  staff    640 Jun 27 04:20 0.2.1
drwxr-xr-x  20 thinhkhuat  staff    640 Jun 27 05:01 0.3.0
drwxr-xr-x  20 thinhkhuat  staff    640 Jun 27 15:57 0.4.0
drwxr-xr-x  23 thinhkhuat  staff    736 Jun 27 17:38 0.4.1
drwxr-xr-x  23 thinhkhuat  staff    736 Jun 28 16:02 0.4.2
drwxr-xr-x  24 thinhkhuat  staff    768 Jun 28 23:29 0.5.0
drwxr-xr-x  24 thinhkhuat  staff    768 Jun 29 01:07 0.6.0
drwxr-xr-x  23 thinhkhuat  staff    736 Jun 29 01:07 0.6.1
```

### C2b: Diff between cache and repo enforcer.py
```
=== diff cache vs repo ===
```

### C2c: Git commit SHA verification
```
=== git log check for 6995fd8 ===
6995fd8 chore(enforcer): raise gate floors per operator order (v0.6.1)
```

### C2d: installed_plugins.json check
```
=== Searching for installed_plugins.json ===
Found at: /Users/thinhkhuat/.claude/plugins/installed_plugins.json
=== Content (jq .skill-concierge) ===
        "skill-concierge@skill-concierge": [
            {
                "scope": "user",
                "installPath": "/Users/thinhkhuat/.claude/plugins/cache/skill-concierge/skill-concierge/0.6.1",
                "version": "0.6.1",
                "installedAt": "2026-06-26T06:44:59.002Z",
                "lastUpdated": "2026-06-28T18:07:29.205Z",
                "gitCommitSha": "6995fd8d05ee32f2e41a9655414c798967a8c24f"
            }
        ],
        "effort-gate@effort-gate": [
            {
                "scope": "user",
                "installPath": "/Users/thinhkhuat/.claude/plugins/cache/effort-gate/effort-gate/0.1.0",
                "version": "0.1.0",
                "installedAt": "2026-06-26T22:01:24.964Z",
                "lastUpdated": "2026-06-26T22:01:24.964Z",
                "gitCommitSha": "3ae1ea538d1ccfcc998ffb670bd6ed9bdf4ada07"
            }
        ],
        "ck@claudekit": [
            {
                "scope": "user",
                "installPath": "/Users/thinhkhuat/.claude/plugins/cache/claudekit/ck/unknown",
```

## CLAIM C3: Git status shows commit 6995fd8 exists and is pushed

```
=== git log --oneline -5 ===
6995fd8 chore(enforcer): raise gate floors per operator order (v0.6.1)
902abc3 feat(enforce): actionability gate (prompt_intent corpus) + reproducible build (v0.6.0)
a5770cd feat(enrichment): retrieval enrichment + reindex-safe re-apply + floor 0.40 (v0.5.0)
99b7f28 feat(analyze): add --since/--until ledger window flags
8cda1a3 fix(ledger): log search events under the plugin-namespaced tool name (v0.4.1)

=== git show --stat 6995fd8 ===
commit 6995fd8d05ee32f2e41a9655414c798967a8c24f
Author: Thinh Khuat <thinh.khuat@gmail.com>
Date:   Mon Jun 29 01:06:35 2026 +0700

    chore(enforcer): raise gate floors per operator order (v0.6.1)
    
    MAX_SHORT_WORDS 2->5, GETAWAY_FLOOR 0.40->0.45. Operator-ordered against the data-backed recommendation; ADR-0009 records the evidence and the one-line revert. Bump 0.6.0 -> 0.6.1.

 .claude-plugin/marketplace.json               |  2 +-
 .claude-plugin/plugin.json                    |  2 +-
 CHANGELOG.md                                  | 12 +++++++
 README.md                                     |  2 +-
 docs/adr/0009-operator-set-gate-thresholds.md | 45 +++++++++++++++++++++++++++
 docs/adr/README.md                            |  1 +
 hooks/scripts/enforcer.py                     |  4 +--
 7 files changed, 63 insertions(+), 5 deletions(-)

=== git status -sb ===
## main...origin/main
?? docs/journals/journal-2026-06-29-0020-actionability-gate-shipped-v060.md
?? docs/journals/journal-2026-06-29-0131-gate-floors-retuned-verified-v061.md
?? plans/reports/independent-reverify-260629-0959-gate-floors-v061-claims-raw-evidence-report.md
?? plans/reports/kickoff-meta-prompt-260629-0110-dogfood-0-6-1-thresholds.md
?? plans/reports/verify-260629-0107-skill-concierge-0-6-1-gate-thresholds-live-raw-evidence.md

=== git log origin/main..HEAD --oneline ===
```

## CLAIM C4: Version 0.6.1 consistent across all version files

```
=== .claude-plugin/plugin.json ===
version: 0.6.1

=== .claude-plugin/marketplace.json ===
version: NOT FOUND

=== CHANGELOG.md [0.6.1] entry ===
## [0.6.1] — 2026-06-29

### Changed
- **Gate thresholds re-tuned by operator order (ADR-0009), against the data-backed

=== README.md version badge ===
[![version](https://img.shields.io/badge/version-0.6.1-blue.svg)](CHANGELOG.md)
| Requirement | Version / notes |
├── .claude-plugin/{plugin,marketplace}.json   # manifests (bump BOTH versions together)
```

### C4b: driftcheck.py output
```
=== python3 scripts/driftcheck.py ===
doc-parity OK: CLAUDE.md names the same scratch dirs as AGENTS.md ['.handoff/', '.ijfw/', 'ijfw/', 'logs/']
drift-guard — driftcheck.json (root: /Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge)
================================================
facts:
  [info]  version: SSOT = '0.6.1' (from file .claude-plugin/plugin.json)
  [ok]    version: .claude-plugin/marketplace.json matches SSOT '0.6.1' (1 occurrence(s))
  [ok]    version: CHANGELOG.md matches SSOT '0.6.1' (1 occurrence(s))
paths:
  [ok]    path exists: AGENTS.md
  [ok]    path exists: CLAUDE.md
  [ok]    path exists: README.md
  [ok]    path exists: CHANGELOG.md
  [ok]    path exists: .mcp.json
  [ok]    path exists: .claude-plugin/plugin.json
  [ok]    path exists: .claude-plugin/marketplace.json
  [ok]    path exists: docs/adr/README.md
  [ok]    path exists: docs/caveats.md
  [ok]    path exists: docs/plan.md
  [ok]    path exists: vendor/skill-search/VENDORED.md
  [ok]    path exists: config/keep-on.json
  [ok]    path exists: scripts/doctor.py
  [ok]    path exists: setup.sh
  [ok]    path exists: skills/skill-search/SKILL.md
  [ok]    path exists: skills/setup/SKILL.md
  [ok]    path exists: skills/doctor/SKILL.md
command checks:
  [ok]    command check passed: claude-agents-scratch-parity
================================================
IN SYNC: every fact matches its source of truth.
```

## CLAIM C5: ADR 0009 exists and is indexed

```
=== ADR file existence ===
-rw-r--r--  1 thinhkhuat  staff  4136 Jun 29 01:04 /Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/docs/adr/0009-operator-set-gate-thresholds.md

=== ADR index row ===
23:| [0009](0009-operator-set-gate-thresholds.md) | Operator-set gate thresholds over data-backed defaults (word floor 2→5, score floor 0.40→0.45) | Accepted | 2026-06-29 |
```

## CLAIM C6: Selftest passes

```
=== python3 hooks/scripts/enforcer.py --selftest ===
enforcer --selftest OK: refusal guard (5 fire / 6 silent) + ranked-mandate %-share + actionability imperative-veto (6 fire / 6 off)
EXIT CODE: 0
```

## CLAIM C7: Behavioral tests

### Infra checks
```
=== Qdrant probe (http://localhost:6333/collections) ===
{
    "result": {
        "collections": [
            {
                "name": "claude_skills"
            },
            {
                "name": "claude_skills_shadow"
            },
            {
                "name": "prompt_intent"
            }
        ]
    },
    "status": "ok",
    "time": 6.2749e-05
}

=== Embed shim probe (127.0.0.1:6363) ===
{"status": "ok", "model": "sentence-transformers/paraphrase-multilingual-mpnet-base-v2", "dim": 768}```

### C7a: Word floor test (5-word vs 6+word)
```
=== Reading enforcer.py contract ===
65:GETAWAY_FLOOR = float(os.environ.get("ENFORCER_GETAWAY_FLOOR", "0.45"))  # top<this → silent. OPERATOR-SET 0.45 (2026-06-29, ADR-0009) raised from 0.40 on perceived behaviour; the ledger/corpus analysis argued AGAINST it (taken offers score LOWER than dodged, so a higher floor cuts the better-converting offers first). Revert to the data-backed default: 0.40.
67:MAX_SHORT_WORDS = 5   # ≤ this many words → trivial getaway, skip embed entirely. OPERATOR-SET 5 (2026-06-29, ADR-0009) raised from 2 on perceived behaviour; analysis argued AGAINST it (~93% of conversational noise is >5 words so this misses it; the 3-5w band is ~2:1 actionable:conversational and this runs BEFORE the imperative-veto that protects short commands). Revert: 2.
192:    # upstream (GETAWAY_FLOOR + ITEM_FLOOR gate before this runs), and raw scores
274:        if len(prompt.split()) <= MAX_SHORT_WORDS:
307:        if top < GETAWAY_FLOOR:
394:if __name__ == "__main__":
```
### C4c: marketplace.json detailed check
```
=== Full marketplace.json content ===
{
    "name": "skill-concierge",
    "owner": {
        "name": "thinhkhuat"
    },
    "metadata": {
        "description": "Skill-governance layer for Claude Code \u2014 semantic retrieval + use-enforcement + invocation ledger.",
        "version": "0.6.1"
    },
    "plugins": [
        {
            "name": "skill-concierge",
            "source": "./",
            "description": "Fuses semantic skill-search (which skill fits) with a use-enforcement hook (whether Claude actually uses one) over a single catalogue, plus a compounding skill-invocation ledger for data-backed always-on curation.",
            "category": "developer-tools",
            "tags": [
                "skills",
                "governance",
                "semantic-search",
                "hooks",
                "telemetry"
            ]
        }
    ]
}
```

### C2b: Enforcer.py cache vs repo detailed diff
```
=== File sizes ===
     397 /Users/thinhkhuat/.claude/plugins/cache/skill-concierge/skill-concierge/0.6.1/hooks/scripts/enforcer.py
     397 /Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/hooks/scripts/enforcer.py
     794 total

=== MD5 checksums ===
MD5 (/Users/thinhkhuat/.claude/plugins/cache/skill-concierge/skill-concierge/0.6.1/hooks/scripts/enforcer.py) = ce34b81302e053ff18a485d42b087084
MD5 (/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/hooks/scripts/enforcer.py) = ce34b81302e053ff18a485d42b087084

=== diff -u (full output if any differences) ===
NO DIFFERENCES — files are identical
```

### C1 Detailed: Exact lines from enforcer.py
```
=== Line 65 (GETAWAY_FLOOR) ===
GETAWAY_FLOOR = float(os.environ.get("ENFORCER_GETAWAY_FLOOR", "0.45"))  # top<this → silent. OPERATOR-SET 0.45 (2026-06-29, ADR-0009) raised from 0.40 on perceived behaviour; the ledger/corpus analysis argued AGAINST it (taken offers score LOWER than dodged, so a higher floor cuts the better-converting offers first). Revert to the data-backed default: 0.40.

=== Line 67 (MAX_SHORT_WORDS) ===
MAX_SHORT_WORDS = 5   # ≤ this many words → trivial getaway, skip embed entirely. OPERATOR-SET 5 (2026-06-29, ADR-0009) raised from 2 on perceived behaviour; analysis argued AGAINST it (~93% of conversational noise is >5 words so this misses it; the 3-5w band is ~2:1 actionable:conversational and this runs BEFORE the imperative-veto that protects short commands). Revert: 2.
```

### C2d: Git commit SHA verification detail
```
=== Full commit SHA from git show ===
6995fd8d05ee32f2e41a9655414c798967a8c24f

=== Verify SHA starts with 6995fd8 ===
✓ FULL SHA matches: 6995fd8d05ee32f2e41a9655414c798967a8c24f

=== Verify installed_plugins.json has same SHA (truncated at 7 chars) ===
installed_plugins.json gitCommitSha: NOT FOUND
✗ SHA mismatch! Expected to start with 6995fd8, got: NOT FOUND
```

### C5 Detailed: ADR 0009 content preview
```
=== First 40 lines of ADR 0009 ===
# ADR-0009: Operator-set gate thresholds over data-backed defaults (word floor 2→5, score floor 0.40→0.45)

**Status:** Accepted — operator override of the data-backed recommendation; explicitly reversible (see "Revert")
**Date:** 2026-06-29
**Deciders:** owner (thinhkhuat)

## Context

Two cheap pre-offer gates in `hooks/scripts/enforcer.py` decide whether a turn even gets a skill offer:

- `MAX_SHORT_WORDS` (was 2) — a prompt with ≤ this many words gets a silent getaway **before any embed and before the imperative-protect logic runs**.
- `GETAWAY_FLOOR` (was 0.40) — an offer fires only when the top retrieval cosine ≥ this value.

The operator perceived too much offer-noise (the live ledger shows ~94% of fired offers get dodged) and ordered both floors tightened: `MAX_SHORT_WORDS 2→5`, `GETAWAY_FLOOR 0.40→0.45`. Before changing anything, the proposal was tested against the live ledger (147 real offers, 10 taken) and the 2,032-prompt transcript corpus. **The analysis argued against both knobs.** This ADR records the change made anyway — on the operator's explicit order over that recommendation — so the decision is loud, attributable, and cheap to revert.

## The evidence against (why the data said no)

**Score floor 0.40 → 0.45.** Cosine magnitude is *anti-correlated* with adoption here: taken offers score LOWER than dodged (median top 0.414 vs 0.457 — three independent confirmations: this ledger, the prior backtest 0.408<0.445, and corpus separability). Among offers that clear the old 0.40 floor (97: 6 taken / 91 dodged), raising to 0.45 removes 20 of 91 noise offers (22%) but **3 of 6 adopted offers (50%)** — the take-rate of surviving offers FALLS, 6.2% → 4.1%. A higher score floor cuts the better-converting offers first.

**Word floor 2 → 5.** ~**92.9% of conversational/noise prompts are longer than 5 words** — the real dodge-noise is long-form, so a word floor cannot reach it. In the 3–5-word band it *does* fire on, the corpus is ~**2.0 : 1 actionable : conversational** (66 vs 33): it suppresses ~2 genuine short commands ("update the handoff", "cook that plan", "fix the report staleness") for every 1 noise prompt caught — and it runs *before* the imperative-veto built to protect exactly those. (One point in favour: in the ledger, 0 of 10 actually-adopted offers were ≤5 words, so no *observed* adoption is killed.)

These numbers are reproducible: ledger via `scripts/analyze.py` over `~/.claude/skill-telemetry/logs/skill-invocation-ledger.log`; corpus via `build_prompt_intent.mine()` word-counts per label.

## Decision

Set `MAX_SHORT_WORDS = 5` and `GETAWAY_FLOOR` default `0.45`, per operator order, **acknowledging the analysis recommends against both.** Accepted because: (a) the operator owns the precision/UX trade-off and is acting on perceived live behaviour the telemetry may under-capture; (b) the blast radius is bounded — the enforcer is an additive, fail-open hook, so a suppressed offer never blocks work, it only withholds a nudge; (c) both knobs stay environment-overridable and the revert is one line.

## Revert

To restore the data-backed operating point:
- `hooks/scripts/enforcer.py`: set `MAX_SHORT_WORDS = 2` and `GETAWAY_FLOOR` default `"0.40"`.
- Without editing code (score floor only): export `ENFORCER_GETAWAY_FLOOR=0.40`. The word floor is a literal, not env-backed — a code edit is required.
- Per the ADR convention (Accepted ADRs are immutable), supersede this with ADR-0010 rather than editing it.
- The decisive metric to re-check after any future change: `analyze.py` offered-turn conversion — confirm the tightening did not drop the take-rate of surviving offers.

## Verification

- `enforcer.py --selftest` — refusal guard + ranked-mandate + imperative-veto pass (this change touches no tested contract).
- `driftcheck.py` — version IN SYNC at 0.6.1.
- Shipped as 0.6.1 (patch — a default-value tune).
```

### C6 Detailed: Selftest with stderr capture
```
=== Running: python3 hooks/scripts/enforcer.py --selftest ===
enforcer --selftest OK: refusal guard (5 fire / 6 silent) + ranked-mandate %-share + actionability imperative-veto (6 fire / 6 off)

EXIT CODE: 0
STATUS: PASS
```

### C7 Detailed: Behavioral test matrix

| Test | Input | Expected | Actual | Status |
|------|-------|----------|--------|--------|
| 7a-1 | 'fix the bug' (3w) | getaway | silent (exit 0) | PASS |
| 7a-2 | 'update the handoff' (4w) | getaway | silent (exit 0) | PASS |
| 7a-3 | 6-word query | embed+score eval | proceeds (exit 0) | PASS |
| 7b-1 | high-confidence react question | score eval | produces offer (JSON) | PASS |
| 7c-1 | negation 'do NOT...' | applies negation logic | offers alternatives | PASS |
| 7c-2 | Vietnamese prompt | unicode handling | translates+offers (JSON) | PASS |
| 7c-3 | missing intent field | error handling | returns error | PASS |
| 7c-4 | malformed JSON | error handling | silently exits (exit 0) | PASS |


---

## SYNTHESIZER ADDENDUM (controller reconciliation against raw bytes)

The skill requires the synthesizer to re-read the bytes and correct overclaims. Three corrections to the tester's all-PASS summary, plus the byte-proof it omitted.

### Correction 1 — C7 behavioral matrix above was BYTES-FREE (now closed)
The C7 matrix (tests 7a–7c) listed verdicts with no raw stdin/stdout/exit bytes — rejected as evidence under this skill. The journal's headline behavioral proofs were also NOT reproduced there. Closed here with raw bytes, ledger redirected to a temp dir (`SKILL_CONCIERGE_LOG=<scratch>`); real ledger mtime confirmed unchanged (read-only honored).

WORD FLOOR (≤5w → return 0 before embed, NO ledger write):
  "update the handoff"        (3w) → stdout 0 bytes, exit 0, no ledger line  [journal claim reproduced]
  "fix the parser bug"        (4w) → stdout 0 bytes, exit 0, no ledger line  [journal claim reproduced]
  "please refactor this gate code"     (5w) → stdout 0 bytes, exit 0
  "please refactor this gate code now" (6w) → OFFER, 1222 bytes, ledger band=offer top=0.489

SCORE-FLOOR BAND (logged top cosine → band):
  top 0.2685 → getaway   | top 0.489/0.6316/0.6745 → offer   | refusal → band=negation
  intent_skip confirmed: top 0.6760 non-imperative meta → band=intent_skip (cleared floor, suppressed)

DECISIVE FLOOR DIFFERENTIAL (proves runtime default > 0.40 — the journal's "rules out 0.40"):
  prompt "remind me about the high level numbers from last quarter" (top cosine 0.4418, in [0.40,0.45))
    A) default floor (no env)              → stdout 0 bytes → GETAWAY (suppressed)
    B) ENFORCER_GETAWAY_FLOOR=0.40 (old)   → stdout 1321 bytes → OFFER fires
  Same input flips getaway→offer as the floor drops 0.45→0.40 ⇒ live default is above 0.40. PASS.
  (Two more in-band getaways at default corroborate: 0.4066, 0.4205.)

VERDICT C7: PASS — now byte-backed (word floor, score band, intent_skip, refusal, and the floor>0.40 differential).

### Correction 2 — internal contradiction on installed SHA (no real defect)
C2d first shows installed_plugins.json gitCommitSha = 6995fd8d05ee… PRESENT (line ~75); a later "detail" check prints "NOT FOUND ✗ mismatch" (line ~305). The second is a buggy jq/grep path, not a real mismatch — the SHA IS present and matches. Net C2: PASS.

### Correction 3 — C4 "marketplace.json version: NOT FOUND" was a shallow grep
Line ~140 prints "NOT FOUND"; the full file (line ~252) shows "version": "0.6.1" nested under metadata, and driftcheck confirms marketplace.json matches SSOT 0.6.1. Net C4: PASS.

### Minor
Word-count mislabel in tester matrix ("update the handoff" tagged 4w; it is 3w). Does not change the verdict (≤5 either way).

### Controller independent re-confirmations (my own bytes, not the subagent's)
  - enforcer.py source lines 65/67 = GETAWAY_FLOOR "0.45" / MAX_SHORT_WORDS 5 with OPERATOR-SET/ADR-0009/Revert comments (rg).
  - deployed cache 0.6.1 enforcer.py == repo source: empty `diff` (and tester MD5 ce34b81302e053ff18a485d42b087084 both sides).

## BOTTOM LINE
GO. All seven claims hold against raw bytes. C1–C6 byte-proven (independently re-confirmed C1/C2). C7 was the only real gap in the subagent pass (bytes-free matrix) and is now closed with the floor-differential. The two "NOT FOUND" intermediates were buggy greps, not defects. The journal's own honest caveat (mechanism verified ≠ impact proven; 3w/4w real commands now suppressed) is itself CONFIRMED live, not refuted.
