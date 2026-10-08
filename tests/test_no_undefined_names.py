"""Shipped Python may not reference an undefined name.

A name left behind by a removal (v0.65.0: `floor`, after the per-skill floor went) raises
NameError only on the branch that reads it, so the suite can pass while one leg of the hook is
dead. pyflakes finds every such name statically.
"""
from pathlib import Path


try:  # a hard requirement, not a skip: a skipped guard is a missing guard
    import pyflakes.api as pyflakes_api
    from pyflakes.reporter import Reporter
except ImportError:  # pragma: no cover
    raise ImportError("tests need pyflakes: python3 -m pip install pyflakes") from None

ROOT = Path(__file__).resolve().parent.parent
SHIPPED = sorted([*(ROOT / "hooks" / "scripts").glob("*.py"), *(ROOT / "scripts").glob("*.py"),
                  *(ROOT / "adapters").glob("*/*.py"), *(ROOT / "skills").glob("*/scripts/*.py"),
                  *(ROOT / "vendor" / "skill-search" / "skill_search").glob("*.py")])


class _Collect(Reporter):
    def __init__(self):
        self.found = []

    def flake(self, message):
        if "undefined name" in str(message):
            self.found.append(str(message))

    def unexpectedError(self, filename, msg):
        self.found.append(f"{filename}: {msg}")

    def syntaxError(self, filename, msg, lineno, offset, text):
        self.found.append(f"{filename}:{lineno}: {msg}")


def _undefined(path):
    rep = _Collect()
    pyflakes_api.checkPath(str(path), rep)
    return rep.found


def test_the_check_fires_on_an_undefined_name(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("def f():\n    return floor\n")
    assert _undefined(bad) and "undefined name 'floor'" in _undefined(bad)[0]


def test_no_shipped_python_references_an_undefined_name():
    assert len(SHIPPED) > 20
    found = [m for p in SHIPPED for m in _undefined(p)]
    assert not found, "\n".join(found)
