#!/usr/bin/env python3
"""
skill-concierge — per-skill threshold calibrator (Phase D, ports the bm25 idea to cosine).

The live enforcer offers any skill whose cosine clears a SINGLE global floor
(GETAWAY_FLOOR=0.20). That floor is a guess. This calibrates a PER-SKILL threshold
(tau) from a labeled scenarios corpus, so each skill could fire at the cosine that
best separates its own positive prompts from near-miss negatives.

Method (mirrors bm25-routing/routing/build-index.js, adapted to cosine):
  - For skill S, fetch its INDEXED vector v_S from Qdrant (the exact vector the
    enforcer scores against — so calibration == live retrieval, no proxy).
  - Score each corpus prompt p as cosine(embed(p), v_S) via the warm embed shim.
    (This IS the score S gets in the live enforcer; no LOO needed — bm25 used
    prompt-vs-prompt LOO only because it had no per-skill vector.)
  - Pick tau maximizing F-beta (beta^2=4, recall-favoring) for the skills that DO
    separate; but classify each skill HONESTLY by its real positive-vs-negative
    cosine separation, NOT by F1 alone (see calibrate()).

HONEST STATUS is the point: a per-skill tau is only meaningful when the skill's own
positive prompts out-score its contrastive negatives. The separation diagnostic
(pos_mean - neg_mean) is method-independent and is what status keys on.

Output: eval/thresholds.json  { skill: {tau, separation, pos_mean, neg_mean,
                                        f1, precision, recall, n_pos, n_neg, status} }
NOT wired into the enforcer here — producing the thresholds is D's calibration step;
activating per-skill tau live is a separate, deliberate change (and only worth doing
for skills whose status is `ok`).

Pure stdlib. Usage:
  python3 scripts/calibrate_thresholds.py            # calibrate + write eval/thresholds.json
  python3 scripts/calibrate_thresholds.py --dry-run  # report only, write nothing
  python3 scripts/calibrate_thresholds.py --selftest # math self-check (no network)
"""
import os
import sys
import json
import math
import argparse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = Path(os.environ.get("SKILL_SCENARIOS_DIR", ROOT / "eval" / "scenarios"))
OUT = Path(os.environ.get("SKILL_THRESHOLDS", ROOT / "eval" / "thresholds.json"))

EMBED_URL = (f"http://{os.environ.get('EMBED_SHIM_HOST','127.0.0.1')}"
             f":{os.environ.get('EMBED_SHIM_PORT','6363')}/embed")
QDRANT = os.environ.get("SKILL_QDRANT_URL", "http://localhost:6333").rstrip("/")
COLLECTION = os.environ.get("SKILL_COLLECTION", "claude_skills")
BETA2 = 4            # recall weighted 4x precision when picking tau (mirrors bm25)
F1_OK = 0.60
SEP_MIN = 0.05       # min (pos_mean - neg_mean) cosine separation for a usable tau


def _post(url, payload, timeout=10.0):
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def embed(text):
    return _post(EMBED_URL, {"text": text})["vector"]


def skill_vector(name):
    """Fetch skill S's indexed vector from Qdrant by exact payload.name."""
    res = _post(f"{QDRANT}/collections/{COLLECTION}/points/scroll", {
        "filter": {"must": [{"key": "name", "match": {"value": name}}]},
        "limit": 1, "with_vector": True,
    })
    pts = res.get("result", {}).get("points", [])
    if not pts:
        return None
    v = pts[0].get("vector")
    return v if isinstance(v, list) else (v or {}).get("default")


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def metrics_at(pos, neg, tau):
    tp = sum(1 for s in pos if s >= tau)
    fn = len(pos) - tp
    fp = sum(1 for s in neg if s >= tau)
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    denom = BETA2 * prec + rec
    fbeta2 = (1 + BETA2) * prec * rec / denom if denom else 0.0
    return prec, rec, f1, fbeta2


def calibrate(pos, neg):
    """Pick tau (F-beta2) AND classify by real separation.

    Status keys on whether the skill's positives actually out-score its contrastive
    negatives — NOT on F1, which is a trap here: with 12 pos vs 5 neg a catch-all tau
    (below every score) already scores F1=0.83 while discriminating nothing.
      no-signal : pos_mean <= neg_mean — cosine flat or INVERTED; no tau can work.
      weak      : positives lead but by < SEP_MIN — a tau exists but is fragile.
      ok        : pos_mean - neg_mean >= SEP_MIN — a usable per-skill tau.
    """
    cands = sorted(set(pos + neg))
    if not cands:
        return None
    pos_mean = round(sum(pos) / len(pos), 4) if pos else 0.0
    neg_mean = round(sum(neg) / len(neg), 4) if neg else 0.0
    best = {"tau": None, "fbeta2": -1.0, "precision": 0.0, "recall": 0.0, "f1": 0.0}
    taus = [cands[0] - 1e-6] + [(cands[i - 1] + cands[i]) / 2 for i in range(1, len(cands))]
    for tau in taus:
        prec, rec, f1, fb = metrics_at(pos, neg, tau)
        if fb > best["fbeta2"]:
            best = {"tau": round(tau, 4), "precision": round(prec, 3),
                    "recall": round(rec, 3), "f1": round(f1, 3), "fbeta2": round(fb, 3)}
    sep = round(pos_mean - neg_mean, 4)
    if pos_mean <= neg_mean:
        status = "no-signal"
    elif sep >= SEP_MIN and best["f1"] >= F1_OK:
        status = "ok"
    else:
        status = "weak"
    best.update(pos_mean=pos_mean, neg_mean=neg_mean, separation=sep, status=status)
    return best


