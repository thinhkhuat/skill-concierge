#!/usr/bin/env python3
"""
skill-search MCP server
------------------------
Replaces Claude Code's native ~1% skill-listing tax with on-demand
semantic retrieval over the FULL skill descriptions/bodies.

Exposes four tools to Claude Code:
  - search_skills(query)   -> ranked relevant skills (the main path)
  - get_skill(name)        -> full SKILL.md for a named skill (explicit pull)
  - reindex(force=False)   -> INCREMENTAL update (only new/changed skills re-embed)
  - health()               -> diagnose drift/outages (skills are name-only, so a
                              broken index hides skills silently — this surfaces it)

Design contract:
  * The vector store (Qdrant) holds full descriptions, NOT the 1% budget.
  * Claude receives only the top-k relevant {name, description, score}.
  * Claude then invokes those skills BY NAME (so they must stay at least
    "name-only" in skillOverrides — see generate_overrides.py).

Scaling notes:
  * reindex is incremental: each point stores a content hash, so a reindex only
    re-embeds skills whose text changed and deletes points whose skill is gone.
    Full rebuild stays available via force=True / `--rebuild`.
  * Default deployment is SERVICE-FREE: embedded on-disk Qdrant + fastembed local
    ONNX embeddings. No Docker, no Ollama, no manual model pull (the model is
    downloaded once, then runs offline). Opt into the faster tier with
    SKILL_QDRANT_URL (Qdrant server) and/or SKILL_EMBED_BACKEND=ollama.

Deps:
  pip install "mcp[cli]" qdrant-client fastembed requests   # default, service-free
  #   Ollama tier instead: set SKILL_EMBED_BACKEND=ollama (uses a running Ollama)
"""

import os
import re
import sys
import json
import time
import uuid
import logging
import hashlib
from pathlib import Path

# Library-style logger: no handler/basicConfig here (that's the host app's call).
# Enable with logging.getLogger("skill_search").setLevel(logging.DEBUG).
log = logging.getLogger("skill_search")

from mcp.server.fastmcp import FastMCP
from qdrant_client import QdrantClient, models
from qdrant_client.models import Distance, VectorParams, PointStruct
import requests

# Skill discovery is shared with generate_overrides.py so both halves operate
# on the exact same set of skills/names — see skills_discovery.py.
from skill_search.skills_discovery import discover_skills


# ---------------------------------------------------------------------------
# Configuration (override via env vars so the same code runs on any machine)
# ---------------------------------------------------------------------------
# Vector store. Default is EMBEDDED (local file, no server/Docker). Set
# SKILL_QDRANT_URL to opt into a Qdrant server; SKILL_QDRANT_PATH overrides the
# embedded location.
QDRANT_URL      = os.environ.get("SKILL_QDRANT_URL")          # set -> server mode
QDRANT_PATH     = os.environ.get("SKILL_QDRANT_PATH")         # embedded location
COLLECTION      = os.environ.get("SKILL_COLLECTION", "claude_skills")

# Embedding backend. Default "fastembed" = local ONNX, NO service and no manual
# model pull (downloaded once, then offline). Set "ollama" to use a running
# Ollama. EMBED_MODEL default tracks the chosen backend.
EMBED_BACKEND   = os.environ.get("SKILL_EMBED_BACKEND", "fastembed").lower()
_DEFAULT_MODEL  = {"ollama": "embeddinggemma", "fastembed": "BAAI/bge-small-en-v1.5"}
EMBED_MODEL     = os.environ.get("SKILL_EMBED_MODEL") or _DEFAULT_MODEL.get(EMBED_BACKEND, "embeddinggemma")
OLLAMA_URL      = os.environ.get("SKILL_OLLAMA_URL", "http://localhost:11434")
EMBED_BATCH     = int(os.environ.get("SKILL_EMBED_BATCH", "64"))

TOP_K           = int(os.environ.get("SKILL_TOP_K", "6"))
# Multi-vector trigger layer: index each skill's intent phrases as separate points and
# MAX-pool them at query time (group_by name). Default ON; set SKILL_MULTIVECTOR=0 + reindex
# to revert to one bare vector per skill. (Validated: 2.2x rank-1/separation, flat false-fire.)
MULTIVECTOR     = os.environ.get("SKILL_MULTIVECTOR", "1") != "0"
# Body-derived trigger points (Option 4): also mine each skill's BODY labeled
# decision-sections ("## When to Use", "Triggers:", ...) for extra trigger phrases,
# not just the description (skills_discovery.parse_skill's `body_triggers`).
# Default ON; set SKILL_BODY_TRIGGERS=0 + reindex to revert to description-only
# triggers (today's behavior, byte-identical). No effect when MULTIVECTOR is off.
SKILL_BODY_TRIGGERS = os.environ.get("SKILL_BODY_TRIGGERS", "1") != "0"
# Index manifest: lets us detect drift between disk and the index cheaply.
META_PATH       = Path(os.environ.get(
    "SKILL_META_PATH", str(Path.home() / ".cache" / "skill-search" / "index_meta.json")))

