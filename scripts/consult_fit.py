#!/usr/bin/env python3
"""Jev fit matrix for `consult --fast` (ADR-0076). Stdlib only.

Per sub-goal one `choice` over the candidates ranks them; a `fits` noul per candidate x sub-goal gives an
absolute floor; an `avoid` noul checks a capsule's exclusions. Plain code ranks; the agent still composes
the chain. Any failure exits non-zero and the skill falls back to inline analysis. Jev output is evidence
only, and skill text is untrusted: it lives in named state fields, never inside a question.

  echo '{"task": ..., "sub_goals": [...], "candidates": [...]}' | python3 scripts/consult_fit.py
  python3 scripts/consult_fit.py --eval [--extract-only] [--limit N]   # post-ship check (W34)

Exit: 0 ok, 2 bad input or Jev failure (JSON error on stdout), 3 disabled (SKILL_CONSULT_JEV=0).
"""
import argparse
import hashlib
import json
import math
import os
import re
import shlex
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jev_client as jc  # noqa: E402

FITS_FLOOR = 0.30            # the router's JEV_FITS_FLOOR
COVER_AT = 0.5
TEXT_CAP = 400               # JEV_RERANK_DESC
TASK_CAP = 4000
TIMEOUT, BUDGET = 2.0, 4.0
CAL_DIR = Path.home() / ".claude" / "skill-concierge" / "jev-calibration"
_STEER = re.compile(r"always (pick|choose|use|select)|ignore (all |the )?(previous|other|above)|"
                    r"you must (pick|choose|use|select)|(pick|choose|select) (me|this skill)", re.I)


def _fail(msg: str, code: int = 2):
    print(json.dumps({"ok": False, "error": msg}))
    return code


def load_input(raw: str) -> dict:
    """Validated input; ValueError on anything outside the contract."""
    try:
        d = json.loads(raw)
    except ValueError as e:
        raise ValueError("input is not JSON") from e
    if not isinstance(d, dict):
        raise ValueError("input must be an object")
    task, goals, cands = d.get("task"), d.get("sub_goals"), d.get("candidates")
    if not isinstance(task, str) or not task.strip():
        raise ValueError("task must be a non-empty string")
    if not isinstance(goals, list) or not 1 <= len(goals) <= 5 \
            or not all(isinstance(g, str) and g.strip() for g in goals):
        raise ValueError("sub_goals must be 1-5 non-empty strings")
    if not isinstance(cands, list) or not 1 <= len(cands) <= 60 \
            or not all(isinstance(c, dict) and isinstance(c.get("name"), str) and c["name"].strip()
                       for c in cands):
        raise ValueError("candidates must be 1-60 objects with a name")
    seen, uniq = set(), []
    for c in cands:
        if c["name"] not in seen:
            seen.add(c["name"])
            uniq.append(c)
    enf = jc.load_enforcer()
    return {"task": enf._jev_redact(task.strip()[:TASK_CAP]),
            "sub_goals": [enf._jev_redact(g.strip()) for g in goals], "candidates": uniq}


def _capsule(row) -> dict:
    c = row.get("capsule")
    return c if isinstance(c, dict) else {}


def _listy(v) -> list:
    return [str(x) for x in v] if isinstance(v, list) else ([str(v)] if v else [])


def candidate_text(row: dict) -> str:
    cap = _capsule(row)
    purpose = str(cap.get("purpose") or "").strip()
    if purpose:
        caps = "; ".join(_listy(cap.get("capabilities")))
        text = f"{purpose} Capabilities: {caps}" if caps else purpose
    else:
        text = str(row.get("description") or "")
    return text[:TEXT_CAP]


