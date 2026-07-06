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
    (a stale-but-serving index is WARN, not FAIL — it still matches the indexed
     skills; only newly added/removed ones are missing until the refresh)
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
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent              # skill-concierge/
VENV = Path(os.environ.get("SKILL_CONCIERGE_VENV", Path.home() / ".claude/skill-concierge/venv"))
QNAME = os.environ.get("SKILL_QDRANT_CONTAINER", "skill-search-qdrant")
SETTINGS = Path(os.environ.get("SKILL_CONCIERGE_SETTINGS", Path.home() / ".claude/settings.json"))
LOGDIR = Path(os.environ.get("SKILL_CONCIERGE_LOG", Path.home() / ".claude/skill-concierge/logs"))
COLLECTION = os.environ.get("SKILL_COLLECTION", "claude_skills")
MULTIVECTOR = os.environ.get("SKILL_MULTIVECTOR", "1") != "0"   # multi-vector trigger layer (default on)

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


def _tree_digest(root: Path):
    """Stable content digest of a package tree: sorted (relpath, bytes) over every file
    except __pycache__/*.pyc. None when the tree is absent or empty."""
    if not root.is_dir():
        return None
    h = hashlib.sha256()
    seen = False
    for p in sorted(root.rglob("*")):
        if p.is_dir() or "__pycache__" in p.parts or p.suffix == ".pyc":
            continue
        try:
            data = p.read_bytes()
        except Exception:
            continue
        seen = True
        h.update(p.relative_to(root).as_posix().encode())
        h.update(b"\0")
        h.update(data)
        h.update(b"\0")
    return h.hexdigest() if seen else None


def _venv_engine_dir():
    """The skill_search package COPIED into the stable venv by setup.sh (NOT editable, so
    /plugin update never refreshes it — the stale-engine vector). None if not installed."""
    for lib in sorted((VENV / "lib").glob("python*")):
        cand = lib / "site-packages" / "skill_search"
        if cand.is_dir():
            return cand
    return None


def check_engine_freshness():
    """Does the engine CODE the MCP actually runs match the DEPLOYED plugin source?

    Landmine (ADR-0004, ADR-0013): the MCP launcher EXECs `skill-search` from the STABLE
    venv, where the engine is COPIED into site-packages by setup.sh — not an editable
    install. So `/plugin update` ships new code into the version-pinned cache but NEVER
    updates the venv copy: the MCP can keep serving an OLDER engine while every other check
    is green ("Engine venv ✓" only proves the bin EXISTS, not that it's current). This
    content-hashes the venv's installed engine against the plugin's vendored source; a
    mismatch means the venv is stale → rerun ./setup.sh (skill-concierge:setup), then
    restart. Fail-open (N/A) when either tree is absent — venv-missing is check_venv's job;
    a missing vendored source means doctor is running outside a packaged checkout.
    """
    if not SS_BIN.exists():
        return None                                        # venv missing -> check_venv owns it
    src_dig = _tree_digest(ROOT / "vendor" / "skill-search" / "skill_search")
    installed = _venv_engine_dir()
    inst_dig = _tree_digest(installed) if installed else None
    if src_dig is None or inst_dig is None:
        return None                                        # can't compare -> don't false-alarm
    if src_dig != inst_dig:
        return dict(id="engine_fresh", label="Engine freshness", status=WARN,
                    detail="venv engine code DIFFERS from the deployed plugin source — the MCP is "
                           "serving STALE engine code after a plugin update; rerun ./setup.sh "
                           "(skill-concierge:setup), then restart Claude Code", fix="setup")
    return dict(id="engine_fresh", label="Engine freshness", status=OK,
                detail="venv engine matches deployed source", fix=None)


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


def _stale_only(rep):
    """True when the index is stale but otherwise fully SERVING — the lone issue is a
    disk/index drift: embedder + qdrant reachable, points indexed, nothing dark or
    stale at the point level. Such an index degrades recall (new skills missing) but
    still works, so it is WARN, not FAIL."""
    emb = (rep.get("embedder") or {}).get("reachable")
    qd = rep.get("qdrant") or {}
    return bool(
        rep.get("stale")
        and emb and qd.get("reachable")
        and (qd.get("indexed") or 0) > 0
        and not (rep.get("dark_skills") or [])
        and not (rep.get("stale_points") or [])
    )


