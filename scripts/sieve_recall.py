#!/usr/bin/env python3
"""
sieve_recall.py — consult sieve recall instrument: a frozen held-out case set built from real
turns, recorded query generation, and a gate harness that runs the REPO's own engine.

  build    freeze the case set (labels resolved to exact indexed names) -> private cases + manifest
  queries  generate the arm queries through the flywheel gateway (append, resume, lock);
           `--retry-failed` retries failed keys, `--freeze` locks the file by sha256
  gate     run the arms over the frozen cases under an index lock and print one VERDICT per
           decision; arms: A0 (today's doctrine, flags off), A1 (slots), A2 (RRF), T (task
           sentence), H (process query), S (one sub-goal per query), C (the shipping combination)

Plan: plans/261003-1907-consult-sieve-recall-fixes/ (phase 1 holds every pre-registered rule;
changing a rule after the freeze voids the gate). Private data lives in
~/.claude/skill-concierge/jev-calibration/ (dir 0700, files 0600), never in the repo.

Engine and gateway imports are lazy: the pure functions below need neither.
"""
import argparse
import hashlib
import json
import math
import os
import random
import re
import statistics
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

SEED = "sieve-recall-261004"
HOME = Path(os.environ.get("SKILL_CONCIERGE_HOME", Path.home() / ".claude" / "skill-concierge"))
CAL_DIR = HOME / "jev-calibration"
LABELS = CAL_DIR / "real-turn-labels.jsonl"
CONSULT_EVAL = CAL_DIR / "consult-eval.jsonl"
CASES = CAL_DIR / "sieve-eval-cases.jsonl"
QUERIES = CAL_DIR / "sieve-eval-queries.jsonl"
LOCK = CAL_DIR / "sieve-eval-queries.lock"
MANIFEST = CAL_DIR / "sieve-eval-manifest.json"

MAX_PER_LABEL = 5
MIN_WORDS = 8
TEMPERATURE = 0.4          # flywheel_llm.chat's fixed temperature, recorded with every reply
PROCESS_LABELS = ("ak-cook", "ak-plan", "tk-research", "session-handoff", "compound-to-skill")
ARMS = ("A0", "A1", "A2", "T", "H", "S", "C")
DECISIONS = ("slots", "rrf", "task", "how", "split")   # Holm family: m = 5, fixed
ARM_OF = {"slots": "A1", "rrf": "A2", "task": "T", "how": "H", "split": "S"}

# Gate constants (pre-registered)
MIN_N = 30
G2_GAIN_PTS = 5.0
G3_LOSS_FRACTION = 0.20
G5_MEDIAN_EXT = 4
G5_SHARE_RISE_PTS = 10.0
G6_P90_MS = 100.0
GUARD_LOWER_PTS = -5.0
MISSING_FRACTION = 0.10
ALPHA = 0.05
BOOT_RESAMPLES = 2000

# Doctrine texts, fixed in advance. DOCTRINE_TODAY is skills/consult/SKILL.md steps 1 and 2 verbatim.
DOCTRINE_TODAY = (
    "Restate the task and split it into 2-5 sub-goals (label them A, B, C…). A niche skill that "
    "serves only one sub-goal must still surface — that is why the sieve takes one query per "
    "sub-goal, not one blended query. Phrase each query by INTENT + DOMAIN TERMS, away from the "
    "skill names you expect.")
PART_TASK = ("Put the user's own words first: one query that copies the sentence where the user "
             "states the task, verbatim, up to about 300 characters.")
PART_HOW = ("Add one query that says how the work will be carried out (the working method or "
            "process), with no domain terms; place it before the sub-goal queries.")
PART_SPLIT = "Each sub-goal is one action on one object; never join two actions in one query."
CAP_NOTE = ("The sieve keeps only the first five queries, so the extra queries above push out the "
            "last sub-goal queries.")
# Harness text around the doctrine so the generating model knows its role and the reply shape. Fixed
# here, part of every system text, therefore part of its recorded sha256.
_ROLE = ("You write the search queries an agent passes to a skill-search tool for the task the user "
         "message gives you. Follow these instructions. ")
_FMT_LIST = ' Reply with JSON only: {"queries": ["...", "..."]}'
_FMT_ONE = ' Reply with JSON only: {"query": "..."}'
SYSTEM = {
    "d0": _ROLE + DOCTRINE_TODAY + _FMT_LIST,
    "how": _ROLE + PART_HOW + _FMT_ONE,
    "split": _ROLE + DOCTRINE_TODAY + " " + PART_SPLIT + _FMT_LIST,
}
PARTS = ("d0", "how", "split")


