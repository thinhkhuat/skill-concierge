#!/usr/bin/env python3
"""
blocklist — view / add / remove the DISABLE list (~/.claude/skill-concierge/blocklist.json).

The blocklist is the user-ordered disable tier (ADR-0046): a skill on it is never
OFFERED by the enforcer, never returned by search_skills, never served by get_skill,
and its Skill-tool invocation is DENIED by the PreToolUse guard (hooks/scripts/skill_guard.py).
It works for ANY skill regardless of origin — personal skills, plugin skills, external
catalog entries, and command-files surfaced as skills (ADR-0001 keeps commands out of the
index, which is exactly why the deny guard — not retrieval filtering — is the layer that
catches them).

  blocklist.py list                 show the disabled skills
  blocklist.py add <name> [...]     disable skill(s), then reconcile settings overrides
  blocklist.py remove <name> [...]  re-enable skill(s), then reconcile

NAME SEMANTICS
  A BARE entry (`resume-session`) blocks every qualified twin — `plugin:name`,
  `alias:name`, any harness origin. "Disable X" means X, everywhere.
  A QUALIFIED entry (`skill-concierge:keep-on`) blocks only that exact form —
  for when one origin must die but a same-named sibling must live.

The list is flat and symmetric with keep-on's ({"blocked": [...]}, deduped, sorted).
add/remove reconcile the settings overrides because a disabled skill must never stay
FULLY described (keep-on) — the blocklist outranks the allowlist by construction.

Test seams (env): SKILL_CONCIERGE_HOME, SKILL_CONCIERGE_BLOCKLIST (exact file),
SKILL_CONCIERGE_VENV (engine venv). Pure stdlib.
"""
import argparse
import json
import os
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

from _keepon import blocklist_path, keepon_path  # sibling module (scripts/ is on sys.path at run)

ROOT = Path(__file__).resolve().parent.parent
VENV = Path(os.environ.get("SKILL_CONCIERGE_VENV", Path.home() / ".claude/skill-concierge/venv"))
APPLIER = ROOT / "scripts" / "apply-overrides.py"


def _load():
    bp = blocklist_path()
    if not bp.exists():
        return {}, []
    raw = json.loads(bp.read_text(encoding="utf-8"))
    lst = raw.get("blocked")
    if not isinstance(lst, list):
        raise SystemExit(f"blocklist invalid: {bp} has no \"blocked\" list")
    return raw, lst


def _save(raw, names):
    raw["blocked"] = sorted(set(names))
    bp = blocklist_path()
    bp.parent.mkdir(parents=True, exist_ok=True)
    bp.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _keep_on_names():
    try:
        raw = json.loads(keepon_path(ROOT).read_text(encoding="utf-8"))
        return {n for n in raw.get("keep_on", []) if isinstance(n, str)}
    except (OSError, ValueError):
        return set()


def _reconcile():
    """Re-apply overrides so a disable takes effect now (a blocked keep-on skill must
    drop its full description immediately). Needs the engine venv python (the applier
    imports the vendored discovery). Fail-graceful if it's missing."""
    py = VENV / "bin" / "python"
    if not py.exists():
        print("  (engine venv not found — edited blocklist.json only; retrieval/guard filters "
              "read it live, run ./setup.sh to reconcile the settings overrides)")
        return
    r = subprocess.run([str(py), str(APPLIER)], capture_output=True, text=True, check=False)
    for ln in (r.stdout or "").splitlines():
        if ln.startswith(("applied", "NOTE", "wrote", "backup", "stripped")):
            print(f"  {ln}")
    for ln in (r.stderr or "").splitlines():
        if ln.strip():
            print(f"  ! {ln.strip()}")
    if r.returncode != 0:
        print(f"  ! reconcile exit {r.returncode}")


def cmd_list(_):
    _, names = _load()
    print(f"disabled skills ({len(names)}) — {blocklist_path()}:")
    for n in sorted(names):
        print(f"  • {n}")
    return 0


