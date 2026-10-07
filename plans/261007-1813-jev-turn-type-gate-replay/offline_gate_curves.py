#!/usr/bin/env python3
"""Offline: per-question curves for the prompt-level Jev questions already cached by the
2026-09-26 exploratory run (three cookbook gates + the ADR-0060 "now" question), split three ways:

  pos  real skill turns (calibrate_jev_gate.is_positive)
  neg  labelled no-skill turns: NO_SKILL searched_then_skipped / skip_nosearch_conversational
  unl  a hash-ordered traffic sample with seed 0 (calibrate_jev_gate defaults to 20260926; the two share 50 of 300 turns)

Every prob is "this turn needs work/skill" (prose_suffices inverted). A threshold t skips a turn
when prob < t. Reports false-NO on pos (Wilson 95 % upper bound), skip share of neg and unl.
No Jev calls."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import calibrate_jev_gate as cal  # noqa: E402

NEG_RULES = {"searched_then_skipped", "skip_nosearch_conversational"}
THRESHOLDS = (0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50)


def is_negative(r):
    return (r["label"] == "NO_SKILL" and r["label_rule"] in NEG_RULES and not r["meta_session"]
            and r["entry_class"] == "interactive")


def probs(ans):
    out = {}
    for k in cal.GATE_QUESTIONS:
        g = ans.get(f"gate::{k}")
        if g:
            out[k] = 1 - g["noul"] if k in cal.INVERTED else g["noul"]
    if "now" in ans:
        out["now(ADR-0060)"] = ans["now"]["noul"]
    return out


def main(variant):
    enf = cal.load_enforcer()
    rows = cal.load_corpus(cal.CORPUS)
    pos, unl = cal.pick(enf, rows, 300, 0)
    neg = [r for r in rows if is_negative(r) and enf._is_english(r["prompt"]) and cal.reaches_gate(enf, r["prompt"])]
    recs = {}
    for rec in cal.read_cache().values():
        if rec["variant"] == variant and rec.get("src", "mpnet") == "mpnet" and "now" in rec["ans"]:
            recs[rec["uuid"]] = probs(rec["ans"])
    sets = {n: [recs[r["uuid"]] for r in s if r["uuid"] in recs] for n, s in (("pos", pos), ("neg", neg), ("unl", unl))}
    print(f"variant={variant}: pos {len(sets['pos'])}/{len(pos)}, neg {len(sets['neg'])}/{len(neg)}, "
          f"unl {len(sets['unl'])}/{len(unl)} have cached prompt-level answers")
    for q in sets["pos"][0] if sets["pos"] else ():
        print(f"\n{q}\n   thr  pos false-NO (UCB95)  neg skipped  unl skipped")
        for t in THRESHOLDS:
            fn = sum(p[q] < t for p in sets["pos"])
            n_pos = len(sets["pos"])
            ns = sum(p[q] < t for p in sets["neg"]) / max(len(sets["neg"]), 1)
            us = sum(p[q] < t for p in sets["unl"]) / max(len(sets["unl"]), 1)
            print(f"  {t:.2f}  {100*fn/n_pos:5.1f}% ({100*cal.wilson_upper(fn, n_pos):5.1f}%)"
                  f"      {100*ns:5.1f}%      {100*us:5.1f}%")
    return sets


if __name__ == "__main__":
    for v in sys.argv[1:] or ["bare", "ctx"]:
        main(v)
