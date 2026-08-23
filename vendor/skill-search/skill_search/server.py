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
from skill_search import skills_discovery as sd
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
# LLM-utterance trigger points (v0.16.0, ADR-0026): layer the offline-generated per-skill
# utterance triggers (eval/triggers.json `llm_triggers` block, produced by
# scripts/llm_triggers.py) into the SAME MAX-pool trigger layer, FIRST (highest
# quality phrases win the capped slots), ahead of description/body phrases.
# Default OFF = byte-identical to today; set SKILL_LLM_TRIGGERS=1 + reindex to enable.
SKILL_LLM_TRIGGERS = os.environ.get("SKILL_LLM_TRIGGERS", "0") != "0"
_LLM_TRIG_PATH = os.environ.get(
    "SKILL_TRIGGERS", str(Path(__file__).resolve().parent.parent.parent.parent / "eval" / "triggers.json"))
# Index manifest: lets us detect drift between disk and the index cheaply. Keyed per
# project root — the signature it stores is CWD-scoped, so one shared file would make
# every session with a different project report a false 'disk changed since last index'.
META_PATH       = Path(os.environ.get(
    "SKILL_META_PATH",
    str(Path.home() / ".cache" / "skill-search" / f"index_meta-{sd.manifest_key()}.json")))
# One file per live MCP server, `<pid>.json`, recording the engine build that process
# actually runs. NOT keyed per project root — a reader (doctor) asks "which builds are
# live on this machine", a question no single project's manifest can answer.
SERVER_RECORDS  = Path(os.environ.get(
    "SKILL_SERVER_RECORDS", str(Path.home() / ".cache" / "skill-search" / "servers")))
# ADR-0029 chain-hint sidecar: {scope: {name: [successors]}} for EVERY indexed skill
# (empty list when unauthored — the enforcer's hint filter uses key presence as
# catalogue membership). Lives under ~/.claude/skill-concierge/ next to the ledger the
# reading hook already owns, not in the engine cache. Written UNCONDITIONALLY at index
# time: its content is flag-independent; ENFORCER_CHAIN_HINT gates only the reader.
NEXT_SKILLS_PATH = Path(os.environ.get(
    "SKILL_CONCIERGE_NEXT_SKILLS",
    str(Path.home() / ".claude" / "skill-concierge" / "next-skills.json")))

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


def _engine_build() -> str:
    """Fingerprint of the engine code THIS process actually loaded.

    Computed at import ON PURPOSE. The venv's engine files can be replaced under a
    long-lived MCP server (a setup.sh re-copy, or a repo build overwriting the deployed
    one), and the server keeps executing the bytes it imported at start. From then on the
    server and every fresh CLI process parse the same SKILL.md files with different
    parsers, so they derive different `_disk_signature()` values from an unchanged disk.
    Whichever one writes the manifest last makes the other report a false 'disk changed
    since last index' — permanently, for the life of that server process. Recording the
    build alongside the signature lets a reader tell "the disk moved" (reindex) apart from
    "we are different builds" (restart), instead of blaming the disk for both.

    Only these two modules are hashed because only they can move the parsed text:
    `_disk_signature` depends on `discover_skills()` (skills_discovery) and on
    `_skill_text`/`_content_hash` (this module). If skill parsing ever moves to a third
    module, add it here or the id silently stops discriminating and this bug returns
    with no test failure.
    """
    h = hashlib.md5()
    for mod in (__file__, sd.__file__):
        try:
            h.update(Path(mod).read_bytes())
        except Exception:
            # Broad on purpose: this runs at import on the server's critical path
            # (`sd.__file__` can be None under exotic loaders, which raises TypeError,
            # not OSError). Losing a diagnostic is acceptable; failing to import is not.
            return "unknown"                    # fail open: no id rather than a wrong one
    return h.hexdigest()[:12]


_ENGINE_BUILD = _engine_build()


