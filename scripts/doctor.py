#!/usr/bin/env python3
"""
skill-concierge doctor — deployment-layer health check + safe auto-fix.

Diagnoses the things `setup.sh` provisions — the stable engine venv, the Qdrant
container, the MCP wiring, the settings.json budget overrides, the ledger dir — and
DELEGATES the retrieval-path diagnostic (embedder reachability, indexed vs dark/stale
skills, freshness) to the engine's own `skill-search --health`, so the two never drift.

Pure stdlib. Read-only by default. With --fix it attempts ONLY fast, safe repairs:
  • start a stopped Qdrant container         → docker start
  • reindex a degraded / stale index         → skill-search --reindex
  • re-apply the curated settings overrides  → scripts/apply-overrides.py

The heavy bootstrap (building the venv, creating the container) is intentionally NOT
auto-run — that is `./setup.sh` (the `skill-concierge:setup` skill). doctor points there.

Usage:
  python3 scripts/doctor.py          # report only; exit 0 = healthy, 1 = degraded (FAIL)
  python3 scripts/doctor.py --fix    # attempt safe fixes, then re-check

Env seams (mirror setup.sh): SKILL_CONCIERGE_VENV, SKILL_QDRANT_URL, SKILL_QDRANT_CONTAINER,
SKILL_EMBED_BACKEND, SKILL_EMBED_MODEL, SKILL_CONCIERGE_SETTINGS, SKILL_CONCIERGE_LOG.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent              # skill-concierge/
VENV = Path(os.environ.get("SKILL_CONCIERGE_VENV", Path.home() / ".local/share/skill-concierge/venv"))
QNAME = os.environ.get("SKILL_QDRANT_CONTAINER", "skill-search-qdrant")
SETTINGS = Path(os.environ.get("SKILL_CONCIERGE_SETTINGS", Path.home() / ".claude/settings.json"))
LOGDIR = Path(os.environ.get("SKILL_CONCIERGE_LOG", Path.home() / ".claude/skill-telemetry/logs"))

OK, WARN, FAIL = "ok", "warn", "fail"
GLYPH = {OK: "✓", WARN: "!", FAIL: "✗"}           # ✓ ! ✗


def read_mcp_env():
    """Embedder + store come from .mcp.json (single source of truth); env overrides win."""
    env = {}
    try:
        env = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["skill-search"]["env"]
    except Exception:
        pass
    return (
        os.environ.get("SKILL_QDRANT_URL", env.get("SKILL_QDRANT_URL", "http://localhost:6333")),
        os.environ.get("SKILL_EMBED_BACKEND", env.get("SKILL_EMBED_BACKEND", "fastembed")),
        os.environ.get("SKILL_EMBED_MODEL", env.get("SKILL_EMBED_MODEL", "")),
    )


QURL, BACKEND, MODEL = read_mcp_env()
SS_BIN = VENV / "bin" / "skill-search"
PY_BIN = VENV / "bin" / "python"


def _run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def _engine_env():
    return {**os.environ, "SKILL_QDRANT_URL": QURL,
            "SKILL_EMBED_BACKEND": BACKEND, "SKILL_EMBED_MODEL": MODEL}


def _qdrant_reachable(timeout=3):
    for u in (QURL.rstrip("/") + "/healthz", QURL):
        try:
            with urllib.request.urlopen(u, timeout=timeout) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            continue
    return False


def _wait_qdrant(timeout=15):
    """Qdrant accepts connections a beat after the container starts — poll so a fix that
    starts it doesn't race the reindex that immediately follows (the reboot case)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _qdrant_reachable(timeout=2):
            return True
        time.sleep(1)
    return False


def _qdrant_container_running():
    """True/False if docker is present; None if docker is unavailable."""
    docker = shutil.which("docker")
    if not docker:
        return None
    r = _run([docker, "ps", "--format", "{{.Names}}"])
    return QNAME in r.stdout.split()


def _last_line(text):
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    return lines[-1] if lines else ""


# ---------- checks: each returns a dict (or None to skip) ----------

