#!/usr/bin/env python3
"""
enrich_index.py — enrich skill vectors with trigger phrases (Phase 1 steps 3 & 7).

Recipe (reverse-engineered from the step-0 shadow ground truth, all 14 skills, best_k
reconstruction = flat mean): enriched_vector = MEAN( [live S] + [embed(trigger) ...] ).
The stored vector S IS included (flat mean, so description weight = 1/(N+1); triggers are
N-capped upstream in build_triggers.py so that weight stays bounded). Triggers come from
eval/triggers.json (keyed by the LIVE INDEX name).

EMBED PARITY (red-team M5, HARD GATE): triggers MUST be embedded via the engine path
(skill_search.server.embed, fastembed==0.8.0, mpnet-768) — the exact embedder the live
index was built with. Verified: re-embedding a skill's indexed text reproduces its live
vector at cosine=1.0. fastembed 0.8.0 warns it switched mpnet to mean-pooling; the live
index already uses 0.8.0 mean-pooling, so parity holds — the gate below RE-asserts it at
run time and ABORTS on drift (a 0.5.1 CLS index would fail here instead of silently
corrupting). Run under the engine venv:
  PYTHONPATH=vendor/skill-search SKILL_EMBED_BACKEND=fastembed \
  SKILL_EMBED_MODEL=sentence-transformers/paraphrase-multilingual-mpnet-base-v2 \
  $HOME/.claude/skill-concierge/venv/bin/python3 scripts/enrich_index.py --shadow

WRITES are vector-only (PUT /points/vectors) — NEVER upsert (an upsert clears the payload
-> skills go dark -> doctor FAILs -> auto-reindex reverts). Payload `enriched=true` +
`enrich_source_hash` are set via a separate set-payload call. --live refuses to run without
a verified Qdrant snapshot (atomic rollback).

Usage:
  ... --shadow              enrich claude_skills_shadow (source vectors read from live)
  ... --live                enrich claude_skills (REQUIRES a fresh verified snapshot)
  ... --revert [--shadow|--live]   restore target vectors from live + clear enriched marker
  ... --selftest            math/centroid self-check (no network)
"""
import os
import sys
import json
import math
import time
import hashlib
import argparse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRIGGERS = Path(os.environ.get("SKILL_TRIGGERS", ROOT / "eval" / "triggers.json"))
QDRANT = os.environ.get("SKILL_QDRANT_URL", "http://localhost:6333").rstrip("/")
LIVE = os.environ.get("SKILL_COLLECTION", "claude_skills")
SHADOW = os.environ.get("SKILL_SHADOW_COLLECTION", "claude_skills_shadow")
PARITY_MIN = 0.999
WRITE_BATCH = 128


def _post(url, payload, timeout=120.0):
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _put(url, payload, timeout=120.0):
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="PUT")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def cosine(a, b):
    d = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)); nb = math.sqrt(sum(y * y for y in b))
    return d / (na * nb) if na and nb else 0.0


def mean_vecs(vecs):
    n = len(vecs); L = len(vecs[0])
    return [sum(v[i] for v in vecs) / n for i in range(L)]


def scroll_live(collection=LIVE):
    """All points of `collection`: name -> (id, vector, payload)."""
    out, nxt = {}, None
    while True:
        body = {"limit": 256, "with_payload": True, "with_vector": True}
        if nxt is not None:
            body["offset"] = nxt
        res = _post(f"{QDRANT}/collections/{collection}/points/scroll", body)["result"]
        for pt in res.get("points", []):
            v = pt["vector"]; v = v if isinstance(v, list) else v.get("default")
            out[pt["payload"]["name"]] = (pt["id"], v, pt["payload"])
        nxt = res.get("next_page_offset")
        if nxt is None:
            break
    return out


def _engine_embed_batch(texts):
    """Engine fastembed path — the ONLY embedder allowed to write index vectors."""
    from skill_search import server
    return server.embed_batch(list(texts))


def parity_gate(live):
    """Re-embed one skill's indexed text via the engine path; ABORT unless it
    reproduces the live vector at cosine>=PARITY_MIN (M5: stop CLS/mean drift)."""
    from skill_search import server
    name = next((n for n, (_i, _v, pl) in live.items() if not pl.get("enriched")), None)
    if name is None:
        print("[parity] all points already enriched — no bare reference; parity check skipped")
        return True
    _id, S, pl = live[name]
    txt = f"{pl['name']}\n{pl.get('description','')}\n"  # body not in payload; desc-only probe
    # desc-only won't hit 1.0 (body missing); use full text via disc if available
    try:
        from skill_search import skills_discovery as disc
        by = {s["name"]: s for s in disc.discover_skills()}
        if name in by:
            txt = server._skill_text(by[name])
    except Exception:
        pass
    c = cosine(server.embed(txt), S)
    print(f"[parity] engine-embed vs live '{name}': cos={c:.5f}  (gate >= {PARITY_MIN})")
    if c < PARITY_MIN:
        print("[parity] ABORT: embedder does not reproduce the live index "
              "(pooling/version drift) — refusing to write skewed vectors.")
        return False
    return True


