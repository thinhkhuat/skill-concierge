#!/usr/bin/env python3
"""Jev sibling-margin filter for flywheel utterances (ADR-0076). Stdlib only.

A generated utterance (a short phrase a user might type when they need a skill) is worth indexing
only if it points at its own skill more than at the skill's nearest neighbours. For each skill one
Jev request carries the skill and its 3 nearest INSTALLED siblings and asks, per utterance and per
skill, a `noul`: would a user who types this be asking for what that skill does?
`margin = p(own) - max(p(sibling))`. Code drops a phrase whose margin is below a threshold measured
for the model that answered. Nothing is lost: dropped phrases, scores and the answering model stay in
`triggers.json` under `llm_triggers.jev`.

Thresholds are keyed by the EXACT model id Jev returned (`jev-1.13.0`, `typesafe/jev-1.13-20260917`,
`jev-1.13-free`): a new dated snapshot is a different model, so it gets no threshold until it is
calibrated; its scores are stored as `pending` and its phrases are kept.

  python3 scripts/trigger_filter.py calibrate --out-dir DIR   # per-model thresholds into a staging dir
  python3 scripts/trigger_filter.py backfill [--out PATH] [--thresholds PATH] [--limit N] [--dry-run]
  python3 scripts/trigger_filter.py reindex                   # CLI reindex + corpus_epoch event
  python3 scripts/trigger_filter.py report [--file PATH]      # accounting of kept / dropped / pending
  python3 scripts/trigger_filter.py --selftest

The filter runs inside `llm_triggers.run` only while SKILL_TRIGGER_JEV_FILTER != 0 AND the live
thresholds file exists (an absent file keeps it inert). Offline Jev calls go through scripts/jev_client.py.
"""
import argparse
import bisect
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import flywheel_llm  # noqa: E402
import flywheel_lock  # noqa: E402
import jev_client  # noqa: E402
import llm_triggers  # noqa: E402

HOME = Path(os.environ.get("SKILL_CONCIERGE_HOME", Path.home() / ".claude" / "skill-concierge"))
CACHE_FILE = HOME / "trigger-jev-cache.jsonl"
THRESHOLDS_FILE = Path(os.environ.get("SKILL_TRIGGER_THRESHOLDS", HOME / "trigger-jev-thresholds.json"))
CAPSULES_FILE = Path(os.environ.get("SKILL_CAPSULES", HOME / "capsules.json"))
BACKUP_DIR = HOME / "backups"
LEDGER = Path(os.environ.get("SKILL_CONCIERGE_LOG", HOME / "logs")) / "skill-invocation-ledger.log"

DESC_CUT = 600
N_SIBLINGS = 3
SAVE_EVERY = 50
CAL_SEED = "20261003"
CAL_SKILLS = 300
CAL_CANDIDATES = (-0.2, -0.1, 0.0, 0.1)
CAL_DROP_CAP = 0.15
CAL_MIN_AUC = 0.75
CAL_MIN_N = 500
SAIGON = timezone(timedelta(hours=7))

# Scoring is advisory: whatever goes wrong (Jev, the embedder, a malformed answer) keeps every phrase.
SCORE_ERRORS = (Exception,)


class NoSiblings(ValueError):
    pass


def now_iso():
    return datetime.now(SAIGON).isoformat(timespec="seconds")


def lang(phrase):
    """`vn` when the phrase has a non-ASCII character (the repo's proxy, llm_triggers.vn_count), else `en`."""
    return "vn" if any(ord(c) > 127 for c in phrase) else "en"


def flag_on():
    return os.environ.get("SKILL_TRIGGER_JEV_FILTER", "1") != "0"


def load_thresholds(path=None):
    """The `models` map of the thresholds file, or None when it is absent or unreadable (filter inert)."""
    try:
        data = json.loads(Path(THRESHOLDS_FILE if path is None else path).read_text(encoding="utf-8"))
        models = data["models"]
        return models if isinstance(models, dict) else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def active():
    return flag_on() and load_thresholds() is not None