def build_questions(task: str, sub_goals: list, candidates: list):
    """(state, questions, labels). Candidate text sits only in state['candidate_skills']."""
    labels = [chr(65 + i) for i in range(len(sub_goals))]
    texts = {c["name"]: candidate_text(c) for c in candidates}
    avoid_when = {c["name"]: "; ".join(_listy(_capsule(c).get("avoid_when"))) for c in candidates
                  if _capsule(c).get("avoid_when")}
    state = {"task": task, "sub_goals": dict(zip(labels, sub_goals)), "candidate_skills": texts}
    if avoid_when:
        state["avoid_when"] = avoid_when
    qs = {}
    for lab, goal in zip(labels, sub_goals):
        qs[f"pick::{lab}"] = {
            "type": "choice",
            "instructions": f'Which of these skills, if any, is the right one for this part of the user\'s '
                            f'task: "{goal}"? Each skill\'s description is under candidate_skills in the state.',
            "criteria": {n: f"see candidate_skills['{n}'] in the state" for n in texts}}
    for ci, c in enumerate(candidates):
        for lab, goal in zip(labels, sub_goals):
            qs[f"fit::{ci}::{lab}"] = {
                "type": "noul",
                "instructions": f"Can the skill '{c['name']}' (described under "
                                f"candidate_skills['{c['name']}'] in the state) do this part of the "
                                f'user\'s task: "{goal}"?'}
        if c["name"] in avoid_when:
            qs[f"avoid::{ci}"] = {
                "type": "noul",
                "instructions": f"Does the user's task fall under a case where the skill '{c['name']}' "
                                f"should not be used (listed under avoid_when['{c['name']}'] in the state)?"}
    return state, qs, labels


