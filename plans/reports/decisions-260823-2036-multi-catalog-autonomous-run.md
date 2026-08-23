# Decisions log — autonomous implementation run, ADR-0031 (owner AFK)

Session 2026-08-23 ~20:57+. Owner order: implement everything per the grilled
decisions; undecided points decided on his behalf, each documented here with
rationale. Appended live as the run proceeds.

## D1 — Execute directly against plan.md; do not spin up the GoalBuddy (/goal) loop

Owner phrasing "keep working autonomously with the /goal clearly defined" is
ambiguous between the GoalBuddy skill and the plain word. Checked: no goal board
exists in the repo (`/goal` runs against a *prepared* board; `goal-prep` would have to
build one first). Rationale: `plans/260823-2036-multi-catalog-roots/plan.md` already
IS the goal definition (phases, acceptance checks, non-goals, authority link);
GoalBuddy's scout/worker/judge agent ceremony would spend the ~1h AFK window on
process instead of implementation. Direct execution with the plan as the board, plus
a blind validation agent before DONE (RULES [57]), preserves the same
independent-check property the loop provides.

## D2 — Search-only tier enforced via a `tier: "external"` payload field, not alias enumeration

The enforcer queries Qdrant directly over REST with no scope filter
(`enforcer.py:_retrieve`). Excluding catalogs by enumerating `catalog:<alias>` scope
values would make the per-turn hook read the config file every turn and drift if it
can't. One constant field on every catalog point (base + trigger) lets the hook
exclude the whole tier with a single static `must_not` condition — no config read on
the hot path, robust to any number of catalogs. Pinned by enforcer selftest case 10
(request-shape assertion).

## D3 — Catalog skills stay OUT of the next-skills sidecar

Sidecar key presence is the enforcer's catalogue-membership signal for CHAIN-HINT
(ADR-0029) — a preview-layer mechanism. Externals are search-only by owner decision
(Q2); letting 1,599 external names into the membership set would allow chains to hint
skills the Skill tool cannot invoke, and bloat a file read on inject-bearing turns.

## D4 — Catalog scopes excluded from skillOverrides generation

`apply-overrides.py` and the engine's `generate_overrides.py` write a
`skillOverrides` entry per discovered skill. External skills are not registered with
Claude Code, so entries for them free zero budget and would quadruple settings.json
(~400 → ~2,000 keys). Both enumerations now skip `catalog:*` scopes.

## D5 — Alias collisions handled by precedence, not hard rejection (softens the plan's Phase-1 line)

Plan said "reject aliases colliding with installed plugin ids — fail loudly". Hard
rejection would dark an entire 1,600-skill catalog over one name overlap, and the
collision class is already neutralized structurally: catalogs are discovered LAST and
`found.setdefault` keeps the installed skill for any identical namespaced name — the
invokable copy always wins, which is the truthful outcome. Config-load warnings still
fire for malformed aliases/paths. (Owner may re-tighten; one-line change.)

## D6 — External result rows: no `command`, no absolute path; `external` + consumption note instead

A `/name` command field on an uninstalled skill is a lie (nothing registered), so it
is dropped. The absolute path is NOT included because a skill's best-scoring point is
often a TRIGGER point, whose payload deliberately carries no `path` — and the
consumption path is `get_skill(name)` anyway, which resolves the path server-side.
Row shape: `{name, description, score, external: <alias>, note: "…get_skill…"}`.

## D7 — Ledger event class is `get_skill` (all deep pulls), external classification downstream

Rather than an `external-take` event only for catalog names (which would require the
hook to read catalog config per call), the ledger hook logs EVERY get_skill pull with
its name; `analyze.py` splits external takes by the configured alias prefixes at
analysis time. Richer data (installed deep pulls become visible too), zero hot-path
config reads, same measurability. hooks.json PostToolUse matcher extended to
`(search_skills|get_skill)`.

## D8 — pytest installed into the stable engine venv

The engine's full test suite (indexing/fusion/CLI) needs qdrant_client, present only
in the stable venv (`~/.claude/skill-concierge/venv`), which lacked pytest. Installed
pytest there (dev-only additive dep, no runtime impact) so the suite runs in the real
engine environment: 73 passed.

## D9 — Live deploy + catalog registration + reindex executed during the AFK run

Plan Phase 5 is the ship gate and the owner's GO covers completion "working
correctly". Engine re-copied into the stable venv, `antigravity` registered
(1,603 skills on disk), incremental reindex launched with the SSOT env forwarded
exactly as auto_reindex does (SKILL_LLM_TRIGGERS=1, TRIGGERS_MAX=16, SKILL_TRIGGERS
at the durable home — the v0.21.1 wipe-lesson env set). Known consequence: the LIVE
MCP server still runs the pre-deploy engine build until the app restarts, so doctor
will show the documented build-drift WARN that clears at the next session start.
## D10 — Blind validator run + defect remediation (post-implementation)

Spawned an independent `agent-validator` (fresh context, told what to verify, not what
to expect) per RULES [57]. Verdict: DONE_WITH_CONCERNS — all mechanics CONFIRMED-OK and
live-verified (namespacing, right-way realpath dedup, prune safety, tier=external on all
13,376 catalog points, pinned+live per-turn exclusion, clean sidecar/overrides/flywheel),
defects confined to the verification/record layer. All fixed same run:

- **B1 (real bug, generator-level):** test suite non-hermetic — `conftest.py` didn't pin
  `SKILL_CONCIERGE_CATALOG_ROOTS`, so pre-existing count-exact tests read the operator's
  LIVE catalog and 2 failed on this machine. Fixed at the generator: conftest now pins it
  to a nonexistent path (RULES [73] fix-the-generator). Discovery+overrides 40 pass;
  full-suite re-run to re-establish the true count (invalidating the stale D8 "73 passed").
- **B3:** plan checkbox asserted a plugin-id-collision rejection never built → marked `[~]`
  with the D5 softening spelled out.
- **B4:** ADR header "implementation pending" → "Accepted + implemented"; Decision 6 text
  claimed "absolute path" in external rows (D6 dropped it) → amended to match shipped shape.
- **B5:** `auto_reindex.py` didn't forward `SKILL_CONCIERGE_CATALOG_ROOTS` (the named
  ADR-0026 gap class) → added to the forwarding tuple.
- **B6:** phantom "ledger selftest" claim → added a real `ledger.py --selftest`
  (classifies get_skill/auto/search/manual), plan claim corrected.
- **B8:** `catalogs.py promote` accepted path-traversal names → bare-name validation +
  two selftest cases.
- **B9 (latent):** `_point_changed` payload-only-migration trap documented in ADR
  consequences (safe this rollout — catalog points are all new-scope).
- **B7:** the uncommitted ship gate — resolved by the commit+push below (the validator ran
  pre-commit by design; that IS the gate).

The validator itself is the required independent check; its concerns were verification/
record-layer, not correctness — every one addressed, nothing waived.
