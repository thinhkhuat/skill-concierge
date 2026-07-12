# AGENTS-ONBOARDING — 5-minute orientation for skill-concierge

> **Read this first, then skim [`AGENTS.md`](AGENTS.md).** This is the 5-minute orientation;
> `AGENTS.md` is the canonical contract. If anything here disagrees with `AGENTS.md`,
> `AGENTS.md` wins.

## What this repo is (one sentence)

A Claude Code **plugin** that governs *which* specialized skill Claude reaches for, *whether* it
uses one at all, and *what* it actually used — three organs (Retrieve / Enforce / Ledger) layered
over the vendored `sowhan/skill-search` engine.

## The 30-second mental model

```
User prompt
    │
    ├── SessionStart: doctrine.py injects SKILL-FIRST standing order
    │                 + auto_reindex / auto_overrides / auto_flywheel self-heal (detached)
    │
    ├── UserPromptSubmit: enforcer.py runs the per-turn gate
    │     embed (warm shim, 200ms cap) → retrieve (Qdrant) → floors+imperative veto
    │     → inject ranked SKILL-FIRST mandate | SKILL-CHECK: authorization | silent
    │     → ledger.py logs the turn
    │
    └── PostToolUse: ledger.py logs the Skill / search_skills invocations
```

**No Stop hook, no PostToolUse enforcement gate.** Governance is *in-generation* — the doctrine
sits in context while the model writes. This is the single most important architectural commitment;
don't add a post-hoc detection layer "to catch skips" — it would reverse the in-generation governance design.

## The 6 files to read (in order)

0. [`openwiki/quickstart.md`](openwiki/quickstart.md) — end-to-end architecture overview (read this first)
1. [`hooks/doctrine/skill-first.md`](hooks/doctrine/skill-first.md) — the standing order
   (112 lines; the 6 rules + the Red Flags table are the contract)
2. [`hooks/scripts/enforcer.py`](hooks/scripts/enforcer.py) — the per-turn gate (846 lines; the
   real source of truth for the rules; has a `--selftest`)
3. [`openwiki/architecture/three-organs.md`](openwiki/architecture/three-organs.md) — the
   conceptual spine + how a request flows
4. [`docs/caveats.md`](docs/caveats.md) — the 15 operational landmines (read before judging
   anything; this exists because people have been wrong before)
5. [`AGENTS.md`](AGENTS.md) — full contract + guardrails

