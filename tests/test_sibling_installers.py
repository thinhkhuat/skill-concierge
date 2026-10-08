"""adapters/omp/install.sh and adapters/zcode/install.sh must fail closed the same way
adapters/claude-code/install.sh does: a missing/unreadable manifest falls back instead of
aborting silently under `set -e`, a deployed copy missing its dir OR launcher is repaired
rather than reported "already current", an unreadable git checkout is refused before any
write, a resync is staged (never extracted in place), the OMP registry record is read with a
field separator that survives an empty field, and every registry write repoints only the
record this run read, atomically, with a bounded backup trail. adapters/commandcode/install.sh
must survive a checkout path containing shell metacharacters (an apostrophe, a double quote):
every heredoc that used to splice a shell variable into Python source now passes it as argv.

Each test below is written against whichever adapters/{omp,zcode,commandcode}/install.sh this
file resolves next to (`ROOT = Path(__file__).resolve().parents[1]`) — running it from this
worktree exercises the fix; running the identical file from a scratch clone whose three
installers were replaced with the pre-fix (5e9fe05) content exercises the regression each test
is named for. The two closing tests (Cline, DSH) are smoke coverage for adapters this file does
not own — they are expected to pass unchanged against both the old and the new checkout, since
neither adapter's script differs between the two."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from installer_env import installer_env

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ID = "skill-concierge@skill-concierge"

INSTALL_SH = {
    "omp": ROOT / "adapters" / "omp" / "install.sh",
    "zcode": ROOT / "adapters" / "zcode" / "install.sh",
    "commandcode": ROOT / "adapters" / "commandcode" / "install.sh",
    "dsh": ROOT / "adapters" / "dsh" / "install.sh",
}


# ── Fixture repo (the checkout the installer deploys FROM) ──────────────────────────────────

def _make_repo(tmp_path, name, version):
    """A minimal git-committed checkout: just enough for install.sh's own reads (SSOT version,
    launcher, enforcer) plus a real git history so `git archive HEAD` works."""
    repo = tmp_path / name
    (repo / ".claude-plugin").mkdir(parents=True)
    (repo / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": version}))
    (repo / "bin").mkdir()
    launcher = repo / "bin" / "skill-search-mcp"
    launcher.write_text("#!/bin/sh\necho fixture-launcher\n")
    launcher.chmod(0o755)
    (repo / "hooks" / "scripts").mkdir(parents=True)
    (repo / "hooks" / "scripts" / "enforcer.py").write_text(f"# enforcer fixture v{version}\n")
    setup = repo / "setup.sh"
    setup.write_text("#!/bin/sh\n")
    setup.chmod(0o755)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"],
                    cwd=repo, check=True)
    return repo


# ── OMP home fixtures ────────────────────────────────────────────────────────────────────────

def _seed_omp_home(tmp_path, *, installed_version, install_path, scope="user", project_path="",
                    extra_records=None):
    home = tmp_path / "home"
    plugins_dir = home / ".omp" / "plugins"
    plugins_dir.mkdir(parents=True)
    rec = {"scope": scope, "installPath": str(install_path), "version": installed_version,
           "lastUpdated": "2026-09-01T00:00:00.000Z"}
    if project_path:
        rec["projectPath"] = project_path
    records = [rec] + list(extra_records or [])
    registry = {"plugins": {PLUGIN_ID: records}}
    (plugins_dir / "installed_plugins.json").write_text(json.dumps(registry, indent=2) + "\n")
    return home


def _seed_omp_home_with_cache(tmp_path, *, version, **kw):
    """A registry + a cache dir whose own plugin.json ALSO carries `version` — the common
    "already deployed at some old version" fixture shape."""
    cache_dir = (tmp_path / "home" / ".omp" / "plugins" / "cache" / "plugins" /
                 f"skill-concierge___skill-concierge___{version}")
    home = _seed_omp_home(tmp_path, installed_version=version, install_path=cache_dir, **kw)
    cache_dir.mkdir(parents=True)
    (cache_dir / ".claude-plugin").mkdir()
    (cache_dir / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": version}))
    return home, cache_dir


def _omp_registry(home):
    return json.loads((home / ".omp" / "plugins" / "installed_plugins.json").read_text())


def _run_omp(tmp_path, root, home, *, extra_env=None):
    env = installer_env(tmp_path, home)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(["bash", str(INSTALL_SH["omp"]), "--root", str(root)],
                           env=env, capture_output=True, text=True, timeout=120)


# ── ZCode home fixtures (ZCode has no --root: the installer must live INSIDE the fixture
# repo's own adapters/zcode/, so SCRIPT_DIR/../.. resolves to it) ───────────────────────────

def _seed_zcode_home(tmp_path, *, installed_version, install_path):
    home = tmp_path / "home"
    plugins_dir = home / ".zcode" / "cli" / "plugins"
    plugins_dir.mkdir(parents=True)
    registry = {"plugins": [
        {"id": PLUGIN_ID, "installPath": str(install_path), "version": installed_version,
         "updatedAt": "2026-09-01T00:00:00.000Z"},
        {"id": "some-other@marketplace", "installPath": "/irrelevant", "version": "1.0.0"},
    ]}
    (plugins_dir / "installed_plugins.json").write_text(json.dumps(registry, indent=2) + "\n")
    return home


def _run_zcode(tmp_path, root, home, *extra_args):
    dest = root / "adapters" / "zcode"
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(INSTALL_SH["zcode"], dest / "install.sh")
    (dest / "install.sh").chmod(0o755)
    # SCRIPT_DIR/../lib must resolve inside the fixture the same way it does for the real
    # checkout: adapters/lib/ is a real dependency of install.sh, not test-only scaffolding.
    lib_dest = root / "adapters" / "lib"
    if not lib_dest.exists():
        shutil.copytree(ROOT / "adapters" / "lib", lib_dest)
    env = installer_env(tmp_path, home)
    return subprocess.run(["bash", str(dest / "install.sh"), *extra_args],
                           env=env, capture_output=True, text=True, timeout=120)


# ── Item 1 (OMP): a missing/unreadable install dir must not abort silently ──────────────────

def test_missing_install_dir_falls_back_instead_of_aborting_silently(tmp_path):
    repo = _make_repo(tmp_path, "repo", "2.0.0")
    home = _seed_omp_home(tmp_path, installed_version="1.0.0", install_path=tmp_path / "gone")
    r = _run_omp(tmp_path, repo, home)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "refreshing via omp CLI" in r.stdout, r.stdout + r.stderr
    rec = _omp_registry(home)["plugins"][PLUGIN_ID][0]
    assert rec["version"] == "2.0.0" and Path(rec["installPath"]).is_dir()


# ── Item 2 (OMP): a deployed dir/launcher gap must be repaired, not reported current ────────

def test_a_missing_launcher_at_the_current_version_is_repaired(tmp_path):
    """The old check looked for adapters/omp/skill-concierge.ext.ts, not the MCP launcher itself
    — a cache dir carrying the stub but missing bin/skill-search-mcp was wrongly "already
    current". The fixed check (mirroring claude-code's _current) inspects the launcher."""
    repo = _make_repo(tmp_path, "repo", "2.0.0")
    home, cache = _seed_omp_home_with_cache(tmp_path, version="2.0.0")
    (cache / "adapters" / "omp").mkdir(parents=True)
    (cache / "adapters" / "omp" / "skill-concierge.ext.ts").touch()
    r = _run_omp(tmp_path, repo, home)
    assert r.returncode == 0, r.stdout + r.stderr
    rec = _omp_registry(home)["plugins"][PLUGIN_ID][0]
    dest = Path(rec["installPath"])
    assert (dest / "bin" / "skill-search-mcp").exists()
    assert os.access(dest / "bin" / "skill-search-mcp", os.X_OK)


