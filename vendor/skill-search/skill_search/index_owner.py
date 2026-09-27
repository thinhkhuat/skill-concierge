"""skill-concierge index owner: one local process that holds the skill index and the
embedding model, replacing the Qdrant container and the warm embed shim.

Run it as `python -m skill_search.index_owner` from the shared engine venv.

Two ports, both bound on 127.0.0.1 and ::1 (IPv4 only when the host has no IPv6
loopback):
  query port (SKILL_OWNER_QUERY_PORT, else SKILL_QDRANT_URL's port, else 6333 — the
      same derivation every caller and doctor already use) — the Qdrant REST subset
      the callers use, in Qdrant's JSON shape ({"result", "status", "time"}):
        GET  /  ·  GET /healthz
        GET | PUT | DELETE /collections/{c}
        GET  /collections/{c}/exists            {"exists": bool}
        PUT  /collections/{c}/points            upsert (normalizes vectors)
        POST /collections/{c}/points            fetch by ids
        POST /collections/{c}/points/scroll     id-ordered paging
        POST /collections/{c}/points/count
        POST /collections/{c}/points/delete     by ids or filter
        POST /collections/{c}/points/query      top-k points
        POST /collections/{c}/points/query/groups   best point per group_by value
  embed port (SKILL_OWNER_EMBED_PORT, else EMBED_SHIM_PORT, else 6363) — POST /embed, GET /health,
      POST /jev (ADR-0061: a fixed-destination warm-connection relay to TypeSafe for
      the Jev skill router, ported from the retired Docker embed shim — see
      VENDORED.md).

Storage: one SQLite file (SKILL_INDEX_DB, default ~/.cache/skill-search/index.sqlite).
This process is its only writer, enforced by an exclusive fcntl lock on `<db>.lock`.
Each write commits to SQLite before it replies and marks that collection's immutable
snapshot stale; the next read rebuilds it under the write lock, so a write is visible
to every later read (read-your-write). Otherwise readers never lock; they use
whichever snapshot is current.

Search is exact cosine: vectors are normalized on write, queries on read, scores
are float32 dot products. Groups are ordered by score descending, then group value
ascending; points by score descending, then id ascending. `params.exact` is accepted
and ignored (always exact). Filters: must / must_not / should, match.value,
match.any, is_null (key present with a null value; a missing key does not match),
is_empty, has_id, and nested filters.

Startup order: lock (retried up to 5 s unless an owner already answers) -> probe the
ports (anything answering means another server holds them: log and exit) -> bind ->
import numpy, load the index, load the model. Until loaded every path answers 503.
A rewritten venv version stamp (not lower than the one loaded) makes the owner
close its listeners, finish in-flight requests, release the lock and exit, so the
next start runs the reinstalled code. A lower stamp is logged and ignored.

Security: requests whose Host header is not 127.0.0.1/[::1]/localhost on the
serving port get 403; a POST/PUT/DELETE without Content-Type application/json gets
415; bodies over 16 MB get 413.

Test seam: SKILL_OWNER_NO_MODEL=1 serves the index without loading a model
(/embed answers 503).
"""
from __future__ import annotations

import bisect
import errno
import fcntl
import http.client
import json
import os
import queue
import re
import signal
import socket
import sqlite3
import ssl
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socketserver import TCPServer
from urllib.parse import urlsplit

TITLE = "skill-concierge index owner (Qdrant-compatible subset)"
MAX_BODY = 16 * 1024 * 1024
LOCK_RETRY_S = 5.0

DB_PATH = Path(os.environ.get("SKILL_INDEX_DB")
               or Path.home() / ".cache" / "skill-search" / "index.sqlite").expanduser()
# Port defaults mirror every caller (doctor.py, the launcher, the enforcer): a configured
# SKILL_QDRANT_URL/EMBED_SHIM_PORT is honored before falling back to the Qdrant/embed-shim
# well-known ports, so an owner started standalone lands on the same port its callers expect.
QUERY_PORT = int(os.environ.get("SKILL_OWNER_QUERY_PORT")
                 or urlsplit(os.environ.get("SKILL_QDRANT_URL", "")).port or 6333)
EMBED_PORT = int(os.environ.get("SKILL_OWNER_EMBED_PORT")
                 or os.environ.get("EMBED_SHIM_PORT") or 6363)
LOG_PATH = Path(os.environ.get("SKILL_OWNER_LOG")
                or Path(os.environ.get("SKILL_CONCIERGE_LOG",
                                        Path.home() / ".claude" / "skill-concierge" / "logs"))
                / "index-owner.log").expanduser()
STAMP_PATH = Path(os.environ.get("SKILL_OWNER_STAMP")
                  or Path(sys.prefix) / ".engine-plugin-version").expanduser()
STAMP_INTERVAL_S = float(os.environ.get("SKILL_OWNER_STAMP_INTERVAL", "60"))
NO_MODEL = os.environ.get("SKILL_OWNER_NO_MODEL", "0") == "1"
_COLL_RE = re.compile(r"^[A-Za-z0-9_.-]{1,255}$")


