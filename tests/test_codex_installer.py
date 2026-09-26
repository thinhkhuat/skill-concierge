"""adapters/codex/install.sh must sync an existing Codex registration. Codex has no
local install-record file (unlike OMP/ZCode) and no `codex plugin upgrade` verb — the
canonical sequence is `marketplace upgrade` -> `remove` -> `add`. When a version gap is
left over after that sequence (the marketplace is a GIT source: the CLI installs what
is PUSHED to the remote, never this checkout), the installer falls back to exporting
this checkout straight into the versioned Codex cache dir — proven live in a sandboxed
CODEX_HOME with the real `codex` binary (see the orchestration report's "Fallback
probe" section) to be exactly what `codex plugin list --json` re-scans and reports,
with zero registry to repoint. These tests run against a FAKE `codex` executable
placed first on PATH — the real binary is never invoked; the fallback's own
`git archive HEAD` still reads this actual repo checkout (read-only) but writes only
into the sandboxed $HOME."""
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "adapters" / "codex" / "install.sh"
ENFORCER_SRC = ROOT / "hooks" / "scripts" / "enforcer.py"
SSOT_VERSION = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())["version"]

FAKE_CODEX = '''#!/usr/bin/env python3
"""Fake `codex` CLI: records every invocation, simulates the plugin cache effects
`marketplace list/upgrade` and `plugin list/add/remove` have on a real Codex install,
driven by a small JSON state file under $HOME so each test controls the scenario."""
import json
import os
import shutil
import sys
from pathlib import Path

HOME = Path(os.environ["HOME"])
STATE_PATH = HOME / ".codex-test-state.json"
LOG_PATH = HOME / ".codex-test-log.jsonl"
CACHE_BASE = HOME / ".codex" / "plugins" / "cache" / "skill-concierge" / "skill-concierge"
ENFORCER_SRC = Path(os.environ["FAKE_CODEX_ENFORCER_SRC"])


def _state():
    return json.loads(STATE_PATH.read_text())


def _save(s):
    STATE_PATH.write_text(json.dumps(s))


def _log(argv):
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"argv": argv}) + "\\n")


def main():
    argv = sys.argv[1:]
    _log(argv)
    if not argv or argv[0] != "plugin":
        print("fake codex: unsupported invocation", file=sys.stderr)
        sys.exit(2)
    sub = argv[1] if len(argv) > 1 else ""
    state = _state()

    if sub == "marketplace":
        sub2 = argv[2] if len(argv) > 2 else ""
        if sub2 == "list":
            mkts = []
            if state.get("marketplace_registered"):
                mkts.append({"name": "skill-concierge",
                             "root": str(HOME / ".codex" / ".tmp" / "marketplaces" / "skill-concierge"),
                             "marketplaceSource": {"sourceType": "git",
                                                    "source": "https://example.invalid/skill-concierge.git"}})
            print(json.dumps({"marketplaces": mkts}))
            sys.exit(0)
        if sub2 == "upgrade":
            sys.exit(1 if state.get("fail_upgrade") else 0)
        print("fake codex: unsupported marketplace subcommand", file=sys.stderr)
        sys.exit(2)

    if sub == "list":
        installed = []
        if state.get("plugin_installed"):
            installed.append({"pluginId": "skill-concierge@skill-concierge", "name": "skill-concierge",
                               "marketplaceName": "skill-concierge", "version": state["remote_version"],
                               "installed": True, "enabled": True})
        print(json.dumps({"installed": installed}))
        sys.exit(0)

    if sub == "remove":
        if state.get("fail_remove"):
            sys.exit(1)
        state["plugin_installed"] = False
        _save(state)
        if CACHE_BASE.is_dir():
            shutil.rmtree(CACHE_BASE)
        sys.exit(0)

    if sub == "add":
        if state.get("fail_add"):
            sys.exit(1)
        version = state["remote_version"]
        dest = CACHE_BASE / version
        if dest.exists():
            shutil.rmtree(dest)
        (dest / ".codex-plugin").mkdir(parents=True)
        (dest / ".codex-plugin" / "plugin.json").write_text(
            json.dumps({"name": "skill-concierge", "version": version}))
        (dest / ".codex-plugin" / "mcp.json").write_text("{}")
        (dest / ".codex").mkdir()
        (dest / ".codex" / "hooks.json").write_text("{}")
        (dest / "skills").mkdir()
        (dest / "bin").mkdir()
        launcher = dest / "bin" / "skill-search-mcp"
        launcher.write_text("#!/bin/bash\\necho fake\\n")
        # Deliberately NOT chmod +x here: the installer must ensure the exec bit itself,
        # the same class of self-heal ZCode's cache needed.
        (dest / "hooks" / "scripts").mkdir(parents=True)
        shutil.copy2(ENFORCER_SRC, dest / "hooks" / "scripts" / "enforcer.py")
        state["plugin_installed"] = True
        _save(state)
        sys.exit(0)

    print("fake codex: unsupported plugin subcommand", file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
'''


