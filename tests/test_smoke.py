"""The smoke pass rule: a harness passes only when its run wrote an offer row (the per-turn enforcer
ran) and a search row (search_skills reached the model). A turn row alone is written by ledger.py, so
it never proves the enforcer ran: that gap hid Codex skipping the enforcer after a hook change.

The hardening tests below touch no real harness: fake CLIs and a fake `opencode serve` are small
Python scripts started in place of the real executables."""
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import smoke  # noqa: E402


def test_offer_and_search_pass():
    assert smoke.verdict([{"ev": "turn"}, {"ev": "offer", "band": "offer"}, {"ev": "search"}]) == ("PASS", "offer + search")


def test_a_turn_row_without_an_offer_row_fails():
    status, detail = smoke.verdict([{"ev": "turn"}, {"ev": "search"}])
    assert status == "FAIL" and "enforcer did not run" in detail


def test_hook_rows_without_a_search_row_fail():
    status, detail = smoke.verdict([{"ev": "turn"}, {"ev": "offer", "band": "offer"}])
    assert status == "FAIL" and "search_skills was not called, or its hook did not log it" in detail


def test_an_early_exit_band_fails_because_retrieval_never_ran():
    for band in ("negation", "harness_skip", "selfref_skip", "consult_route"):
        status, detail = smoke.verdict([{"ev": "offer", "band": band}, {"ev": "search"}])
        assert status == "FAIL" and "before retrieval" in detail, band


def test_bands_decided_after_the_index_lookup_pass():
    # getaway and intent_skip are decided after embedding and the index query (enforcer.py, the
    # getaway and actionability gates), so they prove retrieval ran.
    for band in ("offer", "jev_skip", "getaway", "intent_skip"):
        assert smoke.verdict([{"ev": "offer", "band": band}, {"ev": "search"}])[0] == "PASS", band


def test_an_outage_fallback_fails_even_on_a_retrieval_band():
    for fb in ("embed_timeout", "embed_down", "qdrant_down"):
        status, detail = smoke.verdict([{"ev": "offer", "band": "offer", "fallback": fb}, {"ev": "search"}])
        assert status == "FAIL" and fb in detail, fb
    assert smoke.verdict([{"ev": "offer", "band": "fallback", "fallback": "qdrant_down"}, {"ev": "search"}])[0] == "FAIL"


def test_an_empty_ledger_fails_on_both_signals():
    status, detail = smoke.verdict([])
    assert status == "FAIL" and "offer" in detail and "search" in detail


def test_a_missing_command_line_fails_instead_of_skipping():
    assert smoke.verdict([{"ev": "offer", "band": "offer"}, {"ev": "search"}], cli_found=False)[0] == "FAIL"


def test_zcode_is_unproven_and_fails_the_run_unless_accepted(capsys):
    assert smoke.smoke("zcode")[0] == "UNPROVEN"
    assert smoke.main(["zcode"]) == 1
    assert smoke.main(["zcode", "--accept-unproven", "zcode"]) == 0


# ---- helpers ---------------------------------------------------------------------------------

def _script(path: Path, body: str) -> str:
    path.write_text(f"#!{sys.executable}\n{body}")
    path.chmod(0o755)
    return str(path)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _wait_gone(pid: int, seconds: float = 5.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.05)
    return not _alive(pid)


def _wait_file(path: Path, seconds: float = 10.0) -> str:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if path.exists() and path.read_text().strip():
            return path.read_text().strip()
        time.sleep(0.05)
    raise AssertionError(f"{path} never appeared")


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Temp work folders land under tmp_path; the kill grace is shortened."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(smoke, "KILL_GRACE", 1)
    return tmp_path


def _fake_cli(sandbox: Path, monkeypatch, body: str) -> None:
    exe = _script(sandbox / "fake-cli", body)
    monkeypatch.setattr(smoke, "CLI", {"claude": (exe, [exe])})


# ---- scrubbed environment --------------------------------------------------------------------

