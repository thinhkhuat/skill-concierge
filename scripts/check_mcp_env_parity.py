"""Env parity between the MCP descriptors (ADR-0035).

`.mcp.json` (Claude) and the Codex, Command Code, OMP, ZCode and DSH descriptors each carry an env
block for the SAME engine, and `auto_reindex._mcp_env()` forwards from `.mcp.json` only — so a key
changed in one file but not another silently splits the harnesses' server configuration. This check
fails on any key present in `.mcp.json` and another descriptor with different values, and on any key
present only in another descriptor (the Claude file is the source of truth; the others may omit keys
— see the Codex descriptor's own comment for the deliberate SKILL_SERVER_RECORDS omission — but never
invent them). The Codex descriptor is required; the adapter descriptors are checked when present.

Wired into driftcheck.json command_checks. Exit 0 = in sync.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# (descriptor, keys whose value may differ from .mcp.json, note on a key .mcp.json lacks)
DESCRIPTORS = [
    (".codex-plugin/mcp.json", (), " — the Claude file is the source of truth"),
    ("adapters/commandcode/mcp.json", (), ""),
    ("adapters/omp/mcp.json", (), ""),
    ("adapters/zcode/mcp.json", (), ""),
    ("adapters/dsh/mcp.json", (), ""),
    # Same rule as DSH: the harness stamp is written by install.sh into Hermes's own
    # config.yaml, so it never appears in this descriptor (a key .mcp.json lacks fails here).
    ("adapters/hermes/mcp.json", (), ""),
]


# How each descriptor's harness is spelled in the status line, keyed by the descriptor path.
# One owner: a new adapter adds its row here and the message stays current without a second edit.
DISPLAY = {".codex-plugin/mcp.json": "Codex", "adapters/commandcode/mcp.json": "Command Code",
           "adapters/omp/mcp.json": "OMP", "adapters/zcode/mcp.json": "ZCode",
           "adapters/dsh/mcp.json": "DSH", "adapters/hermes/mcp.json": "Hermes"}


def env_of(path, server="skill-search"):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))["mcpServers"][server].get("env", {})


def main() -> int:
    claude, codex = env_of(".mcp.json"), env_of(".codex-plugin/mcp.json")
    bad = []
    for path, may_differ, note in DESCRIPTORS:
        if not (ROOT / path).exists():
            continue
        for k, v in env_of(path).items():
            if k not in claude:
                bad.append(f"{k}: only in {path} ('{v}'){note}")
            elif k not in may_differ and claude[k] != v:
                bad.append(f"{k}: '{claude[k]}' (.mcp.json) != '{v}' ({path})")
    if bad:
        print("mcp-env-parity FAIL:")
        for b in bad:
            print("  " + b)
        return 1
    omitted = sorted(set(claude) - set(codex))
    checked = ["Claude"] + [DISPLAY[p] for p, _m, _n in DESCRIPTORS if (ROOT / p).exists()]
    where = ", ".join(checked[:-1]) + f" and {checked[-1]}" if len(checked) > 1 else checked[0]
    print(f"mcp-env-parity OK: {len(codex)} shared keys in lockstep across {where}"
          + (f"; codex omits {omitted} (deliberate — see descriptor comment)" if omitted else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
