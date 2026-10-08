"""doctor's self-test body lives in tests/doctor_selftest.py, outside the shipped script.

`doctor.py --selftest` execs that file inside doctor's module namespace. These tests run the
body the same way under pytest, pin that the body stays out of doctor.py, and pin the
one-line exit-2 message when the tests/ file is absent.
"""
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCTOR = ROOT / "scripts" / "doctor.py"
BODY = ROOT / "tests" / "doctor_selftest.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_selftest_body_passes_in_doctor_namespace(capsys):
    dr = _load("doctor_selftest_t", DOCTOR)
    exec(compile(BODY.read_text(encoding="utf-8"), str(BODY), "exec"), vars(dr))
    assert dr._selftest() == 0
    assert capsys.readouterr().out.strip().splitlines()[-1] == "selftest ok"


def test_body_is_not_in_shipped_script():
    assert "def _selftest" not in DOCTOR.read_text(encoding="utf-8")


def test_missing_body_file_exits_2(tmp_path):
    """A checkout without tests/ (doctor copied alone) gets one stderr line and exit 2."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "doctor.py").write_bytes(DOCTOR.read_bytes())
    os.symlink(ROOT / "vendor", tmp_path / "vendor")
    run = subprocess.run([sys.executable, str(tmp_path / "scripts" / "doctor.py"), "--selftest"],
                         capture_output=True, text=True, timeout=60, cwd=tmp_path)
    assert run.returncode == 2
    assert run.stdout == ""
    assert len(run.stderr.strip().splitlines()) == 1
    assert "doctor_selftest.py" in run.stderr