def load_capsules():
    try:
        data = json.loads(CAPSULES_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


# --- score cache -------------------------------------------------------------------------------------

class Cache:
    """Append-only JSONL, one row per (utterance key, answering model). Readers take any model's row,
    preferring one that has a threshold; only the main thread adds."""

    def __init__(self, path=None):
        self.path = Path(CACHE_FILE if path is None else path)
        self.rows = {}
        self.lock = threading.Lock()
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                try:
                    r = json.loads(line)
                    self.rows.setdefault(r["k"], {})[r["model"]] = r
                except (ValueError, KeyError, TypeError):
                    continue
        except OSError:
            pass

    def get(self, k, thresholds):
        by_model = self.rows.get(k)
        if not by_model:
            return None
        for model, r in by_model.items():
            if model in thresholds:
                return r
        return next(iter(by_model.values()))

    def add_many(self, rows):
        if not rows:
            return
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                for r in rows:
                    self.rows.setdefault(r["k"], {})[r["model"]] = r
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")


class Ctx:
    """What a scoring run needs: installed skills {name: description}, capsules, cache, thresholds."""

    def __init__(self, installed, cache=None, thresholds=None, capsules=None):
        self.installed = installed
        self.cache = cache if cache is not None else Cache()
        self.thresholds = thresholds if thresholds is not None else (load_thresholds() or {})
        self.capsules = capsules if capsules is not None else load_capsules()


# --- scoring -----------------------------------------------------------------------------------------

_TIMEOUTS_SET = set()
_TIMEOUT_LOCK = threading.Lock()


def _enforcer():
    """The enforcer via jev_client (which scopes its own log env and caches the module under its own lock),
    with offline-length retrieval timeouts set on the loaded module object, never in os.environ: an
    explicit ENFORCER_*_TIMEOUT from the caller still wins."""
    enf = jev_client.load_enforcer()
    with _TIMEOUT_LOCK:
        if id(enf) not in _TIMEOUTS_SET:
            for var, attr in (("ENFORCER_EMBED_TIMEOUT", "EMBED_TIMEOUT_S"),
                              ("ENFORCER_QDRANT_TIMEOUT", "QDRANT_TIMEOUT_S")):
                if var not in os.environ:
                    setattr(enf, attr, 15.0)
            _TIMEOUTS_SET.add(id(enf))
    return enf


SIBLING_FETCH = 12


def siblings(enf, name, description, installed):
    """Up to 3 nearest INSTALLED skills to `name`: [(name, description)]. The same grouped query the
    enforcer's `_retrieve` sends, minus its per-session invocability filter (`_row_invocable`: project
    isolation, harness, plugin gate), which depends on the calling process's cwd and harness — a detached
    auto-flywheel and a manual backfill would pick different siblings, change the state and miss the cache.
    The candidate set is `installed` (live_skills: every non-external, non-synced indexed skill), so the
    choice is the same from any process. A row that is not a known installed skill (an external catalog
    point, a stale name) is never used."""
    res = enf._post_json(enf.QUERY_GROUPS_URL,
                         {"query": enf._embed(description[:2000]), "group_by": "name",
                          "limit": SIBLING_FETCH, "group_size": 1, "with_payload": ["name"],
                          "filter": {"must_not": [{"key": "tier", "match": {"value": "external"}}]}},
                         enf.QDRANT_TIMEOUT_S)
    out = []
    for g in res.get("result", {}).get("groups", []):
        hits = g.get("hits") or []
        n = ((hits[0].get("payload") or {}).get("name") if hits else None) or g.get("id")
        if n and n != name and n in installed and n not in {o[0] for o in out}:
            out.append((n, installed[n]))
        if len(out) == N_SIBLINGS:
            break
    return out


def state_for(entries, capsules):
    """{"skills": {name: {"description", ["purpose"]}}} for [(name, description)], own skill first."""
    skills = {}
    for name, desc in entries:
        item = {"description": (desc or "")[:DESC_CUT]}
        purpose = (capsules.get(name) or {}).get("purpose")
        if purpose:
            item["purpose"] = purpose
        skills[name] = item
    return {"skills": skills}


def questions_for(indexed_phrases, names):
    """One `noul` per phrase and skill; key `u::<i>::<j>` (j = 0 own, 1.. siblings, then the random one)."""
    qs = {}
    for i, u in indexed_phrases:
        for j, x in enumerate(names):
            qs[f"u::{i}::{j}"] = {"type": "noul", "instructions": (
                f'Would a user who types "{u}" to a coding assistant be asking for what the skill '
                f"'{x}' does (described under skills['{x}'] in the state)?")}
    return qs


def cache_key(state, phrase):
    return hashlib.sha256((json.dumps(state, sort_keys=True, ensure_ascii=False) + "\0" + phrase)
                          .encode("utf-8")).hexdigest()[:20]


def _p(answer):
    p = float(answer["noul"])
    if not 0.0 <= p <= 1.0:
        raise ValueError("noul out of range")
    return p


def score_skill(entries, phrases, ctx, tiers=None, workers=4, timeout=10.0, control=False):
    """Score `phrases` of entries[0] against its siblings (entries[1:]; with `control=True` the LAST entry is
    the calibration control, reported as `p_rand` and never a sibling). Returns (rows, new_rows, meta);
    rows[i] = {"k","model","p_own","p_sib","margin"[,"p_rand"]}, margin against the real siblings only.
    Cached rows are reused; only uncached phrases are asked. Raises on any Jev failure (no partial rows),
    and NoSiblings when there is no real sibling to measure against."""
    n_sib = len(entries) - 1 - (1 if control else 0)
    if n_sib < 1:
        raise NoSiblings(entries[0][0])
    state = state_for(entries, ctx.capsules)
    names = [e[0] for e in entries]
    keys = [cache_key(state, u) for u in phrases]
    rows, todo = [None] * len(phrases), []
    for i, k in enumerate(keys):
        row = ctx.cache.get(k, ctx.thresholds)
        if row is not None:
            rows[i] = row
        else:
            todo.append(i)
    new, meta = [], {"requests": 0, "tokens": 0}
    if todo:
        qs = questions_for([(i, phrases[i]) for i in todo], names)
        answers, m = jev_client.ask(state, qs, timeout=timeout, deadline=time.time() + 60, tiers=tiers,
                                    workers=workers)
        meta["requests"] = m["requests"]
        meta["tokens"] = _enforcer()._jev_tokens(json.dumps({"state": state, "questions": qs}))
        for i in todo:
            ps = [_p(answers[f"u::{i}::{j}"]) for j in range(len(names))]
            models = sorted({str(m["per_key_model"][f"u::{i}::{j}"]) for j in range(len(names))})
            # an utterance whose questions straddled two answering models has no single threshold
            row = {"k": keys[i], "model": "+".join(models), "p_own": ps[0],
                   "p_sib": ps[1:1 + n_sib], "margin": ps[0] - max(ps[1:1 + n_sib])}
            if control:
                row["p_rand"] = ps[-1]
            new.append(row)
            rows[i] = row
    return rows, new, meta


# --- decision (pure) ---------------------------------------------------------------------------------

def _decide(phrases, scores, thresholds):
    kept_i, dropped, pending = [], [], 0
    for i, (u, s) in enumerate(zip(phrases, scores)):
        if s is None:
            kept_i.append(i)
            continue
        entry = (thresholds.get(s["model"]) or {}).get(lang(u))
        if entry is None:
            pending += 1
            kept_i.append(i)
        elif not entry.get("gate", True) or entry.get("threshold") is None or s["margin"] >= entry["threshold"]:
            kept_i.append(i)
        else:
            dropped.append({"t": u, "p": s["p_own"], "margin": s["margin"], "model": s["model"], "i": i,
                            "why": "jev"})
    restored = 0
    if len(kept_i) < llm_triggers.MIN_TRIGGERS and dropped:
        dropped.sort(key=lambda d: -d["margin"])
        while dropped and len(kept_i) < llm_triggers.MIN_TRIGGERS:
            kept_i.append(dropped.pop(0)["i"])
            restored += 1
    kept_i.sort()
    dropped.sort(key=lambda d: d["i"])
    return [phrases[i] for i in kept_i], dropped, pending, restored


def decide(phrases, scores, thresholds):
    """(kept, dropped, pending). `scores[i]` is a score row or None (unscored: kept). `thresholds` is the
    `models` map {model: {lang: {"threshold", "gate"}}}. A model with no entry for the phrase's language
    is pending (kept); a `gate: false` entry is scored but exempt; at least MIN_TRIGGERS phrases stay,
    restored best margin first."""
    return _decide(phrases, scores, thresholds)[:3]


def make_audit(phrases, scores, thresholds, dropped, pending, restored):
    seen = sorted({s["model"] for s in scores if s})
    audit = {"models": seen,
             "thresholds": {m: {lg: (thresholds.get(m) or {}).get(lg, {}).get("threshold")
                                for lg in ("en", "vn")} for m in seen if m in thresholds},
             "scored": sum(1 for s in scores if s), "pending": pending, "dropped": dropped,
             "at": now_iso()}
    if restored:
        audit["restored"] = restored
    return audit


def filter_phrases(name, description, phrases, ctx):
    """Score and decide one skill's phrases. Never raises: on any error every phrase is kept and the
    audit is `{"err": "<ExceptionClass>"}`. Returns {"kept","audit","new_rows","scores","requests","tokens"}."""
    try:
        sibs = siblings(_enforcer(), name, description, ctx.installed)
        if not sibs:
            raise NoSiblings(name)
        rows, new, meta = score_skill([(name, description)] + sibs, phrases, ctx)
    except SCORE_ERRORS as e:
        return {"kept": list(phrases), "audit": {"err": type(e).__name__, "at": now_iso(), "dropped": []},
                "new_rows": [], "scores": [None] * len(phrases), "requests": 0, "tokens": 0}
    kept, dropped, pending, restored = _decide(phrases, rows, ctx.thresholds)
    return {"kept": kept, "audit": make_audit(phrases, rows, ctx.thresholds, dropped, pending, restored),
            "new_rows": new, "scores": rows, "requests": meta["requests"], "tokens": meta["tokens"]}


# --- statistics (calibration) ------------------------------------------------------------------------

def auc(pos, neg):
    """P(pos > neg) over all pairs, ties half (Mann-Whitney U / (n*m)). None when either side is empty."""
    if not pos or not neg:
        return None
    srt = sorted(neg)
    # below + ties/2 == (below + below-or-equal) / 2
    wins = sum(bisect.bisect_left(srt, p) + bisect.bisect_right(srt, p) for p in pos) / 2
    return wins / (len(pos) * len(neg))


def percentile(sorted_vals, q):
    if not sorted_vals:
        return None
    return sorted_vals[min(len(sorted_vals) - 1, max(0, int(round(q * (len(sorted_vals) - 1)))))]


def calibrate_group(rows):
    """Measurement for one (model, language) group of rows {p_own, p_sib, margin[, p_rand]}."""
    n = len(rows)
    margins = sorted(r["margin"] for r in rows)
    a_sib = auc([r["p_own"] for r in rows], [max(r["p_sib"]) for r in rows])
    rand = [r["p_rand"] for r in rows if "p_rand" in r]
    a_rand = auc([r["p_own"] for r in rows if "p_rand" in r], rand)
    drop = {str(t): (sum(1 for m in margins if m < t) / n if n else None) for t in CAL_CANDIDATES}
    ok = [t for t in CAL_CANDIDATES if n and drop[str(t)] <= CAL_DROP_CAP]
    threshold = max(ok) if ok else None
    gate = bool(threshold is not None and a_sib is not None and a_sib >= CAL_MIN_AUC and n >= CAL_MIN_N)
    return {"threshold": threshold, "auc_sib": a_sib, "auc_rand": a_rand, "drop": drop, "n": n, "gate": gate,
            "margin_p10": percentile(margins, 0.1), "margin_p50": percentile(margins, 0.5),
            "margin_p90": percentile(margins, 0.9)}


def calibrate(out_dir, n_skills=CAL_SKILLS, seed=CAL_SEED, workers=4):
    enf = _enforcer()
    installed = flywheel_llm.live_skills()
    corpus = llm_triggers.load_triggers()
    capsules = load_capsules()
    have = [n for n in installed if (corpus.get(n, {}).get("llm_triggers") or {}).get("triggers")]
    sample = sorted(have, key=lambda n: hashlib.sha256((seed + n).encode()).hexdigest())[:n_skills]
    plan = []
    for name in sample:
        try:
            sibs = siblings(enf, name, installed[name], installed)
        except Exception as e:  # noqa: BLE001 — one unlucky lookup must not end the calibration
            print(f"skip {name}: sibling lookup {type(e).__name__}")
            continue
        if not sibs:
            continue
        taken = {name, *[s[0] for s in sibs]}
        pool = sorted(n for n in installed if n not in taken)
        rnd = random.Random(f"{seed}:{name}").choice(pool)
        plan.append((name, [(name, installed[name])] + sibs + [(rnd, installed[rnd])],
                     corpus[name]["llm_triggers"]["triggers"]))
    # An empty cache that is never written: a calibration state carries the control skill, so its keys
    # would never match a backfill state anyway.
    ctx = Ctx(installed, cache=Cache(Path(os.devnull)), thresholds={}, capsules=capsules)
    by_model, failed = {}, {}
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = out_dir / "calibration-rows.jsonl"
    raw.write_text("", encoding="utf-8")
    for tier in enf._jev_bench():
        label = f"{tier['ep']}:{tier['model']}"
        if not enf._jev_key(tier):
            print(f"tier {label}: no key, skipped")
            continue

        def one(item, tier=tier):
            name, entries, phrases = item
            return name, phrases, score_skill(entries, phrases, ctx, tiers=[tier], workers=1, control=True)

        done = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = [pool.submit(one, it) for it in plan]
            for fut in as_completed(futs):
                try:
                    name, phrases, (rows, _new, _meta) = fut.result()
                except Exception as e:  # noqa: BLE001
                    failed[label] = failed.get(label, 0) + 1
                    print(f"tier {label}: skill failed ({type(e).__name__})")
                    continue
                done += 1
                with raw.open("a", encoding="utf-8") as f:
                    for u, r in zip(phrases, rows):
                        by_model.setdefault(r["model"], {}).setdefault(lang(u), []).append(r)
                        f.write(json.dumps({**r, "name": name, "lang": lang(u)}, ensure_ascii=False) + "\n")
        print(f"tier {label}: {done}/{len(plan)} skills scored")
    models = {m: {lg: calibrate_group(rows) for lg, rows in langs.items()} for m, langs in by_model.items()}
    result = {"seed": seed, "n_skills": len(plan), "measured_at": now_iso(), "models": models}
    (out_dir / "trigger-jev-thresholds.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"{'model':32} {'lang':4} {'n':>6} {'auc_sib':>8} {'auc_rand':>8} {'thr':>6} {'drop@thr':>8} gate")
    fmt = lambda v, w, d=3: f"{v:>{w}.{d}f}" if isinstance(v, float) else f"{str(v):>{w}}"  # noqa: E731
    for m, langs in sorted(models.items()):
        for lg, g in sorted(langs.items()):
            dr = g["drop"].get(str(g["threshold"])) if g["threshold"] is not None else None
            print(f"{m:32} {lg:4} {g['n']:>6} {fmt(g['auc_sib'], 8)} {fmt(g['auc_rand'], 8)} "
                  f"{fmt(g['threshold'], 6, 2)} {fmt(dr, 8)} {g['gate']}")
    print(f"wrote {out_dir / 'trigger-jev-thresholds.json'}")
    return 0


# --- backfill ----------------------------------------------------------------------------------------

def original_phrases(entry):
    """The phrase list as it stood before filtering: kept + dropped, in original order."""
    layer = entry.get("llm_triggers") or {}
    kept = list(layer.get("triggers") or [])
    dropped = (layer.get("jev") or {}).get("dropped") or []
    total = len(kept) + len(dropped)
    out, ki = [None] * total, iter(kept)
    try:
        for d in dropped:
            if out[d["i"]] is not None or not isinstance(d["i"], int) or d["i"] < 0:
                raise ValueError("duplicate or negative index")
            out[d["i"]] = d["t"]
        return [p if p is not None else next(ki) for p in out]
    except (KeyError, IndexError, TypeError, StopIteration, ValueError) as e:
        raise ValueError(f"inconsistent jev audit ({type(e).__name__})") from None


def needs_backfill(entry, rescore=False):
    layer = entry.get("llm_triggers") if isinstance(entry, dict) else None
    if not isinstance(layer, dict) or not layer.get("triggers"):
        return False
    jev = layer.get("jev")
    return bool(rescore or not jev or "err" in jev or jev.get("pending", 0) > 0)


def _read_json(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except OSError:
        return {}


def _save_changes(path, source, changed):
    """Re-read `path` and apply only this run's per-skill changes, so an entry another writer changed
    meanwhile survives. Atomic. A target that is missing, unreadable or not a JSON object raises
    (OSError/ValueError) and nothing is written: writing only `changed` would erase every other skill.
    The one exception is a first save into a NEW `--out` copy, which starts from `source`."""
    path, source = Path(path), Path(source)
    base = path if path.exists() or path.resolve() == source.resolve() else source
    data = json.loads(base.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{base} is not a JSON object")
    data.update(changed)
    llm_triggers.save_triggers(data, path)


def ledger_event(row):
    try:
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with LEDGER.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"t": round(time.time(), 3), "ev": "corpus_epoch", **row}, ensure_ascii=False) + "\n")
        return True
    except Exception:  # noqa: BLE001, S110 (fail-silent telemetry boundary)
        return False


def all_descriptions():
    """{name: description} for installed skills plus every configured catalog alias."""
    import build_triggers
    import catalogs
    out = {}
    for alias in catalogs._configured_roots(catalogs._load()):
        for n, d in build_triggers.scroll_all_points(catalog=alias):
            if n and n not in out:
                out[n] = d or ""
    installed = flywheel_llm.live_skills()
    out.update(installed)
    return out, installed


def backfill(args):
    source = Path(llm_triggers.TRIGGERS_FILE)
    live = Path(args.out).resolve() == source.resolve() if args.out else True
    out_path = Path(args.out) if args.out else source
    thresholds = load_thresholds(args.thresholds)
    if thresholds is None:
        print("FAIL: no readable thresholds file — run `calibrate` first (or pass --thresholds)", file=sys.stderr)
        return 2
    if not args.dry_run and not flywheel_lock.acquire(block=False):
        print(f"SKIP: flywheel already running — another run holds {flywheel_lock.LOCK_PATH}", file=sys.stderr)
        return 4
    try:
        return _backfill(args, source, out_path, live, thresholds)
    finally:
        if not args.dry_run:
            flywheel_lock.release()


def _backfill(args, source, out_path, live, thresholds):
    triggers = _read_json(source)
    descs, installed = all_descriptions()
    cap = int(_engine_cap() or 12)
    selected = sorted(n for n, e in triggers.items() if needs_backfill(e, args.rescore))
    if args.limit:
        selected = selected[:args.limit]
    skipped = [n for n in selected if n not in descs]
    selected = [n for n in selected if n in descs]
    originals, inconsistent = {}, []
    for n in selected:
        try:
            originals[n] = original_phrases(triggers[n])
        except ValueError:
            inconsistent.append(n)      # a damaged audit: skip this skill, never abort the run
    selected = [n for n in selected if n in originals]
    print(f"selected {len(selected)} skills ({len(skipped)} skipped: no live description; "
          f"{len(inconsistent)} skipped: inconsistent audit)")
    if args.dry_run:
        print("[dry-run] no requests sent, nothing written.")
        return 0
    ctx = Ctx(installed, thresholds=thresholds)
    backup = None
    stats = {"scored": 0, "failed": 0, "pending_skills": 0, "guard": 0, "requests": 0, "tokens": 0,
             "phrases": {}}
    changed, since_save = {}, 0

    def work(name):
        orig = originals[name]
        return name, orig, filter_phrases(name, descs[name], orig, ctx)

    def flush():
        nonlocal backup, changed
        if not changed:
            return
        if live and backup is None:
            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            backup = BACKUP_DIR / f"triggers-{datetime.now(SAIGON).strftime('%y%m%d-%H%M')}.json"
            shutil.copy2(source, backup)
        _save_changes(out_path, source, changed)
        changed = {}

    save_error = None
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futs = [pool.submit(work, n) for n in selected]
        for fut in as_completed(futs):
            if save_error:
                break
            name, orig, res = fut.result()
            audit = res["audit"]
            stats["requests"] += res["requests"]
            stats["tokens"] += res["tokens"]
            if "err" in audit:
                stats["failed"] += 1
                if (triggers[name].get("llm_triggers") or {}).get("jev"):
                    continue            # keep the audit this skill already has
            else:
                stats["scored"] += 1
                stats["pending_skills"] += 1 if audit["pending"] else 0
                stats["guard"] += 1 if audit.get("restored") else 0
                kept_set = set(res["kept"])
                for u, s in zip(orig, res["scores"]):
                    if s:
                        bucket = stats["phrases"].setdefault((s["model"], lang(u)), [0, 0])
                        bucket[0 if u in kept_set else 1] += 1
            ctx.cache.add_many(res["new_rows"])
            llm_triggers.merge_utterance_layer(triggers, name, res["kept"], cap=cap, audit=audit, orig=orig)
            changed[name] = triggers[name]
            since_save += 1
            if since_save >= SAVE_EVERY:
                try:
                    flush()
                except (OSError, ValueError) as e:
                    save_error = e
                    for f in futs:
                        f.cancel()
                since_save = 0
    if not save_error:
        try:
            flush()
        except (OSError, ValueError) as e:
            save_error = e
    if save_error:
        print(f"FAIL: save aborted ({type(save_error).__name__}: {save_error}); nothing partial was written. "
              f"{len(changed)} scored skills are unsaved; their scores are in the cache, so a re-run "
              f"resumes without new requests.", file=sys.stderr)
        return 3
    kept_n = sum(v[0] for v in stats["phrases"].values())
    drop_n = sum(v[1] for v in stats["phrases"].values())
    print(f"scored {stats['scored']}  skipped {len(skipped)}  failed(err) {stats['failed']}  "
          f"pending skills {stats['pending_skills']}  at MIN_TRIGGERS guard {stats['guard']}  "
          f"inconsistent audit {len(inconsistent)}")
    for (model, lg), (k, d) in sorted(stats["phrases"].items()):
        print(f"  {model:32} {lg}  kept {k}  dropped {d}")
    print(f"requests {stats['requests']}  est. input tokens {stats['tokens']}")
    if live:
        pend = sum((triggers[n]["llm_triggers"].get("jev") or {}).get("pending", 0) for n in selected
                   if n in triggers)
        ledger_event({"what": "trigger_filter_backfill", "backup": str(backup) if backup else None,
                      "kept": kept_n, "dropped": drop_n, "pending": pend})
    return 0


def _engine_cap():
    import engine_env
    return engine_env.engine_env().get("TRIGGERS_MAX")


# --- reindex / report --------------------------------------------------------------------------------

def reindex():
    ss_bin = Path(os.environ.get("SKILL_CONCIERGE_VENV", HOME / "venv")) / "bin" / "skill-search"
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "engine_env.py"), "--exec", str(ss_bin),
                        "--reindex"], capture_output=True, text=True)
    print(r.stdout.strip())
    if r.returncode != 0:
        print(r.stderr.strip(), file=sys.stderr)
        return r.returncode
    try:
        res = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        res = {}
    ledger_event({"what": "reindex", "embedded": res.get("embedded"), "deleted": res.get("deleted")})
    return 0


