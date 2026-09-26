#!/usr/bin/env python3
"""
skill-concierge — Jev gate/router calibrator on REAL traffic (no hand-labelled prompts).

Labels come from what agents actually did: a positive is a turn where the agent loaded and
used a skill in that same turn, and its gold skill is the one it used. Unlabelled traffic
supplies the skip share. Every threshold and every design choice is decided by measured
outcomes, never by a hand-written tuning set.

Scope: English prompts (owner order 2026-09-26: English end to end first; Jev's primary
training language is English per docs.typesafe.ai/concepts/state.md).

  replay  one Jev call per prompt and variant: exactly the live rerank request (a Choice over
          the shortlist + one `fits` Noul per candidate). Raw answers are cached, so every
          signal below is derived offline from the same calls. (The 2026-09-26 exploratory
          run also asked a `relevant` Noul per candidate, the three cookbook gate Nouls and
          the retired ADR-0060 question in the same request; those records still read.)
  curve   per signal: false-NO on real positives vs skip share of traffic, per threshold
  fit     per signal: the highest threshold whose 95 % Wilson upper bound on false NO stays
          at or below --target, re-checked on a later time holdout
  rank    does Jev put the skill the agent actually used nearer the top than retrieval does?
  wide    recall of the used skill: retrieval's shortlist vs Jev over the whole catalogue
  policy  the enforcer's own `_jev_decide` over the cached wide-pipeline answers

Variants: `bare` (the request alone) and `ctx` (plus the previous assistant message and the
skills already loaded this session — context the live hook can read from the transcript).

The corpus (`scripts/extract_turn_labels.py`) holds verbatim prompts and lives under
~/.claude/skill-concierge/jev-calibration/, never in this public repo. The enforcer module is
loaded, not copied: retrieval, keep-off, blocklist, the lanes before the gate, the HTTP helper,
the catalogue, the question builders and `_jev_decide` are the live ones.
"""
import argparse
import hashlib
import importlib.util
import json
import math
import os
import random
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENFORCER = ROOT / "hooks" / "scripts" / "enforcer.py"
HOME = Path(os.environ.get("SKILL_CONCIERGE_HOME", Path.home() / ".claude" / "skill-concierge"))
CAL_DIR = HOME / "jev-calibration"
CORPUS = CAL_DIR / "real-turn-labels.jsonl"
CACHE = CAL_DIR / "suite-scores.jsonl"
SHORTLIST = 10        # retrieved candidates handed to Jev
DESC_CHARS = 400
CTX_CHARS = 1500      # tail of the previous assistant message
MIN_POSITIVES = 125   # below this no threshold can certify a 3 % false-NO bound
VARIANTS = ("bare", "ctx")

# The exploratory run's extra questions, kept so its cached records read (the live Choice and
# `fits` texts are the enforcer's). Cookbook texts, verbatim, fetched 2026-09-26:
# docs.typesafe.ai/cookbooks/skill_suggestion.md
GATE_QUESTIONS = {
    "acts_on_user_system": ("Is the assistant being asked to act on the user's files, accounts, devices, "
                            "or online services, rather than only to explain or advise?"),
    "would_follow_documented_procedure": ("Would a careful expert answering this consult a specific documented "
                                          "procedure or set of commands, rather than answering from general "
                                          "understanding?"),
    "prose_suffices": ("Could a knowledgeable generalist fully satisfy this request in prose, with no tools, "
                       "no documentation, and no access to the user's files or accounts?"),
}
INVERTED = {"prose_suffices"}


def relevant_text(name, desc):   # classifying_rag_passages.md `is_relevant`, candidate named inline
    return f"Does the skill '{name}' address the subject of the user's request? It is described as: {desc}"


ENF = None   # the loaded enforcer module; its question builders and decision policy are used as-is


