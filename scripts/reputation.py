#!/usr/bin/env python3
"""
reputation — view / set the owner's skill ranking (~/.claude/skill-concierge/reputation.json).

The owner's ranking puts a badge next to a skill on the per-turn menu (ADR-0083):

  ❤️ heart  house favourite — the owner's pick for its job
  ⭐ star   trusted — vetted, preferred over skills the owner does not know
  🔥        proven — computed from usage at session start (auto_promote.py), not set here

A badge never moves a row. The menu's legend line tells the agent how to choose with them: among
rows that do the task's job as their main purpose, take ❤️ first, then ⭐, then the highest row.
A ❤️ or ⭐ skill Jev ranked 6th-10th joins the menu below its five rows when Jev judged it a fit.

  reputation.py list                         show both tiers and the current 🔥 list
  reputation.py add heart|star <name> [...]  rank skill(s); a name moves out of the other tier
  reputation.py remove <name> [...]          unrank skill(s), from either tier
  reputation.py why <name> [...]             the badge each name gets, and which entry gives it
  reputation.py suggest [--apply]            propose tier changes from usage and what is installed;
                                             --apply backs the file up, then writes them

SUGGEST (the owner's maintenance pass; run it monthly)
  ❤️  promote  a 🔥 skill (≥5 sessions in 30 days) that is unranked or only ⭐
  ⭐  add      an unranked skill used in ≥2 sessions in 90 days
  ✗  remove   an exact entry no longer installed, or a pattern that matches nothing installed
  ?  review   a ❤️ entry with no recorded use for 90 days. Printed only, never applied: the log
              misses rule-driven use and direct SKILL.md reads, and a ❤️ is the owner's judgement
A "use" is a Skill-tool load or a get_skill read in the ledger. ❤️ is the owner's judgement, so
--apply never adds or removes one: it writes the add and remove lines, and promote and review lines
change only when the owner runs their command (the owner's choice, 2026-10-07, ADR-0084).

NAMES
  An exact entry matches the menu's name exactly (`ak-code-review`, `pstack:architect`).
  A pattern entry (`pstack:*`, `ak-*`) ranks a whole family. An exact entry beats every
  pattern; between two matches of one kind, ❤️ wins.

The file is read live by the per-turn hook: an edit applies on the next prompt, with no
reindex and no restart. Test seams (env): SKILL_CONCIERGE_REPUTATION (exact file),
SKILL_CONCIERGE_PROVEN (the 🔥 digest). Pure stdlib.
"""
import argparse
import fnmatch
import json
import os
import re
import sys
from argparse import Namespace
from pathlib import Path

TIERS = (("heart", "❤️"), ("star", "⭐"))
NOTE = ("Owner's skill ranking (ADR-0083). heart = house favourite, star = trusted. "
        "Exact names or patterns such as `pstack:*`; an exact entry beats every pattern. "
        "Manage with scripts/reputation.py.")


def _path() -> Path:
    return Path(os.environ.get("SKILL_CONCIERGE_REPUTATION",
                               Path.home() / ".claude" / "skill-concierge" / "reputation.json"))


def _proven_path() -> Path:
    return Path(os.environ.get("SKILL_CONCIERGE_PROVEN",
                               Path.home() / ".claude" / "skill-concierge" / "proven.json"))


def _load():
    """The file, each tier normalized the way the hook reads it (strings only, stripped, non-empty)."""
    p = _path()
    if not p.exists():
        return {"_note": NOTE, "heart": [], "star": []}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (UnicodeError, ValueError) as e:
        raise SystemExit(f"reputation file unreadable: {p}: {e}. The hook shows no badge until it is fixed.")
    if not isinstance(raw, dict):
        raise SystemExit(f"reputation file invalid: {p} is not a JSON object")
    for tier, _m in TIERS:
        lst = raw.get(tier, [])
        if not isinstance(lst, list):
            raise SystemExit(f"reputation file invalid: \"{tier}\" in {p} is not a list")
        raw[tier] = [n.strip() for n in lst if isinstance(n, str) and n.strip()]
    return raw


