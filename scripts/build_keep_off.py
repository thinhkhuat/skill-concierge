#!/usr/bin/env python3
"""
Generate config/keep-off.json — the ledger-derived offer-suppression map (ADR-0011).

Hard-drops chronic never-take skills from the OFFER MENU only (not the catalogue). A skill is
suppressed iff offered >= MIN_OFFERS and taken <= MAX_TAKE_RATE of those, over a POST-ENRICHMENT
clean window (pre-enrichment per-skill counts are confounded). Reuses analyze._offer_conversion so
keep-off and the analyzer can NEVER report a divergent metric. Stdlib; read-only except the JSON write.

Usage:
  python3 build_keep_off.py [--since WHEN] [--ledger PATH] [--out PATH] [--full]
  --full   ignore --since (mechanism test: must reproduce the known never-takers)
"""
import os
import sys
import json
import argparse
import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import analyze  # reuse load / parse_when / _offer_conversion (the tested join)

ROOT = HERE.parent
OUT_DEFAULT = ROOT / "config" / "keep-off.json"
# Post-enrichment boundary (ADR-0011): v0.5.0 enrichment shipped 2026-06-28 (~16:05 per ship-log).
ENRICH_SINCE = os.environ.get("KEEPOFF_SINCE", "2026-06-28 16:05:00")
MIN_OFFERS = int(os.environ.get("KEEPOFF_MIN_OFFERS", "15"))
MAX_TAKE_RATE = float(os.environ.get("KEEPOFF_MAX_TAKE_RATE", "0.05"))
MIN_WINDOW_OFFERED_TURNS = int(os.environ.get("KEEPOFF_MIN_WINDOW", "40"))


def _windows(events):
    """Re-build of analyze.main()'s window loop (offer attached by sid,q), but attaching offered
    ONLY for band=='offer' events — the actually-SHOWN menu. getaway/intent_skip log candidates the
    agent never saw; counting them inflates 'offered' and risks over-suppression (review finding #1).
    As of 2026-06-30 analyze._offer_conversion keys on band=='offer' too (the metric was unified —
    ADR-0011 Open resolved), so this builder and the analyzer now report the SAME denominator; the
    window loop stays replicated (not imported) to keep the generator import-light."""
    events = [e for e in events if isinstance(e, dict)]
    events.sort(key=lambda e: e.get("t", 0))
    turns, cur, by_sid_q, offers = [], {}, {}, []
    for e in events:
        sid, ev = e.get("sid", ""), e.get("ev")
        if ev in ("turn", "manual"):
            w = {"sid": sid, "kind": ev, "q": e.get("q", ""), "autos": [], "offered": None}
            turns.append(w)
            cur[sid] = w
            if ev == "turn":
                by_sid_q[(sid, w["q"])] = w
        elif ev == "auto":
            w = cur.get(sid)
            if w is None:
                w = {"sid": sid, "kind": "orphan", "q": "", "autos": [], "offered": None}
                turns.append(w)
                cur[sid] = w
            w["autos"].append(e.get("name") or "?")
        elif ev == "offer":
            offers.append(e)
    for e in offers:
        if e.get("band") != "offer":
            continue  # count only SHOWN menus; getaway/intent_skip never reached the agent
        w = by_sid_q.get((e.get("sid", ""), e.get("q", "")))
        if w is not None:
            # set band too: analyze._offer_conversion now keys its denominator on
            # band=="offer" (the shared SHOWN-menu semantics, ADR-0011), so these
            # windows must carry the marker or the join would count zero.
            w["band"] = "offer"
            w["offered"] = [o[0] for o in e.get("offered", []) if isinstance(o, list) and o]
    return turns


def compute(events):
    turns = _windows(events)
    n_off, _took_any, off_by, took_by = analyze._offer_conversion(turns)
    keep_off, audit = [], []
    for skill in sorted(off_by, key=lambda k: (-off_by[k], k)):
        offered = off_by[skill]
        rate = took_by[skill] / offered if offered else 0.0
        if offered >= MIN_OFFERS and rate <= MAX_TAKE_RATE:
            keep_off.append(skill)
            audit.append({"name": skill, "offered": offered,
                          "taken": took_by[skill], "take_rate": round(rate, 4)})
    return n_off, keep_off, audit


def main():
    ap = argparse.ArgumentParser(description="Generate the keep-off offer-suppression map (ADR-0011).")
    ap.add_argument("--ledger", default=str(analyze.LEDGER))
    ap.add_argument("--since", default=ENRICH_SINCE)
    ap.add_argument("--out", default=str(OUT_DEFAULT))
    ap.add_argument("--full", action="store_true", help="ignore --since (mechanism test)")
    args = ap.parse_args()

    if args.full and Path(args.out).resolve() == OUT_DEFAULT.resolve():
        ap.error("--full produces pre-enrichment-confounded output; refusing to overwrite the live "
                 "config. Pass an explicit --out (e.g. a scratch path).")

    events = analyze.load(args.ledger)
    since = None if args.full else analyze.parse_when(args.since)
    if since is not None:
        events = [e for e in events if e.get("t") and e["t"] >= since]

    n_off, keep_off, audit = compute(events)
    sufficient = n_off >= MIN_WINDOW_OFFERED_TURNS
    if not sufficient:
        keep_off, audit = [], []  # data-sufficiency guard (ADR-0011)

    out = {
        "_note": (f"AUTO-GENERATED by build_keep_off.py (ADR-0011). Skills offered>={MIN_OFFERS} & "
                  f"take-rate<={MAX_TAKE_RATE:.0%} dropped from the OFFER MENU only (still "
                  f"search-reachable). DO NOT hand-edit; rerun the generator."),
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "window": "FULL LEDGER" if args.full else f">= {args.since}",
        "window_offered_turns": n_off,
        "data_sufficient": sufficient,
        "min_window_offered_turns": MIN_WINDOW_OFFERED_TURNS,
        "policy": {"min_offers": MIN_OFFERS, "max_take_rate": MAX_TAKE_RATE},
        "keep_off": keep_off,
        "_audit": audit,
    }
    Path(args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tag = "FULL/mechanism-test" if args.full else "post-enrichment"
    print(f"build_keep_off [{tag}]: offered-turns={n_off} sufficient={sufficient} -> {len(keep_off)} suppressed")
    for a in audit[:12]:
        print(f"    {a['name']:<32} {a['taken']}/{a['offered']}  {a['take_rate']*100:.0f}%")
    print(f"wrote: {args.out}")


if __name__ == "__main__":
    main()