mcp = FastMCP("skill-search")

# Server Qdrant (if a URL is given) vs embedded local-file (the default). Embedded
# needs no Docker but locks the dir to ONE process — don't run a CLI reindex while
# the MCP server is up in that mode; use the reindex() tool instead.
if QDRANT_URL:
    _qdrant = QdrantClient(url=QDRANT_URL)
    _STORE = QDRANT_URL
else:
    _path = QDRANT_PATH or str(Path.home() / ".cache" / "skill-search" / "qdrant")
    Path(_path).mkdir(parents=True, exist_ok=True)
    _qdrant = QdrantClient(path=_path)
    _STORE = f"embedded:{_path}"


# ---------------------------------------------------------------------------
# Staleness tracking. The retriever is the SOLE discovery path once skills are
# name-only, so a stale/missing index silently hides skills. These helpers make
# that drift visible on search_skills()/health(). The signature fingerprints
# CONTENT (not mtime) so it agrees with reindex's skip logic; the per-prompt
# enforcer does NOT go through this path — only the infrequent search_skills()/
# health() do.
# ---------------------------------------------------------------------------
def _disk_signature() -> dict:
    """Content fingerprint of skills on disk: count + hash of (name, content-hash),
    keyed by deduped skill NAME using the SAME signal reindex skips on
    (`_content_hash(_skill_text(s))`). This is the fix for the chronic false
    'disk changed since last index': a mtime-only event (re-clone, `/plugin update`
    re-materializing cache dirs, `touch`, a formatting-only save) leaves the CONTENT
    unchanged, so the detector and the reindex skip logic now agree on what 'changed'
    means — the flag stops false-firing, and it naturally collapses the multi-cached-
    version path churn to the deduped set that is actually indexed."""
    # ponytail: full re-parse per call; if search latency ever measures as a problem,
    # cache the signature in-process and recompute only on a cheap count/mtime tripwire.
    by_name = {}
    for s in discover_skills():
        by_name[s["name"]] = _content_hash(_skill_text(s))
    h = hashlib.md5()
    for name in sorted(by_name):
        h.update(f"{name}:{by_name[name]}".encode())
    return {"count": len(by_name), "hash": h.hexdigest()}


def _write_manifest(indexed: int) -> None:
    """Record what the index reflects, so later runs can detect drift."""
    sig = _disk_signature()
    META_PATH.parent.mkdir(parents=True, exist_ok=True)
    META_PATH.write_text(json.dumps({
        "indexed": indexed,
        "indexed_at": time.time(),
        "backend": EMBED_BACKEND,
        "model": EMBED_MODEL,
        "dim": vector_size(),
        "signature": sig,
    }, indent=2))


def _read_manifest() -> dict | None:
    try:
        return json.loads(META_PATH.read_text())
    except Exception:
        return None


def _staleness_warning() -> str | None:
    """One-line warning if disk has drifted from the last index, else None.
    Fails open: any error returns None rather than breaking search."""
    try:
        manifest = _read_manifest()
        if manifest is None:
            return "index manifest missing — run reindex() (results may be empty/stale)"
        if _disk_signature() != manifest.get("signature"):
            return ("skills changed on disk since last index — run reindex() "
                    "or some skills will be missing/stale in results")
    except Exception:
        return None
    return None


# ---------------------------------------------------------------------------
# Embedding layer. Backend-pluggable + batch-capable so reindex doesn't make
# N sequential round-trips. Swap a backend by editing only this section.
# ---------------------------------------------------------------------------
_fe_model = None


def _fastembed_model():
    """Lazily load the fastembed model (downloads once, then local/offline)."""
    global _fe_model
    if _fe_model is None:
        from fastembed import TextEmbedding            # optional dep
        _fe_model = TextEmbedding(model_name=EMBED_MODEL)
    return _fe_model