def _save(raw):
    for tier, _m in TIERS:
        raw[tier] = sorted(set(raw[tier]))
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def _proven():
    try:
        data = json.loads(_proven_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _is_pattern(entry: str) -> bool:
    return any(ch in entry for ch in "*?[")


def _resolve(name: str, raw: dict):
    """(tier, entry) by the enforcer's rule: exact entries first (❤️ before ⭐), then patterns."""
    for tier, _m in TIERS:
        if name in raw.get(tier, []):
            return tier, name
    for tier, _m in TIERS:
        for p in raw.get(tier, []):
            try:
                if _is_pattern(p) and fnmatch.fnmatchcase(name, p):
                    return tier, p
            except re.error:
                continue      # the hook skips a malformed pattern the same way
    return None, None


def _family(name: str) -> str:
    """Display group: patterns, the plugin of `plugin:skill`, the `ak`/`vn`/`tk` prefix, else own."""
    if _is_pattern(name):
        return "patterns"
    if ":" in name:
        return name.split(":", 1)[0]
    head = name.split("-", 1)[0]
    return head if head in ("ak", "vn", "tk") else "other"


def _grouped(names: list) -> list:
    """Lines `  <family> (n): a, b, c`, largest family first; every name shown."""
    fam = {}
    for n in sorted(names):
        fam.setdefault(_family(n), []).append(n)
    order = sorted(fam, key=lambda f: (f != "patterns", -len(fam[f]), f))
    return [f"  {f} ({len(fam[f])}): {', '.join(fam[f])}" for f in order]


def _bucketed(counts: dict) -> list:
    """Lines `  20+: a 41, b 29` by session count, busiest first."""
    out = []
    for label, lo, hi in (("20+", 20, 10**9), ("10-19", 10, 19), ("6-9", 6, 9), ("≤5", 0, 5)):
        row = sorted(((c, n) for n, c in counts.items() if lo <= c <= hi), key=lambda x: (-x[0], x[1]))
        if row:
            out.append(f"  {label}: {', '.join(f'{n} {c}' for c, n in row)}")
    return out


def cmd_list(_):
    raw = _load()
    pv = _proven()
    counts = pv.get("counts") or {}
    print(f"❤️ {len(raw['heart'])} · ⭐ {len(raw['star'])} · 🔥 {len(counts)}   ({_path()})")
    for tier, mark in TIERS:
        print(f"{mark} {tier}")
        print("\n".join(_grouped(raw[tier])) or "  (none)")
    print(f"🔥 proven (sessions in {pv.get('window_days', 30)} days)")
    print("\n".join(_bucketed(counts)) or "  (no digest yet: written at session start)")
    return 0


def cmd_add(args):
    raw = _load()
    other = "star" if args.tier == "heart" else "heart"
    moved = [n for n in args.names if n in raw[other]]
    raw[other] = [n for n in raw[other] if n not in args.names]
    new = [n for n in args.names if n not in raw[args.tier]]
    raw[args.tier] = raw[args.tier] + new
    _save(raw)
    mark = dict(TIERS)[args.tier]
    print(f"{mark} {args.tier}: added {', '.join(new) if new else '(already there)'}"
          + (f"; moved from {other}: {', '.join(moved)}" if moved else ""))
    return 0


def cmd_remove(args):
    raw = _load()
    gone = [n for n in args.names if any(n in raw[t] for t, _m in TIERS)]
    for tier, _m in TIERS:
        raw[tier] = [n for n in raw[tier] if n not in args.names]
    if not gone:
        print(f"not ranked: {', '.join(args.names)} (no change)")
        return 0
    _save(raw)
    print(f"unranked: {', '.join(gone)}")
    return 0


def cmd_why(args):
    if os.environ.get("SKILL_REPUTATION", "1") == "0":
        print("SKILL_REPUTATION=0: the hook shows no badge at all")
        return 0
    raw = _load()
    proven = set(_proven().get("proven", []))
    for n in args.names:
        tier, entry = _resolve(n, raw)
        mark = (dict(TIERS)[tier] if tier else "") + ("🔥" if n in proven else "")
        src = []
        if tier:
            src.append(f"{tier} via {'exact entry' if entry == n else f'pattern {entry}'}")
        if n in proven:
            src.append("proven by usage")
        print(f"  {n}: {mark or '(no badge)'}" + (f" — {'; '.join(src)}" if src else ""))
    return 0


HOME = Path.home()
SUGGEST_WINDOW_DAYS = 90
SUGGEST_MIN_SESSIONS = 2
USE_EVENTS = ("auto", "manual", "get_skill")   # a Skill-tool load or a get_skill read


def _installed():
    """(names, complete, plugin_prefixes) for Claude Code on this machine. Personal skills by
    directory name; plugin skills as <plugin>:<dir> at both depths under <installPath>/skills
    (category folders included, a skill directory owning everything below it — the discovery
    engine's own rule). `complete` is False when either source could not be read, and then
    `suggest` proposes no removal: a partial view must never read as "uninstalled"."""
    import glob
    names, complete, prefixes = set(), True, set()
    root = HOME / ".claude" / "skills"
    if root.is_dir():
        names |= {p.parent.name for p in root.glob("*/SKILL.md")}
    else:
        complete = False
    try:
        reg = json.loads((HOME / ".claude" / "plugins" / "installed_plugins.json").read_text(encoding="utf-8"))
        for pid, installs in (reg.get("plugins") or {}).items():
            plugin = pid.split("@")[0]
            prefixes.add(plugin)
            for inst in installs if isinstance(installs, list) else []:
                base = Path(inst.get("installPath", "")) / "skills"
                flat = glob.glob(str(base / "*" / "SKILL.md"))
                owners = {os.path.dirname(f) for f in flat}
                nested = [n for n in glob.glob(str(base / "*" / "*" / "SKILL.md"))
                          if os.path.dirname(os.path.dirname(n)) not in owners]
                names |= {f"{plugin}:{Path(h).parent.name}" for h in flat + nested}
    except (OSError, ValueError, AttributeError, TypeError):
        complete = False
    return names, complete, prefixes


def _ap():
    """auto_promote.py as a module: its ledger counter (alias folding included) and its env-checked
    🔥 bar, so `suggest` and the menu's 🔥 can never disagree."""
    import importlib.util
    path = Path(__file__).resolve().parent.parent / "hooks" / "scripts" / "auto_promote.py"
    spec = importlib.util.spec_from_file_location("auto_promote_for_reputation", path)
    ap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ap)
    return ap


