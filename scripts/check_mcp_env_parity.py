#!/usr/bin/env python3
"""Env parity between the two MCP descriptors (ADR-0035).

`.mcp.json` (Claude) and `.codex-plugin/mcp.json` (Codex) each carry an env block for the SAME
engine, and `auto_reindex._mcp_env()` forwards from `.mcp.json` only — so a key changed in one
file but not the other silently splits the two harnesses' server configuration. This check fails
on any key present in BOTH files with different values, and on any key present only in the
CODEX file (the Claude file is the source of truth; the codex file may omit keys — see the
descriptor's own comment for the deliberate SKILL_SERVER_RECORDS omission — but never invent
them).

Wired into driftcheck.json command_checks. Exit 0 = in sync.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def env_of(path, server="skill-search"):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))["mcpServers"][server].get("env", {})


def main() -> int:
    claude, codex = env_of(".mcp.json"), env_of(".codex-plugin/mcp.json")
    bad = []
    for k, v in codex.items():
        if k not in claude:
            bad.append(f"{k}: only in .codex-plugin/mcp.json ('{v}') — the Claude file is the source of truth")
        elif claude[k] != v:
            bad.append(f"{k}: '{claude[k]}' (.mcp.json) != '{v}' (.codex-plugin/mcp.json)")
    if bad:
        print("mcp-env-parity FAIL:")
        for b in bad:
            print("  " + b)
        return 1
    omitted = sorted(set(claude) - set(codex))
    print(f"mcp-env-parity OK: {len(codex)} shared keys in lockstep"
          + (f"; codex omits {omitted} (deliberate — see descriptor comment)" if omitted else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
