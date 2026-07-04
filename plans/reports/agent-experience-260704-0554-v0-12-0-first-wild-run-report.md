# Agent Experience Report — First Live Run Under v0.12.0

**Date:** 2026-07-04 05:54 (Asia/Saigon) · **Author:** operating agent (Opus 4.8), first-person
**Scope:** what the shipped v0.12.0 usefulness-rate governance actually did to me across this session
(a `/briefing` → `what-next` → verification arc). Not a spec review — a lived-run account.

## Environment confirmed (grounded, this session)

Live install `~/.claude/plugins/marketplaces/skill-concierge/` is fully v0.12.0 on all three surfaces:
- `plugin.json` → `0.12.0`
- `hooks/doctrine/skill-first.md` → carries library-doctrine + `SKILL-CHECK` text (v0.12.0)
- `hooks/scripts/enforcer.py` → carries `AUTHORIZED-SKIP`

The SessionStart doctrine injected into my context IS the v0.12.0 text (library-doctrine language +
AUTHORIZED-SKIP/`SKILL-CHECK` framing) — direct primary evidence this session ran under it.

## Post-ship verification (checklist per handoff L71–77)

| Check | Result |
|---|---|
| Docker (qdrant :6333 + embed-shim :6363) | up 27h, healthy |
| `enforcer.py --selftest` (ON leg) | OK (authorized-skip tier inject-on/silent-off) |
| `ENFORCER_AUTHORIZED_SKIP=0 enforcer --selftest` (OFF leg) | OK (silent-off path) |
| `audit_skill_usage.py --selftest` | OK (false-SKIPPING verdict) |
| `driftcheck.py` | IN SYNC |
| pytest `-m "not integration"` | 29 passed, 1 deselected |
| `doctor.py` | **WARN** — index stale (~15m, 488 serving vs 3570 total); multi-vector layer healthy (3082 trigger pts); corpus 12/14 ok. Retrieval serving — freshness nudge, not a break. |

## First-person experience

**1. The doctrine changed a real decision in my favor — once, observably.**
On "what's next based on the briefing," the skill preview surfaced `what-next` at **18%** — below the
25% "these don't obviously fit, I've got this" zone the *old* behavior tolerated a skip in. The v0.12.0
library-doctrine line — *"a loosely-adaptable fit is a USING, not a skip"* — is exactly what made me
invoke `what-next` rather than free-hand a to-do list. The outcome the change was built for (take the
fitting skill instead of improvising) happened on a live turn, not a selftest. Whether body-triggers
specifically lifted that rank I can't cleanly isolate.

**2. The AUTHORIZED-SKIP tier never fired on me — the honest gap.**
Every turn carried a real task with a fitting skill (briefing, what-next), so I always went `USING:` and
never hit the two silent legs (score-floor getaway / conversational skip) the `SKILL-CHECK:` inject
serves. Saw its selftest pass; never saw it act on me. The riskiest shipped change — the getaway leg,
ON against ADR-0009's data (decision D1) — got **zero live pressure** from this session.
First-in-the-wild ≠ first-stress-tested.

**3. The friction is real and it's a per-turn tax.**
Every turn: a line-1 token + a 5-candidate preview to parse. It steered me right this session, so the
tax bought something — but it's a standing cost on *every* turn to catch the subset where I'd have
wrongly skipped. That's the asymmetric-cost bet the library doctrine makes explicit; I felt both sides.

**4. Sharpest lesson — what governance does NOT touch.**
My briefing read the **wrong (older) handoff** (`ls -1t` missed the 0543 file written at session start);
the operator corrected me. The v0.12.0 apparatus made me pick the right *skill* every time and did
nothing to stop me feeding it a stale *input*. Retrieval/gating improves skill **selection**, not input
**correctness**. Hit that boundary live.

**5. My own process was the least reliable thing in the loop.**
Grounding the simple claim "am I on v0.12.0" took three passes — I twice ran a case-sensitive grep
against "Burden of proof" and got spurious false negatives. Plugin state was unambiguous throughout;
my verification was the sloppy part. Belongs in an honest experience account.

## Net

v0.12.0 is live, intact (one index-freshness WARN), and it changed a real decision in my favor this
session. But the piece most in need of live data — the getaway AUTHORIZED-SKIP leg — went unexercised,
because no turn was trivial enough to trigger it.

## Unresolved

- **doctor WARN** — index stale ~15m (488 serving vs 3570). Self-heal = reindex (a state change); left
  as-is pending operator call / in case a background reindex is mid-flight.
- **AUTHORIZED-SKIP getaway leg** — zero live exercise; needs organic conversational turns + the
  `skill-usage-audit` window the handoff calls for (~50–100 organic offered turns).
- **Body-trigger contribution** — not isolable from a single session; real measure is organic adoption
  via `analyze.py`, not the wrong-universe `eval/`.
 