def sha256_text(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ── lazy module access ─────────────────────────────────────────────────────────────────────
_CACHE = {}


def _pe():
    """precision_eval as PE: puts the repo engine first on sys.path. The engine env goes in first."""
    if "pe" not in _CACHE:
        import engine_env
        os.environ.update(engine_env.engine_env())
        import precision_eval
        _CACHE["pe"] = precision_eval
    return _CACHE["pe"]


def _cal():
    if "cal" not in _CACHE:
        import calibrate_jev_gate
        _CACHE["cal"] = calibrate_jev_gate
    return _CACHE["cal"]


def _enf():
    """The live enforcer module (redaction, English test, skill key), loaded once."""
    if "enf" not in _CACHE:
        _CACHE["enf"] = _cal().load_enforcer()
    return _CACHE["enf"]


def skill_key(name):
    return _enf()._skill_key(name)


# ── text helpers ───────────────────────────────────────────────────────────────────────────
def _collapse(text):
    return re.sub(r"\s+", " ", text).strip()


def clean_prompt(prompt, truncated=False):
    """Prompt text as it may leave the machine: injected blocks stripped, secret shapes redacted.
    truncated: the corpus cut this prompt mid-text, so the last token may be half a secret that
    no redaction pattern can recognise; it is dropped before redaction."""
    enf = _enf()
    text = prompt or ""
    if truncated:
        text = re.sub(r"\S*$", "", text)
    text = enf._JEV_REMINDER_RE.sub("", text)
    for rx in enf._JEV_INJECTED_RES:
        text = rx.sub("", text)
    return _collapse(enf._jev_redact(text))


def gen_text(prompt, truncated=False):
    return clean_prompt(prompt, truncated)[:4000]


def task_sentence(prompt):
    """The mechanical task query: redacted, whitespace collapsed, first 300 characters. No model."""
    return clean_prompt(prompt)[:300]


def named_in_prompt(key, prompt):
    """True when `key` (a full skill key) occurs in the lower-cased prompt, ':' read as '-', as a
    whole token: not preceded or followed by a word character or '-'."""
    text = (prompt or "").lower().replace(":", "-")
    return re.search(r"(?<![\w-])" + re.escape(key) + r"(?![\w-])", text) is not None


def label_words(key):
    return [w for w in re.split(r"[-:]", key) if len(w) >= 4]


def leaks(key, queries):
    """True when any query contains, as a whole word, a word of 4+ letters from the label's key."""
    words = label_words(key)
    for q in queries or []:
        low = (q or "").lower()
        for w in words:
            if re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", low):
                return True
    return False


# ── label resolution ───────────────────────────────────────────────────────────────────────
def build_name_index(points):
    """points: [{"name", "tier"?, "scope"?}] of kind=base. Returns the lookup tables."""
    names = {p["name"] for p in points}
    by_key, installed_short = {}, {}
    for p in points:
        by_key.setdefault(skill_key(p["name"]), set()).add(p["name"])
        if p.get("tier") != "external":
            installed_short.setdefault(p["name"].split(":")[-1], set()).add(p["name"])
    return {"names": names, "by_key": by_key, "installed_short": installed_short}


def resolve_label(label, idx):
    """(indexed name | None, how). Order: exact name; unique full key; a bare label with no
    namespace to a unique installed short name. how: exact|key|short|ambiguous|missing."""
    if label in idx["names"]:
        return label, "exact"
    hit = idx["by_key"].get(skill_key(label), set())
    if len(hit) == 1:
        return next(iter(hit)), "key"
    if len(hit) > 1:
        return None, "ambiguous"
    if ":" not in label:
        short = idx["installed_short"].get(label, set())
        if len(short) == 1:
            return next(iter(short)), "short"
        if len(short) > 1:
            return None, "ambiguous"
    return None, "missing"


def collisions(points):
    """Short names (the part after the last ':') shared by 2+ base points."""
    by_short = {}
    for p in points:
        by_short.setdefault(p["name"].split(":")[-1], []).append(p)
    out = {}
    for s, ps in sorted(by_short.items()):
        if len(ps) > 1:
            out[s] = {"names": sorted(p["name"] for p in ps),
                      "cross_tier": len({p.get("tier") == "external" for p in ps}) > 1}
    return out


def router_group(label_key, ledger_offered):
    """offered | not_offered | unknown. ledger_offered is a list of [name, score] pairs or None."""
    if ledger_offered is None:
        return "unknown"
    keys = {skill_key(e[0] if isinstance(e, (list, tuple)) else e) for e in ledger_offered}
    return "offered" if label_key in keys else "not_offered"


def _order_hash(tag, uid):
    return hashlib.sha256(f"{SEED}:{tag}{uid}".encode()).hexdigest()


def pick_cases(candidates):
    """candidates: [{"id","uuid","key",...}]. Hash order, at most MAX_PER_LABEL per label key."""
    kept, per = [], {}
    for c in sorted(candidates, key=lambda c: _order_hash("", c["uuid"]) + c["key"]):
        if per.get(c["key"], 0) >= MAX_PER_LABEL:
            continue
        per[c["key"]] = per.get(c["key"], 0) + 1
        kept.append(c)
    return kept


def make_pairs(cases):
    """Composite pairs: hash order; each unused case takes the next unused case in the order from
    another session with another label. A case is used at most once. Returns [(id_a, id_b)]."""
    order = sorted(cases, key=lambda c: _order_hash("pair:", c["uuid"]) + c["key"])
    used, pairs = set(), []
    for i, a in enumerate(order):
        if a["id"] in used:
            continue
        for b in order[i + 1:]:
            if b["id"] in used or b["sid"] == a["sid"] or b["key"] == a["key"]:
                continue
            used.update((a["id"], b["id"]))
            pairs.append((a["id"], b["id"]))
            break
    return pairs


def dedupe_runs(runs):
    """Real consult runs: forked transcripts hold the same call, so (task, queries) counts once."""
    seen, out = set(), []
    for r in runs:
        k = (r.get("task"), json.dumps(r.get("queries"), sort_keys=True))
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


# ── metric and gate math (pure) ────────────────────────────────────────────────────────────
def hit_at(label_name, rows, k):
    """Full-skill-key match against the first k rows. Never a short-name match."""
    want = skill_key(label_name)
    return any(skill_key(r.get("name", "")) == want for r in rows[:k])


def rank_of(label_name, rows, miss=41):
    want = skill_key(label_name)
    for i, r in enumerate(rows):
        if skill_key(r.get("name", "")) == want:
            return i + 1
    return miss


def pctl(xs, q):
    if not xs:
        return None
    s = sorted(xs)
    return s[min(len(s) - 1, max(0, math.ceil(q * len(s)) - 1))]


def session_sign(sids, base_hits, arm_hits):
    """Session-level sign test: a session's net is its gains minus its losses over its cases.
    Returns (gained_sessions, lost_sessions, p). No discordant session gives p = 1."""
    pe = _pe()
    net = {}
    for s, b, a in zip(sids, base_hits, arm_hits):
        net[s] = net.get(s, 0) + (1 if a and not b else 0) - (1 if b and not a else 0)
    gained = sum(1 for v in net.values() if v > 0)
    lost = sum(1 for v in net.values() if v < 0)
    p = 1.0 if gained + lost == 0 else pe.sign_test_p(lost, gained)
    return gained, lost, p


def rules_sha256():
    """Fingerprint of every pre-registered gate rule: the freeze records it and the gate refuses to
    run when it differs, so a rule changed after the freeze cannot pass silently."""
    rules = {"DECISIONS": DECISIONS, "ARM_OF": ARM_OF, "ARM_FLAGS": ARM_FLAGS, "MIN_N": MIN_N,
             "G2_GAIN_PTS": G2_GAIN_PTS, "G3_LOSS_FRACTION": G3_LOSS_FRACTION,
             "G5_MEDIAN_EXT": G5_MEDIAN_EXT, "G5_SHARE_RISE_PTS": G5_SHARE_RISE_PTS,
             "G6_P90_MS": G6_P90_MS, "GUARD_LOWER_PTS": GUARD_LOWER_PTS,
             "MISSING_FRACTION": MISSING_FRACTION, "ALPHA": ALPHA, "BOOT_RESAMPLES": BOOT_RESAMPLES,
             "SEED": SEED}
    return sha256_text(json.dumps(rules, sort_keys=True))


def holm_adjusted(pvals):
    """Holm-adjusted p-values in input order: the k-th smallest becomes the running maximum of
    min(1, (m - j) * p_(j)) over j <= k, so adjusted <= alpha is exactly the step-down rejection."""
    m = len(pvals)
    out = [1.0] * m
    running = 0.0
    for rank, i in enumerate(sorted(range(m), key=lambda i: pvals[i])):
        running = max(running, min(1.0, (m - rank) * pvals[i]))
        out[i] = running
    return out


def holm(pvals, alpha=ALPHA):
    """Holm step-down over the whole family. Returns a list of bools in input order."""
    return [a <= alpha for a in holm_adjusted(pvals)]


def bootstrap_lower(units, seed=SEED, resamples=BOOT_RESAMPLES):
    """Paired bootstrap 95% CI lower bound (points) of the recall difference. units are
    (difference_sum, observations) per resampling unit (a session, or a composite pair)."""
    if not units:
        return None
    rng = random.Random(seed)
    n = len(units)
    vals = []
    for _ in range(resamples):
        d = o = 0.0
        for _j in range(n):
            u = units[rng.randrange(n)]
            d += u[0]
            o += u[1]
        vals.append(100.0 * d / o if o else 0.0)
    vals.sort()
    return vals[int(0.025 * resamples)]


def guard_units(entries):
    """entries: [(unit_key, diff, n_obs)] -> bootstrap units grouped by unit_key."""
    acc = {}
    for k, d, n in entries:
        a = acc.setdefault(k, [0.0, 0])
        a[0] += d
        a[1] += n
    return [tuple(v) for v in acc.values()]


def gate_rules(base, arm, min_n=MIN_N):
    """Rules G1-G3, G5, G6 for one decision on its primary set. base/arm: parallel lists of
    {id, sid, label, hit, ms, ext, rows}. G4 (session sign test) is returned as a p-value for the
    Holm step, which needs all five decisions."""
    n = len(base)
    out = {"n": n}
    if n < min_n:
        out.update(verdict="INSUFFICIENT", G1=False)
        return out
    bh, ah = [b["hit"] for b in base], [a["hit"] for a in arm]
    gained = sum(1 for b, a in zip(bh, ah) if a and not b)
    lost = sum(1 for b, a in zip(bh, ah) if b and not a)
    gain_pts = 100.0 * (sum(ah) - sum(bh)) / n
    share = lambda rs: 100.0 * statistics.mean(r["ext"] / max(r["rows"], 1) for r in rs)
    share_b, share_a = share(base), share(arm)
    med_ext = statistics.median(a["ext"] for a in arm)
    p90b, p90a = pctl([b["ms"] for b in base], 0.9), pctl([a["ms"] for a in arm], 0.9)
    gs, ls, p = session_sign([b["sid"] for b in base], bh, ah)
    out.update(
        G1=True, gained=gained, lost=lost, gain_pts=gain_pts,
        G2=gain_pts >= G2_GAIN_PTS,
        G3=lost <= G3_LOSS_FRACTION * gained,
        G5=med_ext >= G5_MEDIAN_EXT and share_a <= share_b + G5_SHARE_RISE_PTS,
        G6=p90a <= p90b + G6_P90_MS,
        med_ext=med_ext, share_base=share_b, share_arm=share_a,
        p90_base=p90b, p90_arm=p90a,
        sessions_gained=gs, sessions_lost=ls, p=p,
        base_recall=100.0 * sum(bh) / n, arm_recall=100.0 * sum(ah) / n,
        lost_cases=[(b["id"], b["label"]) for b, a in zip(base, arm) if b["hit"] and not a["hit"]],
    )
    return out


def verdict_of(rules, p_holm_ok, guard=None):
    """PASS / FAIL / INSUFFICIENT from gate_rules + the Holm outcome + the guard bound."""
    if not rules["G1"]:
        return "INSUFFICIENT"
    ok = rules["G2"] and rules["G3"] and rules["G5"] and rules["G6"] and p_holm_ok
    if guard is not None:
        ok = ok and guard["ok"]
    return "PASS" if ok else "FAIL"


def ship_choice(passed):
    """passed: {decision: {"p": Holm-adjusted p, "gain_pts": gain}}. Smallest p ships; tie -> larger gain."""
    if not passed:
        return None
    return sorted(passed, key=lambda d: (passed[d]["p"], -passed[d]["gain_pts"]))[0]


# ── index access ───────────────────────────────────────────────────────────────────────────
def _qdrant():
    _pe()  # puts the repo engine on sys.path for the import below
    from skill_search import ports
    return ports.qdrant_url(default_port=6333).rstrip("/"), os.environ.get("SKILL_COLLECTION", "claude_skills")


def _http(url, payload=None, timeout=60):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def scroll_base_points():
    base, coll = _qdrant()
    out, offset = [], None
    while True:
        body = {"limit": 1000, "with_payload": ["name", "scope", "tier"], "with_vector": False,
                "filter": {"must": [{"key": "kind", "match": {"value": "base"}}]}}
        if offset is not None:
            body["offset"] = offset
        res = _http(f"{base}/collections/{coll}/points/scroll", body)["result"]
        out += [p["payload"] for p in res["points"]]
        offset = res.get("next_page_offset")
        if offset is None:
            return out


def index_state():
    base, coll = _qdrant()
    info = _http(f"{base}/collections/{coll}")["result"]
    pts = scroll_base_points()
    names = sorted(p["name"] for p in pts)
    return {"points_count": info["points_count"], "base_count": len(names),
            "names_sha256": sha256_text("\n".join(names)), "names": names}


def lock_line(state):
    return f"INDEX-LOCK points={state['points_count']} base={state['base_count']} names_sha256={state['names_sha256']}"


def check_index_lock(start, end):
    """Abort (raise) unless the two states are identical."""
    for k in ("points_count", "base_count", "names_sha256"):
        if start[k] != end[k]:
            raise RuntimeError(f"index changed during the gate: {k} {start[k]} -> {end[k]}")


# ── private file io ────────────────────────────────────────────────────────────────────────
def _ensure_dir():
    CAL_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(CAL_DIR, 0o700)


def write_private(path, text):
    _ensure_dir()
    tmp = Path(str(path) + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def read_jsonl(path):
    if not Path(path).exists():
        return []
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


def read_manifest():
    return json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}


# ── build ──────────────────────────────────────────────────────────────────────────────────
def consult_sessions():
    """Sessions with a recorded consult run: consult-eval.jsonl, plus any label row that called it."""
    return {r["session"] for r in read_jsonl(CONSULT_EVAL)}


def build_cases(rows, points, consult_sids, meta_skills, is_positive):
    """The pure build: rows (label corpus), points (indexed base points), the sessions that ran a
    consult, META_SKILLS and the positive rule. Returns (cases, stats)."""
    idx = build_name_index(points)
    sess = set(consult_sids) | {r["sid"] for r in rows if r.get("consult_call")}
    stats = {"eligible_turns": 0, "resolved": {"exact": 0, "key": 0, "short": 0},
             "ambiguous": [], "missing": [], "meta_dropped": [], "named_dropped": []}
    cand = []
    for r in rows:
        if not (is_positive(r) and r["prompt_words"] >= MIN_WORDS and r["sid"] not in sess):
            continue
        stats["eligible_turns"] += 1
        seen = set()
        for label in r.get("final_names") or []:
            name, how = resolve_label(label, idx)
            if name is None:
                stats["ambiguous" if how == "ambiguous" else "missing"].append(label)
                continue
            stats["resolved"][how] += 1
            key = skill_key(name)
            if key in seen:
                continue
            seen.add(key)
            if name.split(":")[-1] in meta_skills or label.split(":")[-1] in meta_skills:
                stats["meta_dropped"].append(label)
                continue
            if named_in_prompt(key, r["prompt"]):
                stats["named_dropped"].append(label)
                continue
            cand.append({"id": f"{r['uuid']}|{key}", "uuid": r["uuid"], "sid": r["sid"],
                         "label_orig": label, "label": name, "key": key,
                         "group": router_group(key, r.get("ledger_offered")),
                         "process": key in PROCESS_LABELS,
                         "english": bool(_enf()._is_english(r["prompt"])),
                         "task": task_sentence(r["prompt"]), "gen_text": gen_text(r["prompt"], r.get("prompt_chars", 0) > len(r["prompt"]))})
    cases = pick_cases(cand)
    pair_of = {}
    for a, b in make_pairs(cases):
        pair_of[a], pair_of[b] = b, a
    for c in cases:
        c["pair"] = pair_of.get(c["id"])
    stats["candidates_before_cap"] = len(cand)
    return cases, stats


def cmd_build(args):
    if read_manifest().get("frozen") and not args.force:
        print("manifest is frozen: build refused (use --force only to start a new, unfrozen evaluation)",
              file=sys.stderr)
        return 2
    pe = _pe()
    cal = _cal()
    rows = cal.load_corpus(LABELS)
    points = scroll_base_points()
    state = index_state()
    cases, st = build_cases(rows, points, consult_sessions(), pe.META_SKILLS, cal.is_positive)
    groups = {g: sum(1 for c in cases if c["group"] == g) for g in ("not_offered", "offered", "unknown")}
    sessions = {c["sid"] for c in cases}
    sessions_no = {c["sid"] for c in cases if c["group"] == "not_offered"}
    pairs = [(c["id"], c["pair"]) for c in cases if c["pair"] and c["id"] < c["pair"]]
    coll = collisions(points)
    cross = sum(1 for v in coll.values() if v["cross_tier"])
    manifest = {
        "seed": SEED, "built_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "inputs": {"real-turn-labels.jsonl": sha256_file(LABELS),
                   "consult-eval.jsonl": sha256_file(CONSULT_EVAL),
                   "doctrine_today_sha256": sha256_text(DOCTRINE_TODAY)},
        "counts": {"labels_rows": len(rows), "eligible_turns": st["eligible_turns"],
                   "candidates_before_cap": st["candidates_before_cap"], "cases": len(cases),
                   "labels": len({c["key"] for c in cases}), "sessions": len(sessions),
                   "sessions_not_offered": len(sessions_no), "groups": groups,
                   "composite_pairs": len(pairs), "english": sum(c["english"] for c in cases),
                   "process_group": sum(c["process"] for c in cases),
                   "label_resolution": st["resolved"],
                   "labels_not_indexed": len(st["missing"]), "labels_ambiguous": len(st["ambiguous"]),
                   "labels_named_in_prompt": len(st["named_dropped"]),
                   "labels_meta": len(st["meta_dropped"]),
                   "collisions": len(coll), "collisions_cross_tier": cross},
        "dropped": {"missing": sorted(set(st["missing"])), "ambiguous": sorted(set(st["ambiguous"])),
                    "named_in_prompt": sorted(set(st["named_dropped"])),
                    "meta": sorted(set(st["meta_dropped"]))},
        "collisions": coll,
        "index": {k: state[k] for k in ("points_count", "base_count", "names_sha256")},
        "index_names": state["names"],
        "pairs": pairs, "frozen": False,
    }
    cases_text = "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cases)
    write_private(CASES, cases_text)
    manifest["cases_sha256"] = sha256_file(CASES)
    write_private(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=1))
    c = manifest["counts"]
    print(f"cases {c['cases']}  labels {c['labels']}  sessions {c['sessions']}")
    print(f"groups not_offered {groups['not_offered']} / offered {groups['offered']} / unknown {groups['unknown']}"
          f"  (not_offered sessions {c['sessions_not_offered']})")
    print(f"composites {c['composite_pairs']}  english {c['english']}  process-group {c['process_group']}")
    print(f"eligible turns {c['eligible_turns']}  before cap {c['candidates_before_cap']}  "
          f"resolution {c['label_resolution']}  not indexed {c['labels_not_indexed']}  "
          f"ambiguous {c['labels_ambiguous']}  named-in-prompt {c['labels_named_in_prompt']}  meta {c['labels_meta']}")
    print(f"collisions {c['collisions']} short names shared by 2+ base points "
          f"({c['collisions_cross_tier']} across installed and external)")
    print(f"index points={state['points_count']} base={state['base_count']}")
    for k, v in manifest["inputs"].items():
        print(f"sha256 {k} {v}")
    print(f"sha256 cases {manifest['cases_sha256']}")
    return 0


