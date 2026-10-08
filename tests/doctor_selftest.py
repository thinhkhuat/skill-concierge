# doctor.py's built-in self-test, kept out of the shipped script.
#
# Not a pytest module (no test_ prefix). `doctor.py --selftest` and
# tests/test_doctor_selftest.py load this file and exec it inside doctor's own module
# namespace, so every bare name below (overall, CHECKS, _drift_remedy, ...) and every
# globals() monkeypatch resolves against doctor exactly as when it lived in doctor.py.
# No module docstring on purpose: exec'ing one would overwrite doctor's __doc__.


def _selftest():
    mk = lambda s: {"id": "x", "label": "x", "status": s, "detail": "", "fix": None}
    assert overall([mk(OK), mk(OK)]) == OK
    assert overall([mk(OK), mk(WARN)]) == WARN
    assert overall([mk(WARN), mk(FAIL)]) == FAIL
    assert overall([]) == OK
    assert QURL.startswith("http")
    assert set(AUTO_FIXERS) <= {"owner", "containers", "reindex", "overrides", "prompt_intent",
                                "purge_junk"}
    # _stale_only: stale + fully reachable + indexed + nothing dark/stale-point -> WARN-worthy
    healthy_emb = {"reachable": True}
    serving_qd = {"reachable": True, "indexed": 495}
    assert _stale_only({"stale": True, "embedder": healthy_emb, "qdrant": serving_qd,
                        "dark_skills": [], "stale_points": []}) is True
    assert _stale_only({"stale": False, "embedder": healthy_emb, "qdrant": serving_qd}) is False
    assert _stale_only({"stale": True, "embedder": healthy_emb, "qdrant": serving_qd,
                        "dark_skills": ["x"], "stale_points": []}) is False
    assert _stale_only({"stale": True, "embedder": {"reachable": False},
                        "qdrant": serving_qd, "dark_skills": [], "stale_points": []}) is False
    sample = ("plugin:skill-concierge:skill-search: /cache/.../0.4.2/bin/skill-search-mcp - ok\n"
              "skill-search: ${CLAUDE_PLUGIN_ROOT}/bin/skill-search-mcp - pending\n"
              "exa: https://x - ok")
    assert _skill_search_servers(sample) == ["plugin:skill-concierge:skill-search"], _skill_search_servers(sample)
    two = sample + "\nskill-search: /usr/local/bin/other-skill-search-mcp - ok"
    assert len(_skill_search_servers(two)) == 2
    # engine-freshness digest: identical trees hash equal, a 1-byte change diverges, absent -> None
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        a, b = Path(d) / "a" / "skill_search", Path(d) / "b" / "skill_search"
        for base in (a, b):
            base.mkdir(parents=True)
            (base / "x.py").write_text("print(1)\n")
        assert _tree_digest(a) == _tree_digest(b)
        (b / "x.py").write_text("print(2)\n")
        assert _tree_digest(a) != _tree_digest(b)
        assert _tree_digest(Path(d) / "absent") is None
    assert any(getattr(fn, "__name__", "") == "check_engine_freshness" for fn in CHECKS)
    # ps etime -> seconds, all three formats the field can take, plus the junk cases
    assert _etime_seconds("05:30") == 330
    assert _etime_seconds("01:02:03") == 3723
    assert _etime_seconds("2-03:04:05") == 2 * 86400 + 3 * 3600 + 4 * 60 + 5
    assert _etime_seconds("garbage") is None and _etime_seconds("1:2:3:4") is None
    assert any(getattr(fn, "__name__", "") == "check_running_engine" for fn in CHECKS)
    # A healthy index the agent cannot reach is still a dark catalogue: parse the STATE of each
    # real skill-search install, not just its presence, and skip the repo's own .mcp.json
    # projection the same way the duplicate check does.
    _mcp = (
        "plugin:smgrep:smgrep: smgrep mcp - \u2714 Connected\n"
        "plugin:skill-concierge:skill-search: /p/bin/x  - \u2298 Disabled for this project (via /mcp)\n"
        "skill-search: ${CLAUDE_PLUGIN_ROOT}/bin/skill-search-mcp  - \u23f8 Pending approval\n")
    _st = _skill_search_statuses(_mcp)
    assert list(_st) == ["plugin:skill-concierge:skill-search"], _st
    assert _st["plugin:skill-concierge:skill-search"].endswith("(via /mcp)")
    assert _skill_search_statuses("") == {}
    assert "Connected" in _skill_search_statuses(
        "plugin:a:skill-search: /p - \u2714 Connected\n")["plugin:a:skill-search"]
    assert any(getattr(fn, "__name__", "") == "check_mcp_enabled" for fn in CHECKS)
    # Engine drift must never be auto-"fixed" by a reindex: the remedy is a restart, and
    # a reindex would clear the CLI-side symptom while the live server stays broken.
    drift_rep = {"status": "degraded", "issues": ["engine ... restart"],
                 "engine_build": {"running": "aaaa", "index_written_by": "bbbb"}}
    assert _stale_only(drift_rep) is False
    # `engine_build` is published on EVERY report now, so its mere presence says nothing.
    # Drift is `index_written_by` being set; keying on presence would flag every healthy run.
    assert _is_engine_drift({"engine_build": {"running": "aaaa", "index_written_by": "bbbb"}})
    assert not _is_engine_drift({"engine_build": {"running": "aaaa", "index_written_by": None}})
    assert not _is_engine_drift({})

    # --- live-server classification: identity, never timestamps -----------
    # The bug this replaces: setup.sh re-copies the engine on every run, so file mtime/ctime
    # advance even when the bytes are identical, and dating a server against them flags every
    # live process after a routine no-op re-run. Builds are compared, so a no-op re-copy is
    # invisible here by construction.
    live = [("100", 1_000.0), ("200", 2_000.0), ("300", 3_000.0)]
    records = {
        "100": {"pid": 100, "build": "cur", "started_at": 1_000.0},   # matches -> clean
        "200": {"pid": 200, "build": "old", "started_at": 2_000.0},   # genuine drift
        # 300 has no record at all -> unknown
    }
    drift, unknown = _classify_servers(live, records, "cur")
    assert drift == ["200"], drift
    assert unknown == ["300"], unknown
    # A no-op re-copy changes no build id, so every server stays clean however new the files.
    assert _classify_servers([("100", 1_000.0)], records, "cur") == ([], [])
    # Pid reuse: the number is live again but belongs to a different process. A record whose
    # start time cannot be THIS process's must not lend it a build it never ran. A leftover
    # record ALWAYS predates the process that inherits its pid, so this is the negative side.
    recycled = [("100", 9_999.0)]
    assert _classify_servers(recycled, records, "cur") == ([], ["100"])
    # A record for a pid that is no longer live is simply not considered.
    assert _classify_servers([], records, "cur") == ([], [])
    # A build id we cannot read is UNKNOWN, never proven drift. "unknown" is the engine's own
    # fail-open sentinel from _engine_build(); server._engine_drift refuses to accuse on it for
    # the same reason — an accusation whose remedy is "restart" that the restart cannot clear.
    # Two copies of that rule exist now, so they are pinned to agree.
    for bad in ({"pid": 100, "build": "unknown", "started_at": 1_000.0},
                {"pid": 100, "started_at": 1_000.0}):
        assert _classify_servers([("100", 1_000.0)], {"100": bad}, "cur") == ([], ["100"])
    # Startup slack is ONE-SIDED. started_at is stamped after the launcher's prelude, which
    # includes the ADR-0018 pip resync — the one moment a plugin update makes drift matter
    # most, and the one most likely to run long. A symmetric window would file that server
    # under "publishes no build id" for its whole life, with a remedy that never clears it.
    slow = {"100": {"pid": 100, "build": "old", "started_at": 1_000.0 + 900}}
    assert _classify_servers([("100", 1_000.0)], slow, "cur") == (["100"], []), "slow startup"
    # ...but a record stamped BEFORE its process began is impossible for that process.
    early = {"100": {"pid": 100, "build": "old", "started_at": 1_000.0 - 900}}
    assert _classify_servers([("100", 1_000.0)], early, "cur") == ([], ["100"]), "pre-dated"
    # ps parsing: only real SERVER processes count. A `--reindex` can run for minutes and
    # matches the same binary path, but CLI runs write no build record — counting one would
    # report a permanent unknown-build server that is really just a busy reindex.
    ps_out = "\n".join([
        f"  501    02:00 {SS_BIN}",
        f"  502    01:00 {SS_BIN} --reindex --force",
        f"  503    00:30 {SS_BIN} --health",
        "  504    00:10 /usr/bin/python3 -m http.server",
        f"  505 garbage {SS_BIN}",
        f"  506    03:00 {SS_BIN} --some-future-flag",
    ])
    parsed = _parse_server_lines(ps_out, now=10_000.0)
    # 506 counts: an unrecognized flag falls through to the server branch upstream and DOES
    # write a record, so excluding it would hide a real server behind a green check.
    assert [p for p, _ in parsed] == ["501", "506"], parsed
    assert parsed[0][1] == 10_000.0 - 120                   # etime resolved to a start epoch
    # An unexpanded ${HOME} would silently point the reader at a directory no server writes
    # to, making every live server "unproven" forever — the failure this seam exists to avoid.
    assert "$" not in str(SERVER_RECORDS), f"unexpanded variable in {SERVER_RECORDS}"
    assert SERVER_RECORDS.is_absolute(), SERVER_RECORDS
    # Assert the WIRING, not the helper. Calling _reset_pass_caches() here and checking the
    # globals would pass while run_all() called a renamed/absent function — which is exactly
    # what happened once: the helper was verified in isolation, run_all() still named the old
    # one, and doctor died with a NameError that the green selftest had no way to see. So
    # drive the real run_all() and have a probe check what a check actually observes.
    global _HEALTH_RUN, _RUNNING_STATE
    seen = {}

    def _probe():
        seen["health"], seen["running"] = _HEALTH_RUN, _RUNNING_STATE

    _saved_checks = list(CHECKS)        # mutate in place: `global CHECKS` would have to be
    _HEALTH_RUN = "sentinel-from-a-previous-run"    # declared above its earlier reads here
    _RUNNING_STATE = "sentinel-from-a-previous-run"
    try:
        CHECKS[:] = [_probe]
        run_all()
    finally:
        CHECKS[:] = _saved_checks
    # BOTH per-pass caches reset from ONE place, so a future third cache cannot be added to
    # only half of the boundary. Any of them outliving a pass makes `--fix` re-report the
    # failure it just repaired and exit 1 on a system that is now healthy.
    assert seen.get("health") is None, "run_all() must invalidate the --health memo"
    assert seen.get("running") is _UNSET, "run_all() must invalidate the live-server memo"

    # --- drift remedy: doctor DECIDES what the engine can only offer as alternatives ---
    # The engine sees its own build and nothing else, so its message names both remedies.
    # doctor holds the live-server evidence in the same pass, so it resolves which applies.
    d, r = _drift_remedy("bbbb", "aaaa", ([], []))
    assert r == "reindex", "proven-clean must be auto-fixable — a reindex re-stamps it"
    assert "reindex" in d.lower() and "restart" not in d.lower(), d
    # A live server on an older build: a reindex writes OUR build and that server hands the
    # mismatch straight back. Auto-fixing here is the 0.20.6 defect, so fix must stay None.
    d, r = _drift_remedy("bbbb", "aaaa", (["77"], []))
    assert r is None and "restart" in d.lower() and "77" in d, d
    # Unproven is not proven-clean. Never auto-reindex on an unverified fleet.
    d, r = _drift_remedy("bbbb", "aaaa", ([], ["77"]))
    assert r is None and "restart" in d.lower(), d
    # No evidence at all (ps missing, engine too old to publish an id) -> stay conditional.
    d, r = _drift_remedy("bbbb", "aaaa", None)
    assert r is None and "reindex" in d.lower() and "restart" in d.lower(), d
    # The SEAM, not just the pure function. `_drift_remedy` can be perfect while
    # `check_engine_health` hands it the wrong fields — a mis-wire that names live pids as
    # "still on an older build" on a proven-CLEAN fleet, which is the exact failure this
    # release retires, and a selftest that only exercised `_drift_remedy` stayed green
    # through it. Everything here is patched, so nothing spawns, reads ps, or touches the
    # records dir: an earlier version called the real `_running_engine_state()` and deleted
    # files from ~/.cache/skill-search/servers as a side effect of running --selftest.
    _g = globals()
    _saved = {k: _g[k] for k in ("SS_BIN", "_health_run", "_running_engine_state")}
    try:
        _g["SS_BIN"] = Path(__file__)                       # merely has to exist
        _g["_health_run"] = lambda: subprocess.CompletedProcess(
            [], 0, stdout=json.dumps({
                "status": "degraded", "issues": ["engine drift"],
                "engine_build": {"running": "aaaa", "index_written_by": "bbbb"},
                "qdrant": {"reachable": True, "indexed": 418}}), stderr="")
        # Clean fleet, but two live pids present: the row must NOT name them as drifting.
        _g["_running_engine_state"] = lambda: RunningState("aaaa", ["11", "22"], [], [])
        row = check_engine_health()
        assert row["fix"] == "reindex", row
        assert "11" not in row["detail"] and "22" not in row["detail"], row
        # Same report, but one pid genuinely on another build -> never auto-fix.
        _g["_running_engine_state"] = lambda: RunningState("aaaa", ["11", "22"], ["11"], [])
        row = check_engine_health()
        assert row["fix"] is None and "11" in row["detail"], row
    finally:
        _g.update(_saved)
    # Pruning is keyed on "does this pid still exist", NOT on "did I see it in ps". The
    # records dir is shared by every install on the machine, but `ps` here only matches THIS
    # venv's binary — so pruning by the ps result would delete another install's LIVE record
    # and make its doctor report an unknown build. That is the very false alarm being fixed.
    assert _pid_alive(str(os.getpid())) is True
    assert _pid_alive("2147483646") is False                # far above any live pid
    assert _pid_alive("not-a-pid") is False
    with tempfile.TemporaryDirectory() as d:
        recs = Path(d)
        mine, dead = recs / f"{os.getpid()}.json", recs / "2147483646.json"
        for p in (mine, dead):
            p.write_text(json.dumps({"pid": int(p.stem), "build": "x", "started_at": 0}))
        _prune_server_records(recs)
        assert mine.exists(), "pruned a record whose process is still alive"
        assert not dead.exists(), "kept a record for a dead pid"
    # --- OMP harness check (ADR-0040): fixture-driven, never touches the real ~/.omp ---
    # Four outcomes, all fail-open: absent OMP -> WARN "not installed" (optional harness,
    # exit unchanged); in-sync -> OK; install-record version lag vs SSOT -> WARN;
    # pre-0.28.0 cache without the OMP extension surface -> WARN with upgrade hint.
    _saved_omp = {k: _g[k] for k in ("OMP_DIR", "OMP_PLUGINS_FILE", "OMP_MARKETPLACE",
                                     "OMP_PLUGIN_CACHE")}
    try:
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            _g["OMP_DIR"] = base / ".omp"
            _g["OMP_PLUGINS_FILE"] = _g["OMP_DIR"] / "plugins" / "installed_plugins.json"
            _g["OMP_MARKETPLACE"] = _g["OMP_DIR"] / "plugins" / "cache" / "marketplaces" / "skill-concierge"
            _g["OMP_PLUGIN_CACHE"] = _g["OMP_DIR"] / "plugins" / "cache" / "plugins"
            # OMP absent entirely -> WARN "omp: not installed", never FAIL.
            row = check_omp()
            assert row["status"] == WARN and "not installed" in row["detail"], row
            # Fully in sync (SSOT 0.27.0 == install record == marketplace == cache, ext present) -> OK.
            ssot = ROOT / ".claude-plugin" / "plugin.json"
            ssot_ver = json.loads(ssot.read_text(encoding="utf-8"))["version"]
            _g["OMP_PLUGINS_FILE"].parent.mkdir(parents=True)
            _g["OMP_PLUGINS_FILE"].write_text(json.dumps({
                "version": 2, "plugins": {
                    "skill-concierge@skill-concierge": [
                        {"scope": "user", "version": ssot_ver, "enabled": True}]}}))
            mkt_dir = _g["OMP_MARKETPLACE"] / ".claude-plugin"
            mkt_dir.mkdir(parents=True)
            (mkt_dir / "marketplace.json").write_text(json.dumps(
                {"plugins": [{"name": "skill-concierge", "version": ssot_ver}]}))
            pinned = _g["OMP_PLUGIN_CACHE"] / f"skill-concierge___skill-concierge___{ssot_ver}"
            (pinned / "adapters" / "omp").mkdir(parents=True)
            (pinned / "adapters" / "omp" / "skill-concierge.ext.ts").write_text("")
            row = check_omp()
            assert row["status"] == OK, row
            # Version lag: install record says 0.26.2 against SSOT 0.27.0 -> WARN naming both.
            _g["OMP_PLUGINS_FILE"].write_text(json.dumps({
                "version": 2, "plugins": {
                    "skill-concierge@skill-concierge": [
                        {"scope": "user", "version": "0.26.2", "enabled": True}]}}))
            row = check_omp()
            assert row["status"] == WARN and "0.26.2" in row["detail"] and ssot_ver in row["detail"], row
            # Pre-0.28.0 cache: record matches SSOT but the cache lacks the ext surface -> WARN.
            _g["OMP_PLUGINS_FILE"].write_text(json.dumps({
                "version": 2, "plugins": {
                    "skill-concierge@skill-concierge": [
                        {"scope": "user", "version": ssot_ver, "enabled": True}]}}))
            (pinned / "adapters" / "omp" / "skill-concierge.ext.ts").unlink()
            row = check_omp()
            assert row["status"] == WARN and "0.28.0" in row["detail"], row
            # Disabled install is surfaced, not silently green.
            _g["OMP_PLUGINS_FILE"].write_text(json.dumps({
                "version": 2, "plugins": {
                    "skill-concierge@skill-concierge": [
                        {"scope": "user", "version": ssot_ver, "enabled": False}]}}))
            row = check_omp()
            assert row["status"] == WARN and "DISABLED" in row["detail"], row
    finally:
        _g.update(_saved_omp)
    # --- Codex harness check (ADR-0033): fixture-driven, never touches the real ~/.codex ---
    # Two outcomes: absent Codex -> WARN "not installed"; cache matches SSOT -> OK.
    _saved_codex = {k: _g[k] for k in ("CODEX_DIR", "CODEX_PLUGIN_CACHE")}
    try:
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            _g["CODEX_DIR"] = base / ".codex"
            _g["CODEX_PLUGIN_CACHE"] = base / ".codex" / "plugins" / "cache" / "skill-concierge" / "skill-concierge"
            # Codex absent entirely -> WARN "codex: not installed", never FAIL.
            row = check_codex()
            assert row["status"] == WARN and "not installed" in row["detail"], row
            # Fully in sync: cached version matches SSOT.
            codex_ssot = _descriptor_version(ROOT / ".codex-plugin" / "plugin.json")
            cached_dir = _g["CODEX_PLUGIN_CACHE"] / codex_ssot
            (cached_dir / ".codex-plugin").mkdir(parents=True)
            (cached_dir / ".codex-plugin" / "plugin.json").write_text(json.dumps(
                {"name": "skill-concierge", "version": codex_ssot}))
            (cached_dir / "skills" / "dummy").mkdir(parents=True)
            (cached_dir / "skills" / "dummy" / "SKILL.md").write_text("# placeholder")
            (cached_dir / ".codex-plugin" / "mcp.json").write_text("{}")
            (cached_dir / ".codex").mkdir()
            (cached_dir / ".codex" / "hooks.json").write_text("{}")
            (cached_dir / "bin").mkdir()
            (cached_dir / "bin" / "skill-search-mcp").write_text("#!/bin/sh\n")
            (cached_dir / "bin" / "skill-search-mcp").chmod(0o755)
            row = check_codex()
            assert row["status"] == OK, row
            # Each descriptor the installer requires is a finding when missing.
            for rel in (".codex-plugin/mcp.json", ".codex/hooks.json"):
                (cached_dir / rel).rename(cached_dir / (rel + ".off"))
                row = check_codex()
                assert row["status"] == WARN and rel in row["detail"], (rel, row)
                (cached_dir / (rel + ".off")).rename(cached_dir / rel)
            # Codex starts the launcher itself: without its exec bit the row is not OK.
            (cached_dir / "bin" / "skill-search-mcp").chmod(0o644)
            row = check_codex()
            assert row["status"] == WARN and "launcher" in row["detail"], row
            (cached_dir / "bin" / "skill-search-mcp").chmod(0o755)
            # Version lag: cache v0.0.1 vs SSOT -> WARN naming both.
            # Write lower version into the cached plugin.json
            (cached_dir / ".codex-plugin" / "plugin.json").write_text(json.dumps(
                {"name": "skill-concierge", "version": "0.0.1"}))
            row = check_codex()
            assert row["status"] == WARN and "0.0.1" in row["detail"] and codex_ssot in row["detail"], row
            assert "adapters/codex/install.sh" in row["detail"], row
    finally:
        _g.update(_saved_codex)

    # Regression: _codex_cached_version() must pick the semver-NEWEST version dir, not the
    # lexically-largest dir name, and must ignore non-version staging dirs Codex leaves
    # behind (e.g. `plugin-install-UEVanZ`) — a plain string sort ranks "0.9.0" above
    # "0.52.3" ('9' > '5' at the first differing char).
    _saved_codex_ver = {k: _g[k] for k in ("CODEX_PLUGIN_CACHE",)}
    try:
        with tempfile.TemporaryDirectory() as d:
            base = Path(d) / "cache"
            _g["CODEX_PLUGIN_CACHE"] = base
            for ver in ("0.9.0", "0.52.3"):
                pdir = base / ver / ".codex-plugin"
                pdir.mkdir(parents=True)
                (pdir / "plugin.json").write_text(json.dumps(
                    {"name": "skill-concierge", "version": ver}))
            # A non-version staging dir carrying its OWN (bogus) descriptor, so passing
            # this case requires the dirname filter to exclude it structurally — it must
            # not merely rely on a missing plugin.json to skip past it.
            stage = base / "plugin-install-UEVanZ" / ".codex-plugin"
            stage.mkdir(parents=True)
            (stage / "plugin.json").write_text(json.dumps(
                {"name": "skill-concierge", "version": "9.9.9"}))
            assert _codex_cached_version() == "0.52.3", _codex_cached_version()
    finally:
        _g.update(_saved_codex_ver)

    # --- Claude Code harness check: fixture-driven, never touches the real ~/.claude/plugins ---
    # Three outcomes: absent registry -> WARN "not installed"; deployed content matches SSOT
    # -> OK; version lag (content decides, not the record) -> WARN naming the install script.
    _saved_cc = {k: _g[k] for k in ("CLAUDE_PLUGINS_DIR", "CLAUDE_PLUGINS_FILE")}
    try:
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            _g["CLAUDE_PLUGINS_DIR"] = base / ".claude" / "plugins"
            _g["CLAUDE_PLUGINS_FILE"] = _g["CLAUDE_PLUGINS_DIR"] / "installed_plugins.json"
            # No ~/.claude/plugins at all -> WARN "not installed", never FAIL.
            row = check_claude_code()
            assert row["status"] == WARN and "not installed" in row["detail"], row
            # Registry present but no record for skill-concierge -> WARN naming it.
            _g["CLAUDE_PLUGINS_DIR"].mkdir(parents=True)
            _g["CLAUDE_PLUGINS_FILE"].write_text(json.dumps({"plugins": {}}))
            row = check_claude_code()
            assert row["status"] == WARN and "no Claude Code install record" in row["detail"], row
            # Fully in sync: registry + the installed path's own plugin.json match SSOT.
            cc_ssot = _descriptor_version(ROOT / ".claude-plugin" / "plugin.json")
            install_dir = _g["CLAUDE_PLUGINS_DIR"] / "cache" / "skill-concierge" / "skill-concierge" / cc_ssot
            (install_dir / ".claude-plugin").mkdir(parents=True)
            (install_dir / ".claude-plugin" / "plugin.json").write_text(
                json.dumps({"name": "skill-concierge", "version": cc_ssot}))
            (install_dir / "bin").mkdir()
            launcher = install_dir / "bin" / "skill-search-mcp"
            launcher.write_text("#!/bin/sh\n")
            launcher.chmod(0o755)
            _g["CLAUDE_PLUGINS_FILE"].write_text(json.dumps({
                "plugins": {"skill-concierge@skill-concierge": [
                    {"scope": "user", "installPath": str(install_dir), "version": cc_ssot}]}}))
            row = check_claude_code()
            assert row["status"] == OK, row
            # Version lag: the installed content's own descriptor is stale -> WARN naming
            # both versions and pointing at the install script (content decides, not the
            # record — the registry can still say cc_ssot while the deployed tree lags).
            (install_dir / ".claude-plugin" / "plugin.json").write_text(
                json.dumps({"name": "skill-concierge", "version": "0.0.1"}))
            row = check_claude_code()
            assert (row["status"] == WARN and "0.0.1" in row["detail"] and cc_ssot in row["detail"]
                    and "adapters/claude-code/install.sh" in row["detail"]), row
            (install_dir / ".claude-plugin" / "plugin.json").write_text(
                json.dumps({"name": "skill-concierge", "version": cc_ssot}))
            # Exec bit lost on the launcher -> WARN naming the install script.
            launcher.chmod(0o644)
            row = check_claude_code()
            assert (row["status"] == WARN and "lost its exec bit" in row["detail"]
                    and "adapters/claude-code/install.sh" in row["detail"]), row
            # Launcher missing -> WARN, never OK; the row carries the deployed version, not the record's.
            launcher.unlink()
            _g["CLAUDE_PLUGINS_FILE"].write_text(json.dumps({
                "plugins": {"skill-concierge@skill-concierge": [
                    {"scope": "user", "installPath": str(install_dir), "version": "0.0.1"}]}}))
            row = check_claude_code()
            assert row["status"] == WARN and "missing" in row["detail"] and row["version"] == cc_ssot, row
            # Unreadable content: the record's version is a claim, so `version` is None and the row
            # names the problem; with no installPath it does not claim a launcher either.
            (install_dir / ".claude-plugin" / "plugin.json").unlink()
            row = check_claude_code()
            assert row["status"] == WARN and "unreadable" in row["detail"] and row["version"] is None, row
            _g["CLAUDE_PLUGINS_FILE"].write_text(json.dumps({
                "plugins": {"skill-concierge@skill-concierge": [{"scope": "user", "version": cc_ssot}]}}))
            row = check_claude_code()
            assert (row["status"] == WARN and "no installPath" in row["detail"] and row["version"] is None
                    and "launcher" not in row["detail"]), row
    finally:
        _g.update(_saved_cc)

    # --- ZCode harness check: fixture-driven, never touches the real ~/.zcode ---
    _saved_zc = {k: _g[k] for k in ("ZCODE_DIR", "ZCODE_PLUGIN_CACHE", "ZCODE_PLUGINS_FILE")}
    try:
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            _g["ZCODE_DIR"] = base / ".zcode"
            _g["ZCODE_PLUGIN_CACHE"] = base / ".zcode" / "cli" / "plugins" / "cache" / "skill-concierge" / "skill-concierge"
            _g["ZCODE_PLUGINS_FILE"] = base / ".zcode" / "cli" / "plugins" / "installed_plugins.json"
            zc_ssot = _descriptor_version(ROOT / ".claude-plugin" / "plugin.json")
            (_g["ZCODE_PLUGIN_CACHE"] / zc_ssot / "bin").mkdir(parents=True)
            launcher = _g["ZCODE_PLUGIN_CACHE"] / zc_ssot / "bin" / "skill-search-mcp"
            launcher.write_text("#!/bin/sh\n")
            launcher.chmod(0o755)
            row = check_zcode()
            assert row["status"] == OK, row
            launcher.unlink()
            row = check_zcode()
            assert row["status"] == WARN and "missing" in row["detail"], row
    finally:
        _g.update(_saved_zc)

    # --- Command Code harness check (ADR-0038): fixture-driven, never touches the real ~/.commandcode ---
    # Two outcomes: absent CC -> WARN "not installed"; all surface present -> OK.
    _saved_ccmd = {k: _g[k] for k in ("CCMD_DIR", "CCMD_MOD", "CCMD_SETTINGS", "CCMD_MCP",
                                      "_CCMD_SETTINGS_HOOK_MARKER", "CCMD_SKILLS_ROOTS")}
    try:
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            _g["CCMD_DIR"] = base / ".commandcode"
            _g["CCMD_MOD"] = _g["CCMD_DIR"] / "mods" / "skill-concierge.ts"
            _g["CCMD_SETTINGS"] = _g["CCMD_DIR"] / "settings.json"
            _g["CCMD_MCP"] = _g["CCMD_DIR"] / "mcp.json"
            # Command Code absent entirely -> WARN "commandcode: not installed", never FAIL.
            row = check_commandcode()
            assert row["status"] == WARN and "not installed" in row["detail"], row
            # Fully present: mod + hooks + MCP all wired.
            _g["CCMD_DIR"].mkdir(parents=True)
            (_g["CCMD_DIR"] / "mods").mkdir()
            _mod_src = ROOT / "adapters" / "commandcode" / "skill-concierge.mod.ts"
            _g["CCMD_MOD"].write_bytes(_mod_src.read_bytes())   # an installed copy == the repo adapter
            _g["CCMD_SETTINGS"].write_text(json.dumps({
                "hooks": {
                    "PreToolUse": [{"hooks": []}],
                    "SessionStart": [{
                        "hooks": [{"type": "command", "command": "python3 /path/to/skill-concierge/hooks/scripts/doctrine.py"}]
                    }]
                }}))
            _g["CCMD_MCP"].write_text(json.dumps({
                "mcpServers": {"skill-search": {"command": "/path/to/bin/skill-search-mcp"}}
            }))
            row = check_commandcode()
            assert row["status"] == OK, row
            # Negative control: a stale copy of the mod (the installer COPIES it) -> WARN naming it.
            _g["CCMD_MOD"].write_text("export default function(cmd) { /* an older mod */ }")
            row = check_commandcode()
            assert row["status"] == WARN and "stale copy" in row["detail"], row
            _g["CCMD_MOD"].write_bytes(_mod_src.read_bytes())
            # Negative control: an event outside CC's four (PreCompact is what the palate
            # writer copies in from Claude) -> WARN naming it.
            _g["CCMD_SETTINGS"].write_text(json.dumps({
                "hooks": {
                    "PreToolUse": [{"hooks": []}],
                    "PreCompact": [{"hooks": [{"type": "command", "command": "palate hook pre-compact"}]}],
                    "SessionStart": [{
                        "hooks": [{"type": "command", "command": "python3 /path/to/skill-concierge/hooks/scripts/doctrine.py"}]
                    }]
                }}))
            row = check_commandcode()
            assert row["status"] == WARN and "PreCompact" in row["detail"], row
            _g["CCMD_SETTINGS"].write_text(json.dumps({
                "hooks": {
                    "PreToolUse": [{"hooks": []}],
                    "SessionStart": [{
                        "hooks": [{"type": "command", "command": "python3 /path/to/skill-concierge/hooks/scripts/doctrine.py"}]
                    }]
                }}))
            # Negative control: a stray root-level SKILL.md under a CC-readable skills root
            # -> WARN naming the path. Same root without it stays OK.
            _g["CCMD_SKILLS_ROOTS"] = (_g["CCMD_DIR"] / "skills",)
            skills_root = _g["CCMD_SKILLS_ROOTS"][0]
            (skills_root / "session-handoff").mkdir(parents=True)
            (skills_root / "session-handoff" / "SKILL.md").write_text("---\nname: session-handoff\n---\n")
            row = check_commandcode()
            assert row["status"] == OK, row
            (skills_root / "SKILL.md").write_text("---\nname: session-handoff\n---\n")
            row = check_commandcode()
            assert row["status"] == WARN and "stray" in row["detail"] and "SKILL.md" in row["detail"], row
            (skills_root / "SKILL.md").unlink()
            row = check_commandcode()
            assert row["status"] == OK, row
    finally:
        _g.update(_saved_ccmd)
    # DSH patch-file shapes DSH cannot load (both shipped before 0.49.0) vs the fixed shape.
    _broken = "# header\n[]\n# skill-concierge skill-search MCP server\n- id: skill-concierge\n  name: x\n"
    _bd = " | ".join(_dsh_patch_defects(_broken))
    assert "bare `[]`" in _bd and "not wrapped in `- insert:`" in _bd, _bd
    _fixed = ("# header\n# skill-concierge skill-search MCP server\n- insert:\n    - id: skill-concierge\n"
              "      name: x\n- insert:\n    - id: skill-concierge-enforcer\n      name: y\n"
              "- id: operator-thing\n  config:\n    args:\n      []\n")   # an indented [] is a value
    assert _dsh_patch_defects(_fixed) == [], _dsh_patch_defects(_fixed)
    assert any("enforcement plugin" in d for d in _dsh_patch_defects(_fixed.replace("skill-concierge-enforcer", "x")))
    assert any(getattr(fn, "__name__", "") == "check_codex" for fn in CHECKS)
    assert any(getattr(fn, "__name__", "") == "check_commandcode" for fn in CHECKS)
    assert any(getattr(fn, "__name__", "") == "check_omp" for fn in CHECKS)
    assert any(getattr(fn, "__name__", "") == "check_claude_code" for fn in CHECKS)
    print("selftest ok")
    return 0