def _ollama_embed_one(text: str) -> list[float]:
    resp = requests.post(f"{OLLAMA_URL}/api/embeddings",
                         json={"model": EMBED_MODEL, "prompt": text}, timeout=30)
    resp.raise_for_status()
    return resp.json()["embedding"]


def _ollama_embed_batch(texts: list[str]) -> list[list[float]]:
    """Prefer Ollama's batch endpoint; fall back to the legacy single one so
    this works across Ollama versions (fail loud only if BOTH paths fail)."""
    try:
        resp = requests.post(f"{OLLAMA_URL}/api/embed",
                             json={"model": EMBED_MODEL, "input": texts}, timeout=120)
        resp.raise_for_status()
        embs = resp.json().get("embeddings")
        if embs and len(embs) == len(texts):
            return embs
    except Exception as e:
        # Not fatal — fall back to the legacy per-item endpoint. But log WHY, so a
        # silent degradation to N sequential calls is visible when debugging.
        log.debug("ollama batch embed failed, falling back to per-item: %s", e)
    return [_ollama_embed_one(t) for t in texts]


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed many strings at once. Raises on failure (fail loud, not silent)."""
    if not texts:
        return []
    if EMBED_BACKEND == "fastembed":
        return [list(map(float, v)) for v in _fastembed_model().embed(texts)]
    return _ollama_embed_batch(texts)


def embed(text: str) -> list[float]:
    """Embed one string (used for the search query)."""
    return embed_batch([text])[0]


_vsize = None


def vector_size() -> int:
    """Embedding dimension. Probed from the live backend unless pinned via
    SKILL_VECTOR_SIZE — so switching backends can't silently mismatch the
    collection's configured size."""
    global _vsize
    if _vsize is None:
        env = os.environ.get("SKILL_VECTOR_SIZE")
        _vsize = int(env) if env else len(embed("dimension probe"))
    return _vsize


# ---------------------------------------------------------------------------
# Indexing helpers. Skill parsing/discovery lives in skills_discovery.py so the
# index and the budget-override generator can never drift to different sets.
# ---------------------------------------------------------------------------
def _point_id(name: str) -> str:
    """Stable Qdrant point id from skill name (so reindex upserts, not dupes).
    Qdrant requires a UUID or u64 — md5 of the name gives a deterministic UUID."""
    return str(uuid.UUID(hashlib.md5(name.encode()).hexdigest()))


def _content_hash(text: str) -> str:
    """Hash of the exact text we embed — lets reindex skip unchanged skills."""
    return hashlib.md5(text.encode()).hexdigest()


# Trigger-phrase derivation for the multi-vector layer. MIRRORS scripts/build_triggers.py
# split_phrases (kept in sync by hand so the vendored package stays self-contained — no
# cross-dependency on scripts/). Splits a skill description into intent-bearing phrases.
_SPLIT_RE = re.compile(r"(?:[.;!?]\s+|\s+[—–]\s+|\n+|^\s*[-*•]\s+)", re.MULTILINE)
_LABEL_RE = re.compile(r"^\s*(triggers?|examples?|use when|also use|use this skill)\b[:\-]?\s*", re.I)
_WS_RE = re.compile(r"\s+")
_TRIG_MAX = int(os.environ.get("TRIGGERS_MAX", "12"))
_TRIG_MIN_WORDS, _TRIG_MIN_CHARS = 3, 12


def _split_phrases(description: str) -> list:
    """Description -> deduped intent-bearing phrases (order-preserving), capped at _TRIG_MAX."""
    if not description:
        return []
    out, seen = [], set()
    for p in _SPLIT_RE.split(description):
        p = _LABEL_RE.sub("", p or "")
        p = _WS_RE.sub(" ", p).strip().strip("\"'`()[]")
        if len(p) < _TRIG_MIN_CHARS or len(p.split()) < _TRIG_MIN_WORDS:
            continue
        k = p.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(p)
    return out[:_TRIG_MAX]


def _trigger_phrases(s: dict) -> list:
    """Trigger-point phrases for one skill: description-derived first, then (if
    SKILL_BODY_TRIGGERS) body-derived, deduped against the description and capped
    COMBINED at _TRIG_MAX — so per-skill triggers never exceed the SAME ceiling (12)
    description-only already had. Growth is BOUNDED, not additive-on-top; but the
    TOTAL point count DOES rise, because most skills left slots empty (median
    description uses ~3 of 12) that body phrases now fill. Measured live: 2231 ->
    3570 (+60%) — well under full-body chunking's 2-4x. Already-verbose descriptions
    at the cap get no body phrases."""
    phrases = _split_phrases(s["description"])
    if SKILL_BODY_TRIGGERS:
        seen = {p.lower() for p in phrases}
        body_text = "\n".join(s.get("body_triggers") or [])
        for p in _split_phrases(body_text):
            if p.lower() not in seen:
                seen.add(p.lower())
                phrases.append(p)
    return phrases[:_TRIG_MAX]


