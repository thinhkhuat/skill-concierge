"""One harness detector (hooks/scripts/harness.py) for enforcer.py, doctrine.py and ledger.py.

Each hook kept its own copy of the detection and the copies drifted. TABLE records, per case,
what each hook answers: the enforcer's harness, the doctrine's rendering (which harness's tool
names the standing order is rewritten to; ZCode renders as Claude) and the ledger row's
`harness` stamp (None = no field, as on every Claude row). Every value was produced by running
main's three copies on the case (main aa6d7c2). Where main's copies disagreed, the enforcer's
answer wins and the row says what main answered (`# main: ...`). One exception goes the other
way: main's enforcer had no `.commandcode` path marker and answered "claude" there; the shared
detector keeps doctrine's marker, which Command Code's env-less SessionStart hook needs
(docs/caveats.md §23, doctrine's own selftest).

A row: (id, env, install-path marker of the running script or None, payload `harness`,
enforcer, doctrine, ledger). CODEX_HOME is read by none of the three (the `codex-home-only` row).
"""
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "hooks" / "scripts"
KEYS = ("SKILL_CONCIERGE_HARNESS", "OMPCODE", "ZCODE_PLUGIN_ROOT", "DSH_SHELL", "CLAUDE_PLUGIN_ROOT",
        "CODEX_HOME")
RENDERINGS = ("claude", "omp", "codex", "commandcode", "dsh", "cline", "opencode")

