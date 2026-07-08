#!/usr/bin/env python3
"""
precision_eval.py — full 495-way recall + cross-skill precision gate (Phase 1 step 4).

The 14-of-495 shadow was un-measurable (an enriched centroid beat 481 bare competitors for
free). This runs the gate AFTER a FULL-495 enrichment, so every skill competes enriched-vs-
enriched — apples to apples. It compares LIVE vs the enriched SHADOW on the same queries:

  RECALL (the lever)         : for each labeled positive, 495-way retrieve; report
                               correct-skill rank-1, top-5, and clears-floor (>=0.20).
  CONFUSION (cannibalization): when the correct skill is NOT rank-1, who stole it.
  TRUE-NEGATIVE (precision)  : each authored near-miss negative for skill X — does X still
                               fire rank-1 above floor? (the precision cost of enrichment).

Queries embedded via the ENGINE path (same space as the index). Run under the engine venv:
  PYTHONPATH=vendor/skill-search SKILL_EMBED_BACKEND=fastembed \
  SKILL_EMBED_MODEL=sentence-transformers/paraphrase-multilingual-mpnet-base-v2 \
  $HOME/.claude/skill-concierge/venv/bin/python3 scripts/precision_eval.py

  --selftest   ranking/metric math self-check (no network)
"""
import os
import sys
import json
import glob
import argparse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS = Path(os.environ.get("SKILL_SCENARIOS_DIR", ROOT / "eval" / "scenarios"))
QDRANT = os.environ.get("SKILL_QDRANT_URL", "http://localhost:6333").rstrip("/")
LIVE = os.environ.get("SKILL_COLLECTION", "claude_skills")
SHADOW = os.environ.get("SKILL_SHADOW_COLLECTION", "claude_skills_shadow")
FLOOR = float(os.environ.get("ENFORCER_GETAWAY_FLOOR", "0.20"))
TOPK = 10


def _post(url, payload, timeout=60.0):
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def search(collection, qvec, k=TOPK):
    """Return [(name, score), ...] top-k SKILLS from a collection (cosine).

    Ranks SKILLS via group_by name + group_size=1 — MAX-pool, mirroring the live
    engine's search_skills (server.py query_points_groups). This is REQUIRED for
    the multivector index: a raw /points/search ranks POINTS, so one skill's base
    + trigger points crowd the list and inflate rank/floor/crowding numbers. On a
    single-vector collection (1 point/skill) grouping collapses to the same top-k,
    so this stays correct for the old shadow too."""
    res = _post(f"{QDRANT}/collections/{collection}/points/query/groups",
                {"query": qvec, "group_by": "name", "limit": k, "group_size": 1,
                 "with_payload": ["name"]})
    groups = res.get("result", {}).get("groups", [])
    out = []
    for g in groups:
        hits = g.get("hits") or []
        if not hits:
            continue
        name = (hits[0].get("payload") or {}).get("name", g.get("id"))
        out.append((name, hits[0]["score"]))
    return out


def rank_of(ranked, name):
    for i, (n, _s) in enumerate(ranked):
        if n == name:
            return i + 1, ranked[i][1]
    return None, None


