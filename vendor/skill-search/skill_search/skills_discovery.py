#!/usr/bin/env python3
"""
skills_discovery
----------------
Single source of truth for "what skills exist and what are they called".

Both halves of skill-search depend on this agreeing exactly:
  * server.py            indexes these skills by `name`
  * generate_overrides.py frees these same `name`s from the 1% budget

If the two walked different sets (they used to), you could index a skill you
never freed, or free one you never indexed — silent budget leaks. Keep this the
ONLY place skill discovery lives.

No third-party deps and no network — safe to import from any script.
"""

import re
import glob
from pathlib import Path

# Directories Claude Code loads skills from, in precedence order
# (personal first, then project — first writer wins on name collision).
SKILL_DIRS = [
    Path.home() / ".claude" / "skills",                 # personal (all projects)
    Path.cwd()  / ".claude" / "skills",                 # project-scoped
]
# Plugin-bundled skills. Scope to the *cache* (the installed/active copies Claude
# Code actually loads), NOT ~/.claude/plugins/marketplaces/** — that holds catalog
# source checkouts including skills that aren't installed, which would pollute the
# index with un-invokable results.
PLUGIN_GLOB = str(Path.home() / ".claude" / "plugins" / "cache" / "**" / "skills" / "*" / "SKILL.md")


def _namespaced_name(path: Path, base_name: str) -> str:
    """For installed plugin skills, prefix the plugin id so the name matches how
    Claude Code references (and overrides) them, e.g. 'context-mode:ctx-purge'.

    Cache layout: .../plugins/cache/<marketplace>/<plugin>/<version>/skills/<skill>/SKILL.md
    Non-plugin skills (personal/project) are returned unchanged.
    """
    parts = path.parts
    try:
        pi = parts.index("plugins")
    except ValueError:
        return base_name
    sub = parts[pi + 1:]
    if len(sub) >= 6 and sub[0] == "cache" and "skills" in sub:
        si = sub.index("skills")
        if si >= 3:                       # cache / <marketplace> / <plugin> / .../ skills
            return f"{sub[si - 2]}:{base_name}"
    return base_name


def parse_skill(path: Path) -> dict | None:
    """Return {name, description, body, path} or None if no valid frontmatter."""
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception:
        return None

    fm = re.search(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", raw, re.DOTALL)
    if not fm:
        return None
    frontmatter, body = fm.group(1), fm.group(2)

    # name: explicit frontmatter, else directory name (matches Claude Code rule).
    name_m = re.search(r"^name:\s*(.+)$", frontmatter, re.MULTILINE)
    name = name_m.group(1).strip() if name_m else path.parent.name
    # Plugin skills are referenced namespaced (plugin:skill) — apply that here so
    # search results, get_skill lookups, and budget overrides all use one id.
    name = _namespaced_name(path, name)

    # description + optional when_to_use (both feed the semantic index).
    desc_m = re.search(r"^description:\s*(.+?)(?=\n\w+:|\Z)", frontmatter,
                       re.MULTILINE | re.DOTALL)
    when_m = re.search(r"^when_to_use:\s*(.+?)(?=\n\w+:|\Z)", frontmatter,
                       re.MULTILINE | re.DOTALL)
    description = (desc_m.group(1).strip() if desc_m else "")
    if when_m:
        description += "  " + when_m.group(1).strip()

    return {
        "name": name,
        "description": description,
        "body": body.strip()[:4000],   # cap body so embeddings stay cheap
        "path": str(path),
    }


def discover_skill_paths() -> list[Path]:
    """Every SKILL.md path across personal dirs, project dirs, and plugins."""
    paths: list[Path] = []
    for d in SKILL_DIRS:
        if d.exists():
            paths += [Path(p) for p in glob.glob(str(d / "*" / "SKILL.md"))]
    paths += [Path(p) for p in glob.glob(PLUGIN_GLOB, recursive=True)]
    return paths


def discover_skills() -> list[dict]:
    """Parsed skill dicts (deduped by name, precedence = personal -> project)."""
    found: dict[str, dict] = {}
    for p in discover_skill_paths():
        skill = parse_skill(p)
        if skill and skill["name"]:
            found.setdefault(skill["name"], skill)   # first writer wins
    return list(found.values())