TABLE = [
    ('none', {}, None, None, 'claude', 'claude', None),
    ('codex-home-only', {'CODEX_HOME': '/nx/.codex'}, None, None, 'claude', 'claude', None),
    ('explicit[claude]', {'SKILL_CONCIERGE_HARNESS': 'claude'}, None, None, 'claude', 'claude', 'claude'),
    ('explicit[codex]', {'SKILL_CONCIERGE_HARNESS': 'codex'}, None, None, 'codex', 'codex', 'codex'),
    ('explicit[commandcode]', {'SKILL_CONCIERGE_HARNESS': 'commandcode'}, None, None, 'commandcode', 'commandcode', 'commandcode'),
    ('explicit[cmd]', {'SKILL_CONCIERGE_HARNESS': 'cmd'}, None, None, 'commandcode', 'commandcode', 'cmd'),
    ('explicit[command-code]', {'SKILL_CONCIERGE_HARNESS': 'command-code'}, None, None, 'commandcode', 'commandcode', 'command-code'),
    ('explicit[omp]', {'SKILL_CONCIERGE_HARNESS': 'omp'}, None, None, 'omp', 'omp', 'omp'),
    ('explicit[oh-my-pi]', {'SKILL_CONCIERGE_HARNESS': 'oh-my-pi'}, None, None, 'omp', 'omp', 'oh-my-pi'),
    ('explicit[zcode]', {'SKILL_CONCIERGE_HARNESS': 'zcode'}, None, None, 'zcode', 'claude', 'zcode'),
    ('explicit[z-code]', {'SKILL_CONCIERGE_HARNESS': 'z-code'}, None, None, 'zcode', 'claude', 'z-code'),
    ('explicit[dsh]', {'SKILL_CONCIERGE_HARNESS': 'dsh'}, None, None, 'dsh', 'dsh', 'dsh'),
    ('explicit[deepseek-harness]', {'SKILL_CONCIERGE_HARNESS': 'deepseek-harness'}, None, None, 'dsh', 'dsh', 'deepseek-harness'),
    ('explicit[oh-dsh]', {'SKILL_CONCIERGE_HARNESS': 'oh-dsh'}, None, None, 'dsh', 'dsh', 'oh-dsh'),
    ('explicit[ohdsh]', {'SKILL_CONCIERGE_HARNESS': 'ohdsh'}, None, None, 'dsh', 'dsh', 'ohdsh'),
    ('explicit[cline]', {'SKILL_CONCIERGE_HARNESS': 'cline'}, None, None, 'cline', 'cline', 'cline'),
    ('explicit[cline-cli]', {'SKILL_CONCIERGE_HARNESS': 'cline-cli'}, None, None, 'cline', 'cline', 'cline-cli'),
    ('explicit[opencode]', {'SKILL_CONCIERGE_HARNESS': 'opencode'}, None, None, 'opencode', 'opencode', 'opencode'),
    ('explicit[open-code]', {'SKILL_CONCIERGE_HARNESS': 'open-code'}, None, None, 'opencode', 'opencode', 'open-code'),
    ('explicit[ OMP ]', {'SKILL_CONCIERGE_HARNESS': ' OMP '}, None, None, 'omp', 'omp', 'omp'),
    ('explicit[Codex]', {'SKILL_CONCIERGE_HARNESS': 'Codex'}, None, None, 'codex', 'codex', 'codex'),
    ('explicit[CMD]', {'SKILL_CONCIERGE_HARNESS': 'CMD'}, None, None, 'commandcode', 'commandcode', 'cmd'),
    ('explicit[foo]', {'SKILL_CONCIERGE_HARNESS': 'foo'}, None, None, 'claude', 'claude', 'foo'),
    ('explicit[]', {'SKILL_CONCIERGE_HARNESS': ''}, None, None, 'claude', 'claude', None),
    ('explicit[   ]', {'SKILL_CONCIERGE_HARNESS': '   '}, None, None, 'claude', 'claude', None),
    ('explicit-claude+ompcode', {'SKILL_CONCIERGE_HARNESS': 'claude', 'OMPCODE': '1'}, None, None, 'claude', 'claude', 'claude'),
    ('explicit-codex+zcode-root', {'SKILL_CONCIERGE_HARNESS': 'codex', 'ZCODE_PLUGIN_ROOT': '/nx/z'}, None, None, 'codex', 'codex', 'codex'),
    ('explicit-foo+ompcode', {'SKILL_CONCIERGE_HARNESS': 'foo', 'OMPCODE': '1'}, None, None, 'omp', 'omp', 'foo'),  # main: doctrine claude
    ('explicit-foo+zcode-file', {'SKILL_CONCIERGE_HARNESS': 'foo'}, '.zcode', None, 'zcode', 'claude', 'foo'),
    ('explicit-foo+cpr-codex', {'SKILL_CONCIERGE_HARNESS': 'foo', 'CLAUDE_PLUGIN_ROOT': '/nx/.codex/plugins/cache/sc'}, None, None, 'codex', 'codex', 'foo'),  # main: doctrine claude
    ('ompcode', {'OMPCODE': '1'}, None, None, 'omp', 'omp', None),
    ('ompcode-padded', {'OMPCODE': ' 1 '}, None, None, 'omp', 'omp', None),
    ('ompcode-0', {'OMPCODE': '0'}, None, None, 'claude', 'claude', None),
    ('zcode-root-abs', {'ZCODE_PLUGIN_ROOT': '/nx/zroot'}, None, None, 'zcode', 'claude', 'zcode'),
    ('zcode-root-rel', {'ZCODE_PLUGIN_ROOT': 'zroot'}, None, None, 'claude', 'claude', None),
    ('zcode-root-empty', {'ZCODE_PLUGIN_ROOT': ''}, None, None, 'claude', 'claude', None),
    ('dsh-shell', {'DSH_SHELL': '1'}, None, None, 'dsh', 'dsh', 'dsh'),
    ('dsh-shell-0', {'DSH_SHELL': '0'}, None, None, 'claude', 'claude', None),
    ('ompcode+zcode-root', {'OMPCODE': '1', 'ZCODE_PLUGIN_ROOT': '/nx/z'}, None, None, 'omp', 'omp', None),  # main: ledger zcode
    ('ompcode+dsh-shell', {'OMPCODE': '1', 'DSH_SHELL': '1'}, None, None, 'omp', 'omp', None),  # main: ledger dsh
    ('zcode-root+dsh-shell', {'ZCODE_PLUGIN_ROOT': '/nx/z', 'DSH_SHELL': '1'}, None, None, 'zcode', 'claude', 'zcode'),
    ('zcode-root+cpr-omp', {'ZCODE_PLUGIN_ROOT': '/nx/z', 'CLAUDE_PLUGIN_ROOT': '/nx/.omp/plugins/cache/sc'}, None, None, 'zcode', 'claude', 'zcode'),
    ('cpr[.omp]', {'CLAUDE_PLUGIN_ROOT': '/nx/.omp/plugins/cache/sc'}, None, None, 'omp', 'omp', None),
    ('file[.omp]', {}, '.omp', None, 'omp', 'omp', None),
    ('cpr[.codex]', {'CLAUDE_PLUGIN_ROOT': '/nx/.codex/plugins/cache/sc'}, None, None, 'codex', 'codex', None),
    ('file[.codex]', {}, '.codex', None, 'codex', 'codex', None),
    ('cpr[.zcode]', {'CLAUDE_PLUGIN_ROOT': '/nx/.zcode/plugins/cache/sc'}, None, None, 'zcode', 'claude', 'zcode'),
    ('file[.zcode]', {}, '.zcode', None, 'zcode', 'claude', 'zcode'),
    ('cpr[.commandcode]', {'CLAUDE_PLUGIN_ROOT': '/nx/.commandcode/plugins/cache/sc'}, None, None, 'commandcode', 'commandcode', None),  # main: enforcer claude
    ('file[.commandcode]', {}, '.commandcode', None, 'commandcode', 'commandcode', None),  # main: enforcer claude
    ('cpr[.dsh]', {'CLAUDE_PLUGIN_ROOT': '/nx/.dsh/plugins/cache/sc'}, None, None, 'dsh', 'dsh', 'dsh'),
    ('file[.dsh]', {}, '.dsh', None, 'dsh', 'dsh', 'dsh'),
    ('cpr[.ohdsh]', {'CLAUDE_PLUGIN_ROOT': '/nx/.ohdsh/plugins/cache/sc'}, None, None, 'dsh', 'dsh', 'dsh'),
    ('file[.ohdsh]', {}, '.ohdsh', None, 'dsh', 'dsh', 'dsh'),
    ('cpr[.cline]', {'CLAUDE_PLUGIN_ROOT': '/nx/.cline/plugins/cache/sc'}, None, None, 'cline', 'cline', None),
    ('file[.cline]', {}, '.cline', None, 'cline', 'cline', None),
    ('cpr[.opencode]', {'CLAUDE_PLUGIN_ROOT': '/nx/.opencode/plugins/cache/sc'}, None, None, 'opencode', 'opencode', None),
    ('file[.opencode]', {}, '.opencode', None, 'opencode', 'opencode', None),
    ('cpr[.claude]', {'CLAUDE_PLUGIN_ROOT': '/nx/.claude/plugins/cache/sc'}, None, None, 'claude', 'claude', None),
    ('file[.claude]', {}, '.claude', None, 'claude', 'claude', None),
    ('cpr[plain]', {'CLAUDE_PLUGIN_ROOT': '/nx/plain/plugins/cache/sc'}, None, None, 'claude', 'claude', None),
    ('file[plain]', {}, 'plain', None, 'claude', 'claude', None),
    ('cpr-empty', {'CLAUDE_PLUGIN_ROOT': ''}, '.codex', None, 'codex', 'codex', None),
    ('cpr-literal', {'CLAUDE_PLUGIN_ROOT': '$HOME/.claude'}, '.codex', None, 'codex', 'codex', None),
    ('cpr-relative', {'CLAUDE_PLUGIN_ROOT': '.omp/x'}, None, None, 'claude', 'claude', None),
    ('cpr-claude+file-zcode', {'CLAUDE_PLUGIN_ROOT': '/nx/.claude/plugins/cache/sc'}, '.zcode', None, 'claude', 'claude', None),  # main: ledger zcode
    ('cpr-claude+file-dsh', {'CLAUDE_PLUGIN_ROOT': '/nx/.claude/plugins/cache/sc'}, '.dsh', None, 'claude', 'claude', None),  # main: ledger dsh
    ('cpr-dsh+file-zcode', {'CLAUDE_PLUGIN_ROOT': '/nx/.dsh/plugins/cache/sc'}, '.zcode', None, 'dsh', 'dsh', 'dsh'),  # main: ledger zcode
    ('cpr-plain+file-codex', {'CLAUDE_PLUGIN_ROOT': '/nx/plain/plugins/cache/sc'}, '.codex', None, 'codex', 'codex', None),
    ('cpr-codex+file-omp', {'CLAUDE_PLUGIN_ROOT': '/nx/.codex/plugins/cache/sc'}, '.omp', None, 'codex', 'codex', None),
    ('cpr-omp-then-zcode-in-one-path', {'CLAUDE_PLUGIN_ROOT': '/nx/.omp/x/.zcode/y'}, None, None, 'omp', 'omp', None),  # main: ledger zcode
    ('cpr-zcode-then-dsh-in-one-path', {'CLAUDE_PLUGIN_ROOT': '/nx/.dsh/x/.zcode/y'}, None, None, 'zcode', 'claude', 'zcode'),
    ('dsh-shell+file-zcode', {'DSH_SHELL': '1'}, '.zcode', None, 'dsh', 'dsh', 'dsh'),  # main: ledger zcode
    ('ompcode+file-zcode', {'OMPCODE': '1'}, '.zcode', None, 'omp', 'omp', None),  # main: ledger zcode
    ('ompcode+cpr-dsh', {'OMPCODE': '1', 'CLAUDE_PLUGIN_ROOT': '/nx/.dsh/plugins/cache/sc'}, None, None, 'omp', 'omp', None),  # main: ledger dsh
    ('payload-omp+dsh-shell', {'DSH_SHELL': '1'}, None, 'omp', 'dsh', 'dsh', 'omp'),
    ('payload-zcode+explicit-omp', {'SKILL_CONCIERGE_HARNESS': 'omp'}, None, 'zcode', 'omp', 'omp', 'zcode'),
]


