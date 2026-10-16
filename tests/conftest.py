"""Tests never inherit the machine's Jev routing. `~/.config/harness-env.sh` exports the live bench, its keys,
its timeouts and JEVD_URL (the live jevd relay) into every shell, and several modules read them at import time, so a per-file `delenv` list misses
whatever was added after it was written. They are removed here, before collection, for the whole session; a test
that needs one sets it with `monkeypatch.setenv`. `SMOKE_ADVISORY` (the owner's advisory harness list, set in the same
file) goes too: the smoke tests assert the strict default.
"""
import os

for _k in list(os.environ):
    if _k.startswith("ENFORCER_JEV_") or _k in ("TYPESAFE_API_KEY", "CMD_API_KEY", "JEVD_URL", "SMOKE_ADVISORY"):
        del os.environ[_k]

# Tests never read the machine's real Command Code model pool either. cmd_agent_bridge resolves a Claude
# tier alias against ~/.commandcode/config.json by default; a test that needs a named pool monkeypatches
# AGENT_BRIDGE_CONFIG at a fixture file (see test_commandcode_agent_bridge.py).
os.environ["AGENT_BRIDGE_CONFIG"] = "/nonexistent/cmd-agent-bridge-tests/config.json"
