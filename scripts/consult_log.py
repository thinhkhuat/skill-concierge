#!/usr/bin/env python3
"""
consult_log.py — append a consult VERDICT row to the skill-invocation ledger.

ADR-0049. The uptake side of consult telemetry is already automatic: invoking the
consult skill logs an `auto` row (PostToolUse hook) and each recommended skill the
agent later invokes logs its own `auto` row. What was missing is the recommendation
itself — without it, "recommended but not taken" is indistinguishable from
"never recommended". This script closes that side.

Design contract (mirrors hooks/scripts/ledger.py):
  • FAIL-SILENT — telemetry must never break or block the consult turn.
  • ADDITIVE-ONLY — one JSONL append to the same ledger file; no rotation here.
  • No session_id on purpose: the skill-side invocation carries no hook payload.
    Joins land on the automatic rows; this row is the epoch-scoped verdict record
    (analyze.py treats unknown `ev` types as inert until taught).

Usage:
  python3 scripts/consult_log.py --shape CHAIN --primary "skill-a" \
      --chain "skill-a,skill-b" --externals 1
  python3 scripts/consult_log.py --selftest
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

LOG_DIR = Path(os.environ.get(
    "SKILL_CONCIERGE_LOG", Path.home() / ".claude" / "skill-concierge" / "logs"))
LEDGER = LOG_DIR / "skill-invocation-ledger.log"

_SHAPES = ("SINGLE", "CHAIN", "NONE")


def append_verdict(shape, primary, chain, externals):
    try:
        row = {
            "t": round(time.time(), 3),
            "ev": "consult_verdict",
            "shape": shape,
            "primary": primary,
            "chain": [c.strip() for c in chain.split(",") if c.strip()] if chain else [],
            "externals": externals,
        }
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with LEDGER.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return True
    except Exception:  # noqa: BLE001, S110 (fail-silent telemetry boundary)
        return False


def _selftest():
    import tempfile
    global LEDGER, LOG_DIR
    saved = (LEDGER, LOG_DIR)
    try:
        with tempfile.TemporaryDirectory() as td:
            LOG_DIR = Path(td)
            LEDGER = LOG_DIR / "ledger.log"
            ok = append_verdict("CHAIN", "skill-a", "skill-a, skill-b,,skill-c", 1)
            assert ok, "append_verdict returned False"
            rows = [json.loads(l) for l in LEDGER.read_text().splitlines()]
            assert len(rows) == 1, f"expected 1 row, got {len(rows)}"
            r = rows[0]
            assert r["ev"] == "consult_verdict"
            assert r["shape"] == "CHAIN"
            assert r["primary"] == "skill-a"
            assert r["chain"] == ["skill-a", "skill-b", "skill-c"], \
                f"chain parsing wrong: {r['chain']!r}"
            assert r["externals"] == 1
            assert "t" in r and isinstance(r["t"], float)
            # NONE shape: empty chain, empty primary
            ok = append_verdict("NONE", "", "", 0)
            assert ok
            rows = [json.loads(l) for l in LEDGER.read_text().splitlines()]
            assert rows[-1]["shape"] == "NONE" and rows[-1]["chain"] == []
            # fail-silence: an unwritable dir must return False, never raise
            LOG_DIR = Path("/proc/definitely-not-writable")
            LEDGER = LOG_DIR / "ledger.log"
            assert append_verdict("SINGLE", "x", "x", 0) is False, \
                "unwritable path must fail silent (False), not raise"
    finally:
        LEDGER, LOG_DIR = saved
    print("consult_log --selftest OK: verdict row shape + chain parsing + NONE "
          "+ fail-silent append")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--shape", default="", choices=list(_SHAPES) + [""],
                   help="verdict shape: SINGLE, CHAIN, or NONE")
    p.add_argument("--primary", default="",
                   help="the user-facing primary skill ('' when NONE)")
    p.add_argument("--chain", default="",
                   help="comma-separated ordered chain (empty when NONE)")
    p.add_argument("--externals", type=int, default=0,
                   help="how many picks in the verdict are external-catalog skills")
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args()

    if args.selftest:
        _selftest()
    else:
        if not args.shape:
            p.error("--shape is required (SINGLE | CHAIN | NONE)")
        sys.exit(0 if append_verdict(args.shape, args.primary, args.chain,
                                     args.externals) else 1)