def load_enforcer():
    """Import the live enforcer with its ledger in a throwaway dir. Offline replay waits for
    retrieval instead of applying the per-turn latency caps (0.5 s / 0.25 s)."""
    global ENF
    if ENF is not None:
        return ENF
    os.environ.setdefault("SKILL_CONCIERGE_LOG", tempfile.mkdtemp(prefix="jevcal-"))
    os.environ.setdefault("ENFORCER_EMBED_TIMEOUT", "15")
    os.environ.setdefault("ENFORCER_QDRANT_TIMEOUT", "15")
    spec = importlib.util.spec_from_file_location("enforcer_cal", ENFORCER)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    ENF = mod
    return mod


def reaches_gate(enf, prompt):
    """True when the live hook would get as far as the Jev gate: the lanes in main() that
    return earlier, in order (hooks/scripts/enforcer.py main)."""
    p = prompt.strip()
    if not p or p.startswith("/") or enf._word_count(p) <= enf.MAX_SHORT_WORDS:
        return False
    if enf._HARNESS_MSG_RE.match(p) or enf._REFUSAL_RE.search(p):
        return False
    if enf.CONSULT_ROUTE and enf._CONSULT_RE.search(p) and not enf._CONSULT_NEG_RE.search(p):
        return False
    if enf.SELFREF_SKIP and enf._is_selfref(p):
        return False
    return not enf._route_hits(p, enf.KEEPOFF)


def shelf(enf, prompt):
    """The installed shortlist the live hook would build: embed -> retrieve -> keep-off -> blocklist."""
    cands = enf._retrieve(enf._embed(prompt))
    cands, _ = enf._drop_keepoff(cands, enf.KEEPOFF)
    cands, _ = enf._drop_blocklisted(cands)
    return [(n, (d or n)[:DESC_CHARS]) for (n, d, _s) in cands[:SHORTLIST]]


def build_state(row, variant):
    state = {"request": row["prompt"][:4000], "recent_context": ""}
    if variant == "ctx":
        state["recent_context"] = (row.get("prev_assistant") or "")[-CTX_CHARS:]
        state["skills_already_loaded_this_session"] = row.get("session_skills") or []
    return state