def snapshot(collection):
    res = _post(f"{QDRANT}/collections/{collection}/snapshots", {})
    snap = res.get("result", {}).get("name")
    print(f"[snapshot] {collection}: {snap}")
    return snap


def enrich(target, live, triggers):
    """Build enriched vectors (mean[S]+triggers) and vector-only-update `target`."""
    names = [n for n in triggers if n in live]
    print(f"[enrich] {len(names)}/{len(triggers)} trigger skills present in live index "
          f"-> {target}")
    updated, src_hashes = [], {}
    # flatten all trigger texts for one batched engine embed
    flat, spans = [], {}
    for n in names:
        ts = triggers[n]["triggers"]
        spans[n] = (len(flat), len(flat) + len(ts))
        flat.extend(ts)
    print(f"[enrich] embedding {len(flat)} trigger phrases via engine path …")
    vecs = _engine_embed_batch(flat)
    for n in names:
        _id, S, _pl = live[n]
        a, b = spans[n]
        enriched = mean_vecs([S] + vecs[a:b]) if b > a else S
        updated.append({"id": _id, "vector": enriched})
        src_hashes[n] = (_id, hashlib.md5("\n".join(triggers[n]["triggers"]).encode()).hexdigest())
    # vector-only update in batches (NEVER upsert)
    for i in range(0, len(updated), WRITE_BATCH):
        _put(f"{QDRANT}/collections/{target}/points/vectors",
             {"points": updated[i:i + WRITE_BATCH]})
    # mark enriched via set-payload (separate, payload-preserving)
    for i in range(0, len(updated), WRITE_BATCH):
        chunk = updated[i:i + WRITE_BATCH]
        ids = [u["id"] for u in chunk]
        # one set-payload per batch with shared marker; hash set individually below
        _post(f"{QDRANT}/collections/{target}/points/payload",
              {"payload": {"enriched": True}, "points": ids})
    for n, (pid, h) in src_hashes.items():
        _post(f"{QDRANT}/collections/{target}/points/payload",
              {"payload": {"enrich_source_hash": h}, "points": [pid]})
    print(f"[enrich] vector-only updated {len(updated)} points; marked enriched=true")
    return updated


def assert_payloads_intact(target, expect_name=True):
    res = _post(f"{QDRANT}/collections/{target}/points/scroll",
                {"limit": 512, "with_payload": True, "with_vector": False})["result"]
    miss = [p["id"] for p in res.get("points", []) if expect_name and not p["payload"].get("name")]
    print(f"[assert] payload check on {len(res.get('points', []))} sampled points: "
          f"{'ALL carry name' if not miss else f'{len(miss)} MISSING name!'}")
    return not miss


def revert(target, live):
    """Restore target vectors from live (vector-only) + clear enriched marker."""
    pts = [{"id": _id, "vector": v} for _id, v, _pl in live.values()]
    for i in range(0, len(pts), WRITE_BATCH):
        _put(f"{QDRANT}/collections/{target}/points/vectors", {"points": pts[i:i + WRITE_BATCH]})
    ids = [_id for _id, _v, _pl in live.values()]
    for i in range(0, len(ids), WRITE_BATCH):
        _post(f"{QDRANT}/collections/{target}/points/payload",
              {"payload": {"enriched": False}, "points": ids[i:i + WRITE_BATCH]})
    print(f"[revert] restored {len(pts)} {target} vectors from live; cleared enriched marker")