def _skill_text(s: dict) -> str:
    """The text we embed: name + description + body (meaning, not just name)."""
    return f"{s['name']}\n{s['description']}\n{s['body']}"


def _collection_dim() -> int | None:
    """Vector size the existing collection was created with, or None if absent.
    Used to catch an embedder swap (different dim) before it corrupts the index."""
    try:
        vectors = _qdrant.get_collection(COLLECTION).config.params.vectors
        if hasattr(vectors, "size"):                 # unnamed single vector
            return vectors.size
        if isinstance(vectors, dict) and vectors:    # named vectors
            return getattr(next(iter(vectors.values())), "size", None)
    except Exception:
        return None
    return None


def _ensure_collection() -> None:
    if not _qdrant.collection_exists(COLLECTION):
        _qdrant.create_collection(
            collection_name=COLLECTION,
            vectors_config=VectorParams(size=vector_size(), distance=Distance.COSINE),
        )
    # Keyword index on `name` so the MAX-pool group_by retrieval is fast + exact. Idempotent:
    # a re-create raises, so swallow it. group_by still works unindexed (just slower).
    try:
        _qdrant.create_payload_index(
            collection_name=COLLECTION, field_name="name",
            field_schema=models.PayloadSchemaType.KEYWORD)
    except Exception:
        pass


def _existing_points() -> dict[str, str]:
    """Map point-id -> stored content_hash for everything currently indexed.
    Used to decide what actually needs re-embedding."""
    existing: dict[str, str] = {}
    if not _qdrant.collection_exists(COLLECTION):
        return existing
    offset = None
    while True:
        points, offset = _qdrant.scroll(
            collection_name=COLLECTION, limit=256,
            with_payload=["content_hash"], with_vectors=False, offset=offset)
        for p in points:
            existing[str(p.id)] = (p.payload or {}).get("content_hash")
        if offset is None:
            break
    return existing


# ---------------------------------------------------------------------------
# Index build: INCREMENTAL by default. Only new/changed skills are embedded;
# points for deleted skills are removed. force=True does a clean full rebuild.
# ---------------------------------------------------------------------------
def build_index(force: bool = False) -> dict:
    skills = discover_skills()

    # Guard the embedder-swap footgun: a collection built at one dimension can't
    # take vectors of another. Tell the user to rebuild instead of failing cryptically.
    if not force:
        cdim = _collection_dim()
        if cdim is not None and cdim != vector_size():
            raise RuntimeError(
                f"embedding dimension changed ({cdim} -> {vector_size()}); the index "
                f"was built with a different embedder. Rerun with force=True (--rebuild).")

    if force and _qdrant.collection_exists(COLLECTION):
        _qdrant.delete_collection(COLLECTION)
    _ensure_collection()

    existing = {} if force else _existing_points()

    # Desired end state: point-id -> (text-to-embed, content_hash, payload).
    # Each skill gets ONE base point (name+desc+body); with MULTIVECTOR on it also gets one
    # TRIGGER point per intent phrase from its description and (SKILL_BODY_TRIGGERS) its
    # body's labeled decision-sections, MAX-pooled at query time via group_by name. Stable
    # per-(skill, slot) ids keep reindex incremental and reindex-safe (a plain reindex
    # maintains the trigger layer — no separate overlay/reapply needed).
    desired: dict[str, tuple] = {}
    for s in skills:
        text = _skill_text(s)
        h = _content_hash(text)
        desired[_point_id(s["name"])] = (text, h, {
            "name": s["name"], "description": s["description"],
            "path": s["path"], "content_hash": h, "kind": "base"})
        if MULTIVECTOR:
            for i, ph in enumerate(_trigger_phrases(s)):
                ph_h = _content_hash(ph)
                desired[_point_id(f"{s['name']}::trig::{i}")] = (ph, ph_h, {
                    "name": s["name"], "description": s["description"],
                    "content_hash": ph_h, "kind": "trigger"})

    # Embed only what's new or whose text changed; delete what's gone (incl. orphaned
    # trigger slots when a description shortens, and ALL triggers if MULTIVECTOR is turned off).
    changed = [(pid, d) for pid, d in desired.items() if existing.get(pid) != d[1]]
    removed = [pid for pid in existing if pid not in desired]

    # Embed AND upsert per chunk — upserting all points in one call overflows Qdrant's
    # 33MB request limit once the multi-vector layer pushes the point count into the thousands.
    for i in range(0, len(changed), EMBED_BATCH):
        chunk = changed[i:i + EMBED_BATCH]
        vecs = embed_batch([d[0] for _, d in chunk])
        pts = [PointStruct(id=pid, vector=vec, payload=payload)
               for (pid, (_text, _h, payload)), vec in zip(chunk, vecs)]
        _qdrant.upsert(collection_name=COLLECTION, points=pts)
    if removed:
        _qdrant.delete(collection_name=COLLECTION,
                       points_selector=models.PointIdsList(points=removed))

    n_skills = len({d[2]["name"] for d in desired.values()})
    _write_manifest(n_skills)
    return {"indexed": n_skills, "points": len(desired), "embedded": len(changed),
            "deleted": len(removed), "skipped": len(desired) - len(changed)}