# ── query generation ───────────────────────────────────────────────────────────────────────
class LockError(RuntimeError):
    pass


def acquire_lock(path=None):
    path = Path(path or LOCK)
    _ensure_dir()
    for _ in range(2):
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(str(os.getpid()))
            return path
        except FileExistsError:
            try:
                pid = int(path.read_text().strip() or 0)
            except (OSError, ValueError):
                pid = 0
            alive = False
            if pid > 0:
                try:
                    os.kill(pid, 0)
                    alive = True
                except ProcessLookupError:
                    alive = False
                except PermissionError:
                    alive = True
            if alive:
                raise LockError(f"queries already running (pid {pid}, lock {path})")
            path.unlink(missing_ok=True)
    raise LockError(f"could not take lock {path}")


def release_lock(path=None):
    Path(path or LOCK).unlink(missing_ok=True)


def query_key(cid, part, system):
    return f"{cid}|{part}|{sha256_text(system)[:16]}"


def latest_records(path=None):
    """The newest record per key (a retry appends a new one)."""
    out = {}
    for r in read_jsonl(path or QUERIES):
        out[r["k"]] = r
    return out


def _append(path, rec):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.chmod(path, 0o600)


def jobs_for(cases, real_runs):
    """[(case_id, part, text)] — every generation call, in a fixed order."""
    jobs = []
    for c in cases:
        for part in PARTS:
            jobs.append((c["id"], part, c["gen_text"]))
    for i, r in enumerate(real_runs):
        jobs.append((f"fid:{i}", "d0", clean_prompt(r["task"])[:4000]))
    return jobs


