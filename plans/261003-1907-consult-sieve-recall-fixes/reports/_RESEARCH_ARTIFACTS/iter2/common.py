"""Shared loader for iter2 exploration. Read-only on repo code and private data."""
import json, os, sys, time
from pathlib import Path
REPO = Path("/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge")
sys.path.insert(0, str(REPO / "scripts"))
import sieve_recall as SR

OUT = Path(__file__).resolve().parent

def load():
    """(srv, kept cases, gen) — the same 83 the gate kept (leak + gone dropped)."""
    srv = SR.load_engine()
    cases = SR.read_jsonl(SR.CASES)
    gen = SR.load_generated()
    names = {p["name"] for p in SR.scroll_base_points()}
    leak = set(SR.leak_dropped(cases, gen))
    cases = [c for c in cases if c["id"] not in leak and c["label"] in names]
    return srv, cases, gen

def groups(srv, vectors, limit, flt):
    return [srv._qdrant.query_groups(srv.COLLECTION, v, group_by="name", limit=limit, filter=flt)
            for v in vectors]

def fused(srv, gl, n):
    rows = srv._fuse_ranked(gl, n, with_paths=True)
    return [r for r in rows if not srv._blocked(r.get("name", ""))]

def engine(srv, qs, top_n, slots="0", rrf="0"):
    return SR.call_engine(srv, qs, top_n, slots, rrf)
