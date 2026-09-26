#!/usr/bin/env python3
"""Copy the live Qdrant index into a STAGING index owner and prove search parity.

  1. Start a staging owner from this checkout's engine source on 127.0.0.1:6433
     (Qdrant-compatible subset) and :6463 (embed), SQLite file SKILL_INDEX_DB
     (default ~/.cache/skill-search/index-staging.sqlite). An owner already
     answering on 6433 is reused, never duplicated.
  2. Digest live Qdrant (point count + sorted content_hash per collection).
  3. Scroll claude_skills and prompt_intent from live Qdrant (read-only) with
     vectors and payloads, load them into the staging owner, then read every point
     back and compare the float32 bytes and payloads with the live copy.
  4. Parity replay: the last 500 human prompts of the invocation ledger (harness
     and orchestrator traffic excluded) plus a fixed 40-prompt EN/VN set, each
     embedded once through the staging owner's /embed. Every prompt is sent in the
     enforcer's four request shapes plus search_skills' should/is_null scope filter
     to live Qdrant with params.exact=true and to the staging owner.
     Pass: same names (point ids for prompt_intent), scores within 1e-4, groups of
     exactly tied live scores compared as sets.
  5. Digest live Qdrant again; if it changed while we worked, say so and rerun.

Exit 0 on full parity, 1 otherwise; one stderr line per mismatch:
  query=<q> rank=<n> live=<name>:<score> owner=<name>:<score>
`--load` instead runs `skill-search --reindex --force` from this checkout
against the staging owner while a sequential loop sends the enforcer's query/groups
requests; exit 0 when their p99 < 250 ms, otherwise exit 1 and print
p50=… p95=… p99=… n=… to stderr.
Live Qdrant is only ever read. The staging owner keeps running with
--keep-running (for the caller sweep and the load test); `--stop` stops it.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ENGINE_SRC = REPO / "vendor" / "skill-search"
LIVE = os.environ.get("MIGRATE_LIVE_URL", "http://127.0.0.1:6333")
QPORT, EPORT = 6433, 6463
STAGING = f"http://127.0.0.1:{QPORT}"
EMBED = f"http://127.0.0.1:{EPORT}"
DB = Path(os.environ.get("SKILL_INDEX_DB")
          or "~/.cache/skill-search/index-staging.sqlite").expanduser()
PIDFILE = Path(f"{DB}.pid")
OWNER_LOG = Path(f"{DB}.log")
LEDGER = Path("~/.claude/skill-concierge/logs/skill-invocation-ledger.log").expanduser()
COLLECTIONS = ("claude_skills", "prompt_intent")
TOL = 1e-4
N_LEDGER = 500
MAX_RERUNS = 3

FIXED_PROMPTS = [
    # English
    "fix the failing pytest in the auth module",
    "write a conventional commit message for these changes",
    "review this pull request for security issues",
    "set up a postgres schema migration",
    "deploy the app to the vps with docker",
    "debug why the api returns 500 on login",
    "create a new claude code skill for release notes",
    "summarize this research paper on vector search",
    "draft a README for this repository",
    "build a react dashboard with charts",
    "refactor this module to remove duplication",
    "research the latest qdrant release notes",
    "make a slide deck for the quarterly review",
    "write unit tests for the parser",
    "audit the website for accessibility problems",
    "plan the implementation of a payment integration",
    "convert this markdown file to a word document",
    "explain how this codebase is organized",
    "scrape product prices from this website",
    "hello, how are you today?",
    # Vietnamese
    "sửa lỗi test đang fail trong module đăng nhập",
    "viết báo cáo thông tin về dư luận tuần này",
    "dịch đoạn tài liệu này sang tiếng Việt",
    "tạo slide thuyết trình cho cuộc họp quý",
    "kiểm tra bảo mật cho đoạn code này",
    "triển khai ứng dụng lên máy chủ bằng docker",
    "viết bài blog về lợi ích của làm việc từ xa",
    "gỡ giọng AI trong đoạn văn này",
    "lập kế hoạch triển khai tính năng thanh toán",
    "phân tích dữ liệu bán hàng trong file excel",
    "tóm tắt tin tức trong nước hôm nay",
    "tạo tài liệu word theo chuẩn văn bản hành chính",
    "rà soát và hoàn thiện văn bản đề án này",
    "tìm kiếm thông tin về chính sách mới",
    "thiết kế giao diện trang chủ cho website",
    "viết commit cho các thay đổi này",
    "chào bạn, hôm nay thế nào?",
    "giải thích cách hoạt động của hệ thống này",
    "cập nhật tài liệu hướng dẫn cài đặt",
    "nghiên cứu thị trường xe điện Việt Nam",
]


# ---------------------------------------------------------------------------
# HTTP

def http(url: str, method: str = "GET", body=None, timeout: float = 60.0):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method)
    if method != "GET":
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


def answers(url: str) -> dict | None:
    try:
        return http(url + "/", timeout=1.0)
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Staging owner lifecycle

def start_owner() -> None:
    info = answers(STAGING)
    if info and "index owner" in str(info.get("title", "")):
        print(f"staging owner already running on :{QPORT} (reused)")
    elif info is not None:
        sys.exit(f"port {QPORT} is held by something that is not an index owner: {info}")
    else:
        py = Path("~/.claude/skill-concierge/venv/bin/python").expanduser()
        env = dict(os.environ, PYTHONPATH=str(ENGINE_SRC), SKILL_INDEX_DB=str(DB),
                   SKILL_OWNER_QUERY_PORT=str(QPORT), SKILL_OWNER_EMBED_PORT=str(EPORT),
                   SKILL_OWNER_LOG=str(OWNER_LOG),
                   SKILL_OWNER_STAMP=str(Path(f"{DB}.stamp")))
        DB.parent.mkdir(parents=True, exist_ok=True)
        with open(OWNER_LOG, "a") as logf:
            proc = subprocess.Popen([str(py if py.exists() else sys.executable),
                                     "-m", "skill_search.index_owner"],
                                    env=env, stdout=logf, stderr=logf,
                                    start_new_session=True, cwd=str(REPO))
        PIDFILE.write_text(str(proc.pid))
        print(f"staging owner started pid={proc.pid} query=:{QPORT} embed=:{EPORT} db={DB}")
    end = time.monotonic() + 180
    while time.monotonic() < end:
        try:
            h = http(EMBED + "/health", timeout=1.0)
            if h.get("status") == "ok":
                print(f"staging owner ready: model={h.get('model')} dim={h.get('dim')} "
                      f"code_version={h.get('code_version')}")
                return
        except (OSError, ValueError):
            pass
        time.sleep(0.5)
    sys.exit(f"staging owner not ready in 180 s; see {OWNER_LOG}")


def stop_owner() -> None:
    try:
        pid = int(PIDFILE.read_text())
    except (OSError, ValueError):
        pid = None
    if pid is None:
        print("no staging owner pid file; nothing to stop")
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        print(f"staging owner pid={pid} already gone")
        PIDFILE.unlink(missing_ok=True)
        return
    for _ in range(60):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            print(f"staging owner pid={pid} stopped")
            PIDFILE.unlink(missing_ok=True)
            return
        time.sleep(0.25)
    # Still alive after 15s of SIGTERM: keep the pid file so a retry (or a human) can find
    # and finish stopping it, instead of silently claiming "stopped" and orphaning it.
    sys.exit(f"staging owner pid={pid} did not stop within 15s of SIGTERM — pid file kept "
             f"at {PIDFILE}")


# ---------------------------------------------------------------------------
# Live digest and copy

def scroll_all(base: str, coll: str, with_vector: bool):
    pts, offset = [], None
    while True:
        body = {"limit": 512, "with_payload": True, "with_vector": with_vector}
        if offset is not None:
            body["offset"] = offset
        r = http(f"{base}/collections/{coll}/points/scroll", "POST", body)["result"]
        pts += r["points"]
        offset = r.get("next_page_offset")
        if offset is None:
            return pts


def digest(base: str) -> dict:
    out = {}
    for c in COLLECTIONS:
        pts = scroll_all(base, c, with_vector=False)
        keys = sorted(str((p.get("payload") or {}).get("content_hash") or f"id:{p['id']}")
                      for p in pts)
        out[c] = {"count": len(pts),
                  "sha256": hashlib.sha256("\n".join(keys).encode()).hexdigest()}
    return out


def copy_and_verify() -> None:
    import numpy as np
    for c in COLLECTIONS:
        info = http(f"{LIVE}/collections/{c}")["result"]["config"]["params"]["vectors"]
        t0 = time.perf_counter()
        live = scroll_all(LIVE, c, with_vector=True)
        try:
            http(f"{STAGING}/collections/{c}", "DELETE")
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
        http(f"{STAGING}/collections/{c}", "PUT",
             {"vectors": {"size": info["size"], "distance": info["distance"]}})
        for i in range(0, len(live), 256):
            chunk = [{"id": p["id"], "vector": p["vector"], "payload": p["payload"]}
                     for p in live[i:i + 256]]
            http(f"{STAGING}/collections/{c}/points?wait=true", "PUT", {"points": chunk})
        staged = {p["id"]: p for p in scroll_all(STAGING, c, with_vector=True)}
        bad_vec = bad_pl = missing = 0
        for p in live:
            s = staged.get(p["id"])
            if s is None:
                missing += 1
                continue
            if (np.asarray(p["vector"], dtype=np.float32).tobytes()
                    != np.asarray(s["vector"], dtype=np.float32).tobytes()):
                bad_vec += 1
            if p["payload"] != s["payload"]:
                bad_pl += 1
        print(f"copy {c}: live={len(live)} staging={len(staged)} missing={missing} "
              f"vector_bytes_differ={bad_vec} payload_differ={bad_pl} "
              f"({time.perf_counter() - t0:.1f}s)")
        if missing or bad_vec or bad_pl or len(staged) != len(live):
            sys.exit(f"copy verification failed for {c}")


# ---------------------------------------------------------------------------
# Replay set

def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def ledger_prompts(harness_re) -> list[str]:
    seen, out = set(), []
    lines = LEDGER.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in reversed(lines):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        q = e.get("q")
        if e.get("ev") != "turn" or e.get("sub") or not isinstance(q, str) or not q.strip():
            continue
        if harness_re.match(q) or q.lstrip().startswith("Execute the following task"):
            continue
        if q in seen:
            continue
        seen.add(q)
        out.append(q)
        if len(out) == N_LEDGER:
            break
    return out


def shapes(enf, scope_filter) -> list[tuple[str, str, dict]]:
    """(label, url path, body without query vector) — the enforcer's four request shapes
    plus search_skills' scope filter, as those callers build them."""
    coll, intent = enf.COLLECTION, enf.PROMPT_INTENT_COLLECTION
    grp = f"/collections/{coll}/points/query/groups"
    foreign = [sc for sc in enf.FOREIGN_SCOPES if sc != "claude-synced"]
    return [
        ("retrieve", grp, {"group_by": "name", "limit": enf.RETRIEVE_LIMIT, "group_size": 1,
                           "with_payload": ["name", "description", "scope"],
                           "filter": {"must_not": [{"key": "tier", "match": {"value": "external"}}]}}),
        ("external", grp, {"group_by": "name", "limit": enf.EXTERNAL_SLOTS * 3, "group_size": 1,
                           "with_payload": ["name", "description", "scope"],
                           "filter": {"must": [{"key": "tier", "match": {"value": "external"}}]}}),
        ("foreign", grp, {"group_by": "name", "limit": enf.FOREIGN_SLOTS * 3, "group_size": 1,
                          "with_payload": ["name", "description", "scope"],
                          "filter": {"must": [{"key": "scope", "match": {"any": foreign}}]}}),
        ("intent-conv", f"/collections/{intent}/points/query",
         {"filter": {"must": [{"key": "label", "match": {"value": "conversational"}}]},
          "limit": enf.INTENT_K}),
        ("intent-act", f"/collections/{intent}/points/query",
         {"filter": {"must": [{"key": "label", "match": {"value": "actionable"}}]},
          "limit": enf.INTENT_K}),
        ("search_skills", grp, {"group_by": "name", "limit": 6, "group_size": 1,
                                "with_payload": True, "filter": scope_filter}),
    ]