def _fresh(rep):
    """' (indexed 3h ago)' suffix from indexed_at, or '' when unknown."""
    t = rep.get("indexed_at")
    if not t:
        return ""
    age = max(0, time.time() - float(t))
    if age < 3600:
        a = f"{int(age // 60)}m"
    elif age < 86400:
        a = f"{int(age // 3600)}h"
    else:
        a = f"{int(age // 86400)}d"
    return f" (indexed {a} ago)"


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
    idx = rep.get("qdrant", {}).get("indexed", "?")
    if rep.get("status") == "ok" and not issues:
        return dict(id="health", label="Retrieval health", status=OK,
                    detail=f"{idx} skills indexed; embedder + qdrant reachable{_fresh(rep)}", fix=None)
    # Stale-but-serving is degraded, not broken: WARN (auto-fixable via reindex) so the
    # exit code distinguishes "index needs a refresh" from "retrieval is down".
    if _stale_only(rep):
        return dict(id="health", label="Retrieval health", status=WARN,
                    detail=f"index stale{_fresh(rep)} — {idx} indexed & serving; run reindex to refresh",
                    fix="reindex")
    return dict(id="health", label="Retrieval health", status=FAIL,
                detail="; ".join(str(i) for i in issues)[:300], fix="reindex")


def _count_enriched(base):
    body = json.dumps({"filter": {"must": [{"key": "enriched", "match": {"value": True}}]},
                       "exact": True}).encode()
    req = urllib.request.Request(base + "/points/count", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=3) as r:
        return json.loads(r.read())["result"]["count"]


def check_enrichment():
    """Enrichment-overlay freshness. A reindex rewrites changed/new points BARE (no `enriched`
    marker); until `enrich_index.py --reapply` runs, retrieval silently regresses for them.
    Enriched-mode + some bare points -> WARN, auto-fixable. Not enriched -> N/A (OK)."""
    if not _qdrant_reachable():
        return None
    base = QURL.rstrip("/") + f"/collections/{COLLECTION}"
    try:
        total = json.loads(urllib.request.urlopen(base, timeout=3).read())["result"]["points_count"]
        enr = _count_enriched(base)
    except Exception:
        return None
    if enr == 0:
        return dict(id="enrich", label="Enrichment overlay", status=OK,
                    detail="not enriched (no overlay in use)", fix=None)
    if enr < total:
        return dict(id="enrich", label="Enrichment overlay", status=WARN,
                    detail=f"{total - enr}/{total} points un-enriched (reindex/new) — run --reapply",
                    fix="reapply")
    return dict(id="enrich", label="Enrichment overlay", status=OK,
                detail=f"all {total} points enriched", fix=None)


def check_prompt_intent():
    """Actionability-gate corpus. The enforcer's gate suppresses conversational-turn offers
    using the `prompt_intent` collection; missing/empty -> the gate silently FAILS-OPEN (offers
    everything, no suppression). Reachable + populated -> OK; reachable + missing/empty -> WARN
    (auto-fixable by rebuilding from the transcript store). Qdrant unreachable -> N/A."""
    if not _qdrant_reachable():
        return None
    coll = os.environ.get("SKILL_PROMPT_INTENT_COLLECTION", "prompt_intent")
    base = QURL.rstrip("/") + f"/collections/{coll}"
    try:
        total = json.loads(urllib.request.urlopen(base, timeout=3).read())["result"]["points_count"]
    except Exception:
        return dict(id="prompt_intent", label="Actionability gate", status=WARN,
                    detail=f"'{coll}' collection missing — gate fails-open (no suppression); "
                           "rebuild from transcripts", fix="prompt_intent")
    if not total:
        return dict(id="prompt_intent", label="Actionability gate", status=WARN,
                    detail=f"'{coll}' empty — gate fails-open; rebuild from transcripts",
                    fix="prompt_intent")
    return dict(id="prompt_intent", label="Actionability gate", status=OK,
                detail=f"{total} labelled prompts in '{coll}'", fix=None)


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
    base = f"{on} on / {len(ov) - on} name-only"
    # Drift check: is the override map still in sync with the installed catalogue? The
    # detector lives in apply-overrides.py (--check) so the discovery logic stays in ONE
    # place. It exits 1 on drift AND on applier errors, so key off the "drift:" marker in
    # stdout — an error (invalid keep-on / no skills) must not masquerade as drift. Fail-open.
    py = PY_BIN if PY_BIN.exists() else Path(sys.executable)
    r = _run([str(py), str(ROOT / "scripts" / "apply-overrides.py"), "--check"])
    if r.returncode == 1 and "drift:" in r.stdout:
        return dict(id="overrides", label="Settings overrides", status=WARN,
                    detail=f"{base} — {_last_line(r.stdout)} "
                           f"(auto-heals on session start; or run apply-overrides)", fix="overrides")
    return dict(id="overrides", label="Settings overrides", status=OK, detail=base, fix=None)


def check_ledger():
    try:
        LOGDIR.mkdir(parents=True, exist_ok=True)
        writable = os.access(LOGDIR, os.W_OK)
    except Exception as exc:
        return dict(id="ledger", label="Ledger dir", status=WARN, detail=str(exc), fix=None)
    return dict(id="ledger", label="Ledger dir", status=(OK if writable else WARN),
                detail=str(LOGDIR), fix=None)


