# researcher-1 — `scripts/generate_catalogs.py` provenance & mechanics

**VERDICT: (b) — orphan / cross-pollinated artifact. Does NOT run here, nothing consumes it, not even committed to git, and its branding + taxonomy belong to a DIFFERENT project ("ClaudeKit Engineer"), not skill-concierge.**

---

## 1. What it claims to do

`scripts/generate_catalogs.py:1-5` — reads two YAML data files and emits grouped `COMMANDS.yaml` / `SKILLS.yaml` catalogs to stdout (or `--output` file). Inputs are loaded from its own script dir:

- `generate_commands_yaml()` → `load_yaml('commands_data.yaml')` (`:40`)
- `generate_skills_yaml()` → `load_yaml('skills_data.yaml')` (`:85`)
- error hint names the producers: `"Run scan_skills.py or scan_commands.py first to generate data files"` (`:33`)
- optional import `from win_compat import ensure_utf8_stdout` (`:19`)

## 2. Declared inputs / producers — ALL MISSING

`ls scripts/` + targeted check:

```
MISSING: scripts/commands_data.yaml
MISSING: scripts/skills_data.yaml
MISSING: scripts/scan_skills.py
MISSING: scripts/scan_commands.py
MISSING: scripts/win_compat.py
EXISTS:  scripts/generate_catalogs.py
```

Every input file, every producer script, and the `win_compat` helper it imports do not exist. The script cannot self-bootstrap: the hint tells you to run `scan_skills.py`/`scan_commands.py`, which also don't exist.

## 3. Actually run — fails both ways

**System `python3`** (crashes before it even reaches its own logic):

```
File ".../scripts/generate_catalogs.py", line 10, in <module>
    import yaml
ModuleNotFoundError: No module named 'yaml'
RC=1                                  # both --skills and --commands
```

`pyyaml` is not available to the interpreter that would run a repo script. Giving it a yaml-capable interpreter only exposes the next wall — its designed failure on missing data:

```
--skills:   Error: .../scripts/skills_data.yaml not found
            Hint: Run scan_skills.py or scan_commands.py first to generate data files
--commands: Error: .../scripts/commands_data.yaml not found
            Hint: Run scan_skills.py or scan_commands.py first to generate data files
```

So: crash on `import yaml` with the system interpreter, or `sys.exit(1)` on missing data files with a yaml interpreter. There is no path where it produces output in this repo.

## 4. Consumers — NONE

Repo-wide (`rg`, `.git` excluded) for `generate_catalogs|COMMANDS\.yaml|SKILLS\.yaml|commands_data|skills_data|scan_skills|scan_commands|win_compat|ensure_utf8_stdout`:

**Every match is inside `generate_catalogs.py` itself** (`:19,:20,:33,:39,:40,:84,:85`). Nothing in `setup.sh`, `AGENTS.md`, `README.md`, `.claude-plugin/`, `hooks/`, or `docs/` imports, calls, documents, or reads this script or its `COMMANDS.yaml`/`SKILLS.yaml` outputs.

> Note on a false friend: the many `catalog`/`catalogue` hits in `docs/`, `README.md`, `.claude-plugin/marketplace.json`, `hooks/scripts/enforcer.py` are the ordinary English word "catalogue" referring to the **Qdrant semantic skill index** — the repo's actual retrieval mechanism — NOT this script's static YAML catalogs. Different system entirely.

## 5. Provenance — untracked loose file, not from this project

Git status:

```
git ls-files scripts/generate_catalogs.py   → (empty; not tracked)
git status --porcelain                       → ?? scripts/generate_catalogs.py   (UNTRACKED)
git log -- scripts/generate_catalogs.py      → (empty; no history)
git check-ignore -v scripts/...              → NOT ignored
```

The 14 scripts git DOES track (`analyze.py`, `apply-overrides.py`, `doctor.py`, `embed_server.py`, `enrich_index.py`, …) do **not** include `generate_catalogs.py` — nor any of its 5 dependencies. It is a loose, never-committed file dropped into the working tree.

**Cross-pollination proof (different project):**
- `:58`  `'description': '... all available commands in ClaudeKit Engineer'`
- `:103` `'description': '... all available skills in ClaudeKit Engineer'`

This repo is **skill-concierge**, not **ClaudeKit Engineer** (a separate product). The hardcoded category taxonomies are ClaudeKit Engineer's, not this repo's:
- command cats (`:63-75`): core / bootstrap / content / cook / design / docs / fix / git / integrate / plan / review / scout / skill
- skill cats (`:108-117`): ai-ml / frontend / backend / infrastructure / database / dev-tools / multimedia / frameworks / utilities / other

skill-concierge's model-invocable skills are retrieved by **semantic search over a Qdrant index** (README §Retrieve; `docs/adr/0001`, `0002`), not by a static hand-categorized YAML catalog. The static-catalog approach here is exactly the "separate, drifting catalogue" the repo's ADR-0002 says it *retired*.

## 6. Verdict

**(b) Orphan / cross-pollinated artifact.** It (1) does not run in this repo — crashes on `import yaml`, and even with yaml it `sys.exit(1)`s on the 5 missing dependencies; (2) has zero consumers anywhere in the repo; (3) is untracked with no git history and is not among the 14 tracked scripts; (4) is branded and structured for "ClaudeKit Engineer", a different project, whose static-YAML-catalog model contradicts skill-concierge's Qdrant semantic-index design. Textbook workbench cross-pollination (per root `CLAUDE.md`: "cross-pollinated code from many sources ... half-baked experiments").

## Unresolved / caveats
- Reached the deeper `load_yaml` error path using the skills-plugin venv (`~/.claude/skills/.venv/bin/python3`, the only yaml-capable interpreter found) purely to demonstrate the second failure wall — read-only, no install, nothing written. The repo ships no venv exposing `pyyaml` to this script.
- Not assessed here (out of scope for provenance/mechanics): whether the script has any *salvage* value or should be deleted — that is researcher-3's angle.
