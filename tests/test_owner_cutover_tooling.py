"""Cutover tooling for the local index owner — doctor rows, --cutover, the three start paths.

Everything here runs against temp files, stub HTTP servers and fake executables: no test
starts a real owner, touches Docker, or reads the live ports.
"""
import http.server
import importlib.util
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
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


def test_cutover_fails_installed_row_with_unknown_version(dr):
    """A3: an installed harness whose version could not be determined (None/empty) must
    FAIL under --cutover — it cannot prove it is at or above the release."""
    rows = [
        {"id": "claude-code", "status": "warn", "version": None,
         "detail": "skill-concierge has no Claude Code install record (installed_plugins.json)"},
        {"id": "omp", "status": "warn", "version": "",
         "detail": "skill-concierge has no OMP install record (installed_plugins.json)"},
    ]
    out = {r["id"]: r for r in dr.apply_cutover(rows, release="0.50.0")}
    assert out["claude-code"]["status"] == "fail" and "unknown" in out["claude-code"]["detail"]
    assert out["omp"]["status"] == "fail" and "unknown" in out["omp"]["detail"]


def test_cutover_leaves_not_installed_rows_from_the_real_checks_unchanged(dr, tmp_path, monkeypatch):
    """A3: the real "not installed" rows from every cutover harness's own check function
    (empty machine, none of the four dirs exist) must survive --cutover untouched, even
    though Claude Code's own row sets version=None just like the "unknown version" case."""
    monkeypatch.setattr(dr, "CLAUDE_PLUGINS_DIR", tmp_path / "no-claude-plugins")
    monkeypatch.setattr(dr, "OMP_DIR", tmp_path / "no-omp")
    monkeypatch.setattr(dr, "CODEX_DIR", tmp_path / "no-codex")
    monkeypatch.setattr(dr, "ZCODE_DIR", tmp_path / "no-zcode")
    rows = [dr.check_claude_code(), dr.check_omp(), dr.check_codex(), dr.check_zcode()]
    assert all("not installed" in r["detail"] for r in rows)
    out = {r["id"]: r for r in dr.apply_cutover(list(rows), release="0.50.0")}
    for r in rows:
        assert out[r["id"]]["status"] == r["status"] == "warn"


def test_cutover_leaves_harness_present_but_plugin_never_installed_rows_unchanged(
        dr, tmp_path, monkeypatch):
    """N7 regression: a harness that IS installed on the machine (its own dir exists) but
    never had skill-concierge installed into it — no cache dir, no install record — has no
    copy that could hold anything back, so --cutover must leave it at WARN, not FAIL. The
    prior fix over-reached: `detail` never contains the literal phrase "not installed" for
    this state (it says "no ... plugin cache found (never installed via marketplace)" or
    "has no ... install record"), so the old substring skip missed it and the row fell
    through to "installed version unknown" -> FAIL."""
    monkeypatch.setattr(dr, "CLAUDE_PLUGINS_DIR", tmp_path / "claude-plugins")
    (tmp_path / "claude-plugins").mkdir()
    monkeypatch.setattr(dr, "CLAUDE_PLUGINS_FILE", tmp_path / "claude-plugins" / "installed_plugins.json")

    monkeypatch.setattr(dr, "OMP_DIR", tmp_path / "omp")
    (tmp_path / "omp").mkdir()
    monkeypatch.setattr(dr, "OMP_PLUGINS_FILE", tmp_path / "omp" / "installed_plugins.json")
    monkeypatch.setattr(dr, "OMP_MARKETPLACE", tmp_path / "omp" / "no-marketplace")
    monkeypatch.setattr(dr, "OMP_PLUGIN_CACHE", tmp_path / "omp" / "no-cache")

    monkeypatch.setattr(dr, "CODEX_DIR", tmp_path / "codex")
    (tmp_path / "codex").mkdir()
    monkeypatch.setattr(dr, "CODEX_PLUGIN_CACHE", tmp_path / "codex" / "no-cache")

    monkeypatch.setattr(dr, "ZCODE_DIR", tmp_path / "zcode")
    (tmp_path / "zcode").mkdir()
    monkeypatch.setattr(dr, "ZCODE_PLUGINS_FILE", tmp_path / "zcode" / "installed_plugins.json")
    monkeypatch.setattr(dr, "ZCODE_PLUGIN_CACHE", tmp_path / "zcode" / "no-cache")

    rows = [dr.check_claude_code(), dr.check_omp(), dr.check_codex(), dr.check_zcode()]
    for r in rows:
        assert r["plugin_installed"] is False, r
        assert r["version"] is None, r
        assert "not installed" not in r["detail"], r   # the harness itself IS present
    out = {r["id"]: r for r in dr.apply_cutover(list(rows), release="0.50.0")}
    for r in rows:
        assert out[r["id"]]["status"] == "warn", out[r["id"]]