def _prob(v) -> float:
    """A finite probability in [0, 1]; anything else is a malformed answer."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0.0 <= v <= 1.0:
        raise ValueError("malformed Jev answer")
    return float(v)


def _p(answers: dict, key: str, field: str) -> float:
    a = answers.get(key)
    if not isinstance(a, dict):
        raise ValueError("malformed Jev answer")
    return _prob(a.get(field))


def _sent_text(row: dict) -> str:
    """Every skill-derived string that leaves the machine, for the steering scan."""
    cap = _capsule(row)
    return " ".join([row["name"], str(row.get("description") or ""), str(cap.get("purpose") or ""),
                     *_listy(cap.get("capabilities")), *_listy(cap.get("avoid_when"))])


def decide(answers: dict, candidates: list, labels: list) -> list:
    rows = []
    for ci, c in enumerate(candidates):
        name = c["name"]
        pick = {}
        for lab in labels:
            probs = (answers.get(f"pick::{lab}") or {}).get("probabilities")
            if not isinstance(probs, dict):
                raise ValueError("malformed Jev answer")
            pick[lab] = _prob(probs.get(name, 0.0))
        fits = {lab: _p(answers, f"fit::{ci}::{lab}", "noul") for lab in labels}
        rank, fit_best = max(pick.values()), max(fits.values())
        avoid = _p(answers, f"avoid::{ci}", "noul") if f"avoid::{ci}" in answers else None
        ext = c.get("external")
        rows.append({
            "name": name, "pick": pick, "rank": rank, "fits": fits, "fit_best": fit_best,
            "below_floor": fit_best < FITS_FLOOR,
            "coverage": sum(1 for v in fits.values() if v >= COVER_AT),
            "avoid": avoid, "score": rank * (1 - avoid) if avoid is not None else rank,
            "installed": bool(c.get("path")) and not ext, "external": ext or None,
            "suspect": bool(_STEER.search(_sent_text(c)))})
    rows.sort(key=lambda r: (-r["score"], -r["fit_best"], r["name"]))
    return rows


def fit(inp: dict) -> dict:
    """The success output for a validated input; raises jev_client.JevError / JevTooLarge."""
    state, qs, labels = build_questions(inp["task"], inp["sub_goals"], inp["candidates"])
    answers, meta = jc.ask(state, qs, timeout=TIMEOUT, deadline=time.time() + BUDGET)
    return {"ok": True, "depth": "fast (jev)", "matrix": decide(answers, inp["candidates"], labels),
            "ms": meta["ms"], "requests": meta["requests"], "questions": len(qs),
            "via": meta["via"], "model": meta["model"]}


# --- post-ship evaluation ----------------------------------------------------------------------------

def _blocks(rec):
    c = (rec.get("message") or {}).get("content")
    return [b for b in c if isinstance(b, dict)] if isinstance(c, list) else []


def _result_rows(block):
    c = block.get("content")
    text = c if isinstance(c, str) else "".join(
        b.get("text", "") for b in c if isinstance(b, dict)) if isinstance(c, list) else ""
    try:
        d = json.loads(text)
    except ValueError:
        return None
    if isinstance(d, dict) and isinstance(d.get("result"), str):   # MCP wraps a tool's JSON as {"result": "<json>"}
        try:
            d = json.loads(d["result"])
        except ValueError:
            return None
    rows = d.get("results") if isinstance(d, dict) else None
    return [r for r in rows if isinstance(r, dict) and r.get("name")] if isinstance(rows, list) else None


def _primary(cmd: str):
    try:
        parts = shlex.split(cmd)
    except ValueError:
        return None
    for i, p in enumerate(parts):
        if p == "--primary" and i + 1 < len(parts):
            return parts[i + 1]
        if p.startswith("--primary="):
            return p.split("=", 1)[1]
    return None


def extract_runs(path: Path) -> list:
    """Closed consult runs from one top-level transcript, via the typed-text allow-list only."""
    enf = jc.load_enforcer()
    runs, task, call = [], None, None
    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if not isinstance(rec, dict) or rec.get("isSidechain"):
                continue
            text = enf._jev_typed_user_text(rec)
            if text:
                task = text
            for b in _blocks(rec):
                if rec.get("type") == "assistant" and b.get("type") == "tool_use":
                    name, inp = b.get("name") or "", b.get("input") or {}
                    if name.endswith("consult_candidates") and isinstance(inp.get("queries"), list):
                        call = {"id": b.get("id"), "task": task, "queries": inp["queries"], "rows": None}
                    elif call and call["rows"] and name == "Bash" and "consult_log.py" in str(inp.get("command")):
                        prim = _primary(str(inp.get("command")))
                        if prim and call["task"]:
                            runs.append({"task": call["task"], "queries": call["queries"],
                                         "rows": call["rows"], "primary": prim})
                            call = None
                elif rec.get("type") == "user" and b.get("type") == "tool_result" \
                        and call and b.get("tool_use_id") == call["id"]:
                    call["rows"] = _result_rows(b)
    return runs


def extract_all(projects: Path, out_dir: Path) -> list:
    runs = []
    for p in sorted(projects.glob("*/*.jsonl")):
        try:
            if "consult_candidates" not in p.read_text(encoding="utf-8", errors="replace"):
                continue
            runs += [{**r, "session": p.stem} for r in extract_runs(p)]
        except OSError:
            continue
    out_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(out_dir, 0o700)
    target = out_dir / "consult-eval.jsonl"
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in runs)
    os.chmod(target, 0o600)
    return runs


def _pctl(xs, q):
    if not xs:
        return None
    s = sorted(xs)
    return s[min(len(s) - 1, max(0, math.ceil(q * len(s)) - 1))]


def check_line(n: int, c1: int, c3: int, b1: int, b3: int, p90) -> str:
    """Pre-registered rule: INSUFFICIENT below 30 eligible runs; PASS needs choice top-1 >= baseline + 2,
    top-3 not worse, and p90 latency within 4000 ms."""
    if n < 30:
        return "CHECK: INSUFFICIENT"
    return "CHECK: PASS" if c1 >= b1 + 2 and c3 >= b3 and p90 is not None and p90 <= 4000 else "CHECK: FAIL"


def _hits(order: list, primary_key: str) -> tuple:
    keys = [jc.load_enforcer()._skill_key(n) for n in order]
    return int(keys[:1] == [primary_key]), int(primary_key in keys[:3])


def score_runs(runs: list, cache_path: Path, limit: int = None) -> dict:
    enf = jc.load_enforcer()
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    tot = {k: 0 for k in ("n", "c1", "c3", "m1", "m3", "b1", "b3", "failed")}
    lat = []
    for run in runs[:limit]:
        pk = enf._skill_key(run["primary"])
        if pk not in {enf._skill_key(r["name"]) for r in run["rows"]}:
            continue
        try:
            inp = load_input(json.dumps({"task": run["task"], "sub_goals": run["queries"][:5],
                                         "candidates": run["rows"][:60]}))
            # Key on the request actually sent, so a change to the question builder never reuses old answers.
            sent = build_questions(inp["task"], inp["sub_goals"], inp["candidates"])[:2]
            h = hashlib.sha256(json.dumps(sent, sort_keys=True).encode()).hexdigest()
            if h not in cache:
                cache[h] = fit(inp)
            res = cache[h]
        except (ValueError, jc.JevError, jc.JevTooLarge):
            tot["failed"] += 1
            continue
        m = res["matrix"]
        orders = {"c": [r["name"] for r in m],
                  "m": [r["name"] for r in sorted(m, key=lambda r: (-r["fit_best"], r["name"]))],
                  "b": [c["name"] for c in inp["candidates"]]}
        tot["n"] += 1
        lat.append(res["ms"])
        for k, order in orders.items():
            a, b = _hits(order, pk)
            tot[k + "1"] += a
            tot[k + "3"] += b
    cache_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(cache_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(cache, f)
    tot["p50"], tot["p90"] = _pctl(lat, 0.5), _pctl(lat, 0.9)
    return tot


def run_eval(args) -> int:
    projects = Path(args.projects_dir) if args.projects_dir else Path.home() / ".claude" / "projects"
    out_dir = Path(args.out_dir) if args.out_dir else CAL_DIR
    runs = extract_all(projects, out_dir)
    print(f"extracted {len(runs)} runs -> {out_dir / 'consult-eval.jsonl'}")
    if args.extract_only:
        return 0
    t = score_runs(runs, out_dir / "consult-eval-cache.json", args.limit)
    print(f"eligible n={t['n']} (jev failed: {t['failed']})")
    for label, k in (("choice", "c"), ("max-noul", "m"), ("baseline", "b")):
        print(f"  {label:9s} top-1 {t[k + '1']}/{t['n']}  top-3 {t[k + '3']}/{t['n']}")
    print(f"  latency p50 {t['p50']} ms  p90 {t['p90']} ms")
    print(check_line(t["n"], t["c1"], t["c3"], t["b1"], t["b3"], t["p90"]))
    print("Caveat: the recorded primary is a proxy label; the agent that chose it saw the sieve order "
          "(and, on the deep path, the analyst's ranking), so the baseline is favoured. "
          "Claude Code transcripts only.")
    return 0


def main(argv=None, stdin=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--in", dest="infile")
    ap.add_argument("--eval", action="store_true")
    ap.add_argument("--extract-only", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--projects-dir")
    ap.add_argument("--out-dir")
    args = ap.parse_args(argv)
    if os.environ.get("SKILL_CONSULT_JEV", "1") == "0":
        return _fail("disabled (SKILL_CONSULT_JEV=0)", 3)
    if args.eval:
        return run_eval(args)
    try:
        raw = Path(args.infile).read_text(encoding="utf-8") if args.infile else (stdin or sys.stdin).read()
        out = fit(load_input(raw))
    except jc.JevTooLarge:            # a ValueError subclass: must be caught before ValueError
        return _fail("JevTooLarge")
    except jc.JevError as e:
        return _fail(str(e) or type(e).__name__)
    except (OSError, ValueError) as e:
        return _fail(str(e) if isinstance(e, ValueError) else type(e).__name__)
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