def test_a_lost_exec_bit_is_repaired_without_a_cli_call(tmp_path):
    repo = _make_repo(tmp_path, "repo", "2.0.0")
    home, cache = _seed_omp_home_with_cache(tmp_path, version="2.0.0")
    shutil.rmtree(cache)
    shutil.copytree(repo, cache, ignore=shutil.ignore_patterns(".git"))
    (cache / "bin" / "skill-search-mcp").chmod(0o644)
    (cache / "adapters" / "omp").mkdir(parents=True)
    (cache / "adapters" / "omp" / "skill-concierge.ext.ts").touch()
    r = _run_omp(tmp_path, repo, home)
    assert r.returncode == 0, r.stdout + r.stderr
    assert os.access(cache / "bin" / "skill-search-mcp", os.X_OK)


# ── Item 3 (OMP + ZCode): refuse a git checkout git cannot read ─────────────────────────────

@pytest.mark.parametrize("harness", ["omp", "zcode"])
def test_refuses_a_git_checkout_git_cannot_read(tmp_path, harness):
    repo = tmp_path / "badrepo"
    (repo / ".claude-plugin").mkdir(parents=True)
    (repo / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": "3.0.0"}))
    (repo / ".git").write_bytes(b"not a real git dir\x00garbage")   # exists, but git can't parse it
    home = tmp_path / "home"
    home.mkdir()
    r = (_run_omp(tmp_path, repo, home) if harness == "omp" else _run_zcode(tmp_path, repo, home))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "git cannot read it" in (r.stdout + r.stderr)
    assert list(home.iterdir()) == [], "must refuse before any write under HOME"


# ── Item 4 (OMP + ZCode): staged export — no stale file survives, old tree kept aside once ──

@pytest.mark.parametrize("harness", ["omp", "zcode"])
def test_export_replaces_the_tree_and_keeps_the_old_one_aside(tmp_path, harness):
    repo = _make_repo(tmp_path, "repo", "2.0.0")
    if harness == "omp":
        home, _old_cache = _seed_omp_home_with_cache(tmp_path, version="1.9.0")
        dest = (tmp_path / "home" / ".omp" / "plugins" / "cache" / "plugins" /
                "skill-concierge___skill-concierge___2.0.0")
        run = lambda: _run_omp(tmp_path, repo, home)
    else:
        home = _seed_zcode_home(tmp_path, installed_version="1.9.0", install_path=tmp_path / "irrelevant")
        dest = (tmp_path / "home" / ".zcode" / "cli" / "plugins" / "cache" /
                "skill-concierge" / "skill-concierge" / "2.0.0")
        run = lambda: _run_zcode(tmp_path, repo, home)

    dest.mkdir(parents=True)
    (dest / "stale.txt").write_text("from an interrupted run")
    (dest.parent / f".{dest.name}.replaced-20260101-000000-1").mkdir()

    r = run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert not (dest / "stale.txt").exists(), "the old tree must not survive the export"
    assert oct(dest.stat().st_mode & 0o777) == oct(0o755)
    aside = [d for d in dest.parent.iterdir() if ".replaced-" in d.name]
    assert len(aside) == 1 and aside[0].name.startswith(f".{dest.name}.replaced-") and (aside[0] / "stale.txt").exists()
    assert not [d for d in dest.parent.iterdir() if d.name.startswith(".skill-concierge-staging.")]


# ── Item 5 (OMP): the registry-read separator must survive an empty field ───────────────────

def _extract_func(path: Path, name: str) -> str:
    """The self-contained `name() { ... }` definition — start line through the first
    subsequent line that is exactly `}` (the function's closing brace; its heredoc body never
    produces such a line on its own)."""
    lines = path.read_text().splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith(f"{name}() {{"))
    end = next(i for i in range(start + 1, len(lines)) if lines[i] == "}")
    return "\n".join(lines[start:end + 1])


