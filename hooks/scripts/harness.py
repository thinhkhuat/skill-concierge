"""skill-concierge — which harness is executing a hook.

The one detector enforcer.py, doctrine.py and ledger.py share (they each kept a copy, and the
copies drifted). Stdlib-only. Each hook passes its own `__file__`, so the install-path marker is
read from the script that is running; each keeps its own use of the answer (the ledger stamps
only ZCode and DSH from it).
"""
from __future__ import annotations

import os
from pathlib import Path

# SKILL_CONCIERGE_HARNESS values (set by the adapters) -> harness name.
_ALIASES = {
    "claude": "claude", "codex": "codex",
    "commandcode": "commandcode", "cmd": "commandcode", "command-code": "commandcode",
    "omp": "omp", "oh-my-pi": "omp",
    "zcode": "zcode", "z-code": "zcode",
    "dsh": "dsh", "deepseek-harness": "dsh", "oh-dsh": "dsh", "ohdsh": "dsh",
    "cline": "cline", "cline-cli": "cline",
    "opencode": "opencode", "open-code": "opencode",
}
# Install-path markers, first match wins within one path. `.commandcode` matters to doctrine:
# Command Code runs its SessionStart hooks without SKILL_CONCIERGE_HARNESS (caveats §23).
_MARKERS = (("omp", ".omp"), ("codex", ".codex"), ("zcode", ".zcode"),
            ("commandcode", ".commandcode"), ("dsh", ".dsh"), ("dsh", ".ohdsh"),
            ("cline", ".cline"), ("opencode", ".opencode"), ("claude", ".claude"))


def running_harness(script: str) -> str:
    """One of the _ALIASES harness names. Precedence: a known SKILL_CONCIERGE_HARNESS value >
    native env signals > the install-path marker of CLAUDE_PLUGIN_ROOT, then of `script` >
    'claude'. The native signals (`OMPCODE=1`, an absolute `ZCODE_PLUGIN_ROOT`, `DSH_SHELL=1`)
    outrank the markers because OMP and ZCode also set Claude's own. An empty or relative path
    is never probed (`Path("").resolve()` is the cwd)."""
    explicit = _ALIASES.get(os.environ.get("SKILL_CONCIERGE_HARNESS", "").strip().lower())
    if explicit:
        return explicit
    if os.environ.get("OMPCODE", "").strip() == "1":
        return "omp"
    zpr = os.environ.get("ZCODE_PLUGIN_ROOT", "").strip()
    if zpr and os.path.isabs(zpr):
        return "zcode"
    if os.environ.get("DSH_SHELL", "").strip() == "1":
        return "dsh"
    for cand in (os.environ.get("CLAUDE_PLUGIN_ROOT"), script):
        if not cand or not os.path.isabs(cand):
            continue
        try:
            resolved = str(Path(cand).resolve())
        except (OSError, RuntimeError):   # RuntimeError: a symlink loop before Python 3.13
            continue
        for name, marker in _MARKERS:
            if f"{os.sep}{marker}{os.sep}" in resolved:
                return name
    return "claude"
