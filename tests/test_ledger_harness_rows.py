"""Ledger rows the harness adapters depend on. The DSH plugin writes a `search` row when the model
calls search_skills (without it a live smoke cannot see that the MCP reached the model) and a
`get_skill` row for a deep pull (driven as the real plugin module under Node with a stub ctx), and a
turn row keeps OpenCode's `parent_lookup` marker."""
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "adapters" / "dsh" / "skill-concierge.dsh.ts"

DRIVER = r"""
const [plugin, toolName, isError] = process.argv.slice(2);
// DSH loads the plugin as CommonJS, where __dirname exists; give the ESM import the same.
globalThis.__dirname = new URL(".", plugin).pathname;
const mod = await import(plugin);
const handlers = {};
mod.default({ on: (ev, fn) => { handlers[ev] = fn; } });
const exec = { name: toolName, arguments: { query: "haiku about weather", name: "x" },
               agent: { session: { header: { id: "dsh-test-session" } } } };
await handlers["tools/post-execute"](exec, { content: [], isError: isError === "1" }, async () => ({}));
"""


def _rows(tool_name: str, tmp_path: Path, is_error: bool = False) -> list[dict]:
    logs = tmp_path / "logs"
    driver = tmp_path / "driver.mjs"
    driver.write_text(DRIVER)
    env = dict(os.environ, SKILL_CONCIERGE_LOG=str(logs), HOME=str(tmp_path))
    subprocess.run(["node", str(driver), PLUGIN.as_uri(), tool_name, "1" if is_error else "0"], env=env, check=True,
                   capture_output=True, timeout=60)
    ledger = logs / "skill-invocation-ledger.log"
    for _ in range(100):  # the ledger write is detached
        if ledger.exists() and ledger.read_text().strip():
            break
        time.sleep(0.1)
    return [json.loads(l) for l in ledger.read_text().splitlines()] if ledger.exists() else []


pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def test_a_search_skills_call_writes_a_search_row(tmp_path):
    rows = _rows("skill-search__search_skills", tmp_path)
    assert [(r["ev"], r.get("harness"), r["sid"]) for r in rows] == [("search", "dsh", "dsh-test-session")]


def test_a_get_skill_call_still_writes_a_get_skill_row(tmp_path):
    rows = _rows("skill-search__get_skill", tmp_path)
    assert [(r["ev"], r.get("name")) for r in rows] == [("get_skill", "x")]


def test_a_failed_search_writes_no_row(tmp_path):
    assert _rows("skill-search__search_skills", tmp_path, is_error=True) == []


def test_an_unrelated_tool_writes_nothing(tmp_path):
    assert _rows("bash", tmp_path) == []


def _ledger(payload: dict, tmp_path: Path) -> list[dict]:
    env = dict(os.environ, SKILL_CONCIERGE_LOG=str(tmp_path / "l"))
    subprocess.run(["python3", str(ROOT / "hooks" / "scripts" / "ledger.py")], input=json.dumps(payload),
                   text=True, env=env, check=True, timeout=30)
    path = tmp_path / "l" / "skill-invocation-ledger.log"
    return [json.loads(l) for l in path.read_text().splitlines()]


def test_a_turn_row_keeps_the_opencode_parent_lookup_marker(tmp_path):
    base = {"hook_event_name": "UserPromptSubmit", "session_id": "s", "prompt": "hi", "harness": "opencode"}
    assert _ledger({**base, "parent_lookup": "pending"}, tmp_path)[-1]["parent_lookup"] == "pending"
    assert "parent_lookup" not in _ledger({**base, "parent_lookup": "landed"}, tmp_path)[-1]


OMP_EXT = ROOT / "adapters" / "omp" / "skill-concierge.ext.ts"
OMP_DRIVER = r"""
const [plugin, isError] = process.argv.slice(2);
globalThis.__dirname = new URL(".", plugin).pathname;
const handlers = {};
(await import(plugin)).default({ on: (ev, fn) => { handlers[ev] = fn; } });
handlers["tool_result"]({ toolName: "mcp__skill_concierge_skill_search_search_skills", input: {},
                          content: [], isError: isError === "1" }, { sessionManager: { getSessionId: () => "omp-s" } });
"""


def _omp_rows(tmp_path: Path, is_error: bool) -> list[dict]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    logs, driver = tmp_path / "logs", tmp_path / "omp.mjs"
    driver.write_text(OMP_DRIVER)
    env = dict(os.environ, SKILL_CONCIERGE_LOG=str(logs), HOME=str(tmp_path))
    subprocess.run(["node", str(driver), OMP_EXT.as_uri(), "1" if is_error else "0"], env=env, check=True,
                   capture_output=True, timeout=60)
    ledger = logs / "skill-invocation-ledger.log"
    for _ in range(100):  # the ledger write is detached
        if ledger.exists() and ledger.read_text().strip():
            break
        time.sleep(0.1)
    return [json.loads(l) for l in ledger.read_text().splitlines()] if ledger.exists() else []


def test_omp_logs_a_successful_search_and_skips_a_failed_one(tmp_path):
    assert [r["ev"] for r in _omp_rows(tmp_path / "ok", False)] == ["search"]
    assert _omp_rows(tmp_path / "err", True) == []