def generate(jobs, chat_fn, model, path=None, retry_failed=False, log=print):
    """Append one record per call as soon as it returns (flushed, fsync'd). A rerun skips keys already
    written, failed ones included unless retry_failed. Returns (calls_made, failed_now)."""
    path = Path(path or QUERIES)
    done = latest_records(path)
    calls = failed = 0
    for cid, part, text in jobs:
        k = query_key(cid, part, SYSTEM[part])
        prior = done.get(k)
        if prior is not None and not (retry_failed and prior.get("err")):
            continue
        rec = {"k": k, "case": cid, "part": part, "doctrine_sha": sha256_text(SYSTEM[part])[:16],
               "model": model, "temperature": TEMPERATURE}
        try:
            rec["reply"] = chat_fn(SYSTEM[part], text)
            rec["err"] = None
        except Exception as e:  # noqa: BLE001 — recorded, retried only with --retry-failed
            rec["reply"], rec["err"] = None, f"{type(e).__name__}: {str(e)[:200]}"
            failed += 1
        calls += 1
        _append(path, rec)
        if calls % 10 == 0 or rec["err"]:
            log(f"{time.strftime('%H:%M:%S')} call {calls} {part} {cid[:20]} err={rec['err']}")
    return calls, failed


def _strings(v):
    """Every non-empty string in a reply value: a string, a list of them, or dicts holding
    `queries` / `query` (the model sometimes answers a one-query ask with a list, or wraps each
    query in a dict)."""
    if isinstance(v, str):
        return [v.strip()] if v.strip() else []
    if isinstance(v, list):
        return [s for x in v for s in _strings(x)]
    if isinstance(v, dict):
        return _strings(v["queries"]) if "queries" in v else _strings(v.get("query"))
    return []


