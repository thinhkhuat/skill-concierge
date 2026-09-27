"""Static guard: every skill-concierge installer must repoint a config file — a JSON
registry, an MCP server declaration, a harness settings file, or DSH's cordis.patch.yml —
through adapters/lib/safe_write.py, never through a bare `mv`/`>` redirect onto the live path,
`os.replace(`, `shutil.move(`, or a raw `.write_text(`/`.write_bytes(`. Those primitives break
a symlinked config (swap the link for a plain file) and can widen a locked-down file's mode to
the shell's umask — the exact defect ADR-0072 fixed once for the Claude Code registry, and
that DSH's own `cordis.patch.yml` swap (`mv "$NEW" "$PATCH"`) had until this release.

Two passes, both driven from the installer scripts themselves rather than a hand-typed file
list, so a NEW config write introduced later is caught the same way:

  1. Bash: any `mv ... "$VAR"` or `> "$VAR"` whose destination is exactly a shell variable the
     installer itself assigned to a path ending in .json/.yml/.yaml (the config extensions) —
     this is precisely what would have caught the DSH regression before it shipped. A backup
     destination (`$VAR.bak-...`) or a scratch candidate (`$VAR.new`) is not the live config
     and is excluded, since the destination there is not exactly `$VAR`.
  2. Python (embedded in the same scripts via heredocs): `.write_text(`, `.write_bytes(`,
     `os.replace(`, `shutil.move(` outside a `safe_write.*` call, with a short, reasoned ALLOW
     list for the two writes that are provably not a config repoint (a mod's own *.ts SOURCE
     copy, and DSH's `.new` scratch candidate, written before DSH's own parser validates it —
     the live file is only ever repointed through safe_write, checked by pass 1 above).
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADAPTER_SCRIPTS = sorted((ROOT / "adapters").glob("*/install.sh"))
CONFIG_EXTENSIONS = (".json", ".yml", ".yaml")

_VAR_ASSIGN_RE = re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)="([^"\n]*)"\s*$', re.MULTILINE)
_PY_WRITE_RE = re.compile(r'\.write_text\(|\.write_bytes\(|\bos\.replace\(|\bshutil\.move\(')

# (adapter dir name, a distinguishing substring of the allowed line) -> why it is not a config
# repoint. Keep this list short — a new entry must justify itself, not just silence the guard.
ALLOWED_RAW_PY_WRITES = {
    ("commandcode", "mod_dst.write_bytes(mod_bytes)"):
        "copies the mod's own .ts SOURCE file, not a JSON/YAML config the harness reads as settings",
    ("dsh", '.write_text(patch_text + "\\n", encoding="utf-8")'):
        "writes the .new SCRATCH candidate beside cordis.patch.yml, before DSH's own parser "
        "validates it — the live file is only ever repointed through safe_write.write_text",
}


def _config_vars(bash_text):
    """VARNAME -> the literal path it was assigned, for every VARNAME whose right-hand side
    ends in a config extension — resolved from the installer's own literal assignment line,
    never guessed."""
    out = {}
    for name, value in _VAR_ASSIGN_RE.findall(bash_text):
        if value.lower().endswith(CONFIG_EXTENSIONS):
            out[name] = value
    return out


def find_unsafe_bash_writes(bash_text):
    """Lines where `mv` or a `>` redirect targets a config variable's OWN path exactly (not a
    `.bak-*` backup or a `.new` scratch candidate beside it)."""
    offenders = []
    config_vars = _config_vars(bash_text)
    for lineno, line in enumerate(bash_text.splitlines(), 1):
        for var in config_vars:
            dest_re = re.compile(r'(?:\bmv\b.*|>)\s*"?\$\{?' + re.escape(var) + r'\}?"?\s*(?:#.*)?$')
            if not dest_re.search(line.rstrip()):
                continue
            if ".bak-" in line or ".new" in line or "safe_write" in line:
                continue
            offenders.append(f"line {lineno}: {line.strip()}")
    return offenders


def _py_write_offenders(adapter, text):
    offenders = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if not _PY_WRITE_RE.search(line):
            continue
        stripped = line.strip()
        if "safe_write." in stripped:
            continue
        if any(adapter == a and needle in stripped for a, needle in ALLOWED_RAW_PY_WRITES):
            continue
        offenders.append(f"{adapter}:{lineno}: {stripped}")
    return offenders


def test_every_installer_config_write_goes_through_safe_write():
    offenders = []
    for script in ADAPTER_SCRIPTS:
        adapter = script.parent.name
        text = script.read_text(encoding="utf-8")
        offenders += [f"{adapter} (bash) {o}" for o in find_unsafe_bash_writes(text)]
        offenders += _py_write_offenders(adapter, text)
    assert offenders == [], "raw config write(s) bypassing safe_write:\n" + "\n".join(offenders)


# ── Prove the guard actually bites (synthetic text — never mutates the real installers) ─────

def test_guard_bites_the_dsh_shaped_mv_regression():
    """The exact shape of the regression this release fixed: a config variable assigned from a
    literal .yml path, then swapped in with a bare `mv` instead of safe_write."""
    bash_text = (
        'PATCH="$PROFILE/cordis.patch.yml"\n'
        'NEW="$PATCH.new"\n'
        'mv "$NEW" "$PATCH"\n'
    )
    assert find_unsafe_bash_writes(bash_text), "a raw mv onto a config variable must be flagged"


def test_guard_allows_a_backup_and_a_safe_write_swap():
    bash_text = (
        'PATCH="$PROFILE/cordis.patch.yml"\n'
        'NEW="$PATCH.new"\n'
        'cp -p "$PATCH" "$PATCH.bak-skillconcierge-20260101-000000"\n'
        'python3 - "$NEW" "$PATCH" <<PY\n'
        "safe_write.write_text(patch_path, new_path.read_text())\n"
        "PY\n"
    )
    assert not find_unsafe_bash_writes(bash_text)


def test_guard_bites_a_raw_python_write_onto_a_config_path():
    py_text = 'patch_path.write_text(new_text, encoding="utf-8")\n'
    assert _py_write_offenders("hypothetical", py_text)


def test_guard_allows_a_safe_write_call():
    py_text = "safe_write.write_text(patch_path, new_text)\n"
    assert not _py_write_offenders("hypothetical", py_text)


def test_guard_would_have_caught_the_shipped_dsh_regression():
    """Regression pin, read straight from git history rather than a copy that could drift:
    the DSH installer as it actually shipped at 7e6cecf swapped cordis.patch.yml in with a
    bare `mv "$NEW" "$PATCH"` — the symlink-breaking, mode-widening swap. This stays true even after the
    working tree is edited again."""
    text = subprocess.run(["git", "show", "7e6cecf:adapters/dsh/install.sh"], cwd=ROOT,
                          capture_output=True, text=True, check=True).stdout
    assert find_unsafe_bash_writes(text), "the guard must flag 7e6cecf's DSH mv regression"
