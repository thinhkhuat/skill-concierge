"""adapters/codex/install.sh must sync an existing Codex registration. Codex has no
local install-record file (unlike OMP/ZCode) and no `codex plugin upgrade` verb — the
canonical sequence is `marketplace upgrade` -> `add`, NEVER `remove`: a bare `add`
refreshes an already-installed plugin in place, a FAILED `add` never uninstalls the
previous copy, and a SUCCESSFUL `add` unconditionally wipes the plugin's entire cache
directory (every version dir and every non-version staging dir) before installing the
fresh one — first install or refresh alike. When a version gap is left over after `add` succeeds (the
marketplace is a GIT source: the CLI installs what is PUSHED to the remote, never this
checkout), the installer falls back to exporting this checkout straight into a NEW
versioned Codex cache dir, which `codex plugin list --json` re-scans with zero further
CLI involvement (no registry to repoint).

These tests run against a FAKE `codex` executable placed first on PATH — the real binary
is never invoked; the fallback's own `git archive HEAD` still reads this actual repo
checkout (read-only) but writes only into the sandboxed $HOME."""
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
                               "installed": True, "enabled": bool(state.get("enabled", True))})
        print(json.dumps({"installed": installed}))
        sys.exit(0)

    if sub == "remove":
        # Real Codex: deletes the plugin's whole cache tree AND its config entry. This
        # installer never calls it (see its header) — modeled here in case a test wants to
        # simulate a manual removal done before the installer even runs.
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
        if state.get("add_noop"):
            sys.exit(0)   # reports success but installs nothing
        version = state["remote_version"]
        # Real Codex: `add` unconditionally wipes the ENTIRE plugin cache dir — every
        # version dir, every non-version staging dir — before installing the fresh
        # version, first install or refresh of an existing one alike.
        if CACHE_BASE.is_dir():
            shutil.rmtree(CACHE_BASE)
        dest = CACHE_BASE / version
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
        state["enabled"] = True  # `add` always (re-)enables — Codex has no CLI to keep it off
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
    # doctor falls back to `docker ps` when Qdrant does not answer: keep the real one out too.
    docker_path = fakebin / "docker"
    docker_path.write_text("#!/bin/sh\nexit 1\n")
    docker_path.chmod(docker_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return home, fakebin


def _env(home, fakebin):
    return dict(
        os.environ,
        HOME=str(home),
        PATH=str(fakebin) + os.pathsep + os.environ.get("PATH", ""),
        FAKE_CODEX_ENFORCER_SRC=str(ENFORCER_SRC),
        SKILL_QDRANT_URL="http://127.0.0.1:9",   # the verify step's doctor never reaches live Qdrant
    )


def _run(env, *extra_args):
    return subprocess.run(["bash", str(INSTALLER), *extra_args], env=env,
                           capture_output=True, text=True, timeout=60)


def _log_lines(home):
    log = home / ".codex-test-log.jsonl"
    if not log.exists():
        return []
    return [json.loads(l) for l in log.read_text().splitlines() if l.strip()]


def _cache_root(home):
    return home / ".codex" / "plugins" / "cache" / "skill-concierge" / "skill-concierge"


def test_fresh_install_reaches_ssot_and_fixes_exec_bit(tmp_path):
    home, fakebin = _make_home(tmp_path, {
        "marketplace_registered": True,
        "plugin_installed": False,
        "remote_version": SSOT_VERSION,
    })
    env = _env(home, fakebin)
    result = _run(env)
    assert result.returncode == 0, result.stdout + result.stderr

    dest = _cache_root(home) / SSOT_VERSION
    assert json.loads((dest / ".codex-plugin" / "plugin.json").read_text())["version"] == SSOT_VERSION
    launcher = dest / "bin" / "skill-search-mcp"
    assert os.access(launcher, os.X_OK), "installer must chmod +x the launcher"
    assert not (home / ".codex" / "config.toml").exists(), "installer must never write config.toml directly"

    argvs = [l["argv"] for l in _log_lines(home)]
    assert ["plugin", "marketplace", "upgrade", "skill-concierge"] in argvs
    assert ["plugin", "add", "skill-concierge@skill-concierge"] in argvs
    assert ["plugin", "remove", "skill-concierge@skill-concierge"] not in argvs, \
        "this installer must never call 'codex plugin remove'"


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
    assert [l["argv"] for l in _log_lines(home)] == [["plugin", "list", "--json"]], \
        "the fast path makes only the read-only registry check"


def test_fast_path_tolerates_lexically_smaller_and_non_version_siblings(tmp_path):
    """With cache dirs "0.9.0" and "0.52.3" both present, the real `codex
    plugin list --json` reports "0.52.3" (semver-aware), while a naive lexical-string
    sort ranks "0.9.0" higher ('9' > '5' at the first differing character). This
    installer's _cached_version() must resolve the fast path correctly regardless of a
    stray lower-digit-width dir, and must never mistake a non-version-named staging dir
    (Codex keeps its plugin-install-<random>/ one level up; the fixture puts one here to
    prove the dirname filter) for a version. The
    fast path calls no CLI at all, so every sibling here survives untouched no matter what
    Codex's own `add` might otherwise do to them."""
    home, fakebin = _make_home(tmp_path, {
        "marketplace_registered": True,
        "plugin_installed": True,
        "remote_version": SSOT_VERSION,
    })
    cache_root = _cache_root(home)

    low = cache_root / "0.9.0"
    (low / ".codex-plugin").mkdir(parents=True)
    (low / ".codex-plugin" / "plugin.json").write_text(json.dumps({"version": "0.9.0"}))
    (low / "skills").mkdir()

    staging = cache_root / "plugin-install-XYZ"
    staging.mkdir(parents=True)
    (staging / "marker.txt").write_text("codex-owned staging content")

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
    assert [l["argv"] for l in _log_lines(home)] == [["plugin", "list", "--json"]], \
        "the fast path makes only the read-only registry check"
    assert (staging / "marker.txt").read_text() == "codex-owned staging content"
    assert (low / ".codex-plugin" / "plugin.json").exists()


def test_fallback_never_deletes_the_version_dir_add_just_created(tmp_path):
    """The fallback runs only AFTER `add` already succeeded (see header step 6-7) — and
    Codex's own `add` wipes the plugin's entire cache dir before installing its own
    version dir. So the only thing that can be sitting there when the
    fallback starts is the dir `add` itself just created; this installer's OWN fallback
    step (git archive HEAD -> a NEW versioned dir) must never delete that, only add
    alongside it — no sibling installer deletes anything, and a running Codex session
    could be using that dir right now."""
    remote_version = "0.45.0"
    assert remote_version != SSOT_VERSION
    home, fakebin = _make_home(tmp_path, {
        "marketplace_registered": True,
        "plugin_installed": False,
        "remote_version": remote_version,
    })
    env = _env(home, fakebin)
    result = _run(env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "deploys the LOCAL checkout DIRECTLY" in result.stderr

    cache_root = _cache_root(home)
    versions = {d.name for d in cache_root.iterdir() if d.is_dir()}
    assert versions == {remote_version, SSOT_VERSION}, \
        "the version dir 'add' just created must survive the fallback, alongside the new one"

    ssot_dest = cache_root / SSOT_VERSION
    assert json.loads((ssot_dest / ".codex-plugin" / "plugin.json").read_text())["version"] == SSOT_VERSION
    assert (ssot_dest / "AGENTS.md").exists(), "git archive HEAD must have populated the real checkout"
    assert not (ssot_dest / ".git").exists(), "git archive HEAD never includes .git itself"
    assert os.access(ssot_dest / "bin" / "skill-search-mcp", os.X_OK)

    argvs = [l["argv"] for l in _log_lines(home)]
    assert ["plugin", "remove", "skill-concierge@skill-concierge"] not in argvs


def test_add_failure_never_falls_back_and_exits_nonzero(tmp_path):
    """A failed `codex plugin add` must never trigger the manual-checkout fallback: Codex's
    own `add` never uninstalls the previous copy on failure, so this
    installer trusts that and reports the failure with restore steps rather than syncing a
    local checkout over a state it cannot fully verify."""
    home, fakebin = _make_home(tmp_path, {
        "marketplace_registered": True,
        "plugin_installed": True,
        "remote_version": "0.45.0",
        "fail_add": True,
    })
    env = _env(home, fakebin)
    result = _run(env)
    assert result.returncode != 0, result.stdout + result.stderr
    combined = result.stdout + result.stderr
    assert "does not report" in combined and "installed" in combined
    assert "previous install should still be intact" in combined
    assert "codex plugin list --json" in combined

    cache_root = _cache_root(home)
    assert not cache_root.is_dir() or not any(d.name == SSOT_VERSION for d in cache_root.iterdir() if d.is_dir()), \
        "no local-checkout sync must be attempted after a failed add"

    argvs = [l["argv"] for l in _log_lines(home)]
    assert ["plugin", "remove", "skill-concierge@skill-concierge"] not in argvs


def test_disabled_plugin_refuses_before_any_cli_call(tmp_path):
    """Codex's `add` always re-enables a plugin and has no CLI to keep one disabled (no
    plugin enable/disable subcommand, and a `-c ...enabled=false` override does not
    persist). If the plugin is already disabled, the installer must refuse before making
    any mutating CLI call at all — never refresh it first and complain afterward."""
    home, fakebin = _make_home(tmp_path, {
        "marketplace_registered": True,
        "plugin_installed": True,
        "remote_version": "0.1.0",
        "enabled": False,
    })
    config_toml = home / ".codex" / "config.toml"
    config_toml.parent.mkdir(parents=True, exist_ok=True)
    config_toml.write_text('[plugins."skill-concierge@skill-concierge"]\nenabled = false\n')
    before = config_toml.read_bytes()

    env = _env(home, fakebin)
    result = _run(env)
    assert result.returncode != 0, result.stdout + result.stderr
    combined = result.stdout + result.stderr
    assert "is installed but disabled" in combined
    assert "set enabled = true" in combined

    argvs = [l["argv"] for l in _log_lines(home)]
    assert ["plugin", "marketplace", "upgrade", "skill-concierge"] not in argvs, \
        "the guard must fire before 'marketplace upgrade' runs"
    assert ["plugin", "add", "skill-concierge@skill-concierge"] not in argvs, \
        "the guard must fire before 'add' runs"

    state = json.loads((home / ".codex-test-state.json").read_text())
    assert state["enabled"] is False, "'add' never ran, so the plugin stays disabled"
    assert config_toml.read_bytes() == before, "the installer must never touch config.toml itself"


def test_enabled_plugin_stays_enabled_across_a_refresh(tmp_path):
    home, fakebin = _make_home(tmp_path, {
        "marketplace_registered": True,
        "plugin_installed": True,
        "remote_version": SSOT_VERSION,
        "enabled": True,
    })
    env = _env(home, fakebin)
    result = _run(env)
    assert result.returncode == 0, result.stdout + result.stderr
    combined = result.stdout + result.stderr
    assert "is installed but disabled" not in combined
    assert "was disabled before this sync" not in combined


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

    cache_root = _cache_root(home)
    assert not (cache_root / SSOT_VERSION).exists(), "no local-checkout sync must be attempted on a downgrade"


def test_downgrade_is_refused_before_any_codex_call(tmp_path):
    newer_version = "9.9.9"
    home, fakebin = _make_home(tmp_path, {
        "marketplace_registered": True,
        "plugin_installed": True,
        "remote_version": newer_version,
    })
    dest = _cache_root(home) / newer_version
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
    cache_root = _cache_root(home)
    assert not cache_root.is_dir() or not any(cache_root.iterdir())


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
    result = _run(env, "--root", str(alt_root))
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"SSOT version: v{alt_version}" in result.stdout


def _write_plugin_fixture(root, version):
    """The minimal plugin tree the Codex installer's fallback and verify steps expect."""
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": version}))
    (root / ".codex-plugin").mkdir(parents=True)
    (root / ".codex-plugin" / "plugin.json").write_text(
        json.dumps({"name": "skill-concierge", "version": version}))
    (root / ".codex-plugin" / "mcp.json").write_text("{}")
    (root / ".codex").mkdir()
    (root / ".codex" / "hooks.json").write_text("{}")
    (root / "skills").mkdir()
    (root / "skills" / ".gitkeep").write_text("")  # git tracks no empty dirs
    (root / "bin").mkdir()
    launcher = root / "bin" / "skill-search-mcp"
    launcher.write_text("#!/bin/sh\necho fixture\n")
    launcher.chmod(0o755)
    (root / "hooks" / "scripts").mkdir(parents=True)
    shutil.copy2(ENFORCER_SRC, root / "hooks" / "scripts" / "enforcer.py")


def test_git_worktree_export_excludes_untracked_and_ignored_files(tmp_path):
    """A git *worktree*'s `.git` is a FILE, not a directory — `[ -d "$ROOT/.git" ]` would
    misclassify it as a non-git checkout and tar the whole working tree, untracked and
    ignored files included. The check compares `git rev-parse --show-toplevel` with ROOT,
    so a worktree still takes the `git archive HEAD` branch, which only ever exports
    what is committed."""
    base_repo = tmp_path / "base-repo"
    _write_plugin_fixture(base_repo, "7.0.0")
    (base_repo / ".gitignore").write_text("ignored.txt\n")
    subprocess.run(["git", "init", "-q"], cwd=base_repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=base_repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"],
                    cwd=base_repo, check=True)

    worktree = tmp_path / "worktree"
    subprocess.run(["git", "worktree", "add", str(worktree), "HEAD"], cwd=base_repo, check=True,
                    capture_output=True, text=True)
    assert (worktree / ".git").is_file(), "a linked worktree's .git must be a FILE, not a dir"

    (worktree / "untracked.txt").write_text("must never be exported")
    (worktree / "ignored.txt").write_text("must never be exported either")

    home, fakebin = _make_home(tmp_path, {
        "marketplace_registered": True,
        "plugin_installed": False,
        "remote_version": "1.0.0",  # != the worktree's own SSOT -> forces the fallback
    })
    env = _env(home, fakebin)
    result = _run(env, "--root", str(worktree))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "exported HEAD" in result.stdout, "a real git checkout must take the git-archive branch"

    dest = _cache_root(home) / "7.0.0"
    assert dest.is_dir()
    assert (dest / "bin" / "skill-search-mcp").exists()
    assert not (dest / "untracked.txt").exists(), "git archive HEAD must exclude untracked files"
    assert not (dest / "ignored.txt").exists(), "git archive HEAD must exclude gitignored files"
    assert not (dest / ".git").exists()


def test_plain_root_inside_another_repo_copies_only_itself(tmp_path):
    """A non-git ROOT that sits inside an unrelated git repo must NOT take the
    `git archive HEAD` branch: git would export the OUTER repo's committed tree into the
    plugin cache. It takes the working-tree copy instead, and drops tool caches."""
    outer = tmp_path / "outer-repo"
    outer.mkdir()
    (outer / "outer-secret.txt").write_text("belongs to the outer repo")
    subprocess.run(["git", "init", "-q"], cwd=outer, check=True)
    subprocess.run(["git", "add", "-A"], cwd=outer, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"],
                   cwd=outer, check=True)

    root = outer / "plain-checkout"
    _write_plugin_fixture(root, "7.0.0")
    (root / ".pytest_cache").mkdir()
    (root / ".pytest_cache" / "junk").write_text("tool cache")

    home, fakebin = _make_home(tmp_path, {
        "marketplace_registered": True,
        "plugin_installed": False,
        "remote_version": "1.0.0",  # != ROOT's SSOT -> forces the fallback
    })
    result = _run(_env(home, fakebin), "--root", str(root))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "copied the working tree (not a git checkout)" in result.stdout
    assert "exported HEAD" not in result.stdout

    dest = _cache_root(home) / "7.0.0"
    assert (dest / "bin" / "skill-search-mcp").exists()
    assert not (dest / "outer-secret.txt").exists(), "the outer repo's files must never be exported"
    assert not (dest / "plain-checkout").exists()
    assert not (dest / ".pytest_cache").exists(), "tool caches must not be copied"


def _installed_once(tmp_path):
    """A home whose cache is current and complete after one normal run."""
    home, fakebin = _make_home(tmp_path, {"marketplace_registered": True, "plugin_installed": False,
                                          "remote_version": SSOT_VERSION})
    env = _env(home, fakebin)
    assert _run(env).returncode == 0
    (home / ".codex-test-log.jsonl").unlink()
    return home, env


def _set_state(home, **kw):
    path = home / ".codex-test-state.json"
    state = json.loads(path.read_text())
    state.update(kw)
    path.write_text(json.dumps(state))


def test_an_incomplete_cache_is_not_current(tmp_path):
    """A copy with only its manifest and skills (an interrupted export) must not pass as current:
    Codex starts ./bin/skill-search-mcp itself and reads the MCP and hooks files."""
    home, fakebin = _make_home(tmp_path, {"marketplace_registered": True, "plugin_installed": True,
                                          "remote_version": SSOT_VERSION})
    part = _cache_root(home) / SSOT_VERSION
    (part / ".codex-plugin").mkdir(parents=True)
    (part / ".codex-plugin" / "plugin.json").write_text(json.dumps({"name": "skill-concierge",
                                                                     "version": SSOT_VERSION}))
    (part / "skills").mkdir()
    result = _run(_env(home, fakebin))
    assert "Already current" not in result.stdout
    assert result.returncode == 0, result.stdout + result.stderr
    assert (part / ".codex-plugin" / "mcp.json").is_file() and (part / ".codex" / "hooks.json").is_file()


def test_fast_path_reports_a_disabled_plugin_without_claiming_it_loads(tmp_path):
    home, env = _installed_once(tmp_path)
    _set_state(home, enabled=False)
    result = _run(env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "DISABLED" in result.stderr and "stays disabled" in result.stdout
    assert "Restart Codex" not in result.stdout


def test_fast_path_fails_when_codex_does_not_list_the_plugin(tmp_path):
    home, env = _installed_once(tmp_path)
    _set_state(home, plugin_installed=False)
    result = _run(env)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "does not show" in result.stderr


def test_an_add_that_installs_nothing_exits_nonzero(tmp_path):
    home, fakebin = _make_home(tmp_path, {"marketplace_registered": True, "plugin_installed": False,
                                          "remote_version": SSOT_VERSION, "add_noop": True})
    result = _run(_env(home, fakebin))
    assert result.returncode == 1, result.stdout + result.stderr
    assert "does not report" in result.stderr


def test_a_root_with_an_apostrophe_works(tmp_path):
    alt_root = tmp_path / "Thinh's checkout"
    shutil.copytree(ROOT / ".claude-plugin", alt_root / ".claude-plugin")
    (alt_root / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": "1.2.3"}))
    home, fakebin = _make_home(tmp_path, {"marketplace_registered": True, "plugin_installed": False,
                                          "remote_version": "1.2.3"})
    result = _run(_env(home, fakebin), "--root", str(alt_root))
    assert "SyntaxError" not in result.stderr, result.stderr
    assert "SSOT version: v1.2.3" in result.stdout, result.stdout + result.stderr


def test_a_renamed_git_dir_is_refused_before_any_cli_call(tmp_path):
    alt_root = tmp_path / "toggled"
    shutil.copytree(ROOT / ".claude-plugin", alt_root / ".claude-plugin")
    (alt_root / "git").mkdir()
    (alt_root / "git" / "HEAD").write_text("ref: refs/heads/main\n")
    home, fakebin = _make_home(tmp_path, {"marketplace_registered": True, "plugin_installed": False,
                                          "remote_version": "1.0.0"})
    result = _run(_env(home, fakebin), "--root", str(alt_root))
    assert result.returncode == 1 and "git/" in result.stderr, result.stdout + result.stderr
    assert _log_lines(home) == []


def test_a_symlinked_root_still_exports_head(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".claude-plugin").mkdir(parents=True)
    (repo / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": "7.0.0"}))
    (repo / "bin").mkdir()
    (repo / "bin" / "skill-search-mcp").write_text("#!/bin/sh\n")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"],
                   cwd=repo, check=True)
    (repo / "untracked.txt").write_text("never exported")
    link = tmp_path / "link"
    link.symlink_to(repo)
    home, fakebin = _make_home(tmp_path, {"marketplace_registered": True, "plugin_installed": False,
                                          "remote_version": "1.0.0"})
    result = _run(_env(home, fakebin), "--root", str(link))
    assert "exported HEAD" in result.stdout, result.stdout + result.stderr
    assert not (_cache_root(home) / "7.0.0" / "untracked.txt").exists()