def ckey(variant, model, state, cands):
    blob = json.dumps([variant, model, state, [n for n, _ in cands]], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()[:20]


def call(enf, key, model, state, qs, timeout):
    body = {"model": model, "state": state, "questions": qs}
    err = None
    for attempt in range(4):
        t0 = time.time()
        try:
            ans = enf._post_json(enf.JEV_URL, body, timeout, {"Authorization": "Bearer " + key})
            return ans["answers"], int((time.time() - t0) * 1000), ans.get("usage"), None
        except Exception as e:  # noqa: BLE001 — retried, then reported (never cached)
            err = type(e).__name__
            time.sleep(1.5 * (attempt + 1))
    return None, None, None, err


# ── corpus ───────────────────────────────────────────────────────────────────
def is_positive(r):
    """Needed a skill, judged from this turn: the skill was loaded and used in THIS turn, outside
    skill-concierge's own sessions, typed interactively, not interrupted, not corrected next turn."""
    return (r["label"] == "NEEDS_SKILL" and r["label_rule"] == "using+executed_this_turn"
            and not r["meta_session"] and r["entry_class"] == "interactive"
            and not r["interrupted"] and not r["next_prompt_correction"])


def gold(r):
    return {n.split(":")[-1] for n in r.get("final_names") or []}


def pick(enf, rows, n_unlab, seed):
    """Positives and a random traffic sample from ONE population: English, interactive, outside
    skill-concierge's own sessions, and reaching the gate in the live hook."""
    pool = [r for r in rows if enf._is_english(r["prompt"]) and r["entry_class"] == "interactive"
            and not r["meta_session"] and reaches_gate(enf, r["prompt"])]
    pos = [r for r in pool if is_positive(r)]
    unl = random.Random(seed).sample(pool, min(n_unlab, len(pool)))
    return pos, unl


def load_corpus(path):
    return [json.loads(line) for line in open(path, encoding="utf-8")]


def read_cache():
    out = {}
    if CACHE.exists():
        for line in open(CACHE, encoding="utf-8"):
            r = json.loads(line)
            out[r["k"]] = r
    return out


def cmd_replay(a):
    key = os.environ.get("TYPESAFE_API_KEY", "")
    if not key:
        sys.exit("TYPESAFE_API_KEY is not set")
    enf = load_enforcer()
    pos, unl = pick(enf, load_corpus(a.corpus), a.unlabelled, a.seed)
    rows = {r["uuid"]: r for r in pos + unl}
    print(f"{len(pos)} positives, {len(unl)} traffic, {len(rows)} unique turns", flush=True)
    cat_h = None
    if a.shelf == "wide":   # the proposed live pipeline: Jev ranks the whole catalogue first
        catalog = live_catalog()
        cat_h = catalog_hash(catalog)
        desc = dict(catalog)
        shelves = {}
        for variant in a.variants:
            a.variant = variant
            for u, rec in wide_answers(enf, a, list(rows.values()), catalog).items():
                shelves[(u, variant)] = [(n, (desc.get(n) or n)[:DESC_CHARS]) for n in enf._jev_shortlist(rec["ans"])]
    else:
        with ThreadPoolExecutor(a.jobs) as ex:
            base = dict(zip(rows, ex.map(lambda r: shelf(enf, r["prompt"]), rows.values())))
        shelves = {(u, v): base[u] for u in rows for v in a.variants}
    cache = read_cache()
    CAL_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(CAL_DIR, 0o700)
    for variant in a.variants:
        todo = []
        for u, r in rows.items():
            st, cands = build_state(r, variant), shelves.get((u, variant), [])
            k = ckey(variant, a.model, st, cands)
            if k not in cache and cands:
                todo.append((u, k, st, cands))
        print(f"{variant}: {len(rows) - len(todo)} cached/empty-shelf, {len(todo)} to score", flush=True)

        def one(t):
            return t, call(enf, key, a.model, t[2], enf._jev_rerank_questions(t[3]), a.timeout)

        done = fails = 0
        with ThreadPoolExecutor(a.jobs) as ex, open(CACHE, "a", encoding="utf-8") as fh:
            for (u, k, st, cands), (ans, ms, usage, err) in ex.map(one, todo):
                done += 1
                if ans is None:
                    fails += 1
                    continue
                fh.write(json.dumps({"k": k, "variant": variant, "model": a.model, "uuid": u, "src": a.shelf, "cat": cat_h,
                                     "shelf": [n for n, _ in cands], "ans": ans, "ms": ms,
                                     "usage": usage}) + "\n")
                fh.flush()
                if done % 100 == 0:
                    print(f"  {variant}: {done}/{len(todo)} ({fails} failed)", flush=True)
        os.chmod(CACHE, 0o600)
        print(f"{variant}: done, {fails} failed (not cached; rerun to retry)", flush=True)
    return 0


# ── signals ──────────────────────────────────────────────────────────────────
def per_candidate(ans, prefix):
    return {int(k.split("::")[1]): v["noul"] for k, v in ans.items() if k.startswith(prefix + "::")}


def signals(rec):
    """Every candidate 'needs a skill' probability derivable from one rerank answer. `max_fits` is
    the live gate; the rest exist only on the exploratory records that asked more questions."""
    ans = rec["ans"]
    fits = per_candidate(ans, "fits")
    probs = ans["which"]["probabilities"]
    top = rec["shelf"].index(max(probs, key=probs.get))
    out = {"max_fits": max(fits.values()), "fits_of_choice_top": fits[top]}
    rel = per_candidate(ans, "relevant")
    if rel:
        out["max_relevant"] = max(rel.values())
        out["max_fits_and_relevant"] = max(min(fits[i], rel[i]) for i in fits)
    if all(f"gate::{k}" in ans for k in GATE_QUESTIONS):
        gates = [(1 - ans[f"gate::{k}"]["noul"]) if k in INVERTED else ans[f"gate::{k}"]["noul"] for k in GATE_QUESTIONS]
        out["gate_mean"] = sum(gates) / len(gates)
        out["fits_x_gate"] = out["max_fits"] * out["gate_mean"]
    if "now" in ans:
        out["now"] = ans["now"]["noul"]
    return out


def scored(enf, a):
    pos, unl = pick(enf, load_corpus(a.corpus), a.unlabelled, a.seed)
    cat_h = catalog_hash(live_catalog()) if a.shelf == "wide" else None
    by_uuid = {rec["uuid"]: rec for rec in read_cache().values()
               if rec["variant"] == a.variant and rec["model"] == a.model
               and rec.get("src", "mpnet") == a.shelf and rec.get("cat") == cat_h}
    P = [(r, by_uuid[r["uuid"]]) for r in pos if r["uuid"] in by_uuid]
    U = [(r, by_uuid[r["uuid"]]) for r in unl if r["uuid"] in by_uuid]
    return P, U, len(pos), len(unl)


def wilson_upper(k, n, z=1.96):
    if n == 0:
        return 1.0
    ph = k / n
    den = 1 + z * z / n
    return min(1.0, (ph + z * z / (2 * n) + z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n))) / den)


