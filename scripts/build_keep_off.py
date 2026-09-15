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
import argparse
import datetime
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import analyze  # reuse load / parse_when / _offer_conversion (the tested join)

ROOT = HERE.parent
# ADR-0054: the generated map lives in the canonical durable home (the keep-on/blocklist
# pattern) so a plugin update cannot wipe it; config/keep-off.json stays the empty seed.
OUT_DEFAULT = Path(os.environ.get(
    "SKILL_CONCIERGE_KEEPOFF", Path.home() / ".claude" / "skill-concierge" / "keep-off.json"))
# Clean-window boundary. History: v0.5.0 enrichment 2026-06-28 16:05 (ADR-0011). ADR-0054
# moved it to the v0.47.0 epoch (harness-message lane + default-on routes + wider timeouts
# all change offer composition, so earlier per-skill conversion is confounded).
ENRICH_SINCE = os.environ.get("KEEPOFF_SINCE", "2026-09-15 00:00:00")
# Mirror of enforcer._HARNESS_MSG_RE (stdlib duplicate — the generator must not import the
# hook). Offers made on harness-generated text are excluded from the conversion join: they
# were the dominant source of "chronic never-take" slots (horizon-notify 0/201 in the
# v0.46.0 epoch, every one on a notification), and since v0.47.0 the enforcer skips them.
_HARNESS_MSG_RE = re.compile(
    r"^\s*(?:<task-notification>|<system-reminder>|<cross-session-message\b|<teammate-message\b"
    r"|Another Claude session sent a message|\[Request interrupted by user"
    r"|\[SYSTEM NOTIFICATION\b|This session is being continued from a previous conversation"
    r"|<file name=\"[^\"\n]*omp-msum-[^\"\n]*\">)")
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
        if _HARNESS_MSG_RE.match(e.get("q") or ""):
            continue  # ADR-0054: harness-generated text is not a turn the agent could take on
        w = by_sid_q.get((e.get("sid", ""), e.get("q", "")))
        if w is not None:
            # set band too: analyze._offer_conversion now keys its denominator on
            # band=="offer" (the shared SHOWN-menu semantics, ADR-0011), so these
            # windows must carry the marker or the join would count zero.
            w["band"] = "offer"
            w["offered"] = [o[0] for o in e.get("offered", []) if isinstance(o, list) and o]
    return turns


KEEP_ON_PATH = Path(os.environ.get(
    "SKILL_CONCIERGE_KEEPON", Path.home() / ".claude" / "skill-concierge" / "keep-on.json"))


def _keep_on_names():
    """Curated always-on skills are exempt from keep-off (ADR-0054): they are the operator's
    explicit choice, and the ledger cannot see inline USING takes (a SKILL.md read with no
    Skill tool) — the v0.46.0 backtest would have dropped `vn-doc-complete`, taken 3× inline.
    Fail-open: unreadable file -> no exemption."""
    try:
        data = json.loads(KEEP_ON_PATH.read_text(encoding="utf-8"))
        return {n for n in data.get("keep_on", []) if isinstance(n, str)}
    except (OSError, ValueError, AttributeError, TypeError):
        return set()


def compute(events):
    turns = _windows(events)
    n_off, _took_any, off_by, took_by = analyze._offer_conversion(turns)
    exempt = _keep_on_names()
    keep_off, audit = [], []
    for skill in sorted(off_by, key=lambda k: (-off_by[k], k)):
        if skill in exempt or skill.split(":", 1)[-1] in exempt:
            continue
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
        "generated_at": datetime.datetime.now(datetime.timezone.utc)
        .astimezone()
        .strftime("%Y-%m-%dT%H:%M:%S"),
        "window": "FULL LEDGER" if args.full else f">= {args.since}",
        "window_offered_turns": n_off,
        "data_sufficient": sufficient,
        "min_window_offered_turns": MIN_WINDOW_OFFERED_TURNS,
        "policy": {"min_offers": MIN_OFFERS, "max_take_rate": MAX_TAKE_RATE},
        "keep_off": keep_off,
        "_audit": audit,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tag = "FULL/mechanism-test" if args.full else "epoch-scoped"
    print(f"build_keep_off [{tag}]: offered-turns={n_off} sufficient={sufficient} -> {len(keep_off)} suppressed")
    for a in audit[:12]:
        print(f"    {a['name']:<32} {a['taken']}/{a['offered']}  {a['take_rate']*100:.0f}%")
    print(f"wrote: {args.out}")


if __name__ == "__main__":
    main()