def run(dry_run):
    files = sorted(CORPUS_DIR.glob("*.json"))
    if not files:
        print(f"[calibrate] no corpus at {CORPUS_DIR} (author eval/scenarios/*.json first)")
        return 1
    out, rows = {}, []
    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        skill = d["skill"]
        v = skill_vector(skill)
        if v is None:
            print(f"[calibrate] WARN {skill}: no indexed vector (skipped)")
            continue
        pos = [cosine(embed(p), v) for p in d.get("positive", [])]
        neg = [cosine(embed(n), v) for n in d.get("negative", [])]
        cal = calibrate(pos, neg)
        if cal is None:
            continue
        cal.update(n_pos=len(pos), n_neg=len(neg))
        out[skill] = cal
        rows.append((skill, cal))

    rows.sort(key=lambda r: r[1]["separation"], reverse=True)
    glob_floor = float(os.environ.get("ENFORCER_GETAWAY_FLOOR", "0.20"))
    print(f"\nper-skill calibration ({len(rows)} skills)   single global floor today = {glob_floor}")
    print(f"{'skill':<26}{'pos_mean':>9}{'neg_mean':>9}{'sep':>8}{'tau':>8}{'F1':>6}  status")
    print("-" * 78)
    for skill, c in rows:
        print(f"{skill:<26}{c['pos_mean']:>9.3f}{c['neg_mean']:>9.3f}{c['separation']:>8.3f}"
              f"{c['tau']:>8.3f}{c['f1']:>6.2f}  {c['status']}")
    print("-" * 78)
    counts = {s: sum(1 for _k, c in rows if c["status"] == s) for s in ("ok", "weak", "no-signal")}
    print(f"separation summary: {counts['ok']} ok  ·  {counts['weak']} weak  ·  "
          f"{counts['no-signal']} no-signal   (of {len(rows)})")
    print("read: only `ok` skills have cosine separation strong enough for a trustworthy")
    print("      per-skill tau. `weak`/`no-signal` skills can't be fixed by ANY threshold —")
    print("      the lever for those is the index content/embedding, not calibration.")

    if dry_run:
        print("\n[dry-run] no file written.")
    else:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nwrote {OUT}  ({len(out)} skills). NOT wired into the enforcer (deliberate).")
    return 0


def _selftest():
    """Separation-based status + F-beta math on synthetic sets (no network)."""
    bad = []
    cal = calibrate([0.5, 0.5, 0.5], [0.1, 0.1])              # clean separation
    if not (cal and cal["status"] == "ok" and 0.1 < cal["tau"] < 0.5):
        bad.append(f"separable -> ok: {cal}")
    cal2 = calibrate([0.3, 0.3], [0.3, 0.3])                   # flat overlap
    if not (cal2 and cal2["status"] == "no-signal"):
        bad.append(f"overlap -> no-signal: {cal2}")
    cal3 = calibrate([0.10, 0.12], [0.30, 0.28])               # inverted (neg higher)
    if not (cal3 and cal3["status"] == "no-signal"):
        bad.append(f"inverted -> no-signal: {cal3}")
    cal4 = calibrate([0.22, 0.24, 0.23], [0.20, 0.21])         # thin lead (<SEP_MIN)
    if not (cal4 and cal4["status"] == "weak"):
        bad.append(f"thin-separation -> weak: {cal4}")
    _p, r, _f1, _fb = metrics_at([0.4, 0.5], [0.35], 0.30)
    if r != 1.0:
        bad.append(f"recall calc wrong: r={r}")
    if bad:
        print("calibrate --selftest FAIL:")
        for b in bad:
            print("  " + b)
        return 1
    print("calibrate --selftest OK: separation status (ok/weak/no-signal) + F-beta math")
    return 0


def main():
    ap = argparse.ArgumentParser(description="per-skill threshold calibrator (Phase D)")
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    ap.add_argument("--selftest", action="store_true", help="math self-check, no network")
    args = ap.parse_args()
    if args.selftest:
        return _selftest()
    return run(args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
