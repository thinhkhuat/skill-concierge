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
    cmd_env = env_of("adapters/commandcode/mcp.json") if (ROOT / "adapters/commandcode/mcp.json").exists() else None
    omp_env = env_of("adapters/omp/mcp.json") if (ROOT / "adapters/omp/mcp.json").exists() else None
    bad = []
    for k, v in codex.items():
        if k not in claude:
            bad.append(f"{k}: only in .codex-plugin/mcp.json ('{v}') — the Claude file is the source of truth")
        elif claude[k] != v:
            bad.append(f"{k}: '{claude[k]}' (.mcp.json) != '{v}' (.codex-plugin/mcp.json)")
    if cmd_env is not None:
        for k, v in cmd_env.items():
            if k not in claude:
                bad.append(f"{k}: only in adapters/commandcode/mcp.json ('{v}')")
            elif k == "SKILL_SERVER_RECORDS":
                # commandcode expands standard path rather than literal ${HOME}
                continue
            elif claude[k] != v:
                bad.append(f"{k}: '{claude[k]}' (.mcp.json) != '{v}' (adapters/commandcode/mcp.json)")
    if omp_env is not None:
        for k, v in omp_env.items():
            if k not in claude:
                bad.append(f"{k}: only in adapters/omp/mcp.json ('{v}')")
            elif k == "SKILL_SERVER_RECORDS":
                # omp, like commandcode, expands standard path rather than literal ${HOME}
                continue
            elif claude[k] != v:
                bad.append(f"{k}: '{claude[k]}' (.mcp.json) != '{v}' (adapters/omp/mcp.json)")
    zcode_env = env_of("adapters/zcode/mcp.json") if (ROOT / "adapters/zcode/mcp.json").exists() else None
    if zcode_env is not None:
        for k, v in zcode_env.items():
            if k not in claude:
                bad.append(f"{k}: only in adapters/zcode/mcp.json ('{v}')")
            elif claude[k] != v:
                bad.append(f"{k}: '{claude[k]}' (.mcp.json) != '{v}' (adapters/zcode/mcp.json)")
    dsh_env = env_of("adapters/dsh/mcp.json") if (ROOT / "adapters/dsh/mcp.json").exists() else None
    if dsh_env is not None:
        for k, v in dsh_env.items():
            if k not in claude:
                bad.append(f"{k}: only in adapters/dsh/mcp.json ('{v}')")
            elif claude[k] != v:
                bad.append(f"{k}: '{claude[k]}' (.mcp.json) != '{v}' (adapters/dsh/mcp.json)")
    cline_env = env_of("adapters/cline/mcp.json") if (ROOT / "adapters/cline/mcp.json").exists() else None
    if cline_env is not None:
        for k, v in cline_env.items():
            if k not in claude:
                bad.append(f"{k}: only in adapters/cline/mcp.json ('{v}')")
            elif claude[k] != v:
                bad.append(f"{k}: '{claude[k]}' (.mcp.json) != '{v}' (adapters/cline/mcp.json)")
    if bad:
        print("mcp-env-parity FAIL:")
        for b in bad:
            print("  " + b)
        return 1
    omitted = sorted(set(claude) - set(codex))
    print(f"mcp-env-parity OK: {len(codex)} shared keys in lockstep across Claude, Codex, "
          f"Command Code, OMP, ZCode, DSH, and Cline"
          + (f"; codex omits {omitted} (deliberate — see descriptor comment)" if omitted else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
