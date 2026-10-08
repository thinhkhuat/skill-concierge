"""scripts/check_flag_docs_parity.py passes on the real tree and fails on each kind of drift it guards:
a table row with no docs entry, a docs entry with no table row, a table default, a docs default, and a
code default that disagree. Each case edits a throwaway copy of the files the check reads."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / "scripts" / "check_flag_docs_parity.py"
CODE_DIRS = ("hooks/scripts", "vendor/skill-search/skill_search", "scripts", "bin")


@pytest.fixture
def tree(tmp_path):
    for d in CODE_DIRS:
        shutil.copytree(ROOT / d, tmp_path / d, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy(ROOT / "AGENTS.md", tmp_path / "AGENTS.md")
    (tmp_path / "docs").mkdir()
    shutil.copy(ROOT / "docs" / "runtime-flags.md", tmp_path / "docs" / "runtime-flags.md")
    return tmp_path


def run(root):
    env = dict(os.environ, SKILL_CONCIERGE_ROOT=str(root))
    return subprocess.run([sys.executable, str(CHECK)], env=env, capture_output=True, text=True)


def edit(path, old, new):
    text = path.read_text(encoding="utf-8")
    assert text.count(old) >= 1, f"fixture text not found in {path.name}: {old!r}"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def test_real_tree_is_in_parity(tree):
    r = run(tree)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "flag-docs-parity OK" in r.stdout


def test_table_row_without_docs_entry_fails(tree):
    docs = tree / "docs" / "runtime-flags.md"
    text = docs.read_text(encoding="utf-8")
    kept = [ln for ln in text.splitlines(keepends=True) if "SKILL_COMMANDCODE_ROOTS" not in ln]
    docs.write_text("".join(kept), encoding="utf-8")
    r = run(tree)
    assert r.returncode == 1 and "SKILL_COMMANDCODE_ROOTS is never named" in r.stdout


def test_docs_entry_without_table_row_fails(tree):
    with open(tree / "docs" / "runtime-flags.md", "a", encoding="utf-8") as f:
        f.write("\n- `SKILL_NOT_IN_TABLE` (`scripts/x.py`) — default ON: a made-up flag.\n")
    r = run(tree)
    assert r.returncode == 1 and "SKILL_NOT_IN_TABLE but the AGENTS.md table has no row" in r.stdout


def test_table_default_that_differs_from_code_fails(tree):
    edit(tree / "AGENTS.md", "| `SKILL_CONSULT_SLOTS` | OFF |", "| `SKILL_CONSULT_SLOTS` | ON |")
    r = run(tree)
    assert r.returncode == 1 and "AGENTS.md says SKILL_CONSULT_SLOTS defaults ON" in r.stdout


def test_docs_default_that_differs_from_code_fails(tree):
    edit(tree / "docs" / "runtime-flags.md", "— default `0`: with `=1`", "— default `1`: with `=1`")
    r = run(tree)
    assert r.returncode == 1 and "docs/runtime-flags.md says ENFORCER_JEV_HISTORY defaults ON" in r.stdout


def test_code_default_change_without_doc_change_fails(tree):
    edit(tree / "hooks" / "scripts" / "enforcer.py", '"ENFORCER_CHAIN_HINT", "1")', '"ENFORCER_CHAIN_HINT", "0")')
    r = run(tree)
    assert r.returncode == 1 and "ENFORCER_CHAIN_HINT defaults ON, code says ['OFF']" in r.stdout


def test_docs_entry_without_a_default_fails(tree):
    edit(tree / "docs" / "runtime-flags.md", "— default ON; the harness-message lane", "— the harness-message lane")
    r = run(tree)
    assert r.returncode == 1 and "entry ENFORCER_HARNESS_SKIP states no default" in r.stdout


def test_unset_value_in_table_that_differs_fails(tree):
    edit(tree / "AGENTS.md", "unset = `ts:<ENFORCER_JEV_MODEL>`", "unset = `cc:<ENFORCER_JEV_MODEL>`")
    r = run(tree)
    assert r.returncode == 1 and "AGENTS.md says ENFORCER_JEV_BENCH unset = 'cc:<ENFORCER_JEV_MODEL>'" in r.stdout


def test_unset_value_in_docs_that_differs_fails(tree):
    edit(tree / "docs" / "runtime-flags.md", "Unset = `ts:<ENFORCER_JEV_MODEL>`", "Unset = `gw:<ENFORCER_JEV_MODEL>`")
    r = run(tree)
    assert r.returncode == 1 and "its docs entry does not say 'Unset = `ts:<ENFORCER_JEV_MODEL>`'" in r.stdout


def test_unset_value_in_code_that_differs_fails(tree):
    edit(tree / "hooks" / "scripts" / "enforcer.py", '"ENFORCER_JEV_BENCH", f"ts:{JEV_MODEL}"', '"ENFORCER_JEV_BENCH", f"cc:{JEV_MODEL}"')
    r = run(tree)
    assert r.returncode == 1 and "code says ['cc:<ENFORCER_JEV_MODEL>']" in r.stdout


def test_default_cell_that_is_not_understood_fails(tree):
    edit(tree / "AGENTS.md", "| `SKILL_CONSULT_SLOTS` | OFF |", "| `SKILL_CONSULT_SLOTS` | sometimes |")
    r = run(tree)
    assert r.returncode == 1 and "SKILL_CONSULT_SLOTS has a default cell that is neither" in r.stdout


def test_empty_unset_value_in_code_that_differs_fails(tree):
    """An empty-string default is written "unset = (empty)" (ENFORCER_JEV_TIER) and still checked."""
    edit(tree / "hooks" / "scripts" / "enforcer.py", '"ENFORCER_JEV_TIER", ""', '"ENFORCER_JEV_TIER", "typesafe"')
    r = run(tree)
    assert r.returncode == 1 and "AGENTS.md says ENFORCER_JEV_TIER unset = ''" in r.stdout