def test_cli_gets_a_scrubbed_environment(sandbox, monkeypatch):
    _fake_cli(sandbox, monkeypatch, "import json, os\njson.dump(dict(os.environ), open('env.json', 'w'))\n")
    monkeypatch.setenv("SKILL_CONCIERGE_LOG", "/live/ledger")
    monkeypatch.setenv("SKILL_CONCIERGE_HARNESS", "claude")
    monkeypatch.setenv("SKILL_CONCIERGE_ROOT", "/a/clone")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("KEEP_ME", "yes")
    work = smoke._workdir("claude")
    smoke._run_cli("claude", work)
    env = json.loads((work / "env.json").read_text())
    assert env["SKILL_CONCIERGE_LOG"] == str(work / "logs")
    assert env["MNEMOSYNE_DATA_DIR"] == env["MNEMOSYNE_HOME"] == str(work / "mnemosyne")   # no live memory writes
    assert env["MNEMOSYNE_NO_CAPTURE"] == "1"
    assert "SKILL_CONCIERGE_HARNESS" not in env                 # a forced label would mislabel the run
    assert env["SKILL_CONCIERGE_ROOT"] == "/a/clone"              # install settings stay
    assert "CLAUDECODE" not in env and "ANTHROPIC_API_KEY" not in env
    assert env["KEEP_ME"] == "yes"


# ---- full output kept; ledger grace ----------------------------------------------------------

def test_cli_output_is_kept_in_full(sandbox, monkeypatch):
    _fake_cli(sandbox, monkeypatch,
              "import sys\nprint('first line')\nprint('to stderr', file=sys.stderr)\nprint('last line')\n")
    work = smoke._workdir("claude")
    note = smoke._run_cli("claude", work)
    text = (work / "output.txt").read_text()
    assert "first line" in text and "to stderr" in text and "last line" in text
    assert "last line" in note


LATE_WRITER = '''
import os, subprocess, sys
log = os.path.join(os.environ["SKILL_CONCIERGE_LOG"], "skill-invocation-ledger.log")
writer = ("import time, sys\\ntime.sleep(1.5)\\n"
          "open(sys.argv[1], 'a').write('{\\"ev\\": \\"offer\\", \\"band\\": \\"offer\\"}\\\\n{\\"ev\\": \\"search\\"}\\\\n')\\n")
subprocess.Popen([sys.executable, "-c", writer, log], start_new_session=True,
                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
'''


def test_ledger_rows_that_land_after_the_cli_exits_still_count(sandbox, monkeypatch):
    _fake_cli(sandbox, monkeypatch, LATE_WRITER)
    monkeypatch.setattr(smoke, "LEDGER_GRACE", 5)
    status, detail, _, _ = smoke.smoke("claude")
    assert (status, detail) == ("PASS", "offer + search")


def test_a_ledger_that_never_fills_fails_after_the_grace(sandbox, monkeypatch):
    _fake_cli(sandbox, monkeypatch, "pass\n")
    monkeypatch.setattr(smoke, "LEDGER_GRACE", 1)
    t0 = time.time()
    status, _, _, _ = smoke.smoke("claude")
    assert status == "FAIL" and time.time() - t0 >= 1


# ---- process groups --------------------------------------------------------------------------

GRANDCHILD_CLI = '''
import os, signal, subprocess, sys, time
child = ("import os, signal, time\\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\\n"
         "open('grandchild.pid', 'w').write(str(os.getpid()))\\ntime.sleep(300)\\n")
subprocess.Popen([sys.executable, "-c", child])
time.sleep(300)
'''


def test_timeout_leaves_no_live_process_even_one_that_ignores_sigterm(sandbox, monkeypatch):
    _fake_cli(sandbox, monkeypatch, GRANDCHILD_CLI)
    monkeypatch.setattr(smoke, "TIMEOUT", 1.5)
    work = smoke._workdir("claude")
    pidfile = work / "grandchild.pid"
    try:
        note = smoke._run_cli("claude", work)
        assert "timed out" in note
        pid = int(_wait_file(pidfile))
        assert _wait_gone(pid), "the grandchild outlived the timeout"
    finally:
        if pidfile.exists():
            try:
                os.kill(int(pidfile.read_text()), signal.SIGKILL)
            except (ProcessLookupError, ValueError):
                pass


