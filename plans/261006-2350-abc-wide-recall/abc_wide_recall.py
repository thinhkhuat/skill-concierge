#!/usr/bin/env python3
"""Paired A/A2/B/C recall experiment on the Jev router's WIDE pass (prereg.md in this directory).

  prep     pin the catalogue, build the four variants' wide questions, draw the 200-turn sample (no Jev call)
  run      5-turn pilot, token projection, then the rest of the 200 (Command Code via jevd ONLY)
  analyze  paired recall, McNemar, Holm, noise floor, MDE, MRR -> _RESEARCH_ARTIFACTS/results.json

Hard constraint (owner's order): no TypeSafe call. Structural exclusion: TYPESAFE_API_KEY and the other provider
keys are removed from this process before the enforcer loads; the only tier ever used is the jevd ladder entry
named "commandcode", sent with jevd's X-Jevd-Provider pin (jevd's router returns that one provider and never
walks its ladder for a pinned request); `_jev_route` is never called. Keys are never read or printed here.
"""
import hashlib
import json
import math
import os
import random
import sys
import threading
import time
import urllib.error
import http.client
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

for _k in ("TYPESAFE_API_KEY", "CMD_API_KEY", "FLYWHEEL_LLM_API_KEY", "ENFORCER_JEV_KEY"):
    os.environ.pop(_k, None)
assert "TYPESAFE_API_KEY" not in os.environ

D = Path(__file__).resolve().parent
ART = D / "_RESEARCH_ARTIFACTS"
REPO = D.parents[1]
LABELS = Path.home() / ".claude/skill-concierge/jev-calibration/real-turn-labels.jsonl"
TRIGGERS = Path.home() / ".claude/skill-concierge/triggers.json"
SEED = 20261006
N_TURNS = 200
PILOT = 5
TOKEN_CAP = 60_000_000
TIMEOUT = 5.5
WORKERS = 3
RETRY_PAUSE = 2.0
VARIANTS = ("A", "A2", "B", "C")
C_CAP = 320
C_EXAMPLES = 3
CALLS = ART / "calls.jsonl"

sys.path.insert(0, str(REPO / "scripts"))
import jev_client  # noqa: E402  (read-only import: its loader execs the enforcer once with a throwaway ledger dir)

ENF = jev_client.load_enforcer()
ENF_SHA = hashlib.sha256(Path(ENF.__file__).read_bytes()).hexdigest()
assert os.environ.get("TYPESAFE_API_KEY") is None


def bare(name: str) -> str:
    """Bare skill name, as the calibrator compares (`split(':')[-1]`), lowercased, arguments dropped."""
    s = (name or "").strip().lstrip("/")
    s = s.split()[0] if s.split() else s
    return s.split(":")[-1].lower()


SEARCH = {"skill-search", "skill-concierge-skill-search"}


def gold(row) -> set:
    return {bare(c) for c in row.get("skill_calls") or [] if bare(c) and bare(c) not in SEARCH}


def offer_independent(row) -> bool:
    """No gold skill was in the hook's offer on that turn, or no offer was recorded (design amendment, prereg)."""
    off = row.get("ledger_offered") or []
    return not (gold(row) & {bare(x[0] if isinstance(x, (list, tuple)) else x) for x in off})


JEV_LIVE_UTC = "2026-09-26T02:47"   # 2026-09-26 09:47 Asia/Saigon, Jev router live (v0.51.0)


def commandcode_tier() -> dict:
    ladder = ENF._jevd_ladder()
    if not ladder:
        sys.exit("jevd ladder unavailable (JEVD_URL unset or jevd silent): refusing to run")
    tiers = [t for t in ladder if t.get("name") == "commandcode"]
    assert len(tiers) == 1, "expected exactly one jevd provider named commandcode"
    assert all(t["name"] == "commandcode" and t["ep"] == "jevd" for t in tiers)
    return tiers[0]


def state_of(row) -> dict:
    return {"request": row["prompt"][:ENF.JEV_MAX_CHARS], "recent_context": row.get("prev_assistant") or "",
            "skills_already_loaded_this_session": list(row.get("session_skills") or [])}


def jload(p):
    return json.loads(Path(p).read_text())


def jdump(p, obj):
    Path(p).write_text(json.dumps(obj, ensure_ascii=False, indent=1))


