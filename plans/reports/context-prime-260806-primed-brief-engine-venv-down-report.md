# Context Prime — 2026-08-06

**Session start orientation for skill-concierge.** Produced before any work began;
captures the live state discovered, the headline finding (broken engine venv), and
open threads from the latest handoff.

---

## What skill-concierge is

A skill-governance layer over Claude Code: semantic retrieval (*which* skill) +
per-turn enforcement (*whether* a skill is used) + an invocation ledger. Vendored
MCP engine (`skill-search`) on Qdrant + multilingual mpnet embeddings, with a
flywheel that generates natural-utterance trigger points offline.

**Version:** v0.20.5 (2026-07-31). `Unreleased` changelog section empty. `main`
clean, `ahead=0 behind=0`. Four reports in `plans/reports/` untracked (not committed).

---

## ⚠️ Headline finding — the engine is currently DOWN

`doctor.py` (the "verify before done" bar) crashes immediately. Root cause is a
**dead venv**:

```
~/.claude/skill-concierge/venv/bin/python3.12 → /opt/homebrew/opt/python@3.12/bin/python3.12   (dangling)
```

Homebrew's `python@3.12` is entirely gone (no `/opt/homebrew/opt`, no Cellar).
The venv was built against it, so every entrypoint script's shebang resolves to
nothing. `subprocess` reports `FileNotFoundError` against the *script* path, which
masks the real culprit (the interpreter in the shebang) — that's why `ls` shows
`skill-search` exists but doctor can't run it.

| Layer | State |
|---|---|
| Qdrant container `skill-search-qdrant` | **Up** (17h, `:6333-6334`) — state intact |
| Engine venv `~/.claude/skill-concierge/venv` | **Broken** — dangling python3.12 symlink |
| `skill-search` MCP server | **Not running** (no process) |
| Embed shim (`embed_server.py`) | **Not running** |
| Doctor | **Crashes** before any check runs |

**Consequence:** no live semantic retrieval; enforcement gate is running fail-open
or not at all. A working 3.12 exists via pyenv (`3.12.11`, what doctor itself runs
under), so the fix is `./setup.sh` to rebuild the venv against pyenv's interpreter.
**Not executed** — priming only, repair not authorized.

---

## Recent arc (from git + latest handoff)

Last real work was a **v0.20.3–v0.20.5** cluster fixing *what gets embedded*:

- **v0.20.3** — skill identity is now the **directory name** not frontmatter
  `name:` (so `skillOverrides` finally apply). Verified against a live catalogue
  (`zread-cli` ships `name: zread` but Claude Code lists it as `zread-cli`).
- **v0.20.4** — frontmatter values no longer swallow hyphenated keys
  (`_FM_NEXT_KEY` terminator). 168/356 personal skills were polluted with
  frontmatter junk in their embedded text (~1.7k est. tokens of noise).
- **v0.20.5** — `setup.sh` now forwards the trigger-layer env
  (`SKILL_LLM_TRIGGERS`, `TRIGGERS_MAX`, `SKILL_TRIGGERS`, `SKILL_BODY_TRIGGERS`)
  so a rebuild stops silently pruning utterance points and building a layer
  composition the query server does not serve.

Before that, **v0.19** fixed a multi-session split-brain: sessions were deleting
each other's skills via CWD-scoped pruning of a shared collection; the installed-
plugin filter dropped the index 548→427 with nothing invocable lost; utterance
prompt v2 was measured to beat v1 on the live embedder (0.7558 vs 0.5731, the
lever being vocabulary distance from the description, not sentence-likeness).

---

## Open threads (from handoff 2026-07-09)

1. **Flywheel cold-start timeout (unproven).** One run crashed:
   `llm_triggers crashed: timed out` at the `:4310` LM Studio model. Not
   reproduced — a bounded regeneration ran in 10s, exit 0. A trivial `:4310`
   call took 41s while the model was cold. If `doctor`'s flywheel line keeps
   recording this, it needs a bounded retry, not a guess.
2. **Utterance catalogue regenerating** under prompt v2 at 25/session (~17
   sessions to cover 427 skills). Full burn never started (GPU-sensitive).
   Coverage was 428/430; two gaps: project-scoped `claude-code` and `native-mcp`.
3. **`/reload-plugins` reported 2 load errors** never attributed. Re-check
   `/plugin` if anything misbehaves.

---

## Key landmines (each cost real time before)

- **Reindex trap:** `skill-search --reindex` from a bare shell has no
  `SKILL_QDRANT_URL` → silently reindexes an *embedded* store at
  `~/.cache/skill-search/qdrant`, on a wrong-dim embedder. Always forward the
  live env: `env $(ps eww <mcp_pid> | tr ' ' '\n' | grep '^SKILL_') ... --reindex`.
- **Deploy trap (ADR-0018):** venv is a *copy install*. After touching `vendor/`:
  `~/.claude/skill-concierge/venv/bin/pip install --force-reinstall --no-deps
  vendor/skill-search`, then reindex from a **fresh process** — long-lived MCP
  servers hold stale modules in memory.
- **Telemetry is epoch-scoped (HARD):** never cite a ledger rate pooled across
  config changes; this repo changes what the ledger measures ~daily. Window
  `analyze.py --since "<last config commit>"`, exclude subagent traffic, say
  "insufficient data" rather than pool backward. A prior multi-agent analysis
  got this fatally wrong once (pooled ~15 epochs v0.2→v0.12).

---

## Key files for next session

| File | Why |
|------|-----|
| `docs/plan.md` | Fusion build plan + dated build log (P1 COMPLETE + LIVE) |
| `.handoff/handoff-2026-07-09-2234-...-v0191.md` | Latest handoff — full decision arc for v0.19 |
| `vendor/skill-search/skill_search/server.py` | `_existing_points`, `_point_changed`, `_prunable`, `_scope_filter`, `META_PATH` |
| `vendor/skill-search/skill_search/skills_discovery.py` | `_scope_for`, `visible_scopes`, `_installed_plugin_roots`, `SKILL_DIRS` (deliberately one level deep) |
| `vendor/skill-search/VENDORED.md` | Every engine patch; re-apply on re-vendor |
| `scripts/llm_triggers.py` | `SYSTEM_PROMPT` v2 + `PROMPT_VERSION` + measurement table |
| `scripts/apply-overrides.py` | `discover_skill_names()` excludes `project:` scope |
| `hooks/scripts/auto_flywheel.py` | `_index_lags_disk`, `_meta_path`, `_ping_ok` |
| `tests/test_auto_flywheel.py` | First tests for the hook layer |

---

## Step zero for any engine-touching work

Rebuild the venv — it's dead. `./setup.sh` against the pyenv 3.12.11 interpreter.
Confirm with `python3 scripts/doctor.py` → `status: OK` before claiming anything
engine-related is "done."
