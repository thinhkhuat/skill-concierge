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

hit@k (was the auto-invoked skill in the offered set?) computes once `offer` events land
from the enforcer hook; before any offers it falls back to "pending" (no offered-set yet).

Pure stdlib, read-only. Usage:  python3 analyze.py [path-to-ledger.log]
"""
import sys
import os
import json
import urllib.request
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
    """Live skill-name set straight from the Qdrant index — the SAME catalogue the
    enforcer offers from — so the manual real-skill-vs-builtin split can't drift
    from what the retriever knows (kills the old 585/508/512 library.json drift).
    Scrolls all point payload `name`s (stdlib only). Empty set if Qdrant is down."""
    base = os.environ.get("SKILL_QDRANT_URL", "http://localhost:6333").rstrip("/")
    coll = os.environ.get("SKILL_COLLECTION", "claude_skills")
    url = f"{base}/collections/{coll}/points/scroll"
    ids, offset = set(), None
    try:
        while True:
            body = {"limit": 256, "with_payload": ["name"]}
            if offset is not None:
                body["offset"] = offset
            req = urllib.request.Request(
                url, data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json"})
            res = json.loads(urllib.request.urlopen(req, timeout=3).read())["result"]
            for p in res.get("points", []):
                nm = (p.get("payload") or {}).get("name")
                if isinstance(nm, str):
                    ids.add(nm)
            offset = res.get("next_page_offset")
            if offset is None:
                break
        return ids, f"{base}/{coll}"
    except Exception:
        return set(), None


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else str(LEDGER)
    events = load(path)
    events.sort(key=lambda e: e.get("t", 0))

    # Segment into per-session turn windows. A `turn`/`manual` opens a window;
    # subsequent `auto`/`search` for that session attach to its latest window.
    # `offer` (from the enforcer) fires in the SAME UserPromptSubmit as `turn`
    # but BEFORE it (hook array order), so a latest-window match would miss — we
    # collect offers and attach them by (sid, q) after windows are built.
    turns, cur, by_sid_q, offers = [], {}, {}, []
    for e in events:
        sid, ev = e.get("sid", ""), e.get("ev")
        if ev in ("turn", "manual"):
            w = {"sid": sid, "kind": ev, "q": e.get("q", ""), "name": e.get("name", ""),
                 "autos": [], "searches": 0, "offered": None, "band": None, "fallback": None}
            turns.append(w)
            cur[sid] = w
            if ev == "turn":
                by_sid_q[(sid, w["q"])] = w
        elif ev == "auto":
            w = cur.get(sid)
            if w is None:
                w = {"sid": sid, "kind": "orphan-auto", "q": "", "name": "",
                     "autos": [], "searches": 0, "offered": None, "band": None, "fallback": None}
                turns.append(w)
                cur[sid] = w
            w["autos"].append(e.get("name") or "?")
        elif ev == "search":
            w = cur.get(sid)
            if w is None:
                w = {"sid": sid, "kind": "orphan-search", "q": "", "name": "",
                     "autos": [], "searches": 0, "offered": None, "band": None, "fallback": None}
                turns.append(w)
                cur[sid] = w
            w["searches"] += 1
        elif ev == "offer":
            offers.append(e)

    # Attach offers to their turn window by (sid, q-prefix). Offer.q and turn.q
    # are both prompt[:120], so they match exactly.
    for e in offers:
        w = by_sid_q.get((e.get("sid", ""), e.get("q", "")))
        if w is not None:
            w["offered"] = [o[0] for o in e.get("offered", []) if isinstance(o, list) and o]
            w["band"] = e.get("band")
            w["fallback"] = e.get("fallback")

    windows = [w for w in turns if w["kind"] == "turn" and w["q"].strip()]
    manual = [w for w in turns if w["kind"] == "manual"]
    n = len(windows)
    used = sum(1 for w in windows if w["autos"])
    searched = sum(1 for w in windows if w["searches"])
    dodge = sum(1 for w in windows if not w["autos"] and not w["searches"])

    # hit@k — of turns that offered candidates AND used an auto skill, how often
    # the used skill was in the offered set (the retriever's precision payoff).
    eligible = [w for w in windows if w["offered"] and w["autos"]]
    hits = sum(1 for w in eligible if any(a in w["offered"] for a in w["autos"]))
    # fallback rate — offers that degraded to mandate-only (embed/qdrant down/slow).
    all_offers = [w for w in turns if w["band"] is not None]
    fb = sum(1 for w in all_offers if w["fallback"])
    band_freq = Counter(w["band"] for w in all_offers)

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
    if all_offers:
        hk = f"{hits}/{len(eligible)}  {(100*hits/len(eligible)):.0f}%" if eligible else "n/a (no offered+used turn yet)"
        print(f"hit@k         : {hk}   (used skill was in the offered set)")
        print(f"offers        : {len(all_offers)}   bands: {dict(band_freq)}")
        print(f"fallback rate : {fb}/{len(all_offers)}  {(100*fb/len(all_offers)):.0f}%   (mandate-only: embed/qdrant down or slow)")
    else:
        print(f"hit@k         : pending (no `offer` events yet — enforcer not live / no banked turns)")
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