def fit_one(pos_p, target):
    """Highest threshold t (0.01 steps) with Wilson-UCB(share of positives scoring < t) <= target."""
    if len(pos_p) < MIN_POSITIVES:
        return None
    best = None
    for t in [round(x * 0.01, 2) for x in range(1, 96)]:
        if wilson_upper(sum(p < t for p in pos_p), len(pos_p)) <= target:
            best = t
    return best


THRESHOLDS = (0.02, 0.05, 0.08, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50)


def cmd_curve(a):
    enf = load_enforcer()
    P, U, np_, nu = scored(enf, a)
    menu = [(r, x) for r, x in U if r["ledger_offer_band"] == "offer"]
    ms = sorted(x["ms"] for _, x in P + U)
    print(f"variant={a.variant}: {len(P)}/{np_} positives, {len(U)}/{nu} traffic scored "
          f"({len(menu)} traffic turns got a menu); latency p50 {ms[len(ms) // 2] if ms else '-'} ms, "
          f"p90 {ms[int(len(ms) * 0.9)] if ms else '-'} ms")
    for sig in (signals(P[0][1]) if P else ()):
        pp = [signals(x)[sig] for _, x in P]
        print(f"\n{sig}\n   thr  false-NO (UCB95)  skip-all  skip-menu")
        for t in THRESHOLDS:
            fn = sum(p < t for p in pp)
            sk = sum(signals(x)[sig] < t for _, x in U) / max(len(U), 1)
            sm = sum(signals(x)[sig] < t for _, x in menu) / max(len(menu), 1)
            print(f"  {t:.2f}  {100 * fn / len(pp):5.1f}% ({100 * wilson_upper(fn, len(pp)):5.1f}%)"
                  f"  {100 * sk:6.1f}%  {100 * sm:7.1f}%")
    return 0


def cmd_fit(a):
    """Fit on turns before --holdout-from, then check the bound on turns from that date on."""
    enf = load_enforcer()
    P, U, _, _ = scored(enf, a)
    train = [x for r, x in P if (r["ts_local"] or "") < a.holdout_from]
    test = [x for r, x in P if (r["ts_local"] or "") >= a.holdout_from]
    menu = [x for r, x in U if r["ledger_offer_band"] == "offer"]
    out = {}
    for sig in (signals(P[0][1]) if P else {}):
        t = fit_one([signals(x)[sig] for x in train], a.target)
        if t is None:
            out[sig] = {"verdict": "insufficient data" if len(train) < MIN_POSITIVES else "no threshold meets target"}
            continue
        fn_te = sum(signals(x)[sig] < t for x in test)
        out[sig] = {"threshold": t, "train_n": len(train), "holdout_n": len(test),
                    "holdout_false_no": fn_te, "holdout_ucb": round(wilson_upper(fn_te, len(test)), 4),
                    "skip_all": round(sum(signals(x)[sig] < t for _, x in U) / max(len(U), 1), 3),
                    "skip_menu": round(sum(signals(x)[sig] < t for x in menu) / max(len(menu), 1), 3)}
    print(json.dumps(out, indent=2))
    return 0