def _record_server_build():
    """Publish "pid P runs build B" so a reader can look it up instead of guessing it.

    Nothing outside this process can otherwise learn which engine a long-lived server
    imported. The obvious substitute — dating the process against the engine files'
    mtime/ctime — does not work: setup.sh re-copies the engine on EVERY run, so the
    timestamps advance even when the bytes are byte-identical, and every live server gets
    accused of running old code after a routine no-op re-run. A build id moves only when
    the code moves, which is the actual question.

    `started_at` is what makes the record safe to trust. Pids are recycled; a stale
    record left by a dead server would otherwise hand its build to whatever process
    inherits the number — reintroducing the same false accusation, one layer down.

    Called only from the MCP-server path. CLI invocations (`--health`, `--reindex`) are
    short-lived and would just litter the directory with records for dead pids.

    Returns the path written, or None if anything went wrong: this sits on the server's
    startup path, and losing a diagnostic is acceptable where failing to start is not.
    """
    try:
        SERVER_RECORDS.mkdir(parents=True, exist_ok=True)
        path = SERVER_RECORDS / f"{os.getpid()}.json"
        body = json.dumps({
            "pid": os.getpid(),
            "build": _ENGINE_BUILD,
            "started_at": time.time(),
        })
        # Write-then-rename, because this file is read by a CONCURRENT process by design.
        # A plain write truncates first, so a reader arriving mid-write sees an empty or
        # half-written file, fails to parse it, and reports the server's build as unknown.
        # os.replace is atomic within a directory, so a reader sees old or new, never torn.
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(body)
        os.replace(tmp, path)
        return path
    except Exception:
        return None


def _write_manifest(indexed: int) -> None:
    """Record what the index reflects, so later runs can detect drift."""
    sig = _disk_signature()
    META_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Write-then-rename: a live server reads this file while the SessionStart reindex writes
    # it. A truncating write lets that reader see an empty or half-written file, parse nothing,
    # and report "no index manifest — never indexed" on a perfectly good index.
    _tmp = META_PATH.with_suffix(f".{os.getpid()}.tmp")
    _tmp.write_text(json.dumps({
        "indexed": indexed,
        "indexed_at": time.time(),
        "backend": EMBED_BACKEND,
        "model": EMBED_MODEL,
        "dim": vector_size(),
        "signature": sig,
        "engine": _ENGINE_BUILD,
    }, indent=2))
    os.replace(_tmp, META_PATH)          # atomic within the directory: old or new, never torn


def _write_next_skills_sidecar(skills: list[dict]) -> None:
    """ADR-0029: write the chain-hint sidecar {scope: {name: [successors]}}.

    Per-scope MERGE, not replace: this session writes ONLY the scopes it owns
    (`skills_discovery.visible_scopes()` — the same ownership rule `_prunable`
    enforces for points) and leaves foreign project scopes intact, so two
    concurrent sessions with different CWDs cannot last-writer-wins each other
    (the exact incident ADR-0028 records for the index itself). Write-then-
    `os.replace` for the same torn-read reason as `_write_manifest`. Unconditional
    and best-effort: a sidecar failure must never fail an index build.
    """
    try:
        mine: dict[str, dict[str, list]] = {}
        for s in skills:
            scope = s.get("scope", "personal")
            # ADR-0031: catalog skills stay OUT of the sidecar. Sidecar key presence
            # is the enforcer's catalogue-membership signal for chain hints — a
            # preview-layer mechanism — and catalog skills are search-only by
            # decision; admitting 1.5k+ external names would let chains hint skills
            # the Skill tool cannot invoke.
            if scope.startswith("catalog:"):
                continue
            mine.setdefault(scope, {})[s["name"]] = list(s.get("next_skills") or [])
        try:
            merged = json.loads(NEXT_SKILLS_PATH.read_text(encoding="utf-8"))
            if not isinstance(merged, dict):
                merged = {}
        except Exception:
            merged = {}
        merged.update(mine)
        NEXT_SKILLS_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = NEXT_SKILLS_PATH.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, NEXT_SKILLS_PATH)
    except Exception as exc:
        log.warning("next-skills sidecar write failed: %s", exc)


def _read_manifest() -> dict | None:
    try:
        return json.loads(META_PATH.read_text())
    except Exception:
        return None


