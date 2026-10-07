#!/usr/bin/env python3
"""Offline: would a source-reputation tier (pstack, Matt Pocock, ak-*) put the skill the agent really
used higher in the live offer? Uses cached Jev wide-pipeline answers (catalogue f65af73783c60a68,
jev-1.13.0, ctx) for the real skill turns. Live offer = top 5 of Jev's 10-row shortlist by `which`
probability. Policies re-order only inside that shortlist (a tier rule over the whole catalogue would pull
in skills Jev never shortlisted, so this is the most favourable case for the idea). No Jev calls."""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "scripts"))
import calibrate_jev_gate as cal  # noqa: E402

CAT = "f65af73783c60a68"
SKILLS = Path.home() / ".claude" / "skills"


def family(name):
    base = name.split(":")[-1]
    if name.startswith("pstack:"):
        return "pstack"
    if name.startswith(("ak:", "ak-")) or base.startswith("ak-"):
        return "ak"
    link = SKILLS / base
    if link.is_symlink() and "-mattpocock-" in os.path.realpath(link):
        return "matt"
    return "other"


TOP = {"pstack", "ak", "matt"}


def order(rec, policy, boost=0.10):
    probs = rec["ans"]["which"]["probabilities"]
    names = list(probs)
    if policy == "jev":
        key = lambda n: -probs[n]
    elif policy == "strict":          # reputable tier always ahead, Jev order inside each tier
        key = lambda n: (family(n) not in TOP, -probs[n])
    else:                             # soft: reputable rows get +boost probability
        key = lambda n: -(probs[n] + (boost if family(n) in TOP else 0))
    return sorted(names, key=key)


def main():
    enf = cal.load_enforcer()
    pos, _ = cal.pick(enf, cal.load_corpus(cal.CORPUS), 300, 0)
    recs = {r["uuid"]: r for r in cal.read_cache().values()
            if r.get("src") == "wide" and r.get("cat") == CAT and r["variant"] == "ctx" and "which" in r["ans"]}
    rows = [(r, recs[r["uuid"]]) for r in pos if r["uuid"] in recs]
    fam_gold = {}
    for r, _ in rows:
        for g in cal.gold(r):
            fam_gold[family(g)] = fam_gold.get(family(g), 0) + 1
    print(f"{len(rows)} real skill turns with cached wide answers; families of the used skill: {fam_gold}")
    for pol in ("jev", "soft", "strict"):
        top1 = top5 = lost = gained = 0
        for r, rec in rows:
            g = cal.gold(r)
            base5 = {n.split(":")[-1] for n in order(rec, "jev")[:5]}
            o = order(rec, pol)
            got5 = {n.split(":")[-1] for n in o[:5]}
            top1 += o[0].split(":")[-1] in g
            top5 += bool(g & got5)
            lost += bool(g & base5) and not (g & got5)
            gained += bool(g & got5) and not (g & base5)
        n = len(rows)
        print(f"{pol:6s}: used skill ranked 1st {top1}/{n} ({100*top1/n:.1f}%), in the 5-row offer {top5}/{n} "
              f"({100*top5/n:.1f}%); vs jev: gained {gained}, lost {lost}")


if __name__ == "__main__":
    main()
