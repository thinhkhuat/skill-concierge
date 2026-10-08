"""A missing harness.py: a hook run stays silent (exit 0, no output); an importer gets ImportError.

Exiting at import would end any long-running process that imports the enforcer (the findability
sweep loads it and catches Exception, not SystemExit).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parent.parent / "hooks" / "scripts"


@pytest.fixture
def stripped(tmp_path):
    for f in HOOKS.glob("*.py"):
        if f.name != "harness.py":
            shutil.copy(f, tmp_path / f.name)
    return tmp_path


@pytest.mark.parametrize("module", ["enforcer", "doctrine", "ledger"])
def test_hook_run_is_silent_without_harness(module, stripped):
    run = subprocess.run([sys.executable, str(stripped / f"{module}.py")], input="{}",
                         capture_output=True, text=True, timeout=60,
                         env={"HOME": str(stripped), "PATH": "/usr/bin:/bin",
                              "SKILL_CONCIERGE_LOG": str(stripped), "ENFORCER_LEDGER": "0"})
    assert (run.returncode, run.stdout, run.stderr) == (0, "", "")


@pytest.mark.parametrize("module", ["enforcer", "doctrine", "ledger"])
def test_import_raises_instead_of_exiting(module, stripped):
    run = subprocess.run([sys.executable, "-c",
                          f"import sys; sys.path.insert(0, {str(stripped)!r})\n"
                          f"try:\n    import {module}\nexcept ImportError:\n    print('IMPORT_ERROR')"],
                         capture_output=True, text=True, timeout=60,
                         env={"HOME": str(stripped), "PATH": "/usr/bin:/bin", "SKILL_CONCIERGE_LOG": str(stripped)})
    assert run.returncode == 0 and "IMPORT_ERROR" in run.stdout, run.stderr
