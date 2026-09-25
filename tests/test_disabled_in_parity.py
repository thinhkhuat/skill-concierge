"""The search server's `disabled_in: ["claude"]` must agree with the per-turn hook's own
invocability verdict: a row may be marked off for Claude only when the enforcer would drop that
plugin in a Claude session. The rule is written twice (engine and hook cannot share code), so this
pins the two copies to each other on the same fixtures."""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def mods(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("engine")
    saved = dict(os.environ)
    os.environ.pop("SKILL_QDRANT_URL", None)
    os.environ.update({"SKILL_QDRANT_PATH": str(tmp / "q"), "SKILL_META_PATH": str(tmp / "m.json"),
                       "SKILL_VECTOR_SIZE": "384", "SKILL_TRIGGERS": str(tmp / "none.json"),
                       "SKILL_CONCIERGE_CATALOG_ROOTS": str(tmp / "none-cat.json"),
                       "SKILL_CONCIERGE_HARNESS": "claude"})
    sys.path.insert(0, str(ROOT / "vendor" / "skill-search"))
    try:
        from skill_search import server, skills_discovery
        spec = importlib.util.spec_from_file_location("enforcer_parity", ROOT / "hooks" / "scripts" / "enforcer.py")
        enf = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(enf)
        yield server, skills_discovery, enf
        server._qdrant.close()          # embedded store: close before interpreter shutdown
    finally:
        os.environ.clear()
        os.environ.update(saved)


CASES = {
    "user switched off": ({"p@m": [{}]}, {"p@m": False}, None),
    "stale key, other marketplace installed": ({"p@new": [{}]}, {"p@old": False}, None),
    "one copy on, one off": ({"p@a": [{}], "p@b": [{}]}, {"p@a": False, "p@b": True}, None),
    "non-bool falsy value": ({"p@m": [{}]}, {"p@m": 0}, None),
    "every entry enabled:false": ({"p@m": [{"enabled": False}]}, {}, None),
    "local layer re-enables": ({"p@m": [{}]}, {"p@m": False}, {"p@m": True}),
    "not installed at all": ({"q@m": [{}]}, {"p@m": False}, None),
    "unreadable registry": ("{broken", {"p@m": False}, None),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_server_marks_off_exactly_what_the_enforcer_drops(case, mods, tmp_path, monkeypatch):
    server, sd, enf = mods
    installed, user, local = CASES[case]
    home = tmp_path / "home"
    (home / ".claude" / "plugins").mkdir(parents=True)
    reg = home / ".claude" / "plugins" / "installed_plugins.json"
    reg.write_text(installed if isinstance(installed, str) else json.dumps({"plugins": installed}))
    (home / ".claude" / "settings.json").write_text(json.dumps({"enabledPlugins": user}))
    proj = tmp_path / "proj"
    (proj / ".claude").mkdir(parents=True)
    if local is not None:
        (proj / ".claude" / "settings.local.json").write_text(json.dumps({"enabledPlugins": local}))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(proj)
    monkeypatch.setattr(sd, "INSTALLED_PLUGINS_JSON", reg)
    monkeypatch.setattr(sd, "CLAUDE_SETTINGS_JSON", home / ".claude" / "settings.json")
    monkeypatch.setattr(enf, "_INSTALLED_PLUGINS_JSON", reg)
    monkeypatch.setattr(enf, "_CLAUDE_SETTINGS_JSON", home / ".claude" / "settings.json")
    monkeypatch.setattr(enf, "RUNNING_HARNESS", "claude")

    marked_off = server._claude_disabled_plugin_ids()
    invocable = enf._invocable_plugin_ids()
    for pid in ("p", "q"):
        enforcer_drops = invocable is not None and pid not in invocable and ":" in f"{pid}:x"
        installed_here = isinstance(installed, dict) and any(k.startswith(f"{pid}@") for k in installed)
        # the server may mark off only what the enforcer drops, and must mark every installed one it drops
        assert (pid in marked_off) == (enforcer_drops and installed_here), (case, pid, marked_off, invocable)


def test_both_sides_read_the_user_settings_file_from_one_env_seam(tmp_path):
    """SKILL_CLAUDE_SETTINGS moves the USER settings layer for the engine; the hook must follow it,
    or the two copies of the rule read different files and `disabled_in` drifts from the offer."""
    alt = tmp_path / "alt-settings.json"
    code = ("import importlib.util, sys; sys.path.insert(0, sys.argv[1] + '/vendor/skill-search');"
            "from skill_search import skills_discovery as sd;"
            "s = importlib.util.spec_from_file_location('e', sys.argv[1] + '/hooks/scripts/enforcer.py');"
            "e = importlib.util.module_from_spec(s); s.loader.exec_module(e);"
            "print(sd.CLAUDE_SETTINGS_JSON == e._CLAUDE_SETTINGS_JSON == __import__('pathlib').Path(sys.argv[2]))")
    env = dict(os.environ, SKILL_CLAUDE_SETTINGS=str(alt), SKILL_CONCIERGE_HARNESS="claude")
    out = subprocess.run([sys.executable, "-c", code, str(ROOT), str(alt)], env=env,
                         capture_output=True, text=True, timeout=60)
    assert out.stdout.strip().endswith("True"), out.stdout + out.stderr
