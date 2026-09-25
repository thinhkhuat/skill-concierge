"""Every reindex path forwards the SAME engine settings from .mcp.json.

Behavioural: each env builder is run against a temp plugin root whose .mcp.json pins every
ENGINE_ENV_KEYS key to a sentinel; each must yield every sentinel, and a value already in the
process environment must win. A builder that keeps its own shorter key list fails here."""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ENGINE_ENV = _load("engine_env_under_test", ROOT / "scripts" / "engine_env.py")
KEYS = ENGINE_ENV.ENGINE_ENV_KEYS


@pytest.fixture()
def plugin_root(tmp_path, monkeypatch):
    (tmp_path / ".mcp.json").write_text(json.dumps({"mcpServers": {"skill-search": {
        "command": "x", "env": {k: f"v-{k}" for k in KEYS}}}}), encoding="utf-8")
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
    return tmp_path


def _builders(root, monkeypatch):
    """(label, zero-arg callable returning the env dict) for all five reindex paths."""
    ar = _load("auto_reindex_t", ROOT / "hooks" / "scripts" / "auto_reindex.py")
    af = _load("auto_flywheel_t", ROOT / "hooks" / "scripts" / "auto_flywheel.py")
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    fw = _load("flywheel_t", ROOT / "scripts" / "flywheel.py")
    dr = _load("doctor_t", ROOT / "scripts" / "doctor.py")
    monkeypatch.setattr(fw, "ROOT", root)
    monkeypatch.setattr(dr, "ROOT", root)

    def _setup_path():
        out = subprocess.run([sys.executable, str(ROOT / "scripts" / "engine_env.py"),
                              "--root", str(root), "--exec", "env"],
                             capture_output=True, text=True, check=True, env=dict(os.environ))
        return dict(ln.split("=", 1) for ln in out.stdout.splitlines() if "=" in ln)

    return [("engine_env", lambda: ENGINE_ENV.engine_env(root)),
            ("auto_reindex", lambda: ar._mcp_env()[0]),
            ("auto_flywheel", lambda: af._mcp_env()[0]),
            ("flywheel", fw._engine_env),
            ("doctor", dr._engine_env),
            ("setup.sh --exec path", _setup_path)]


# doctor pins the embedder/store trio to its own resolved values by design; everything else
# must come from .mcp.json exactly as for the other builders.
_DOCTOR_OWN = {"SKILL_QDRANT_URL", "SKILL_EMBED_BACKEND", "SKILL_EMBED_MODEL"}


def test_every_builder_forwards_every_engine_key(plugin_root, monkeypatch):
    for label, build in _builders(plugin_root, monkeypatch):
        env = build()
        keys = [k for k in KEYS if not (label == "doctor" and k in _DOCTOR_OWN)]
        missing = [k for k in keys if env.get(k) != f"v-{k}"]
        assert not missing, f"{label} does not forward {missing}"


def test_process_env_beats_mcp_json_in_every_builder(plugin_root, monkeypatch):
    monkeypatch.setenv("SKILL_SYNCED_ROOTS", "operator-value")
    for label, build in _builders(plugin_root, monkeypatch):
        assert build().get("SKILL_SYNCED_ROOTS") == "operator-value", label


def test_unreadable_mcp_json_fails_open(tmp_path, monkeypatch):
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)
    (tmp_path / ".mcp.json").write_text("{not json", encoding="utf-8")
    env = ENGINE_ENV.engine_env(tmp_path)
    assert not any(k in env for k in KEYS)


def test_empty_values_are_not_forwarded(tmp_path, monkeypatch):
    monkeypatch.delenv("SKILL_LLM_TRIGGERS", raising=False)
    (tmp_path / ".mcp.json").write_text(json.dumps({"mcpServers": {"skill-search": {
        "env": {"SKILL_LLM_TRIGGERS": ""}}}}), encoding="utf-8")
    assert "SKILL_LLM_TRIGGERS" not in ENGINE_ENV.engine_env(tmp_path)


def test_setup_sh_env_run_routes_through_engine_env():
    """[R] wiring guard (regression, not behaviour): setup.sh's reindex env comes from the
    shared helper, not from a hand-kept key list."""
    body = (ROOT / "setup.sh").read_text(encoding="utf-8")
    start = body.index("env_run() {")
    assert "scripts/engine_env.py" in body[start:body.index("}", start)]