def report(path=None):
    data = _read_json(path or llm_triggers.TRIGGERS_FILE)
    c = {"entries": 0, "no_jev": 0, "err": 0, "pending_entries": 0, "ok": 0, "inconsistent": 0,
         "kept": 0, "pending": 0, "jev": 0, "cap": 0}
    by_model = {}
    for entry in data.values():
        layer = entry.get("llm_triggers") if isinstance(entry, dict) else None
        if not isinstance(layer, dict) or not layer.get("triggers"):
            continue
        c["entries"] += 1
        jev = layer.get("jev")
        if not jev:
            c["no_jev"] += 1
            continue
        dropped = jev.get("dropped") or []
        idx = [d.get("i") for d in dropped]
        total = len(layer["triggers"]) + len(dropped)
        if len(set(idx)) != len(idx) or any(not isinstance(i, int) or not 0 <= i < total for i in idx):
            c["inconsistent"] += 1
        if "err" in jev:
            c["err"] += 1
        elif jev.get("pending", 0) > 0:
            c["pending_entries"] += 1
        else:
            c["ok"] += 1
        c["kept"] += len(layer["triggers"])
        c["pending"] += jev.get("pending", 0)
        for d in dropped:
            c[d.get("why", "jev")] = c.get(d.get("why", "jev"), 0) + 1
            if d.get("why") == "jev":
                by_model[d.get("model")] = by_model.get(d.get("model"), 0) + 1
    print(f"entries with utterances {c['entries']}: scored ok {c['ok']}, pending {c['pending_entries']}, "
          f"err {c['err']}, not yet scored {c['no_jev']}, inconsistent audit {c['inconsistent']}")
    print(f"phrases on scored entries: kept {c['kept']} (of which pending/uncalibrated {c['pending']}), "
          f"dropped by jev {c['jev']}, dropped by cap {c['cap']}")
    for m, n in sorted(by_model.items(), key=lambda x: str(x[0])):
        print(f"  jev drops by {m}: {n}")
    return 0