def _make_home(tmp_path, state):
    home = tmp_path / "home"
    (home / ".codex" / "plugins" / "cache").mkdir(parents=True)
    (home / ".codex-test-state.json").write_text(json.dumps(state))
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    codex_path = fakebin / "codex"
    codex_path.write_text(FAKE_CODEX)
    codex_path.chmod(codex_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    # The installer's verify step runs doctor.py, and doctor shells out to `claude mcp list`.
    # A silent stub keeps the real Claude Code binary out of every test run.
    claude_path = fakebin / "claude"
    claude_path.write_text("#!/bin/sh\nexit 0\n")
    claude_path.chmod(claude_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return home, fakebin


def _env(home, fakebin):
    return dict(
        os.environ,
        HOME=str(home),
        PATH=str(fakebin) + os.pathsep + os.environ.get("PATH", ""),
        FAKE_CODEX_ENFORCER_SRC=str(ENFORCER_SRC),
    )


def _run(env):
    return subprocess.run(["bash", str(INSTALLER)], env=env, capture_output=True, text=True, timeout=60)


def _log_lines(home):
    log = home / ".codex-test-log.jsonl"
    if not log.exists():
        return []
    return [json.loads(l) for l in log.read_text().splitlines() if l.strip()]


def test_fresh_install_reaches_ssot_and_fixes_exec_bit(tmp_path):
    home, fakebin = _make_home(tmp_path, {
        "marketplace_registered": True,
        "plugin_installed": False,
        "remote_version": SSOT_VERSION,
    })
    env = _env(home, fakebin)
    result = _run(env)
    assert result.returncode == 0, result.stdout + result.stderr

    dest = home / ".codex" / "plugins" / "cache" / "skill-concierge" / "skill-concierge" / SSOT_VERSION
    assert json.loads((dest / ".codex-plugin" / "plugin.json").read_text())["version"] == SSOT_VERSION
    launcher = dest / "bin" / "skill-search-mcp"
    assert os.access(launcher, os.X_OK), "installer must chmod +x the launcher"
    assert not (home / ".codex" / "config.toml").exists(), "installer must never write config.toml directly"

    argvs = [l["argv"] for l in _log_lines(home)]
    assert ["plugin", "marketplace", "upgrade", "skill-concierge"] in argvs
    assert ["plugin", "add", "skill-concierge@skill-concierge"] in argvs
    assert ["plugin", "remove", "skill-concierge@skill-concierge"] not in argvs, \
        "nothing was installed yet — remove must not be called"


def test_second_run_is_a_no_op_fast_path(tmp_path):
    home, fakebin = _make_home(tmp_path, {
        "marketplace_registered": True,
        "plugin_installed": False,
        "remote_version": SSOT_VERSION,
    })
    env = _env(home, fakebin)
    first = _run(env)
    assert first.returncode == 0, first.stdout + first.stderr

    (home / ".codex-test-log.jsonl").unlink()
    second = _run(env)
    assert second.returncode == 0, second.stdout + second.stderr
    assert _log_lines(home) == [], "fast path must not call the codex CLI at all"


def test_stale_remote_falls_back_to_local_checkout_sync_without_deleting_old_dir(tmp_path):
    """Proven live (sandboxed CODEX_HOME + real codex binary, see the orchestration
    report): Codex keeps no registry, so `codex plugin list --json` re-scans the cache
    dir tree on every call, resolving the newest dir by semver. A version-named dir
    dropped straight into it via `git archive HEAD` is picked up with zero further CLI
    involvement — and the SAME probe proved a stale sibling dir is simply never
    resolved as current, so this installer must NEVER delete one: no sibling installer
    deletes anything, nothing here can back up a directory before removing it, and a
    running Codex session could be using the old dir right now."""
    # Two DIFFERENT stale versions: one the fake CLI's `add` will (re)create at
    # remote_version, and an OLDER one it never touches at all — isolating "my
    # installer's own fallback never deletes" from "the CLI naturally overwrites the
    # exact version dir it (re)installs," which is not this installer's concern.
    untouched_version = "0.1.0"
    remote_version = "0.45.0"
    assert untouched_version != SSOT_VERSION and remote_version != SSOT_VERSION
    home, fakebin = _make_home(tmp_path, {
        "marketplace_registered": True,
        "plugin_installed": False,  # no `remove` call — the pre-seeded dir is untouched by the CLI step
        "remote_version": remote_version,
    })
    # Pre-seed a cache dir at an unrelated old version, as if installed long ago.
    dest = home / ".codex" / "plugins" / "cache" / "skill-concierge" / "skill-concierge" / untouched_version
    (dest / ".codex-plugin").mkdir(parents=True)
    (dest / ".codex-plugin" / "plugin.json").write_text(json.dumps({"version": untouched_version}))
    (dest / "skills").mkdir()
    marker = dest / "skills" / "marker.txt"
    marker.write_text("pre-existing content that must survive")

    env = _env(home, fakebin)
    result = _run(env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "deploys the LOCAL checkout DIRECTLY" in result.stderr
    assert "not" in result.stderr and "pushed" in result.stderr

    cache_root = home / ".codex" / "plugins" / "cache" / "skill-concierge" / "skill-concierge"
    versions = {d.name for d in cache_root.iterdir() if d.is_dir()}
    assert versions == {untouched_version, remote_version, SSOT_VERSION}, \
        "every old version dir must survive, untouched, alongside the new one"
    assert marker.read_text() == "pre-existing content that must survive", "the old dir's content must be untouched"

    ssot_dest = cache_root / SSOT_VERSION
    assert json.loads((ssot_dest / ".codex-plugin" / "plugin.json").read_text())["version"] == SSOT_VERSION
    assert (ssot_dest / "AGENTS.md").exists(), "git archive HEAD must have populated the real checkout"
    assert not (ssot_dest / ".git").exists(), "git archive HEAD never includes .git itself"
    assert os.access(ssot_dest / "bin" / "skill-search-mcp", os.X_OK)


def test_add_failure_still_falls_back_to_local_checkout_sync(tmp_path):
    """Codex's own remove-then-add sequence (per --help: "remove" "removes its local
    cache") can leave the cache dir gone entirely before `add` fails — the fallback must
    still reach the SSOT even from nothing on disk."""
    home, fakebin = _make_home(tmp_path, {
        "marketplace_registered": True,
        "plugin_installed": True,
        "remote_version": "0.45.0",
        "fail_add": True,
    })
    env = _env(home, fakebin)
    result = _run(env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "deploys the LOCAL checkout DIRECTLY" in result.stderr

    cache_root = home / ".codex" / "plugins" / "cache" / "skill-concierge" / "skill-concierge"
    assert {d.name for d in cache_root.iterdir() if d.is_dir()} == {SSOT_VERSION}


def test_non_version_staging_dir_is_left_alone(tmp_path):
    """Codex itself creates non-version-named staging dirs under this cache tree from
    an interrupted install (the real machine carries a live plugin-install-UEVanZ/
    leftover, documented in the scout report). Neither the fallback nor
    _cached_version() may treat a dir shaped like "plugin-install-XYZ" as a version —
    and, since the fallback never deletes anything at all, it must survive untouched."""
    stale_version = "0.45.0"
    assert stale_version != SSOT_VERSION
    home, fakebin = _make_home(tmp_path, {
        "marketplace_registered": True,
        "plugin_installed": False,
        "remote_version": stale_version,
    })
    cache_root = home / ".codex" / "plugins" / "cache" / "skill-concierge" / "skill-concierge"
    # A non-version-shaped dir sitting alongside the version dirs, same shape a stale
    # `_ver_gt`-based glob (a first-pass draft of this script had one) would have
    # matched and mis-sorted (its "version" tuple decodes to all -1s: neither newer
    # nor older than anything, by design of ver_key's fallback).
    staging = cache_root / "plugin-install-XYZ"
    staging.mkdir(parents=True)
    (staging / "marker.txt").write_text("codex-owned staging content")

    env = _env(home, fakebin)
    result = _run(env)
    assert result.returncode == 0, result.stdout + result.stderr

    assert (staging / "marker.txt").read_text() == "codex-owned staging content", \
        "a non-version-named sibling dir must never be touched, let alone deleted"
    versions = {d.name for d in cache_root.iterdir() if d.is_dir()}
    assert versions == {stale_version, SSOT_VERSION, "plugin-install-XYZ"}


def test_downgrade_after_cli_refresh_is_refused(tmp_path):
    """The one-directional guard must re-apply AFTER the CLI refresh too: the refresh
    itself could install something newer than this checkout (a teammate pushed ahead)."""
    newer_version = "99.0.0"
    assert newer_version != SSOT_VERSION
    home, fakebin = _make_home(tmp_path, {
        "marketplace_registered": True,
        "plugin_installed": False,
        "remote_version": newer_version,
    })
    env = _env(home, fakebin)
    result = _run(env)
    assert result.returncode != 0, result.stdout + result.stderr
    assert "refusing to downgrade" in result.stderr
    assert "after the CLI refresh" in result.stderr

    cache_root = home / ".codex" / "plugins" / "cache" / "skill-concierge" / "skill-concierge"
    assert not (cache_root / SSOT_VERSION).exists(), "no local-checkout sync must be attempted on a downgrade"


def test_cached_version_sort_is_semver_not_lexical(tmp_path):
    """Proven live: with cache dirs "0.9.0" and "0.52.3" both present, the real `codex
    plugin list --json` reports "0.52.3" (semver-aware), while a naive lexical-string
    sort — scripts/doctor.py's own _codex_cached_version() — ranks "0.9.0" higher
    ('9' > '5' at the first differing character). This installer's _cached_version()
    must resolve the fast path correctly regardless of a stray lower-digit-width dir."""
    home, fakebin = _make_home(tmp_path, {
        "marketplace_registered": True,
        "plugin_installed": True,
        "remote_version": SSOT_VERSION,
    })
    cache_root = home / ".codex" / "plugins" / "cache" / "skill-concierge" / "skill-concierge"
    low = cache_root / "0.9.0"
    (low / ".codex-plugin").mkdir(parents=True)
    (low / ".codex-plugin" / "plugin.json").write_text(json.dumps({"version": "0.9.0"}))
    (low / "skills").mkdir()

    current = cache_root / SSOT_VERSION
    (current / ".codex-plugin").mkdir(parents=True)
    (current / ".codex-plugin" / "plugin.json").write_text(json.dumps({"version": SSOT_VERSION}))
    (current / "skills").mkdir()
    (current / "bin").mkdir()
    (current / "bin" / "skill-search-mcp").write_text("#!/bin/bash\necho fake\n")
    (current / "bin" / "skill-search-mcp").chmod(0o755)
    (current / ".codex-plugin" / "mcp.json").write_text("{}")
    (current / ".codex").mkdir()
    (current / ".codex" / "hooks.json").write_text("{}")
    (current / "hooks" / "scripts").mkdir(parents=True)
    shutil.copy2(ENFORCER_SRC, current / "hooks" / "scripts" / "enforcer.py")

    env = _env(home, fakebin)
    result = _run(env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Already current" in result.stdout, \
        "a lexical-string sort would misidentify 0.9.0 as newest and skip the fast path"
    assert _log_lines(home) == [], "the fast path must not call the codex CLI at all"


def test_downgrade_is_refused_before_any_codex_call(tmp_path):
    newer_version = "9.9.9"
    home, fakebin = _make_home(tmp_path, {
        "marketplace_registered": True,
        "plugin_installed": True,
        "remote_version": newer_version,
    })
    dest = home / ".codex" / "plugins" / "cache" / "skill-concierge" / "skill-concierge" / newer_version
    (dest / ".codex-plugin").mkdir(parents=True)
    (dest / ".codex-plugin" / "plugin.json").write_text(json.dumps({"version": newer_version}))
    (dest / "skills").mkdir()

    env = _env(home, fakebin)
    result = _run(env)
    assert result.returncode != 0, result.stdout + result.stderr
    assert "refusing to downgrade" in result.stderr
    assert _log_lines(home) == [], "the downgrade guard must fire before any codex CLI call"
    assert json.loads((dest / ".codex-plugin" / "plugin.json").read_text())["version"] == newer_version


def test_marketplace_not_registered_prints_bootstrap_instructions(tmp_path):
    home, fakebin = _make_home(tmp_path, {
        "marketplace_registered": False,
        "plugin_installed": False,
        "remote_version": SSOT_VERSION,
    })
    env = _env(home, fakebin)
    result = _run(env)
    assert result.returncode != 0, result.stdout + result.stderr
    assert "codex plugin marketplace add" in result.stderr
    assert "codex plugin add skill-concierge@skill-concierge" in result.stderr

    argvs = [l["argv"] for l in _log_lines(home)]
    assert ["plugin", "marketplace", "upgrade", "skill-concierge"] not in argvs
    assert ["plugin", "add", "skill-concierge@skill-concierge"] not in argvs
    cache_root = home / ".codex" / "plugins" / "cache" / "skill-concierge" / "skill-concierge"
    assert not cache_root.is_dir() or not any(cache_root.iterdir())


def test_unknown_flag_prints_usage_and_exits_1(tmp_path):
    home, fakebin = _make_home(tmp_path, {
        "marketplace_registered": True,
        "plugin_installed": False,
        "remote_version": SSOT_VERSION,
    })
    env = _env(home, fakebin)
    result = subprocess.run(["bash", str(INSTALLER), "--bogus"], env=env,
                             capture_output=True, text=True, timeout=60)
    assert result.returncode == 1
    assert "usage:" in result.stderr


def test_root_flag_reads_ssot_from_the_given_path(tmp_path):
    # A second checkout, elsewhere, with its own plugin.json.
    alt_root = tmp_path / "alt-checkout"
    shutil.copytree(ROOT / ".claude-plugin", alt_root / ".claude-plugin")
    (alt_root / "hooks" / "scripts").mkdir(parents=True)
    shutil.copy2(ENFORCER_SRC, alt_root / "hooks" / "scripts" / "enforcer.py")
    alt_version = "1.2.3"
    (alt_root / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": alt_version}))

    home, fakebin = _make_home(tmp_path, {
        "marketplace_registered": True,
        "plugin_installed": False,
        "remote_version": alt_version,
    })
    env = _env(home, fakebin)
    result = subprocess.run(["bash", str(INSTALLER), "--root", str(alt_root)], env=env,
                             capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"SSOT version: v{alt_version}" in result.stdout
