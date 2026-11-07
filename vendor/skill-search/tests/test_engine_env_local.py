"""The machine-local engine overrides (scripts/engine_env.py).

The defect these exist for: `engine_env.engine_env()` merged `os.environ` with the
`.mcp.json` env block only. Two engine keys -- the embedder URL and its bearer
token -- cannot live in `.mcp.json` (ADR-0097: the token is read from the
environment, never the descriptor), so inside a SessionStart hook they resolved to
their defaults: `SKILL_OLLAMA_URL` fell back to `http://localhost:11434` and the
token to empty. Every background reindex therefore rebuilt points against a
DIFFERENT embedder than the one serving queries, with no error. Measured
2026-11-07: 19,873 points stamped by the localhost embedder beside 26,687 stamped
by the GPU host.
"""

import json
import sys
from pathlib import Path

# `engine_env.py` is a plugin script, not part of this vendored package, so it is not on
# sys.path. Resolve it from this file's own location rather than pytest's rootdir.
_ROOT = Path(__file__).resolve().parents[3]        # vendor/skill-search/tests -> plugin root
sys.path.insert(0, str(_ROOT / "scripts"))
import engine_env  # noqa: E402


def test_local_overrides_are_merged(tmp_path, monkeypatch):
    f = tmp_path / "engine-env.json"
    f.write_text(json.dumps({
        "SKILL_OLLAMA_URL": "https://gpu.example",
        "SKILL_EMBED_TOKEN": "tok",
    }))
    monkeypatch.setattr(engine_env, "LOCAL_ENV_PATH", f)
    merged = engine_env.engine_env(tmp_path)          # no .mcp.json here
    assert merged["SKILL_OLLAMA_URL"] == "https://gpu.example"
    assert merged["SKILL_EMBED_TOKEN"] == "tok"


def test_process_environment_still_wins(tmp_path, monkeypatch):
    """A caller that decided deliberately outranks both files."""
    f = tmp_path / "engine-env.json"
    f.write_text(json.dumps({"SKILL_OLLAMA_URL": "https://from-file.example"}))
    monkeypatch.setattr(engine_env, "LOCAL_ENV_PATH", f)
    monkeypatch.setenv("SKILL_OLLAMA_URL", "https://from-process.example")
    assert engine_env.engine_env(tmp_path)["SKILL_OLLAMA_URL"] == "https://from-process.example"


def test_unknown_and_empty_keys_are_ignored(tmp_path, monkeypatch):
    f = tmp_path / "engine-env.json"
    f.write_text(json.dumps({
        "SKILL_OLLAMA_URL": "",              # empty would read as ON for a flag
        "PATH": "/evil",                     # not an engine key
    }))
    monkeypatch.setattr(engine_env, "LOCAL_ENV_PATH", f)
    merged = engine_env.engine_env(tmp_path)
    assert "SKILL_OLLAMA_URL" not in merged
    assert merged["PATH"] != "/evil"


def test_missing_or_malformed_file_degrades_to_defaults(tmp_path, monkeypatch):
    """Fail-open: a broken file must never raise into a hook."""
    for body in (None, "not json", "[1,2,3]"):
        f = tmp_path / "engine-env.json"
        if body is None:
            f.unlink(missing_ok=True)
        else:
            f.write_text(body)
        monkeypatch.setattr(engine_env, "LOCAL_ENV_PATH", f)
        assert engine_env.engine_env(tmp_path).get("SKILL_OLLAMA_URL") is None


def test_local_outranks_the_descriptor(tmp_path, monkeypatch):
    """`.mcp.json` ships defaults; the machine file carries deployment truth."""
    (tmp_path / ".mcp.json").write_text(json.dumps(
        {"mcpServers": {"skill-search": {"env": {"SKILL_EMBED_MODEL": "shipped-model"}}}}))
    f = tmp_path / "engine-env.json"
    f.write_text(json.dumps({"SKILL_EMBED_MODEL": "machine-model"}))
    monkeypatch.setattr(engine_env, "LOCAL_ENV_PATH", f)
    assert engine_env.engine_env(tmp_path)["SKILL_EMBED_MODEL"] == "machine-model"
