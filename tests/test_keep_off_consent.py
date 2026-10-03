"""ADR-0077: the keep-off map is built ONLY with Thinh's consent, never automatically.

Covered:
  • the hook hides skills only from a map marked `approved_by_user: true`; an unmarked (auto-built)
    map hides nothing;
  • build_keep_off.py writes nothing by default (proposal only); `--apply` saves an approved map;
  • no automatic path runs the generator: setup.sh, doctor.py, the hooks and the adapters never
    invoke it (comments that tell Thinh how to run it by hand are allowed).
"""

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENFORCER = ROOT / "hooks" / "scripts" / "enforcer.py"
GEN = ROOT / "scripts" / "build_keep_off.py"


def _enforcer_with(tmp_path, monkeypatch, data):
    path = tmp_path / "keep-off.json"
    path.write_text(json.dumps(data))
    monkeypatch.setenv("SKILL_CONCIERGE_KEEPOFF", str(path))
    monkeypatch.setenv("SKILL_CONCIERGE_LOG", str(tmp_path))
    spec = importlib.util.spec_from_file_location(f"enforcer_keepoff_{abs(hash(json.dumps(data)))}", ENFORCER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_an_unapproved_map_hides_nothing(tmp_path, monkeypatch):
    mod = _enforcer_with(tmp_path, monkeypatch, {"keep_off": ["ak-sumup", "graft"]})
    assert mod.KEEPOFF == frozenset()


def test_a_map_marked_false_hides_nothing(tmp_path, monkeypatch):
    mod = _enforcer_with(tmp_path, monkeypatch, {"keep_off": ["ak-sumup"], "approved_by_user": False})
    assert mod.KEEPOFF == frozenset()


def test_an_approved_map_hides_its_skills(tmp_path, monkeypatch):
    mod = _enforcer_with(tmp_path, monkeypatch, {"keep_off": ["ak-sumup"], "approved_by_user": True})
    assert mod.KEEPOFF == frozenset({"ak-sumup"})


def _run_gen(tmp_path, *extra):
    ledger = tmp_path / "ledger.log"
    ledger.write_text("")
    out = tmp_path / "keep-off.json"
    r = subprocess.run([sys.executable, str(GEN), "--ledger", str(ledger), "--out", str(out), *extra],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return out, r.stdout


def test_the_generator_writes_nothing_by_default(tmp_path):
    out, stdout = _run_gen(tmp_path)
    assert not out.exists()
    assert "nothing written" in stdout


def test_apply_saves_an_approved_map(tmp_path):
    out, _ = _run_gen(tmp_path, "--apply")
    assert json.loads(out.read_text())["approved_by_user"] is True


def _code_lines(path: Path):
    """Non-comment lines (shell `#`, Python `#`), so instructions to Thinh in comments are allowed."""
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.lstrip().startswith("#"):
            yield line


# A real invocation: a quoted script path (a subprocess/argv element) or an import in Python; any
# non-comment line in a shell or JS file. Prose that tells Thinh how to run it by hand is allowed.
_PY_CALL = re.compile(r"""["']build_keep_off\.py["']|^\s*(?:import|from)\s+build_keep_off\b""")


def test_no_automatic_path_runs_the_generator():
    paths = [ROOT / "setup.sh", ROOT / "scripts" / "doctor.py"]
    paths += sorted((ROOT / "hooks").rglob("*.py")) + sorted((ROOT / "hooks").rglob("*.sh"))
    paths += sorted((ROOT / "adapters").rglob("*.sh")) + sorted((ROOT / "adapters").rglob("*.ts"))
    paths += sorted((ROOT / "adapters").rglob("*.cjs")) + sorted((ROOT / "bin").glob("*"))
    offenders = []
    for p in paths:
        if not p.is_file():
            continue
        is_py = p.suffix == ".py"
        for line in _code_lines(p):
            hit = _PY_CALL.search(line) if is_py else "build_keep_off" in line
            if hit:
                offenders.append(f"{p.relative_to(ROOT)}: {line.strip()}")
    assert offenders == []


def test_the_guard_catches_a_real_call(tmp_path):
    """The invocation pattern bites on the exact form doctor used before ADR-0077."""
    old = 'r = _run([str(py), str(ROOT / "scripts" / "build_keep_off.py"), "--out", str(KEEPOFF_DURABLE)])'
    assert _PY_CALL.search(old)
    assert not _PY_CALL.search("saved by `build_keep_off.py --apply` after Thinh's yes")
