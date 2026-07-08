#!/usr/bin/env python3
"""
flywheel_manifest.py — shared run manifest for the retrieval flywheel (ADR-0027 Phase 2).
Stdlib only.

Canonical durable home: ~/.claude/skill-concierge/flywheel-manifest.json — survives repo
pulls/reinstalls (mirrors the log-dir convention in hooks/scripts/auto_reindex.py). Both the
SessionStart auto-hook (hooks/scripts/auto_flywheel.py) and the manual
`scripts/flywheel.py --generate` append one run record here, so any agent or the user can
see what the background flywheel did without watching a live process — read via
read_manifest() / last_run(), no need to invoke the flywheel itself.

Usage:
  python3 scripts/flywheel_manifest.py --selftest
"""
import json
import os
import time
from pathlib import Path

MANIFEST_PATH = Path(os.environ.get(
    "FLYWHEEL_MANIFEST", Path.home() / ".claude/skill-concierge/flywheel-manifest.json"))
MAX_RUNS = 20  # bounded history — the last run is what matters, older ones are just breadcrumbs


def read_manifest():
    """Return the manifest dict, or an empty shell if none exists yet / it's unreadable."""
    try:
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"runs": []}


def last_run():
    """Return the most recent run record (dict), or None if no run has ever completed."""
    runs = read_manifest().get("runs") or []
    return runs[-1] if runs else None


def write_run(endpoint, model, skills, coverage, totals=None, last_error=None):
    """Append one run record, capped to the last MAX_RUNS.

    skills   : list of {"name", "status": "generated"|"error", "when"} — only skills
               actually attempted this run (cache-hit/unchanged skills are omitted; their
               count lives in totals["skipped"]).
    coverage : {"have": N, "total": M} — post-run index coverage.
    totals   : {"generated", "error", "skipped"} counts; derived from `skills` (skipped=0)
               when not given by the caller.
    last_error: a short string describing a run-level failure (venv missing, endpoint
               unreachable, generator crash), or None on a clean run.
    """
    if totals is None:
        totals = {
            "generated": sum(1 for s in skills if s.get("status") == "generated"),
            "error": sum(1 for s in skills if s.get("status") == "error"),
            "skipped": 0,
        }
    manifest = read_manifest()
    runs = manifest.get("runs") or []
    runs.append({
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "endpoint": endpoint,
        "model": model,
        "skills": skills,
        "totals": totals,
        "coverage": coverage,
        "last_error": last_error,
    })
    manifest["runs"] = runs[-MAX_RUNS:]
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = MANIFEST_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(MANIFEST_PATH)  # atomic — a concurrent reader never sees a half-written file
    return manifest["runs"][-1]


def _selftest():
    import tempfile

    global MANIFEST_PATH
    real = MANIFEST_PATH
    tmp_dir = Path(tempfile.mkdtemp())
    MANIFEST_PATH = tmp_dir / "flywheel-manifest.json"
    try:
        assert read_manifest() == {"runs": []}, "empty manifest should read as {'runs': []}"
        assert last_run() is None, "last_run() on empty manifest must be None"

        run1 = write_run(
            endpoint="http://x/v1/chat/completions", model="m1",
            skills=[{"name": "a", "status": "generated", "when": "t1"},
                    {"name": "b", "status": "error", "when": "t1"}],
            coverage={"have": 10, "total": 12},
        )
        assert run1["totals"] == {"generated": 1, "error": 1, "skipped": 0}, run1["totals"]
        assert last_run()["coverage"] == {"have": 10, "total": 12}

        write_run(endpoint="e", model="m2", skills=[], coverage={"have": 12, "total": 12},
                  totals={"generated": 0, "error": 0, "skipped": 12}, last_error=None)
        assert last_run()["model"] == "m2", "last_run() must return the most recent run"
        assert len(read_manifest()["runs"]) == 2

        write_run(endpoint="e", model="m3", skills=[], coverage={"have": 0, "total": 0},
                  last_error="endpoint unreachable")
        assert last_run()["last_error"] == "endpoint unreachable"

        # cap enforcement
        for i in range(MAX_RUNS + 5):
            write_run(endpoint="e", model=f"m{i}", skills=[], coverage={"have": 0, "total": 0})
        assert len(read_manifest()["runs"]) == MAX_RUNS, "run history must be capped to MAX_RUNS"
        assert last_run()["model"] == f"m{MAX_RUNS + 4}", "cap must keep the most recent runs"

        # atomic write leaves no stray .tmp file behind
        assert not MANIFEST_PATH.with_suffix(".tmp").exists()
    finally:
        MANIFEST_PATH = real
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)
    print("PASS")


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        _selftest()
    else:
        print(__doc__)
