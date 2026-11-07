"""The MCP launcher's engine-env loader (bin/skill-search-mcp).

The loader is an inline Python program inside a single-quoted shell string, so it cannot
be imported. These tests extract it from the file and run it as its own process, which is
exactly how the launcher runs it — a unit-test seam for behaviour that previously had NO
test at all. An independent audit found three defects in it because only the happy path
was ever exercised.

Defects these tests pin (all shipped in v0.76.3/0.76.4):
  1. A Unicode key ("ÉCOLE") passed Python str.isidentifier(), bash rejected the emitted
     `export`, and set -euo pipefail aborted startup — the opposite of the documented
     fail-open contract.
  2. The key filter allowed ANY shell-safe name, so a non-engine key (FOO=bar) reached the
     engine from the launcher while scripts/engine_env.py dropped it: two consumers of one
     file disagreed.
  3. A value shipped in .mcp.json arrives in os.environ, so the launcher treated a
     descriptor default as an explicit export and let it beat the machine-local file —
     the exact split-brain the design claims to close, in the opposite direction from
     engine_env.py.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

LAUNCHER = Path(__file__).resolve().parents[3] / "bin" / "skill-search-mcp"
ENGINE_ENV_PY = Path(__file__).resolve().parents[3] / "scripts" / "engine_env.py"


def _loader_source() -> str:
    """The inline Python program, lifted verbatim out of the launcher.

    Delimited by the `-I -c '` opening and the `' 2>/dev/null` closing, not by the first
    import: the program legitimately begins with comments, and anchoring on `import json`
    silently matched nothing the moment one was added above it.
    """
    src = LAUNCHER.read_text(encoding="utf-8")
    m = re.search(r"-I -c '(.*?)\n' 2>/dev/null", src, re.S)
    assert m, "could not locate the inline loader in bin/skill-search-mcp"
    return m.group(1)


def _run_loader(tmp_path, config, *, mcp_env=None, process_env=None):
    """Run the loader exactly as the launcher does, return the `export` lines it emits."""
    cfg = tmp_path / "engine-env.json"
    cfg.write_text(json.dumps(config))
    mcp = tmp_path / ".mcp.json"
    mcp.write_text(json.dumps({"mcpServers": {"skill-search": {"env": mcp_env or {}}}}))
    env = {
        "PATH": "/usr/bin:/bin",
        "ENGINE_ENV_PATH": str(cfg),
        "ENGINE_ENV_KEYS_SRC": str(ENGINE_ENV_PY),
        "ENGINE_MCP_JSON": str(mcp),
    }
    env.update(process_env or {})
    # -I keeps this isolated exactly as the launcher does.
    out = subprocess.run([sys.executable, "-I", "-c", _loader_source()],
                         capture_output=True, text=True, env=env, timeout=30)
    return out.stdout.strip().splitlines(), out.returncode


def test_loader_emits_real_engine_keys(tmp_path):
    lines, rc = _run_loader(tmp_path, {
        "SKILL_OLLAMA_URL": "https://gpu.example",
        "SKILL_EMBED_MODEL": "m",
    })
    assert rc == 0
    assert any("SKILL_OLLAMA_URL=https://gpu.example" in l for l in lines)
    assert any("SKILL_EMBED_MODEL=m" in l for l in lines)


def test_non_ascii_key_is_dropped_not_emitted(tmp_path):
    """Defect 1: bash rejects a Unicode identifier; emitting one aborted the launcher."""
    lines, rc = _run_loader(tmp_path, {"ÉCOLE": "x", "SKILL_OLLAMA_URL": "https://ok.example"})
    assert rc == 0
    assert lines == ["export SKILL_OLLAMA_URL=https://ok.example"]


def test_non_engine_key_is_dropped(tmp_path):
    """Defect 2: FOO is a valid shell name but not an engine key."""
    lines, rc = _run_loader(tmp_path, {"FOO": "bar", "SKILL_OLLAMA_URL": "https://ok.example"})
    assert rc == 0
    assert lines == ["export SKILL_OLLAMA_URL=https://ok.example"]


def test_machine_file_beats_a_descriptor_default(tmp_path):
    """Defect 3: a .mcp.json value is in os.environ; it must NOT count as an explicit export."""
    lines, rc = _run_loader(
        tmp_path,
        {"SKILL_EMBED_MODEL": "machine-model"},
        mcp_env={"SKILL_EMBED_MODEL": "descriptor-model"},
        process_env={"SKILL_EMBED_MODEL": "descriptor-model"},   # as the descriptor injects it
    )
    assert rc == 0
    assert lines == ["export SKILL_EMBED_MODEL=machine-model"]


def test_a_real_export_still_beats_the_machine_file(tmp_path):
    """The precedence rule's other half: an operator decision outranks the file."""
    lines, rc = _run_loader(
        tmp_path,
        {"SKILL_EMBED_MODEL": "machine-model"},
        mcp_env={"SKILL_EMBED_MODEL": "descriptor-model"},
        process_env={"SKILL_EMBED_MODEL": "operator-choice"},    # differs from the descriptor
    )
    assert rc == 0
    assert lines == []


@pytest.mark.parametrize("body", ["not json", "[]", '{"A": 1}', ""])
def test_malformed_or_odd_config_cannot_fail_the_loader(tmp_path, body):
    """The fail-open contract: nothing here may raise or emit junk."""
    cfg = tmp_path / "engine-env.json"
    cfg.write_text(body)
    mcp = tmp_path / ".mcp.json"
    mcp.write_text("{}")
    out = subprocess.run(
        [sys.executable, "-I", "-c", _loader_source()],
        capture_output=True, text=True, timeout=30,
        env={"PATH": "/usr/bin:/bin", "ENGINE_ENV_PATH": str(cfg),
             "ENGINE_ENV_KEYS_SRC": str(ENGINE_ENV_PY), "ENGINE_MCP_JSON": str(mcp)})
    assert out.returncode == 0
    assert out.stdout.strip() == ""