def labels() -> dict:
    out = {}
    with open(LABELS) as fh:
        for line in fh:
            r = json.loads(line)
            out[r["uuid"]] = r
    return out


# ---------------------------------------------------------------- prep

def frontmatter(path: str) -> dict:
    import yaml
    try:
        text = Path(path).read_text(errors="replace")
    except OSError:
        return {}
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    try:
        fm = yaml.safe_load(text[3:end])
    except yaml.YAMLError:
        return {}
    return fm if isinstance(fm, dict) else {}


def flat(v) -> str:
    if isinstance(v, list):
        v = " ".join(str(x) for x in v)
    return " ".join(str(v or "").split())


def index_paths() -> dict:
    """name -> SKILL.md path from the index's installed base points (the same rows `_jev_catalog` reads)."""
    out, off = {}, None
    while True:
        body = {"limit": 2000, "with_payload": ["name", "path"], "with_vector": False,
                "filter": {"must": [{"key": "kind", "match": {"value": "base"}}],
                           "must_not": [{"key": "tier", "match": {"value": "external"}}]}}
        if off is not None:
            body["offset"] = off
        res = ENF._post_json(f"{ENF.QDRANT_URL}/collections/{ENF.COLLECTION}/points/scroll", body, 5.0)["result"]
        for pt in res.get("points", []):
            pl = pt.get("payload") or {}
            if pl.get("name") and pl["name"] not in out:
                out[pl["name"]] = pl.get("path")
        off = res.get("next_page_offset")
        if off is None:
            return out


def wide_for(catalog, cut):
    prev = ENF.JEV_WIDE_DESC
    try:
        ENF.JEV_WIDE_DESC = cut
        return ENF._jev_wide_questions(catalog)
    finally:
        ENF.JEV_WIDE_DESC = prev


def cmd_prep():
    ART.mkdir(parents=True, exist_ok=True)
    if (ART / "catalog.json").exists():
        sys.exit("catalog already pinned; prep refuses to overwrite")
    catalog = [list(x) for x in ENF._jev_catalog()]
    jdump(ART / "catalog.json", catalog)
    paths = index_paths()
    trig = jload(TRIGGERS)
    b_text, c_text, b_meta, c_meta = {}, {}, {}, {}
    for n, d in catalog:
        base = d or n
        wtu = flat(frontmatter(paths.get(n) or "").get("when_to_use")) if paths.get(n) else ""
        if wtu:
            b_text[n] = (wtu + " " + base)
            b_meta[n] = paths.get(n)
        utts = (((trig.get(n) or {}).get("llm_triggers") or {}).get("triggers") or [])
        en = [u for u in utts if isinstance(u, str) and u.strip() and ENF._is_english(u)][:C_EXAMPLES]
        if en:
            c_text[n] = (base[:ENF.JEV_WIDE_DESC] + " Examples: " + "; ".join(en))[:C_CAP]
            c_meta[n] = len(en)
    cat_a = [(n, d) for n, d in catalog]
    cat_b = [(n, b_text.get(n, d)) for n, d in catalog]       # still cut to 160 by _jev_wide_questions
    cat_c = [(n, c_text.get(n, (d or n)[:ENF.JEV_WIDE_DESC])) for n, d in catalog]   # cut 320 below
    qs = {"A": wide_for(cat_a, ENF.JEV_WIDE_DESC), "B": wide_for(cat_b, ENF.JEV_WIDE_DESC),
          "C": wide_for(cat_c, C_CAP)}
    qs["A2"] = qs["A"]
    jdump(ART / "questions.json", qs)
    # sample
    rows = labels()
    names = {bare(n) for n, _ in catalog}
    elig = sorted((r for r in rows.values() if r.get("lang") == "en" and r.get("skill_call")
                   and gold(r) & names and offer_independent(r)), key=lambda r: r["uuid"])
    sample = random.Random(SEED).sample(elig, N_TURNS)
    jdump(ART / "sample.json", [r["uuid"] for r in sample])
    tok = {v: ENF._jev_tokens(json.dumps(q)) for v, q in qs.items()}
    longest = {v: max(ENF._jev_tokens(json.dumps({k: x})) for k, x in q.items()) for v, q in qs.items()}
    st = [ENF._jev_tokens(json.dumps(state_of(r))) for r in sample]
    meta = {"enforcer_sha256": ENF_SHA, "seed": SEED, "catalog_n": len(catalog),
            "catalog_sha16": hashlib.sha256(json.dumps(catalog).encode()).hexdigest()[:16],
            "chunks": len(qs["A"]), "eligible_n": len(elig),
            "eligible_any_offer_n": sum(1 for r in rows.values() if r.get("lang") == "en" and r.get("skill_call")
                                        and gold(r) & names),
            "sample_post_jev_live_n": sum(1 for r in sample if r["ts_utc"] >= JEV_LIVE_UTC), "sample_n": len(sample),
            "b_changed": len(b_text), "c_changed": len(c_text),
            "c_examples_hist": {k: sum(1 for x in c_meta.values() if x == k) for k in (1, 2, 3)},
            "b_differs_from_a": sum(1 for (n, d), (_, b) in zip(cat_a, cat_b) if (d or n)[:160] != (b or n)[:160]),
            "question_tokens_est": tok, "longest_question_tokens_est": longest,
            "state_tokens_est": {"max": max(st), "mean": round(sum(st) / len(st))},
            "jev_wide_desc": ENF.JEV_WIDE_DESC, "jev_chunk": ENF.JEV_CHUNK, "jev_per_chunk": ENF.JEV_PER_CHUNK,
            "prepared_at": time.strftime("%Y-%m-%d %H:%M:%S %z")}
    jdump(ART / "prep-meta.json", meta)
    jdump(ART / "variant-texts-changed.json", {"B": sorted(b_text), "C": sorted(c_text)})
    print(json.dumps(meta, indent=1))


