#!/usr/bin/env python3
"""
multivector_experiment.py — multi-vector (MAX-pooled) retrieval vs the bare single-vector
baseline, A/B'd LIVE (claude_skills) vs SHADOW (claude_skills_shadow).

Hypothesis: index each skill's trigger/scenario *phrases* as SEPARATE points and score a
skill by its BEST-matching point (MAX-pool). This attacks the documented "cosines compressed /
measures topic not intent" ceiling that a single mean-vector-per-skill suffers — the opposite
of enrich_index.py's MEAN centroid.

SHADOW layout (this script builds it, mutating ONLY claude_skills_shadow):
  * base     : ALL live points copied verbatim (vector + name), payload kind="base".
               Keeps the full ~500-skill competitive field so retrieval is a fair N-way.
  * trigger  : one point per trigger phrase (eval/triggers.json, ALL 498 skills), embedded
               via the engine path, payload kind="trigger". Every skill is multi-vector, not
               just the 14 eval skills — otherwise the eval skills get an unfair point-count edge.
  * scenario : one point per scenario positive (eval/scenarios/*.json, the 14 eval skills),
               payload kind="scenario".

NAME RESOLUTION: scenario labels use a single "ck:" prefix (ck:ai-artist) but the live index
stores a DOUBLE prefix (ck:ck:ai-artist, from the plugin install path). canonical() resolves a
scenario label to its real live point name, so the A/B is fair (the LIVE baseline can actually
find the skill, and SHADOW trigger/scenario points share the base point's name for MAX collapse).

LEAKAGE GUARD (integrity): the scenario positives are ALSO the eval queries. Indexing them and
then querying with them is train==test leakage (exact self-match cosine=1.0 -> trivial ~100%).
So the VERDICT metric scores SHADOW over candidates {base, trigger} only — scenario points live
in the index (per the build spec) but are held out of scoring. A second, clearly-labeled
"scenario-leak (LOO)" column scores {base,trigger,scenario} with exact-query self-exclusion, to
show the contaminated optimistic ceiling. The verdict is read off the held-out column.

Run under the engine venv (same embedding space as the index):
  PYTHONPATH=vendor/skill-search SKILL_EMBED_BACKEND=fastembed \
  SKILL_EMBED_MODEL=sentence-transformers/paraphrase-multilingual-mpnet-base-v2 \
  $HOME/.local/share/skill-concierge/venv/bin/python3 scripts/multivector_experiment.py

  (no args)    build SHADOW then run the A/B and print the table
  --build      (re)build the SHADOW multi-vector index only
  --eval       run the A/B only (assumes SHADOW already built)
  --selftest   pin the group-by-name-MAX collapse logic (no network)
"""
import os
import sys
import json
import glob
import uuid
import argparse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS = Path(os.environ.get("SKILL_SCENARIOS_DIR", ROOT / "eval" / "scenarios"))
TRIGGERS = Path(os.environ.get("SKILL_TRIGGERS", ROOT / "eval" / "triggers.json"))
QDRANT = os.environ.get("SKILL_QDRANT_URL", "http://localhost:6333").rstrip("/")
LIVE = os.environ.get("SKILL_COLLECTION", "claude_skills")
SHADOW = os.environ.get("SKILL_SHADOW_COLLECTION", "claude_skills_shadow")
FLOOR = float(os.environ.get("ENFORCER_GETAWAY_FLOOR", "0.20"))
WRITE_BATCH = 256


# --------------------------------------------------------------------------- REST helpers
def _req(url, payload, method):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method=method)
    with urllib.request.urlopen(req, timeout=180.0) as r:
        return json.loads(r.read())


def _post(url, payload):
    return _req(url, payload, "POST")


def _put(url, payload):
    return _req(url, payload, "PUT")


def _get(url):
    with urllib.request.urlopen(url, timeout=60.0) as r:
        return json.loads(r.read())


def _delete(url):
    req = urllib.request.Request(url, method="DELETE")
    with urllib.request.urlopen(req, timeout=60.0) as r:
        return json.loads(r.read())


def collection_count(coll):
    return _get(f"{QDRANT}/collections/{coll}").get("result", {}).get("points_count", 0)


def collection_dim(coll):
    v = _get(f"{QDRANT}/collections/{coll}")["result"]["config"]["params"]["vectors"]
    return v["size"]


