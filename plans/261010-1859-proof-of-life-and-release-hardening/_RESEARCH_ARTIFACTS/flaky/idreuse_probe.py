"""Probe: does trigger_filter._enforcer() skip the timeout setup for a *new* enforcer module that gets the
address (id) of a freed earlier one? Run from the worktree root: python3 <this file>."""
import gc
import os
import sys
from pathlib import Path

root = Path.cwd()
sys.path.insert(0, str(root / "scripts"))
sys.path.insert(0, str(root / "vendor" / "skill-search"))
for k in [k for k in os.environ if k.startswith(("ENFORCER_JEV_", "ENFORCER_EMBED_TIMEOUT", "ENFORCER_QDRANT_TIMEOUT"))]:
    del os.environ[k]
import jev_client  # noqa: E402
import trigger_filter as tf  # noqa: E402

hits = misses = 0
for i in range(40):
    jev_client._ENF = None
    enf = tf._enforcer()
    ok = enf.EMBED_TIMEOUT_S == 15.0 and enf.QDRANT_TIMEOUT_S == 15.0
    hits += ok
    misses += not ok
    if not ok:
        print(f"iter {i}: id={id(enf):#x} EMBED_TIMEOUT_S={enf.EMBED_TIMEOUT_S}")
    del enf
    if i % 2:
        gc.collect()          # the cycle collector frees the dropped module; its address can be handed out again
print(f"timeouts applied: {hits}, silently skipped: {misses}")