def _skill_search_servers(mcp_list_text):
    """Distinct skill-search MCP *installs* from `claude mcp list`. Counts real registrations,
    NOT substring lines: one entry per line ("name: command - status"), keyed by the name before
    the first colon. Excludes entries whose command still contains an UNEXPANDED
    ${CLAUDE_PLUGIN_ROOT} — that is this plugin's own .mcp.json template being auto-loaded as a
    project MCP when CWD is the source repo (a real install expands the var), not a second install."""
    out = []
    for ln in mcp_list_text.splitlines():
        name, sep, rest = ln.partition(": ")       # name/command separator is colon-SPACE;
        if not sep:                                 # a namespaced name keeps its internal colons
            continue
        name = name.strip()
        if not (name == "skill-search" or name.endswith(":skill-search")):
            continue
        if "${CLAUDE_PLUGIN_ROOT}" in rest:        # repo's own template projection, not an install
            continue
        out.append(name)
    return out


def check_dup_mcp():
    claude = shutil.which("claude")
    if not claude:
        return None
    r = _run([claude, "mcp", "list"])
    if r.returncode != 0:
        return None
    servers = _skill_search_servers(r.stdout)
    if len(servers) > 1:
        return dict(id="dupmcp", label="Duplicate MCP", status=WARN,
                    detail=f"{len(servers)} skill-search installs ({', '.join(servers)}) — "
                           f"remove the extra: claude mcp remove <name> (check its scope first)",
                    fix=None)
    return dict(id="dupmcp", label="Duplicate MCP", status=OK, detail="single skill-search MCP", fix=None)


def check_multivector():
    """Multi-vector trigger layer (server.py build_index). Counts kind="trigger" points: present
    => each skill is scored by its single best phrase point (MAX-pool retrieval); absent => the
    index is one bare vector per skill. Read-only, fail-open (N/A if Qdrant unreachable)."""
    if not _qdrant_reachable():
        return None
    url = QURL.rstrip("/") + f"/collections/{COLLECTION}/points/count"

    def _count(flt):
        body = {"exact": True}
        if flt:
            body["filter"] = flt
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        return json.loads(urllib.request.urlopen(req, timeout=3).read())["result"]["count"]
    try:
        trig = _count({"must": [{"key": "kind", "match": {"value": "trigger"}}]})
        total = _count(None)
    except Exception:
        return None
    if trig == 0:
        if MULTIVECTOR:
            # env expects multi-vector but the index has none -> retrieval silently degraded to
            # single-vector (lower recall, more getaways). This is the "skills go dark silently"
            # mode the doctor exists to catch — WARN, auto-fixable by reindex.
            return dict(id="multivector", label="Multi-vector layer", status=WARN,
                        detail="SKILL_MULTIVECTOR on but 0 trigger points — retrieval degraded to "
                               "single-vector; reindex to build the trigger layer", fix="reindex")
        return dict(id="multivector", label="Multi-vector layer", status=OK,
                    detail="off — one bare vector per skill", fix=None)
    return dict(id="multivector", label="Multi-vector layer", status=OK,
                detail=f"{trig} trigger points (+ base) of {total} total — MAX-pooled retrieval",
                fix=None)


def check_corpus_health():
    """Per-skill calibration corpus health. Reads eval/thresholds.json (from
    calibrate_thresholds.py): how many skills have cosine separation strong enough for a
    trustworthy per-skill tau. `weak`/`no-signal` skills can't be fixed by ANY threshold —
    the lever is index content (e.g. multi-vector) or contrastive negatives. Surfaced here
    so the fix-list is visible in the normal health workflow. Read-only, fail-open: missing
    file -> N/A (calibration is optional); WARN only if calibration is wholly signal-less."""
    path = ROOT / "eval" / "thresholds.json"
    if not path.exists():
        return None  # calibration is optional; its absence is not a deployment fault
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return dict(id="corpus", label="Corpus health", status=WARN,
                    detail=f"{path.name} invalid JSON — re-run calibrate_thresholds.py", fix=None)
    if not d:
        return None
    counts = {"ok": 0, "weak": 0, "no-signal": 0}
    for v in d.values():
        counts[v.get("status")] = counts.get(v.get("status"), 0) + 1
    n = len(d)
    needs = counts.get("weak", 0) + counts.get("no-signal", 0)
    detail = f"{counts.get('ok', 0)}/{n} ok · {counts.get('weak', 0)} weak · {counts.get('no-signal', 0)} no-signal"
    if needs:
        detail += " — weak/no-signal need contrastive negatives or richer index (multi-vector), not a threshold"
    status = WARN if counts.get("ok", 0) == 0 else OK
    return dict(id="corpus", label="Corpus health", status=status, detail=detail, fix=None)