def _stderr_is_log_file() -> bool:
    """True when fd 2 is already LOG_PATH — a launcher/doctor that redirects the owner's
    stderr into the same log file would otherwise get every line twice (once from the
    explicit file write below, once from the redirected stderr print)."""
    try:
        err = os.fstat(sys.stderr.fileno())
        cur = LOG_PATH.stat()
    except (OSError, ValueError, AttributeError):
        return False
    return (err.st_dev, err.st_ino) == (cur.st_dev, cur.st_ino)


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} pid={os.getpid()} {msg}"
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
    if not _stderr_is_log_file():
        print(line, file=sys.stderr, flush=True)


class ApiError(Exception):
    def __init__(self, code: int, msg: str):
        super().__init__(msg)
        self.code = code


# ---------------------------------------------------------------------------
# Point ids keep their JSON type: unsigned integers or UUID strings (canonical form).

def _norm_id(pid):
    if isinstance(pid, bool):
        raise ApiError(400, f"bad point id: {pid!r}")
    if isinstance(pid, int):
        if pid < 0:
            raise ApiError(400, f"bad point id: {pid!r}")
        return pid
    if isinstance(pid, str):
        try:
            return str(uuid.UUID(pid))
        except ValueError:
            raise ApiError(400, f"bad point id: {pid!r}") from None
    raise ApiError(400, f"bad point id: {pid!r}")


def _id_sort(pid):
    return (0, pid, "") if isinstance(pid, int) else (1, 0, pid)


# ---------------------------------------------------------------------------
# Filters: boolean masks over a snapshot's rows.

_MISSING = object()


def _eq(a, v) -> bool:
    if isinstance(a, list):
        return any(_eq(x, v) for x in a)
    if isinstance(a, bool) or isinstance(v, bool):
        return type(a) is type(v) and a == v     # a boolean never equals 1
    return a == v and not (isinstance(a, str) ^ isinstance(v, str))


def _as_list(x):
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


class Snapshot:
    """Immutable view of one collection: rows in id order, a float32 matrix of
    normalized vectors, per-snapshot caches for filter masks and group layouts."""

    def __init__(self, np, rows: dict, dim: int):
        items = sorted(rows.values(), key=lambda r: _id_sort(r[0]))
        self.np = np
        self.ids = [r[0] for r in items]
        self.keys = [_id_sort(i) for i in self.ids]
        self.payloads = [r[2] for r in items]
        self.mat = (np.stack([r[1] for r in items]) if items
                    else np.zeros((0, dim), dtype=np.float32))
        self.n = len(items)
        self._masks: dict = {}
        self._groups: dict = {}

    # -- filters --
    def mask(self, flt):
        if not flt:
            return None
        if not isinstance(flt, dict):
            raise ApiError(400, "filter must be an object")
        key = json.dumps(flt, sort_keys=True)
        m = self._masks.get(key)
        if m is None:
            m = self._filter(flt)
            if len(self._masks) > 512:
                self._masks.clear()
            self._masks[key] = m
        return m

    def _filter(self, flt: dict):
        np = self.np
        m = np.ones(self.n, dtype=bool)
        for c in _as_list(flt.get("must")):
            m &= self._cond(c)
        for c in _as_list(flt.get("must_not")):
            m &= ~self._cond(c)
        should = _as_list(flt.get("should"))
        if should:
            s = np.zeros(self.n, dtype=bool)
            for c in should:
                s |= self._cond(c)
            m &= s
        return m

    def _col(self, fn):
        return self.np.fromiter((fn(p) for p in self.payloads), dtype=bool, count=self.n)

    def _cond(self, c):
        if not isinstance(c, dict):
            raise ApiError(400, "filter condition must be an object")
        if any(k in c for k in ("must", "must_not", "should")):
            return self._filter(c)
        if "is_null" in c:
            k = c["is_null"]["key"]
            return self._col(lambda p: k in p and p[k] is None)
        if "is_empty" in c:
            k = c["is_empty"]["key"]
            return self._col(lambda p: p.get(k) is None or p.get(k) == [])
        if "has_id" in c:
            want = {_norm_id(i) for i in c["has_id"]}
            return self.np.fromiter((i in want for i in self.ids), dtype=bool, count=self.n)
        if "key" in c and isinstance(c.get("match"), dict):
            k, mt = c["key"], c["match"]
            if "value" in mt:
                v = mt["value"]
                return self._col(lambda p: _eq(p.get(k, _MISSING), v))
            if "any" in mt:
                vals = mt["any"]
                strs = {x for x in vals if isinstance(x, str)}
                others = [x for x in vals if not isinstance(x, str)]

                def hit(a):
                    if isinstance(a, list):
                        return any(hit(x) for x in a)
                    if isinstance(a, str):
                        return a in strs
                    return any(_eq(a, x) for x in others)
                return self._col(lambda p: hit(p.get(k, _MISSING)))
        raise ApiError(400, f"unsupported filter condition: {json.dumps(c)[:200]}")

    # -- group layout: rows ordered by (group value, id), start offset of each group --
    def groups(self, key: str):
        g = self._groups.get(key)
        if g is None:
            np = self.np
            elig = [(p.get(key), i) for i, p in enumerate(self.payloads)
                    if isinstance(p.get(key), (str, int, float)) and not isinstance(p.get(key), bool)]
            elig.sort(key=lambda t: (not isinstance(t[0], str), t[0], t[1]))
            perm = np.array([i for _, i in elig], dtype=np.intp)
            starts, labels = [], []
            for pos, (val, _) in enumerate(elig):
                if not labels or labels[-1] != val:
                    starts.append(pos)
                    labels.append(val)
            g = (perm, np.array(starts, dtype=np.intp), labels)
            self._groups[key] = g
        return g

    # -- record rendering --
    def record(self, i: int, with_payload, with_vector, score=None) -> dict:
        rec = {"id": self.ids[i], "version": 0}
        if score is not None:
            rec["score"] = float(score)
        rec["payload"] = _select_payload(self.payloads[i], with_payload)
        rec["vector"] = [float(x) for x in self.mat[i]] if with_vector else None
        return rec


