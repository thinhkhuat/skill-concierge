#!/usr/bin/env python3
"""
Analyze the skill-concierge invocation ledger.

Reads the append-only JSONL ledger and reports the numbers that drive decisions:
  • uptake rate  — of substantive turns, how often Claude actually used a skill
  • search rate  — how often Claude called the semantic retriever
  • dodge rate   — substantive turn with NO skill and NO search (the behaviour the
                   enforcement layer exists to kill)
  • per-skill rollups — auto-invoked frequency + manual /skill frequency
                   (the evidence base for always-on promote/demote)

hit@k (was the auto-invoked skill in the offered set?) is intentionally NOT computed
yet: `offer` events come from the rewritten enforcer hook (a later build phase). Until
then there is no offered-set to compare against, so hit@k is reported as pending.

Pure stdlib, read-only. Usage:  python3 analyze.py [path-to-ledger.log]
"""
import sys
import os
import json
from pathlib import Path
from collections import Counter

LEDGER = Path(os.environ.get(
    "SKILL_CONCIERGE_LOG", Path.home() / ".claude" / "skill-telemetry" / "logs")
) / "skill-invocation-ledger.log"


def load(path):
    events = []
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except Exception:
                pass  # tolerate a partial last line / corrupt row
    except FileNotFoundError:
        pass
    return events


def known_skill_ids():
    """Live skill-name set from the which-skills catalogue, to separate real skills
    from built-in/plugin slash commands in the manual rollup. Interim source:
    library.json (the plan unifies this onto the Qdrant index later). Empty if absent."""
    p = Path.home() / ".claude" / "which-skills" / "library.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        ids = set()
        for s in d.get("skills", []):
            for k in ("id", "name"):
                if isinstance(s.get(k), str):
                    ids.add(s[k])
        return ids, str(p)
    except Exception:
        return set(), None


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else str(LEDGER)
    events = load(path)
    events.sort(key=lambda e: e.get("t", 0))

    # Segment into per-session turn windows. A `turn`/`manual` opens a window;
    # subsequent `auto`/`search` for that session attach to its latest window.
    turns, cur = [], {}
    for e in events:
        sid, ev = e.get("sid", ""), e.get("ev")
        if ev in ("turn", "manual"):
            w = {"sid": sid, "kind": ev, "q": e.get("q", ""),
                 "name": e.get("name", ""), "autos": [], "searches": 0}
            turns.append(w)
            cur[sid] = w
        elif ev == "auto":
            w = cur.get(sid)
            if w is None:
                w = {"sid": sid, "kind": "orphan-auto", "q": "",
                     "name": "", "autos": [], "searches": 0}
                turns.append(w)
                cur[sid] = w
            w["autos"].append(e.get("name") or "?")
        elif ev == "search":
            w = cur.get(sid)
            if w is None:
                w = {"sid": sid, "kind": "orphan-search", "q": "",
                     "name": "", "autos": [], "searches": 0}
                turns.append(w)
                cur[sid] = w
            w["searches"] += 1

    windows = [w for w in turns if w["kind"] == "turn" and w["q"].strip()]
    manual = [w for w in turns if w["kind"] == "manual"]
    n = len(windows)
    used = sum(1 for w in windows if w["autos"])
    searched = sum(1 for w in windows if w["searches"])
    dodge = sum(1 for w in windows if not w["autos"] and not w["searches"])

    auto_freq = Counter(a for w in turns for a in w["autos"])
    names = [w["name"] for w in manual if w["name"]]
    skills, cat_src = known_skill_ids()
    if skills:
        manual_skill = Counter(nm for nm in names if nm in skills)
        manual_other = Counter(nm for nm in names if nm not in skills)
    else:
        manual_skill, manual_other = Counter(names), Counter()

    def pct(x):
        return f"{(100 * x / n):.0f}%" if n else "n/a"

    print(f"ledger        : {path}")
    print(f"events        : {len(events)}   turn-windows: {n}   manual: {len(manual)}")
    print(f"uptake        : {used}/{n}  {pct(used)}   (turn used a skill)")
    print(f"search called : {searched}/{n}  {pct(searched)}")
    print(f"dodge         : {dodge}/{n}  {pct(dodge)}   (no skill, no search)")
    print(f"hit@k         : pending (needs `offer` events from the enforcer hook)")
    print(f"top auto      : {auto_freq.most_common(10)}")
    if skills:
        print(f"top manual (real skill)     : {manual_skill.most_common(10)}")
        print(f"manual (built-in/non-skill) : {manual_other.most_common(10)}   [split via {cat_src}]")
    else:
        print(f"top manual (UNFILTERED)     : {manual_skill.most_common(10)}   [catalogue unavailable — includes built-in slashes]")
    print("note: `turn` denominator = non-empty non-slash prompts (NOT offer/triviality-gated);")
    print("      treat dodge/uptake as a proxy upper-bound until `offer` events land, then re-derive vs offered turns.")


if __name__ == "__main__":
    main()
