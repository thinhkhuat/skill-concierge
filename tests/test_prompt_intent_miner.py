"""The actionability-gate corpus miner (`scripts/build_prompt_intent.py`) labels a typed prompt by
what the agent did next. A harness message that hands the agent work (a cross-session message, a
notification, a scheduled task, a slash command) is not a typed prompt and ends the turn, so the
tool calls it triggers never label the prompt before it."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_prompt_intent as B  # noqa: E402


def test_the_miner_selftest_passes():
    assert B._selftest() == 0
