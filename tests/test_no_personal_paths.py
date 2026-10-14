"""No shipped code names one machine's checkout or home directory.

The Command Code mod fell back to the maintainer's checkout path, so on every other machine it
resolved its root to $HOME and did nothing, silently (GitHub issue #1). The DSH, OMP and OpenCode
adapters carried the same fallback, and the Command Code installer keyed a project dir on it. Code
must find its checkout from its own location, an installed root, or SKILL_CONCIERGE_ROOT.

The shipped MCP descriptors carried the same home directory in SKILL_TRIGGERS and
SKILL_SERVER_RECORDS; they pin "${HOME}/..." now, which the engine expands itself.

Scope is code and JSON under adapters/, hooks/, bin/, scripts/, skills/ and .codex-plugin/, plus the
root .mcp.json. Docs are out of scope.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIRS = ("adapters", "hooks", "bin", "scripts", "skills", ".codex-plugin")
CODE = {".ts", ".tsx", ".mts", ".mjs", ".js", ".py", ".sh", ".json"}
SKIP = {"node_modules", "__pycache__", ".venv"}
PERSONAL = re.compile(r"in-PROD/MY-WORKBENCH|in-prod-my-workbench|/Users/thinhkhuat\b", re.IGNORECASE)


def offenders(base):
    hits = []
    for path in [base / ".mcp.json", *(p for d in DIRS for p in sorted((base / d).rglob("*")))]:
        if not path.is_file() or SKIP & set(path.parts):
            continue
        if path.suffix not in CODE and path.parent.name != "bin":
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if PERSONAL.search(line):
                hits.append(f"{path.relative_to(base)}:{n}: {line.strip()}")
    return hits


def test_the_check_catches_a_personal_checkout_path(tmp_path):
    (tmp_path / "adapters" / "x").mkdir(parents=True)
    (tmp_path / "adapters" / "x" / "mod.ts").write_text(
        'const p = join(homedir(), "in-PROD/MY-WORKBENCH/skill-concierge");\n')
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "launcher").write_text("exec /Users/thinhkhuat/sc/bin/x\n")
    (tmp_path / ".mcp.json").write_text('{"env": {"SKILL_TRIGGERS": "/Users/thinhkhuat/.claude/t.json"}}\n')
    assert len(offenders(tmp_path)) == 3


def test_shipped_code_names_no_personal_checkout_path():
    assert offenders(ROOT) == []