def queries_of(rec):
    """A record's query list (d0, split) or its how-query candidates (the arm takes the first);
    [] when the reply is missing or holds no string."""
    return _strings((rec or {}).get("reply"))


def load_generated(path=None):
    """{case_id: {part: [queries]}} from the latest records."""
    out = {}
    for r in latest_records(path).values():
        q = queries_of(r)
        if q:
            out.setdefault(r["case"], {})[r["part"]] = q
    return out


def real_runs():
    return dedupe_runs(read_jsonl(CONSULT_EVAL))


def leak_dropped(cases, gen):
    return sorted(c["id"] for c in cases
                  if leaks(c["key"], [q for qs in gen.get(c["id"], {}).values() for q in qs]))


def cmd_queries(args):
    man = read_manifest()
    if not man:
        print("no manifest: run build first", file=sys.stderr)
        return 2
    cases = read_jsonl(CASES)
    if man.get("frozen"):
        # a re-freeze only re-records counts for the SAME file (a parser fix, never new queries)
        if args.freeze and not args.retry_failed and sha256_file(QUERIES) == man["queries"]["sha256"]:
            return _freeze(man, cases, man["queries"]["model"])
        print("queries are frozen: refusing to run", file=sys.stderr)
        return 2
    import flywheel_llm
    try:
        acquire_lock()
    except LockError as e:
        print(str(e), file=sys.stderr)
        return 3
    try:
        if args.freeze:
            return _freeze(man, cases, flywheel_llm.MODEL)
        jobs = jobs_for(cases, real_runs())
        print(f"{len(jobs)} calls planned; model {flywheel_llm.MODEL}; "
              f"{len(latest_records())} keys already recorded")
        calls, failed = generate(jobs, flywheel_llm.chat, flywheel_llm.MODEL,
                                 retry_failed=args.retry_failed)
        print(f"made {calls} calls, {failed} failed")
    finally:
        release_lock()
    return 0


def _freeze(man, cases, model):
    if man.get("rules_sha256", rules_sha256()) != rules_sha256():
        raise RuntimeError("the gate rules changed since the freeze; a re-freeze cannot re-register them")
    recs = latest_records()
    by_part = {}
    for r in recs.values():
        d = by_part.setdefault(r["part"], {"keys": 0, "failed": 0})
        d["keys"] += 1
        d["failed"] += 1 if (r.get("err") or not queries_of(r)) else 0
    gen = load_generated()
    leak = leak_dropped(cases, gen)
    man["queries"] = {"sha256": sha256_file(QUERIES), "model": model, "temperature": TEMPERATURE,
                      "records": len(read_jsonl(QUERIES)), "by_part": by_part,
                      "system_sha256": {p: sha256_text(s) for p, s in SYSTEM.items()},
                      "leak_dropped": len(leak), "leak_dropped_ids": leak}
    man["rules_sha256"] = rules_sha256()
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if man.get("frozen"):
        man.setdefault("refrozen_utc", []).append(now)
    else:
        man["frozen"] = True
        man["frozen_utc"] = now
    write_private(MANIFEST, json.dumps(man, ensure_ascii=False, indent=1))
    print(f"frozen: sha256 {man['queries']['sha256']} model {model} temperature {TEMPERATURE}")
    print(f"by part: {by_part}")
    print(f"leak-dropped cases: {len(leak)}")
    return 0


# ── engine loading ─────────────────────────────────────────────────────────────────────────
class EngineError(RuntimeError):
    pass