def _select_payload(p: dict, spec):
    if spec is True:
        return p
    if not spec:
        return None
    if isinstance(spec, list):
        return {k: p[k] for k in spec if k in p}
    if isinstance(spec, dict):
        if "include" in spec:
            return {k: p[k] for k in _as_list(spec["include"]) if k in p}
        if "exclude" in spec:
            ex = set(_as_list(spec["exclude"]))
            return {k: v for k, v in p.items() if k not in ex}
    raise ApiError(400, "bad with_payload")


def _with_vector(body: dict) -> bool:
    return bool(body.get("with_vector", body.get("with_vectors", False)))


class Collection:
    def __init__(self, np, name: str, dim: int, distance: str = "Cosine", lock=None):
        self.name, self.dim, self.distance = name, dim, distance
        self.rows: dict = {}          # id -> (id, normalized float32 vector, payload)
        self._np, self._lock = np, lock or threading.RLock()
        self._snap = Snapshot(np, self.rows, dim)
        self._stale = False

    def changed(self) -> None:
        """Rows changed (caller holds the store's write lock)."""
        self._stale = True

    @property
    def snap(self) -> "Snapshot":
        # Rebuilt at the first read after a write, not at every write: a full reindex is
        # hundreds of writes, and a fresh full-size matrix per write churned tens of GB
        # through the allocator (several GB resident at peak). Rebuilding under the write
        # lock keeps read-your-write: a read after an acknowledged write sees it.
        if self._stale:
            with self._lock:
                if self._stale:
                    self._snap = Snapshot(self._np, self.rows, self.dim)
                    self._stale = False
        return self._snap


# ---------------------------------------------------------------------------
# Store: SQLite persistence + in-memory snapshots. One write lock for all writes.