def _extract_line(path: Path, needle: str) -> str:
    return next(l for l in path.read_text().splitlines() if needle in l and "IFS=" in l)


def _omp_registry_read(install_sh, tmp_path, *, version, install_path, scope="user", project=""):
    """Run the installer's OWN `_omp_record` function plus its own first registry-read line, in
    isolation, against a crafted registry — proves which byte actually separates the fields,
    without running (or being confused by) the rest of the installer."""
    snippet = _extract_func(install_sh, "_omp_record") + "\n" + _extract_line(install_sh, "_omp_record)")
    reg = tmp_path / "iso" / "installed_plugins.json"
    reg.parent.mkdir(parents=True)
    rec = {"scope": scope, "installPath": install_path, "version": version}
    if project:
        rec["projectPath"] = project
    reg.write_text(json.dumps({"plugins": {PLUGIN_ID: [rec]}}))
    script = (
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        f'OMP_PLUGINS_JSON="{reg}"\n{snippet}\n'
        'printf "INSTALLED=%s\\nINSTALLED_PATH=%s\\nSCOPE=%s\\nPROJECT_PATH=%s\\n" '
        '"${INSTALLED-<unset>}" "${INSTALLED_PATH-<unset>}" "${SCOPE-<unset>}" "${PROJECT_PATH-<unset>}"\n'
    )
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stdout + r.stderr
    out = {}
    for line in r.stdout.splitlines():
        k, _, v = line.partition("=")
        out[k] = v
    return out


def test_registry_read_survives_an_empty_version_field(tmp_path):
    """A tab is IFS whitespace: an empty version field's leading tab is stripped by `read`, so the
    real installPath is misassigned into $INSTALLED and the path field comes up empty. The fix
    reads a \\x1f field separator instead — not IFS whitespace — and also emits scope/projectPath."""
    got = _omp_registry_read(INSTALL_SH["omp"], tmp_path, version="", install_path="/opt/sc/2.0.0",
                              scope="project", project="/proj/A")
    assert got["INSTALLED"] == "", got
    assert got["INSTALLED_PATH"] == "/opt/sc/2.0.0", got
    assert got["SCOPE"] == "project", got
    assert got["PROJECT_PATH"] == "/proj/A", got


# ── Item 6 (OMP + ZCode): registry writes repoint only the record read, bounded backups ─────

@pytest.mark.parametrize("harness", ["omp", "zcode"])
def test_backups_are_named_with_time_and_pid_and_only_five_are_kept(tmp_path, harness):
    repo = _make_repo(tmp_path, "repo", "2.0.0")
    if harness == "omp":
        home, _ = _seed_omp_home_with_cache(tmp_path, version="1.9.0")
        plugins_dir = home / ".omp" / "plugins"
        run = lambda: _run_omp(tmp_path, repo, home)
    else:
        cache = (tmp_path / "home" / ".zcode" / "cli" / "plugins" / "cache" /
                 "skill-concierge" / "skill-concierge" / "1.9.0")
        home = _seed_zcode_home(tmp_path, installed_version="1.9.0", install_path=cache)
        plugins_dir = home / ".zcode" / "cli" / "plugins"
        run = lambda: _run_zcode(tmp_path, repo, home)

    for i in range(6):
        (plugins_dir / f"installed_plugins.json.bak-{harness}-20260101-00000{i}-1").write_text("{}")

    r = run()
    assert r.returncode == 0, r.stdout + r.stderr
    kept = sorted(p.name for p in plugins_dir.glob(f"installed_plugins.json.bak-{harness}-*"))
    assert len(kept) == 5, kept