def _file_for(marker):
    return f"/nx/{marker}/plugin/hooks/scripts/x.py" if marker else "/nx/repo/hooks/scripts/x.py"


def _load(name, log_dir):
    saved = dict(os.environ)
    for k in KEYS:
        os.environ.pop(k, None)
    os.environ["SKILL_CONCIERGE_LOG"] = str(log_dir)
    try:
        spec = importlib.util.spec_from_file_location(f"{name}_harness_table", HOOKS / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        os.environ.clear()
        os.environ.update(saved)


@pytest.fixture(scope="module")
def hooks(tmp_path_factory):
    log = tmp_path_factory.mktemp("log")
    return {name: _load(name, log) for name in ("harness", "enforcer", "doctrine", "ledger")}


@pytest.fixture
def case_env(monkeypatch):
    def apply(env):
        for k in KEYS:
            monkeypatch.delenv(k, raising=False)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
    return apply


def _ids():
    return [row[0] for row in TABLE]


@pytest.mark.parametrize("row", TABLE, ids=_ids())
def test_detector(row, hooks, case_env):
    _id, env, marker, _payload, enforcer, _doctrine, _ledger = row
    case_env(env)
    assert hooks["harness"].running_harness(_file_for(marker)) == enforcer


@pytest.mark.parametrize("row", TABLE, ids=_ids())
def test_enforcer(row, hooks, case_env, monkeypatch):
    _id, env, marker, _payload, enforcer, _doctrine, _ledger = row
    case_env(env)
    monkeypatch.setattr(hooks["enforcer"], "__file__", _file_for(marker))
    assert hooks["enforcer"]._running_harness() == enforcer


@pytest.mark.parametrize("row", TABLE, ids=_ids())
def test_doctrine(row, hooks, case_env, monkeypatch):
    _id, env, marker, _payload, _enforcer, doctrine, _ledger = row
    doc = hooks["doctrine"]
    sample = doc._body(doc.DOCTRINE_PATH.read_text(encoding="utf-8"))
    monkeypatch.setattr(doc, "__file__", _file_for(None))
    ref = {}
    for h in RENDERINGS:
        case_env({"SKILL_CONCIERGE_HARNESS": h})
        ref.setdefault(doc._harness_adapt(sample), h)
    assert len(ref) == len(RENDERINGS)                  # every rendering is distinguishable
    case_env(env)
    monkeypatch.setattr(doc, "__file__", _file_for(marker))
    assert ref.get(doc._harness_adapt(sample)) == doctrine


@pytest.mark.parametrize("row", TABLE, ids=_ids())
def test_ledger(row, hooks, case_env, monkeypatch, tmp_path):
    _id, env, marker, payload, _enforcer, _doctrine, ledger = row
    led = hooks["ledger"]
    case_env(env)
    monkeypatch.setattr(led, "__file__", _file_for(marker))
    monkeypatch.setattr(led, "LOG_DIR", tmp_path)
    monkeypatch.setattr(led, "LEDGER", tmp_path / "ledger.log")
    p = {"hook_event_name": "UserPromptSubmit", "prompt": "hello there", "session_id": "s"}
    if payload:
        p["harness"] = payload
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(p)))
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    assert led.main() == 0
    row_out = json.loads((tmp_path / "ledger.log").read_text(encoding="utf-8"))
    expected_keys = {"t", "sid", "ev", "q"} | ({"harness"} if ledger else set())
    assert set(row_out) == expected_keys                # a Claude row still carries no field
    assert row_out.get("harness") == ledger