class Store:
    def __init__(self, path: Path):
        import numpy
        self.np = numpy
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS collections("
                        "name TEXT PRIMARY KEY, dim INTEGER NOT NULL, distance TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS points(collection TEXT NOT NULL, "
                        "id TEXT NOT NULL, vector BLOB NOT NULL, payload TEXT NOT NULL, "
                        "PRIMARY KEY(collection, id))")
        self.db.commit()
        self.wlock = threading.RLock()      # re-entrant: a filtered delete reads the snapshot
        self.colls: dict[str, Collection] = {}
        for name, dim, dist in self.db.execute("SELECT name, dim, distance FROM collections"):
            self.colls[name] = Collection(numpy, name, dim, dist, self.wlock)
        for cname, pid, blob, payload in self.db.execute(
                "SELECT collection, id, vector, payload FROM points"):
            c = self.colls.get(cname)
            if c is not None:
                p = json.loads(pid)
                c.rows[p] = (p, numpy.frombuffer(blob, dtype=numpy.float32), json.loads(payload))
        for c in self.colls.values():
            c._snap = Snapshot(numpy, c.rows, c.dim)

    def close(self) -> None:
        with self.wlock:
            self.db.close()

    def get(self, name: str) -> Collection:
        c = self.colls.get(name)
        if c is None:
            raise ApiError(404, f"Not found: Collection `{name}` doesn't exist!")
        return c

    def _normalize(self, vec, dim: int):
        np = self.np
        if isinstance(vec, dict):
            raise ApiError(400, "named vectors are not supported")
        try:
            v = np.asarray(vec, dtype=np.float32)
        except (TypeError, ValueError):
            raise ApiError(400, "vector must be a list of numbers") from None
        if v.ndim != 1 or v.shape[0] != dim:
            raise ApiError(400, f"Wrong input: Vector dimension error: expected dim: {dim}, "
                                f"got {v.shape[0] if v.ndim == 1 else v.shape}")
        # Qdrant's cosine preprocess rule (lib/segment/src/spaces/tools.rs,
        # is_length_zero_or_normalized): a zero or already-unit vector is stored as
        # given, so vectors copied from Qdrant stay bit-for-bit identical.
        sq = float(np.dot(v, v))
        if sq < float(np.finfo(np.float32).eps) or abs(sq - 1.0) <= 1e-6:
            return v
        return v / np.float32(np.sqrt(np.float32(sq)))

    def query_vector(self, c: Collection, q):
        if isinstance(q, dict) and "nearest" in q:
            q = q["nearest"]
        return self._normalize(q, c.dim)

    # -- writes (each commits before returning; the next read rebuilds the snapshot) --
    def create(self, name: str, body: dict) -> bool:
        if not _COLL_RE.match(name):
            raise ApiError(400, f"bad collection name: {name!r}")
        vec = body.get("vectors")
        if not isinstance(vec, dict) or not isinstance(vec.get("size"), int) or vec["size"] <= 0:
            raise ApiError(400, "vectors.size is required")
        dist = str(vec.get("distance", "Cosine"))
        if dist.lower() != "cosine":
            raise ApiError(400, f"only Cosine distance is supported, got {dist}")
        with self.wlock:
            if name in self.colls:
                raise ApiError(409, f"Wrong input: Collection `{name}` already exists!")
            self.db.execute("INSERT INTO collections VALUES (?,?,?)", (name, vec["size"], "Cosine"))
            self.db.commit()
            c = Collection(self.np, name, vec["size"], lock=self.wlock)
            self.colls[name] = c
        return True

    def drop(self, name: str) -> bool:
        with self.wlock:
            if name not in self.colls:
                return False
            self.db.execute("DELETE FROM points WHERE collection=?", (name,))
            self.db.execute("DELETE FROM collections WHERE name=?", (name,))
            self.db.commit()
            del self.colls[name]
        return True

    def upsert(self, name: str, body: dict) -> None:
        c = self.get(name)
        if "batch" in body:
            b = body["batch"]
            ids, vecs = b.get("ids") or [], b.get("vectors") or []
            pls = b.get("payloads") or [None] * len(ids)
            if not (len(ids) == len(vecs) == len(pls)):
                raise ApiError(400, "batch ids/vectors/payloads length mismatch")
            pts = [{"id": i, "vector": v, "payload": p} for i, v, p in zip(ids, vecs, pls)]
        else:
            pts = body.get("points")
            if not isinstance(pts, list):
                raise ApiError(400, "points must be a list")
        rows = []
        for p in pts:
            if not isinstance(p, dict):
                raise ApiError(400, "point must be an object")
            pid = _norm_id(p.get("id"))
            payload = p.get("payload") or {}
            if not isinstance(payload, dict):
                raise ApiError(400, "payload must be an object")
            rows.append((pid, self._normalize(p.get("vector"), c.dim), payload))
        with self.wlock:
            if self.colls.get(name) is not c:
                raise ApiError(404, f"Not found: Collection `{name}` doesn't exist!")
            with self.db:   # atomic: a failed executemany rolls back, never leaves partial rows
                self.db.executemany(
                    "INSERT OR REPLACE INTO points VALUES (?,?,?,?)",
                    [(name, json.dumps(pid), v.tobytes(), json.dumps(pl)) for pid, v, pl in rows])
            for row in rows:
                c.rows[row[0]] = row
            c.changed()

    def delete_points(self, name: str, body: dict) -> None:
        c = self.get(name)
        with self.wlock:
            if "points" in body:
                ids = [_norm_id(i) for i in _as_list(body["points"])]
            elif "filter" in body:
                snap = c.snap
                m = snap.mask(body["filter"])
                ids = list(snap.ids) if m is None else [snap.ids[i] for i in self.np.nonzero(m)[0]]
            else:
                raise ApiError(400, "delete needs `points` or `filter`")
            ids = [i for i in ids if i in c.rows]
            if not ids:
                return
            with self.db:   # atomic: a failed executemany rolls back, never leaves partial rows
                self.db.executemany("DELETE FROM points WHERE collection=? AND id=?",
                                    [(name, json.dumps(i)) for i in ids])
            for i in ids:
                del c.rows[i]
            c.changed()

    # -- reads (lock-free: one snapshot reference per request) --
    def info(self, name: str) -> dict:
        c = self.get(name)
        return {"status": "green", "optimizer_status": "ok", "points_count": c.snap.n,
                "indexed_vectors_count": 0, "segments_count": 1,
                "config": {"params": {"vectors": {"size": c.dim, "distance": c.distance}}},
                "payload_schema": {}}

    def retrieve(self, name: str, body: dict) -> list:
        snap = self.get(name).snap
        wp, wv = body.get("with_payload", True), _with_vector(body)
        out = []
        for pid in _as_list(body.get("ids")):
            pid = _norm_id(pid)
            k = _id_sort(pid)
            i = bisect.bisect_left(snap.keys, k)
            if i < snap.n and snap.keys[i] == k:
                out.append(snap.record(i, wp, wv))
        return out

    def count(self, name: str, body: dict) -> dict:
        snap = self.get(name).snap
        m = snap.mask(body.get("filter"))
        return {"count": snap.n if m is None else int(m.sum())}

    def scroll(self, name: str, body: dict) -> dict:
        snap = self.get(name).snap
        limit = int(body.get("limit") or 10)
        start = 0
        if body.get("offset") is not None:
            start = bisect.bisect_left(snap.keys, _id_sort(_norm_id(body["offset"])))
        m = snap.mask(body.get("filter"))
        if m is None:
            idx = range(start, min(snap.n, start + limit + 1))
        else:
            idx = (self.np.nonzero(m[start:])[0][:limit + 1] + start).tolist()
        idx = list(idx)
        wp, wv = body.get("with_payload", True), _with_vector(body)
        pts = [snap.record(i, wp, wv) for i in idx[:limit]]
        nxt = snap.ids[idx[limit]] if len(idx) > limit else None
        return {"points": pts, "next_page_offset": nxt}

    def _scores(self, c: Collection, snap: Snapshot, body: dict):
        np = self.np
        q = self.query_vector(c, body.get("query", body.get("vector")))
        scores = snap.mat @ q if snap.n else np.zeros(0, dtype=np.float32)
        m = snap.mask(body.get("filter"))
        m = np.ones(snap.n, dtype=bool) if m is None else m.copy()
        thr = body.get("score_threshold")
        if thr is not None:
            m &= scores >= np.float32(thr)
        return scores, m

    def query(self, name: str, body: dict) -> dict:
        np = self.np
        c = self.get(name)
        snap = c.snap
        scores, m = self._scores(c, snap, body)
        limit, offset = int(body.get("limit") or 10), int(body.get("offset") or 0)
        cand = np.nonzero(m)[0]
        s = scores[cand]
        k = limit + offset
        if len(cand) > k > 0:
            kth = np.partition(s, len(s) - k)[len(s) - k]
            keep = s >= kth
            cand, s = cand[keep], s[keep]
        order = np.lexsort((cand, -s))[offset:offset + limit]
        wp, wv = body.get("with_payload", False), _with_vector(body)
        return {"points": [snap.record(int(cand[j]), wp, wv, s[j]) for j in order]}

    def query_groups(self, name: str, body: dict) -> dict:
        np = self.np
        c = self.get(name)
        snap = c.snap
        key = body.get("group_by")
        if not isinstance(key, str) or not key:
            raise ApiError(400, "group_by is required")
        limit, gsize = int(body.get("limit") or 10), int(body.get("group_size") or 3)
        scores, m = self._scores(c, snap, body)
        perm, starts, labels = snap.groups(key)
        if not len(perm):
            return {"groups": []}
        ms = np.where(m[perm], scores[perm], -np.inf)
        gmax = np.maximum.reduceat(ms, starts)
        cand = np.nonzero(gmax > -np.inf)[0]
        # score descending, then group value ascending (labels are sorted, so index order)
        top = cand[np.lexsort((cand, -gmax[cand]))][:limit]
        ends = np.append(starts[1:], len(perm))
        wp, wv = body.get("with_payload", False), _with_vector(body)
        out = []
        for g in top:
            seg = ms[starts[g]:ends[g]]
            live = np.nonzero(seg > -np.inf)[0]
            pick = live[np.argsort(-seg[live], kind="stable")][:gsize]
            hits = [snap.record(int(perm[starts[g] + j]), wp, wv, seg[j]) for j in pick]
            out.append({"id": labels[g], "hits": hits})
        return {"groups": out}