# ---------------------------------------------------------------- run

_WLOCK = threading.Lock()


def record(rec):
    with _WLOCK, open(CALLS, "a") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def done_ok() -> set:
    if not CALLS.exists():
        return set()
    out = set()
    for line in CALLS.read_text().splitlines():
        r = json.loads(line)
        if r.get("ok"):
            out.add((r["uuid"], r["variant"]))
    return out


def one(tier, row, variant, qs, pos):
    state = state_of(row)
    tok = ENF._jev_tokens(json.dumps({"state": state, "questions": qs}))
    key = ENF._jev_key(tier)   # jevd marker only ("jevd"); never a real key, never sent
    for attempt in (1, 2):
        t0 = time.time()
        try:
            ans, via, model = ENF._jev_call(state, qs, tier, key, TIMEOUT)
            probs = {k: {n: round(float(p), 6) for n, p in v["probabilities"].items()} for k, v in ans.items()}
            record({"uuid": row["uuid"], "variant": variant, "attempt": attempt, "ok": True, "ms": int((time.time() - t0) * 1000),
                    "tok_est": tok, "via": via, "model": model, "pos": pos, "t": round(t0, 3), "probs": probs})
            return True
        except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException) as e:
            code = getattr(e, "code", None)
            record({"uuid": row["uuid"], "variant": variant, "attempt": attempt, "ok": False,
                    "ms": int((time.time() - t0) * 1000), "tok_est": tok, "err": type(e).__name__,
                    "code": code, "pos": pos, "t": round(t0, 3)})
            if attempt == 1:
                time.sleep(RETRY_PAUSE)
    return False


def run_turns(tier, rows, qs_all, uuids, skip):
    tasks = []
    for u in uuids:
        order = list(VARIANTS)
        random.Random(f"{SEED}:{u}").shuffle(order)
        for pos, v in enumerate(order):
            if (u, v) not in skip:
                tasks.append((u, v, pos))
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        list(pool.map(lambda t: one(tier, rows[t[0]], t[1], qs_all[t[1]], t[2]), tasks))
    return time.time() - t0, len(tasks)