def cmd_rank(a):
    """Gold-skill position in the shortlist: retrieval order vs Jev Choice vs fits vs relevant."""
    enf = load_enforcer()
    P, _, _, _ = scored(enf, a)
    tally = {m: [0, 0, 0] for m in ("retrieval", "jev_choice", "jev_fits", "jev_relevant")}
    n = 0
    for r, rec in P:
        g = gold(r)
        sh = [s.split(":")[-1] for s in rec["shelf"]]
        if not g & set(sh):
            continue
        n += 1
        probs = rec["ans"]["which"]["probabilities"]
        fits, rel = per_candidate(rec["ans"], "fits"), per_candidate(rec["ans"], "relevant")
        orders = {"retrieval": sh,
                  "jev_choice": [s.split(":")[-1] for s in sorted(probs, key=lambda k: -probs[k])],
                  "jev_fits": [sh[i] for i in sorted(fits, key=lambda i: -fits[i])],
                  "jev_relevant": [sh[i] for i in sorted(rel, key=lambda i: -rel[i])]}
        for m, order in orders.items():
            at = min(order.index(x) for x in g if x in order)
            for i, k in enumerate((1, 3, 5)):
                tally[m][i] += at < k
    in_shelf = sum(1 for r, rec in P if gold(r) & {s.split(":")[-1] for s in rec["shelf"]})
    print(f"variant={a.variant}: used skill inside the retrieved shortlist of {SHORTLIST}: "
          f"{in_shelf}/{len(P)} positives")
    for m, (t1, t3, t5) in tally.items():
        print(f"  {m:12s} top-1 {100 * t1 / max(n, 1):5.1f}%   top-3 {100 * t3 / max(n, 1):5.1f}%"
              f"   top-5 {100 * t5 / max(n, 1):5.1f}%")
    return 0


WIDE_CACHE = CAL_DIR / "wide-scores.jsonl"
CATALOG_SNAPSHOT = CAL_DIR / "invocable-catalog.json"   # what live_catalog() last returned, for the record


def catalog_hash(catalog):
    return hashlib.sha256(json.dumps(catalog, sort_keys=True).encode()).hexdigest()[:16]


def live_catalog():
    """The catalogue the live hook would send Jev from this cwd: the enforcer's own `_jev_catalog`
    (project isolation makes it cwd-dependent). Snapshot written for the record; the cache key
    carries the full catalogue, so a changed catalogue is never replayed from stale scores."""
    cat = [list(x) for x in load_enforcer()._jev_catalog()]
    CATALOG_SNAPSHOT.write_text(json.dumps(cat))
    return cat


def wide_answers(enf, a, rows, catalog):
    """{uuid: cached wide record} for rows, calling Jev for the missing ones."""
    cache = {}
    if WIDE_CACHE.exists():
        cache = {json.loads(line)["k"]: json.loads(line) for line in open(WIDE_CACHE, encoding="utf-8")}
    qs = enf._jev_wide_questions(catalog)     # the live builder: replay == hook
    key = os.environ.get("TYPESAFE_API_KEY", "")
    todo, keys = [], {}
    for r in rows:
        st = build_state(r, a.variant)
        k = hashlib.sha256(json.dumps([a.variant, a.model, st, catalog], sort_keys=True).encode()).hexdigest()[:20]
        keys[r["uuid"]] = k
        if k not in cache:
            todo.append((r, k, st))
    if todo and not key:
        sys.exit("TYPESAFE_API_KEY is not set")
    print(f"wide: {len(rows) - len(todo)} cached, {len(todo)} to score", flush=True)
    with ThreadPoolExecutor(a.jobs) as ex, open(WIDE_CACHE, "a", encoding="utf-8") as fh:
        for (r, k, st), (ans, ms, usage, err) in ex.map(lambda t: (t, call(enf, key, a.model, t[2], qs, a.timeout)), todo):
            if ans is not None:
                rec = {"k": k, "uuid": r["uuid"], "variant": a.variant, "ans": ans, "ms": ms, "usage": usage}
                fh.write(json.dumps(rec) + "\n")
                cache[k] = rec
    os.chmod(WIDE_CACHE, 0o600)
    return {u: cache[k] for u, k in keys.items() if k in cache}