def test_only_the_matching_scope_record_is_repointed_omp(tmp_path):
    repo = _make_repo(tmp_path, "repo", "2.0.0")
    other = {"scope": "project", "projectPath": "/proj/A", "installPath": "/proj/A/cache", "version": "1.5.0"}
    home, _ = _seed_omp_home_with_cache(tmp_path, version="1.9.0", extra_records=[other])
    r = _run_omp(tmp_path, repo, home)
    assert r.returncode == 0, r.stdout + r.stderr
    recs = _omp_registry(home)["plugins"][PLUGIN_ID]
    assert recs[0]["version"] == "2.0.0"
    assert recs[1] == other, recs[1]


# ── ZCode: registry existence checked, and a downgrade refused, before any cache write ──────

def test_zcode_refuses_when_registry_file_is_missing(tmp_path):
    repo = _make_repo(tmp_path, "repo", "2.0.0")
    home = tmp_path / "home"
    home.mkdir()
    r = _run_zcode(tmp_path, repo, home)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "no skill-concierge@skill-concierge entry" in (r.stdout + r.stderr)
    cache_root = home / ".zcode" / "cli" / "plugins" / "cache"
    assert not cache_root.exists(), "must refuse before any write to the cache"


def test_zcode_refuses_when_registry_has_no_matching_entry(tmp_path):
    repo = _make_repo(tmp_path, "repo", "2.0.0")
    home = tmp_path / "home"
    plugins_dir = home / ".zcode" / "cli" / "plugins"
    plugins_dir.mkdir(parents=True)
    (plugins_dir / "installed_plugins.json").write_text(
        json.dumps({"plugins": [{"id": "some-other@marketplace", "installPath": "/x", "version": "1.0.0"}]}))
    r = _run_zcode(tmp_path, repo, home)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "no skill-concierge@skill-concierge entry" in (r.stdout + r.stderr)
    assert not (plugins_dir / "cache").exists(), "must refuse before any write to the cache"


