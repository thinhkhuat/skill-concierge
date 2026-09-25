#!/usr/bin/env python3
"""Archive a Qdrant collection to disk, verify the archive, then optionally delete it.

Stdlib only. Three steps, each a subcommand, so deletion can never run on an
unverified archive:

  export  -> <dest>/points.jsonl (id, vector, payload per line)
             <dest>/<snapshot>.snapshot (Qdrant's own snapshot, downloaded)
             <dest>/manifest.json (collection info, counts, sha256s)
  verify  -> re-reads the archive: point count == --expect, every line has a
             vector of the collection's dimension, snapshot present and its
             sha256 matches the manifest. Exit 0 only when all hold.
  delete  -> runs verify first; deletes the live collection only if it passes.

Usage:
  archive_qdrant_collection.py export --collection C --dest DIR
  archive_qdrant_collection.py verify --dest DIR --expect N
  archive_qdrant_collection.py delete --collection C --dest DIR --expect N
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

DEFAULT_URL = "http://127.0.0.1:6333"


def _req(url: str, method: str = "GET", body: dict | None = None, timeout: float = 120):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def export(base: str, collection: str, dest: Path) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    info = _req(f"{base}/collections/{collection}")["result"]
    points_path = dest / "points.jsonl"
    n = 0
    offset = None
    with points_path.open("w") as out:
        while True:
            body = {"limit": 256, "with_payload": True, "with_vector": True}
            if offset is not None:
                body["offset"] = offset
            res = _req(f"{base}/collections/{collection}/points/scroll", "POST", body)["result"]
            for p in res["points"]:
                out.write(json.dumps({"id": p["id"], "vector": p["vector"],
                                      "payload": p.get("payload")}) + "\n")
                n += 1
            offset = res.get("next_page_offset")
            if offset is None:
                break

    snap = _req(f"{base}/collections/{collection}/snapshots", "POST", timeout=600)["result"]
    snap_path = dest / snap["name"]
    with urllib.request.urlopen(
            f"{base}/collections/{collection}/snapshots/{snap['name']}", timeout=600) as resp, \
            snap_path.open("wb") as f:
        while chunk := resp.read(1 << 20):
            f.write(chunk)

    manifest = {
        "collection": collection,
        "source": base,
        "collection_info": info,
        "points_file": points_path.name,
        "points_exported": n,
        "points_sha256": _sha256(points_path),
        "snapshot_file": snap_path.name,
        "snapshot_size": snap_path.stat().st_size,
        "snapshot_sha256": _sha256(snap_path),
        "snapshot_server_checksum": snap.get("checksum"),
    }
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"exported {n} points + snapshot {snap_path.name} to {dest}")
    return 0


def verify(dest: Path, expect: int) -> int:
    errors = []
    manifest = json.loads((dest / "manifest.json").read_text())
    dim = manifest["collection_info"]["config"]["params"]["vectors"]["size"]
    points_path = dest / manifest["points_file"]
    n, ids = 0, set()
    with points_path.open() as f:
        for line in f:
            p = json.loads(line)
            ids.add(str(p["id"]))
            if not isinstance(p.get("vector"), list) or len(p["vector"]) != dim:
                errors.append(f"point {p['id']}: vector missing or dim != {dim}")
            if p.get("payload") is None:
                errors.append(f"point {p['id']}: payload missing")
            n += 1
    if n != expect:
        errors.append(f"points.jsonl has {n} points, expected {expect}")
    if len(ids) != n:
        errors.append(f"duplicate ids: {n} lines, {len(ids)} unique ids")
    if _sha256(points_path) != manifest["points_sha256"]:
        errors.append("points.jsonl sha256 does not match manifest")
    snap_path = dest / manifest["snapshot_file"]
    if not snap_path.is_file() or snap_path.stat().st_size == 0:
        errors.append(f"snapshot missing or empty: {snap_path}")
    elif _sha256(snap_path) != manifest["snapshot_sha256"]:
        errors.append("snapshot sha256 does not match manifest")
    elif manifest.get("snapshot_server_checksum") and \
            manifest["snapshot_server_checksum"] != manifest["snapshot_sha256"]:
        errors.append("snapshot sha256 does not match Qdrant's reported checksum")
    for e in errors:
        print(e, file=sys.stderr)
    if errors:
        return 1
    print(f"verified: {n} points (dim {dim}, unique ids, payloads present), "
          f"snapshot {snap_path.name} {snap_path.stat().st_size} bytes sha256 ok")
    return 0


def delete(base: str, collection: str, dest: Path, expect: int) -> int:
    if verify(dest, expect) != 0:
        print(f"refusing to delete {collection}: archive verification failed", file=sys.stderr)
        return 1
    res = _req(f"{base}/collections/{collection}", "DELETE")
    print(f"deleted {collection}: {json.dumps(res.get('result'))}")
    return 0 if res.get("result") is True else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Archive, verify, then delete a Qdrant collection.")
    ap.add_argument("cmd", choices=("export", "verify", "delete"))
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--collection")
    ap.add_argument("--dest", required=True, type=Path)
    ap.add_argument("--expect", type=int)
    a = ap.parse_args()
    dest = a.dest.expanduser()
    if a.cmd in ("export", "delete") and not a.collection:
        ap.error("--collection is required")
    if a.cmd in ("verify", "delete") and a.expect is None:
        ap.error("--expect is required")
    if a.cmd == "export":
        return export(a.url, a.collection, dest)
    if a.cmd == "verify":
        return verify(dest, a.expect)
    return delete(a.url, a.collection, dest, a.expect)


if __name__ == "__main__":
    sys.exit(main())
