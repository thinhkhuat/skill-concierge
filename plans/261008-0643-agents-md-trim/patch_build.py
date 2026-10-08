from pathlib import Path
s = Path("build_draft.py"); u = s.read_text()
R = [
 # CLAUDE pointer (F5)
 ('"- **Governance flags (one-var reverts):** every runtime flag, its default, its code and its ADR are in "\n           "[`AGENTS.md`](AGENTS.md) → *Runtime flags* (one-line table plus the `ENGINE_ENV_KEYS` invariant); each flag\'s "\n           "full text is in [`docs/runtime-flags.md`](docs/runtime-flags.md).',
  '"- **Governance flags (one-var reverts):** every flag, with its default, code and ADR, is indexed in "\n           "[`AGENTS.md`](AGENTS.md) → *Runtime flags* (one-line table plus the `ENGINE_ENV_KEYS` invariant); each flag\'s "\n           "full text, tuning knobs and preconditions are in [`docs/runtime-flags.md`](docs/runtime-flags.md).'),
 # CLAUDE.md last line + docs corrections, applied AFTER the verbatim check
 ('new_claude = claude.replace(bullet, pointer)\n',
  'new_claude = claude.replace(bullet, pointer)\n'
  'OLD_TAIL = "Repo layout, full conventions, and guardrails are all in [`AGENTS.md`](AGENTS.md)."\n'
  'assert new_claude.count(OLD_TAIL) == 1\n'
  'new_claude = new_claude.replace(OLD_TAIL, "Repo layout, full conventions, and guardrails are all in [`AGENTS.md`](AGENTS.md); "\n'
  '                                "per-file layout detail is in [`docs/repository-layout.md`](docs/repository-layout.md).")\n'),
 ('fail = 0\n',
  'fail = 0\n'
  'flags_doc_moved = flags_doc  # the verbatim check below runs on this\n'
  '# Corrections to the moved text, each found by the 2026-10-08 validator and checked in code:\n'
  'CORRECTIONS = [\n'
  '    ("which all five reindex paths (`auto_reindex.py`, `auto_flywheel.py`, `flywheel.py`, `doctor.py`, `setup.sh`) now call through",\n'
  '     "which all six reindex paths (`auto_reindex.py`, `auto_flywheel.py`, `flywheel.py`, `doctor.py`, `setup.sh`, `trigger_filter.py reindex`) now call through"),\n'
  ']\n'
  'for a, b in CORRECTIONS:\n'
  '    assert flags_doc.count(a) == 1, a[:50]\n'
  '    flags_doc = flags_doc.replace(a, b)\n'
  'flags_doc += ("\\n- `SKILL_COMMANDCODE_ROOTS` (`vendor/skill-search/skill_search/skills_discovery.py`) — default ON (added 2026-10-08; "\n'
  '              "the flag predates this file but had no entry): index Command Code\'s skill roots, `~/.commandcode/skills` and "\n'
  '              "`<cwd>/.commandcode/skills`, alongside the other harnesses\' roots. In `ENGINE_ENV_KEYS`. `=0` + a reindex "\n'
  '              "reverts. [ADR-0038](adr/0038-command-code-triple-harness-parity.md).\\n")\n'
  'files["docs/runtime-flags.md"] = flags_doc\n'
  '(OUT / "docs/runtime-flags.md").write_text(flags_doc, encoding="utf-8")\n'),
 ('for name, old, doc in (("flags", flags_old, flags_doc),', 'for name, old, doc in (("flags", flags_old, flags_doc_moved),'),
]
for a, b in R:
    assert u.count(a) == 1, a[:60]
    u = u.replace(a, b)
s.write_text(u); print("ok")