def _indexed_names() -> set[str]:
    """Names currently present as points in the Qdrant collection."""
    names: set[str] = set()
    offset = None
    while True:
        points, offset = _qdrant.scroll(
            collection_name=COLLECTION, limit=256,
            with_payload=["name"], with_vectors=False, offset=offset)
        names.update((p.payload or {}).get("name") for p in points)
        if offset is None:
            break
    return names


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------
def _fuse_ranked(group_lists: list, top_k: int) -> list:
    """MAX-pool skills across one or more query result sets: each skill keeps its
    single BEST score across all queries, then return the fused top-k by score.
    One query angle can bury the precise skill below the cut; fusing several
    angles lifts it. With a single query this is identical to the old top-k."""
    best: dict = {}  # name -> (score, description)
    for groups in group_lists:
        for g in groups:
            if not g.hits:
                continue
            h = g.hits[0]
            pl = h.payload or {}
            name = pl.get("name", g.id)
            if name not in best or h.score > best[name][0]:
                best[name] = (h.score, pl.get("description", ""))
    ranked = sorted(best.items(), key=lambda kv: kv[1][0], reverse=True)[:top_k]
    return [{"name": n, "command": f"/{n}", "description": d, "score": round(s, 4)}
            for n, (s, d) in ranked]


@mcp.tool()
def search_skills(query: str, extra_queries: list[str] | None = None) -> str:
    """Find skills relevant to a task by SEMANTIC match over full descriptions.
    Returns ranked {name, description, score}. Claude should then invoke the
    relevant ones by name (e.g. /frontend-design).

    Query by INTENT + DOMAIN TERMS, not the raw user sentence. For best recall,
    pass 2-3 varied phrasings of the same need in `extra_queries` — the server
    embeds every phrasing and scores each skill by its single best-matching
    phrasing across all of them (MAX-pool over the query union), so a skill a
    single phrasing would bury still surfaces."""
    # group_by name + group_size=1 keeps each skill's single BEST point (on the
    # multi-vector index, its best-matching phrase point — the recall lever).
    queries = [query] + [q for q in (extra_queries or []) if q and q.strip()]
    group_lists = [
        _qdrant.query_points_groups(
            collection_name=COLLECTION, query=qv, group_by="name",
            limit=TOP_K, group_size=1, with_payload=True).groups
        for qv in embed_batch(queries)
    ]
    out = {"query": query, "results": _fuse_ranked(group_lists, TOP_K)}
    if len(queries) > 1:
        out["queries"] = queries
    # Surface index drift in-band so dark/stale skills don't fail silently.
    warning = _staleness_warning()
    if warning:
        out["warning"] = warning
    return json.dumps(out, indent=2)


@mcp.tool()
def get_skill(name: str) -> str:
    """Return the full SKILL.md text for a named skill (explicit deep pull)."""
    name = name.lstrip("/")
    # Fast path: resolve the file path from the index payload — O(1) lookup,
    # no walking/parsing every SKILL.md on disk.
    try:
        recs = _qdrant.retrieve(collection_name=COLLECTION,
                                ids=[_point_id(name)], with_payload=True)
        if recs:
            path = (recs[0].payload or {}).get("path")
            if path and Path(path).exists():
                return Path(path).read_text(encoding="utf-8")
    except Exception:
        pass
    # Fallback: added since last reindex / index unavailable -> walk disk once.
    for s in discover_skills():
        if s["name"] == name:
            return Path(s["path"]).read_text(encoding="utf-8")
    return json.dumps({"error": f"skill '{name}' not found"})


