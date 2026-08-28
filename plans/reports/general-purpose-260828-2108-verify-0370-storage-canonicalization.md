# Verification report — 0.37.0 storage-canonicalization release (skill-concierge)

- Date: 2026-08-28 ~21:2x +07
- Scope: end-to-end validation of release fdaf90c after `/plugin marketplace update` + `/reload-plugins`
- Verdict: **PASS** — all 8 checklist items verified green, no regressions found.

## Checklist results

1. **Release integrity — PASS.** `git rev-parse origin/main` = `fdaf90cfdcebb9369d7d0bfc496b529365347bac`; `git branch -r --contains fdaf90c` → `origin/main` + `origin/HEAD`. All four manifests at `0.37.0`: `.claude-plugin/plugin.json:3`, `.claude-plugin/marketplace.json:8,23`, `.codex-plugin/plugin.json:3`, `package.json:4`. `CHANGELOG.md` has `## [0.37.0] — 2026-08-28` with the canonicalization entry. `docs/adr/0044-utterance-corpus-canonical-home.md` exists (3.5k, 28 Aug 21:03). `python3 scripts/driftcheck.py driftcheck.json` → "IN SYNC", exit 0.
2. **Canonical corpus — PASS.** `~/.claude/skill-concierge/triggers.json` (3.7M): 3,406 total keys; 1,928 `antigravity:*` keys; **all 1,928 carry non-empty `llm_triggers`** (0 empty/missing; each is `{source, triggers[n], n}` with real utterance text incl. Vietnamese). Backups: `~/.claude/skill-concierge/backups/triggers-20260828-2030/` holds exactly two files — `triggers.dev-repo.json` (3.7M) and `triggers.durable-home.json` (1.4M).
3. **Dev copy retired — PASS.** `eval/triggers.json` does not exist (ls: No such file or directory). fdaf90c's `.gitignore` diff removed the `-eval/triggers.json` line (replaced with a comment noting the move); the retained `eval/triggers.json.bak-*` (line 34) is a different pattern for backup-file globs, not the dev corpus. `~/.claude/settings.json`: no `SKILL_TRIGGERS` key; `jq empty` → valid JSON.
4. **Generator defaults — PASS.** All four resolve `SKILL_TRIGGERS` env first, then the durable home: `scripts/build_triggers.py:37` (`OUT`), `scripts/enrich_index.py:45` (`TRIGGERS`), `scripts/llm_triggers.py:39` (`TRIGGERS_FILE`), `scripts/flywheel.py:46` (`TRIGGERS_FILE`), each `os.environ.get("SKILL_TRIGGERS", str(Path.home()/".claude/skill-concierge/triggers.json"))`. `flywheel.py` `_engine_env()` also forwards the key (line 68).
5. **Vendored engine — PASS.** `vendor/skill-search/skill_search/server.py:98-100`: `_LLM_TRIG_PATH` default = `str(Path.home() / ".claude" / "skill-concierge" / "triggers.json")`, env wins. `vendor/skill-search/VENDORED.md:282` carries the v0.37.0 entry. The deployed venv copy (`~/.claude/skill-concierge/venv/lib/python3.12/site-packages/skill_search/server.py`) is **byte-identical** (`diff` → IDENTICAL); grepped, not imported.
6. **No-env end-to-end — PASS.** With `env -u SKILL_TRIGGERS`: `flywheel.py` status → `installed: 728/728; 0 missing`, `antigravity: 1928/1928; 0 missing`, exit 0 (endpoint reachable: YES). Since the dev eval copy no longer exists, the durable home is provably the only source of those 1,928. Selftests: `llm_triggers --selftest` PASS (exit 0), `llm_eval_gen --selftest` PASS (exit 0), `flywheel_llm --selftest` PASS (exit 0), `doctor.py --selftest` → "selftest ok" (exit 0), `driftcheck.py driftcheck.json` exit 0. Bonus: `pytest tests/ -q` → 13 passed (test_auto_flywheel, test_chain_hint_e2e, test_flywheel_llm_truncation).
7. **Installed copy parity — PASS.** `~/.claude/plugins/installed_plugins.json:224` installPath → `.../skill-concierge/skill-concierge/0.37.0` (cache refreshed; 0.36.1 dir also present but not active). Installed `plugin.json` = 0.37.0. Byte-identical to dev repo: `flywheel.py`, `flywheel_llm.py`, `llm_triggers.py`, `build_triggers.py`, `enrich_index.py`, `doctor.py`, `driftcheck.py` — all IDENTICAL via diff.
8. **Retrieval outcome — PASS.** Qdrant HTTP count (`POST /collections/claude_skills/points/count`, filter `scope = catalog:antigravity`, exact) → **30,818** (target ~30,818; collection total 41,207).

## Cross-harness (other sessions)

- Repo `.mcp.json:13`, installed plugin `.mcp.json:13`, and all three adapter manifests in BOTH dev and installed copies (`adapters/omp/mcp.json:14`, `adapters/zcode/mcp.json:14`, `adapters/commandcode/mcp.json:14`, `adapters/commandcode/install.sh:145,184`) all pin `/Users/thinhkhuat/.claude/skill-concierge/triggers.json`. OMP/ZCode expand the plugin `.mcp.json` natively (no `~/.omp/agent/mcp.json` written) — that file is correct at 0.37.0. Grok's marketplace cache copy (`.grok/marketplace-cache/64c8526d37363856/.mcp.json`) also pins the durable home.
- Live `~/.codex/config.toml` has no skill-search env block and does not reference `config2.toml` — no live surface points at the retired path.

## Minor observations (non-defects)

- `vendor/.../server.py` comments at lines 91 and 504 still name `eval/triggers.json` — historical prose only; the 0.37.0 comment at lines 96-97 documents the move. Cosmetic.
- `scripts/llm_triggers.py:359` assert message still says "the real eval/triggers.json" — stale message text; the actual path compared is `TRIGGERS_FILE` (durable home). Cosmetic.
- `~/.codex/config2.toml:852` still carries `SKILL_TRIGGERS = .../eval/triggers.json` — a stale backup file (PAI_* era), not referenced by live `config.toml`; harmless.
- Working tree clean apart from untracked `.zcode/`.

Unresolved: none.
