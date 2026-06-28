#!/usr/bin/env python3
"""
Analyze the skill-concierge invocation ledger.

Reads the append-only JSONL ledger and reports the numbers that drive decisions:
  • uptake rate  — of substantive turns, how often Claude actually used a skill
  • search rate  — how often Claude called the semantic retriever
  • dodge rate   — substantive turn with NO skill and NO search (the behaviour the
                   enforcement layer exists to kill)
  • offered-turn conversion / per-skill offer\u2192take (C1) — of turns where a skill was
                   actually OFFERED, how often the agent took one (the compliance denominator,
                   cleaner than global dodge which includes getaway/no-offer turns)
  • per-skill rollups — auto-invoked frequency + manual /skill frequency
                   (the evidence base for always-on promote/demote)

hit@k (was the auto-invoked skill in the offered set?) computes once `offer` events land
from the enforcer hook; before any offers it falls back to "pending" (no offered-set yet).

Pure stdlib, read-only.

Usage:
  python3 analyze.py [path-to-ledger.log] [--since WHEN] [--until WHEN]

`--since`/`--until` window the ledger by event time so you don't have to split it by
hand. WHEN is epoch seconds or a local ISO time (`YYYY-MM-DD` or `YYYY-MM-DD HH:MM:SS`).
Before/after compare around a fix/ship point T (e.g. a commit time):
  python3 analyze.py --until "T"     # the "before" window
  python3 analyze.py --since "T"     # the "after"  window
"""
import os
import json
import argparse
import datetime
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


def parse_when(s):
    """Parse a --since/--until value into epoch seconds (local time).
    Accepts raw epoch seconds, or an ISO-ish date / datetime:
    `YYYY-MM-DD`, `YYYY-MM-DD HH:MM[:SS]`, or `YYYY-MM-DDTHH:MM[:SS]`.
    Tip — a git commit time is a valid boundary; grab it with
    `git show -s --format=%cd --date=format:'%Y-%m-%d %H:%M:%S' <ref>`."""
    s = s.strip()
    try:
        return float(s)  # bare epoch seconds
    except ValueError:
        pass
    iso = s.replace("/", "-")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(iso, fmt).timestamp()
        except ValueError:
            continue
    raise SystemExit(
        f"--since/--until: cannot parse '{s}' "
        f"(use epoch seconds, 'YYYY-MM-DD', or 'YYYY-MM-DD HH:MM:SS' in local time)")


def _offer_conversion(windows):
    """C1 offers<->takes join. For turns where the enforcer offered >=1 candidate:
      - turn-level conversion: did the agent invoke ANY offered skill that turn?
      - per-skill: how often each skill was offered, and of those turns how often
        that SAME skill was actually invoked (its own pull, not the turn's).
    Returns (n_offered_turns, n_took_any, offered_by_skill, took_by_skill)."""
    offered_turns = [w for w in windows if w.get("offered")]
    took_any = sum(1 for w in offered_turns
                   if any(a in w["offered"] for a in w["autos"]))
    off_by, took_by = Counter(), Counter()
    for w in offered_turns:
        autos = set(w["autos"])
        for skill in set(w["offered"]):
            off_by[skill] += 1
            if skill in autos:
                took_by[skill] += 1
    return len(offered_turns), took_any, off_by, took_by


