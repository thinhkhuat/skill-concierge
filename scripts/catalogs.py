#!/usr/bin/env python3
"""
catalogs — manage external skill-catalog roots (ADR-0031,
~/.claude/skill-concierge/catalog-roots.json).

A catalog is a LOCAL directory of third-party skills (children containing
SKILL.md) indexed for retrieval WITHOUT being installed into any Claude Code
root: its skills are search-only citizens named `<alias>:<dirname>`, consumed
by reading their SKILL.md (get_skill), never by the Skill tool.

  catalogs.py list                          show configured roots + on-disk skill counts
  catalogs.py add <alias> <path>            register a root (alias: [a-z0-9][a-z0-9_-]*)
      [--include GLOB ...] [--exclude GLOB ...]
  catalogs.py remove <alias>                unregister (points prune at next reindex)
  catalogs.py promote <alias>:<name>        symlink the skill into ~/.claude/skills/<name>
                                            (refuses on collision; reports broken promotions)
  catalogs.py --selftest

add/remove edit catalog-roots.json (atomic write); the INDEX follows at the next
reindex — auto_reindex picks the change up at the next session start, or run the
reindex() MCP tool / `skill-search --reindex` to land it now. Pure stdlib.

Test seams (env): SKILL_CONCIERGE_CATALOG_ROOTS (config path), SKILL_PROMOTE_DIR
(promotion target dir, default ~/.claude/skills).
"""
import argparse
import glob
import json
import os
import re
import sys
from pathlib import Path

CONFIG = Path(os.environ.get(
    "SKILL_CONCIERGE_CATALOG_ROOTS",
    Path.home() / ".claude" / "skill-concierge" / "catalog-roots.json"))
PROMOTE_DIR = Path(os.environ.get("SKILL_PROMOTE_DIR", Path.home() / ".claude" / "skills"))
_ALIAS_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def _load() -> dict:
    try:
        data = json.loads(CONFIG.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):  # missing/unreadable file, bad JSON, bad encoding
        return {}


def _save(cfg: dict) -> None:
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, CONFIG)


def _spec(entry) -> dict:
    if isinstance(entry, str):
        entry = {"path": entry}
    return entry if isinstance(entry, dict) else {}


def _skill_count(spec: dict) -> int:
    p = spec.get("path")
    return len(glob.glob(str(Path(os.path.expanduser(str(p))) / "*" / "SKILL.md"))) if p else 0


def _configured_roots(cfg: dict) -> dict:
    return {a: _spec(s) for a, s in cfg.items()
            if isinstance(a, str) and not a.startswith("_") and _spec(s).get("path")}


def _broken_promotions(cfg: dict) -> list:
    """Symlinks in the promotion dir that point into a configured root but dangle
    (catalog moved/renamed, or the skill dir was deleted upstream)."""
    roots = [str(Path(os.path.expanduser(str(s["path"])))) for s in _configured_roots(cfg).values()]
    out = []
    try:
        entries = list(PROMOTE_DIR.iterdir())
    except OSError:
        return out
    for d in entries:
        if not d.is_symlink():
            continue
        target = os.path.realpath(d)
        if (any(target.startswith(r + os.sep) for r in roots) and not os.path.isdir(target)) or (
            not os.path.exists(target) and any(str(os.readlink(d)).startswith(r) for r in roots)
        ):
            out.append(f"{d.name} -> {os.readlink(d)}")
    return out


def cmd_list(_):
    cfg = _load()
    roots = _configured_roots(cfg)
    if not roots:
        print("no external catalogs configured "
              f"({CONFIG} absent or empty) — `catalogs.py add <alias> <path>` to register one")
        return 0
    for alias, spec in sorted(roots.items()):
        inc, exc = spec.get("include") or [], spec.get("exclude") or []
        globs = "".join([f"  include={inc}" if inc else "", f"  exclude={exc}" if exc else ""])
        print(f"{alias:<16} {spec['path']}   skills≈{_skill_count(spec)}{globs}")
    broken = _broken_promotions(cfg)
    if broken:
        print("\nBROKEN promotions (symlink into a catalog that no longer resolves):")
        for b in broken:
            print(f"  {b}")
    return 0


def cmd_add(args):
    if not _ALIAS_RE.match(args.alias):
        print(f"invalid alias {args.alias!r} (want [a-z0-9][a-z0-9_-]*)", file=sys.stderr)
        return 1
    root = Path(os.path.expanduser(args.path)).resolve()
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 1
    n = _skill_count({"path": str(root)})
    if n == 0:
        print(f"warning: no */SKILL.md under {root} — registering anyway (empty catalog)",
              file=sys.stderr)
    cfg = _load()
    entry = {"path": str(root)}
    if args.include:
        entry["include"] = args.include
    if args.exclude:
        entry["exclude"] = args.exclude
    cfg[args.alias] = entry
    _save(cfg)
    print(f"registered {args.alias} -> {root}  (skills≈{n})")
    print("index follows at the next reindex (auto at session start, or run reindex() now)")
    return 0


