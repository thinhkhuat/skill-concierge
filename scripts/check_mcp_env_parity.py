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
    # Command Code and OMP expand the standard path rather than a literal ${HOME}.
    ("adapters/commandcode/mcp.json", ("SKILL_SERVER_RECORDS",), ""),
    ("adapters/omp/mcp.json", ("SKILL_SERVER_RECORDS",), ""),
    ("adapters/zcode/mcp.json", (), ""),
    ("adapters/dsh/mcp.json", (), ""),
]


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
    print(f"mcp-env-parity OK: {len(codex)} shared keys in lockstep across Claude, Codex, "
          f"Command Code, OMP, ZCode, and DSH"
          + (f"; codex omits {omitted} (deliberate — see descriptor comment)" if omitted else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