def test_zcode_refuses_to_downgrade(tmp_path):
    """A newer copy is already active per the registry's own installPath manifest —
    a stale checkout must never repoint ZCode backwards, and must never touch the cache."""
    repo = _make_repo(tmp_path, "repo", "2.0.0")
    deployed = tmp_path / "home" / ".zcode" / "cli" / "plugins" / "cache" / "skill-concierge" / "skill-concierge" / "3.0.0"
    home = _seed_zcode_home(tmp_path, installed_version="3.0.0", install_path=deployed)
    (deployed / ".claude-plugin").mkdir(parents=True)
    (deployed / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": "3.0.0"}))
    r = _run_zcode(tmp_path, repo, home)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "refusing to downgrade" in (r.stdout + r.stderr)
    cache_2_0_0 = deployed.parent / "2.0.0"
    assert not cache_2_0_0.exists(), "must refuse before exporting the older checkout"
    assert (deployed / ".claude-plugin" / "plugin.json").read_text() == json.dumps({"version": "3.0.0"})


def test_zcode_header_lists_every_refusal_that_exits_before_a_write():
    """The installer's own header must list every refusal that exits 1 before any write —
    the registry ones AND the checkout ones (HEAD/version mismatch, a git/ dir, unreadable
    git) — so a reader doesn't have to read the code to know what stops a run."""
    text = INSTALL_SH["zcode"].read_text()
    header_lines = []
    for line in text.splitlines()[1:]:
        if not line.startswith("#"):
            break
        header_lines.append(line)
    header = "\n".join(header_lines)
    assert "# Refusals" in header
    for must_mention in (
        "no registry record",
        "unreadable registry",
        "downgrade",
        "HEAD",
        "git/",
        "git cannot read",
    ):
        assert must_mention in header, f"header is missing a mention of: {must_mention!r}"


def test_changelog_054_1_entry_mentions_the_zcode_missing_registry_entry_refusal():
    """The 0.54.1 entry documents that the ZCode installer refuses a downgrade, but that
    release also shipped a refusal when the registry has no matching entry — the release
    record (CHANGELOG.md, since the README keeps only the current release line) must say so too."""
    changelog = (ROOT / "CHANGELOG.md").read_text()
    start = changelog.index("## [0.54.1]")
    entry = changelog[start:changelog.index("\n## [", start + 1)]
    assert "registry" in entry and "no matching entry" in entry, (
        "CHANGELOG's 0.54.1 entry must mention the ZCode refusal when the registry entry is missing"
    )


# ── Symlink- and mode-safety at each safe_write call site (per-call-site coverage: a regression
# to a plain os.replace at any ONE of these must fail here, not just at the sites already
# covered elsewhere — Claude Code's registry write and the Command Code end-to-end write) ─────

def test_omp_registry_write_keeps_a_symlink_and_its_mode(tmp_path):
    repo = _make_repo(tmp_path, "repo", "2.0.0")
    home, _old_cache = _seed_omp_home_with_cache(tmp_path, version="1.9.0")
    reg = home / ".omp" / "plugins" / "installed_plugins.json"
    dotfiles = tmp_path / "dotfiles"
    dotfiles.mkdir()
    real = dotfiles / "installed_plugins.json"
    shutil.move(str(reg), real)
    real.chmod(0o600)
    reg.symlink_to(real)

    r = _run_omp(tmp_path, repo, home)
    assert r.returncode == 0, r.stdout + r.stderr
    assert reg.is_symlink(), "the OMP registry must stay a symlink"
    assert os.path.realpath(reg) == str(real)
    assert json.loads(real.read_text())["plugins"][PLUGIN_ID][0]["version"] == "2.0.0"
    assert oct(real.stat().st_mode & 0o777) == oct(0o600), "the real file must not widen past 0600"


def test_zcode_registry_write_keeps_a_symlink_and_its_mode(tmp_path):
    repo = _make_repo(tmp_path, "repo", "2.0.0")
    deployed = (tmp_path / "home" / ".zcode" / "cli" / "plugins" / "cache" /
                "skill-concierge" / "skill-concierge" / "1.9.0")
    home = _seed_zcode_home(tmp_path, installed_version="1.9.0", install_path=deployed)
    reg = home / ".zcode" / "cli" / "plugins" / "installed_plugins.json"
    dotfiles = tmp_path / "dotfiles"
    dotfiles.mkdir()
    real = dotfiles / "installed_plugins.json"
    shutil.move(str(reg), real)
    real.chmod(0o600)
    reg.symlink_to(real)

    r = _run_zcode(tmp_path, repo, home)
    assert r.returncode == 0, r.stdout + r.stderr
    assert reg.is_symlink(), "the ZCode registry must stay a symlink"
    assert os.path.realpath(reg) == str(real)
    data = json.loads(real.read_text())
    rec = next(p for p in data["plugins"] if p.get("id") == PLUGIN_ID)
    assert rec["version"] == "2.0.0"
    assert oct(real.stat().st_mode & 0o777) == oct(0o600), "the real file must not widen past 0600"


def test_zcode_mcp_fallback_write_keeps_a_symlink_and_its_mode(tmp_path):
    repo = _make_repo(tmp_path, "repo", "2.0.0")
    deployed = (tmp_path / "home" / ".zcode" / "cli" / "plugins" / "cache" /
                "skill-concierge" / "skill-concierge" / "1.9.0")
    home = _seed_zcode_home(tmp_path, installed_version="1.9.0", install_path=deployed)
    (deployed / ".claude-plugin").mkdir(parents=True)
    (deployed / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": "1.9.0"}))
    (repo / "adapters" / "zcode").mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "adapters" / "zcode" / "mcp.json", repo / "adapters" / "zcode" / "mcp.json")
    config = home / ".zcode" / "cli" / "config.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps({"mcp": {"servers": {}}, "keep": "me"}))
    dotfiles = tmp_path / "dotfiles"
    dotfiles.mkdir()
    real = dotfiles / "config.json"
    shutil.move(str(config), real)
    real.chmod(0o600)
    config.symlink_to(real)

    r = _run_zcode(tmp_path, repo, home, "--mcp-fallback")
    assert r.returncode == 0, r.stdout + r.stderr
    assert config.is_symlink(), "ZCode's config.json must stay a symlink"
    assert os.path.realpath(config) == str(real)
    data = json.loads(real.read_text())
    assert data["mcp"]["servers"]["skill-search"]["command"]
    assert data["keep"] == "me", "an unrelated top-level key must survive the merge"
    assert oct(real.stat().st_mode & 0o777) == oct(0o600), "the real file must not widen past 0600"


def test_omp_config_yml_dev_mode_write_keeps_a_symlink_and_its_mode(tmp_path):
    repo = _make_repo(tmp_path, "repo", "2.0.0")
    (repo / "adapters" / "omp").mkdir(parents=True)
    (repo / "adapters" / "omp" / "skill-concierge.ext.ts").touch()
    home = tmp_path / "home"
    omp_agent = home / ".omp" / "agent"
    omp_agent.mkdir(parents=True)
    config = omp_agent / "config.yml"
    dotfiles = tmp_path / "dotfiles"
    dotfiles.mkdir()
    real = dotfiles / "config.yml"
    real.write_text("extensions:\n  - /some/other/ext.ts\n")
    real.chmod(0o600)
    config.symlink_to(real)

    r = _run_omp(tmp_path, repo, home)   # no installed_plugins.json -> dev-mode path
    assert r.returncode == 0, r.stdout + r.stderr
    assert config.is_symlink(), "OMP's config.yml must stay a symlink"
    assert os.path.realpath(config) == str(real)
    text = real.read_text()
    assert str(repo / "adapters" / "omp" / "skill-concierge.ext.ts") in text
    assert "/some/other/ext.ts" in text, "an unrelated existing extension entry must survive"
    assert oct(real.stat().st_mode & 0o777) == oct(0o600), "the real file must not widen past 0600"


# ── Item 7 (Command Code): a root path holding an apostrophe AND a double quote ─────────────

def test_apostrophe_and_double_quote_in_root_path(tmp_path):
    root = tmp_path / "root's \"repo\""
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": "9.9.9"}))
    (root / "adapters" / "commandcode").mkdir(parents=True)
    shutil.copy(ROOT / "adapters" / "commandcode" / "skill-concierge.mod.ts",
                root / "adapters" / "commandcode" / "skill-concierge.mod.ts")
    (root / "bin").mkdir()
    launcher = root / "bin" / "skill-search-mcp"
    launcher.touch()
    launcher.chmod(0o755)
    home = tmp_path / "home's dir"
    home.mkdir()

    env = installer_env(tmp_path, home)
    r = subprocess.run(["bash", str(INSTALL_SH["commandcode"]), "--root", str(root)],
                        env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SyntaxError" not in r.stderr, r.stderr
    # An unquoted heredoc lets bash run the backticks inside the embedded Python's comments.
    assert "command not found" not in r.stderr, r.stderr
    assert "verify: OK" in r.stdout, r.stdout + r.stderr

    mcp = json.loads((home / ".commandcode" / "mcp.json").read_text())
    assert mcp["mcpServers"]["skill-search"]["command"] == f"{root}/bin/skill-search-mcp"
    settings = json.loads((home / ".commandcode" / "settings.json").read_text())
    assert any(str(root) in h.get("command", "")
               for b in settings["hooks"]["SessionStart"] for h in b["hooks"])


def test_commandcode_verify_failure_exits_nonzero(tmp_path):
    """A genuinely broken install (no MCP launcher on disk) must make verify's own
    `bad` flag exit the script non-zero — printing "verify: FAILED" while returning 0
    would let a caller (or a test) read the run as successful."""
    root = tmp_path / "repo"
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": "9.9.9"}))
    (root / "adapters" / "commandcode").mkdir(parents=True)
    shutil.copy(ROOT / "adapters" / "commandcode" / "skill-concierge.mod.ts",
                root / "adapters" / "commandcode" / "skill-concierge.mod.ts")
    # No bin/skill-search-mcp created — the MCP launcher check must fail verify.
    home = tmp_path / "home"
    home.mkdir()

    env = installer_env(tmp_path, home)
    r = subprocess.run(["bash", str(INSTALL_SH["commandcode"]), "--root", str(root)],
                        env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "verify: FAILED" in r.stdout, r.stdout + r.stderr
    assert "MCP launcher not found" in r.stdout, r.stdout + r.stderr


def test_commandcode_refuses_a_malformed_settings_json_instead_of_resetting_it(tmp_path):
    root = tmp_path / "repo"
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": "9.9.9"}))
    (root / "adapters" / "commandcode").mkdir(parents=True)
    shutil.copy(ROOT / "adapters" / "commandcode" / "skill-concierge.mod.ts",
                root / "adapters" / "commandcode" / "skill-concierge.mod.ts")
    (root / "bin").mkdir()
    launcher = root / "bin" / "skill-search-mcp"
    launcher.touch()
    launcher.chmod(0o755)
    home = tmp_path / "home"
    home.mkdir()
    settings = home / ".commandcode" / "settings.json"
    settings.parent.mkdir(parents=True)
    broken = '{"hooks": {"SessionStart": [}'   # malformed on purpose
    settings.write_text(broken)

    env = installer_env(tmp_path, home)
    r = subprocess.run(["bash", str(INSTALL_SH["commandcode"]), "--root", str(root)],
                        env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode != 0, r.stdout + r.stderr
    assert settings.read_text() == broken, "the malformed file must be left byte-identical"


def test_commandcode_malformed_mcp_json_stops_before_any_write(tmp_path):
    """A malformed mcp.json must stop the run before settings.json or the mod is touched,
    so a refusal never leaves Command Code half-configured."""
    root = tmp_path / "repo"
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": "9.9.9"}))
    (root / "adapters" / "commandcode").mkdir(parents=True)
    shutil.copy(ROOT / "adapters" / "commandcode" / "skill-concierge.mod.ts",
                root / "adapters" / "commandcode" / "skill-concierge.mod.ts")
    (root / "bin").mkdir()
    launcher = root / "bin" / "skill-search-mcp"
    launcher.touch()
    launcher.chmod(0o755)
    home = tmp_path / "home"
    cmd = home / ".commandcode"
    cmd.mkdir(parents=True)
    settings = cmd / "settings.json"
    good = json.dumps({"hooks": {}, "keep": "me"})
    settings.write_text(good)
    broken = '{"mcpServers": {'   # malformed on purpose
    (cmd / "mcp.json").write_text(broken)

    env = installer_env(tmp_path, home)
    r = subprocess.run(["bash", str(INSTALL_SH["commandcode"]), "--root", str(root)],
                        env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode != 0, r.stdout + r.stderr
    assert "Nothing was changed" in r.stderr, r.stderr
    assert (cmd / "mcp.json").read_text() == broken
    assert settings.read_text() == good, "settings.json must not be rewritten on a refusal"
    assert not (cmd / "mods" / "skill-concierge.ts").exists(), "the mod must not be installed"


# The project-scope override path is keyed on a fixed slug for this one machine's checkout
# location, independent of --root, so a fixture only needs to place the file at that fixed
# path under the redirected $HOME to exercise it.
_PROJECT_SLUG = "users-thinhkhuat-in-prod-my-workbench-skill-concierge"


@pytest.mark.parametrize("target,content", [
    ("mcp.json", "[]"),
    ("mcp.json", '{"mcpServers": null}'),
    ("settings.json", "[]"),
    (f"projects/{_PROJECT_SLUG}/mcp.json", "[]"),
    (f"projects/{_PROJECT_SLUG}/mcp.json", '{"mcpServers": null}'),
])
def test_commandcode_wrong_shape_json_refuses_before_any_write(tmp_path, target, content):
    """Valid JSON of the wrong shape (a top-level array, or a null where an object is
    expected) must be refused by the preflight just like a parse failure — not accepted,
    then crash a later step after earlier steps already wrote their part. The per-project
    mcp.json override was already checked for parseability before this shape check existed
    (v0.54.1); these two cases are what is actually new about the preflight there."""
    root = tmp_path / "repo"
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": "9.9.9"}))
    (root / "adapters" / "commandcode").mkdir(parents=True)
    shutil.copy(ROOT / "adapters" / "commandcode" / "skill-concierge.mod.ts",
                root / "adapters" / "commandcode" / "skill-concierge.mod.ts")
    (root / "bin").mkdir()
    launcher = root / "bin" / "skill-search-mcp"
    launcher.touch()
    launcher.chmod(0o755)
    home = tmp_path / "home"
    cmd = home / ".commandcode"
    cmd.mkdir(parents=True)
    target_path = cmd / target
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(content)

    env = installer_env(tmp_path, home)
    r = subprocess.run(["bash", str(INSTALL_SH["commandcode"]), "--root", str(root)],
                        env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode != 0, r.stdout + r.stderr
    assert "Nothing was changed" in r.stderr, r.stderr
    assert target_path.read_text() == content, "the wrong-shape file must be left byte-identical"
    assert not (cmd / "mods" / "skill-concierge.ts").exists(), "the mod must not be installed"


@pytest.mark.parametrize("settings_content", [
    '{"hooks": {"SessionStart": null}}',
    '{"hooks": {"SessionStart": [{"hooks": null}]}}',
    '{"hooks": {"SessionStart": [{"hooks": ["x"]}]}}',
])
def test_commandcode_nested_wrong_shape_leaves_every_file_byte_identical(tmp_path, settings_content):
    """A shape wrong enough to pass the top-level preflight (hooks IS an object) but wrong
    at a nested level (SessionStart null, or an entry whose own hooks list holds something
    that is not a dict) used to crash mid-run — after the mod and settings.json were already
    written. The installer computes every JSON transform in memory before writing anything,
    so a nested failure here must leave the mod absent and all three JSON files — including
    the OTHER two it also rewrites — byte-identical to what was on disk before the run."""
    root = tmp_path / "repo"
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": "9.9.9"}))
    (root / "adapters" / "commandcode").mkdir(parents=True)
    shutil.copy(ROOT / "adapters" / "commandcode" / "skill-concierge.mod.ts",
                root / "adapters" / "commandcode" / "skill-concierge.mod.ts")
    (root / "bin").mkdir()
    launcher = root / "bin" / "skill-search-mcp"
    launcher.touch()
    launcher.chmod(0o755)
    home = tmp_path / "home"
    cmd = home / ".commandcode"
    cmd.mkdir(parents=True)
    settings = cmd / "settings.json"
    settings.write_text(settings_content)
    mcp = cmd / "mcp.json"
    mcp_good = json.dumps({"mcpServers": {"keep": "me"}})
    mcp.write_text(mcp_good)
    project_dir = cmd / "projects" / _PROJECT_SLUG
    project_dir.mkdir(parents=True)
    project_mcp = project_dir / "mcp.json"
    project_mcp_good = json.dumps({"mcpServers": {"also-keep": "me"}})
    project_mcp.write_text(project_mcp_good)

    env = installer_env(tmp_path, home)
    r = subprocess.run(["bash", str(INSTALL_SH["commandcode"]), "--root", str(root)],
                        env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode != 0, r.stdout + r.stderr
    assert settings.read_text() == settings_content, "settings.json must be left byte-identical"
    assert mcp.read_text() == mcp_good, "mcp.json must be left byte-identical"
    assert project_mcp.read_text() == project_mcp_good, "the project mcp.json must be left byte-identical"
    assert not (cmd / "mods" / "skill-concierge.ts").exists(), "the mod must not be installed"


def test_commandcode_write_keeps_a_symlinked_settings_json_a_symlink_and_a_0600_mcp_json_0600(tmp_path):
    """The same class of defect ADR-0072 fixed for the Claude Code registry write: a plain
    `os.replace(tmp, path)` swaps a SYMLINKED settings.json for a plain file (breaking a
    dotfiles-manager setup) and a fresh tmp file inherits the shell's umask, silently
    widening a 0600 mcp.json (which can hold another MCP server's API token in its own
    "env") to a world-readable mode."""
    root = tmp_path / "repo"
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": "9.9.9"}))
    (root / "adapters" / "commandcode").mkdir(parents=True)
    shutil.copy(ROOT / "adapters" / "commandcode" / "skill-concierge.mod.ts",
                root / "adapters" / "commandcode" / "skill-concierge.mod.ts")
    (root / "bin").mkdir()
    launcher = root / "bin" / "skill-search-mcp"
    launcher.touch()
    launcher.chmod(0o755)
    home = tmp_path / "home"
    cmd = home / ".commandcode"
    cmd.mkdir(parents=True)

    # settings.json is a symlink into a dotfiles-managed target (a common real-world layout).
    dotfiles = tmp_path / "dotfiles"
    dotfiles.mkdir()
    real_settings = dotfiles / "commandcode-settings.json"
    real_settings.write_text(json.dumps({"hooks": {}, "keep": "me"}))
    (cmd / "settings.json").symlink_to(real_settings)

    # mcp.json holds another MCP server's token and is locked down to owner-only.
    mcp = cmd / "mcp.json"
    mcp.write_text(json.dumps({"mcpServers": {"other-server": {"env": {"TOKEN": "s3cr3t"}}}}))
    mcp.chmod(0o600)

    env = installer_env(tmp_path, home)
    r = subprocess.run(["bash", str(INSTALL_SH["commandcode"]), "--root", str(root)],
                        env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr

    assert (cmd / "settings.json").is_symlink(), "settings.json must stay a symlink"
    assert os.path.realpath(cmd / "settings.json") == str(real_settings), \
        "the symlink must still point at the same dotfiles-managed file"
    updated = json.loads(real_settings.read_text())
    assert updated["keep"] == "me" and "SessionStart" in updated["hooks"], \
        "the REAL file the symlink points at must carry the new content"

    assert oct(mcp.stat().st_mode & 0o777) == oct(0o600), "mcp.json must not widen past 0600"
    mcp_data = json.loads(mcp.read_text())
    assert mcp_data["mcpServers"]["other-server"]["env"]["TOKEN"] == "s3cr3t", \
        "an unrelated MCP server's own entry must survive the merge"
    assert "skill-search" in mcp_data["mcpServers"]


# ── Sibling smoke tests (not owned here): must not choke on an apostrophe in the root path ──

def _copy_min_repo(dest):
    """A minimal copy of this checkout's own tree, enough for adapters/cline's and
    adapters/dsh's own reads (their own .claude-plugin, scripts, hooks, bin) — placed at an
    apostrophe path so the smoke test actually exercises quoting."""
    dest.mkdir(parents=True)
    for rel in (".claude-plugin", ".mcp.json", "adapters", "scripts", "hooks", "bin", "skills", "setup.sh"):
        src = ROOT / rel
        if not src.exists():
            continue
        if src.is_dir():
            shutil.copytree(src, dest / rel, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(src, dest / rel)


def test_cline_installer_tolerates_an_apostrophe_in_its_own_checkout_path(tmp_path):
    """Cline has no --root flag: ROOT is derived from the installer's own location two levels
    up, so the checkout itself must live at the apostrophe path to exercise anything."""
    checkout = tmp_path / "root's checkout"
    _copy_min_repo(checkout)
    home = tmp_path / "home"
    home.mkdir()
    # installer_env's hermetic PATH deliberately omits `node` (the OMP/ZCode/CommandCode
    # installers never need it); Cline's own verify step shells out to it, so add just that one.
    node_front = tmp_path / "node-front"
    node_front.mkdir()
    node = shutil.which("node")
    if node:
        (node_front / "node").symlink_to(node)
    env = installer_env(tmp_path, home, node_front)
    r = subprocess.run(["bash", str(checkout / "adapters" / "cline" / "install.sh")],
                        env=env, capture_output=True, text=True, timeout=120)
    assert "SyntaxError" not in (r.stdout + r.stderr)
    assert r.returncode == 0, r.stdout + r.stderr


def test_dsh_installer_tolerates_an_apostrophe_in_root_path(tmp_path):
    root = tmp_path / "root's repo"
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": "1.0.0"}))
    home = tmp_path / "home"
    home.mkdir()
    env = installer_env(tmp_path, home, SKILL_DSH_HOME=str(tmp_path / "dsh-home-empty"))
    r = subprocess.run(["bash", str(INSTALL_SH["dsh"]), "--root", str(root)],
                        env=env, capture_output=True, text=True, timeout=120)
    assert "SyntaxError" not in (r.stdout + r.stderr)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "No DSH profiles found" in (r.stdout + r.stderr)
