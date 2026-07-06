#!/usr/bin/env python3
"""
keep-on — view / add / remove the always-ON skill allowlist (~/.claude/skill-concierge/keep-on.json).

The allowlist is the set of skills kept FULLY described in every turn's context; every
other skill goes "name-only" and is retrieved on demand. This is the seamless surface for
curating it:

  keep-on.py list                 show the always-on skills
  keep-on.py add <name> [...]     add skill(s) to always-on, then reconcile settings.json
  keep-on.py remove <name> [...]  remove skill(s), then reconcile

add/remove edit keep-on.json (deduped, sorted) then re-apply the overrides so the change
takes effect immediately (the autonomous session-start reconcile would otherwise catch it
next session). Skill NAMES are catalogue-namespaced (e.g. `ck:plan`,
`superpowers:brainstorming`) — copy them from `keep-on.py list` or a search result.
Pure stdlib.

Test seams (env): SKILL_CONCIERGE_HOME (canonical home), SKILL_CONCIERGE_KEEPON (exact allowlist
path), SKILL_CONCIERGE_VENV (engine venv).
"""
import argparse
import json
import os
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

from _keepon import keepon_path      # sibling module (scripts/ is on sys.path at run)

ROOT = Path(__file__).resolve().parent.parent
VENV = Path(os.environ.get("SKILL_CONCIERGE_VENV", Path.home() / ".claude/skill-concierge/venv"))
APPLIER = ROOT / "scripts" / "apply-overrides.py"


def _load():
    kp = keepon_path(ROOT)
    raw = json.loads(kp.read_text(encoding="utf-8"))
    lst = raw.get("keep_on")
    if not isinstance(lst, list):
        raise SystemExit(f"keep-on policy invalid: {kp} has no \"keep_on\" list")
    return raw, lst


def _save(raw, names):
    raw["keep_on"] = sorted(set(names))
    keepon_path(ROOT).write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _reconcile():
    """Re-apply overrides so an allowlist edit takes effect now. Needs the engine venv
    python (the applier imports the vendored discovery). Fail-graceful if it's missing."""
    py = VENV / "bin" / "python"
    if not py.exists():
        print("  (engine venv not found — edited keep-on.json only; run ./setup.sh or "
              "apply-overrides.py to reconcile settings.json)")
        return
    r = subprocess.run([str(py), str(APPLIER)], capture_output=True, text=True)
    for ln in (r.stdout or "").splitlines():
        if ln.startswith(("applied", "NOTE", "wrote", "backup")):
            print(f"  {ln}")
    for ln in (r.stderr or "").splitlines():          # surface the router-name WARN etc.
        if ln.strip():
            print(f"  ! {ln.strip()}")
    if r.returncode != 0:
        print(f"  ! reconcile exit {r.returncode}")


def cmd_list(_):
    _, names = _load()
    print(f"always-on skills ({len(names)}) — {keepon_path(ROOT)}:")
    for n in sorted(names):
        print(f"  • {n}")
    return 0


def cmd_add(args):
    raw, names = _load()
    cur = set(names)
    new = [n for n in args.names if n not in cur]
    if not new:
        print(f"already always-on: {', '.join(args.names)} (no change)")
        return 0
    _save(raw, cur | set(args.names))
    print(f"added to always-on: {', '.join(sorted(new))}")
    _reconcile()
    return 0


def cmd_remove(args):
    raw, names = _load()
    cur = set(names)
    gone = [n for n in args.names if n in cur]
    if not gone:
        print(f"not in always-on: {', '.join(args.names)} (no change)")
        return 0
    if "skill-search" in gone or "skill-concierge:skill-search" in gone:
        print("  ! WARNING: removing the retriever router (skill-search) makes it name-only — "
              "retrieval degrades. Re-add it unless that is truly intended.")
    _save(raw, cur - set(args.names))
    print(f"removed from always-on: {', '.join(sorted(gone))}")
    _reconcile()
    return 0


def cmd_selftest(_):
    import tempfile
    global VENV
    with tempfile.TemporaryDirectory() as td:
        kp = Path(td) / "keep.json"
        kp.write_text(json.dumps({"_note": "keep", "keep_on": ["b", "a", "a"]}), encoding="utf-8")
        os.environ["SKILL_CONCIERGE_KEEPON"] = str(kp)   # keepon_path() returns this, no seeding
        VENV = Path(td) / "no-venv"           # missing -> reconcile is a no-op note (no settings touch)
        cmd_add(Namespace(names=["c", "a"]))  # 'a' already present -> dedups
        got = json.loads(kp.read_text())
        assert got["keep_on"] == ["a", "b", "c"], got
        assert got["_note"] == "keep", "must preserve other keys"
        cmd_remove(Namespace(names=["b", "zzz"]))   # 'zzz' absent -> ignored
        assert json.loads(kp.read_text())["keep_on"] == ["a", "c"]
        cmd_add(Namespace(names=["a"]))       # no-op path
        assert json.loads(kp.read_text())["keep_on"] == ["a", "c"]
    os.environ.pop("SKILL_CONCIERGE_KEEPON", None)
    print("selftest ok")
    return 0


def main():
    ap = argparse.ArgumentParser(description="View/add/remove the always-ON skill allowlist.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="show the always-on skills").set_defaults(fn=cmd_list)
    pa = sub.add_parser("add", help="add skill(s) to always-on, then reconcile")
    pa.add_argument("names", nargs="+")
    pa.set_defaults(fn=cmd_add)
    pr = sub.add_parser("remove", help="remove skill(s) from always-on, then reconcile")
    pr.add_argument("names", nargs="+")
    pr.set_defaults(fn=cmd_remove)
    sub.add_parser("selftest", help=argparse.SUPPRESS).set_defaults(fn=cmd_selftest)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
