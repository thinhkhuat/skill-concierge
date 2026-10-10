"""What in an OpenCode config is skill-concierge's. Shared by adapters/opencode/install.sh and
scripts/doctor.py so the two always agree (ADR-0089). Stdlib only.

Every copy of the plugin declares the id "skill-concierge", and OpenCode fails all but the first
plugin with a given id, so `opencode.json` `plugins` may hold exactly one copy.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

PACKAGE_NAME = "skill-concierge-opencode"
SKILLS_DIRNAME = "skill-concierge-skills"


def entry_path(entry) -> str | None:
    """The path a `plugins` entry names (a string, or {"package": ...})."""
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict) and isinstance(entry.get("package"), str):
        return entry["package"]
    return None


def resolve(path: str, config_dir: Path) -> Path:
    """Resolve a path the way OpenCode does: file:// URLs, ~, and relative to the config file."""
    if path.startswith("file://"):
        path = path[len("file://"):]
    p = Path(path).expanduser()
    return p if p.is_absolute() else config_dir / p


def is_copy(entry, config_dir: Path) -> bool:
    """True when a `plugins` entry is a copy of this plugin: its folder is
    `…/adapters/opencode/plugin` holding a package.json named skill-concierge-opencode, or that
    folder is gone and its path names skill-concierge (a deleted checkout or cache version)."""
    raw = entry_path(entry)
    if raw is None:
        return False
    p = resolve(raw, config_dir)
    if p.parts[-3:] != ("adapters", "opencode", "plugin"):
        return False
    try:
        return json.loads((p / "package.json").read_text(encoding="utf-8")).get("name") == PACKAGE_NAME
    except FileNotFoundError:
        return not p.exists() and "skill-concierge" in p.parts
    except (OSError, ValueError, AttributeError):
        return False


def is_plugin_cache(path) -> bool:
    """A versioned plugin-cache copy (e.g. Claude Code's ~/.claude/plugins/cache/…): replaced and
    deleted on the next plugin update, so OpenCode must not be pointed at it over a checkout."""
    parts = Path(path).parts
    return any(parts[i:i + 2] == ("plugins", "cache") for i in range(len(parts) - 1))


def skills_entries(cfg: dict, config_dir: Path) -> list[Path] | None:
    """The `skills` folders a config registers, resolved; None when `skills` is not a list."""
    raw = cfg.get("skills")
    if raw is None:
        return []
    if not isinstance(raw, list):
        return None
    return [resolve(s, config_dir) for s in raw if isinstance(s, str)]


def known_versions(repo: Path, name: str) -> set[str]:
    """Every text skills/<name>/SKILL.md has had: the current file plus, in a git checkout, each
    committed version. An installed copy equal to one of them is the installer's own, unedited."""
    out = set()
    cur = repo / "skills" / name / "SKILL.md"
    if cur.is_file():
        out.add(cur.read_text(encoding="utf-8"))
    rel = f"skills/{name}/SKILL.md"
    try:
        revs = subprocess.run(["git", "-C", str(repo), "log", "--format=%H", "--", rel],
                              capture_output=True, text=True, timeout=20).stdout.split()
        for rev in revs:
            show = subprocess.run(["git", "-C", str(repo), "show", f"{rev}:{rel}"],
                                  capture_output=True, text=True, timeout=20)
            if show.returncode == 0:
                out.add(show.stdout)
    except (OSError, subprocess.SubprocessError):
        pass
    return out