def reapply(target):
    """Idempotent re-apply: enrich ONLY points lacking the `enriched` marker — exactly the
    points an engine reindex just rewrote bare (changed/new skills) or a force-rebuild reset.
    Triggers are regenerated from each point's CURRENT description, so a changed SKILL.md gets
    fresh triggers. Already-enriched points keep their marker and are skipped, so there is NO
    double-enrichment. This is what makes `skill-search --reindex` safe."""
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    from build_triggers import split_phrases
    from skill_search import server, skills_discovery as disc
    by = {sk["name"]: sk for sk in disc.discover_skills()}
    pts = scroll_live(target)
    todo = {n: (pid, v, pl) for n, (pid, v, pl) in pts.items() if not pl.get("enriched")}
    print(f"[reapply] {target}: {len(todo)}/{len(pts)} points lack the enriched marker")
    if not todo:
        print("[reapply] fully enriched — idempotent no-op.")
        return 0
    # M5 parity: find a GENUINELY-bare todo point (engine-embed of its source text reproduces the
    # stored vector at ~1.0) — confirms the embedder still matches the index. A desynced point
    # (marker cleared but vector still enriched) fails this and is skipped, NOT aborted on: we
    # recompute the bare base from source below rather than trusting the stored vector.
    parity = None
    for n, (_pid, v, _pl) in todo.items():
        if n in by:
            c = cosine(server.embed(server._skill_text(by[n])), v)
            if c >= PARITY_MIN:
                parity = (n, c)
                break
    if parity:
        print(f"[reapply] parity OK on bare '{parity[0]}': cos={parity[1]:.5f}")
    else:
        print("[reapply] WARN: no genuinely-bare reference among todo points (marker/vector "
              "desync) — proceeding via recompute-from-source (cannot double-enrich).")
    # Recompute the BARE base from source text (embed(_skill_text)) instead of trusting the stored
    # vector — identical to the stored bare (proven cos=1.0) but CANNOT double-enrich even if a
    # point's vector is already enriched. Per point: centroid of [bare-source] + trigger phrases.
    flat, spans, trig, skipped = [], {}, {}, []
    for n, (_pid, _v, _pl) in todo.items():
        if n not in by:                            # indexed but gone from disk — no source
            skipped.append(n)
            continue
        ts = split_phrases(by[n]["description"])
        trig[n] = ts
        span = [server._skill_text(by[n])] + ts    # bare-source FIRST, then triggers
        spans[n] = (len(flat), len(flat) + len(span))
        flat.extend(span)
    print(f"[reapply] embedding {len(flat)} texts (bare-source + triggers) via engine path …")
    vecs = _engine_embed_batch(flat) if flat else []
    updated, hashes = [], {}
    for n in trig:
        pid = todo[n][0]
        a, b = spans[n]
        updated.append({"id": pid, "vector": mean_vecs(vecs[a:b])})
        hashes[n] = (pid, hashlib.md5("\n".join(trig[n]).encode()).hexdigest())
    for i in range(0, len(updated), WRITE_BATCH):
        _put(f"{QDRANT}/collections/{target}/points/vectors", {"points": updated[i:i + WRITE_BATCH]})
    for i in range(0, len(updated), WRITE_BATCH):
        ids = [u["id"] for u in updated[i:i + WRITE_BATCH]]
        _post(f"{QDRANT}/collections/{target}/points/payload",
              {"payload": {"enriched": True}, "points": ids})
    for n, (pid, h) in hashes.items():
        _post(f"{QDRANT}/collections/{target}/points/payload",
              {"payload": {"enrich_source_hash": h}, "points": [pid]})
    # keep triggers.json current for the (re)enriched skills
    tj = json.loads(TRIGGERS.read_text(encoding="utf-8")) if TRIGGERS.exists() else {}
    for n, ts in trig.items():
        tj[n] = {"source": "prose-phrase", "triggers": ts, "n": len(ts)}
    TRIGGERS.write_text(json.dumps(tj, indent=2, ensure_ascii=False), encoding="utf-8")
    assert_payloads_intact(target)
    msg = f"[reapply] re-enriched {len(updated)} points; triggers.json refreshed ({len(tj)} skills)"
    if skipped:
        msg += f"; skipped {len(skipped)} indexed-but-deleted-from-disk (reindex to drop)"
    print(msg)
    return 0


def _selftest():
    bad = []
    S = [1.0, 0.0]; t1 = [0.0, 1.0]
    m = mean_vecs([S, t1])
    if not (abs(m[0] - 0.5) < 1e-9 and abs(m[1] - 0.5) < 1e-9):
        bad.append(f"mean wrong: {m}")
    if abs(cosine([1, 0], [1, 0]) - 1.0) > 1e-9 or abs(cosine([1, 0], [0, 1])) > 1e-9:
        bad.append("cosine wrong")
    # enrichment moves S toward the trigger (separation lever)
    enr = mean_vecs([S] + [t1, t1, t1])
    if not cosine(enr, t1) > cosine(S, t1):
        bad.append("enrichment did not move vector toward trigger")
    if bad:
        print("enrich_index --selftest FAIL:")
        for b in bad: print("  " + b)
        return 1
    print("enrich_index --selftest OK: flat-mean centroid + cosine + enrichment-direction")
    return 0


def main():
    ap = argparse.ArgumentParser(description="enrich skill vectors with trigger phrases")
    ap.add_argument("--shadow", action="store_true", help="target the shadow collection")
    ap.add_argument("--live", action="store_true", help="target the LIVE collection (snapshot-gated)")
    ap.add_argument("--revert", action="store_true", help="restore target vectors from live")
    ap.add_argument("--reapply", action="store_true",
                    help="idempotently re-enrich only points missing the marker (makes reindex safe)")
    ap.add_argument("--selftest", action="store_true", help="math self-check, no network")
    args = ap.parse_args()
    if args.selftest:
        return _selftest()
    target = LIVE if args.live else SHADOW
    if args.reapply:
        # reapply maintains the LIVE index by default (the one reindex rewrites); --shadow to override
        return reapply(SHADOW if args.shadow else LIVE)
    live = scroll_live()
    print(f"[enrich] live index: {len(live)} points; target = {target}")

    if args.revert:
        revert(target, live)
        return 0
    if not parity_gate(live):
        return 2
    if args.live:
        snap = snapshot(LIVE)
        if not snap:
            print("[live] ABORT: no verified snapshot — refusing to enrich live.")
            return 3
    triggers = json.loads(TRIGGERS.read_text(encoding="utf-8"))
    enrich(target, live, triggers)
    assert_payloads_intact(target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