def test_symlink_loop_is_skipped_not_raised(hooks, case_env, tmp_path):
    (tmp_path / "a").symlink_to(tmp_path / "b")
    (tmp_path / "b").symlink_to(tmp_path / "a")
    case_env({"CLAUDE_PLUGIN_ROOT": str(tmp_path / "a" / "x")})
    assert hooks["harness"].running_harness(_file_for(".codex")) == "codex"


@pytest.mark.parametrize("script, stdin", [
    ("enforcer.py", {"hook_event_name": "UserPromptSubmit", "prompt": "deploy the app", "session_id": "s"}),
    ("doctrine.py", {"hook_event_name": "SessionStart", "session_id": "s"}),
    ("ledger.py", {"hook_event_name": "UserPromptSubmit", "prompt": "hello there", "session_id": "s"}),
])
def test_hook_without_the_detector_exits_0_silently(script, stdin, tmp_path):
    """A partial copy that lacks harness.py must never crash a turn (hooks are fail-silent)."""
    scripts = tmp_path / "hooks" / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy(HOOKS / script, scripts / script)
    env = {k: v for k, v in os.environ.items() if k not in KEYS}
    env.update({"SKILL_CONCIERGE_LOG": str(tmp_path / "log"), "ENFORCER_LEDGER": "0"})
    run = subprocess.run([sys.executable, str(scripts / script)], input=json.dumps(stdin),
                         capture_output=True, text=True, timeout=60, cwd=tmp_path, env=env)
    assert run.returncode == 0 and run.stdout == "" and "Traceback" not in run.stderr
    assert not (tmp_path / "log").exists()