def cmd_remove(args):
    cfg = _load()
    if args.alias not in cfg:
        print(f"no catalog {args.alias!r} configured", file=sys.stderr)
        return 1
    cfg.pop(args.alias)
    _save(cfg)
    print(f"removed {args.alias} — its catalog:{args.alias} points prune at the next reindex")
    return 0


def cmd_promote(args):
    if ":" not in args.skill:
        print("promote takes <alias>:<name>", file=sys.stderr)
        return 1
    alias, name = args.skill.split(":", 1)
    # Reject path-traversal / nested names: a skill dir is a single path component,
    # so anything with a separator or `..` would resolve src/dst outside the catalog
    # and promotion dirs. Bare-name only.
    if not name or name in (".", "..") or "/" in name or "\\" in name or os.sep in name:
        print(f"invalid skill name {name!r} (bare directory name only, no path separators)",
              file=sys.stderr)
        return 1
    roots = _configured_roots(_load())
    if alias not in roots:
        print(f"no catalog {alias!r} configured", file=sys.stderr)
        return 1
    src = Path(os.path.expanduser(str(roots[alias]["path"]))) / name
    if not (src / "SKILL.md").is_file():
        print(f"no skill at {src}", file=sys.stderr)
        return 1
    dst = PROMOTE_DIR / name
    if dst.exists() or dst.is_symlink():
        print(f"refusing: {dst} already exists — resolve the collision by hand", file=sys.stderr)
        return 1
    PROMOTE_DIR.mkdir(parents=True, exist_ok=True)
    dst.symlink_to(src)
    print(f"promoted {args.skill} -> {dst} (symlink; catalog clone stays the source of truth)")
    print(f"note: {name!r} is now an installed skill — it costs per-turn context like any other; "
          "the catalog twin is auto-suppressed at the next reindex")
    return 0


def cmd_selftest(_):
    import tempfile
    global CONFIG, PROMOTE_DIR
    saved = (CONFIG, PROMOTE_DIR)
    ok = True
    try:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            CONFIG = tdp / "catalog-roots.json"
            PROMOTE_DIR = tdp / "skills"
            cat = tdp / "cat"
            (cat / "seo").mkdir(parents=True)
            (cat / "seo" / "SKILL.md").write_text("---\ndescription: d\n---\nb")
            # add (valid) / add (bad alias) / list state
            ok &= cmd_add(argparse.Namespace(alias="anti", path=str(cat),
                                             include=None, exclude=None)) == 0
            ok &= cmd_add(argparse.Namespace(alias="Bad!", path=str(cat),
                                             include=None, exclude=None)) == 1
            ok &= set(_configured_roots(_load())) == {"anti"}
            # promote: works once, refuses the collision
            ok &= cmd_promote(argparse.Namespace(skill="anti:seo")) == 0
            ok &= (PROMOTE_DIR / "seo").is_symlink()
            ok &= cmd_promote(argparse.Namespace(skill="anti:seo")) == 1
            # promote: rejects path-traversal names (no escape from the dirs)
            ok &= cmd_promote(argparse.Namespace(skill="anti:../../etc/x")) == 1
            ok &= cmd_promote(argparse.Namespace(skill="anti:..")) == 1
            # broken promotion detected after the catalog skill vanishes
            (cat / "seo" / "SKILL.md").unlink()
            (cat / "seo").rmdir()
            ok &= len(_broken_promotions(_load())) == 1
            # remove
            ok &= cmd_remove(argparse.Namespace(alias="anti")) == 0
            ok &= _configured_roots(_load()) == {}
            ok &= cmd_remove(argparse.Namespace(alias="anti")) == 1
    finally:
        CONFIG, PROMOTE_DIR = saved
    print("catalogs --selftest " + ("OK" if ok else "FAIL"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selftest", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("list")
    p_add = sub.add_parser("add")
    p_add.add_argument("alias")
    p_add.add_argument("path")
    p_add.add_argument("--include", nargs="*", default=None)
    p_add.add_argument("--exclude", nargs="*", default=None)
    p_rm = sub.add_parser("remove")
    p_rm.add_argument("alias")
    p_pr = sub.add_parser("promote")
    p_pr.add_argument("skill")
    args = ap.parse_args()
    if args.selftest:
        return cmd_selftest(args)
    return {"list": cmd_list, "add": cmd_add, "remove": cmd_remove,
            "promote": cmd_promote, None: cmd_list}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
