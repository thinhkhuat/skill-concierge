"""Remove the skill-search row the old file-hook installer (ADR-0051) merged into Cline's
global cline_mcp_settings.json.

usage: mcp_row.py <cline_mcp_settings.json>

Since ADR-0086 the Agent Plugin provides the server as skill-concierge.skill-search, so a
leftover row would register the same server twice. A row that is not ours (another command
or launcher) is left alone. Backs the settings file up before any write; refuses to touch
invalid JSON.
"""
import json
import os
import shutil
import sys
import time
from pathlib import Path

import safe_write


def ours(row) -> bool:
    args = row.get("args") if isinstance(row, dict) else None
    return isinstance(args, list) and bool(args) and str(args[0]).endswith("/bin/skill-search-mcp")


def main() -> int:
    os.umask(0o077)   # the backup holds the user's MCP config; never world-readable, even briefly
    cfg_path = Path(sys.argv[1])
    if not cfg_path.exists():
        return 0
    try:
        existing = json.loads(cfg_path.read_text(encoding="utf-8"))
    except ValueError:
        print(f"!! {cfg_path} is not valid JSON — refusing to touch it; edit it by hand.",
              file=sys.stderr)
        return 1
    servers = existing.get("mcpServers") if isinstance(existing, dict) else None
    row = servers.get("skill-search") if isinstance(servers, dict) else None
    if not row:
        return 0
    if not ours(row):
        print("    skill-search MCP row is not this installer's — left alone")
        return 0
    del servers["skill-search"]
    backup = cfg_path.with_suffix(".json.bak-skill-concierge-" + time.strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(cfg_path, backup)
    print(f"    backup: {backup.name}")
    safe_write.write_text(cfg_path, json.dumps(existing, indent=2, ensure_ascii=False) + "\n")
    print(f"    removed old mcpServers.skill-search row → {cfg_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