def rows(res: dict) -> list[tuple[str, float]]:
    r = res["result"]
    if "groups" in r:
        return [(str(g["id"]), float(g["hits"][0]["score"])) for g in r["groups"] if g["hits"]]
    return [(str(p["id"]), float(p["score"])) for p in r["points"]]


def compare(live: list, own: list, limit: int, wider=None) -> list[tuple[int, tuple, tuple]]:
    """Mismatches as (rank, live_row, owner_row). Live rows with exactly equal scores form
    one tie group whose names are compared as a set. A tie group reaching a full result
    list's cutoff may continue past it; a differing owner name there is accepted only when
    `wider()` (the same live query, widened until the list runs past the tie group) shows
    that name at exactly the tied score."""
    bad = []
    none = ("-", float("nan"))
    if len(live) != len(own):
        for k in range(min(len(live), len(own)), max(len(live), len(own))):
            bad.append((k + 1, live[k] if k < len(live) else none, own[k] if k < len(own) else none))
    n = min(len(live), len(own))
    i = 0
    while i < n:
        j = i
        while j < n and live[j][1] == live[i][1]:
            j += 1
        lset = {nm for nm, _ in live[i:j]}
        extra = {nm for nm, _ in own[i:j]} - lset
        if extra and j == n and len(live) == limit and wider is not None:
            tied = {nm for nm, sc in wider() if sc == live[i][1]}
            if extra <= tied:
                extra = set()
        for k in range(i, j):
            if abs(own[k][1] - live[k][1]) > TOL or extra:
                bad.append((k + 1, live[k], own[k]))
        i = j
    return bad