def _selftest():
    assert auc([1, 2, 3], [0, 0.5]) == 1.0 and auc([1], [1]) == 0.5
    k, d, p = decide(["alpha one", "beta two", "gamma three", "delta four", "epsilon five"],
                     [{"model": "m", "p_own": 0.9, "margin": 0.5}] * 5, {"m": {"en": {"threshold": 0.0}}})
    assert len(k) == 5 and not d and not p
    print("PASS")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--selftest", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    c = sub.add_parser("calibrate")
    c.add_argument("--out-dir", required=True)
    c.add_argument("--skills", type=int, default=CAL_SKILLS)
    c.add_argument("--workers", type=int, default=4)
    b = sub.add_parser("backfill")
    b.add_argument("--workers", type=int, default=4)
    b.add_argument("--limit", type=int, default=None)
    b.add_argument("--out", default=None)
    b.add_argument("--dry-run", action="store_true")
    b.add_argument("--rescore", action="store_true")
    b.add_argument("--thresholds", default=None)
    sub.add_parser("reindex")
    r = sub.add_parser("report")
    r.add_argument("--file", default=None)
    args = ap.parse_args(argv)
    if args.selftest:
        return _selftest()
    if args.cmd == "calibrate":
        return calibrate(args.out_dir, n_skills=args.skills, workers=args.workers)
    if args.cmd == "backfill":
        return backfill(args)
    if args.cmd == "reindex":
        return reindex()
    if args.cmd == "report":
        return report(args.file)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
