"""The Command Code mod, driven the way Command Code's mod host drives it, against stub hook scripts.

Pins the governance contract: `transformContext` governs each prompt exactly once (one enforcer
run, one `turn` row) in print mode and in the TUI, ranks on the typed text when IDE context or
another mod prepended text, re-applies the cached menu on every model call of a tool loop, and
leaves Command Code's own user messages (automated, summary, meta) and image-only prompts alone.
`transformInput` only records the typed text and logs a typed slash command as a `manual` row.
The session id never comes from `sessions.leafId()`, a session-tree entry id that changes with
every appended entry.
"""
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "adapters" / "commandcode" / "skill-concierge.mod.ts"
HARNESS = Path(__file__).with_name("commandcode_mod_harness.mjs")
NODE = shutil.which("node")

STUB = '''import json, os, sys
name = os.path.basename(__file__)
raw = sys.stdin.read()
with open(os.path.join(os.environ["STUB_LOG"], name + ".jsonl"), "a") as f:
    f.write(json.dumps({"stdin": raw, "harness": os.environ.get("SKILL_CONCIERGE_HARNESS")}) + "\\n")
p = json.loads(raw or "{}")
if name == "enforcer.py":
    print(json.dumps({"hookSpecificOutput": {"additionalContext": "MENU for: " + p["prompt"]}}))
'''
SCRIPTS = ["enforcer.py", "ledger.py", "skill_exclusions.py"]
HOOK_OPEN = '<hook_context source="skill-concierge">'

pytestmark = pytest.mark.skipif(NODE is None, reason="node is required for the Command Code mod tests")


@pytest.fixture()
def fake(tmp_path):
    root, log = tmp_path / "repo", tmp_path / "log"
    (root / "adapters" / "commandcode").mkdir(parents=True)
    (root / "hooks" / "scripts").mkdir(parents=True)
    log.mkdir()
    shutil.copy(MOD, root / "adapters" / "commandcode" / MOD.name)
    for name in SCRIPTS:
        (root / "hooks" / "scripts" / name).write_text(STUB)

    def drive(calls):
        e = {**os.environ, "STUB_LOG": str(log), "SKILL_CONCIERGE_ROOT": str(root)}
        e.pop("COMMANDCODE_SESSION_ID", None)
        r = subprocess.run([NODE, str(HARNESS), str(root / "adapters" / "commandcode" / MOD.name)],
                           input=json.dumps({"calls": calls}),
                           capture_output=True, text=True, timeout=120, env=e)
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout)

    def logged(name, expect=0):
        """Rows a stub script received. Ledger writers are detached: wait for `expect` rows, then
        give a stray extra row time to land, so a count of zero or of `expect` is a real count."""
        path = log / f"{name}.jsonl"
        read = lambda: [json.loads(json.loads(x)["stdin"]) for x in path.read_text().splitlines()] \
            if path.exists() else []
        deadline = time.time() + 5
        while len(read()) < expect and time.time() < deadline:
            time.sleep(0.05)
        time.sleep(0.4)
        return read()

    return drive, logged


_clock = iter(range(1000, 10**6))


def user(content, **meta):
    """A stored user message: Command Code stamps `meta.createdAt` (and `source`) on every one."""
    if isinstance(content, str):
        content = [{"type": "text", "text": content}]
    return {"role": "user", "content": content, "meta": {"source": "user", "createdAt": next(_clock), **meta}}


def assistant_tool_call():
    return {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "read_file", "input": {}}]}


def tool_results():
    return {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1",
                                         "content": [{"type": "text", "text": "file body"}]}],
            "meta": {"createdAt": next(_clock)}}


def context(messages, sid="S1"):
    return {"hook": "transformContext", "messages": messages, "state": {"sessionId": sid}}


def menus(res):
    """Every text block of the returned messages that holds the injected menu."""
    return [b["text"] for m in res for b in m["content"] if b.get("type") == "text" and HOOK_OPEN in b["text"]]


def turn_rows(rows):
    return [r for r in rows if not r["prompt"].startswith("/")]


def test_print_mode_prompt_is_governed_once(fake):
    drive, logged = fake
    msgs = [user("fix the login bug")]
    res = drive([context(msgs)])[0]
    assert len(menus(res)) == 1 and "MENU for: fix the login bug" in menus(res)[0]
    assert [r["prompt"] for r in logged("enforcer.py", 1)] == ["fix the login bug"]
    assert [r["prompt"] for r in turn_rows(logged("ledger.py", 1))] == ["fix the login bug"]


def test_typed_prompt_then_context_is_governed_once(fake):
    drive, logged = fake
    msgs = [user("fix the login bug")]
    out = drive([{"hook": "transformInput", "text": "fix the login bug"}, context(msgs)])
    assert out[0] == {"action": "continue"}, "transformInput must not rewrite the prompt"
    assert len(menus(out[1])) == 1
    assert len(logged("enforcer.py", 1)) == 1
    assert len(turn_rows(logged("ledger.py", 1))) == 1