def _engine_drift(manifest: dict) -> str | None:
    """The manifest writer's engine build, when it differs from ours — else None.

    A manifest written by a DIFFERENT build carries a signature computed by a different
    parser, so comparing it against ours says nothing about the disk. Pre-`engine`
    manifests (no key) are treated as ours: we cannot tell, and guessing drift would
    reintroduce the false alarm this exists to remove.
    """
    other = manifest.get("engine")
    if not other or other == "unknown" or _ENGINE_BUILD == "unknown":
        return None                 # a sentinel on EITHER side identifies no build, and
                                    # accusing it of drift would demand a restart that
                                    # fixes nothing — the same permanent false alarm this
                                    # exists to remove, relocated one field over.
    return other if other != _ENGINE_BUILD else None


def _staleness_warning() -> str | None:
    """One-line warning if disk has drifted from the last index, else None.
    Fails open: any error returns None rather than breaking search."""
    try:
        manifest = _read_manifest()
        if manifest is None:
            return "index manifest missing — run reindex() (results may be empty/stale)"
        if _engine_drift(manifest):
            # Two causes, opposite remedies, and this process can see neither: it knows its
            # own build and nothing about other processes. Leftover manifest from a previous
            # release -> a reindex re-stamps it. A server still live on the old build -> only
            # a restart helps. Naming one as fact is a coin flip every engine upgrade loses,
            # since changing the engine necessarily changes the build id.
            #
            # This string is read by the MODEL — it rides in every search_skills reply — so it
            # must not order a reindex either. `reindex()` is an MCP tool that runs INSIDE this
            # process, the one whose build is in question, and build ids are unordered hashes:
            # a server cannot tell whether its own build is the newer or the older one. If it
            # is the older one, reindexing here re-embeds with the stale parser and re-stamps
            # the manifest BACKWARD, fighting the session-start rebuild. Route to doctor, which
            # holds the live-server records and decides; the leftover case clears itself.
            return ("the index was built by a different engine build than this server runs, "
                    "so disk-vs-index comparison is unavailable — do not reindex from here, "
                    "this server's own build is what is in question. Run skill-concierge "
                    "doctor for the decided fix; the common case clears itself at the next "
                    "session start")
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


_LLM_TRIG_CACHE = None


def _llm_utterance_phrases(name: str) -> list:
    """LLM-utterance trigger phrases for `name` from eval/triggers.json (cached).
    Reads the `llm_triggers.triggers` block (scripts/llm_triggers.py output); [] if
    the file is absent/unreadable or the skill has no llm layer."""
    global _LLM_TRIG_CACHE
    if _LLM_TRIG_CACHE is None:
        try:
            d = json.loads(Path(_LLM_TRIG_PATH).read_text(encoding="utf-8"))
            _LLM_TRIG_CACHE = {
                k: ((v.get("llm_triggers") or {}).get("triggers") or [])
                for k, v in d.items() if isinstance(v, dict)}
        except Exception:
            _LLM_TRIG_CACHE = {}
    return _LLM_TRIG_CACHE.get(name, [])


def _trigger_phrases(s: dict) -> list:
    """Trigger-point phrases for one skill, deduped (case-insensitive) and capped
    COMBINED at _TRIG_MAX. Sources in QUALITY order: (if SKILL_LLM_TRIGGERS) the
    offline-generated utterance triggers FIRST, then description-derived, then (if
    SKILL_BODY_TRIGGERS) body-derived. Utterances-first means the best phrases win
    the capped slots; the cap keeps per-skill growth bounded (raise TRIGGERS_MAX to
    add slots rather than evict). TOTAL point count still rises because most skills
    left description slots empty. Flags default OFF/prior — byte-identical to before
    when unset."""
    phrases, seen = [], set()

    def _add(src):
        for p in src:
            k = p.lower()
            if k not in seen:
                seen.add(k)
                phrases.append(p)

    if SKILL_LLM_TRIGGERS:
        _add(_llm_utterance_phrases(s["name"]))
    _add(_split_phrases(s["description"]))
    if SKILL_BODY_TRIGGERS:
        _add(_split_phrases("\n".join(s.get("body_triggers") or [])))
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