def check_python():
    if SS_BIN.exists():
        return None                                        # venv built — prereq moot
    found = next((c for c in ("python3.12", "python3.11", "python3.10") if shutil.which(c)), None)
    if found:
        return dict(id="python", label="Python 3.10-3.12", status=OK, detail=found, fix=None)
    return dict(id="python", label="Python 3.10-3.12", status=FAIL,
                detail="no python3.10-3.12 on PATH (set SKILL_PYTHON, then ./setup.sh)", fix="setup")


def check_venv():
    if SS_BIN.exists() and os.access(SS_BIN, os.X_OK):
        return dict(id="venv", label="Engine venv", status=OK, detail=str(VENV), fix=None)
    return dict(id="venv", label="Engine venv", status=FAIL,
                detail=f"no skill-search bin at {SS_BIN} — run ./setup.sh", fix="setup")


def check_mcp_wiring():
    launcher = ROOT / "bin" / "skill-search-mcp"
    probs = []
    mcp = ROOT / ".mcp.json"
    if not mcp.exists():
        probs.append(".mcp.json missing")
    else:
        try:
            json.loads(mcp.read_text(encoding="utf-8"))
        except Exception:
            probs.append(".mcp.json invalid JSON")
    if not launcher.exists():
        probs.append("bin/skill-search-mcp missing")
    elif not os.access(launcher, os.X_OK):
        probs.append("bin/skill-search-mcp not executable (chmod +x)")
    if probs:
        return dict(id="mcp", label="MCP wiring", status=FAIL, detail="; ".join(probs), fix=None)
    return dict(id="mcp", label="MCP wiring", status=OK, detail="launcher + .mcp.json present", fix=None)


def check_qdrant():
    if _qdrant_reachable():
        return dict(id="qdrant", label="Qdrant", status=OK, detail=QURL, fix=None)
    running = _qdrant_container_running()
    if running is False:
        return dict(id="qdrant", label="Qdrant", status=FAIL,
                    detail=f"container '{QNAME}' is stopped", fix="docker")
    if running is None:
        return dict(id="qdrant", label="Qdrant", status=FAIL,
                    detail=f"unreachable at {QURL}; docker not found (server tier needs it)", fix=None)
    return dict(id="qdrant", label="Qdrant", status=FAIL,
                detail=f"container up but {QURL} not answering yet", fix=None)


def check_engine_health():
    """Delegate the retrieval diagnostic to the engine itself (DRY)."""
    if not SS_BIN.exists():
        return dict(id="health", label="Retrieval health", status=FAIL,
                    detail="engine venv missing — run ./setup.sh", fix="setup")
    r = _run([str(SS_BIN), "--health"], env=_engine_env())
    try:
        rep = json.loads(r.stdout)
    except Exception:
        return dict(id="health", label="Retrieval health", status=FAIL,
                    detail=(r.stderr.strip() or "could not parse --health output")[:200], fix="reindex")
    issues = rep.get("issues") or []
    if rep.get("status") == "ok" and not issues:
        idx = rep.get("qdrant", {}).get("indexed", "?")
        return dict(id="health", label="Retrieval health", status=OK,
                    detail=f"{idx} skills indexed; embedder + qdrant reachable", fix=None)
    return dict(id="health", label="Retrieval health", status=FAIL,
                detail="; ".join(str(i) for i in issues)[:300], fix="reindex")


def check_overrides():
    if not SETTINGS.exists():
        return dict(id="overrides", label="Settings overrides", status=WARN,
                    detail=f"{SETTINGS} not found", fix="overrides")
    try:
        s = json.loads(SETTINGS.read_text(encoding="utf-8"))
    except Exception:
        return dict(id="overrides", label="Settings overrides", status=FAIL,
                    detail=f"{SETTINGS} invalid JSON", fix=None)
    ov = s.get("skillOverrides")
    if not ov:
        return dict(id="overrides", label="Settings overrides", status=WARN,
                    detail="no skillOverrides — budget not applied", fix="overrides")
    on = sum(1 for v in ov.values() if v == "on")
    return dict(id="overrides", label="Settings overrides", status=OK,
                detail=f"{on} on / {len(ov) - on} name-only", fix=None)


def check_ledger():
    try:
        LOGDIR.mkdir(parents=True, exist_ok=True)
        writable = os.access(LOGDIR, os.W_OK)
    except Exception as exc:
        return dict(id="ledger", label="Ledger dir", status=WARN, detail=str(exc), fix=None)
    return dict(id="ledger", label="Ledger dir", status=(OK if writable else WARN),
                detail=str(LOGDIR), fix=None)