def load_engine():
    """The REPO's server.py, never the stale venv copy. Env first, then cwd = home, then PE."""
    import engine_env
    os.environ.update(engine_env.engine_env())
    os.chdir(Path.home())
    pe = _pe()
    srv = pe._server_for(ROOT)
    assert_engine(srv, ())
    return srv


def assert_engine(srv, arms, root=ROOT):
    path = Path(getattr(srv, "__file__", "") or "").resolve()
    try:
        path.relative_to(Path(root).resolve())
    except ValueError:
        raise EngineError(f"engine loaded from {path}, outside the repo {Path(root).resolve()}")
    readers = {"A1": ("_consult_slots_on",), "A2": ("_consult_rrf_on",),
               "C": ("_consult_slots_on", "_consult_rrf_on")}
    for n in sorted({n for a in arms for n in readers.get(a, ())}):
        if not hasattr(srv, n):
            raise EngineError(f"engine at {path} lacks {n}: arm cannot run (phase 2 flag reader missing)")


# ── gate ───────────────────────────────────────────────────────────────────────────────────
ARM_FLAGS = {"A0": ("0", "0"), "A1": ("1", "0"), "A2": ("0", "1"), "T": ("0", "0"), "H": ("0", "0"),
             "S": ("0", "0")}


def arm_queries(arm, gen, case, parts=None):
    """The query list an arm sends for a single case, or None when its parts are missing."""
    g = gen.get(case["id"], {})
    d0, how, split = g.get("d0"), g.get("how"), g.get("split")
    if arm in ("A0", "A1", "A2"):
        return d0[:5] if d0 else None
    if arm == "T":
        return ([case["task"]] + d0)[:5] if d0 else None
    if arm == "H":
        return (how[:1] + d0)[:5] if how and d0 else None
    if arm == "S":
        return split[:5] if split else None
    if arm == "C":
        qs = []
        if "task" in parts:
            qs.append(case["task"])
        if "how" in parts:
            if not how:
                return None
            qs += how[:1]
        body = split if "split" in parts else d0
        if not body:
            return None
        return (qs + body)[:5]
    raise ValueError(arm)


def composite_queries(a, b, gen):
    da, db = gen.get(a["id"], {}).get("d0"), gen.get(b["id"], {}).get("d0")
    return (da[:2] + db[:2]) if da and db else None


def call_engine(srv, queries, top_n, slots, rrf):
    os.environ["SKILL_CONSULT_SLOTS"] = slots
    os.environ["SKILL_CONSULT_RRF"] = rrf
    t0 = time.perf_counter()
    raw = srv.consult_candidates(queries, top_n)
    ms = (time.perf_counter() - t0) * 1000.0
    data = json.loads(raw)
    if "error" in data:
        raise EngineError(f"consult_candidates error: {data['error']}")
    return data.get("results") or [], ms


def measure(srv, queries, slots, rrf):
    """One arm call at K=20 (gating, timed) and K=40 (reported)."""
    r20, ms = call_engine(srv, queries, 20, slots, rrf)
    r40, _ = call_engine(srv, queries, 40, slots, rrf)
    return r20, r40, ms


def run_single(srv, case, queries, flags):
    r20, r40, ms = measure(srv, queries, *flags)
    return {"id": case["id"], "sid": case["sid"], "label": case["label"], "hit": hit_at(case["label"], r20, 20),
            "hit40": hit_at(case["label"], r40, 40), "ms": ms,
            "ext": sum(1 for r in r20 if r.get("external")), "rows": len(r20)}


def run_composite(srv, a, b, queries, flags):
    r20, _, ms = measure(srv, queries, *flags)
    ha, hb = hit_at(a["label"], r20, 20), hit_at(b["label"], r20, 20)
    return {"unit": a["id"], "hit_count": int(ha) + int(hb), "n_labels": 2, "ms": ms}


def fidelity(srv, runs, gen, idx):
    """R6: rank of the resolved chosen skill under the recorded queries vs the generated d0 queries,
    top_n 40, flags off; 41 stands for '>40'."""
    rows = []
    for i, r in enumerate(runs):
        name, how = resolve_label(r["primary"], idx)
        if name is None:
            rows.append({"i": i, "primary": r["primary"], "skip": how})
            continue
        g = gen.get(f"fid:{i}", {}).get("d0")
        real, _ = call_engine(srv, r["queries"][:5], 40, "0", "0")
        gen_rank = None
        if g:
            gr, _ = call_engine(srv, g[:5], 40, "0", "0")
            gen_rank = rank_of(name, gr)
        rows.append({"i": i, "primary": name, "real": rank_of(name, real), "gen": gen_rank})
    return rows


def fidelity_report(rows):
    lines = ["FIDELITY (rank of the chosen skill, top_n 40, flags off; 41 = >40)",
             "  run  primary                      real  generated"]
    diffs, agree, n = [], 0, 0
    for r in rows:
        if "skip" in r:
            lines.append(f"  {r['i']:>3}  {r['primary'][:28]:<28}  skipped ({r['skip']})")
            continue
        g = "n/a" if r["gen"] is None else r["gen"]
        lines.append(f"  {r['i']:>3}  {r['primary'][:28]:<28}  {r['real']:>4}  {g:>9}")
        if r["gen"] is not None:
            n += 1
            diffs.append(abs(r["real"] - r["gen"]))
            agree += (r["real"] <= 20) == (r["gen"] <= 20)
    med = statistics.median(diffs) if diffs else None
    lines.append(f"  median absolute rank difference {med}; both <=20 or both >20 in {agree} of {n} runs")
    return "\n".join(lines)


def check_freeze(man):
    if not man.get("frozen"):
        raise RuntimeError("the evaluation is not frozen: run `queries --freeze` first")
    for label, path, want in (("labels", LABELS, man["inputs"]["real-turn-labels.jsonl"]),
                              ("cases", CASES, man["cases_sha256"]),
                              ("queries", QUERIES, man["queries"]["sha256"])):
        got = sha256_file(path)
        if got != want:
            raise RuntimeError(f"{label} file changed since the freeze: {got} != {want}")
    if man.get("rules_sha256") != rules_sha256():
        raise RuntimeError("the gate rules differ from the ones recorded at the freeze "
                           f"({man.get('rules_sha256')} != {rules_sha256()})")