def pct(xs: list, p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))] if xs else float("nan")


def parity() -> int:
    enf = _load_module("enforcer_for_parity", REPO / "hooks" / "scripts" / "enforcer.py")
    os.environ["SKILL_QDRANT_URL"] = STAGING
    sys.path.insert(0, str(ENGINE_SRC))
    import skill_search.server as server          # this checkout's engine source
    scope_filter = server._scope_filter()
    led = ledger_prompts(enf._HARNESS_MSG_RE)
    prompts = led + FIXED_PROMPTS
    print(f"replay set: {len(led)} ledger prompts + {len(FIXED_PROMPTS)} fixed EN/VN "
          f"= {len(prompts)}; shapes: 4 enforcer ({'retrieve, external, foreign, intent'}"
          f" [conv+act]) + search_skills scope filter")
    sh = shapes(enf, scope_filter)
    mism, n_cmp, lat, approx_miss = 0, 0, [], 0
    per_shape = {s[0]: 0 for s in sh}
    for q in prompts:
        vec = http(EMBED + "/embed", "POST", {"text": q})["vector"]
        for label, path, base in sh:
            body = dict(base, query=vec)
            live = rows(http(LIVE + path, "POST", dict(body, params={"exact": True})))
            t0 = time.perf_counter()
            own = rows(http(STAGING + path, "POST", body))
            lat.append((time.perf_counter() - t0) * 1000)
            n_cmp += 1
            if label == "retrieve":
                approx = rows(http(LIVE + path, "POST", body))
                if [n for n, _ in approx] != [n for n, _ in live]:
                    approx_miss += 1
            def wider(lim=body["limit"], body=body, path=path):
                # widen until the live list runs past the tie group or runs out
                while True:
                    lim *= 4
                    got = rows(http(LIVE + path, "POST", dict(body, limit=lim, params={"exact": True})))
                    if len(got) < lim or got[-1][1] < got[body["limit"] - 1][1]:
                        return got
            for rank, lr, orow in compare(live, own, body["limit"], wider):
                mism += 1
                per_shape[label] += 1
                qq = json.dumps(f"[{label}] {q}", ensure_ascii=False)
                print(f"query={qq} rank={rank} live={lr[0]}:{lr[1]:.6f} "
                      f"owner={orow[0]}:{orow[1]:.6f}", file=sys.stderr)
    print(f"parity: prompts={len(prompts)} comparisons={n_cmp} mismatches={mism} "
          f"per_shape={per_shape}")
    print(f"owner latency ms: p50={pct(lat, 50):.2f} p90={pct(lat, 90):.2f} "
          f"p99={pct(lat, 99):.2f} n={len(lat)}")
    print(f"approximate-vs-exact (live, retrieve shape): {approx_miss}/{len(prompts)} "
          f"prompts where Qdrant's default search order differed from exact")
    return 0 if mism == 0 else 1