@mcp.tool()
def reindex(force: bool = False) -> str:
    """Update the semantic index. Incremental by default: only new/changed
    skills are re-embedded and deleted skills are dropped. Pass force=True for
    a full clean rebuild. Run after adding/removing/editing skills."""
    stats = build_index(force=force)
    return json.dumps({**stats, "collection": COLLECTION})


def _health() -> dict:
    """Full diagnostic of the retrieval path. Because skills are name-only, a
    silent failure here = skills go dark, so report every degraded dependency
    and the exact dark/stale skills, not just an overall up/down."""
    report: dict = {"status": "ok", "issues": []}

    # Dependency: embedding backend — probe a real embed (the true signal, and
    # backend-agnostic: works for ollama and fastembed alike).
    try:
        dim = len(embed("health probe"))
        report["embedder"] = {"backend": EMBED_BACKEND, "model": EMBED_MODEL,
                              "reachable": True, "dim": dim}
    except Exception as e:
        report["embedder"] = {"backend": EMBED_BACKEND, "model": EMBED_MODEL,
                              "reachable": False, "error": str(e)}
        report["issues"].append(
            f"embedding backend '{EMBED_BACKEND}' ({EMBED_MODEL}) unavailable")

    # Dependency: Qdrant + the collection, and disk-vs-index drift.
    disk_names = {s["name"] for s in discover_skills()}
    try:
        indexed = _indexed_names()
        report["qdrant"] = {"store": _STORE, "reachable": True, "indexed": len(indexed)}
        dark = sorted(disk_names - indexed)    # on disk, NOT searchable
        stale = sorted(indexed - disk_names)   # indexed, deleted from disk
        report["disk_skills"] = len(disk_names)
        report["dark_skills"] = dark
        report["stale_points"] = stale
        if dark:
            report["issues"].append(f"{len(dark)} skill(s) on disk but not indexed "
                                    f"(invisible to search) — run reindex()")
        if stale:
            report["issues"].append(f"{len(stale)} indexed skill(s) deleted from disk "
                                    f"(dead results) — run reindex()")
        # Embedder swap guard: collection dim vs what the live backend produces.
        cdim = _collection_dim()
        edim = report["embedder"].get("dim")
        report["qdrant"]["dim"] = cdim
        if cdim and edim and cdim != edim:
            report["issues"].append(
                f"collection built at dim {cdim} but backend '{EMBED_BACKEND}' now "
                f"produces {edim} — embedder changed; run reindex(force=True)/--rebuild")
    except Exception as e:
        report["qdrant"] = {"store": _STORE, "reachable": False, "error": str(e)}
        report["issues"].append(f"qdrant/collection unavailable at {_STORE} "
                                f"('{COLLECTION}') — run reindex()")

    # Freshness: when was the index last built, and has disk changed since?
    manifest = _read_manifest()
    if manifest:
        report["indexed_at"] = manifest.get("indexed_at")
        report["stale"] = _disk_signature() != manifest.get("signature")
        if report["stale"]:
            report["issues"].append("disk changed since last index — run reindex()")
    else:
        report["indexed_at"] = None
        report["issues"].append("no index manifest — never indexed; run reindex()")

    if report["issues"]:
        report["status"] = "degraded"
    return report


@mcp.tool()
def health() -> str:
    """Report retrieval health: embedder/Qdrant reachability, how many skills are
    indexed vs on disk, which skills are DARK (on disk but unsearchable) or stale,
    and whether a reindex is needed. Run this when search results look wrong."""
    return json.dumps(_health(), indent=2)


def main() -> None:
    """Console entry point (`skill-search`). No args -> run the MCP server (stdio);
    `--reindex` incremental (add --force for full rebuild); `--rebuild` full;
    `--health` diagnose (exits non-zero when degraded, for cron/CI)."""
    if "--reindex" in sys.argv or "--rebuild" in sys.argv:
        force = "--rebuild" in sys.argv or "--force" in sys.argv
        print(json.dumps({**build_index(force=force), "collection": COLLECTION}))
    elif "--health" in sys.argv:
        report = _health()
        print(json.dumps(report, indent=2))
        sys.exit(0 if report["status"] == "ok" else 1)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
