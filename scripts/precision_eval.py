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

--mode findability (ADR-0074, design plans/260927-1450-findability-at-the-root SS4 E): the
pre-registered evaluation harness for an index- or ranking-shaping change (F1/F2/X/K). Runs a
BASE owner (the live index) against a CANDIDATE owner (a staging build) over five sets:
  W  every claude-invocable installed skill's name-word probe (the SAME rule
     `skill_search.findability` uses for its own ratchet) -> MCP-view rank, base vs candidate.
  C  real interactive turns (scripts/calibrate_jev_gate.py's `load_corpus`/`is_positive`/
     `gold`), meta skills excluded, English-gating / Vietnamese reported separately.
  D  the same corpus's `search_queries` -> the skill that turn invoked.
  N  every current installed skill's negatives in eval/scenarios-shadow/*.json (if generated;
     absent corpus reports "0/0, not independently verified", never a false PASS-by-omission)
     plus the incident's 7 hand-written controls (evidence/curated_measure.py's NEGATIVE list,
     copied verbatim, target tk-gdelt-doctor).
  G  the 3 GDELT name queries (#1 bar) plus the paraphrase query (F3's, reported only).
Flags: --base-url/--base-embed-port, --candidate-url/--candidate-embed-port (default = base,
so `--mode findability` alone runs a trivial base-vs-itself check), --collection, --corpus
(the private real-turn corpus — read, never copied into this repo), --markdown (also emit a
markdown evidence block). Exit 0 iff every GATING bar (W, C, D per view, N, G-name) passes.
"""
import argparse
import glob
import importlib.util
import json
import math
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vendor" / "skill-search"))
from skill_search import ports  # noqa: E402  (needs ROOT on sys.path first)

CORPUS = Path(os.environ.get("SKILL_SCENARIOS_DIR", ROOT / "eval" / "scenarios"))
QDRANT = ports.qdrant_url(default_port=6333).rstrip("/")
LIVE = os.environ.get("SKILL_COLLECTION", "claude_skills")
SHADOW = os.environ.get("SKILL_SHADOW_COLLECTION", "claude_skills_shadow")
FLOOR = float(os.environ.get("ENFORCER_GETAWAY_FLOOR", "0.20"))
TOPK = 10

# ── findability mode (ADR-0074) ─────────────────────────────────────────────────────────────
REAL_TURN_CORPUS = Path(os.environ.get(
    "SKILL_CONCIERGE_HOME", Path.home() / ".claude" / "skill-concierge")) / \
    "jev-calibration" / "real-turn-labels.jsonl"
SHADOW_SCENARIOS_DIR = Path(os.environ.get("SKILL_SCENARIOS_SHADOW_DIR", ROOT / "eval" / "scenarios-shadow"))
# skill-concierge's OWN skills — evaluating "can we find OUR OWN governance skills" is a
# different, distracting question from "can we find a real task skill" (design SS4 E, set C).
META_SKILLS = {"skill-search", "doctor", "setup", "flywheel", "catalogs", "consult",
               "keep-on", "blocklist", "skill-usage-audit"}
GDELT_SKILL = "tk-gdelt-doctor"
# The 3 queries that literally NAME gdelt (the #1 bar) — plans/.../evidence/gdelt_probe.py's
# default list minus its one non-name-bearing paraphrase, copied verbatim.
GDELT_NAME_QUERIES = ["my gdelt tone query crashed with a unicode error",
                      "move the gdelt-ngrams archive to another server", "gdelt"]
GDELT_PARAPHRASE_QUERY = "is my local news archive up to date and healthy"   # F3's; reported only
# The incident's 7 hand-written controls — plans/.../evidence/curated_measure.py's NEGATIVE
# list, copied verbatim 2026-09-27. Target: GDELT_SKILL must NOT newly rank top-3 for these.
GDELT_INCIDENT_CONTROLS = [
    "ssh to rtx-wsl permission denied",
    "write a vietnamese news briefing about the economy",
    "godot shader programming",
    "search the web for today's news",
    "check disk space on my mac",
    "move my postgres database to another server",
    "monitor vietnamese news sites for new articles",
]
N_RANK_DEPTH = 10          # N/G only ever test "top 3" / "#1" — no need for W's deeper probe
SIGN_TEST_P_BAR = 0.10
N_VIOLATION_RATE_BAR = 0.01
N_VIOLATION_GAIN_FRACTION = 1.0 / 3.0


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


def _exists(collection):
    try:
        with urllib.request.urlopen(f"{QDRANT}/collections/{collection}", timeout=10) as r:
            return r.status == 200
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        raise


METRICS = [("rank1_pct", "correct rank-1 %"), ("top5_pct", "correct top-5 %"),
           ("floor_pct", "clears-floor %"), ("tn_fire_pct", "true-neg false-fire %")]


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
    if not _exists(SHADOW):
        # the enrichment shadow was retired (exported, then dropped): report LIVE alone
        print(f"\nfull 495-way precision_eval  ({live['n_pos']} positives / {live['n_neg']} "
              f"negatives across {len(corpus)} skills)   floor={FLOOR}   "
              f"(no '{SHADOW}' collection — LIVE only)")
        for k, lab in METRICS:
            print(f"{lab:<26}{live[k]:>10}")
        print(f"OFFER-SET CROWDING  mean {live['offer_mean']}  median {live['offer_median']}  "
              f"p95 {live['offer_p95']}  (of 495)")
        return 0
    shadow = eval_collection(SHADOW, qvec, corpus)

    print(f"\nfull 495-way precision_eval  ({live['n_pos']} positives / {live['n_neg']} "
          f"negatives across {len(corpus)} skills)   floor={FLOOR}")
    print(f"{'metric':<26}{'LIVE':>10}{'SHADOW':>10}{'Δ':>10}")
    print("-" * 56)
    for k, lab in METRICS:
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
    print("  -> if SHADOW crowds far above LIVE, the global floor MUST be re-tuned before the")
    print("     enriched index improves OFFERS (rank gains are scale-invariant and stand regardless).")
    print("\nSHADOW confusion (who steals a positive when correct isn't rank-1):")
    for n, c in list(shadow["confusion"].items())[:12]:
        print(f"   {c:>3}x  {n}")
    return 0


# ═══════════════════════════════════════════════════════════════════════════════════════════
# findability mode (ADR-0074) — pre-registered evaluation harness, design SS4 E
# ═══════════════════════════════════════════════════════════════════════════════════════════

# ── bar math: pure, no I/O, no network — the whole reason it is decomposed this way ────────
def sign_test_p(lost: int, gained: int) -> float:
    """One-sided binomial sign-test p-value: P(X <= lost) under Binomial(lost + gained, 0.5).
    A SMALL p means it would be unlikely, if gains/losses were an unbiased coin flip, to see
    this FEW losses — i.e. losses are rare relative to gains (design bar 2's "p <= 0.10
    against loss"). n == 0 (nothing changed either way) is the strongest possible no-loss
    signal, not an undefined one, so it returns 0.0 rather than raising or returning 1.0."""
    n = lost + gained
    if n == 0:
        return 0.0
    return sum(math.comb(n, i) for i in range(0, lost + 1)) / (2 ** n)


def gains_losses(base_hits, cand_hits) -> tuple:
    """(gained, lost) from two parallel "was the gold skill in the cut" boolean sequences."""
    gained = sum(1 for b, c in zip(base_hits, cand_hits) if c and not b)
    lost = sum(1 for b, c in zip(base_hits, cand_hits) if b and not c)
    return gained, lost


def lost_gained_cases(pairs, base_hits, cand_hits) -> tuple:
    """([(text, target), ...] lost, [(text, target), ...] gained) — the individual cases
    behind cd_bar's aggregate counts, for the release evidence's full lost-case list."""
    lost = [pairs[i] for i, (b, c) in enumerate(zip(base_hits, cand_hits)) if b and not c]
    gained = [pairs[i] for i, (b, c) in enumerate(zip(base_hits, cand_hits)) if c and not b]
    return lost, gained


def cd_bar(base_hits, cand_hits) -> dict:
    """One (set, view) bar 2 verdict: net top-6 change >= 0 AND the sign test clears 0.10."""
    gained, lost = gains_losses(base_hits, cand_hits)
    net = gained - lost
    p = sign_test_p(lost, gained)
    return {"gained": gained, "lost": lost, "net": net, "p": round(p, 4),
            "passed": net >= 0 and p <= SIGN_TEST_P_BAR}


def w_bar(w_rows: list, topn: int = 3) -> dict:
    """Bar 1 (v4.1 wording, the fix for the v4 review's blocker): no W probe leaves the top
    `topn`, and the count of probes in the top `topn` must not fall."""
    leavers = [r for r in w_rows if r["base_rank"] <= topn and r["cand_rank"] > topn]
    base_top = sum(1 for r in w_rows if r["base_rank"] <= topn)
    cand_top = sum(1 for r in w_rows if r["cand_rank"] <= topn)
    return {"leavers": leavers, "base_top3": base_top, "cand_top3": cand_top,
            "passed": not leavers and cand_top >= base_top}


def n_bar(violations: int, n_total: int, recall_gains: int) -> dict:
    """Bar 3 (Thinh's decision): violations <= 1% of N AND <= 1/3 of the recall gains
    (W + C + D). Vacuously satisfied on an empty N (0/0) — the CALLER must still disclose
    that as unverified, never print it as a measured pass."""
    if n_total == 0:
        return {"rate_ok": True, "gain_ok": True, "passed": True}
    rate_ok = violations <= N_VIOLATION_RATE_BAR * n_total
    gain_ok = violations <= N_VIOLATION_GAIN_FRACTION * recall_gains
    return {"rate_ok": rate_ok, "gain_ok": gain_ok, "passed": rate_ok and gain_ok}


def g_bar(name_query_ranks: list) -> dict:
    """Bar 4: the 3 GDELT name queries at #1 in the MCP view (candidate)."""
    return {"ranks": name_query_ranks, "passed": bool(name_query_ranks)
            and all(r == 1 for r in name_query_ranks)}


# ── module loading: two fresh enforcer instances (base/candidate each bake their OWN
# QDRANT_URL/EMBED_PORT into module globals at import time — one shared, cached instance
# cannot serve both) ─────────────────────────────────────────────────────────────────────────
def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _enforcer_for(cal, qdrant_url: str, embed_port: int):
    """A fresh enforcer pinned at (qdrant_url, embed_port), reusing `cal.load_enforcer`'s own
    body — its cache is reset first so base and candidate get genuinely separate instances."""
    os.environ["SKILL_QDRANT_URL"] = qdrant_url
    os.environ["EMBED_SHIM_PORT"] = str(embed_port)
    os.environ.setdefault("SKILL_CONCIERGE_HARNESS", "claude")
    cal.ENF = None
    return cal.load_enforcer()


def _server_for(engine_root: Path):
    """A fresh `skill_search.server` loaded from `engine_root`'s OWN vendor/skill-search, so a
    BASE checkout that predates the ADR-0075 installed/external complement rule (X) genuinely
    lacks `_search_complement_on`/`_arrange_tiers` — `search_skills_rank` detects that absence
    and falls back to the pre-X plain shape, rather than this script guessing which side has
    the mechanism. No network state to bake in: `_scope_filter`/`_installed_only_filter`/
    `_external_only_filter`/`_arrange_tiers`/`_search_complement_on` take the query URL as an
    explicit argument (via `findability.py`'s `_query_groups`) or read a live env flag, never a
    module-level owner URL. `skills_discovery` still resolves through the normal import system
    (whichever copy is first on sys.path), which is immaterial here: none of the functions this
    is used for reads skill CONTENT, only harness-root CONFIG."""
    return _load_module(f"precision_eval_server_{engine_root}",
                        engine_root / "vendor" / "skill-search" / "skill_search" / "server.py")


def _mcp_rank(fnd, embed_cache: dict, embed_base: str, query_base: str, collection: str,
             scope_filter, srv, text: str, target: str, depth: int) -> int:
    """The MCP-view rank of `target` for `text`, exactly as `search_skills()` on THIS `srv`
    instance would return it (`skill_search.findability.search_skills_rank` — the complement
    arrangement when `srv` carries X and it is on, else the pre-X plain shape). Never re-
    embedded twice for the same (embed_base, text) — a free win when --candidate-url defaults
    to --base-url."""
    key = (embed_base, text)
    if key not in embed_cache:
        embed_cache[key] = fnd._owner_embed(embed_base, text)
    rank, _winner = fnd.search_skills_rank(query_base, collection, scope_filter, srv,
                                           embed_cache[key], target, depth)
    return rank


def _enforcer_hit6(enf, text: str, target: str) -> bool:
    """Is `target` in the enforcer's own installed top-6 for `text`?"""
    vector = enf._embed(text)
    return any(n == target for n, _d, _s in enf._retrieve(vector))


# ── corpus loading ───────────────────────────────────────────────────────────────────────────
def _cd_pairs(cal, enf, corpus_path: Path) -> tuple:
    """(C, D) sets, each {"en": [(text, target), ...], "vn": [...]}. C = prompt -> gold();
    D = the row's first `search_queries` entry -> gold(). Meta skills excluded from both;
    `is_positive`/`gold` are `calibrate_jev_gate.py`'s own, reused verbatim."""
    rows = cal.load_corpus(corpus_path)
    c = {"en": [], "vn": []}
    d = {"en": [], "vn": []}
    for r in rows:
        if not cal.is_positive(r):
            continue
        g = sorted(cal.gold(r))
        if not g or g[0] in META_SKILLS:
            continue
        target = g[0]
        lang = "en" if enf._is_english(r["prompt"]) else "vn"
        c[lang].append((r["prompt"], target))
        sq = r.get("search_queries")
        if isinstance(sq, str) and sq.startswith("["):
            try:
                sq = json.loads(sq.replace("'", '"'))
            except (ValueError, TypeError):
                sq = []
        for q in (sq or [])[:1]:
            if isinstance(q, str) and q.strip():
                d[lang].append((q, target))
    return c, d


def _n_pairs(installed_names: set) -> list:
    """[(skill, negative_text), ...]: every CURRENT installed skill's authored negatives in
    eval/scenarios-shadow/*.json (llm_eval_gen.py's output, gitignored — absent on a fresh
    checkout is normal, never an error) plus the incident's 7 hand-written controls."""
    rows = []
    if SHADOW_SCENARIOS_DIR.is_dir():
        for f in sorted(SHADOW_SCENARIOS_DIR.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            skill = data.get("skill")
            if skill not in installed_names:
                continue
            for neg in data.get("negative") or []:
                if isinstance(neg, str) and neg.strip():
                    rows.append((skill, neg))
    if GDELT_SKILL in installed_names:
        rows += [(GDELT_SKILL, q) for q in GDELT_INCIDENT_CONTROLS]
    return rows


def _markdown_block(base_url, cand_url, w_result, cd_results, vn_counts, n_result,
                    n_pairs_n, violations, g_result, g_ranks, overall) -> str:
    lines = ["## Findability evidence (ADR-0074)",
            f"- base `{base_url}` vs candidate `{cand_url}`",
            f"- **W** (name-word, MCP view): base top-3 {w_result['base_top3']}, "
            f"candidate top-3 {w_result['cand_top3']}, leavers {len(w_result['leavers'])} "
            f"-> **{'PASS' if w_result['passed'] else 'FAIL'}**"]
    for label in ("C", "D"):
        for view in ("mcp", "enforcer"):
            r = cd_results[f"{label}_{view}"]
            lines.append(f"- **{label} [{view}]**: +{r['gained']}/-{r['lost']} "
                         f"(net {r['net']:+d}, p={r['p']}) -> "
                         f"**{'PASS' if r['passed'] else 'FAIL'}**")
    lines.append(f"  - Vietnamese slice (informational, not gated): C={vn_counts['C']}, "
                f"D={vn_counts['D']}")
    lines.append(f"- **N**: {len(violations)}/{n_pairs_n} violations -> "
                f"**{'PASS' if n_result['passed'] else 'FAIL'}**"
                + ("" if n_pairs_n else " (vacuous — eval/scenarios-shadow/ not generated "
                                       "here, NOT independently verified)"))
    lines.append(f"- **G** (name queries, MCP view): {g_ranks} -> "
                f"**{'PASS' if g_result['passed'] else 'FAIL'}**")
    lines.append(f"- **Overall: {'PASS' if overall else 'FAIL'}**")
    return "\n".join(lines)


def run_findability(args) -> int:
    os.chdir(Path.home())      # pin the view, mirroring skill_search.findability's own sweep
    cal = _load_module("precision_eval_calibrate_jev_gate", ROOT / "scripts" / "calibrate_jev_gate.py")
    from skill_search import findability as fnd
    from skill_search import server as srv
    from skill_search import skills_discovery as sd

    base_url, base_port = args.base_url, args.base_embed_port
    cand_url = args.candidate_url or args.base_url
    cand_port = (args.candidate_embed_port if args.candidate_embed_port is not None
                else args.base_embed_port)
    base_embed, cand_embed = f"http://127.0.0.1:{base_port}", f"http://127.0.0.1:{cand_port}"

    enf_base = _enforcer_for(cal, base_url, base_port)
    enf_cand = _enforcer_for(cal, cand_url, cand_port)
    # `srv` (this script's OWN skill_search.server) governs the candidate side by construction
    # — this script IS the candidate's code. The base side gets its OWN instance only when
    # --base-engine-root names a different checkout (e.g. origin/main, which predates the
    # ADR-0075 installed/external complement rule); absent that flag, base is assumed to run
    # the SAME code (the --mode findability self-check with no flags at all).
    srv_base = _server_for(args.base_engine_root) if args.base_engine_root else srv
    scope_filter = srv._scope_filter()
    embed_cache = {}

    def rank(embed_base, query_base, srv_side, text, target, depth):
        return _mcp_rank(fnd, embed_cache, embed_base, query_base, args.collection,
                         scope_filter, srv_side, text, target, depth)

    print(f"\nfindability eval (ADR-0074)  base={base_url} embed=:{base_port}  "
          f"candidate={cand_url} embed=:{cand_port}  collection={args.collection}")

    # ---- W ----
    all_skills = sd.discover_skills()
    installed_names = {s["name"] for s in all_skills
                       if not str(s.get("scope", "")).startswith("catalog:")}
    df = fnd.document_frequency(all_skills)
    w_skills = fnd._installed_skills(enf_base, sd)
    w_rows = []
    for s in w_skills:
        tok = fnd.probe_token(s["name"], df)
        if tok is None:
            continue
        br = rank(base_embed, base_url, srv_base, tok, s["name"], fnd.NAME_RANK_DEPTH)
        cr = rank(cand_embed, cand_url, srv, tok, s["name"], fnd.NAME_RANK_DEPTH)
        w_rows.append({"skill": s["name"], "token": tok, "base_rank": br, "cand_rank": cr})
    w_result = w_bar(w_rows)
    print(f"W: {len(w_rows)} probes  base top-3 {w_result['base_top3']}  "
          f"candidate top-3 {w_result['cand_top3']}  leavers {len(w_result['leavers'])}  "
          f"-> {'PASS' if w_result['passed'] else 'FAIL'}")
    for r in w_result["leavers"][:20]:
        print(f"    LEFT TOP-3  {r['skill']!r} ({r['token']!r}): "
              f"{r['base_rank']} -> {r['cand_rank']}")

    # ---- C / D ----
    c_sets, d_sets = _cd_pairs(cal, enf_base, args.corpus)
    cd_results = {}
    for label, pairs in (("C", c_sets["en"]), ("D", d_sets["en"])):
        base_mcp = [rank(base_embed, base_url, srv_base, q, t, N_RANK_DEPTH) <= 6 for q, t in pairs]
        cand_mcp = [rank(cand_embed, cand_url, srv, q, t, N_RANK_DEPTH) <= 6 for q, t in pairs]
        base_enf = [_enforcer_hit6(enf_base, q, t) for q, t in pairs]
        cand_enf = [_enforcer_hit6(enf_cand, q, t) for q, t in pairs]
        cd_results[f"{label}_mcp"] = cd_bar(base_mcp, cand_mcp)
        cd_results[f"{label}_enforcer"] = cd_bar(base_enf, cand_enf)
        cd_cases = {"mcp": lost_gained_cases(pairs, base_mcp, cand_mcp),
                   "enforcer": lost_gained_cases(pairs, base_enf, cand_enf)}
        for view in ("mcp", "enforcer"):
            r = cd_results[f"{label}_{view}"]
            print(f"{label} [{view}]: n={len(pairs)} +{r['gained']}/-{r['lost']} "
                  f"net {r['net']:+d} p={r['p']}  -> {'PASS' if r['passed'] else 'FAIL'}")
            lost, _gained = cd_cases[view]
            if lost:
                print(f"  {label} [{view}] LOST cases ({len(lost)}):")
                for q, t in lost:
                    print(f"    LOST  {t!r} <- {q!r}")
        cd_results[f"{label}_cases"] = cd_cases
    vn_counts = {"C": len(c_sets["vn"]), "D": len(d_sets["vn"])}
    print(f"  (English rows gate the bar; Vietnamese reported separately: "
          f"C={vn_counts['C']}, D={vn_counts['D']})")

    # ---- N ----
    n_pairs = _n_pairs(installed_names)
    violations = []
    for skill, text in n_pairs:
        br = rank(base_embed, base_url, srv_base, text, skill, N_RANK_DEPTH)
        cr = rank(cand_embed, cand_url, srv, text, skill, N_RANK_DEPTH)
        if br > 3 and cr <= 3:
            violations.append({"skill": skill, "query": text, "base_rank": br, "cand_rank": cr})
    recall_gains = (sum(1 for r in w_rows if r["base_rank"] > 3 and r["cand_rank"] <= 3)
                    + cd_results["C_mcp"]["gained"] + cd_results["D_mcp"]["gained"])
    n_result = n_bar(len(violations), len(n_pairs), recall_gains)
    print(f"N: {len(violations)}/{len(n_pairs)} violations "
          f"(bar <= {N_VIOLATION_RATE_BAR * 100:.0f}% AND <= 1/3 of the recall gains "
          f"{recall_gains})  -> {'PASS' if n_result['passed'] else 'FAIL'}"
          + ("" if n_pairs else "  [N is EMPTY on this machine (eval/scenarios-shadow/ not "
                                "generated) — this PASS is VACUOUS, not independently verified]"))
    for v in violations:
        print(f"    VIOLATION  {v['skill']!r} <- {v['query']!r}: "
              f"{v['base_rank']} -> {v['cand_rank']}")

    # ---- G ----
    g_applicable = GDELT_SKILL in installed_names
    g_ranks = ([rank(cand_embed, cand_url, srv, q, GDELT_SKILL, N_RANK_DEPTH)
               for q in GDELT_NAME_QUERIES] if g_applicable else [])
    g_result = g_bar(g_ranks) if g_applicable else {"ranks": [], "passed": True}
    if g_applicable:
        g_base_ranks = [rank(base_embed, base_url, srv_base, q, GDELT_SKILL, N_RANK_DEPTH)
                        for q in GDELT_NAME_QUERIES]
        g_para_rank = rank(cand_embed, cand_url, srv, GDELT_PARAPHRASE_QUERY, GDELT_SKILL,
                          N_RANK_DEPTH)
        print(f"G (name, #1 bar): base {g_base_ranks} -> candidate {g_ranks}  "
              f"-> {'PASS' if g_result['passed'] else 'FAIL'}")
        print(f"G (paraphrase, F3's territory — reported only, never gated): "
              f"candidate rank {g_para_rank}")
    else:
        print(f"G: {GDELT_SKILL!r} is not installed here — not applicable "
              "(counted as PASS, not independently verified)")

    gating = {"W": w_result["passed"], "C_mcp": cd_results["C_mcp"]["passed"],
             "C_enforcer": cd_results["C_enforcer"]["passed"],
             "D_mcp": cd_results["D_mcp"]["passed"],
             "D_enforcer": cd_results["D_enforcer"]["passed"],
             "N": n_result["passed"], "G": g_result["passed"]}
    overall = all(gating.values())
    print("\nPASS/FAIL by bar: " + "  ".join(f"{k}={'PASS' if v else 'FAIL'}"
                                              for k, v in gating.items()))
    print(f"OVERALL: {'PASS' if overall else 'FAIL'} "
          f"({sum(gating.values())}/{len(gating)} bars)")

    if args.markdown:
        print("\n" + _markdown_block(base_url, cand_url, w_result, cd_results, vn_counts,
                                     n_result, len(n_pairs), violations, g_result, g_ranks,
                                     overall))
    return 0 if overall else 1


def main():
    ap = argparse.ArgumentParser(description="full 495-way recall + precision gate, or "
                                              "--mode findability (ADR-0074)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--mode", choices=("495", "findability"), default="495",
                    help="495 = the original full-495-way recall/precision gate (default); "
                         "findability = the ADR-0074 base-vs-candidate harness")
    ap.add_argument("--base-url", default=os.environ.get("SKILL_QDRANT_URL", "http://127.0.0.1:6333"),
                    help="findability mode: the BASE owner's Qdrant-compatible query URL")
    ap.add_argument("--base-embed-port", type=int,
                    default=int(os.environ.get("EMBED_SHIM_PORT", "6363")),
                    help="findability mode: the BASE owner's embed port")
    ap.add_argument("--candidate-url", default=None,
                    help="findability mode: the CANDIDATE owner's query URL "
                         "(default: same as --base-url, for a trivial self-check)")
    ap.add_argument("--candidate-embed-port", type=int, default=None,
                    help="findability mode: the CANDIDATE owner's embed port "
                         "(default: same as --base-embed-port)")
    ap.add_argument("--base-engine-root", type=Path, default=None,
                    help="findability mode: repo root whose vendor/skill-search/server.py the "
                         "BASE owner is actually running, when it differs from this script's "
                         "own code (e.g. origin/main, pre-ADR-0075) — lets the MCP-view rank "
                         "correctly detect that BASE has no installed/external complement rule "
                         "to apply. Default: assume BASE runs the same code as this script.")
    ap.add_argument("--collection", default=os.environ.get("SKILL_COLLECTION", "claude_skills"),
                    help="findability mode: the collection name on BOTH owners")
    ap.add_argument("--corpus", type=Path, default=REAL_TURN_CORPUS,
                    help="findability mode: the private real-turn corpus (read, never copied)")
    ap.add_argument("--markdown", action="store_true",
                    help="findability mode: also print a markdown evidence block")
    args = ap.parse_args()
    if args.selftest:
        # selftest must not require the engine import
        bad = []
        ranked = [("a", 0.9), ("b", 0.5), ("c", 0.1)]
        if rank_of(ranked, "b") != (2, 0.5):
            bad.append("rank_of wrong")
        if rank_of(ranked, "z") != (None, None):
            bad.append("missing-name rank wrong")
        if abs(sign_test_p(8, 24) - 0.0035) > 1e-3:
            bad.append("sign_test_p wrong (n=32,lost=8)")
        if sign_test_p(0, 0) != 0.0:
            bad.append("sign_test_p(0,0) must be 0.0, not undefined")
        if not w_bar([{"base_rank": 1, "cand_rank": 1}])["passed"]:
            bad.append("w_bar wrong on a no-op")
        if n_bar(0, 0, 0)["passed"] is not True:
            bad.append("n_bar must vacuously pass on an empty N")
        if bad:
            print("precision_eval --selftest FAIL:", bad); return 1
        print("precision_eval --selftest OK: rank_of + missing-name handling + bar math")
        return 0
    if args.mode == "findability":
        return run_findability(args)
    return run()


if __name__ == "__main__":
    sys.exit(main())
