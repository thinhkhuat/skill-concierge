"""Bare skill name -> the `plugin:name` the menu shows (ADR-0083 amendment, 0.61.2).

Claude Code resolves a typed `/bro` or a Skill-tool call for `bro` to the one plugin skill of that
name (`pstack:bro`). The ledger and the 🔥 counter must name it the same way the menu does, or a
heavily used plugin skill never shows 🔥. A bare name is folded only when exactly one installed
plugin has a skill by that name and no personal skill does; an ambiguous name stays as typed.
Stdlib only, Python 3.9-safe; fail-open to "no aliases". Seams: SKILL_CONCIERGE_PLUGIN_REGISTRY
(installed_plugins.json), SKILL_CONCIERGE_SKILLS_ROOT (personal skills root).
"""
import glob
import json
import os
from pathlib import Path

REGISTRY = Path(os.environ.get(
    "SKILL_CONCIERGE_PLUGIN_REGISTRY", Path.home() / ".claude" / "plugins" / "installed_plugins.json"))
SKILLS_ROOT = Path(os.environ.get("SKILL_CONCIERGE_SKILLS_ROOT", Path.home() / ".claude" / "skills"))


def plugin_bare_aliases(registry=None, skills_root=None) -> dict:
    """{bare: "plugin:bare"} for every bare name exactly one installed plugin owns. Plugin skills
    are read at both depths under <installPath>/skills, a skill directory owning everything below
    it (the discovery engine's rule)."""
    registry = REGISTRY if registry is None else Path(registry)
    skills_root = SKILLS_ROOT if skills_root is None else Path(skills_root)
    try:
        plugins = json.loads(registry.read_text(encoding="utf-8")).get("plugins") or {}
    except (OSError, ValueError, AttributeError):
        return {}
    owners = {}
    for pid, installs in plugins.items():
        plugin = str(pid).split("@")[0]
        for inst in installs if isinstance(installs, list) else []:
            base = os.path.join(str(inst.get("installPath", "")) if isinstance(inst, dict) else "", "skills")
            flat = glob.glob(os.path.join(base, "*", "SKILL.md"))
            dirs = {os.path.dirname(f) for f in flat}
            nested = [n for n in glob.glob(os.path.join(base, "*", "*", "SKILL.md"))
                      if os.path.dirname(os.path.dirname(n)) not in dirs]
            for hit in flat + nested:
                bare = os.path.basename(os.path.dirname(hit))
                owners.setdefault(bare, set()).add(f"{plugin}:{bare}")
    personal = {p.parent.name for p in skills_root.glob("*/SKILL.md")} if skills_root.is_dir() else set()
    return {b: next(iter(full)) for b, full in owners.items() if len(full) == 1 and b not in personal}


def canonical(name: str, aliases=None) -> str:
    """The menu's name for `name`: unchanged when it is already qualified, personal or ambiguous."""
    if not isinstance(name, str) or not name or ":" in name:
        return name
    aliases = plugin_bare_aliases() if aliases is None else aliases
    return aliases.get(name, name)