def cmd_add(args):
    raw, names = _load()
    cur = set(names)
    new = [n for n in args.names if n not in cur]
    if not new:
        print(f"already disabled: {', '.join(args.names)} (no change)")
        return 0
    for n in new:
        if n == "skill-search" or n.endswith(":skill-search"):
            print("  ! WARNING: disabling the retriever router (skill-concierge:skill-search) "
                  "degrades all semantic retrieval. Re-enable unless that is truly intended.")
    overlap = {n for n in new} & _keep_on_names()
    if overlap:
        print(f"  ! NOTE: {', '.join(sorted(overlap))} is on the keep-on allowlist — the "
              "blocklist outranks it; its full description will be stripped on reconcile.")
    _save(raw, cur | set(args.names))
    print(f"disabled: {', '.join(sorted(new))}")
    _reconcile()
    return 0


def cmd_remove(args):
    raw, names = _load()
    cur = set(names)
    gone = [n for n in args.names if n in cur]
    if not gone:
        print(f"not disabled: {', '.join(args.names)} (no change)")
        return 0
    _save(raw, cur - set(args.names))
    print(f"re-enabled: {', '.join(sorted(gone))}")
    _reconcile()
    return 0


def cmd_selftest(_):
    import tempfile
    global VENV
    with tempfile.TemporaryDirectory() as td:
        bp = Path(td) / "bl.json"
        bp.write_text(json.dumps({"_note": "bl", "blocked": ["b", "a", "a"]}), encoding="utf-8")
        os.environ["SKILL_CONCIERGE_BLOCKLIST"] = str(bp)
        os.environ["SKILL_CONCIERGE_KEEPON"] = str(Path(td) / "keep.json")
        VENV = Path(td) / "no-venv"           # missing -> reconcile is a graceful no-op
        cmd_add(Namespace(names=["c", "a"]))  # 'a' already present -> dedups
        got = json.loads(bp.read_text())
        assert got["blocked"] == ["a", "b", "c"], got
        assert got["_note"] == "bl", "must preserve other keys"
        cmd_remove(Namespace(names=["b", "zzz"]))   # 'zzz' absent -> ignored
        assert json.loads(bp.read_text())["blocked"] == ["a", "c"]
        cmd_add(Namespace(names=["a"]))       # no-op path
        assert json.loads(bp.read_text())["blocked"] == ["a", "c"]
        # absent file = empty list (never seeded). HOME must be patched as the MODULE
        # global — setting the env var mid-process is a no-op (_keepon reads it at
        # import), and the frozen real home would leak this leg on any machine that
        # actually has a live blocklist (validator-caught, 2026-08-29).
        del os.environ["SKILL_CONCIERGE_BLOCKLIST"]
        import _keepon
        _saved_home = _keepon.HOME
        _keepon.HOME = Path(td) / "home2"
        try:
            raw, names = _load()
            assert raw == {} and names == [], "absent blocklist must load empty"
        finally:
            _keepon.HOME = _saved_home
    for k in ("SKILL_CONCIERGE_BLOCKLIST", "SKILL_CONCIERGE_HOME", "SKILL_CONCIERGE_KEEPON"):
        os.environ.pop(k, None)
    print("selftest ok")
    return 0


def main():
    ap = argparse.ArgumentParser(description="View/add/remove the skill DISABLE list (ADR-0046).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="show the disabled skills").set_defaults(fn=cmd_list)
    pa = sub.add_parser("add", help="disable skill(s), then reconcile")
    pa.add_argument("names", nargs="+")
    pa.set_defaults(fn=cmd_add)
    pr = sub.add_parser("remove", help="re-enable skill(s), then reconcile")
    pr.add_argument("names", nargs="+")
    pr.set_defaults(fn=cmd_remove)
    sub.add_parser("selftest", help=argparse.SUPPRESS).set_defaults(fn=cmd_selftest)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