Skip-read (skim, don't memorize): `vendor/skill-search/skill_search/server.py`,
`scripts/doctor.py`, `docs/adr/README.md` (28 ADRs — read the one for whatever area you're touching).
## The 5 hard rules (breaking these invalidates your work)

1. **Hooks are fail-silent + additive-only.** Any error → `exit 0`, turn proceeds unchanged.
   Never `exit 2` / `decision: block`. A hook that "does nothing" may be silently swallowing an
   exception — never assume silence means success.

2. **Ledger metrics are EPOCH-SCOPED — never pool them.** This repo changes what the ledger
   measures almost daily (gate floors, retrieval engine, doctrine, embed shim). A rate pooled
   across config changes describes no real configuration. Find the current epoch start
   (`git log -1 --date=format:'%Y-%m-%d %H:%M:%S' --format=%cd -- hooks/scripts/enforcer.py hooks/doctrine/skill-first.md vendor/skill-search/skill_search/server.py scripts/embed_server.py`),
   then `python3 scripts/analyze.py --since "<that datetime>"`. Drop subagent / self-session
   traffic. If the window is thin, say **"insufficient data"** — do not pool backward.
   *This exact mistake once invalidated a full multi-agent analysis.*
3. **The ledger measures gate compliance, NOT skill usage.** For "is the right skill being
   used", use the **`skill-concierge:skill-usage-audit`** skill against the transcript
   SKILL-FIRST trail — not `analyze.py`. Inline `USING:` use (read SKILL.md, no `Skill` tool
   call) fires no PostToolUse, so the ledger AND tool-call trackers both miss it.

4. **Index holds model-invocable `SKILL.md` skills only.** Built-in / user-only slash-commands
   are excluded by design (ADR-0001). Their absence is correct, not a bug. The vendored `eval/`
   recall@k is calibrated to a different skill universe — near-zero is a wrong-universe
   artifact, not a weak retriever.

5. **The plugin lives in the versioned cache; your edits don't go live by themselves.** Bump
   `.claude-plugin/plugin.json` **and** `.claude-plugin/marketplace.json` together, push,
   then `/plugin marketplace update` + restart. The MCP launcher (`bin/skill-search-mcp`)
   auto-resyncs the venv engine on a version mismatch (ADR-0018), so a plain `setup.sh` rerun
   is only needed for a dependency change. Read [`docs/caveats.md` §11](docs/caveats.md)
   before debugging "the MCP serves old code".

## Common tasks → where to look

| If you need to… | Go to |
|---|---|
| Add or change a runtime behavior | `hooks/scripts/enforcer.py` (the gate) — has `--selftest` |
| Edit the standing order | `hooks/doctrine/skill-first.md` (runtime-read; no code change) |
| Tune retrieval | `vendor/skill-search/skill_search/server.py` (MAX-pool trigger layer) — see `VENDORED.md` if you change engine code |
| Add a new plugin skill | `skills/<name>/SKILL.md` with `name: skill-concierge:<name>` + `user-invocable: true` (+ `argument-hint` for skills that take arguments — ClaudeKit pattern, see caveats §15). Minimal skeleton: `skills/setup/SKILL.md` (argument-less, so no `argument-hint`); see `skills/keep-on/SKILL.md` for the `argument-hint` form. |
| Add a new hook event | `hooks/hooks.json` + `hooks/scripts/<name>.py` (mirror the fail-silent contract) |
| Bump the version | BOTH `plugin.json` + `marketplace.json` together + `CHANGELOG.md` entry |
| Check the deployment is healthy | `python3 scripts/doctor.py` (green `status: OK` is the bar) |
| Curate the always-on allowlist | `skill-concierge:keep-on` skill OR `python3 scripts/keep-on.py list\|add\|remove` |
| Measure the gate | `python3 scripts/analyze.py --since "<epoch-start>"` (NOT all-time) |
| Measure real usage | `skill-concierge:skill-usage-audit` skill (NOT `analyze.py`) |
| Regenerate utterance triggers | `skill-concierge:flywheel --generate` (offline, incremental) |
| Add an ADR | `docs/adr/<NNNN>-<kebab-case>.md` — accepted ADRs are immutable, supersede not edit |
| Verify version+doc sync | `python3 scripts/driftcheck.py driftcheck.json` (exit 0 = synced) |

## The 4 most-biting landmines (the rest are in `docs/caveats.md`)

- **Stale MCP after `/plugin update`** — the engine is *copied* into the venv, not editable.
  The launcher (`bin/skill-search-mcp`) auto-resyncs the venv engine on version mismatch (ADR-0018).
  `setup.sh` uses `--force-reinstall --no-deps` for the same reason. If `doctor` warns
  `Engine freshness`, rerun `setup.sh` + restart.
- **`.mcp.json` env must reach the DETACHED reindex**, not just the live query server, or
  `auto_reindex` rebuilds at engine defaults and silently prunes the utterance points (v0.16.1
  fix in `auto_reindex._mcp_env()` — caveats §14).
- **Concurrent sessions sharing one Qdrant collection** — must carry `scope` on every point
  and only prune what's in `visible_scopes()` (ADR-0028). If you touch `build_index()` or
  `search_skills`, this is load-bearing.
- **Plugin skills are namespaced in the index** — `ck:worktree`, not `worktree`; look up /
  label with the prefix (caveats §5).

## Verify before "done"

```bash
./setup.sh                                       # first-run bootstrap (idempotent)
python3 scripts/doctor.py                        # deployment health; "status: OK" is the bar
python3 scripts/doctor.py --fix                  # safe auto-fixes (Qdrant, reindex, reapply overrides, reapply enrichment, rebuild prompt_intent)
python3 scripts/driftcheck.py driftcheck.json    # version + doc-parity
python3 hooks/scripts/enforcer.py --selftest     # enforcer contract pinned (repo-local; use $CLAUDE_PLUGIN_ROOT only in deployed cache)
python3 -m pytest tests/                         # run test suite (vendor/skill-search/tests/ also available)
## When in doubt

- **"What's the right model for this turn?"** — the SKILL-FIRST doctrine in context is.
  Operate under it; don't reinvent.
- **"Should I add a Stop/PostToolUse gate?"** — no. See `openwiki/architecture/three-organs.md:34-37`:
  governance is in-generation; a post-hoc detection layer would reverse the design.
- **"Should I cite this ledger rate?"** — only if it's epoch-scoped + windowed + sample-adequate.
  Say **"insufficient data"** for a fresh/small epoch; say **"UNMEASURED"** if pooled across epochs.
- **"Should I run the upstream `generate_overrides.py`?"** — NO. It nukes the curated
  allowlist. Always use `scripts/apply-overrides.py` (caveats §2, ADR-0005).
- **"Should I edit the vendored engine?"** — yes, but log the patch in
  `vendor/skill-search/VENDORED.md`; re-apply it if upstream is ever re-vendored.

---

*Skim the rest of `AGENTS.md` for the full guardrails, the OpenWiki quickstart for the
end-to-end architecture, and the relevant ADR(s) for whatever area you're changing. ADRs are
immutable; supersede with a new one rather than editing an accepted record.*
> **Skill skeleton reference:** `skills/setup/SKILL.md` is the canonical minimal pattern.
> Required frontmatter keys: `name: skill-concierge:<name>`, `user-invocable: true` — plus
> `argument-hint` for skills that take arguments (`setup` is argument-less, so it omits it; see
> `skills/keep-on/SKILL.md` for the `argument-hint` form).