def cmd_run():
    tier = commandcode_tier()
    assert tier["name"] == "commandcode" and tier["ep"] == "jevd"
    assert os.environ.get("TYPESAFE_API_KEY") is None
    meta = jload(ART / "prep-meta.json")
    assert meta["enforcer_sha256"] == ENF_SHA, "enforcer changed since prep: the variants were built on another file"
    qs_all = jload(ART / "questions.json")
    uuids = jload(ART / "sample.json")
    rows = labels()
    print(f"tier: name={tier['name']} model={tier['model']} timeout={TIMEOUT}s workers={WORKERS}", flush=True)
    wall_pilot, n_pilot = run_turns(tier, rows, qs_all, uuids[:PILOT], done_ok())
    recs = [json.loads(l) for l in CALLS.read_text().splitlines()]
    pil = [r for r in recs if r["uuid"] in set(uuids[:PILOT])]
    per_var = {}
    for v in VARIANTS:
        xs = [r for r in pil if r["variant"] == v]
        oks = [r for r in xs if r["ok"]]
        per_var[v] = {"calls": len(xs), "ok": len(oks), "tok_est_mean": round(sum(r["tok_est"] for r in xs) / max(len(xs), 1)),
                      "ms_ok_mean": round(sum(r["ms"] for r in oks) / max(len(oks), 1)),
                      "ms_ok_max": max((r["ms"] for r in oks), default=None)}
    tok_pilot = sum(r["tok_est"] for r in pil)
    proj = tok_pilot / PILOT * N_TURNS
    pilot = {"per_variant": per_var, "tok_est_pilot": tok_pilot, "projected_tok_est_200": round(proj),
             "wall_s_pilot": round(wall_pilot, 1), "projected_wall_s_200": round(wall_pilot / PILOT * N_TURNS),
             "cap": TOKEN_CAP, "continue": proj <= TOKEN_CAP, "at": time.strftime("%Y-%m-%d %H:%M:%S %z")}
    jdump(ART / "pilot.json", pilot)
    print(json.dumps(pilot, indent=1), flush=True)
    if proj > TOKEN_CAP:
        print("STOP: projection exceeds the 60M-token cap", flush=True)
        return 2
    wall, n = run_turns(tier, rows, qs_all, uuids[PILOT:], done_ok())
    jdump(ART / "run-meta.json", {"wall_s_rest": round(wall, 1), "tasks_rest": n, "wall_s_pilot": round(wall_pilot, 1),
                                  "finished_at": time.strftime("%Y-%m-%d %H:%M:%S %z")})
    print(f"done: {n} tasks in {wall:.0f}s", flush=True)
    return 0


# ---------------------------------------------------------------- analyze

def mcnemar_p(b, c):
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def mde(n, psi, alpha=0.025, power=0.8):
    """Smallest net paired difference (b-c)/n detectable (normal approx., Connor 1987) given discordance psi."""
    from statistics import NormalDist
    za, zb = NormalDist().inv_cdf(1 - alpha / 2), NormalDist().inv_cdf(power)
    if psi <= 0:
        return None
    lo, hi = 1e-6, psi
    for _ in range(100):
        d = (lo + hi) / 2
        need = (za * math.sqrt(psi) + zb * math.sqrt(max(psi - d * d, 0))) ** 2 / (d * d)
        lo, hi = (d, hi) if need > n else (lo, d)
    return round(hi, 4)