CHECKS = [check_python, check_venv, check_engine_freshness, check_mcp_wiring, check_qdrant,
          check_engine_health, check_enrichment, check_multivector, check_prompt_intent,
          check_corpus_health, check_overrides, check_ledger, check_dup_mcp]


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


def _reapply_cmd():
    py = PY_BIN if PY_BIN.exists() else Path(sys.executable)
    return _run([str(py), str(ROOT / "scripts" / "enrich_index.py"), "--reapply"], env=_engine_env())


def fix_reindex():
    if not SS_BIN.exists():
        return False, "venv missing — run ./setup.sh first"
    r = _run([str(SS_BIN), "--reindex"], env=_engine_env())
    if r.returncode != 0:
        return False, (r.stderr.strip() or "reindex failed")
    msg = _last_line(r.stdout) or "reindexed"
    if MULTIVECTOR:
        # The multi-vector trigger layer is rebuilt by reindex itself (build_index), so the
        # legacy MEAN enrichment overlay must NOT run on top — it would mean-corrupt the base
        # vectors. Skip reapply; multi-vector supersedes the overlay.
        return True, msg
    # reindex rewrites changed/new points bare — re-apply the enrichment overlay so the
    # refresh does not silently undo it (no-op when the index was never enriched).
    rr = _reapply_cmd()
    return (rr.returncode == 0), f"{msg}; reapply: {_last_line(rr.stdout) or rr.stderr.strip()}"


def fix_reapply():
    if not SS_BIN.exists():
        return False, "venv missing — run ./setup.sh first"
    rr = _reapply_cmd()
    return (rr.returncode == 0), (_last_line(rr.stdout) or rr.stderr.strip() or "reapplied")


def fix_overrides():
    py = PY_BIN if PY_BIN.exists() else Path(sys.executable)
    r = _run([str(py), str(ROOT / "scripts" / "apply-overrides.py")])
    return (r.returncode == 0), (_last_line(r.stdout) or r.stderr.strip() or "applied")


def fix_prompt_intent():
    py = PY_BIN if PY_BIN.exists() else Path(sys.executable)
    r = _run([str(py), str(ROOT / "scripts" / "build_prompt_intent.py")], env=_engine_env())
    return (r.returncode == 0), (_last_line(r.stdout) or r.stderr.strip() or "rebuilt prompt_intent")


AUTO_FIXERS = {"docker": fix_docker_start, "reindex": fix_reindex,
               "reapply": fix_reapply, "overrides": fix_overrides,
               "prompt_intent": fix_prompt_intent}


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
    assert set(AUTO_FIXERS) <= {"docker", "reindex", "reapply", "overrides", "prompt_intent"}
    # _stale_only: stale + fully reachable + indexed + nothing dark/stale-point -> WARN-worthy
    healthy_emb = {"reachable": True}
    serving_qd = {"reachable": True, "indexed": 495}
    assert _stale_only({"stale": True, "embedder": healthy_emb, "qdrant": serving_qd,
                        "dark_skills": [], "stale_points": []}) is True
    assert _stale_only({"stale": False, "embedder": healthy_emb, "qdrant": serving_qd}) is False
    assert _stale_only({"stale": True, "embedder": healthy_emb, "qdrant": serving_qd,
                        "dark_skills": ["x"], "stale_points": []}) is False
    assert _stale_only({"stale": True, "embedder": {"reachable": False},
                        "qdrant": serving_qd, "dark_skills": [], "stale_points": []}) is False
    sample = ("plugin:skill-concierge:skill-search: /cache/.../0.4.2/bin/skill-search-mcp - ok\n"
              "skill-search: ${CLAUDE_PLUGIN_ROOT}/bin/skill-search-mcp - pending\n"
              "exa: https://x - ok")
    assert _skill_search_servers(sample) == ["plugin:skill-concierge:skill-search"], _skill_search_servers(sample)
    two = sample + "\nskill-search: /usr/local/bin/other-skill-search-mcp - ok"
    assert len(_skill_search_servers(two)) == 2
    # engine-freshness digest: identical trees hash equal, a 1-byte change diverges, absent -> None
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        a, b = Path(d) / "a" / "skill_search", Path(d) / "b" / "skill_search"
        for base in (a, b):
            base.mkdir(parents=True)
            (base / "x.py").write_text("print(1)\n")
        assert _tree_digest(a) == _tree_digest(b)
        (b / "x.py").write_text("print(2)\n")
        assert _tree_digest(a) != _tree_digest(b)
        assert _tree_digest(Path(d) / "absent") is None
    assert any(getattr(fn, "__name__", "") == "check_engine_freshness" for fn in CHECKS)
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