# ---------------------------------------------------------------------------
# Owner state shared by the handlers.

class Owner:
    def __init__(self):
        self.ready = False
        self.store: Store | None = None
        self.embed = None
        self.model = None
        self.dim = None
        self.stamp = _read_stamp()
        # The version actually running never changes for the life of the process — only a
        # restart runs new code. `self.stamp` below is mutable bookkeeping for check_stamp's
        # own change-detection (including the intentional downgrade dedup), so `/health`
        # must report THIS field, not `self.stamp`, or a downgrade makes code_version lie
        # about which code answered the request (L1: doctor's check_owner compares
        # /health's code_version against the venv stamp file to catch exactly this drift).
        self.loaded_version = self.stamp[0] if self.stamp else None
        self.stop = threading.Event()
        self.stop_reason = ""
        self._stamp_lock = threading.Lock()

    def request_stop(self, reason: str) -> None:
        if not self.stop.is_set():
            self.stop_reason = reason
            self.stop.set()

    def check_stamp(self) -> None:
        """A rewritten stamp at an equal or higher version means the venv was just
        reinstalled: exit so the next start runs the new code. A lower version (an
        old harness copy downgraded the venv) is logged; the owner keeps serving."""
        with self._stamp_lock:
            new = _read_stamp()
            old = self.stamp
            if new is None or new == old:
                return
            if old is None or _ver(new[0]) >= _ver(old[0]):
                log(f"venv stamp rewritten ({old and old[0]!r} -> {new[0]!r}): exiting for the new code")
                self.request_stop("stamp")
            else:
                log(f"WARNING venv stamp downgraded ({old[0]!r} -> {new[0]!r}) by an older "
                    "harness copy: keeping the running owner")
                self.stamp = new

    @property
    def code_version(self):
        return self.loaded_version

    @property
    def stamp_version(self):
        """The version currently on disk, as last observed by check_stamp — differs from
        code_version exactly when an older harness copy downgraded the venv stamp."""
        return self.stamp[0] if self.stamp else None


