"""Build the Cline Agent Plugin (agent-plugins.org) from this checkout (ADR-0086).

usage: agent_plugin.py sync|check [dest]     (dest default: ~/.agents/plugins/skill-concierge)

sync  — write <dest>/plugin.json, <dest>/mcp.json and <dest>/skills/<name>/ from the repo,
        touching only files whose content changed; prune skills this tool added that the repo
        no longer has. Prints one summary line.
check — exit 0 when <dest> matches what sync would write, 1 (and the stale paths) otherwise.

Why a generated folder instead of a link to the repo: Cline accepts only the agent-plugins.org
SKILL.md frontmatter keys (name, description, license, compatibility, metadata,
allowed-tools) and rejects a skill carrying any other, and it expands no ${CLAUDE_PLUGIN_ROOT}.
The repo's skills also serve Claude Code, which reads user-invocable, argument-hint and
next-skills, so the copies drop those keys and resolve ${CLAUDE_PLUGIN_ROOT} to this checkout.
mcp.json is the skill-search server from the repo's .mcp.json, rewritten in Cline's schema.
The Cline code plugin re-runs `sync` at each session start, so the copies follow the repo
without a reinstall.
"""
import json
import os
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
DEFAULT_DEST = Path.home() / ".agents" / "plugins" / "skill-concierge"
MARKER = ".skill-concierge-managed.json"
ALLOWED = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
KEY = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):")
PLUGIN_ROOT_VAR = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}|\$CLAUDE_PLUGIN_ROOT\b")


def convert_skill(text: str) -> str:
    """Return SKILL.md text Cline's Agent Plugin loader accepts: top-level frontmatter keys
    outside ALLOWED dropped (with their indented continuation lines), ${CLAUDE_PLUGIN_ROOT}
    resolved to this checkout, everything else unchanged."""
    m = re.match(r"^---\r?\n([\s\S]*?)\r?\n---(\r?\n|$)", text)
    if not m:
        raise ValueError("SKILL.md has no frontmatter")
    out, keep, key = [], True, ""
    for line in m.group(1).splitlines():
        k = KEY.match(line)
        if k and not line.startswith((" ", "\t")):
            key = k.group(1)
            keep = key in ALLOWED
        elif key == "metadata":
            # Cline rejects a metadata value that is not a string ("version: 1.0" parses as a number).
            # Only a plain scalar; a quoted value, block scalar (| >), flow map/list or anchor stays.
            child = re.match(r"^(\s+[A-Za-z][\w-]*):\s*(.+?)\s*$", line)
            if child and child.group(2)[0] not in "\"'|>{[&*!%@`#":
                line = f"{child.group(1)}: {json.dumps(child.group(2))}"
        if keep:
            out.append(line)
    body = PLUGIN_ROOT_VAR.sub(lambda _: str(ROOT), text[m.end():])
    return "---\n" + "\n".join(out) + "\n---\n" + body


def mcp_config() -> dict:
    """The repo's skill-search server (.mcp.json) in the agent-plugins.org mcp.json schema."""
    server = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["skill-search"]
    return {
        "$schema": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",
        "mcpServers": {"skill-search": {
            "type": "stdio",
            "command": "bash",    # Cline wants one bare executable token or a ./plugin-relative path
            "args": [PLUGIN_ROOT_VAR.sub(lambda _: str(ROOT), a) for a in server["args"]],
            "env": server.get("env", {}),
        }},
    }


def plan() -> dict:
    """{relative path: bytes} for everything the plugin folder should hold."""
    manifest = json.loads((HERE / "agent-plugin.json").read_text(encoding="utf-8"))
    manifest["version"] = json.loads(
        (ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]
    files = {
        "plugin.json": (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode(),
        "mcp.json": (json.dumps(mcp_config(), indent=2, ensure_ascii=False) + "\n").encode(),
    }
    for skill in sorted((ROOT / "skills").iterdir()) if (ROOT / "skills").is_dir() else []:
        md = skill / "SKILL.md"
        if not md.is_file():
            continue
        for src in sorted(p for p in skill.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
            rel = f"skills/{skill.name}/{src.relative_to(skill).as_posix()}"
            files[rel] = convert_skill(src.read_text(encoding="utf-8")).encode() if src == md else src.read_bytes()
    return files


def _managed(dest: Path) -> set:
    """Paths this tool wrote last time; an entry that would leave dest is ignored, never pruned."""
    try:
        names = json.loads((dest / MARKER).read_text(encoding="utf-8")).get("files", [])
    except (OSError, ValueError):
        return set()
    return {n for n in names if isinstance(n, str) and n and not n.startswith("/")
            and ".." not in Path(n).parts}


def _write(path: Path, data: bytes) -> None:
    """Atomic replace; the temp name is per process so two Cline sessions can sync at once."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp-skill-concierge-{os.getpid()}")
    tmp.write_bytes(data)
    tmp.replace(path)


def stale(dest: Path, files: dict) -> list:
    out = [rel for rel, data in files.items()
           if not (dest / rel).is_file() or (dest / rel).read_bytes() != data]
    return out + sorted(_managed(dest) - set(files))


def sync(dest: Path) -> int:
    if dest.is_symlink():
        # Writing through a link would rewrite whatever it points at (a repo's own skills/).
        print(f"!! {dest} is a symlink — refusing to write through it; remove it and re-run",
              file=sys.stderr)
        return 1
    if dest.exists() and not (dest / MARKER).is_file():
        print(f"!! {dest} exists and was not built by this tool — refusing to replace it",
              file=sys.stderr)
        return 1
    files = plan()
    changed = stale(dest, files)
    for rel in changed:
        path = dest / rel
        if rel in files:
            _write(path, files[rel])
        else:
            path.unlink(missing_ok=True)
    for d in sorted((p for p in (dest / "skills").glob("*") if p.is_dir()), reverse=True):
        if not any(d.rglob("*")):
            shutil.rmtree(d, ignore_errors=True)
    _write(dest / MARKER, (json.dumps({"files": sorted(files)}, indent=2) + "\n").encode())
    print(f"    Agent Plugin → {dest}: {len(changed)} file(s) updated, {len(files)} managed")
    return 0


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in ("sync", "check"):
        print((__doc__ or "").strip().splitlines()[2], file=sys.stderr)
        return 2
    dest = Path(sys.argv[2]).expanduser() if len(sys.argv) > 2 else DEFAULT_DEST
    if sys.argv[1] == "sync":
        return sync(dest)
    out = stale(dest, plan())
    for rel in out:
        print(f"stale: {rel}")
    return 1 if out else 0


if __name__ == "__main__":
    sys.exit(main())
