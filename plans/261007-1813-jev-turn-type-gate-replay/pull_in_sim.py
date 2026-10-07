#!/usr/bin/env python3
"""Offline: if a badged skill Jev shortlisted (rows 6-10) is APPENDED to the 5-row menu when its own
`fits` clears a bar, how often does that add the skill the agent really used, and how many extra rows
does it cost? Jev's top 5 are never displaced. Badged = pstack / ak-* / Matt Pocock (the families the
owner named), the same stand-in as reputation_tier_sim.py. Cached answers only; no Jev calls."""
from reputation_tier_sim import cal, CAT, family, TOP


def main():
    enf = cal.load_enforcer()
    pos, _ = cal.pick(enf, cal.load_corpus(cal.CORPUS), 300, 0)
    recs = {r["uuid"]: r for r in cal.read_cache().values()
            if r.get("src") == "wide" and r.get("cat") == CAT and r["variant"] == "ctx" and "which" in r["ans"]}
    rows = [(r, recs[r["uuid"]]) for r in pos if r["uuid"] in recs]
    sample = rows[0][1]["ans"]
    print("answer keys sample:", sorted(sample)[:6], "| shortlist field:", [k for k in rows[0][1] if "short" in k])
    n = len(rows)
    in5 = in10 = 0
    for r, rec in rows:
        g = cal.gold(r)
        order = sorted(rec["ans"]["which"]["probabilities"], key=lambda x: -rec["ans"]["which"]["probabilities"][x])
        b = lambda xs: {x.split(":")[-1] for x in xs}
        in5 += bool(g & b(order[:5])); in10 += bool(g & b(order[:10]))
    print(f"{n} turns: used skill in top 5 {in5}, in shortlist top 10 {in10} (rows 6-10 hold {in10 - in5})")
    for bar in (0.3, 0.5, 0.7, 0.9):
        gained = extra = wrong_pulls = 0
        for r, rec in rows:
            g = cal.gold(r)
            ans = rec["ans"]
            probs = ans["which"]["probabilities"]
            order = sorted(probs, key=lambda x: -probs[x])
            short = list(probs)  # fits::i follows the shortlist order the Choice was asked in
            fits = {short[i]: float(ans[f"fits::{i}"]["noul"]) for i in range(len(short)) if f"fits::{i}" in ans}
            base = order[:5]
            pulls = [x for x in order[5:10] if family(x) in TOP and fits.get(x, 0) >= bar][:2]
            extra += len(pulls)
            base_hit = bool(g & {x.split(":")[-1] for x in base})
            pull_hit = bool(g & {x.split(":")[-1] for x in pulls})
            gained += (pull_hit and not base_hit)
            wrong_pulls += sum(1 for x in pulls if x.split(":")[-1] not in g)
        print(f"bar {bar}: gained {gained}/{n}, extra rows {extra} ({extra/n:.2f}/turn), pulls that were not the used skill {wrong_pulls}")


if __name__ == "__main__":
    main()