def cmd_wide(a):
    """Recall of the used skill: retrieval's shortlist vs a Jev ranking of the WHOLE catalogue."""
    enf = load_enforcer()
    catalog = live_catalog()
    names = {n.split(":")[-1] for n, _ in catalog}
    pos, _ = pick(enf, load_corpus(a.corpus), 0, a.seed)
    pos = [r for r in pos if gold(r) & names]            # gold still invocable today
    by = wide_answers(enf, a, pos, catalog)
    suite = {rec["uuid"]: rec for rec in read_cache().values()
             if rec["variant"] == a.variant and rec.get("src", "mpnet") == "mpnet"}
    n = hit_ret = hit_wide = hit_union = 0
    ms = []
    for r in pos:
        if r["uuid"] not in by or r["uuid"] not in suite:
            continue
        n += 1
        g = gold(r)
        ret = {s.split(":")[-1] for s in suite[r["uuid"]]["shelf"]}
        wide = {s.split(":")[-1] for s in enf._jev_shortlist(by[r["uuid"]]["ans"])}
        hit_ret += bool(g & ret)
        hit_wide += bool(g & wide)
        hit_union += bool(g & (ret | wide))
        ms.append(by[r["uuid"]]["ms"])
    ms.sort()
    tok = sorted((by[u]["usage"] or {}).get("input_tokens", 0) for u in by)
    print(f"variant={a.variant}, catalogue {len(catalog)} skills in {len(enf._jev_wide_questions(catalog))} Choice chunks, {n} positives")
    print(f"  used skill in retrieval shortlist ({SHORTLIST}):      {100 * hit_ret / max(n, 1):5.1f}%")
    print(f"  used skill in Jev wide shortlist ({enf.JEV_PER_CHUNK}/chunk):     {100 * hit_wide / max(n, 1):5.1f}%")
    print(f"  used skill in the union:                          {100 * hit_union / max(n, 1):5.1f}%")
    if ms:
        print(f"  wide call latency p50 {ms[len(ms) // 2]} ms, p90 {ms[int(len(ms) * 0.9)]} ms; "
              f"input tokens p50 {tok[len(tok) // 2]}")
    return 0


def cmd_policy(a):
    """The enforcer's own `_jev_decide` over the cached pipeline answers (src=wide): what the live
    router would have done on each real turn — false NO on positives, skip share, lead accuracy."""
    enf = load_enforcer()
    a.shelf = "wide"
    P, U, _, _ = scored(enf, a)
    catalog = dict(live_catalog())

    def decide(rec):
        sl = [(n, (catalog.get(n) or n)[:DESC_CHARS]) for n in rec["shelf"]]
        return enf._jev_decide(rec["ans"], sl)
    fn = sum(decide(x)[0] == "skip" for _, x in P)
    held = [x for r, x in P if (r["ts_local"] or "") >= a.holdout_from]
    fn_h = sum(decide(x)[0] == "skip" for x in held)
    sk = sum(decide(x)[0] == "skip" for _, x in U)
    installed = {n.split(":")[-1] for n in catalog}
    top_ok = lead_ok = offered = 0
    for r, x in P:
        verdict, rows, _conf, _ = decide(x)
        if verdict != "offer" or not gold(r) & installed:
            continue
        offered += 1
        top_ok += bool(gold(r) & {n.split(":")[-1] for n, _, _ in rows})
        lead_ok += rows[0][0].split(":")[-1] in gold(r)
    print(f"live policy (fits floor {enf.JEV_FITS_FLOOR}, top {enf.JEV_OFFER_ROWS}) on {len(P)} positives, {len(U)} traffic:")
    print(f"  false NO {fn}/{len(P)} ({100 * fn / max(len(P), 1):.1f}%, UCB {100 * wilson_upper(fn, len(P)):.1f}%);"
          f" holdout from {a.holdout_from}: {fn_h}/{len(held)}")
    print(f"  traffic skipped {sk}/{len(U)} ({100 * sk / max(len(U), 1):.1f}%)")
    print(f"  offers (used skill still installed) containing it: {top_ok}/{offered} ({100 * top_ok / max(offered, 1):.1f}%);"
          f" first row is it: {lead_ok} ({100 * lead_ok / max(offered, 1):.1f}%)")
    return 0


