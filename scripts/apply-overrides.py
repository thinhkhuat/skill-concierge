#!/usr/bin/env python3
"""
Apply skill-concierge's name-only budget overrides to ~/.claude/settings.json.

Every discovered skill → "name-only" EXCEPT the curated keep-on allowlist
(config/keep-on.json), which stay "on". Writes to **settings.json** (the global
single source), NOT settings.local.json — backs it up first and preserves every
other key.

Why NOT upstream `skill-search-overrides`: it targets settings.local.json with a
2-item keep-on default, silently reverting the hand-curated keep-on set (see
vendor/skill-search/VENDORED.md + the deployment readme). This applier is the
customization that keeps the curated policy intact.

Safety: refuses to write empty overrides (a failed discovery must not blank the
budget); always backs up before touching; UTF-8 preserved (ensure_ascii=False).

Test seams (env): SKILL_CONCIERGE_SETTINGS, SKILL_CONCIERGE_KEEPON,
SKILL_CONCIERGE_SKILLS_FILE (newline-separated names → skips live discovery).
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # skill-concierge/
KEEPON = Path(os.environ.get("SKILL_CONCIERGE_KEEPON", ROOT / "config" / "keep-on.json"))
SETTINGS = Path(os.environ.get(
    "SKILL_CONCIERGE_SETTINGS", Path.home() / ".claude" / "settings.json"))
VENDOR = ROOT / "vendor" / "skill-search"


def discover_skill_names():
    """Skill names from the SAME source the index uses (vendored skills_discovery),
    so overrides and the retriever never drift. Test override: a newline file."""
    f = os.environ.get("SKILL_CONCIERGE_SKILLS_FILE")
    if f:
        return [ln.strip() for ln in Path(f).read_text(encoding="utf-8").splitlines() if ln.strip()]
    sys.path.insert(0, str(VENDOR))
    from skill_search.skills_discovery import discover_skills  # vendored engine
    return [s["name"] for s in discover_skills()]


def main():
    raw = json.loads(KEEPON.read_text(encoding="utf-8"))
    keep_list = raw.get("keep_on")
    if not isinstance(keep_list, list) or not keep_list:
        print(f"keep-on policy invalid: '{KEEPON}' needs a non-empty \"keep_on\" list — "
              f"refusing (a missing/blank list would set EVERY skill to name-only).",
              file=sys.stderr)
        return 1
    keep_on = set(keep_list)
    if "skill-search" not in keep_on:
        print("WARN: 'skill-search' (the router) is not in keep_on — the retriever entry "
              "point would go name-only/dark. Add it unless that's intended.", file=sys.stderr)

    names = sorted(set(discover_skill_names()))
    if not names:
        print("no skills discovered — refusing to write empty overrides", file=sys.stderr)
        return 1

    overrides = {n: ("on" if n in keep_on else "name-only") for n in names}
    missing = sorted(keep_on - set(names))   # keep-on entries absent on this machine

    settings = {}
    if SETTINGS.exists():
        settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
        stamp = f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"   # collision-safe
        bak = SETTINGS.parent / (SETTINGS.name + f".bak-skillconcierge-{stamp}")
        bak.write_text(SETTINGS.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"backup : {bak}")

    settings["skillOverrides"] = overrides
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write: serialize to a temp file in the same dir, then os.replace() — so a
    # crash/disk-full mid-write can NEVER leave the global settings.json truncated (B1).
    tmp = SETTINGS.parent / (SETTINGS.name + f".tmp-{os.getpid()}")
    tmp.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, SETTINGS)

    on = sum(1 for v in overrides.values() if v == "on")
    print(f"wrote  : {SETTINGS}")
    print(f"applied: {on} on / {len(overrides) - on} name-only   (skills discovered: {len(names)})")
    if missing:
        print(f"NOTE   : {len(missing)} keep-on entr(ies) not present on this machine "
              f"(left unset — they'll apply if those skills get installed): {missing}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
