#!/usr/bin/env python3
"""Recall@k eval for skill-search retrieval.

For each labeled {query, expect[]}, a hit@k means at least one expected skill
appears in the top-k results. Reports recall@1/@3/@6 and lists misses so you can
see where retrieval is weak (the honest part — don't just trust the headline).

Usage:
    python eval/run_eval.py [path/to/labeled.jsonl]

Builds the index first if needed (incremental). Uses whatever embedder/store the
SKILL_* env selects; defaults to the service-free tier (fastembed + embedded Qdrant).
"""

import json
import sys
from pathlib import Path

from skill_search import server

KS = (1, 3, 6)


def load(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            rows.append(json.loads(line))
    return rows


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "labeled_queries.jsonl"
    rows = load(path)

    server.build_index()  # incremental; builds from empty on first run

    hits = {k: 0 for k in KS}
    misses = []
    for r in rows:
        names = [h["name"] for h in json.loads(server.search_skills(r["query"]))["results"]]
        expect = set(r["expect"])
        for k in KS:
            if expect & set(names[:k]):
                hits[k] += 1
        if not (expect & set(names[: max(KS)])):
            misses.append((r["query"], r["expect"], names[:3]))

    n = len(rows)
    print(f"labeled queries: {n}  (embedder: {server.EMBED_BACKEND}/{server.EMBED_MODEL})")
    for k in KS:
        print(f"recall@{k}: {hits[k] / n:.2f}  ({hits[k]}/{n})")
    if misses:
        print("\nmisses (no expected skill in top-6):")
        for q, exp, got in misses:
            print(f"  - {q!r}\n      expected one of {exp}\n      got {got}")

    # Informational benchmark — recall depends on your skill set + embedder, so
    # this isn't a pass/fail gate. Exits non-zero only if recall@6 < EVAL_MIN_RECALL
    # (default 0.0 = never fail), for anyone who wants to wire their own floor.
    import os
    floor = float(os.environ.get("EVAL_MIN_RECALL", "0.0"))
    sys.exit(0 if hits[max(KS)] / n >= floor else 1)


if __name__ == "__main__":
    main()