def selftest():
    assert wilson_upper(0, 0) == 1.0
    assert abs(wilson_upper(0, 100) - 0.0370) < 1e-3
    assert abs(wilson_upper(3, 431) - 0.0203) < 1e-3
    assert fit_one([0.9] * 400 + [0.04] * 2, 0.03) == 0.9
    assert fit_one([0.9] * 10, 0.03) is None                       # too few positives
    assert fit_one([0.01] * 100 + [0.9] * 100, 0.03) == 0.01       # half at the floor: only a no-op threshold qualifies
    rec = {"shelf": ["a", "b"], "ans": {
        "which": {"probabilities": {"a": 0.2, "b": 0.8}}, "now": {"noul": 0.3},
        "fits::0": {"noul": 0.9}, "fits::1": {"noul": 0.4},
        "relevant::0": {"noul": 0.5}, "relevant::1": {"noul": 0.7},
        "gate::acts_on_user_system": {"noul": 0.6}, "gate::would_follow_documented_procedure": {"noul": 0.6},
        "gate::prose_suffices": {"noul": 0.4}}}
    s = signals(rec)
    assert s["max_fits"] == 0.9 and abs(s["gate_mean"] - 0.6) < 1e-9
    assert s["fits_of_choice_top"] == 0.4 and s["max_relevant"] == 0.7 and s["max_fits_and_relevant"] == 0.5
    print("selftest OK")
    return 0


def main():
    if "--selftest" in sys.argv:
        return selftest()
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("replay", "curve", "fit", "rank", "wide", "policy"):
        s = sub.add_parser(name)
        s.add_argument("--corpus", type=Path, default=CORPUS)
        s.add_argument("--model", default=os.environ.get("ENFORCER_JEV_MODEL", "jev-1.13.0"))
        s.add_argument("--unlabelled", type=int, default=300, help="random traffic sample for the skip share")
        s.add_argument("--seed", type=int, default=20260926)
        s.add_argument("--shelf", default="mpnet", choices=("mpnet", "wide"),
                       help="shortlist source: embedding retrieval, or Jev over the whole catalogue")
        if name in ("replay", "wide"):
            s.add_argument("--jobs", type=int, default=6)
            s.add_argument("--timeout", type=float, default=15.0)
        if name == "replay":
            s.add_argument("--variants", nargs="+", default=list(VARIANTS), choices=VARIANTS)
        else:
            s.add_argument("--variant", default="ctx", choices=VARIANTS)
        if name in ("fit", "policy"):
            s.add_argument("--target", type=float, default=0.03, help="max false-NO rate (95%% upper bound)")
            s.add_argument("--holdout-from", default="2026-09-01", help="fit before this local date, test from it")
    a = ap.parse_args()
    return {"replay": cmd_replay, "curve": cmd_curve, "fit": cmd_fit, "rank": cmd_rank, "wide": cmd_wide, "policy": cmd_policy}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