def _suggestions(raw: dict, installed: set, used_short: dict, used90: dict, proven_min: int,
                 short_days: int = 30, can_remove: bool = True, can_review: bool = True,
                 prefixes=None) -> list:
    """Pure: [(action, tier_or_None, name, reason)] in a stable order. A removal is proposed only
    when the installed view is complete and the entry is one this view can judge: a bare personal
    name, or `<plugin>:...` of a plugin Claude Code has registered (another harness's entries stay)."""
    out = []
    for n in sorted(n for n, c in used_short.items() if c >= proven_min and n in installed):
        tier, _e = _resolve(n, raw)
        if tier != "heart":
            out.append(("promote", "heart", n, f"🔥 {used_short[n]} sessions in {short_days} days, now {tier or 'unranked'}"))
    for n in sorted(n for n, c in used90.items() if c >= SUGGEST_MIN_SESSIONS and n in installed):
        if _resolve(n, raw)[0] is None and not any(s[2] == n for s in out):
            out.append(("add", "star", n, f"used in {used90[n]} sessions in {SUGGEST_WINDOW_DAYS} days, unranked"))
    if can_review:
        for n in raw["heart"]:
            if not _is_pattern(n) and n in installed and used90.get(n, 0) == 0:
                out.append(("review", "star", n, f"❤️ with no recorded use for {SUGGEST_WINDOW_DAYS} days; "
                                                  "rule-driven use is not logged, so your call"))
    if can_remove:
        judgeable = lambda n: ":" not in n or prefixes is None or n.split(":", 1)[0] in prefixes
        for tier, _m in TIERS:
            for n in raw[tier]:
                if _is_pattern(n):
                    try:
                        hit = any(fnmatch.fnmatchcase(x, n) for x in installed)
                    except re.error:
                        hit = False
                    if not hit:
                        out.append(("remove", None, n, f"{tier} pattern matches no installed skill"))
                elif n not in installed and judgeable(n):
                    out.append(("remove", None, n, f"{tier} entry is not installed"))
    return out


