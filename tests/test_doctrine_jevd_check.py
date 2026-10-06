"""The SessionStart jevd check: a session whose environment lacks JEVD_URL while jevd answers on loopback
bypasses jevd for every Jev call, so doctrine.py warns the user (systemMessage) and the agent (context).
Run as a subprocess, as the harness runs it, against a fake jevd on a free port named in a temp config."""
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

DOCTRINE = Path(__file__).resolve().parents[1] / "hooks" / "scripts" / "doctrine.py"
PAYLOAD = '{"hook_event_name":"SessionStart","source":"startup","session_id":"s"}'


class _Health(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"status": "ok"}).encode()
        self.send_response(200 if self.path == "/health" else 404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


@pytest.fixture
def jevd(tmp_path):
    srv = HTTPServer(("127.0.0.1", 0), _Health)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    cfg = tmp_path / "config.toml"
    cfg.write_text(f'[server]\nhost = "127.0.0.1"\nport = {srv.server_port}\n')
    yield cfg, srv.server_port
    srv.shutdown()


_CLEARED = ("JEVD_URL", "JEVD_CONFIG", "JEVD_HOME", "SKILL_JEVD_ENV_CHECK", "ENFORCER_JEV_ROUTER",
            "ENFORCER_JEV_GATE", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy", "NO_PROXY", "no_proxy")


def _run(cfg, **env) -> dict:
    e = {k: v for k, v in os.environ.items() if k not in _CLEARED}
    if cfg is not None:
        e["JEVD_CONFIG"] = str(cfg)
    e.update(env)
    out = subprocess.run([sys.executable, str(DOCTRINE)], input=PAYLOAD, capture_output=True, text=True,
                         env=e, timeout=10)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


# Unset, plus every shape the enforcer discards (it keeps only an http URL on a loopback host).
@pytest.mark.parametrize("jevd_url", [None, "", " ", "127.0.0.1:4377", "localhost:4377",
                                      "https://127.0.0.1:4377", "http://192.168.1.5:4377"])
def test_warns_when_jevd_runs_and_jevd_url_is_unusable(jevd, jevd_url):
    cfg, port = jevd
    out = _run(cfg, **({} if jevd_url is None else {"JEVD_URL": jevd_url}))
    assert f"http://127.0.0.1:{port}" in out["systemMessage"]
    quiet = _run(cfg, SKILL_JEVD_ENV_CHECK="0")["hookSpecificOutput"]["additionalContext"]
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert ctx.startswith(quiet + "\n\nJEVD-ENV WARNING")  # the doctrine whole, the warning after it


def test_probe_ignores_an_environment_proxy(jevd):
    out = _run(jevd[0], HTTP_PROXY="http://127.0.0.1:1", http_proxy="http://127.0.0.1:1",
               ALL_PROXY="http://127.0.0.1:1")
    assert "systemMessage" in out


def test_config_found_through_jevd_home(jevd):
    out = _run(None, JEVD_HOME=str(jevd[0].parent))
    assert f":{jevd[1]}" in out["systemMessage"]


@pytest.mark.parametrize("env", [{"JEVD_URL": "http://127.0.0.1:1"}, {"JEVD_URL": "http://localhost:4377/v1/systemone"},
                                 {"SKILL_JEVD_ENV_CHECK": "0"},
                                 {"ENFORCER_JEV_ROUTER": "0"}, {"ENFORCER_JEV_GATE": "0"}])
def test_silent_when_jevd_url_set_or_check_or_router_off(jevd, env):
    out = _run(jevd[0], **env)
    assert "systemMessage" not in out
    assert "JEVD-ENV" not in out["hookSpecificOutput"]["additionalContext"]


def test_silent_when_jevd_is_not_running(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("[server]\nport = 1\n")  # nothing listens on port 1
    out = _run(cfg)
    assert "systemMessage" not in out
    assert "SKILL-FIRST" in out["hookSpecificOutput"]["additionalContext"]