def _existing_points() -> dict[str, tuple]:
    """Map point-id -> (stored content_hash, stored scope) for everything indexed.
    The hash decides what needs re-embedding; the scope decides what this process
    is allowed to delete. Legacy points predating scope tagging carry scope=None."""
    existing: dict[str, tuple] = {}
    if not _qdrant.collection_exists(COLLECTION):
        return existing
    offset = None
    while True:
        points, offset = _qdrant.scroll(
            collection_name=COLLECTION, limit=256,
            with_payload=["content_hash", "scope"], with_vectors=False, offset=offset)
        for p in points:
            pl = p.payload or {}
            existing[str(p.id)] = (pl.get("content_hash"), pl.get("scope"))
        if offset is None:
            break
    return existing


def _point_changed(stored: tuple | None, want_hash: str, want_scope: str) -> bool:
    """Re-embed when the text changed OR the owning scope changed. The scope arm
    is what migrates legacy scope-less points onto the scoped payload; without it
    an unchanged description would keep its scope-less payload forever and be
    filtered out of every search."""
    if stored is None:
        return True
    return stored[0] != want_hash or stored[1] != want_scope


def _prunable(existing: dict[str, tuple], desired: dict, visible: set[str]) -> list[str]:
    """Point-ids this process may delete: gone from disk AND owned by a scope we
    can see. A point in another session's project scope is invisible here — it is
    'not mine', not 'deleted'. Legacy scope-less points stay prunable so the
    migration can clear them."""
    return [pid for pid, (_h, scope) in existing.items()
            if pid not in desired and (scope is None or scope in visible)]


def _scope_filter():
    """Restrict a query to scopes this session owns. `scope is null` keeps legacy
    points searchable in the window between deploying this code and reindexing."""
    vis = sd.visible_scopes()
    return models.Filter(should=[
        *[models.FieldCondition(key="scope", match=models.MatchValue(value=s)) for s in sorted(vis)],
        models.IsNullCondition(is_null=models.PayloadField(key="scope")),
    ])


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
        scope = s.get("scope", "personal")
        # ADR-0031: catalog points carry tier=external so the per-turn enforcer can
        # exclude them with ONE must_not condition (search-only tier) without
        # enumerating aliases. On every point (base + trigger) — the enforcer's
        # group_by query scores whichever point ranks best.
        tier = {"tier": "external"} if scope.startswith("catalog:") else {}
        desired[_point_id(s["name"])] = (text, h, {
            "name": s["name"], "description": s["description"],
            "path": s["path"], "content_hash": h, "kind": "base", "scope": scope, **tier})
        if MULTIVECTOR:
            for i, ph in enumerate(_trigger_phrases(s)):
                ph_h = _content_hash(ph)
                desired[_point_id(f"{s['name']}::trig::{i}")] = (ph, ph_h, {
                    "name": s["name"], "description": s["description"],
                    "content_hash": ph_h, "kind": "trigger", "scope": scope, **tier})

    # Embed only what's new or whose text/scope changed. Delete what's gone (incl.
    # orphaned trigger slots when a description shortens, and ALL triggers if
    # MULTIVECTOR is turned off) — but ONLY within the scopes this session owns:
    # every session shares this collection, and another session's project skills
    # are invisible here, not deleted.
    changed = [(pid, d) for pid, d in desired.items()
               if _point_changed(existing.get(pid), d[1], d[2]["scope"])]
    removed = _prunable(existing, desired, sd.visible_scopes())

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
    _write_next_skills_sidecar(skills)   # ADR-0029: unconditional, per-scope merge
    _write_manifest(n_skills)
    return {"indexed": n_skills, "points": len(desired), "embedded": len(changed),
            "deleted": len(removed), "skipped": len(desired) - len(changed)}


