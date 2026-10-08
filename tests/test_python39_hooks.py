"""Every hook script must load on the system Python 3.9.

hooks/hooks.json runs plain `python3`. A harness started with a PATH that lacks Homebrew
resolves that to macOS's /usr/bin/python3 (3.9), where a 3.10-only annotation such as
`str | None` raises TypeError at import and the hook dies before printing anything.
Skipped when no 3.9 interpreter is installed.
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / "hooks" / "scripts"
PY39 = shutil.which("python3.9") or ("/usr/bin/python3" if Path("/usr/bin/python3").exists() else "")


def _version(py):
    out = subprocess.run([py, "-c", "import sys; print(sys.version_info[:2])"],
                         capture_output=True, text=True, timeout=30).stdout
    return out.strip()


pytestmark = pytest.mark.skipif(not PY39 or _version(PY39) != "(3, 9)",
                                reason="no Python 3.9 interpreter on this machine")


def _env(tmp_path):
    return {"HOME": os.environ["HOME"], "PATH": "/usr/bin:/bin",
            "SKILL_CONCIERGE_LOG": str(tmp_path)}


@pytest.mark.parametrize("module", sorted(p.stem for p in HOOKS.glob("*.py")))
def test_hook_module_imports_on_python39(module, tmp_path):
    run = subprocess.run([PY39, "-c", f"import sys; sys.path.insert(0, {str(HOOKS)!r}); import {module}"],
                         capture_output=True, text=True, timeout=60, env=_env(tmp_path), cwd=tmp_path)
    assert run.returncode == 0, run.stderr[-2000:]


def test_enforcer_selftest_on_python39(tmp_path):
    run = subprocess.run([PY39, str(HOOKS / "enforcer.py"), "--selftest"],
                         capture_output=True, text=True, timeout=120, env=_env(tmp_path), cwd=ROOT)
    assert run.returncode == 0, run.stdout[-2000:] + run.stderr[-2000:]
    assert "enforcer --selftest OK" in run.stdout