def _run_selftest():
    """Pin the C1 join contract on synthetic turn-windows."""
    windows = [
        {"offered": ["a", "b"], "autos": ["a"]},   # converted on a
        {"offered": ["a", "c"], "autos": []},       # dodged
        {"offered": ["b"], "autos": ["b"]},          # converted on b
        {"offered": [], "autos": ["z"]},             # NOT an offered turn
    ]
    n_off, took, off_by, took_by = _offer_conversion(windows)
    bad = []
    if n_off != 3:
        bad.append(f"offered_turns expected 3, got {n_off}")
    if took != 2:
        bad.append(f"took_any expected 2, got {took}")
    if dict(off_by) != {"a": 2, "b": 2, "c": 1}:
        bad.append(f"offered_by_skill wrong: {dict(off_by)}")
    if dict(took_by) != {"a": 1, "b": 1}:
        bad.append(f"took_by_skill wrong: {dict(took_by)}")
    if bad:
        print("analyze --selftest FAIL:")
        for b in bad:
            print("  " + b)
        return 1
    print("analyze --selftest OK: offer->take join (turn conversion + per-skill)")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="Analyze the skill-concierge invocation ledger.")
    ap.add_argument("path", nargs="?", default=str(LEDGER),
                    help="ledger file to read (default: the live telemetry log)")
    ap.add_argument("--since", metavar="WHEN",
                    help="keep only events at/after WHEN (epoch or local ISO time)")
    ap.add_argument("--until", metavar="WHEN",
                    help="keep only events BEFORE WHEN (epoch or local ISO time)")
    ap.add_argument("--selftest", action="store_true",
                    help="run the C1 offer->take join self-check and exit")
    args = ap.parse_args()
    if args.selftest:
        raise SystemExit(_run_selftest())
    path = args.path

    events = load(path)
    n_total = len(events)
    since = parse_when(args.since) if args.since else None
    until = parse_when(args.until) if args.until else None
    if since is not None or until is not None:
        # Window the ledger by event time. Events without a `t` can't be placed
        # in a window, so they're dropped here (kept only on a full-ledger run).
        events = [e for e in events
                  if e.get("t")
                  and (since is None or e["t"] >= since)
                  and (until is None or e["t"] < until)]
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
    n_off_turns, took_off, offered_by_skill, took_by_skill = _offer_conversion(windows)

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
    if since is not None or until is not None:
        def _fmt(t):
            return datetime.datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M") if t else "—"
        print(f"window        : [{_fmt(since)} .. {_fmt(until)})   "
              f"{len(events)}/{n_total} events in window")
    print(f"events        : {len(events)}   turn-windows: {n}   manual: {len(manual)}")
    print(f"uptake        : {used}/{n}  {pct(used)}   (turn used a skill)")
    print(f"search called : {searched}/{n}  {pct(searched)}")
    print(f"dodge         : {dodge}/{n}  {pct(dodge)}   (no skill, no search)")
    if all_offers:
        hk = f"{hits}/{len(eligible)}  {(100*hits/len(eligible)):.0f}%" if eligible else "n/a (no offered+used turn yet)"
        print(f"hit@k         : {hk}   (used skill was in the offered set)")
        print(f"offers        : {len(all_offers)}   bands: {dict(band_freq)}")
        print(f"fallback rate : {fb}/{len(all_offers)}  {(100*fb/len(all_offers)):.0f}%   (mandate-only: embed/qdrant down or slow)")
        if n_off_turns:
            conv = 100 * took_off / n_off_turns
            print(f"offered-turn conv : {took_off}/{n_off_turns}  {conv:.0f}%   (offered \u22651 skill -> agent used one of them)")
            print(f"offered-turn dodge: {n_off_turns - took_off}/{n_off_turns}  {100 - conv:.0f}%   (offered yet none used \u2014 the compliance gap)")
            rows = sorted(offered_by_skill, key=lambda k: (-offered_by_skill[k], -took_by_skill[k]))
            print("per-skill offer\u2192take (top 10 by times offered):")
            for skill in rows[:10]:
                off, tk = offered_by_skill[skill], took_by_skill[skill]
                print(f"    {skill:<30} {tk}/{off}  {(100*tk/off):.0f}%")
    else:
        print(f"hit@k         : pending (no `offer` events yet — enforcer not live / no banked turns)")
    print(f"top auto      : {auto_freq.most_common(10)}")
    if skills:
        print(f"top manual (real skill)     : {manual_skill.most_common(10)}")
        print(f"manual (built-in/non-skill) : {manual_other.most_common(10)}   [split via {cat_src}]")
    else:
        print(f"top manual (UNFILTERED)     : {manual_skill.most_common(10)}   [catalogue unavailable — includes built-in slashes]")
    print("note: `turn` denominator = non-empty non-slash prompts (NOT offer/triviality-gated);")
    print("      global dodge/uptake are a proxy upper-bound (they include getaway/no-offer turns).")
    print("      The real compliance signal is `offered-turn conv/dodge` above: dodge measured ONLY")
    print("      on turns where the enforcer actually surfaced a skill.")


if __name__ == "__main__":
    main()