def cmd_suggest(args):
    import shlex
    import time
    raw = _load()
    ap = _ap()
    installed, complete, prefixes = _installed()
    used_short = ap._proven_counts(evs=USE_EVENTS)
    used90 = ap._proven_counts(evs=USE_EVENTS, window_days=SUGGEST_WINDOW_DAYS)
    start = ap._ledger_start(evs=USE_EVENTS)
    covered = start is not None and start <= time.time() - SUGGEST_WINDOW_DAYS * 86400
    sugg = _suggestions(raw, installed, used_short, used90, ap.PROVEN_MIN_SESSIONS, ap.PROVEN_WINDOW_DAYS,
                        can_remove=complete, can_review=covered, prefixes=prefixes)
    if not complete:
        print("note: the installed-skill view is incomplete (a skills root or the plugin registry is "
              "unreadable), so no removal is proposed")
    if not covered:
        days = 0 if start is None else int((time.time() - start) / 86400)
        print(f"note: the usage log covers {days} days, not {SUGGEST_WINDOW_DAYS}, so no ❤️ is reviewed")
    if not sugg:
        print("No suggestions.")
        return 0
    n_apply = sum(1 for s in sugg if s[0] in APPLIED)
    if not args.apply:
        print("\n".join(_fmt_suggest(sugg, used_short, used90)))
        return 0
    p = _path()
    if p.exists():
        import datetime
        bak = p.with_name(f"{p.name}.bak-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')}")
        bak.write_bytes(p.read_bytes())
        print(f"backup: {bak}")
    _save(_apply(raw, sugg))
    print(f"applied {n_apply} suggestion(s) to {p}; {len(sugg) - n_apply} ❤️ line(s) left for you")
    return 0


APPLIED = ("add", "remove")


def _fmt_suggest(sugg: list, used_short: dict, used90: dict) -> list:
    """Pure: the suggest report. Line 1 is the next command; then one group per action, every
    name shown once with its session count, busiest first."""
    import shlex
    by = {}
    for action, _tier, n, _why in sugg:
        by.setdefault(action, []).append(n)
    n_apply = sum(len(by.get(a, [])) for a in APPLIED)
    if n_apply:
        out = [f"Next: reputation.py suggest --apply   (writes {n_apply} ⭐/✗ lines; never touches ❤️)"]
    else:
        out = ["Next: reputation.py add heart <name>   (for each ❤️ pick you accept)"]
    heads = (("add", "⭐ add", used90, "90d"), ("remove", "✗ remove", None, ""),
             ("promote", "? ❤️ promote — your call", used_short, "30d"),
             ("review", "? ❤️ review — no logged use in 90d; demote: add star <name>", None, ""))
    for action, head, counts, win in heads:
        names = by.get(action)
        if not names:
            continue
        if counts is not None:
            names = sorted(names, key=lambda n: (-counts.get(n, 0), n))
            items = [f"{n} {counts.get(n, 0)}" for n in names]
            head += f" (sessions, {win})"
        else:
            items = [shlex.quote(n) if action == "remove" else n for n in names]
        out += [f"{head} [{len(names)}]", "  " + ", ".join(items)]
    return out   # ADR-0084: ❤️ changes only by the owner's own command


def _apply(raw: dict, sugg: list) -> dict:
    """Pure: the ranking with every add/remove written; a ❤️ is never added or removed here."""
    for action, tier, n, _why in sugg:
        if action not in APPLIED:
            continue
        for t, _m in TIERS:
            raw[t] = [x for x in raw[t] if x != n]
        if action != "remove":
            raw[tier].append(n)
    return raw