def cmd_analyze():
    catalog = jload(ART / "catalog.json")
    uuids = jload(ART / "sample.json")
    rows = labels()
    recs = [json.loads(l) for l in CALLS.read_text().splitlines()]
    ans = {}
    for r in recs:
        if r["ok"]:
            ans[(r["uuid"], r["variant"])] = r
    fails = {v: {"failed_calls": sum(1 for r in recs if r["variant"] == v and not r["ok"]),
                 "unanswered_turns": sum(1 for u in uuids if (u, v) not in ans),
                 "errors": {}} for v in VARIANTS}
    for r in recs:
        if not r["ok"]:
            e = f"{r['err']}{'/' + str(r['code']) if r.get('code') else ''}"
            fails[r["variant"]]["errors"][e] = fails[r["variant"]]["errors"].get(e, 0) + 1
    paired = [u for u in uuids if all((u, v) in ans for v in VARIANTS)]
    hit, rr = {v: {} for v in VARIANTS}, {v: {} for v in VARIANTS}
    for u in paired:
        g = gold(rows[u])
        for v in VARIANTS:
            probs = ans[(u, v)]["probs"]
            sl = ENF._jev_shortlist({k: {"probabilities": p} for k, p in probs.items()})
            hit[v][u] = bool(g & {bare(n) for n in sl})
            ranked = sorted(((p, n) for ch in probs.values() for n, p in ch.items()), key=lambda x: -x[0])
            rank = next((i + 1 for i, (_, n) in enumerate(ranked) if bare(n) in g), None)
            rr[v][u] = 1 / rank if rank else 0.0
    n = len(paired)

    def cmp(v, w="A"):
        b = sum(1 for u in paired if hit[v][u] and not hit[w][u])   # v gains
        c = sum(1 for u in paired if hit[w][u] and not hit[v][u])   # v loses
        return b, c
    noise_b, noise_c = cmp("A2")
    noise = (noise_b + noise_c) / n if n else None
    res = {}
    for v in VARIANTS:
        res[v] = {"recall": round(sum(hit[v].values()) / n, 4) if n else None,
                  "hits": sum(hit[v].values()), "mrr": round(sum(rr[v].values()) / n, 4) if n else None}
    tests = {}
    for v in ("B", "C"):
        b, c = cmp(v)
        tests[v] = {"gains_b": b, "losses_c": c, "p_raw": mcnemar_p(b, c),
                    "gain_pts": round((b - c) / n, 4), "discordance": round((b + c) / n, 4),
                    "mde_alpha025": mde(n, (b + c) / n), "mrr_delta": round(res[v]["mrr"] - res["A"]["mrr"], 4)}
    order = sorted(("B", "C"), key=lambda v: tests[v]["p_raw"])
    prev = 0.0
    for i, v in enumerate(order):
        adj = min(1.0, max(prev, (2 - i) * tests[v]["p_raw"]))
        tests[v]["p_holm"] = adj
        prev = adj
    for v in ("B", "C"):
        t = tests[v]
        if t["p_holm"] < 0.05 and t["gain_pts"] > 0 and t["gain_pts"] > noise:
            t["decision"] = "proven"
        elif t["p_holm"] < 0.05 and t["gain_pts"] < 0:
            t["decision"] = "harmful"
        else:
            t["decision"] = "not-proven"
    a2 = {"gains_b": noise_b, "losses_c": noise_c, "p_raw": mcnemar_p(noise_b, noise_c),
          "disagreement": round(noise, 4) if n else None}
    oks = [r for r in recs if r["ok"]]
    lat = {}
    for v in VARIANTS:
        ms = sorted(r["ms"] for r in oks if r["variant"] == v)
        lat[v] = {"p50": ms[len(ms) // 2] if ms else None, "p90": ms[int(len(ms) * 0.9)] if ms else None}
    def split(sub):
        m = len(sub)
        d = {v: round(sum(hit[v][u] for u in sub) / m, 4) if m else None for v in VARIANTS}
        for v in ("A2", "B", "C"):
            d[v + "_vs_A_gain_loss"] = [sum(1 for u in sub if hit[v][u] and not hit["A"][u]),
                                       sum(1 for u in sub if hit["A"][u] and not hit[v][u])]
        return {"n": m, "recall": d}
    periods = {"pre_jev_live": split([u for u in paired if rows[u]["ts_utc"] < JEV_LIVE_UTC]),
               "post_jev_live": split([u for u in paired if rows[u]["ts_utc"] >= JEV_LIVE_UTC])}
    named = sum(1 for u in paired if gold(rows[u]) & {bare(x) for x in rows[u].get("skill_named_in_prompt") or []})
    out = {"n_sample": len(uuids), "n_paired": n, "catalog_n": len(catalog), "variants": res, "tests": tests,
           "noise_A_vs_A2": a2, "mde_grid_alpha025": {str(p): mde(n, p) for p in (0.05, 0.1, 0.15, 0.2, 0.3)},
           "mde_grid_alpha05": {str(p): mde(n, p, 0.05) for p in (0.05, 0.1, 0.15, 0.2, 0.3)},
           "periods": periods, "all_offer_independent": all(offer_independent(rows[u]) for u in uuids),
           "failures": fails, "latency_ms_ok": lat,
           "calls_total": len(recs), "calls_ok": len(oks),
           "tok_est_sent_total": sum(r["tok_est"] for r in recs),
           "tok_est_sent_by_variant": {v: sum(r["tok_est"] for r in recs if r["variant"] == v) for v in VARIANTS},
           "returned_models": sorted({str(r.get("model")) for r in oks}),
           "vias": sorted({str(r.get("via")) for r in oks}),
           "paired_gold_named_in_prompt": named,
           "first_call_t": min(r["t"] for r in recs), "last_call_t": max(r["t"] for r in recs)}
    jdump(ART / "results.json", out)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    sys.exit({"prep": cmd_prep, "run": cmd_run, "analyze": cmd_analyze}.get(cmd, lambda: print(__doc__))() or 0)
