"""Cutover tooling for the local index owner — doctor rows, --cutover, the three start paths.

Everything here runs against temp files, stub HTTP servers and fake executables: no test
starts a real owner, touches Docker, or reads the live ports.
"""
import http.server
import importlib.util
import json
import os
import socket
import sqlite3
import subprocess
import threading
import time
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# doctor reads its configuration from the environment at import. The engine suite's
# conftest sets these process-wide for its own test owner, so a shared pytest run would
# hand doctor that owner's ports and collection: load doctor from a clean slate.
_ENGINE_SUITE_ENV = ("EMBED_SHIM_HOST", "EMBED_SHIM_PORT", "SKILL_COLLECTION",
                     "SKILL_CONCIERGE_CATALOG_ROOTS", "SKILL_EMBED_BACKEND", "SKILL_META_PATH",
                     "SKILL_QDRANT_URL", "SKILL_TRIGGERS", "SKILL_VECTOR_SIZE")


@pytest.fixture()
def dr(monkeypatch):
    for k in _ENGINE_SUITE_ENV:
        monkeypatch.delenv(k, raising=False)
    return _load("doctor_owner_t", ROOT / "scripts" / "doctor.py")


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _serve(routes):
    """Stub HTTP server on an ephemeral port answering GET `routes[path]` as JSON."""
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = routes.get(self.path)
            code = 200 if body is not None else 404
            data = json.dumps(body or {}).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


# ---------- --cutover ----------

def test_cutover_fails_harness_rows_below_release(dr):
    rows = [
        {"id": "claude-code", "status": "ok", "detail": "d", "version": "0.50.0"},
        {"id": "omp", "status": "warn", "detail": "d", "version": "0.47.1"},
        {"id": "codex", "status": "warn", "detail": "d", "version": "0.45.0"},
        {"id": "zcode", "status": "warn", "detail": "not installed", "version": None},
        {"id": "ledger", "status": "ok", "detail": "d", "version": "0.1.0"},
    ]
    out = {r["id"]: r for r in dr.apply_cutover(rows, release="0.50.0")}
    assert out["claude-code"]["status"] == "ok"
    assert out["omp"]["status"] == "fail" and "CUTOVER" in out["omp"]["detail"]
    assert out["codex"]["status"] == "fail"
    assert out["zcode"]["status"] == "warn"          # not installed: no copy to hold back
    assert out["ledger"]["status"] == "ok"           # not a harness row


def test_cutover_off_by_default_and_wired_through_run_all(dr, monkeypatch):
    assert dr.CUTOVER is False
    monkeypatch.setattr(dr, "CHECKS", [lambda: {"id": "omp", "label": "OMP", "status": "warn",
                                                "detail": "d", "fix": None, "version": "0.0.1"}])
    assert dr.run_all()[0]["status"] == "warn"
    monkeypatch.setattr(dr, "CUTOVER", True)
    assert dr.run_all()[0]["status"] == "fail"


def test_codex_version_sort_is_numeric(dr, tmp_path, monkeypatch):
    for v in ("0.9.0", "0.49.0", "0.45.0"):
        d = tmp_path / v / ".codex-plugin"
        d.mkdir(parents=True)
        (d / "plugin.json").write_text(json.dumps({"version": v}))
    monkeypatch.setattr(dr, "CODEX_PLUGIN_CACHE", tmp_path)
    assert dr._codex_cached_version() == "0.49.0"   # a string sort would say 0.9.0