def scroll_points(collection, with_vector):
    """All points of `collection`: list of (id, vector|None, payload)."""
    out, nxt = [], None
    while True:
        body = {"limit": 256, "with_payload": True, "with_vector": with_vector}
        if nxt is not None:
            body["offset"] = nxt
        res = _post(f"{QDRANT}/collections/{collection}/points/scroll", body)["result"]
        for pt in res.get("points", []):
            v = pt.get("vector")
            if isinstance(v, dict):
                v = v.get("default")
            out.append((pt["id"], v, pt.get("payload", {})))
        nxt = res.get("next_page_offset")
        if nxt is None:
            break
    return out


# --------------------------------------------------------------------------- name resolution
def canonical(skill, live_names):
    """Resolve a scenario/trigger label to its real live point name. The live index
    double-prefixes ck: skills (ck:ai-artist -> ck:ck:ai-artist)."""
    if skill in live_names:
        return skill
    if skill.startswith("ck:") and ("ck:" + skill) in live_names:
        return "ck:" + skill
    return skill  # unresolved -> caller will see it as never-found in BOTH collections


# --------------------------------------------------------------------------- group-by-name MAX
def collapse_max(point_hits):
    """[(name, score), ...] with repeats -> [(name, max_score), ...] sorted desc.
    THE core of multi-vector retrieval: a skill scores as its single best point."""
    best = {}
    for name, score in point_hits:
        if name not in best or score > best[name]:
            best[name] = score
    return sorted(best.items(), key=lambda kv: -kv[1])


def rank_of(ranked, name):
    for i, (n, _s) in enumerate(ranked):
        if n == name:
            return i + 1, ranked[i][1]
    return None, None


def search_collapsed(collection, qvec, limit, allowed_kinds=None, query_text=None):
    """Query points, optionally filter candidate points by payload kind and drop the exact
    self-match (payload text == query_text), then collapse to skill by MAX score."""
    res = _post(f"{QDRANT}/collections/{collection}/points/search",
                {"vector": qvec, "limit": limit,
                 "with_payload": ["name", "kind", "text"]})
    hits = []
    for p in res.get("result", []):
        pl = p["payload"]
        if allowed_kinds is not None and pl.get("kind") not in allowed_kinds:
            continue
        if query_text is not None and pl.get("text") == query_text:
            continue
        hits.append((pl["name"], p["score"]))
    return collapse_max(hits)


# --------------------------------------------------------------------------- build SHADOW
def build_shadow():
    """Recreate SHADOW as a multi-vector index. MUTATES ONLY claude_skills_shadow."""
    if SHADOW == LIVE:   # real runtime guard (an `assert` is stripped under python -O)
        raise SystemExit("refusing to build over the live collection (SHADOW == LIVE)")
    from skill_search import server

    live_pts = scroll_points(LIVE, with_vector=True)
    live_names = {pl["name"] for _i, _v, pl in live_pts}
    dim = collection_dim(LIVE)
    print(f"[build] live: {len(live_pts)} points, dim={dim}")

    # recreate shadow at the same dim + cosine
    try:
        _delete(f"{QDRANT}/collections/{SHADOW}")
    except Exception:
        pass
    _put(f"{QDRANT}/collections/{SHADOW}",
         {"vectors": {"size": dim, "distance": "Cosine"}})

    # 1) base: copy every live point verbatim
    base = [{"id": pid, "vector": vec, "payload": {"name": pl["name"], "kind": "base"}}
            for pid, vec, pl in live_pts]

    # 2) trigger: one point per trigger phrase (ALL skills -> full multi-vector field)
    triggers = json.loads(TRIGGERS.read_text(encoding="utf-8"))
    trig_flat, trig_meta = [], []          # parallel: text , name
    for name, rec in triggers.items():
        if name not in live_names:         # keep names aligned to the base field
            continue
        for ph in rec.get("triggers", []):
            trig_flat.append(ph)
            trig_meta.append(name)

    # 3) scenario: one point per scenario positive (14 eval skills)
    corpus = [json.loads(Path(f).read_text(encoding="utf-8"))
              for f in sorted(glob.glob(str(CORPUS / "*.json")))]
    scen_flat, scen_meta = [], []          # parallel: text , canonical-name
    for d in corpus:
        cn = canonical(d["skill"], live_names)
        for ph in d.get("positive", []):
            scen_flat.append(ph)
            scen_meta.append(cn)

    print(f"[build] embedding {len(trig_flat)} trigger + {len(scen_flat)} scenario phrases "
          f"via engine path …")
    flat = trig_flat + scen_flat
    vecs = server.embed_batch(flat) if flat else []
    tvecs, svecs = vecs[:len(trig_flat)], vecs[len(trig_flat):]

    extra = []
    for ph, name, v in zip(trig_flat, trig_meta, tvecs):
        extra.append({"id": str(uuid.uuid4()), "vector": v,
                      "payload": {"name": name, "kind": "trigger", "text": ph}})
    for ph, name, v in zip(scen_flat, scen_meta, svecs):
        extra.append({"id": str(uuid.uuid4()), "vector": v,
                      "payload": {"name": name, "kind": "scenario", "text": ph}})

    allpts = base + extra
    for i in range(0, len(allpts), WRITE_BATCH):
        _put(f"{QDRANT}/collections/{SHADOW}/points?wait=true",
             {"points": allpts[i:i + WRITE_BATCH]})

    counts = {"base": len(base), "trigger": len(trig_flat), "scenario": len(scen_flat),
              "total": len(allpts)}
    print(f"[build] SHADOW points: base={counts['base']} trigger={counts['trigger']} "
          f"scenario={counts['scenario']} total={counts['total']}  "
          f"(qdrant reports {collection_count(SHADOW)})")
    return counts