def run_arms(srv, cases, pairs, gen, arms):
    """Single cases in a rotating arm order, then composite pairs for A0/A1/A2. Returns (res, comp):
    res[arm][case_id] and comp[arm][pair_unit]."""
    res = {a: {} for a in arms}
    for n, case in enumerate(cases):
        for a in arms[n % len(arms):] + arms[:n % len(arms)]:
            q = arm_queries(a, gen, case)
            if q:
                res[a][case["id"]] = run_single(srv, case, q, ARM_FLAGS[a])
    comp = {a: {} for a in arms if a in ("A0", "A1", "A2")}
    for ca, cb in pairs:
        q = composite_queries(ca, cb, gen)
        if q:
            for a in comp:
                comp[a][ca["id"]] = run_composite(srv, ca, cb, q, ARM_FLAGS[a])
    return res, comp


def cmd_gate(args):
    man = read_manifest()
    check_freeze(man)
    arms = [a for a in (args.arms.split(",") if args.arms else ARMS[:6]) if a]
    for a in arms:
        if a not in ARMS or a == "C":
            raise SystemExit(f"unknown or non-selectable arm {a!r}; C is built from --combine or the passing decisions")
    if "A0" not in arms:
        arms.insert(0, "A0")
    combine = None
    if args.combine:
        f, _, p = args.combine.partition(":")
        combine = ([x for x in f.split(",") if x], [x for x in p.split(",") if x])
    srv = load_engine()
    assert_engine(srv, arms + (["C"] if combine else []))
    cases = read_jsonl(CASES)
    gen = load_generated()
    start = index_state()
    print(f"provenance: script sha256 {sha256_file(Path(__file__))} rules sha256 {rules_sha256()}")
    print(lock_line(start))
    built = set(man["index_names"])
    now = set(start["names"])
    print(f"index drift vs build: +{len(now - built)} -{len(built - now)}")
    idx = build_name_index(scroll_base_points())
    live_names = idx["names"]
    gone = [c["id"] for c in cases if c["label"] not in live_names]
    print(f"cases dropped, label no longer indexed: {len(gone)}")
    leak = set(leak_dropped(cases, gen))
    print(f"cases dropped by the leak check: {len(leak)}")
    drop = leak | set(gone)
    cases = [c for c in cases if c["id"] not in drop]
    byid = {c["id"]: c for c in cases}
    pairs = [(byid[a], byid[b]) for a, b in man["pairs"] if a in byid and b in byid] if args.composites else []

    # warm-up call, discarded
    call_engine(srv, ["warm up the skill index"], 20, "0", "0")

    res, comp = run_arms(srv, cases, pairs, gen, arms)

    # arm C: only after the single-arm verdicts (or an explicit --combine)
    fid = fidelity(srv, real_runs(), gen, idx)
    verdicts = evaluate(cases, pairs, res, comp, combine, srv, gen)
    end = index_state()
    print(lock_line(end))
    check_index_lock(start, end)
    for line in verdicts:
        print(line)
    print(fidelity_report(fid))
    for line in strata_report(cases, res):
        print(line)
    for a in arms:
        rs = list(res[a].values())
        if rs:
            n = len(rs)
            print(f"RECALL {a}: n={n} @20 {100.0 * sum(r['hit'] for r in rs) / n:.1f}  "
                  f"@40 {100.0 * sum(r['hit40'] for r in rs) / n:.1f}  p50 {pctl([r['ms'] for r in rs], .5):.0f} ms  "
                  f"p90 {pctl([r['ms'] for r in rs], .9):.0f} ms")
    return 0


def strata_report(cases, res):
    """Reported, never gating: recall@20 per arm on the English, process-skill, unknown-router and
    router-group strata, with case and session counts."""
    strata = {"all": lambda c: True, "english": lambda c: c.get("english"),
              "process": lambda c: c.get("process"), "unknown": lambda c: c["group"] == "unknown",
              "not_offered": lambda c: c["group"] == "not_offered", "offered": lambda c: c["group"] == "offered"}
    lines = []
    for name, f in strata.items():
        sel = [c for c in cases if f(c)]
        ids = {c["id"] for c in sel}
        sessions = len({c["sid"] for c in sel})
        parts = []
        for a, r in res.items():
            hs = [v["hit"] for i, v in r.items() if i in ids]
            parts.append(f"{a} {100.0 * sum(hs) / len(hs):.1f}" if hs else f"{a} n/a")
        lines.append(f"STRATUM {name}: cases {len(sel)} sessions {sessions} recall@20 " + "  ".join(parts))
    return lines


def _pair(res, a, b, ids):
    ids = [i for i in ids if i in res[a] and i in res[b]]
    return [res[a][i] for i in ids], [res[b][i] for i in ids]


def _guard(base_rows, arm_rows):
    """Non-inferiority guard over single-case rows: resampling unit = session."""
    ent = [(b["sid"], int(a["hit"]) - int(b["hit"]), 1) for b, a in zip(base_rows, arm_rows)]
    low = bootstrap_lower(guard_units(ent))
    return {"lower": low, "ok": low is not None and low >= GUARD_LOWER_PTS}


def _composite_guard(base, arm):
    """Non-inferiority guard over composite pairs ({unit: {hit_count, n_labels}}); unit = the pair."""
    ids = [i for i in base if i in arm]
    ent = [(i, arm[i]["hit_count"] - base[i]["hit_count"], base[i]["n_labels"]) for i in ids]
    low = bootstrap_lower(guard_units(ent))
    return {"lower": low, "ok": low is not None and low >= GUARD_LOWER_PTS, "n": len(ids)}


