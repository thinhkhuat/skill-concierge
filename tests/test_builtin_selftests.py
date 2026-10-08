"""Run the built-in `--selftest` of the enforcer and of doctor under pytest.

Both scripts carry their own self-test, and nothing in tests/ ran them, so the enforcer's
self-test failed on main (missing `opencode-personal` scope) without any test noticing.
"""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("script, marker", [
    ("hooks/scripts/enforcer.py", "enforcer --selftest OK"),
    ("scripts/doctor.py", "selftest ok"),
])
def test_builtin_selftest_passes(script, marker):
    run = subprocess.run([sys.executable, str(ROOT / script), "--selftest"],
                         capture_output=True, text=True, timeout=120, cwd=ROOT)
    assert run.returncode == 0, run.stdout[-2000:] + run.stderr[-2000:]
    assert marker in run.stdout
