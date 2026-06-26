#!/usr/bin/env python3
"""
generate_overrides.py
---------------------
The other half of the fix. The MCP server gives you semantic retrieval, but
that only helps if you ALSO stop paying the native 1% listing tax.

This writes skillOverrides into .claude/settings.local.json, setting every
skill to "name-only" (name stays visible + invocable, description leaves the
budget) EXCEPT a small keep-on allowlist (your router/search entry points).

Run from your project root, or pass --global to target ~/.claude.

  python generate_overrides.py                 # project: ./.claude/settings.local.json
  python generate_overrides.py --global        # user:    ~/.claude/settings.local.json
  python generate_overrides.py --keep skill-a skill-b   # extra skills to leave "on"
"""

import sys
import json
from pathlib import Path

# Shared with server.py: the set of skills the retriever indexes is exactly the
# set we free from the budget here. Uses the same parsed `name` (frontmatter,
# falling back to directory) so override keys match what search_skills returns.
from skill_search.skills_discovery import discover_skills

# Skills to leave fully "on" (name + description in context). Keep this tiny —
# these are the entry points Claude relies on without a search round-trip.
DEFAULT_KEEP_ON = {"skill-search", "skill-finder"}


def keep_on_from_argv(argv: list[str]) -> set[str]:
    """The keep-on allowlist: the defaults plus anything after `--keep`
    (stopping at the next flag, so `--keep a b --global` doesn't swallow --global)."""
    keep_on = set(DEFAULT_KEEP_ON)
    if "--keep" in argv:
        for a in argv[argv.index("--keep") + 1:]:
            if a.startswith("-"):
                break
            keep_on.add(a)
    return keep_on


def compute_overrides(names, keep_on) -> dict:
    """Map each skill name to 'on' (keep-on allowlist) or 'name-only' (everything
    else). This is the whole budget-freeing decision, isolated for testing."""
    return {n: ("on" if n in keep_on else "name-only") for n in sorted(names)}


def write_overrides(settings_path: Path, overrides: dict) -> None:
    """Merge skillOverrides into settings.local.json without clobbering other keys."""
    settings = {}
    if settings_path.exists():
        settings = json.loads(settings_path.read_text())
    settings["skillOverrides"] = overrides
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, indent=2))


def main():
    is_global = "--global" in sys.argv
    keep_on = keep_on_from_argv(sys.argv)

    base = Path.home() / ".claude" if is_global else Path.cwd() / ".claude"
    settings_path = base / "settings.local.json"

    # Same discovery the retriever uses: personal + project + plugin skills.
    names = sorted({s["name"] for s in discover_skills()})
    overrides = compute_overrides(names, keep_on)
    write_overrides(settings_path, overrides)

    on = [n for n, v in overrides.items() if v == "on"]
    print(json.dumps({
        "wrote": str(settings_path),
        "total_skills": len(names),
        "kept_on": on,
        "set_name_only": len(names) - len(on),
    }, indent=2))


if __name__ == "__main__":
    main()