def test_claude_version_row(dr, tmp_path, monkeypatch):
    """The --cutover gate reads the Claude Code row's `version`: the DEPLOYED content's own
    version (what Claude Code loads), which can differ from the install record's."""
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    monkeypatch.setattr(dr, "CLAUDE_PLUGINS_DIR", plugins)
    monkeypatch.setattr(dr, "CLAUDE_PLUGINS_FILE", plugins / "installed_plugins.json")
    assert dr.check_claude_code()["version"] is None
    deployed = tmp_path / "cache" / "0.47.1"
    (deployed / ".claude-plugin").mkdir(parents=True)
    (deployed / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": "0.47.1"}))
    (plugins / "installed_plugins.json").write_text(json.dumps({"plugins": {
        "skill-concierge@skill-concierge": [{"scope": "user", "version": "0.9.0",
                                             "installPath": str(deployed)}]}}))
    row = dr.check_claude_code()
    assert row["id"] == "claude-code" and row["version"] == "0.47.1"
    assert row["status"] == "warn"        # below SSOT, but only --cutover turns it FAIL
    assert dr.check_claude_code in dr.CHECKS


# ---------- owner port / container rows ----------

def test_parse_publishers(dr):
    ps = ("skill-search-qdrant\t127.0.0.1:6333->6333/tcp\n"
          "skill-concierge-embed-shim\t127.0.0.1:6363->6363/tcp\n"
          "other\t0.0.0.0:8443->443/tcp\n"
          "legacy\t0.0.0.0:6333->6333/tcp, :::6333->6333/tcp, 0.0.0.0:6334->6334/tcp\n")
    names = [n for n, _ in dr._parse_publishers(ps)]
    assert names == ["skill-search-qdrant", "skill-concierge-embed-shim", "legacy"]


def test_owner_ports_row(dr, monkeypatch):
    monkeypatch.setattr(dr, "_publishing_containers", lambda: None)
    assert dr.check_owner_ports()["status"] == "ok"
    monkeypatch.setattr(dr, "_publishing_containers", lambda: [])
    assert dr.check_owner_ports()["status"] == "ok"
    monkeypatch.setattr(dr, "_publishing_containers",
                        lambda: [("skill-search-qdrant", "127.0.0.1:6333->6333/tcp")])
    row = dr.check_owner_ports()
    assert row["status"] == "fail" and row["fix"] == "containers"
    monkeypatch.setattr(dr, "_publishing_containers", lambda: [("someone-else", "6333")])
    row = dr.check_owner_ports()
    assert row["status"] == "fail" and row["fix"] is None   # never stop a stranger's container


def test_owner_ports_follow_configured_ports(dr, monkeypatch):
    # an owner configured on other ports (a staging run) is not blocked by containers on 6333
    monkeypatch.setattr(dr, "OWNER_PORTS", ("6433", "6463"))
    ps = "skill-search-qdrant\t127.0.0.1:6333->6333/tcp\nstaged\t127.0.0.1:6433->6433/tcp\n"
    assert [n for n, _ in dr._parse_publishers(ps)] == ["staged"]


def test_owner_log_row(dr, tmp_path, monkeypatch):
    log = tmp_path / "index-owner.log"
    monkeypatch.setattr(dr, "OWNER_LOG", log)
    assert dr.check_owner_log()["status"] == "ok"
    log.write_text("2026-09-26 owner up\n")
    assert dr.check_owner_log()["status"] == "ok"
    log.write_text("2026-09-26 PORT CONFLICT: 6333 answered by 'qdrant - vector search engine'\n")
    assert dr.check_owner_log()["status"] == "fail"
    log.write_text("2026-09-26 venv stamp downgrade 0.50.0 -> 0.47.1; keeps serving\n")
    assert dr.check_owner_log()["status"] == "fail"


def test_fix_containers_is_latched_on_the_owner_index(dr, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(dr, "_run", lambda cmd, **kw: calls.append(cmd))
    monkeypatch.setattr(dr, "INDEX_DB", tmp_path / "index.sqlite")   # absent: pre-cutover
    ok, msg = dr.fix_containers()
    assert not ok and "cutover has not run" in msg and calls == []


def test_fix_containers_stops_disables_then_starts_owner(dr, tmp_path, monkeypatch):
    db = tmp_path / "index.sqlite"
    db.write_bytes(b"")
    calls = []

    class R:
        returncode, stderr, stdout = 0, "", ""

    monkeypatch.setattr(dr, "INDEX_DB", db)
    monkeypatch.setattr(dr.shutil, "which", lambda _n: "/usr/bin/docker")
    monkeypatch.setattr(dr, "_publishing_containers", lambda: [
        ("skill-search-qdrant", "6333"), ("skill-concierge-embed-shim", "6363"), ("x", "6333")])
    monkeypatch.setattr(dr, "_run", lambda cmd, **kw: calls.append(cmd[1:]) or R())
    monkeypatch.setattr(dr, "fix_owner_start", lambda: (True, "started the index owner"))
    ok, msg = dr.fix_containers()
    assert ok, msg
    assert calls == [["update", "--restart=no", "skill-search-qdrant"],
                     ["stop", "skill-search-qdrant"],
                     ["update", "--restart=no", "skill-concierge-embed-shim"],
                     ["stop", "skill-concierge-embed-shim"]]
    assert "docker" not in dr.AUTO_FIXERS            # the docker start path is gone
    assert dr.AUTO_FIXERS["containers"] is dr.fix_containers


# ---------- owner row ----------

def _owner_db(path, n):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE points(collection TEXT, id, vector BLOB, payload TEXT,"
                " PRIMARY KEY(collection, id))")
    con.executemany("INSERT INTO points VALUES ('claude_skills', ?, x'00', '{}')",
                    [(i,) for i in range(n)])
    con.commit()
    con.close()


def test_owner_row_foreign_answerer_fails(dr, monkeypatch):
    srv, url = _serve({"/": {"title": "qdrant - vector search engine", "version": "1.18.2"}})
    try:
        monkeypatch.setattr(dr, "QURL", url)
        row = dr.check_owner()
        assert row["status"] == "fail" and "not the index owner" in row["detail"]
        assert row["fix"] == "containers"
    finally:
        srv.shutdown()


def test_loading_owner_is_recognised_by_its_503_title(dr, monkeypatch):
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            data = json.dumps({"title": dr.OWNER_TITLE, "status": "loading"}).encode()
            self.send_response(503)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        monkeypatch.setattr(dr, "QURL", f"http://127.0.0.1:{srv.server_address[1]}")
        assert dr._store_title() == dr.OWNER_TITLE    # loading, not down: no duplicate start
    finally:
        srv.shutdown()


def test_owner_row_down_offers_start(dr, monkeypatch):
    monkeypatch.setattr(dr, "QURL", f"http://127.0.0.1:{_free_port()}")
    row = dr.check_owner()
    assert row["status"] == "fail" and row["fix"] == "owner"


def test_owner_row_healthy(dr, tmp_path, monkeypatch):
    db = tmp_path / "index.sqlite"
    _owner_db(db, 3)
    venv = tmp_path / "venv"
    venv.mkdir()
    (venv / ".engine-plugin-version").write_text("0.50.0")
    store, qurl = _serve({"/": {"title": dr.OWNER_TITLE},
                          "/collections/claude_skills": {"result": {"points_count": 3}}})
    emb, eurl = _serve({"/health": {"status": "ok", "code_version": "0.50.0"}})
    try:
        monkeypatch.setattr(dr, "QURL", qurl)
        monkeypatch.setattr(dr, "EMBED_BASE", eurl)
        monkeypatch.setattr(dr, "INDEX_DB", db)
        monkeypatch.setattr(dr, "VENV", venv)
        row = dr.check_owner()
        assert row["status"] == "ok", row
        assert "3 points" in row["detail"] and "integrity ok" in row["detail"]
        (venv / ".engine-plugin-version").write_text("0.51.0")
        assert dr.check_owner()["status"] == "warn"      # code_version skew
    finally:
        store.shutdown()
        emb.shutdown()


def test_cosine(dr):
    assert dr._cosine([1.0, 0.0], [2.0, 0.0]) == pytest.approx(1.0)
    assert dr._cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


# ---------- enforcer autostart (connection refused only, kill-switch) ----------

@pytest.fixture()
def en(tmp_path, monkeypatch):
    monkeypatch.setenv("SKILL_CONCIERGE_LOG", str(tmp_path / "logs"))
    mod = _load("enforcer_owner_t", ROOT / "hooks" / "scripts" / "enforcer.py")
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").write_text("")
    monkeypatch.setattr(mod, "OWNER_VENV", venv)
    monkeypatch.setattr(mod, "OWNER_AUTOSTART_STAMP", tmp_path / "owner-autostart.stamp")
    spawned = []
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kw: spawned.append(cmd))
    mod._spawned = spawned
    return mod


def test_enforcer_autostart_only_on_connection_refused(en):
    assert en._owner_autostart(TimeoutError()) is False
    assert en._owner_autostart(urllib.error.URLError(socket.timeout())) is False
    assert en._owner_autostart(urllib.error.HTTPError("u", 503, "loading", {}, None)) is False
    assert en._spawned == []
    assert en._owner_autostart(urllib.error.URLError(ConnectionRefusedError())) is True
    assert en._spawned[0][-2:] == ["-m", "skill_search.index_owner"]


def test_enforcer_autostart_rate_limited(en):
    refused = urllib.error.URLError(ConnectionRefusedError())
    assert en._owner_autostart(refused) is True
    assert en._owner_autostart(refused) is False      # within OWNER_AUTOSTART_EVERY_S
    old = time.time() - en.OWNER_AUTOSTART_EVERY_S - 5
    os.utime(en.OWNER_AUTOSTART_STAMP, (old, old))
    assert en._owner_autostart(refused) is True
    assert len(en._spawned) == 2


def test_enforcer_autostart_kill_switch(en, monkeypatch):
    monkeypatch.setattr(en, "OWNER_AUTOSTART", False)
    assert en._owner_autostart(ConnectionRefusedError()) is False
    assert en._spawned == []


def test_enforcer_kill_switch_reads_env(tmp_path, monkeypatch):
    monkeypatch.setenv("SKILL_OWNER_AUTOSTART", "0")
    monkeypatch.setenv("SKILL_CONCIERGE_LOG", str(tmp_path))
    assert _load("enforcer_owner_env_t", ROOT / "hooks" / "scripts" / "enforcer.py").OWNER_AUTOSTART is False


# ---------- MCP launcher autostart ----------

def _fake_venv(tmp_path):
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    marker = tmp_path / "owner-started"
    py = venv / "bin" / "python"
    py.write_text(f'#!/bin/sh\n[ "$1" = "-m" ] && echo "$2" >> "{marker}"\nexit 0\n')
    ss = venv / "bin" / "skill-search"
    ss.write_text("#!/bin/sh\nexit 0\n")
    py.chmod(0o755)
    ss.chmod(0o755)
    return venv, marker


@pytest.mark.parametrize("switch,started", [("1", True), ("0", False)])
def test_launcher_starts_owner_when_health_fails(tmp_path, switch, started):
    venv, marker = _fake_venv(tmp_path)
    env = dict(os.environ, SKILL_CONCIERGE_VENV=str(venv), SKILL_OWNER_AUTOSTART=switch,
               EMBED_SHIM_PORT=str(_free_port()), SKILL_CONCIERGE_LOG=str(tmp_path / "logs"))
    r = subprocess.run(["bash", str(ROOT / "bin" / "skill-search-mcp")], env=env,
                       capture_output=True, text=True, timeout=30, check=False)
    assert r.returncode == 0, r.stderr
    deadline = time.time() + 5
    while started and not marker.exists() and time.time() < deadline:
        time.sleep(0.1)
    assert marker.exists() is started
    if started:
        assert marker.read_text().strip() == "skill_search.index_owner"


# ---------- setup.sh ----------

def test_setup_has_no_docker_start_path_and_starts_owner():
    text = (ROOT / "setup.sh").read_text()
    code = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
    assert "docker" not in code
    assert "-m skill_search.index_owner" in code
    # the stop is guarded by the owner title, so it can never signal a container's process
    assert "index owner (Qdrant-compatible subset)" in code
    assert subprocess.run(["bash", "-n", str(ROOT / "setup.sh")], check=False).returncode == 0
