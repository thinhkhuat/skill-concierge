"""Run the enforcer's contract self-test (tests/enforcer_selftest.py) under pytest.

The body moved out of hooks/scripts/enforcer.py so the per-prompt hook stops compiling it;
`enforcer.py --selftest` still runs it by exec'ing that file in the enforcer's namespace. This
test does the same against an imported enforcer module, and pins the move itself.
"""
import contextlib
import importlib.util
import io
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENFORCER = ROOT / "hooks" / "scripts" / "enforcer.py"
SELFTEST = ROOT / "tests" / "enforcer_selftest.py"


def _load_enforcer(tmp_path):
    saved = dict(os.environ)
    os.environ["SKILL_CONCIERGE_LOG"] = str(tmp_path)
    try:
        spec = importlib.util.spec_from_file_location(f"enforcer_selftest_{abs(hash(str(tmp_path)))}", ENFORCER)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        os.environ.clear()
        os.environ.update(saved)


def test_selftest_body_passes_in_the_enforcer_namespace(tmp_path):
    mod = _load_enforcer(tmp_path)
    exec(compile(SELFTEST.read_text(encoding="utf-8"), str(SELFTEST), "exec"), mod.__dict__)
    saved, cwd, out = dict(os.environ), os.getcwd(), io.StringIO()
    try:
        os.environ["SKILL_CONCIERGE_LOG"] = str(tmp_path)
        with contextlib.redirect_stdout(out):
            rc = mod._selftest()
    finally:
        os.chdir(cwd)
        os.environ.clear()
        os.environ.update(saved)
    assert rc == 0, out.getvalue()[-3000:]
    assert "enforcer --selftest OK" in out.getvalue()


def test_selftest_body_is_not_in_the_hook():
    assert "def _selftest" not in ENFORCER.read_text(encoding="utf-8")


def test_selftest_cli_exits_2_when_the_tests_file_is_missing(tmp_path):
    hook = tmp_path / "hooks" / "scripts" / "enforcer.py"
    hook.parent.mkdir(parents=True)
    shutil.copy(ENFORCER, hook)
    shutil.copy(ENFORCER.parent / "harness.py", hook.parent / "harness.py")
    run = subprocess.run([sys.executable, str(hook), "--selftest"], capture_output=True, text=True,
                         timeout=120, cwd=tmp_path,
                         env={**os.environ, "SKILL_CONCIERGE_LOG": str(tmp_path), "ENFORCER_LEDGER": "0"})
    assert run.returncode == 2
    assert run.stdout == "" and "enforcer_selftest.py not found" in run.stderr
    assert len(run.stderr.strip().splitlines()) == 1
