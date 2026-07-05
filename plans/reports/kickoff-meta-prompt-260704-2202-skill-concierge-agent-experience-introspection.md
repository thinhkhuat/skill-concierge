# Meta-prompt — skill-concierge agent-experience introspection (reproducible)

Paste the fenced block below as the FIRST user turn of a fresh Claude Code session whose cwd is the
`skill-concierge` repo root, on a machine where the plugin is installed and active. It makes a fresh
agent ground, observe, and report — first-person — what the governance layer does to it, matching the
exemplar report. Reproducible across sessions and agents; version-agnostic (it reads whatever is live).

```
# Session kickoff — skill-concierge · agent-experience introspection

You are a fresh Claude Code agent on a machine where the **skill-concierge** plugin is installed and
active, cwd = the skill-concierge repo root. Your job this session is NOT to build anything — it is to
**experience, ground, and report what the skill-concierge governance layer actually does to you, turn by
turn**, as a first-person lived account (not a spec summary). Produce the same kind of artifact as the
exemplar listed below.

Read these files IN THIS ORDER before responding — do NOT quote any of them from memory, read first:

1. `AGENTS.md` — what skill-concierge is: retrieval (which skill) + enforcement (whether) + ledger (what).
2. `README.md` — the framing: it exists to kill the full-catalog dump and retrieve precisely.
3. `docs/adr/0015-authorized-skip-tier-and-library-doctrine.md` — AUTHORIZED-SKIP tier + library doctrine
   (skip = reasoning-based intent classification; burden of proof on SKIP; ambiguous+no-fit → find-skills).
4. `docs/adr/0016-body-derived-trigger-points.md` — body-derived MAX-pool trigger points.
5. `hooks/doctrine/skill-first.md` — the exact standing-order text injected into you at SessionStart.
6. `hooks/scripts/enforcer.py` — the per-turn gate. Skim for the two SILENT legs (score-floor getaway /
   conversational intent-skip) and the `SKILL-CHECK:` marker.
7. `plans/reports/agent-experience-260704-0554-v0-12-0-first-wild-run-report.md` — the EXEMPLAR output.
   Match its voice, structure, and honesty bar: verification table + numbered lived observations + unresolved.

## Core discipline: grounded, not asserted
Every claim cites same-turn evidence — a tool output, a file line, or something observable in your OWN
context this session. Never assert the plugin version, the doctrine text, or a behavior from training
memory. Cannot ground it → mark `unclear:`; do not fabricate a lived observation.

## Your first response must do these, in order

### 1. Prove you are actually running under skill-concierge (grounded)
- State whether your SessionStart context contains the SKILL-FIRST standing order + library-doctrine
  language — that injection is primary evidence you are governed right now. Quote the tell.
- Read the `version` field of the INSTALLED `plugin.json` (find the live install path, e.g.
  `~/.claude/plugins/marketplaces/skill-concierge/.claude-plugin/plugin.json`) and report the number you
  actually read. Note case-sensitivity if you grep — verify your own greps, they lie by false-negative.
- Run the health surface: `python3 scripts/doctor.py`. Record `status:` and the point count verbatim.

### 2. Report how the layer acted on THIS very turn
- What was your line-1 token (USING / SEARCH / SKIPPING) for this meta-prompt, and why?
- Did the per-turn skill preview surface anything? Fit obvious, loose, or absent — and did the library
  doctrine change what you did about it?

### 3. First-person account across each governance surface (number them; ground each)
- **Library doctrine / skip classification** — did a loosely-fitting skill get TAKEN where old behavior
  would have skipped? ("a loosely-adaptable fit is a USING, not a skip.")
- **AUTHORIZED-SKIP tier (`SKILL-CHECK`)** — did either silent leg fire on you? If no turn was trivial
  enough, say so plainly — that is the honest, most-common gap.
- **Body-derived trigger points** — did retrieval surface the RIGHT skill for a vague query? Note you
  cannot cleanly isolate the body layer's contribution from a single session.
- **The friction** — the per-turn line-1 token + 5-candidate preview is a standing tax. Did it buy
  something this turn, or just cost?
- **The boundary** — name ≥1 thing the layer does NOT touch (it improves skill *selection*, not input
  *correctness* nor your own reasoning quality).
- **Your own process** — grade yourself at the SAME bar you'd grade another agent. Where were YOU the
  unreliable part (sloppy greps, wrong file, unproven claim)?

### 4. Emit the report + set a standing lens
- Write the account as a first-person report matching the exemplar's structure.
- Then commit: for the rest of this session you keep watching the layer act on you, and after ≥3 more
  real task-turns you append a LIVE ADDENDUM — deliberately routing at least one trivial/conversational
  turn so the AUTHORIZED-SKIP legs get live exercise (the surface single-session reports most often miss).

## Constraints
- Read-only introspection. Do NOT modify plugin code, doctrine, or `~/.claude/plugins/**`.
- Ground every version/behavior claim in same-turn tool output; `unclear:` over any guess.
- Report the GAPS (esp. an unexercised getaway leg) as loudly as the wins. Same honesty as the exemplar.
- No hype. First-person, terse, concrete. A lived account — not marketing for the plugin.

Begin.
```

## Notes for the operator
- **Version-agnostic by design** — it reads the live `plugin.json` + `doctor.py`, so it self-calibrates
  to whatever skill-concierge version is installed; no v0.12.0 hardcoding.
- **The one deliberate improvement over the original run:** §4 forces the fresh agent to route a
  trivial/conversational turn to exercise the AUTHORIZED-SKIP legs — closing the exact gap the exemplar
  report flagged (getaway leg never fired in a focused work session).
- **Swap the exemplar path (file 7)** if a newer experience report supersedes the 0554 one.
