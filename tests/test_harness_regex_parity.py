"""ADR-0054: the harness-message regex is duplicated (the keep-off generator must not import
the hook). Pin byte-equality of the two patterns so a shape added on one side cannot silently
drift from the other, and pin the evidenced shapes + the pasted-mid-prompt negative on both."""
import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _both():
    # The enforcer resolves KEEPOFF/BLOCKLIST/etc. at import; point the seams at empty temp
    # files is unnecessary for a regex-only read, but keep the import side-effect free of the
    # live ledger by never calling main().
    os.environ.setdefault("SKILL_CONCIERGE_LOG", "/tmp/sc-regex-parity-logs")
    enf = _load(ROOT / "hooks" / "scripts" / "enforcer.py", "enforcer_under_test")
    sys.path.insert(0, str(ROOT / "scripts"))
    gen = _load(ROOT / "scripts" / "build_keep_off.py", "build_keep_off_under_test")
    return enf, gen


def test_patterns_are_byte_identical():
    enf, gen = _both()
    assert enf._HARNESS_MSG_RE.pattern == gen._HARNESS_MSG_RE.pattern


def test_evidenced_shapes_fire_and_pasted_block_does_not():
    enf, gen = _both()
    fire = [
        "<task-notification>\n<task-id>b1</task-id>\n<summary>Monitor event</summary>",
        "<system-reminder> Last turn had no tool call → session idle.",
        "<cross-session-message from=\"uds:/tmp/x.sock\"> FYI",
        "<file name=\"/var/folders/vz/T/omp-msum-o650bgz2.txt\">\nSummarize the following agent turn",
    ]
    off = [
        "look at this <task-notification> I pasted and tell me what it means",
        "commit & push pls and ensure a clean worktree afterwards",
    ]
    for rx in (enf._HARNESS_MSG_RE, gen._HARNESS_MSG_RE):
        assert all(rx.match(p) for p in fire)
        assert not any(rx.match(p) for p in off)