def test_sigterm_to_the_smoke_runs_cleanup(tmp_path):
    scripts = str(Path(smoke.__file__).resolve().parent)
    fake = _script(tmp_path / "fake-long-cli", GRANDCHILD_CLI)
    driver = tmp_path / "driver.py"
    driver.write_text(
        f"import sys\nsys.path.insert(0, {scripts!r})\nimport smoke\n"
        f"smoke.CLI = {{'claude': ({fake!r}, [{fake!r}])}}\nsmoke.TIMEOUT = 120\n"
        "sys.exit(smoke.main(['claude']))\n")
    env = dict(os.environ, TMPDIR=str(tmp_path))
    proc = subprocess.Popen([sys.executable, str(driver)], env=env, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    pid = None
    try:
        pidfiles = []
        deadline = time.time() + 15
        while time.time() < deadline and not pidfiles:
            pidfiles = list(tmp_path.glob("sc-smoke-claude-*/grandchild.pid"))
            time.sleep(0.1)
        assert pidfiles, "the fake CLI never started"
        pid = int(_wait_file(pidfiles[0]))
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=20) == 128 + signal.SIGTERM
        assert _wait_gone(pid), "the grandchild survived SIGTERM to the smoke"
    finally:
        if proc.poll() is None:
            proc.kill()
        if pid and _alive(pid):
            os.kill(pid, signal.SIGKILL)


# ---- one harness's exception becomes a FAIL --------------------------------------------------

def test_main_turns_an_exception_into_a_fail_and_runs_the_rest(monkeypatch, capsys):
    def fake(h):
        if h == "claude":
            raise AttributeError("'dict' object has no attribute 'get'")
        return "PASS", "offer + search", 0.0, None

    monkeypatch.setattr(smoke, "smoke", fake)
    assert smoke.main(["claude", "codex"]) == 1
    out = capsys.readouterr().out
    claude = next(line for line in out.splitlines() if " claude " in line)
    assert "FAIL" in claude and "no attribute 'get'" in claude
    assert any(" codex " in line and "PASS" in line for line in out.splitlines())


# ---- OpenCode: a fake `opencode serve` -------------------------------------------------------

STUB_SERVER = r'''
import json, os, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

mode = os.environ["STUB_MODE"]
port = int(sys.argv[sys.argv.index("--port") + 1])
if mode == "exit":
    sys.exit(3)
open("server.pid", "w").write(str(os.getpid()))
if mode == "late":
    time.sleep(1.5)
log = os.path.join(os.environ["SKILL_CONCIERGE_LOG"], "skill-invocation-ledger.log")


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, code, payload):
        body = json.dumps({"data": payload}).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def route(self):
        if self.command == "POST":
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if mode == "401" or not self.headers.get("Authorization", "").startswith("Basic "):
            return self.reply(401, {})
        p = self.path
        if p == "/api/mcp":
            return self.reply(200, [{"name": "skill-search", "status": {"status": "connected"}}])
        if p == "/api/session":
            return self.reply(200, {"id": "s1"})
        if p == "/api/session/s1/prompt":
            if mode == "prompt500":
                return self.reply(500, {})
            if mode in ("ok", "late"):
                with open(log, "a") as f:
                    f.write('{"ev": "offer", "band": "offer"}\n{"ev": "search"}\n')
            time.sleep(60)   # the turn never finishes: smoke must stop the server mid-turn
            return self.reply(200, {})
        if p == "/api/session/s1/permission":
            if mode == "perm":
                return self.reply(200, [{"id": "p1", "action": "bash", "resources": ["cat vendor/skill-search/x.py"]}])
            return self.reply(200, [])
        if "/permission/" in p:
            open("replied.txt", "w").write(p)
            return self.reply(200, {})
        if p.endswith("/message"):
            return self.reply(200, [{"role": "user"}])
        if p.endswith("/context"):
            return self.reply(200, {"ctx": 1})
        self.reply(404, {})

    do_GET = do_POST = route


ThreadingHTTPServer.daemon_threads = True
ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
'''