def test_cutover_leaves_at_release_row_unchanged(dr):
    rows = [{"id": "codex", "status": "ok", "detail": "d", "version": "0.50.0"}]
    out = dr.apply_cutover(list(rows), release="0.50.0")
    assert out[0]["status"] == "ok"


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


def test_zcode_version_prefers_registry_install_path_over_newest_dir(dr, tmp_path, monkeypatch):
    """L10: ZCode's own install registry names the ACTIVE copy — read that copy's version
    instead of trusting whichever cache dir happens to sort newest by name."""
    zcode_dir = tmp_path / "zcode"
    cache = zcode_dir / "cli" / "plugins" / "cache" / "skill-concierge" / "skill-concierge"
    active = cache / "0.40.0"
    newer_unused = cache / "0.99.0"           # sorts newest by name, but is NOT the active copy
    for d, ver in ((active, "0.40.0"), (newer_unused, "0.99.0")):
        (d / ".claude-plugin").mkdir(parents=True)
        (d / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": ver}))
        (d / "bin").mkdir()
        (d / "bin" / "skill-search-mcp").write_text("#!/bin/sh\n")
        (d / "bin" / "skill-search-mcp").chmod(0o755)
    registry = zcode_dir / "cli" / "plugins" / "installed_plugins.json"
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(json.dumps({"plugins": [
        {"id": "skill-concierge@skill-concierge", "version": "0.40.0", "installPath": str(active)}]}))
    monkeypatch.setattr(dr, "ZCODE_DIR", zcode_dir)
    monkeypatch.setattr(dr, "ZCODE_PLUGIN_CACHE", cache)
    monkeypatch.setattr(dr, "ZCODE_PLUGINS_FILE", registry)
    assert dr._zcode_installed_path() == str(active)
    row = dr.check_zcode()
    assert row["version"] == "0.40.0"        # the registry's active copy, not "0.99.0"


def test_zcode_version_falls_back_to_newest_dir_without_a_registry_record(dr, tmp_path, monkeypatch):
    zcode_dir = tmp_path / "zcode"
    cache = zcode_dir / "cli" / "plugins" / "cache" / "skill-concierge" / "skill-concierge"
    for v in ("0.9.0", "0.40.0"):
        (cache / v).mkdir(parents=True)
    monkeypatch.setattr(dr, "ZCODE_DIR", zcode_dir)
    monkeypatch.setattr(dr, "ZCODE_PLUGIN_CACHE", cache)
    monkeypatch.setattr(dr, "ZCODE_PLUGINS_FILE", zcode_dir / "cli" / "plugins" / "installed_plugins.json")
    assert dr._zcode_installed_path() is None
    row = dr.check_zcode()
    assert row["version"] == "0.40.0"        # numeric sort, not lexical ("0.9.0" > "0.40.0")


def test_cutover_fails_codex_row_with_corrupt_manifest(dr, tmp_path, monkeypatch):
    """M1: a Codex version dir IS present (installed), but its plugin.json is corrupt —
    existence must drive plugin_installed, not the (failed) version parse, or --cutover
    silently skips a stale/broken copy instead of FAILing it."""
    cache = tmp_path / "codex" / "cache"
    v = cache / "0.50.0" / ".codex-plugin"
    v.mkdir(parents=True)
    (v / "plugin.json").write_text("{corrupt")
    monkeypatch.setattr(dr, "CODEX_DIR", tmp_path / "codex")
    monkeypatch.setattr(dr, "CODEX_PLUGIN_CACHE", cache)
    row = dr.check_codex()
    assert row["version"] is None and row["plugin_installed"] is True
    assert "not installed" not in row["detail"] and "never installed" not in row["detail"]
    out = dr.apply_cutover([dict(row)], release="0.54.1")[0]
    assert out["status"] == "fail"


def test_cutover_fails_codex_row_with_version_dir_but_no_manifest(dr, tmp_path, monkeypatch):
    """M1: a Codex version dir with no plugin.json at all is still an install, not an
    absence — --cutover must FAIL it."""
    cache = tmp_path / "codex" / "cache"
    (cache / "0.50.0" / ".codex-plugin").mkdir(parents=True)
    monkeypatch.setattr(dr, "CODEX_DIR", tmp_path / "codex")
    monkeypatch.setattr(dr, "CODEX_PLUGIN_CACHE", cache)
    row = dr.check_codex()
    assert row["version"] is None and row["plugin_installed"] is True
    out = dr.apply_cutover([dict(row)], release="0.54.1")[0]
    assert out["status"] == "fail"


def test_cutover_fails_claude_record_without_version_key(dr, tmp_path, monkeypatch):
    """M1: a Claude Code install record present with no `version` field must not read as
    plugin_installed=False — a real install with a broken/missing version claim must FAIL
    under --cutover, not be skipped as never-installed."""
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    monkeypatch.setattr(dr, "CLAUDE_PLUGINS_DIR", plugins)
    monkeypatch.setattr(dr, "CLAUDE_PLUGINS_FILE", plugins / "installed_plugins.json")
    old = tmp_path / "cache" / "0.50.0"
    (old / ".claude-plugin").mkdir(parents=True)
    (old / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": "0.50.0"}))
    (plugins / "installed_plugins.json").write_text(json.dumps({"plugins": {
        "skill-concierge@skill-concierge": [{"scope": "user", "installPath": str(old)}]}}))
    row = dr.check_claude_code()
    assert row["plugin_installed"] is True
    assert "has no Claude Code install record" not in row["detail"]
    out = dr.apply_cutover([dict(row)], release="0.54.1")[0]
    assert out["status"] == "fail"


def test_cutover_fails_omp_record_without_version_key(dr, tmp_path, monkeypatch):
    """M1: same rule for OMP — a present record with no `version` field must FAIL, not be
    treated as never-installed."""
    omp = tmp_path / "omp"
    omp.mkdir()
    monkeypatch.setattr(dr, "OMP_DIR", omp)
    monkeypatch.setattr(dr, "OMP_PLUGINS_FILE", omp / "installed_plugins.json")
    monkeypatch.setattr(dr, "OMP_MARKETPLACE", omp / "no-marketplace")
    monkeypatch.setattr(dr, "OMP_PLUGIN_CACHE", omp / "no-cache")
    (omp / "installed_plugins.json").write_text(json.dumps({"plugins": {
        "skill-concierge@skill-concierge": [{"scope": "user", "installPath": "/x"}]}}))
    row = dr.check_omp()
    assert row["plugin_installed"] is True
    assert "has no OMP install record" not in row["detail"]
    out = dr.apply_cutover([dict(row)], release="0.54.1")[0]
    assert out["status"] == "fail"


def test_cutover_fails_zcode_registry_pointing_at_a_corrupt_copy_despite_a_newer_dir(
        dr, tmp_path, monkeypatch):
    """M1: ZCode's registry names a corrupt old copy as active while a newer, unrelated
    version dir also sits in the cache. The newest-dir-by-name fallback must never mask
    the registry's own broken pointer — that previously reported OK/matches-SSOT."""
    zcode = tmp_path / ".zcode"
    cache = zcode / "cache"
    old = cache / "0.50.0"
    (old / ".claude-plugin").mkdir(parents=True)
    (old / ".claude-plugin" / "plugin.json").write_text("{corrupt")
    (old / "bin").mkdir()
    (old / "bin" / "skill-search-mcp").write_text("x")
    (old / "bin" / "skill-search-mcp").chmod(0o755)
    new = cache / "0.54.1"
    (new / ".claude-plugin").mkdir(parents=True)
    (new / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": "0.54.1"}))
    monkeypatch.setattr(dr, "ZCODE_DIR", zcode)
    monkeypatch.setattr(dr, "ZCODE_PLUGIN_CACHE", cache)
    monkeypatch.setattr(dr, "ZCODE_PLUGINS_FILE", zcode / "installed_plugins.json")
    (zcode / "installed_plugins.json").write_text(json.dumps({"plugins": [
        {"id": "skill-concierge@skill-concierge", "installPath": str(old)}]}))
    row = dr.check_zcode()
    assert row["version"] is None and row["plugin_installed"] is True
    assert row["status"] == "warn" and "unreadable" in row["detail"]
    out = dr.apply_cutover([dict(row)], release="0.54.1")[0]
    assert out["status"] == "fail"


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


def test_fix_containers_reports_failure_when_docker_update_fails(dr, tmp_path, monkeypatch):
    """L5: a failed `docker update --restart=no` must be reported as a failure, never
    papered over as "disabled" — the container could still restart on its own."""
    db = tmp_path / "index.sqlite"
    db.write_bytes(b"")

    class Fail:
        returncode, stderr, stdout = 1, "permission denied", ""

    class Ok:
        returncode, stderr, stdout = 0, "", ""

    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd[1:])
        return Fail() if cmd[1] == "update" else Ok()

    monkeypatch.setattr(dr, "INDEX_DB", db)
    monkeypatch.setattr(dr.shutil, "which", lambda _n: "/usr/bin/docker")
    monkeypatch.setattr(dr, "_publishing_containers", lambda: [("skill-search-qdrant", "6333")])
    monkeypatch.setattr(dr, "_run", fake_run)
    ok, msg = dr.fix_containers()
    assert ok is False
    assert "disabled" not in msg
    assert "update --restart=no" in msg and "permission denied" in msg
    # never proceeded to `stop` once `update` failed
    assert calls == [["update", "--restart=no", "skill-search-qdrant"]]


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
        assert str(db) in row["detail"]   # the resolved database path, ordered by Thinh
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
    # OWNER_AUTOSTART is a module-level constant read from this env var at import time.
    # An ambient SKILL_OWNER_AUTOSTART=0 (e.g. the gate's own H1-safe test env) must not
    # silently flip these autostart-behavior tests' default-on assumption.
    monkeypatch.delenv("SKILL_OWNER_AUTOSTART", raising=False)
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


# ---------- embed parity ----------

class _FakeEmbedResp:
    def __init__(self, data: bytes):
        self._data = data

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_check_embed_parity_reports_a_clean_timeout_instead_of_hanging(dr, monkeypatch, tmp_path):
    """L6: the in-process model-load subprocess must be bounded — a stuck load reports a
    WARN row instead of hanging doctor forever."""
    monkeypatch.setattr(dr, "_owner_health", lambda: {"status": "ok", "model": "test-model"})
    monkeypatch.setattr(dr.urllib.request, "urlopen",
                        lambda req, timeout=10: _FakeEmbedResp(json.dumps({"vector": [0.1, 0.2]}).encode()))
    real_file = tmp_path / "fake-python"
    real_file.write_text("")
    monkeypatch.setattr(dr, "PY_BIN", real_file)

    def fake_run(cmd, **kw):
        assert kw.get("timeout") == dr.EMBED_PARITY_LOAD_TIMEOUT_S
        raise dr.subprocess.TimeoutExpired(cmd, kw["timeout"])

    monkeypatch.setattr(dr, "_run", fake_run)
    row = dr.check_embed_parity()
    assert row["status"] == "warn"
    assert "timed out" in row["detail"]


# ---------- MCP launcher autostart ----------

def _fake_venv(tmp_path):
    """A fake venv whose `python` answers the two `-c` shapes the launcher/setup.sh use
    (the owner-start Popen call, and the deployed-version JSON read) plus the legacy `-m`
    form some other caller might still use. The owner-start branch runs the launcher's OWN
    Popen code under the real interpreter, with a stub `skill_search.index_owner` first on
    PYTHONPATH that records its process group to `pgid_file` — so the test sees the group
    the launcher's code really produced, and dropping start_new_session makes it fail.
    """
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    marker = tmp_path / "owner-started"
    pgid_file = tmp_path / "owner-pgid"
    stub = tmp_path / "stubpkg" / "skill_search"
    stub.mkdir(parents=True)
    (stub / "__init__.py").write_text("")
    (stub / "index_owner.py").write_text(
        f"import os\nopen({str(pgid_file)!r}, 'w').write(str(os.getpgrp()))\n"
        f"open({str(marker)!r}, 'a').write('skill_search.index_owner\\n')\n")
    py = venv / "bin" / "python"
    py.write_text(f'''#!/bin/bash
if [ "$1" = "-m" ]; then
  echo "$2" >> "{marker}"
  exit 0
fi
if [ "$1" = "-c" ]; then
  case "$2" in
    *Popen*)
      exec env PYTHONPATH="{stub.parent}" "{sys.executable}" -c "$2" "$3"
      ;;
    *)
      f="$3"
      [ -f "$f" ] || exit 1
      ver=$(grep -o '"version"[[:space:]]*:[[:space:]]*"[^"]*"' "$f" | head -1 | sed -E 's/.*"([^"]*)"[[:space:]]*$/\\1/')
      [ -n "$ver" ] || exit 1
      printf '%s' "$ver"
      exit 0
      ;;
  esac
fi
exit 0
''')
    ss = venv / "bin" / "skill-search"
    ss.write_text("#!/bin/sh\nexit 0\n")
    py.chmod(0o755)
    ss.chmod(0o755)
    return venv, marker, pgid_file


@pytest.mark.parametrize("switch,started", [("1", True), ("0", False)])
def test_launcher_starts_owner_when_health_fails(tmp_path, switch, started):
    venv, marker, pgid_file = _fake_venv(tmp_path)
    query_port, embed_port = _free_port(), _free_port()
    home = tmp_path / "home"
    home.mkdir()
    # D2: the nested Popen the launcher runs (`python -m skill_search.index_owner`)
    # inherits this process's cwd all the way down — `-m` puts cwd ahead of the
    # PYTHONPATH stub on sys.path, so a caller running pytest with cwd inside
    # vendor/skill-search would let the REAL package shadow the stub and start a
    # real owner against the real database and port 6333. Pin cwd to tmp_path
    # (which holds no top-level skill_search package) so the stub wins no matter
    # where pytest itself was invoked from. HOME/SKILL_INDEX_DB/SKILL_OWNER_NO_MODEL
    # and the explicit ports are a second guard: if the stub is ever bypassed
    # regardless, a real owner still lands on a temp DB and free ports, never live.
    env = dict(os.environ, SKILL_CONCIERGE_VENV=str(venv), SKILL_OWNER_AUTOSTART=switch,
               EMBED_SHIM_PORT=str(embed_port), SKILL_CONCIERGE_LOG=str(tmp_path / "logs"),
               HOME=str(home), SKILL_INDEX_DB=str(tmp_path / "index.sqlite"),
               SKILL_OWNER_NO_MODEL="1",
               SKILL_OWNER_QUERY_PORT=str(query_port), SKILL_OWNER_EMBED_PORT=str(embed_port),
               SKILL_QDRANT_URL=f"http://127.0.0.1:{query_port}")
    r = subprocess.run(["bash", str(ROOT / "bin" / "skill-search-mcp")], env=env, cwd=tmp_path,
                       capture_output=True, text=True, timeout=30, check=False)
    assert r.returncode == 0, r.stderr
    deadline = time.time() + 5
    while started and not (marker.exists() and pgid_file.exists()) and time.time() < deadline:
        time.sleep(0.1)
    assert marker.exists() is started
    if started:
        assert marker.read_text().strip() == "skill_search.index_owner"
        # H2: the owner must land in its OWN process group, never the launcher's (bash
        # `subprocess.run` here shares this test process's pgid, since it is not itself
        # started with a new session) — a `nohup ... &` regression would put the child
        # back in that shared group.
        child_pgid = int(pgid_file.read_text().strip())
        assert child_pgid != os.getpgrp()


def test_launcher_execs_engine_when_owner_log_cannot_be_opened(tmp_path):
    """N2 regression: SKILL_CONCIERGE_LOG pointing at an unwritable location (here, a
    path with a plain FILE where a directory is expected) must not stop the MCP from
    starting — only the owner autostart fails, and the launcher still execs the engine
    (D3: this fix previously shipped with no test)."""
    venv, marker, pgid_file = _fake_venv(tmp_path)
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    env = dict(os.environ, SKILL_CONCIERGE_VENV=str(venv), SKILL_OWNER_AUTOSTART="1",
               EMBED_SHIM_PORT=str(_free_port()), SKILL_CONCIERGE_LOG=str(blocker / "logs"))
    r = subprocess.run(["bash", str(ROOT / "bin" / "skill-search-mcp")], env=env, cwd=tmp_path,
                       capture_output=True, text=True, timeout=30, check=False)
    assert r.returncode == 0, r.stderr  # fail-open: the launcher still execs the engine
    assert "owner autostart failed" in r.stderr
    assert not marker.exists()   # the owner never actually started
    assert not pgid_file.exists()


def test_engine_version_read_handles_apostrophe_in_root(tmp_path):
    """A1/A2: $ROOT (and $PLUGIN_JSON built from it) must never be spliced into a Python
    string literal — an apostrophe in the path used to break the embedded `open('...')`
    call. The launcher passes the path via argv instead, so it must survive unmodified."""
    root = tmp_path / "root's project"
    (root / "bin").mkdir(parents=True)
    shutil.copy(ROOT / "bin" / "skill-search-mcp", root / "bin" / "skill-search-mcp")
    (root / "bin" / "skill-search-mcp").chmod(0o755)
    (root / ".claude-plugin").mkdir()
    (root / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": "9.9.9"}))
    (root / "vendor" / "skill-search").mkdir(parents=True)
    venv, _marker, _pgid_file = _fake_venv(tmp_path)
    env = dict(os.environ, SKILL_CONCIERGE_VENV=str(venv), SKILL_OWNER_AUTOSTART="0")
    r = subprocess.run(["bash", str(root / "bin" / "skill-search-mcp")], env=env,
                       capture_output=True, text=True, timeout=30, check=False)
    assert r.returncode == 0, r.stderr
    assert "could not read version" not in r.stderr


def test_engine_version_read_fails_open_and_reports_on_bad_json(tmp_path):
    """A2: a readable-but-unparseable plugin.json must print one clear stderr line and
    still let the launcher continue (fail-open, not silent)."""
    root = tmp_path / "root"
    (root / "bin").mkdir(parents=True)
    shutil.copy(ROOT / "bin" / "skill-search-mcp", root / "bin" / "skill-search-mcp")
    (root / "bin" / "skill-search-mcp").chmod(0o755)
    (root / ".claude-plugin").mkdir()
    (root / ".claude-plugin" / "plugin.json").write_text("not json")
    (root / "vendor" / "skill-search").mkdir(parents=True)
    venv, _marker, _pgid_file = _fake_venv(tmp_path)
    env = dict(os.environ, SKILL_CONCIERGE_VENV=str(venv), SKILL_OWNER_AUTOSTART="0")
    r = subprocess.run(["bash", str(root / "bin" / "skill-search-mcp")], env=env,
                       capture_output=True, text=True, timeout=30, check=False)
    assert r.returncode == 0, r.stderr  # fail-open: the launcher still execs the engine
    assert "could not read version" in r.stderr


# ---------- setup.sh ----------

def test_setup_has_no_docker_start_path_and_starts_owner():
    text = (ROOT / "setup.sh").read_text()
    code = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
    assert "docker" not in code
    # H2: started via argv, not "-m skill_search.index_owner" string-glued on one nohup line
    assert '"skill_search.index_owner"' in code
    assert "start_new_session=True" in code
    # the stop is guarded by the owner title, so it can never signal a container's process
    assert "index owner (Qdrant-compatible subset)" in code
    # M4: the engine resync takes the SAME mkdir lock bin/skill-search-mcp's background
    # resync uses, so the two can never race pip against the shared venv.
    assert ".engine-resync.lock" in code
    # N10: the owner it starts must bind the SAME store/embed ports this script just
    # probed and stopped ($store_port, derived from $QURL) — QURL/EPORT are plain bash
    # vars, never exported by default, so the owner-start line must export them itself
    # or a configured non-default .mcp.json port would leave the owner on 6333/6363.
    owner_start = code[code.index('subprocess.Popen(') - 200:code.index('subprocess.Popen(')]
    assert 'SKILL_QDRANT_URL="$QURL"' in owner_start
    assert 'EMBED_SHIM_PORT="$EPORT"' in owner_start
    assert subprocess.run(["bash", "-n", str(ROOT / "setup.sh")], check=False).returncode == 0
