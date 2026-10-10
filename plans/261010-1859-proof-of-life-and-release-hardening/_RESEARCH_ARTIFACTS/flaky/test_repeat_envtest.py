"""Runs the flaky test body 40 times inside ONE process (fresh enforcer module each time, as in a full run).
Run: PYTHONPATH=<worktree>/tests pytest <this file> (see repeat.sh)."""
import pytest
import test_trigger_filter as T

env = T.env


@pytest.mark.parametrize("n", range(40))
def test_repeat(env, monkeypatch, n):
    T.test_enforcer_setup_leaves_the_process_environment_alone(env, monkeypatch)