def evaluate(cases, pairs, res, comp, combine, srv, gen):
    """The five decisions, Holm, and the combination. Returns the printed lines."""
    lines = []
    all_ids = [c["id"] for c in cases]
    primary = {"slots": all_ids, "rrf": all_ids, "how": all_ids, "split": all_ids,
               "task": [c["id"] for c in cases if c["group"] == "not_offered"]}
    rules, guards = {}, {}
    for d in DECISIONS:
        a = ARM_OF[d]
        if a not in res:
            continue
        ids = primary[d]
        lacking = sum(1 for i in ids if i not in res[a])
        if lacking > MISSING_FRACTION * max(len(ids), 1):
            rules[d] = {"n": len(ids), "verdict": "INSUFFICIENT", "G1": False,
                        "why": f"{lacking} of {len(ids)} primary cases lack queries"}
            continue
        b, r = _pair(res, "A0", a, ids)
        rules[d] = gate_rules(b, r)
        if rules[d]["G1"]:
            if d == "task":
                off = [c["id"] for c in cases if c["group"] == "offered"]
                ob, orr = _pair(res, "A0", a, off)
                guards[d] = _guard(ob, orr) if ob else {"lower": None, "ok": False}
            elif d in ("slots", "rrf"):
                guards[d] = _composite_guard(comp["A0"], comp[a]) if comp.get(a) else {"lower": None, "ok": False, "n": 0}
    pvals = [rules[d]["p"] if d in rules and rules[d].get("G1") else 1.0 for d in DECISIONS]
    adj = dict(zip(DECISIONS, holm_adjusted(pvals)))
    ok_holm = {d: adj[d] <= ALPHA for d in DECISIONS}
    passed = {}
    for d in DECISIONS:
        if d not in rules:
            lines.append(f"VERDICT: {d} NOT RUN")
            continue
        v = verdict_of(rules[d], ok_holm[d], guards.get(d))
        proxy = " (proxy)" if d in ("task", "how", "split") else ""
        r = rules[d]
        if v == "INSUFFICIENT":
            lines.append(f"VERDICT: {d} INSUFFICIENT{proxy} n={r['n']} {r.get('why', '')}")
            continue
        g = guards.get(d)
        gtxt = "" if g is None else f" guard_lower={g['lower'] if g['lower'] is None else round(g['lower'], 2)} guard_ok={g['ok']}"
        lines.append(
            f"VERDICT: {d} {v}{proxy} n={r['n']} recall@20 {r['base_recall']:.1f} -> {r['arm_recall']:.1f} "
            f"(gain {r['gain_pts']:.1f} pts) G2={r['G2']} G3={r['G3']} (lost {r['lost']}, gained {r['gained']}) "
            f"G4 p={r['p']:.4f} holm={ok_holm[d]} (sessions +{r['sessions_gained']}/-{r['sessions_lost']}) "
            f"G5={r['G5']} (median ext {r['med_ext']}, share {r['share_base']:.1f}->{r['share_arm']:.1f}) "
            f"G6={r['G6']} (p90 {r['p90_base']:.0f}->{r['p90_arm']:.0f} ms){gtxt}")
        for cid, label in r["lost_cases"]:
            lines.append(f"  LOST {d}: {label} ({cid[:8]})")
        if v == "PASS":
            passed[d] = {"p": adj[d], "gain_pts": r["gain_pts"]}
    # combination: explicit --combine, else the passing decisions when more than one passes
    if combine:
        flags, parts = combine
    elif len(passed) > 1:
        flags = [d for d in ("slots", "rrf") if d in passed]
        parts = [d for d in ("task", "how", "split") if d in passed]
    else:
        flags = parts = None
    if flags is not None:
        lines += run_combination(srv, cases, pairs, gen, res, comp, flags, parts)
        if not combine:
            lines.append(f"IF-COMBINED-FAILS-SHIP: {ship_choice(passed)}")
    elif passed:
        lines.append(f"SHIP: {ship_choice(passed)}")
    return lines


def run_combination(srv, cases, pairs, gen, res, comp, flags, parts):
    """Arm C vs A0 on all cases: G2, G3, G5, G6 and the session sign test at 0.05 (no Holm: it
    confirms, it does not search). With a flag included the composite guard must hold too."""
    slots = "1" if "slots" in flags else "0"
    rrf = "1" if "rrf" in flags else "0"
    rows = {}
    for case in cases:
        q = arm_queries("C", gen, case, parts)
        if q:
            rows[case["id"]] = run_single(srv, case, q, (slots, rrf))
    ids = [c["id"] for c in cases if c["id"] in rows and c["id"] in res["A0"]]
    rl = gate_rules([res["A0"][i] for i in ids], [rows[i] for i in ids])
    tag = f"COMBINED: flags={','.join(flags) or '-'} parts={','.join(parts) or '-'}"
    if not rl["G1"]:
        return [f"{tag} INSUFFICIENT n={rl['n']}"]
    ok = rl["G2"] and rl["G3"] and rl["G5"] and rl["G6"] and rl["p"] <= ALPHA
    gtxt = ""
    if flags:
        if comp.get("A0"):
            crows = {}
            for ca, cb in pairs:
                q = composite_queries(ca, cb, gen)
                if q:
                    crows[ca["id"]] = run_composite(srv, ca, cb, q, (slots, rrf))
            g = _composite_guard(comp["A0"], crows)
            ok = ok and g["ok"]
            gtxt = f" composite-guard lower={g['lower'] if g['lower'] is None else round(g['lower'], 2)} ok={g['ok']} (pairs {g['n']})"
        else:
            ok = False
            gtxt = " composite-guard=NOT RUN (pass --composites; a flag cannot ship unguarded)"
    lines = [f"{tag} {'PASS' if ok else 'FAIL'} n={rl['n']} recall@20 {rl['base_recall']:.1f} -> {rl['arm_recall']:.1f} "
             f"(gain {rl['gain_pts']:.1f}) G2={rl['G2']} G3={rl['G3']} (lost {rl['lost']}, gained {rl['gained']}) "
             f"sign p={rl['p']:.4f} G5={rl['G5']} G6={rl['G6']}{gtxt}"]
    lines += [f"  LOST combined: {label} ({cid[:8]})" for cid, label in rl["lost_cases"]]
    return lines


# ── cli ────────────────────────────────────────────────────────────────────────────────────
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="freeze the case set and write the manifest")
    b.add_argument("--force", action="store_true", help="rebuild even if frozen (starts a new evaluation)")
    q = sub.add_parser("queries", help="generate the arm queries (append, resume, lock)")
    q.add_argument("--retry-failed", action="store_true")
    q.add_argument("--freeze", action="store_true", help="record sha256 and lock the query file")
    g = sub.add_parser("gate", help="run the arms and print verdicts")
    g.add_argument("--arms", help="comma list of A0,A1,A2,T,H,S (default all six)")
    g.add_argument("--composites", action="store_true", help="run composite pairs for A0/A1/A2")
    g.add_argument("--combine", help="FLAGS:PARTS, e.g. slots,rrf:task,how — arm C against A0")
    g.add_argument("--check-freeze", action="store_true", help="accepted for clarity; the gate always checks the freeze")
    args = ap.parse_args(argv)
    try:
        return {"build": cmd_build, "queries": cmd_queries, "gate": cmd_gate}[args.cmd](args)
    except (EngineError, RuntimeError) as e:
        print(f"ABORT: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