def eval_collection(coll, qvec_cache, corpus):
    """Returns dict of aggregate recall + per-query confusion + true-neg fires."""
    r1 = r5 = floor_ok = npos = 0
    confusion = {}                 # stealer_name -> count (when correct not rank-1)
    tn_fire = 0; ntn = 0           # negatives where its labeled skill fires rank-1 above floor
    offer_sizes = []               # how many of ALL 495 clear the floor per query (crowding)
    for d in corpus:
        skill = d["skill"]
        for p in d.get("positive", []):
            npos += 1
            full = search(coll, qvec_cache[p], k=495)
            offer_sizes.append(sum(1 for _n, s in full if s >= FLOOR))
            rk, sc = rank_of(full, skill)          # rank + score over the FULL 495, not top-10
            top1 = full[0][0] if full else None
            if rk == 1:
                r1 += 1
            else:
                confusion[top1] = confusion.get(top1, 0) + 1
            if rk and rk <= 5:
                r5 += 1
            # clears-floor = correct skill present at a score >= floor
            if sc is not None and sc >= FLOOR:
                floor_ok += 1
        for n in d.get("negative", []):
            ntn += 1
            rk, sc = rank_of(search(coll, qvec_cache[n], k=495), skill)
            if rk == 1 and sc is not None and sc >= FLOOR:
                tn_fire += 1
    return {
        "n_pos": npos, "rank1": r1, "top5": r5, "clears_floor": floor_ok,
        "rank1_pct": round(100 * r1 / npos, 1) if npos else 0.0,
        "top5_pct": round(100 * r5 / npos, 1) if npos else 0.0,
        "floor_pct": round(100 * floor_ok / npos, 1) if npos else 0.0,
        "confusion": dict(sorted(confusion.items(), key=lambda kv: -kv[1])),
        "n_neg": ntn, "tn_fire": tn_fire,
        "tn_fire_pct": round(100 * tn_fire / ntn, 1) if ntn else 0.0,
        "offer_mean": round(sum(offer_sizes) / len(offer_sizes), 1) if offer_sizes else 0.0,
        "offer_median": sorted(offer_sizes)[len(offer_sizes) // 2] if offer_sizes else 0,
        "offer_p95": sorted(offer_sizes)[int(0.95 * len(offer_sizes)) - 1] if offer_sizes else 0,
    }


def run():
    from skill_search import server
    corpus = [json.loads(Path(f).read_text(encoding="utf-8"))
              for f in sorted(glob.glob(str(CORPUS / "*.json")))]
    # embed every unique query once via the engine path
    prompts = []
    for d in corpus:
        prompts += d.get("positive", []) + d.get("negative", [])
    prompts = list(dict.fromkeys(prompts))
    vecs = server.embed_batch(prompts)
    qvec = dict(zip(prompts, vecs))

    live = eval_collection(LIVE, qvec, corpus)
    shadow = eval_collection(SHADOW, qvec, corpus)

    print(f"\nfull 495-way precision_eval  ({live['n_pos']} positives / {live['n_neg']} "
          f"negatives across {len(corpus)} skills)   floor={FLOOR}")
    print(f"{'metric':<26}{'LIVE':>10}{'SHADOW':>10}{'Δ':>10}")
    print("-" * 56)
    for k, lab in [("rank1_pct", "correct rank-1 %"), ("top5_pct", "correct top-5 %"),
                   ("floor_pct", "clears-floor %"), ("tn_fire_pct", "true-neg false-fire %")]:
        d = round(shadow[k] - live[k], 1)
        print(f"{lab:<26}{live[k]:>10}{shadow[k]:>10}{d:>+10}")
    print("-" * 56)
    print(f"recall counts  rank1 {live['rank1']}->{shadow['rank1']}  "
          f"top5 {live['top5']}->{shadow['top5']}  floor {live['clears_floor']}->{shadow['clears_floor']}  "
          f"(of {live['n_pos']})")
    print(f"true-neg fires {live['tn_fire']}->{shadow['tn_fire']}  (of {live['n_neg']})")
    print(f"\nOFFER-SET CROWDING (skills clearing floor={FLOOR} per query — the real precision gate):")
    print(f"  LIVE    mean {live['offer_mean']:>6}  median {live['offer_median']:>4}  p95 {live['offer_p95']:>4}  (of 495)")
    print(f"  SHADOW  mean {shadow['offer_mean']:>6}  median {shadow['offer_median']:>4}  p95 {shadow['offer_p95']:>4}  (of 495)")
    print(f"  -> if SHADOW crowds far above LIVE, the global floor MUST be re-tuned before the")
    print(f"     enriched index improves OFFERS (rank gains are scale-invariant and stand regardless).")
    print(f"\nSHADOW confusion (who steals a positive when correct isn't rank-1):")
    for n, c in list(shadow["confusion"].items())[:12]:
        print(f"   {c:>3}x  {n}")
    return 0


def main():
    ap = argparse.ArgumentParser(description="full 495-way recall + precision gate")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        # selftest must not require the engine import
        bad = []
        ranked = [("a", 0.9), ("b", 0.5), ("c", 0.1)]
        if rank_of(ranked, "b") != (2, 0.5):
            bad.append("rank_of wrong")
        if rank_of(ranked, "z") != (None, None):
            bad.append("missing-name rank wrong")
        if bad:
            print("precision_eval --selftest FAIL:", bad); return 1
        print("precision_eval --selftest OK: rank_of + missing-name handling")
        return 0
    return run()


if __name__ == "__main__":
    sys.exit(main())