def _read_stamp():
    try:
        st = STAMP_PATH.stat()
        return (STAMP_PATH.read_text(encoding="utf-8").strip(), st.st_mtime_ns, st.st_ino, st.st_size)
    except OSError:
        return None


def _ver(s: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", s))


OWNER: Owner | None = None


# ---------------------------------------------------------------------------
# ADR-0061 /jev relay, ported verbatim from the retired Docker embed shim
# (scripts/embed_server.py) so the Jev skill router keeps its warm connection once the
# shim is gone — see VENDORED.md. Fixed destination: the owner never takes a URL from
# the request. The caller's Authorization header is forwarded and never stored or
# logged; the owner itself holds no key.

JEV_HOST = "api.typesafe.ai"
JEV_PATH = "/v1/systemone"
JEV_MAX_TIMEOUT = 10.0
_JEV_TLS = ssl.create_default_context()
_JEV_POOL = queue.LifoQueue(maxsize=8)   # warm connections, most recently used first; thread-safe


def _jev_relay(body: bytes, auth: str, timeout: float):
    """POST body to TypeSafe on a pooled warm connection -> (status, response bytes). A pooled
    connection the server has since closed fails at once (reset / remote closed); that case alone
    retries once on a fresh connection. A timeout is never retried: the request may already be
    billed and the caller has stopped waiting. A connection returns to the pool only after a
    complete exchange. `_JEV_POOL` is a `queue.LifoQueue`, safe under the owner's concurrent
    per-request threads without an extra lock."""
    for attempt in (0, 1):
        try:
            if attempt:   # the retry never takes a second pooled connection: after an idle spell
                raise queue.Empty   # every pooled one may be stale
            conn, reused = _JEV_POOL.get_nowait(), True
        except queue.Empty:
            conn, reused = http.client.HTTPSConnection(JEV_HOST, context=_JEV_TLS), False
        conn.timeout = timeout
        if conn.sock is not None:
            conn.sock.settimeout(timeout)
        try:
            conn.request("POST", JEV_PATH, body=body,
                         headers={"Authorization": auth, "Content-Type": "application/json"})
            resp = conn.getresponse()
            out = resp.status, resp.read()
        except (ConnectionResetError, BrokenPipeError, http.client.RemoteDisconnected,
                http.client.BadStatusLine):
            conn.close()
            if attempt or not reused:
                raise
            continue
        except (http.client.HTTPException, OSError):
            conn.close()
            raise
        try:
            _JEV_POOL.put_nowait(conn)
        except queue.Full:
            conn.close()
        return out
    raise RuntimeError("unreachable")


# ---------------------------------------------------------------------------
# HTTP layer.

class Handler(BaseHTTPRequestHandler):
    server_version = "skill-concierge-index-owner"
    kind = "query"          # overridden per port

    def log_message(self, *_a):
        pass

    def _send(self, code: int, obj, ctype="application/json") -> None:
        body = obj if isinstance(obj, bytes) else json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _ok(self, result, t0):
        self._send(200, {"result": result, "status": "ok", "time": time.perf_counter() - t0})

    def _err(self, code: int, msg: str, t0):
        self._send(code, {"status": {"error": msg}, "time": time.perf_counter() - t0})

    def _guard(self, write: bool) -> str | None:
        port = self.server.server_address[1]
        host = (self.headers.get("Host") or "").lower()
        if host not in (f"127.0.0.1:{port}", f"[::1]:{port}", f"localhost:{port}"):
            return "403"
        if write:
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if ctype != "application/json":
                return "415"
        return None

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ApiError(413, "request body too large")
        raw = self.rfile.read(n) if n else b""
        if not raw.strip():
            return {}
        try:
            body = json.loads(raw)
        except ValueError:
            raise ApiError(400, "request body is not valid JSON") from None
        if not isinstance(body, dict):
            raise ApiError(400, "request body must be a JSON object")
        return body

    def _handle(self, method: str) -> None:
        t0 = time.perf_counter()
        bad = self._guard(method != "GET")
        if bad == "403":
            return self._err(403, "forbidden host", t0)
        if bad == "415":
            return self._err(415, "Content-Type must be application/json", t0)
        owner = OWNER
        parts = urlsplit(self.path)
        path = parts.path.rstrip("/") or "/"
        try:
            if self.kind == "embed":
                return self._embed_route(owner, method, path, t0)
            if not owner.ready:
                if method == "GET" and path == "/":
                    return self._send(503, {"title": TITLE, "version": owner.code_version,
                                            "status": "loading"})
                return self._err(503, "index owner is loading", t0)
            return self._query_route(owner.store, method, path, t0)
        except ApiError as e:
            return self._err(e.code, str(e), t0)
        except (KeyError, TypeError, ValueError) as e:
            return self._err(400, f"bad request: {e}", t0)
        except Exception as e:  # noqa: BLE001 — answer, never drop the connection
            log(f"ERROR {method} {path}: {e!r}")
            return self._err(500, f"internal error: {e}", t0)

    def _query_route(self, store: Store, method: str, path: str, t0) -> None:
        if path == "/" and method == "GET":
            return self._send(200, {"title": TITLE, "version": OWNER.code_version})
        if path == "/healthz" and method == "GET":
            return self._send(200, b"healthz check passed", "text/plain")
        seg = path.strip("/").split("/")
        if len(seg) < 2 or seg[0] != "collections":
            raise ApiError(404, "not found")
        c, rest = seg[1], "/".join(seg[2:])
        if not rest:
            if method == "GET":
                return self._ok(store.info(c), t0)
            if method == "PUT":
                return self._ok(store.create(c, self._body()), t0)
            if method == "DELETE":
                self._body()
                return self._ok(store.drop(c), t0)
        elif rest == "exists" and method == "GET":
            return self._ok({"exists": c in store.colls}, t0)
        elif rest == "points" and method == "PUT":
            store.upsert(c, self._body())
            return self._ok({"operation_id": 0, "status": "completed"}, t0)
        elif method == "POST":
            body = self._body()
            if rest == "points":
                return self._ok(store.retrieve(c, body), t0)
            if rest == "points/scroll":
                return self._ok(store.scroll(c, body), t0)
            if rest == "points/count":
                return self._ok(store.count(c, body), t0)
            if rest == "points/delete":
                store.delete_points(c, body)
                return self._ok({"operation_id": 0, "status": "completed"}, t0)
            if rest == "points/query":
                return self._ok(store.query(c, body), t0)
            if rest == "points/query/groups":
                return self._ok(store.query_groups(c, body), t0)
        raise ApiError(404, "not found")

    def _embed_route(self, owner: Owner, method: str, path: str, t0) -> None:
        if path == "/jev" and method == "POST":
            return self._jev()
        if path == "/health" and method == "GET":
            owner.check_stamp()
            if not owner.ready:
                return self._send(503, {"status": "loading", "code_version": owner.code_version,
                                        "routes": ["embed", "jev"]})
            return self._send(200, {"status": "ok", "model": owner.model, "dim": owner.dim,
                                    "code_version": owner.code_version,
                                    "stamp_version": owner.stamp_version,
                                    "routes": ["embed", "jev"]})
        if path == "/embed" and method == "POST":
            if not owner.ready or owner.embed is None:
                return self._send(503, {"error": "model not loaded"})
            body = self._body()
            text = body.get("text", "")
            if not isinstance(text, str) or not text:
                return self._send(400, {"error": "missing 'text'"})
            return self._send(200, {"vector": owner.embed(text)})
        return self._send(404, {"error": "not found"})

    def _jev(self) -> None:
        """ADR-0061 relay: forward to TypeSafe on a pooled connection, reply with its status
        and body verbatim. Never requires the index or the model to be loaded."""
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return self._send(401, {"error": "missing bearer token"})
        try:
            timeout = min(float(self.headers.get("X-Jev-Timeout", "5") or 5), JEV_MAX_TIMEOUT)
            n = int(self.headers.get("Content-Length", 0) or 0)
            status, raw = _jev_relay(self.rfile.read(n), auth, timeout)
        except (OSError, ValueError, http.client.HTTPException) as exc:
            return self._send(502, {"error": type(exc).__name__})
        return self._send(status, raw)

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PUT(self):
        self._handle("PUT")

    def do_DELETE(self):
        self._handle("DELETE")


class _Server4(ThreadingHTTPServer):
    daemon_threads = False      # server_close() joins in-flight requests (drain)
    request_queue_size = 256    # listen backlog: the default 5 resets bursts of hook requests
    block_on_close = True

    def server_bind(self):      # skip HTTPServer's getfqdn(): it can stall on macOS DNS
        TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


class _Server6(_Server4):
    address_family = socket.AF_INET6

    def server_bind(self):
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        super().server_bind()


def _probe(port: int) -> str | None:
    """Who answers on this port: None (nobody), 'owner', or 'other'. A connection the
    listener ACCEPTS and then resets/closes before a usable response still proves someone
    is there (e.g. a foreign wildcard listener still warming up) — that counts as 'other',
    never 'nobody'. Only a refused connection (nothing accepted it) means nobody."""
    seen = None
    for host in ("127.0.0.1", "::1"):
        conn = http.client.HTTPConnection(host, port, timeout=0.5)
        try:
            conn.request("GET", "/", headers={"Host": f"{'[::1]' if ':' in host else host}:{port}"})
            r = conn.getresponse()
            try:
                title = json.loads(r.read() or b"{}").get("title")
            except (ValueError, AttributeError):
                title = None
            if title == TITLE:
                return "owner"
            seen = "other"
        except ConnectionRefusedError:
            pass                                  # nobody listening on this host/family
        except OSError as e:
            if host == "::1" and e.errno in (errno.EADDRNOTAVAIL, errno.EAFNOSUPPORT,
                                              errno.ENETUNREACH, errno.EHOSTUNREACH):
                pass                               # no IPv6 loopback — nobody there, as _bind assumes
            else:
                seen = "other"                    # accepted then reset/closed (127.0.0.1 stays strict)
        except http.client.HTTPException:
            seen = "other"                        # accepted then reset/closed/malformed
        finally:
            conn.close()
    return seen


def _bind(port: int, kind: str) -> list:
    handler = type(f"{kind.title()}Handler", (Handler,), {"kind": kind})
    servers = [_Server4(("127.0.0.1", port), handler)]
    try:
        servers.append(_Server6(("::1", port), handler))
    except OSError as e:
        if e.errno in (errno.EADDRNOTAVAIL, errno.EAFNOSUPPORT):
            log(f"no IPv6 loopback ({e.strerror}): serving {kind} port {port} on 127.0.0.1 only")
        else:
            for s in servers:
                s.server_close()
            raise
    return servers


def _load(owner: Owner) -> None:
    owner.store = Store(DB_PATH)
    if not NO_MODEL:
        os.environ.setdefault("SKILL_EMBED_BACKEND", "fastembed")
        os.environ.setdefault("SKILL_EMBED_MODEL",
                              "sentence-transformers/paraphrase-multilingual-mpnet-base-v2")
        from skill_search.server import EMBED_MODEL, embed
        owner.dim = len(embed("dimension probe"))
        bad = {c.name: c.dim for c in owner.store.colls.values() if c.dim != owner.dim}
        if bad:
            raise RuntimeError(f"model dimension {owner.dim} does not match collections {bad}")
        owner.model, owner.embed = EMBED_MODEL, embed


def main() -> int:
    global OWNER
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    lockf = open(f"{DB_PATH}.lock", "a+")
    deadline = time.monotonic() + LOCK_RETRY_S
    while True:
        try:
            fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            if _probe(QUERY_PORT) == "owner":
                log(f"duplicate start: an owner already serves {DB_PATH} on :{QUERY_PORT}; exiting")
                return 0
            if time.monotonic() > deadline:
                log(f"another owner holds {DB_PATH}.lock; exiting")
                return 0
            time.sleep(0.05)

    for port in (QUERY_PORT, EMBED_PORT):
        who = _probe(port)
        if who:
            what = "another index owner" if who == "owner" else "a non-owner server (Docker Qdrant/embed shim?)"
            log(f"PORT CONFLICT: port {port} is answered by {what}; not starting")
            return 1

    OWNER = owner = Owner()
    try:
        servers = _bind(QUERY_PORT, "query") + _bind(EMBED_PORT, "embed")
    except OSError as e:
        log(f"PORT CONFLICT: cannot bind ({e}); not starting")
        return 1
    threads = [threading.Thread(target=s.serve_forever, args=(0.1,), daemon=True)
               for s in servers]
    for t in threads:
        t.start()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: owner.request_stop("signal"))
    log(f"listening query=:{QUERY_PORT} embed=:{EMBED_PORT} db={DB_PATH} "
        f"code_version={owner.code_version}")

    try:
        _load(owner)
    except Exception as e:  # noqa: BLE001
        log(f"ERROR load failed, refusing to serve: {e!r}")
        owner.request_stop("load-failed")
    else:
        owner.ready = True
        counts = {c.name: c.snap.n for c in owner.store.colls.values()}
        log(f"ready: collections={counts} model={owner.model}")

    def _watch():
        while not owner.stop.wait(STAMP_INTERVAL_S):
            owner.check_stamp()
    threading.Thread(target=_watch, daemon=True).start()

    while not owner.stop.wait(0.5):
        pass
    # Close listeners, finish in-flight requests (every acknowledged write is
    # committed), then release the lock, so a restart never loses to this exit.
    for s in servers:
        s.shutdown()
    for s in servers:
        s.server_close()
    if owner.store is not None:
        owner.store.close()
    fcntl.flock(lockf, fcntl.LOCK_UN)
    lockf.close()
    log(f"exited ({owner.stop_reason})")
    return 1 if owner.stop_reason == "load-failed" else 0


if __name__ == "__main__":
    sys.exit(main())