# ---------------------------------------------------------------------------
# Hook latency while a full reindex runs through the staging owner

P99_BAR_MS = 250.0


def reindex_cmd(state: Path) -> tuple[list, dict]:
    """`skill-search --reindex --force` from this checkout's engine source against the
    staging owner, with the live query server's engine flags (.mcp.json) and every
    file the engine writes redirected under `state`."""
    sys.path.insert(0, str(REPO / "scripts"))
    import engine_env
    env = engine_env.engine_env(REPO)
    state.mkdir(parents=True, exist_ok=True)
    env.update(PYTHONPATH=str(ENGINE_SRC), SKILL_QDRANT_URL=STAGING,
               EMBED_SHIM_HOST="127.0.0.1", EMBED_SHIM_PORT=str(EPORT),
               SKILL_META_PATH=str(state / "index_meta.json"),
               SKILL_SERVER_RECORDS=str(state / "servers"),
               SKILL_CONCIERGE_NEXT_SKILLS=str(state / "next-skills.json"))
    py = Path("~/.claude/skill-concierge/venv/bin/python").expanduser()
    return [str(py), "-m", "skill_search.server", "--reindex", "--force"], env


def load_test() -> int:
    enf = _load_module("enforcer_for_load", REPO / "hooks" / "scripts" / "enforcer.py")
    hook = [(path, body) for label, path, body in shapes(enf, None)
            if label in ("retrieve", "external", "foreign")]
    vecs = [http(EMBED + "/embed", "POST", {"text": q})["vector"] for q in FIXED_PROMPTS]
    cmd, env = reindex_cmd(Path("/tmp/cutover/load-state"))
    print(f"load: {len(hook)} hook-shaped query/groups requests per iteration, "
          f"{len(vecs)} prompt vectors, sequential loop with no pause; reindex: {' '.join(cmd)}")
    base, during, errors = [], [], 0

    def one(path, body, vec, sink):
        nonlocal errors
        t0 = time.perf_counter()
        try:
            http(STAGING + path, "POST", dict(body, query=vec), timeout=5.0)
            sink.append((time.perf_counter() - t0) * 1000)
        except (OSError, ValueError) as e:
            errors += 1
            sink.append(float("inf"))
            print(f"request error: {e!r}", file=sys.stderr)

    i = 0
    t_end = time.monotonic() + 5            # 5 s idle baseline
    while time.monotonic() < t_end:
        path, body = hook[i % len(hook)]
        one(path, body, vecs[i % len(vecs)], base)
        i += 1
    log = open("/tmp/cutover/load-reindex.log", "w")
    t0 = time.monotonic()
    proc = subprocess.Popen(cmd, env=env, cwd=str(REPO), stdout=log, stderr=subprocess.STDOUT)
    while proc.poll() is None:
        path, body = hook[i % len(hook)]
        one(path, body, vecs[i % len(vecs)], during)
        i += 1
    elapsed = time.monotonic() - t0
    log.close()
    tail = Path("/tmp/cutover/load-reindex.log").read_text().strip().splitlines()[-3:]
    print(f"reindex --force exit={proc.returncode} wall={elapsed:.1f}s under load; log tail: {tail}")
    fmt = lambda xs: (f"p50={pct(xs, 50):.2f} p95={pct(xs, 95):.2f} p99={pct(xs, 99):.2f} "
                      f"max={max(xs):.2f} n={len(xs)}") if xs else "n=0"
    print(f"idle baseline ms: {fmt(base)}")
    print(f"during reindex ms: {fmt(during)} errors={errors}")
    line = f"p50={pct(during, 50):.2f} p95={pct(during, 95):.2f} p99={pct(during, 99):.2f} n={len(during)}"
    ok = proc.returncode == 0 and during and pct(during, 99) < P99_BAR_MS
    if not ok:
        print(line, file=sys.stderr)
    print(f"load under reindex: {'PASS' if ok else 'FAIL'} ({line}; bar p99 < {P99_BAR_MS:.0f} ms"
          f"{'' if proc.returncode == 0 else '; reindex failed'})")
    return 0 if ok else 1


# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--stop", action="store_true", help="stop the staging owner and exit")
    ap.add_argument("--keep-running", action="store_true",
                    help="leave the staging owner running afterwards")
    ap.add_argument("--load", action="store_true",
                    help="hook-shaped load during a reindex --force on staging")
    ap.add_argument("--skip-copy", action="store_true",
                    help="replay against what staging already holds (digest still checked)")
    a = ap.parse_args()
    if a.stop:
        stop_owner()
        return 0
    start_owner()
    if a.load:
        try:
            return load_test()
        finally:
            if not a.keep_running:
                stop_owner()
    rc = 1
    try:
        for attempt in range(1, MAX_RERUNS + 1):
            before = digest(LIVE)
            print(f"live digest before (attempt {attempt}): {json.dumps(before)}")
            if not a.skip_copy or attempt > 1:
                copy_and_verify()
            rc = parity()
            after = digest(LIVE)
            print(f"live digest after  (attempt {attempt}): {json.dumps(after)}")
            if after == before:
                print("live digest unchanged during copy+replay")
                break
            print("live Qdrant changed during copy+replay (background reindex?); rerunning")
        else:
            print(f"live Qdrant kept changing across {MAX_RERUNS} attempts", file=sys.stderr)
            rc = 1
    finally:
        if not a.keep_running:
            stop_owner()
    print(f"search parity: {'PASS' if rc == 0 else 'FAIL'}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