@pytest.fixture
def opencode(sandbox, monkeypatch):
    exe = _script(sandbox / "fake-opencode", STUB_SERVER)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    monkeypatch.setattr(smoke, "OPENCODE_CMD", [exe])
    monkeypatch.setattr(smoke, "OPENCODE_PORT", port)
    monkeypatch.setattr(smoke, "POLL", 0.2)
    monkeypatch.setattr(smoke, "POLL_START", 0.1)
    monkeypatch.setattr(smoke, "STARTUP", 20)
    monkeypatch.setattr(smoke, "TIMEOUT", 4)
    for var in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(var, raising=False)

    def run(mode: str):
        monkeypatch.setenv("STUB_MODE", mode)
        work = smoke._workdir("opencode")
        note = smoke._run_opencode(work)
        pidfile = work / "server.pid"
        if pidfile.exists():
            assert _wait_gone(int(pidfile.read_text())), "opencode serve outlived the run"
        return work, note

    return run


def test_opencode_pass_leaves_no_server_no_thread_noise_and_ignores_proxies(opencode, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
    seen = []
    monkeypatch.setattr(threading, "excepthook", lambda args: seen.append(args))
    work, note = opencode("ok")
    assert note == "server turn finished"
    assert smoke.verdict(smoke._rows(work / "logs"))[0] == "PASS"
    assert seen == [], "the prompt thread printed a traceback after the server was stopped"


def test_opencode_waits_through_connection_refused_until_the_server_is_up(opencode):
    work, note = opencode("late")
    assert note == "server turn finished"


def test_opencode_http_error_reports_status_and_path_at_once(opencode):
    t0 = time.time()
    work, note = opencode("401")
    assert "HTTP 401" in note and "/api/mcp" in note
    assert "did not start" not in note
    assert time.time() - t0 < 10


def test_opencode_server_exit_is_reported_with_its_code(opencode):
    t0 = time.time()
    work, note = opencode("exit")
    assert note == "opencode serve exited 3"
    assert time.time() - t0 < 10


def test_opencode_prompt_failure_is_reported_not_blamed_on_missing_rows(opencode):
    work, note = opencode("prompt500")
    assert "prompt request failed" in note and "HTTP 500" in note and "/prompt" in note
    assert (work / "messages.json").exists() and (work / "context.json").exists()


def test_opencode_never_approves_a_permission_and_names_the_pending_one(opencode):
    work, note = opencode("perm")
    assert "no offer + search rows" in note
    assert "bash" in note and "cat vendor/skill-search/x.py" in note
    assert not (work / "replied.txt").exists(), "a permission request was answered"
    assert (work / "messages.json").exists() and (work / "context.json").exists()


def test_an_advisory_harness_still_reports_but_never_blocks(monkeypatch, capsys):
    monkeypatch.setattr(smoke, "smoke", lambda h: ("FAIL", "no offer row", 1.0, None) if h == "codex"
                        else ("PASS", "offer + search", 1.0, None))
    assert smoke.main(["claude", "codex"]) == 1                       # strict by default
    assert smoke.main(["claude", "codex", "--advisory", "codex"]) == 0
    out = capsys.readouterr().out
    assert "codex" in out and "FAIL" in out and "advisory: does not block" in out
    assert "smoke: OK (advisory, not proven: codex)" in out
    monkeypatch.setenv("SMOKE_ADVISORY", "codex,dsh")
    assert smoke.main(["claude", "codex"]) == 0                       # the default comes from SMOKE_ADVISORY
    assert smoke.main(["claude", "codex", "--advisory", ""]) == 1      # an explicit empty list is strict again


def test_an_unknown_advisory_harness_is_an_error():
    import pytest
    with pytest.raises(SystemExit):
        smoke.main(["claude", "--advisory", "codx"])