def test_ide_context_prefixed_message_ranks_on_the_typed_text(fake):
    drive, logged = fake
    typed = "add a dark mode toggle"
    msgs = [user(f"<ide_selection>The user opened src/app.ts</ide_selection>\n\n{typed}")]
    out = drive([{"hook": "transformInput", "text": typed}, context(msgs)])
    assert len(menus(out[1])) == 1
    assert [r["prompt"] for r in logged("enforcer.py", 1)] == [typed]
    assert [r["prompt"] for r in turn_rows(logged("ledger.py", 1))] == [typed]


def test_tool_loop_runs_the_enforcer_once_and_reapplies_the_menu(fake):
    drive, logged = fake
    prompt = user("fix the login bug")
    first = [prompt]
    second = [prompt, assistant_tool_call(), tool_results()]
    out = drive([{"hook": "transformInput", "text": "fix the login bug"}, context(first), context(second)])
    assert len(menus(out[1])) == 1 and len(menus(out[2])) == 1
    assert menus(out[1]) == menus(out[2])
    assert out[2][0]["content"][0]["text"].startswith(HOOK_OPEN), "menu goes on the prompt, not the tool results"
    assert out[2][2] == second[2], "the tool-results message is left alone"
    assert len(logged("enforcer.py", 1)) == 1
    assert len(turn_rows(logged("ledger.py", 1))) == 1


def test_same_prompt_text_in_a_later_turn_is_governed_again(fake):
    drive, logged = fake
    t1, t2 = user("continue"), user("continue")
    drive([context([t1]), context([t1, assistant_tool_call(), tool_results(), t2])])
    assert len(logged("enforcer.py", 2)) == 2


@pytest.mark.parametrize("meta", [
    {"isAutomated": True, "source": "stop_hook"},
    {"isSummary": True},
    {"isMeta": True, "isAutomated": True, "source": "scheduled-cron:abc"},
    {"isMeta": True, "source": "mod:some-mod"},
], ids=["automated", "summary", "meta", "mod-message"])
def test_harness_generated_message_is_not_governed(fake, meta):
    drive, logged = fake
    earlier = user("fix the login bug")
    generated = user("Tests are still failing, keep going", **meta)
    msgs = [earlier, {"role": "assistant", "content": [{"type": "text", "text": "done"}]}, generated]
    res = drive([context(msgs)])[0]
    assert res == msgs
    assert logged("enforcer.py") == []
    assert logged("ledger.py") == []


def test_image_only_prompt_neither_governs_nor_reuses_an_earlier_menu(fake):
    drive, logged = fake
    earlier = user("fix the login bug")
    image = user([{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}}])
    reply = {"role": "assistant", "content": [{"type": "text", "text": "done"}]}
    out = drive([context([earlier]), context([earlier, reply, image])])
    assert len(menus(out[0])) == 1
    assert menus(out[1]) == [] and out[1] == [earlier, reply, image]
    assert len(logged("enforcer.py", 1)) == 1
    assert len(turn_rows(logged("ledger.py", 1))) == 1


def test_typed_slash_command_logs_a_manual_row_and_is_never_ranked(fake):
    drive, logged = fake
    msgs = [user("/review the diff")]
    out = drive([{"hook": "transformInput", "text": "/review the diff"}, context(msgs), context(msgs)])
    assert out[0] == {"action": "continue"}
    assert out[1] == msgs and out[2] == msgs
    assert [r["prompt"] for r in logged("ledger.py", 1)] == ["/review the diff"]
    assert logged("enforcer.py") == []


def test_session_id_comes_from_the_state_not_from_the_tree_leaf(fake):
    drive, logged = fake
    msgs = [user("fix the login bug")]
    drive([context(msgs, sid="SESSION-1"),
           {"event": "skill_loaded", "payload": {"name": "debugging"}},
           {"event": "tool_completed", "payload": {"toolName": "skill-search__get_skill", "input": {"name": "x"}}}])
    assert [r["session_id"] for r in logged("enforcer.py", 1)] == ["SESSION-1"]
    assert {r["session_id"] for r in logged("ledger.py", 3)} == {"SESSION-1"}


def test_session_id_falls_back_to_run_start_then_prefers_ctx(fake):
    drive, logged = fake
    drive([{"event": "run_start", "payload": {"sessionId": "RUN-1"}},
           {"hook": "transformInput", "text": "/help"},
           {"hook": "transformInput", "text": "/status", "ctx": {"sessionId": "CTX-1"}},
           {"event": "skill_loaded", "payload": {"name": "debugging"}}])
    # detached writers land in any order
    assert sorted(r["session_id"] for r in logged("ledger.py", 3)) == ["CTX-1", "CTX-1", "RUN-1"]


def test_caches_are_bounded(fake):
    drive, logged = fake
    first = user("the first prompt")
    others = [context([user(f"prompt number {n}")]) for n in range(65)]
    drive([context([first])] + others + [context([first])])
    prompts = [r["prompt"] for r in logged("enforcer.py", 67)]
    assert prompts.count("the first prompt") == 2, "the oldest cached prompt must be evicted after 64 newer ones"
