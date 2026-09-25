"""adapters/dsh/install.sh must write a patch layer DSH can actually load.

Before 0.49.0 it appended list items after a pristine profile's `[]` line (not YAML: DSH refused to
boot the profile) and wrote bare `- id:` entries (DSH's patch layer skips unknown ids — adding needs
`- insert:`), so nothing it wrote ever loaded. Run it against a scratch DSH home and check the shapes
with doctor's own detector and, when DSH is installed, DSH's own js-yaml."""
import importlib.util
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PRISTINE = "# User patch layer for this profile, applied after the packaged bundles.\n[]\n"
LEGACY = PRISTINE + (
    "# skill-concierge skill-search MCP server (ADR-0050, v0.47.1)\n- id: skill-concierge\n"
    "  name: '@deepseek-ai/dsh-mcp-client'\n  config:\n    serverName: skill-search\n"
    "# unlazy stop-hook (DSH), v2.1.0\n- id: unlazy-stop\n  name: '/x/unlazy-dsh-stop.dsh.ts'\n  config: {}\n")


def _doctor():
    spec = importlib.util.spec_from_file_location("doctor_dsh", ROOT / "scripts" / "doctor.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _js_yaml():
    dsh = shutil.which("dsh")
    if not dsh or not shutil.which("node"):
        return None
    cand = Path(os.path.realpath(dsh)).parent.parent / "node_modules" / "js-yaml"
    return cand if cand.is_dir() else None


@pytest.mark.parametrize("start", [PRISTINE, LEGACY], ids=["pristine", "legacy-broken"])
def test_installer_writes_a_loadable_idempotent_patch_layer(start, tmp_path):
    home = tmp_path / "dsh"
    prof = home / "profiles" / "tui"
    prof.mkdir(parents=True)
    (prof / "cordis.yml").write_text("[]\n")
    patch = prof / "cordis.patch.yml"
    patch.write_text(start)
    env = dict(os.environ, SKILL_DSH_HOME=str(home), SKILL_CONCIERGE_LOG=str(tmp_path / "logs"))
    run = lambda: subprocess.run(["bash", str(ROOT / "adapters" / "dsh" / "install.sh")], env=env,
                                 capture_output=True, text=True, timeout=120)
    first = run()
    assert first.returncode == 0, first.stdout + first.stderr
    text = patch.read_text()
    assert _doctor()._dsh_patch_defects(text) == [], text
    for entry in ("id: skill-concierge\n", "id: unlazy-stop\n", "id: skill-concierge-enforcer\n"):
        assert entry in text
    assert text.count("- insert:") == 3 and "\n[]\n" not in text
    js_yaml = _js_yaml()
    if js_yaml:
        chk = subprocess.run(["node", "-e", "const y=require(process.argv[1]);"
                              "const d=y.load(require('fs').readFileSync(process.argv[2],'utf8'));"
                              "if(!Array.isArray(d)||d.length!==3||!d.every(p=>Array.isArray(p.insert)))process.exit(3)",
                              str(js_yaml), str(patch)], capture_output=True, text=True, timeout=60)
        assert chk.returncode == 0, chk.stderr
    assert run().returncode == 0 and patch.read_text() == text   # idempotent


OPERATOR = (
    "# my own patch layer\n"
    "- id: their-plugin\n"
    "  config:\n"
    "    args:\n"
    "      []\n"
    "    home: !!js process.env.HOME\n"
    "# skill-concierge skill-search MCP server (ADR-0050, v0.47.1)\n"
    "\n"
    "- id: skill-concierge\n"
    "  name: '@deepseek-ai/dsh-mcp-client'\n"
    "  # operator note that must survive\n"
    "- id: another-plugin\n"
    "  config: {}\n")


def _install(tmp_path, start):
    home = tmp_path / "dsh"
    prof = home / "profiles" / "tui"
    prof.mkdir(parents=True)
    (prof / "cordis.yml").write_text("[]\n")
    patch = prof / "cordis.patch.yml"
    patch.write_text(start)
    env = dict(os.environ, SKILL_DSH_HOME=str(home), SKILL_CONCIERGE_LOG=str(tmp_path / "logs"))
    r = subprocess.run(["bash", str(ROOT / "adapters" / "dsh" / "install.sh")], env=env,
                       capture_output=True, text=True, timeout=120)
    return r, patch


def test_operator_content_survives_and_nothing_is_duplicated(tmp_path):
    r, patch = _install(tmp_path, OPERATOR)
    assert r.returncode == 0, r.stdout + r.stderr
    text = patch.read_text()
    for kept in ("- id: their-plugin", "      []\n", "home: !!js process.env.HOME",
                 "# operator note that must survive", "- id: another-plugin"):
        assert kept in text, kept
    assert text.count("id: skill-concierge\n") == 1, text      # the blank-line-separated legacy entry was replaced
    assert _doctor()._dsh_patch_defects(text) == [], text
    assert list(patch.parent.glob("cordis.patch.yml.bak-skillconcierge-*")), "a changed file keeps a backup"


def test_a_result_dsh_could_not_load_never_replaces_the_original(tmp_path):
    if not _js_yaml():
        pytest.skip("DSH's js-yaml not installed — the loadability check cannot run")
    flow = "[{insert: [{id: mine, name: p}]}]\n"
    r, patch = _install(tmp_path, flow)
    assert r.returncode != 0, "a failed check must fail the installer"
    assert patch.read_text() == flow, "the original must stay untouched"
    assert not (patch.parent / "cordis.patch.yml.new").exists()