def cmd_selftest(_):
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        os.environ["SKILL_CONCIERGE_REPUTATION"] = str(Path(td) / "rep.json")
        os.environ["SKILL_CONCIERGE_PROVEN"] = str(Path(td) / "proven.json")
        cmd_add(Namespace(tier="star", names=["ak-*", "x"]))
        cmd_add(Namespace(tier="heart", names=["ak-code-review", "x"]))   # x moves star -> heart
        raw = json.loads(Path(td, "rep.json").read_text())
        assert raw["heart"] == ["ak-code-review", "x"] and raw["star"] == ["ak-*"], raw
        assert raw["_note"] == NOTE
        assert _resolve("ak-code-review", raw) == ("heart", "ak-code-review")
        assert _resolve("ak-git", raw) == ("star", "ak-*")
        assert _resolve("other", raw) == (None, None)
        cmd_remove(Namespace(names=["x", "zzz"]))
        raw = json.loads(Path(td, "rep.json").read_text())
        assert raw["heart"] == ["ak-code-review"], raw
    raw = {"heart": ["hot", "idle", "gone"], "star": ["ak-*", "zz-*", "warm"]}
    inst = {"hot", "idle", "warm", "ak-git", "fresh", "rising"}
    got = _suggestions(raw, inst, used_short={"rising": 6, "hot": 7, "warm": 1},
                       used90={"rising": 6, "hot": 7, "fresh": 2, "warm": 1}, proven_min=5)
    assert [(a, t, n) for a, t, n, _w in got] == [
        ("promote", "heart", "rising"),        # 🔥 and unranked -> ❤️ (hot is already ❤️)
        ("add", "star", "fresh"),              # used twice in 90 days, unranked
        ("review", "star", "idle"),            # ❤️ unused for 90 days -> printed, never applied
        ("remove", None, "gone"),              # exact entry not installed
        ("remove", None, "zz-*"),              # pattern matches nothing installed
    ], got
    applied = _apply({"heart": ["hot", "idle", "gone"], "star": ["ak-*", "zz-*", "warm"]}, got)
    assert applied == {"heart": ["hot", "idle"], "star": ["ak-*", "warm", "fresh"]}, applied   # no ❤️ change
    # bad input fails closed: no removal from an incomplete view, no review from a short log,
    # and an entry for a plugin Claude Code does not know is left for the harness that owns it
    quiet = _suggestions(raw, inst, {}, {}, proven_min=5, can_remove=False, can_review=False)
    assert quiet == [], quiet       # idle is installed and unused, gone is uninstalled: both held back
    other = _suggestions({"heart": [], "star": ["omp-only:thing", "known:gone"]}, {"x"}, {}, {}, 5,
                         prefixes={"known"})
    assert [(a, n) for a, _t, n, _w in other] == [("remove", "known:gone")], other
    rep_lines = _fmt_suggest(got, {"rising": 6}, {"fresh": 2})
    assert rep_lines[0].startswith("Next: reputation.py suggest --apply"), rep_lines
    body = "\n".join(rep_lines[1:])
    for _a, _t, n, _w in got:
        assert body.count(n) == 1, (n, body)      # every name shown exactly once, none capped
    assert len(rep_lines) == 1 + 2 * 4, rep_lines  # four groups present: add, remove, promote, review
    assert _grouped(["ak-x", "ak-y", "*:*", "pstack:z", "solo"])[0].startswith("  patterns (1)")
    for k in ("SKILL_CONCIERGE_REPUTATION", "SKILL_CONCIERGE_PROVEN"):
        os.environ.pop(k, None)
    print("reputation selftest ok")
    return 0


def main():
    ap = argparse.ArgumentParser(description="View/set the owner's skill ranking (menu badges).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="show both tiers and the current 🔥 list").set_defaults(fn=cmd_list)
    pa = sub.add_parser("add", help="rank skill(s) heart or star")
    pa.add_argument("tier", choices=[t for t, _m in TIERS])
    pa.add_argument("names", nargs="+")
    pa.set_defaults(fn=cmd_add)
    pr = sub.add_parser("remove", help="unrank skill(s)")
    pr.add_argument("names", nargs="+")
    pr.set_defaults(fn=cmd_remove)
    pw = sub.add_parser("why", help="the badge each name gets, and the entry that gives it")
    pw.add_argument("names", nargs="+")
    pw.set_defaults(fn=cmd_why)
    ps = sub.add_parser("suggest", help="propose tier changes from usage and what is installed")
    ps.add_argument("--apply", action="store_true", help="back the file up, then write every suggestion")
    ps.set_defaults(fn=cmd_suggest)
    sub.add_parser("selftest", help=argparse.SUPPRESS).set_defaults(fn=cmd_selftest)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