# --------------------------------------------------------------------------- eval
def eval_collection(coll, qvec, corpus, live_names, limit, allowed_kinds, loo):
    """precision_eval.eval_collection, skill-collapsed. `loo`=True drops the exact self-match
    point (payload text == query) so an indexed scenario can't trivially retrieve itself."""
    r1 = r5 = floor_ok = npos = 0
    confusion = {}
    tn_fire = 0
    ntn = 0
    offer_sizes = []
    pos_scores, neg_scores = [], []
    for d in corpus:
        skill = canonical(d["skill"], live_names)
        for p in d.get("positive", []):
            npos += 1
            ranked = search_collapsed(coll, qvec[p], limit, allowed_kinds,
                                      query_text=(p if loo else None))
            offer_sizes.append(sum(1 for _n, s in ranked if s >= FLOOR))
            rk, sc = rank_of(ranked, skill)
            top1 = ranked[0][0] if ranked else None
            if rk == 1:
                r1 += 1
            else:
                confusion[top1] = confusion.get(top1, 0) + 1
            if rk and rk <= 5:
                r5 += 1
            if sc is not None and sc >= FLOOR:
                floor_ok += 1
            pos_scores.append(sc if sc is not None else 0.0)
        for n in d.get("negative", []):
            ntn += 1
            ranked = search_collapsed(coll, qvec[n], limit, allowed_kinds,
                                      query_text=(n if loo else None))
            rk, sc = rank_of(ranked, skill)
            if rk == 1 and sc is not None and sc >= FLOOR:
                tn_fire += 1
            neg_scores.append(sc if sc is not None else 0.0)
    n = len(offer_sizes)
    pm = sum(pos_scores) / len(pos_scores) if pos_scores else 0.0
    nm = sum(neg_scores) / len(neg_scores) if neg_scores else 0.0
    return {
        "n_pos": npos, "rank1": r1, "top5": r5, "clears_floor": floor_ok,
        "rank1_pct": round(100 * r1 / npos, 1) if npos else 0.0,
        "top5_pct": round(100 * r5 / npos, 1) if npos else 0.0,
        "floor_pct": round(100 * floor_ok / npos, 1) if npos else 0.0,
        "confusion": dict(sorted(confusion.items(), key=lambda kv: -kv[1])),
        "n_neg": ntn, "tn_fire": tn_fire,
        "tn_fire_pct": round(100 * tn_fire / ntn, 1) if ntn else 0.0,
        "offer_mean": round(sum(offer_sizes) / n, 1) if n else 0.0,
        "offer_median": sorted(offer_sizes)[n // 2] if n else 0,
        "offer_p95": sorted(offer_sizes)[int(0.95 * n) - 1] if n else 0,
        "pos_mean": round(pm, 4), "neg_mean": round(nm, 4), "separation": round(pm - nm, 4),
    }


def run_eval():
    from skill_search import server
    corpus = [json.loads(Path(f).read_text(encoding="utf-8"))
              for f in sorted(glob.glob(str(CORPUS / "*.json")))]
    live_names = {pl["name"] for _i, _v, pl in scroll_points(LIVE, with_vector=False)}

    prompts = []
    for d in corpus:
        prompts += d.get("positive", []) + d.get("negative", [])
    prompts = list(dict.fromkeys(prompts))
    qvec = dict(zip(prompts, server.embed_batch(prompts)))

    live_n = collection_count(LIVE)
    shadow_n = collection_count(SHADOW)

    # LIVE: single-vector, collapse is a no-op, no kind filter
    live = eval_collection(LIVE, qvec, corpus, live_names, live_n, None, loo=False)
    # SHADOW verdict: held-out — candidates {base,trigger}, scenario points NOT scored
    shadow = eval_collection(SHADOW, qvec, corpus, live_names, shadow_n,
                             {"base", "trigger"}, loo=False)
    # SHADOW scenario-leak (LOO): {base,trigger,scenario} minus the exact query point
    leak = eval_collection(SHADOW, qvec, corpus, live_names, shadow_n,
                           {"base", "trigger", "scenario"}, loo=True)

    print(f"\nmulti-vector MAX A/B  ({live['n_pos']} positives / {live['n_neg']} negatives "
          f"across {len(corpus)} skills)   floor={FLOOR}")
    print(f"LIVE points={live_n}   SHADOW points={shadow_n}")
    print(f"\n{'metric':<26}{'LIVE':>10}{'SHADOW':>10}{'Δ':>9}{'  | leak(LOO)':>13}")
    print("-" * 70)
    for k, lab in [("rank1_pct", "correct rank-1 %"), ("top5_pct", "correct top-5 %"),
                   ("floor_pct", "clears-floor %"), ("tn_fire_pct", "true-neg false-fire %"),
                   ("pos_mean", "pos_mean (best pt)"), ("neg_mean", "neg_mean (best pt)"),
                   ("separation", "separation")]:
        dlt = round(shadow[k] - live[k], 3)
        print(f"{lab:<26}{live[k]:>10}{shadow[k]:>10}{dlt:>+9}{leak[k]:>13}")
    print("-" * 70)
    print(f"recall counts  rank1 {live['rank1']}->{shadow['rank1']}  "
          f"top5 {live['top5']}->{shadow['top5']}  floor {live['clears_floor']}->"
          f"{shadow['clears_floor']}  (of {live['n_pos']})")
    print(f"true-neg fires {live['tn_fire']}->{shadow['tn_fire']}  (of {live['n_neg']})")
    print(f"\nOFFER-SET CROWDING (skills clearing floor={FLOOR} per query):")
    print(f"  LIVE    mean {live['offer_mean']:>6}  median {live['offer_median']:>4}  "
          f"p95 {live['offer_p95']:>4}")
    print(f"  SHADOW  mean {shadow['offer_mean']:>6}  median {shadow['offer_median']:>4}  "
          f"p95 {shadow['offer_p95']:>4}")
    print(f"\nSHADOW (held-out) confusion — who steals a positive when correct isn't rank-1:")
    for nm, c in list(shadow["confusion"].items())[:12]:
        print(f"   {c:>3}x  {nm}")
    return {"live": live, "shadow": shadow, "leak": leak,
            "live_n": live_n, "shadow_n": shadow_n}


# --------------------------------------------------------------------------- selftest
def run_sweep():
    """Floor sweep on the BUILT shadow multi-vector index (held-out {base,trigger}). Embeds the
    corpus once, collapses each query to skill-MAX, then thresholds at several floors — so we can
    pick the live getaway floor that restores ~LIVE offer-crowding while keeping positive recall.
    Read-only to live. Prints pos clears-floor %, neg false-fire %, and offer-crowding per floor."""
    from skill_search import server
    corpus = [json.loads(Path(f).read_text(encoding="utf-8"))
              for f in sorted(glob.glob(str(CORPUS / "*.json")))]
    live_names = {pl["name"] for _i, _v, pl in scroll_points(LIVE, with_vector=False)}
    prompts = []
    for d in corpus:
        prompts += d.get("positive", []) + d.get("negative", [])
    prompts = list(dict.fromkeys(prompts))
    qvec = dict(zip(prompts, server.embed_batch(prompts)))
    shadow_n = collection_count(SHADOW)
    kinds = {"base", "trigger"}

    pos = []   # (own_score, [all skill-max scores])  — crowding = how many skills clear a floor
    neg = []   # (own_is_rank1, own_score)            — false-fire = rank1==own AND own>=floor
    for d in corpus:
        skill = canonical(d["skill"], live_names)
        for p in d.get("positive", []):
            ranked = search_collapsed(SHADOW, qvec[p], shadow_n, kinds)
            rk, sc = rank_of(ranked, skill)
            pos.append((sc if sc is not None else 0.0, [s for _n, s in ranked]))
        for nq in d.get("negative", []):
            ranked = search_collapsed(SHADOW, qvec[nq], shadow_n, kinds)
            rk, sc = rank_of(ranked, skill)
            neg.append((rk == 1, sc if sc is not None else 0.0))

    def median(xs):
        xs = sorted(xs); return xs[len(xs) // 2] if xs else 0

    floors = [0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]
    print(f"\nFLOOR SWEEP — SHADOW held-out {{base,trigger}}  ({len(pos)} pos / {len(neg)} neg)")
    print(f"LIVE baseline crowding @0.20 was mean 87.6 / median 34 (target to restore)\n")
    print(f"{'floor':>6}{'pos_clear%':>12}{'neg_falsefire%':>16}{'crowd_mean':>12}{'crowd_med':>11}")
    print("-" * 57)
    for fl in floors:
        pc = 100 * sum(1 for s, _ in pos if s >= fl) / len(pos) if pos else 0.0
        nf = 100 * sum(1 for r1, s in neg if r1 and s >= fl) / len(neg) if neg else 0.0
        crowds = [sum(1 for s in scores if s >= fl) for _own, scores in pos]
        cm = sum(crowds) / len(crowds) if crowds else 0.0
        print(f"{fl:>6.2f}{pc:>12.1f}{nf:>16.1f}{cm:>12.1f}{median(crowds):>11}")
    print("-" * 57)
    print("pick: highest pos_clear% with crowd_median near LIVE's 34 and neg_falsefire low.")
    return 0


def _selftest():
    bad = []
    got = collapse_max([("a", 0.9), ("a", 0.3), ("b", 0.5)])
    if got != [("a", 0.9), ("b", 0.5)]:
        bad.append(f"collapse_max wrong: {got}")
    # collapse keeps the MAX and re-sorts (b's single 0.5 must sit below a's 0.9)
    got2 = collapse_max([("b", 0.5), ("a", 0.3), ("a", 0.95)])
    if got2 != [("a", 0.95), ("b", 0.5)]:
        bad.append(f"collapse_max sort/max wrong: {got2}")
    if rank_of([("a", 0.9), ("b", 0.5)], "b") != (2, 0.5):
        bad.append("rank_of wrong")
    if rank_of([("a", 0.9)], "z") != (None, None):
        bad.append("missing-name rank wrong")
    # canonical: single-prefix scenario label resolves to the double-prefix live name
    ln = {"ck:ck:ai-artist", "tdd"}
    if canonical("ck:ai-artist", ln) != "ck:ck:ai-artist":
        bad.append("canonical ck: double-prefix resolve wrong")
    if canonical("tdd", ln) != "tdd":
        bad.append("canonical identity wrong")
    if bad:
        print("multivector_experiment --selftest FAIL:")
        for b in bad:
            print("  " + b)
        return 1
    print("multivector_experiment --selftest OK: collapse_max(MAX+sort) + rank_of + canonical")
    return 0


def main():
    ap = argparse.ArgumentParser(description="multi-vector MAX-pool retrieval A/B")
    ap.add_argument("--build", action="store_true", help="(re)build the SHADOW multi-vector index")
    ap.add_argument("--eval", action="store_true", help="run the A/B (assumes SHADOW built)")
    ap.add_argument("--sweep", action="store_true", help="floor sweep on the built SHADOW index")
    ap.add_argument("--selftest", action="store_true", help="collapse-logic self-check, no network")
    args = ap.parse_args()
    if args.selftest:
        return _selftest()
    if args.sweep:
        return run_sweep()
    do_build = args.build or not args.eval    # build unless eval-only
    do_eval = args.eval or not args.build     # eval unless build-only
    if do_build:
        build_shadow()
    if do_eval:
        run_eval()
    return 0


if __name__ == "__main__":
    sys.exit(main())
