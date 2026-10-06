"""Tests never inherit the machine's Jev routing. `~/.config/harness-env.sh` exports the live bench, its keys,
its timeouts and JEVD_URL (the live jevd relay) into every shell, and several modules read them at import time, so a per-file `delenv` list misses
whatever was added after it was written. They are removed here, before collection, for the whole session; a test
that needs one sets it with `monkeypatch.setenv`.
"""
import os

for _k in list(os.environ):
    if _k.startswith("ENFORCER_JEV_") or _k in ("TYPESAFE_API_KEY", "CMD_API_KEY", "JEVD_URL"):
        del os.environ[_k]