def check_dup_mcp():
    claude = shutil.which("claude")
    if not claude:
        return None
    r = _run([claude, "mcp", "list"])
    if r.returncode != 0:
        return None
    hits = [ln for ln in r.stdout.splitlines() if "skill-search" in ln]
    if len(hits) > 1:
        return dict(id="dupmcp", label="Duplicate MCP", status=WARN,
                    detail="more than one skill-search MCP — de-dup: claude mcp remove skill-search -s user",
                    fix=None)
    return dict(id="dupmcp", label="Duplicate MCP", status=OK, detail="single skill-search MCP", fix=None)


CHECKS = [check_python, check_venv, check_mcp_wiring, check_qdrant,
          check_engine_health, check_overrides, check_ledger, check_dup_mcp]


# ---------- auto-fixers: return (ok, message). Only the safe/fast ones. ----------

def fix_docker_start():
    docker = shutil.which("docker")
    if not docker:
        return False, "docker not found"
    r = _run([docker, "start", QNAME])
    if r.returncode != 0:
        return False, (r.stderr.strip() or "docker start failed")
    if _wait_qdrant():
        return True, f"started container {QNAME} (ready)"
    return True, f"started container {QNAME} (still booting — re-run doctor shortly)"


def fix_reindex():
    if not SS_BIN.exists():
        return False, "venv missing — run ./setup.sh first"
    r = _run([str(SS_BIN), "--reindex"], env=_engine_env())
    return (r.returncode == 0), (_last_line(r.stdout) or r.stderr.strip() or "reindexed")


def fix_overrides():
    py = PY_BIN if PY_BIN.exists() else Path(sys.executable)
    r = _run([str(py), str(ROOT / "scripts" / "apply-overrides.py")])
    return (r.returncode == 0), (_last_line(r.stdout) or r.stderr.strip() or "applied")


AUTO_FIXERS = {"docker": fix_docker_start, "reindex": fix_reindex, "overrides": fix_overrides}


# ---------- run + report ----------

def run_all():
    return [c for c in (fn() for fn in CHECKS) if c]


def overall(results):
    if any(r["status"] == FAIL for r in results):
        return FAIL
    if any(r["status"] == WARN for r in results):
        return WARN
    return OK


def report(results):
    w = max((len(r["label"]) for r in results), default=0)
    for r in results:
        print(f"  [{GLYPH[r['status']]}] {r['label']:<{w}}  {r['detail']}")


def _selftest():
    mk = lambda s: dict(id="x", label="x", status=s, detail="", fix=None)
    assert overall([mk(OK), mk(OK)]) == OK
    assert overall([mk(OK), mk(WARN)]) == WARN
    assert overall([mk(WARN), mk(FAIL)]) == FAIL
    assert overall([]) == OK
    assert QURL.startswith("http")
    assert set(AUTO_FIXERS) <= {"docker", "reindex", "overrides"}
    print("selftest ok")
    return 0


def main():
    ap = argparse.ArgumentParser(description="skill-concierge deployment health check")
    ap.add_argument("--fix", action="store_true", help="attempt safe auto-fixes, then re-check")
    ap.add_argument("--selftest", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.selftest:
        return _selftest()

    print(f"skill-concierge doctor   (qdrant={QURL}  venv={VENV})\n")
    results = run_all()
    report(results)

    if args.fix:
        todo = [r for r in results if r["status"] in (FAIL, WARN) and r.get("fix") in AUTO_FIXERS]
        manual = [r for r in results if r["status"] in (FAIL, WARN)
                  and r.get("fix") and r.get("fix") not in AUTO_FIXERS]
        if todo:
            print("\napplying safe fixes:")
            for r in todo:
                ok, msg = AUTO_FIXERS[r["fix"]]()
                print(f"  [{GLYPH[OK] if ok else GLYPH[FAIL]}] {r['id']}: {msg}")
            print("\nre-checking:")
            results = run_all()
            report(results)
        else:
            print("\nno auto-fixable issues found.")
        for r in manual:
            print(f"  → {r['id']}: {r['detail']}")

    st = overall(results)
    print(f"\nstatus: {st.upper()}")
    return 0 if st != FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
