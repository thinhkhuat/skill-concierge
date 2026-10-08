"""flywheel_llm.run_batch: the driver llm_triggers, llm_capsules and llm_eval_gen share.

Pinned: skills that no longer need work are skipped; a chat failure becomes an error record and never
reaches merge; merge always runs in the calling thread (the corpus and cache files stay single-writer);
a sequential run merges in name order.
"""
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import flywheel_llm  # noqa: E402


@pytest.mark.parametrize("workers", [1, 4])
def test_run_batch(workers, capsys):
    main, merged = threading.get_ident(), []

    def net(name):
        return name, (OSError("refused") if name == "b" else {"reply": name})

    def merge(name, reply):
        assert threading.get_ident() == main, "merge must run in the calling thread"
        merged.append(name)
        return {"name": name, "status": "generated", "detail": reply["reply"]}

    out = flywheel_llm.run_batch(["a", "b", "c", "d", "e"], lambda n: n != "c", net, merge, workers)

    assert sorted(out, key=lambda r: r["name"]) == [
        {"name": "a", "status": "generated", "detail": "a"},
        {"name": "b", "status": "error", "detail": "chat failed: refused"},
        {"name": "d", "status": "generated", "detail": "d"},
        {"name": "e", "status": "generated", "detail": "e"},
    ]
    assert "WARN: skipping b: chat failed (refused)" in capsys.readouterr().out
    if workers == 1:
        assert merged == ["a", "d", "e"]
    else:
        assert sorted(merged) == ["a", "d", "e"]
