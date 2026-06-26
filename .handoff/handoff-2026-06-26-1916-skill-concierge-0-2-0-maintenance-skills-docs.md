# Session Handoff — skill-concierge: 0.2.0 maintenance skills (setup + doctor) + full docs refresh

> Save-location note: the session-handoff skill's canonical target is
> `<project-root>/.handoff/`, but the workbench root-anchoring HARD RULE (artifacts are
> inert data — no writes) blocked writing inside `skill-concierge/` because its `.git` is
> currently present. Routed here to the workbench-root `plans/` per the guard's reroute
> instruction. To keep it inside the repo instead, apply the `.git`→`git` no-dot bypass
> (caveats §10) and re-run /session-handoff.

## Where it started
User asked, in sequence: (1) rewrite README.md to public-release quality while retaining
original content/intent; (2) add housekeeping skills `skill-concierge:setup` +
`skill-concierge:doctor` to bootstrap the plugin and run healthcheck + auto-fix; (3) confirm
docs were "fully refreshed". Project context (cross-session, from `docs/plan.md`): skill-concierge
is a skill-governance layer = semantic Retrieve (skill-search MCP) × Enforce (UPS hook) × a
compounding invocation Ledger. The P1 fusion (warm embed shim + enforcer rewrite) was built in
prior/parallel work and is COMPLETE-but-HELD; this session added the 0.2.0 maintenance layer on
top and brought all docs current.

## Decisions locked + what shipped

This session (0.2.0 — maintenance + docs):
- **README.md rewritten** to public-release quality (badges, TOC, prerequisites, MCP-tool usage,
  config reference, request-flow, troubleshooting, contributing, license) — retains all original
  sections. `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/README.md`
- **`scripts/doctor.py`** — pure-stdlib deployment healthcheck; delegates retrieval health to the
  engine's `skill-search --health` (DRY); `--fix` does only safe/fast repairs (docker start +
  readiness poll → reindex → re-apply overrides); has `--selftest`; exits non-zero on FAIL.
- **`skills/setup/SKILL.md`** (`skill-concierge:setup`) wraps idempotent `setup.sh`; **`skills/doctor/SKILL.md`**
  (`skill-concierge:doctor`) drives doctor.py. Both declare `name:`=dir (proven registration
  pattern, 158/159 cache skills) with single-line descriptions (engine parses frontmatter by
  regex, not YAML — a `>-` block scalar leaks into the index).
- **Version bump 0.1.2 → 0.2.0** in BOTH `.claude-plugin/plugin.json` and
  `.claude-plugin/marketplace.json` (enforced both-bump policy); CHANGELOG `[0.2.0]` entry + links.
- **Docs refresh:** `docs/adr/0007-maintenance-skills-setup-doctor.md` (delegate-to-engine +
  safe-fix-boundary rationale) + index row; `docs/plan.md` build-log 0.2.0 entry; `docs/caveats.md`
  top doctor pointer; README version refs → 0.2.0.

Pre-existing project state (built outside this session; grounded from files + plan.md — do NOT
re-attribute to this session):
- **P1 fusion COMPLETE, HELD owner-gated go-live** (per plan.md Status): warm embed shim
  (`scripts/embed_server.py`, Docker sidecar `skill-search-embed-shim` @ `127.0.0.1:6363`) +
  rewritten enforcer (`hooks/scripts/enforcer.py`) — verified 90ms timeout, cosine parity
  1.000000, fallback tested. ADR-0008 records the shim + timeout calibration; caveats §9 covers it.
- Ledger slice (`hooks/scripts/ledger.py` + `scripts/analyze.py`) + reproduction layer
  (`.mcp.json`, `setup.sh`, `scripts/apply-overrides.py`, `config/keep-on.json`) — built earlier.
- ADRs 0001–0006 (model-invocable-only index, WHICH×WHETHER fusion, mpnet-768+Qdrant, stable-venv
  launcher, overrides applier, compounding ledger).

## Key files for next session

| File | Why |
|------|-----|
| Plan: `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/docs/plan.md` | READ FIRST — cross-session record; P1 status, phases, go-live gate |
| `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/docs/adr/README.md` | decision index 0001–0008 (the WHY) |
| `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/docs/caveats.md` | operational landmines §1–§10 (doctor automates the common ones) |
| `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/scripts/doctor.py` | this session's diagnostic engine |
| `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/skills/doctor/SKILL.md` | `skill-concierge:doctor` skill |
| `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/skills/setup/SKILL.md` | `skill-concierge:setup` skill |
| `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/scripts/embed_server.py` | P1 warm embed shim (sidecar) |
| `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/hooks/scripts/enforcer.py` | P1 enforcer hook (rewritten; HELD) |
| `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/hooks/scripts/ledger.py` | telemetry capture (UPS + PostToolUse) |
| `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/setup.sh` | idempotent bootstrap (venv + Qdrant + index + overrides) |
| `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/.mcp.json` | MCP wiring + embedder/Qdrant single-source-of-truth env |
| `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/CHANGELOG.md` | release history; [0.2.0] is current |

- Memory touched: none (no project-memory files or agentmemory lessons written this session).

## Running state
- Background processes: none started this session.
- Dev servers / ports: project Docker sidecars (persistent, `--restart unless-stopped`, NOT
  started by this session) — Qdrant `skill-search-qdrant` @ `localhost:6333`; embed shim
  `skill-search-embed-shim` @ `127.0.0.1:6363`. Check: `docker ps --filter name=skill-search`.
- Open worktrees / branches: branch `main` (workbench repo uses the `.git`↔`git` no-dot bypass;
  see caveats §10 — `.git` is currently present, which is why the in-repo handoff write was blocked).
  No worktrees.

## Verification — how to confirm things still work
- `python3 scripts/doctor.py` — prints the check matrix; currently expected `status: FAIL`
  (real findings: stale index "disk changed" + duplicate user-scope MCP). Run from plugin root.
- `python3 scripts/doctor.py --selftest` — expect `selftest ok`.
- `python3 -m py_compile scripts/doctor.py` — expect no output (compiles).
- Version coherence: `python3 -c "import json;print(json.load(open('.claude-plugin/plugin.json'))['version'], json.load(open('.claude-plugin/marketplace.json'))['metadata']['version'])"` — expect `0.2.0 0.2.0`.

## Deferred + open questions
- Deferred: **P1 fusion go-live is owner-gated/HELD** — deregister the old `skill-first-nudge`
  hook in `~/.claude/settings.json` (back up first) → bump marketplace → full plugin install.
  Live behavior begins only after install (plan.md Status).
- Deferred: **0.2.0 live slash registration of `skill-concierge:doctor`/`:setup` is UNVERIFIED**
  until the bumped plugin is reinstalled; chose the proven `name:`=dir pattern to de-risk.
- Deferred: caveats §4 — harden `setup.sh` python picker to test venv+pip per candidate
  (portability-only; owner machine already works).
- Open: handoff save-location — kept under workbench `plans/` because the repo `.handoff/` write
  was guard-blocked; user may prefer it in-repo via the `.git`→`git` bypass.

## Pick up here
Run the owner-gated go-live: reinstall the bumped 0.2.0 plugin (deregister old hook → marketplace
bump/update → install), then `python3 scripts/doctor.py --fix` to clear the stale index + verify
`skill-concierge:doctor`/`:setup` register and the enforcer/shim are live.
