#!/usr/bin/env python3
"""Baseline: the embedding-based actionability gate (enforcer `_is_imperative` + `_intent_conversational`,
bypassed on Jev turns since ADR-0061) on the same pos / neg / unl populations and probes as the Jev replay.
Local embed + index owner only; no Jev calls."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "scripts"))
sys.path.insert(0, str(HERE))
import calibrate_jev_gate as cal  # noqa: E402
from live_turn_type_replay import PROBES, populations  # noqa: E402


def skips(enf, prompt):
    return (not enf._is_imperative(prompt)) and enf._intent_conversational(enf._embed(prompt))


def main():
    enf = cal.load_enforcer()
    for pop, rows in populations(enf).items():
        k = sum(skips(enf, r["prompt"]) for r in rows)
        n = len(rows)
        extra = f" (UCB95 {100 * cal.wilson_upper(k, n):.1f}%)" if pop == "pos" else ""
        print(f"{pop}: intent gate skips {k}/{n} = {100 * k / max(n, 1):.1f}%{extra}")
    for kind, p in PROBES:
        print(f"probe {kind}: skip={skips(enf, p)} | {p[:60]!r}")


if __name__ == "__main__":
    main()