def _indexed_names() -> set[str]:
    """Names indexed AND visible to this session.

    Scope-filtered on purpose: the collection is shared across sessions, so an
    unfiltered count diffed against this session's CWD-scoped disk view reported
    another project's skills as 'dark' (and this project's as 'stale') — a false
    alarm that invited a destructive reindex."""
    names: set[str] = set()
    offset = None
    while True:
        points, offset = _qdrant.scroll(
            collection_name=COLLECTION, limit=256, scroll_filter=_scope_filter(),
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
    angles lifts it. With a single query this is identical to the old top-k.

    ADR-0031: a hit from a `catalog:<alias>` scope is an EXTERNAL skill — merged
    into the same ranking (no artificial tier inside the list) but marked with
    provenance and the read-inline consumption note, because the Skill tool
    cannot invoke it; `get_skill(name)` returns its full body."""
    best: dict = {}  # name -> (score, description, scope)
    for groups in group_lists:
        for g in groups:
            if not g.hits:
                continue
            h = g.hits[0]
            pl = h.payload or {}
            name = pl.get("name", g.id)
            if name not in best or h.score > best[name][0]:
                best[name] = (h.score, pl.get("description", ""), pl.get("scope") or "")
    ranked = sorted(best.items(), key=lambda kv: kv[1][0], reverse=True)[:top_k]
    out = []
    for n, (s, d, scope) in ranked:
        row = {"name": n, "command": f"/{n}", "description": d, "score": round(s, 4)}
        if scope.startswith("catalog:"):
            row.pop("command")           # not a slash command — it is not installed
            row["external"] = scope.split(":", 1)[1]
            row["note"] = ("external catalog skill — NOT installed; consume by "
                           f"get_skill(\"{n}\") and follow its SKILL.md inline")
        out.append(row)
    return out


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
    # query_filter: never surface another session's project skills — this process
    # cannot invoke them, so offering them is a dead recommendation.
    scope_filter = _scope_filter()
    group_lists = [
        _qdrant.query_points_groups(
            collection_name=COLLECTION, query=qv, group_by="name",
            query_filter=scope_filter,
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
    # Which build we run is a FACT about this process, true with or without an index, so
    # it is published on every report rather than only when something is wrong. doctor
    # reads it as the yardstick for every live server; making it a drift-only flag would
    # mean the yardstick exists only once drift already does — and would push doctor into
    # re-deriving `_engine_build()`'s rule itself, a second copy free to stop agreeing.
    manifest = _read_manifest()
    report["engine_build"] = {"running": _ENGINE_BUILD, "index_written_by": None}
    if manifest:
        report["indexed_at"] = manifest.get("indexed_at")
        drift = _engine_drift(manifest)
        if drift:
            # Different builds parse skills differently, so the signature comparison is
            # meaningless here — reporting it would be the false 'disk changed' alarm.
            # None, not False: across builds the comparison is UNKNOWABLE, not negative.
            # False would tell every consumer the index matches disk. None reads as falsy
            # for the callers that only gate on it, and stays honest for the rest.
            report["stale"] = None
            report["engine_build"]["index_written_by"] = drift
            # State the OBSERVATION and offer both remedies as alternatives. Which one
            # applies turns on whether any OTHER process is still live on the old build —
            # invisible from here, and the reason `engine_build` is published as data:
            # doctor holds the live-server evidence and renders the decided remedy from it.
            # An earlier version asserted "a live MCP server is on a different build" and
            # "reindexing will not fix it". Both are false in the commoner case, a manifest
            # merely left over from the previous release — which EVERY engine upgrade
            # produces, because changing the engine necessarily changes the build id.
            # "this process", not "this server": _health() is also reached via the CLI
            # `--health` (that is how doctor calls it), where the older build, if any live
            # process really holds it, belongs to some OTHER long-lived server.
            report["issues"].append(
                f"index was built by engine {drift} but this process runs {_ENGINE_BUILD}, so "
                f"disk-vs-index comparison is unavailable — which fix applies turns on whether "
                f"any live server is still on {drift}, invisible from here. Run skill-concierge "
                f"doctor: it holds the live-server records and decides. Do not reindex from an "
                f"MCP server whose own build is what is in question")
        else:
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
        _record_server_build()      # only the long-lived path: CLI pids die immediately
        mcp.run()


if __name__ == "__main__":
    main()
