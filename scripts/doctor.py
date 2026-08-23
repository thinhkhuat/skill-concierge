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
SKILL_EMBED_BACKEND, SKILL_EMBED_MODEL, SKILL_CONCIERGE_SETTINGS, SKILL_CONCIERGE_LOG,
SKILL_TRIGGERS, SKILL_SERVER_RECORDS.
"""
import argparse
import collections
import glob
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
# Same seam as flywheel.py/llm_triggers.py: the engine reads triggers from SKILL_TRIGGERS, which
# need not live under ROOT — when doctor runs from the plugin cache, ROOT/eval/ does not exist.
TRIGGERS = Path(os.environ.get("SKILL_TRIGGERS", ROOT / "eval" / "triggers.json"))
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
def read_server_records_dir():
    """Where live MCP servers publish their build id — resolved from `.mcp.json` FIRST.

    Deliberately inverted from the other seams, where an env var wins. Here doctor is
    reading an artifact the SERVER writes, and the server's environment is the one
    `.mcp.json` hands it — so the pinned value is what the writer actually used, and a
    shell export in the reader's environment would only make the two disagree. Doctor
    would then find an empty directory and report every live server as unproven, forever.
    This repo has shipped that exact writer/reader seam split twice already (v0.16.1
    `auto_reindex._mcp_env`, v0.20.5 `setup.sh env_run`), both as "a seam honoured by one
    side and not the other".

    `${HOME}`/`$HOME` are expanded because Claude Code expands them for the server.
    """
    try:
        env = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["skill-search"]["env"]
        pinned = env.get("SKILL_SERVER_RECORDS")
    except Exception:
        pinned = None
    raw = pinned or os.environ.get("SKILL_SERVER_RECORDS") or str(Path.home() / ".cache/skill-search/servers")
    return Path(os.path.expandvars(raw)).expanduser()


# One `<pid>.json` per live MCP server, naming the engine build that process actually runs.
SERVER_RECORDS = read_server_records_dir()


def _run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


_HEALTH_RUN = None


def _health_run():
    """`skill-search --health`, executed at most once per CHECK PASS and shared.

    Spawning the engine is by far the slowest thing doctor does, and two checks need the
    same answer — which cannot change within a single pass. It very much CAN change between
    passes, which is why `run_all()` clears the memo before every one; see `_reset_health_memo`.
    """
    global _HEALTH_RUN
    if _HEALTH_RUN is None:
        _HEALTH_RUN = _run([str(SS_BIN), "--health"], env=_engine_env())
    return _HEALTH_RUN


def _reset_pass_caches():
    """Drop every per-pass cache so the next pass re-measures.

    The scope of these memos is ONE pass; `--fix` runs a second pass whose entire purpose is
    to observe what the fix changed. Any cache that outlives a pass makes the re-check
    re-report the failure it just repaired and exit 1 on a system that is now healthy.
    ONE reset point on purpose — a per-cache reset invites the next cache to be added to
    only half the boundary, and the bug is silent when that happens.
    """
    global _HEALTH_RUN, _RUNNING_STATE
    _HEALTH_RUN = None
    _RUNNING_STATE = _UNSET


def _health_json():
    """Parsed --health report, or None when the engine is missing or its output is not JSON."""
    if not SS_BIN.exists():
        return None
    try:
        return json.loads(_health_run().stdout)
    except Exception:
        return None


def _is_engine_drift(rep):
    """Drift is the index's writer differing from us — NOT the mere presence of the field.

    `engine_build` rides on every report now (it states which build is running), so keying
    on presence, as the first version did, would flag every healthy run as drift.
    """
    return bool((rep.get("engine_build") or {}).get("index_written_by"))


def _drift_remedy(index_build, running_build, state):
    """(detail, fix) for an index whose manifest was written by a different engine build.

    Two causes with OPPOSITE remedies hide behind one symptom:
      • the manifest is left over from a previous release, no old server survives
        → a reindex re-stamps it and clears. EVERY engine upgrade lands here first,
          because changing the engine necessarily changes the build id.
      • a server is still live on the old build
        → only a restart helps; a reindex writes OUR build and that server hands the
          mismatch straight back, which is what "reindex will not fix it" was about.

    The engine cannot tell these apart — it sees its own build and no other process — so it
    offers both. doctor computed the live-server picture in this same pass, so it decides.

    `state` is (drift_pids, unknown_pids) from `_running_engine_state`, or None when that
    evidence is unavailable. fix="reindex" is returned ONLY for a proven-clean fleet:
    auto-reindexing while an old server is live is the 0.20.6 defect, re-armed.
    """
    head = (f"index was built by engine {index_build}, this process runs {running_build}, "
            f"so disk-vs-index comparison is unavailable")
    if state is None:
        return (f"{head} — if every live MCP server is now on {running_build}, a reindex "
                f"clears this; if any is still on {index_build}, restart Claude Code "
                f"instead (live-server evidence unavailable, so this is not decided)"), None
    drift_pids, unknown_pids = state
    if drift_pids:
        runs = "run" if len(drift_pids) > 1 else "runs"
        return (f"{head} — pid {', '.join(drift_pids)} still {runs} an older build, so a "
                f"reindex would hand the mismatch back. Restart Claude Code"), None
    if unknown_pids:
        pub = "publish" if len(unknown_pids) > 1 else "publishes"
        return (f"{head} — pid {', '.join(unknown_pids)} {pub} no build id, so a clean "
                f"fleet is unproven. Restart Claude Code; if it persists, reindex"), None
    return (f"{head} — no live MCP server is on an older build, so the manifest is simply "
            f"left over from a previous release; a reindex re-stamps it"), "reindex"


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


def _etime_seconds(etime: str):
    """`ps -o etime=` -> seconds. Formats: MM:SS, HH:MM:SS, DD-HH:MM:SS. None if unparseable."""
    try:
        days, _, rest = etime.strip().rpartition("-")
        parts = [int(p) for p in rest.split(":")]
        if len(parts) == 2:
            secs = parts[0] * 60 + parts[1]
        elif len(parts) == 3:
            secs = parts[0] * 3600 + parts[1] * 60 + parts[2]
        else:
            return None
        return secs + (int(days) * 86400 if days else 0)
    except Exception:
        return None


# Exactly the flags `server.main()` dispatches on. A process carrying one of these took a
# CLI branch and wrote no build record, so counting it would report a permanent unknown-build
# server that is really just a busy reindex. Matching this SET rather than "any `--` token"
# is deliberate: an unrecognized flag falls through to the server branch upstream and does
# write a record, so excluding it would make every server invisible and turn this diagnostic
# silently green — a false all-clear is worse here than a false alarm.
CLI_FLAGS = ("--reindex", "--rebuild", "--health")


def _parse_server_lines(stdout, now):
    """`ps -o pid=,etime=,command=` output -> [(pid, start_epoch)] for MCP *servers* only."""
    live = []
    for line in stdout.splitlines():
        if str(SS_BIN) not in line:
            continue
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        if any(tok in CLI_FLAGS for tok in parts[2].split()):
            continue                            # a CLI run, not a server
        secs = _etime_seconds(parts[1])
        if secs is None:
            continue
        live.append((parts[0], now - secs))
    return live


def _live_servers():
    """[(pid, start_epoch)] for every live MCP server process. None if ps is unusable."""
    # -A not -e: on Darwin -e means "show the environment too"; -A is "all processes" on
    # both Darwin and procps. -ww defeats width truncation — output goes to a PIPE here,
    # so BSD ps would otherwise clip at ~79 columns and cut off the very path we match on,
    # returning a reassuring "no stale server" on exactly the platform this is written for.
    try:
        proc = _run(["ps", "-A", "-ww", "-o", "pid=,etime=,command="])
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    return _parse_server_lines(proc.stdout, time.time())


def _read_server_records():
    """{pid: record} for every build record on disk. Unreadable/garbage entries are
    dropped — a record we cannot parse is simply a build we do not know."""
    out = {}
    try:
        paths = sorted(SERVER_RECORDS.glob("*.json"))
    except OSError:
        return out
    for p in paths:
        try:
            rec = json.loads(p.read_text())
        except Exception:
            continue
        if isinstance(rec, dict):
            out[p.stem] = rec
    return out


def _pid_alive(pid):
    """Does a process with this pid exist? Signal 0 checks without delivering anything.
    PermissionError means it exists and belongs to someone else — alive, not gone."""
    try:
        os.kill(int(pid), 0)
    except PermissionError:
        return True
    except (OSError, ValueError, TypeError):
        return False
    return True


def _prune_server_records(records_dir=None):
    """Drop records whose process no longer exists. Without this the directory grows one
    file per Claude Code restart, forever. Best-effort: a failed unlink costs nothing.

    Keyed on pid liveness, NOT on the `ps` scan that drives the check. The records dir is
    shared by every skill-concierge install on the machine, while `_live_servers()` only
    matches THIS venv's binary — so pruning by that result would delete a second install's
    LIVE record and leave its doctor reporting an unknown build. It also closes the race
    against a server writing its record while doctor sweeps: a just-started pid is alive.
    """
    root = SERVER_RECORDS if records_dir is None else records_dir
    try:
        paths = sorted(root.glob("*.json"))
    except OSError:
        return
    for p in paths:
        if not _pid_alive(p.stem):
            try:
                p.unlink()
            except OSError:
                pass


# The gap between a process's start and its record's timestamp is ONE-SIDED: ps dates the
# pid from the launcher's exec, while `started_at` is stamped after the launcher's prelude
# has run. So the record is always the LATER of the two, by however long that prelude took —
# and the prelude contains the ADR-0018 pip resync, which fires on exactly the occasion this
# check matters most (a plugin update) and can reach the network. A leftover record from a
# recycled pid is the opposite shape: it always PREDATES the process that inherited the pid.
# Hence a tight floor (the reuse guard, all it needs) and a generous ceiling (startup slack).
PID_START_SLOP = 5              # seconds a record may precede its process: ps etime is
                                # whole-seconds, so allow rounding — but not a real gap.
PID_START_MAX_PRELUDE = 3600    # seconds the launcher's prelude may take before its record


def _classify_servers(live, records, current):
    """Split live MCP servers into (drift, unknown) by BUILD ID, never by timestamp.

    live    — [(pid, start_epoch)] from ps
    records — {pid: {"build":…, "started_at":…}} each server wrote at its own startup
    current — the build a process starting right now would run

    drift   — the record proves a different build; a restart is the only remedy.
    unknown — no usable record, or one naming no build. Its build is unproven, so it is
              reported separately rather than folded into a proven mismatch.
    """
    drift, unknown = [], []
    for pid, started in live:
        rec = records.get(pid)
        try:
            delta = float(rec.get("started_at")) - started
            mine = -PID_START_SLOP <= delta <= PID_START_MAX_PRELUDE
        except (AttributeError, TypeError, ValueError):
            mine = False
        build = rec.get("build") if mine and isinstance(rec, dict) else None
        # A sentinel or absent id identifies no build, so it cannot evidence a mismatch.
        # `server._engine_drift()` refuses to accuse on the same grounds, and for the same
        # reason: the remedy printed here is "restart", and a restart re-derives the same
        # sentinel — a permanent warning that doing what it says will never clear.
        if not build or build == "unknown":
            unknown.append(pid)
        elif build != current:
            drift.append(pid)
    return drift, unknown


_UNSET = object()           # "not computed yet", distinct from a computed None
_RUNNING_STATE = _UNSET

# Named, not a bare tuple: two checks consume this, and positional indexing is how a reader
# silently gets the wrong element when the shape grows — `live` was added after the first
# version and the consumers had to be renumbered by hand. Fields cannot be mis-numbered.
RunningState = collections.namedtuple("RunningState", "current live drift unknown")


def _running_engine_state():
    """A RunningState, or None if it cannot be determined.

    Memoized for one check pass: two checks need this same picture — `check_running_engine`
    reports it, `check_engine_health` decides a remedy from it — and re-deriving it would
    re-scan `ps` for an answer that cannot change mid-pass. Cleared by `_reset_pass_caches`.

    `live_pids` rides along rather than being re-fetched by the caller: a second `ps` scan
    could observe a server that started or died since the first, and then the row would
    report a population its own drift/unknown split never classified.
    """
    global _RUNNING_STATE
    if _RUNNING_STATE is _UNSET:
        _RUNNING_STATE = _compute_running_engine_state()
    return _RUNNING_STATE


def _compute_running_engine_state():
    if not SS_BIN.exists() or not shutil.which("ps"):
        return None
    rep = _health_json()
    if rep is None or "engine_build" not in rep:
        return None                             # engine predates the published id
    current = (rep.get("engine_build") or {}).get("running")
    if not current or current == "unknown":
        return None                             # no id to measure against
    live = _live_servers()
    if live is None:
        return None
    records = _read_server_records()
    _prune_server_records()
    drift, unknown = _classify_servers(live, records, current)
    return RunningState(current, [pid for pid, _ in live], drift, unknown)


def check_running_engine():
    """Is a LIVE MCP server executing an engine build other than the one on disk now?

    `check_engine_freshness` compares two file trees (venv vs deployed source) and is blind
    to the process dimension: a server that started BEFORE the venv was refreshed keeps
    running the bytes it imported, and no amount of re-copying changes that. The symptom is
    not "search is old" — it is a permanent false `stale: true`, because the running build
    and every fresh CLI process derive different disk signatures from the same unchanged
    files, so each reindex hands the false alarm back to the other side. Only a restart
    clears it.

    Identity, not timestamps. The first version of this check dated each process against
    the engine files' newest mtime/ctime, which looked equivalent and was not: setup.sh
    re-copies the engine on EVERY run, so those timestamps advance even when the bytes are
    byte-identical, and a routine re-run accused every live server of running old code
    while the engine's own health() correctly reported no drift. Builds are compared now —
    each server publishes the id it runs at startup, and a no-op re-copy moves no id.

    Fail-open (N/A) whenever the venv, `ps`, or a published build id is unavailable —
    including against an engine too old to publish one, where every server would look
    unknown. This is a diagnostic, never a gate.
    """
    state = _running_engine_state()
    if state is None:
        return None
    current, live = state.current, state.live
    drift, unknown = state.drift, state.unknown
    if drift:
        return dict(id="engine_running", label="Running engine", status=WARN,
                    detail=f"{len(drift)} live MCP server(s) run a DIFFERENT engine build than "
                           f"the one on disk ({current}) — pid {', '.join(drift)}. They execute "
                           f"the OLD code, which shows up as a false 'disk changed since last "
                           f"index'. Restart Claude Code; reindexing will not fix it", fix=None)
    if unknown:
        # State the OBSERVATION, not a cause. Several paths land here and they do not share a
        # remedy: a server predating this engine (a restart clears it), an unwritable records
        # dir, a `SKILL_SERVER_RECORDS` that differs between the server's env and this one, or
        # a record naming no build. Asserting "started before this engine" would send the user
        # to restart on the ones a restart cannot fix.
        return dict(id="engine_running", label="Running engine", status=WARN,
                    detail=f"no build record for {len(unknown)} live MCP server(s) (pid "
                           f"{', '.join(unknown)}), so their engine cannot be compared with the "
                           f"one on disk ({current}). Usual cause: they started before this "
                           f"engine was installed — restart Claude Code and it clears. If it "
                           f"persists after a restart, check {SERVER_RECORDS} is writable and "
                           f"that SKILL_SERVER_RECORDS is not set differently for the server "
                           f"than for this shell", fix=None)
    return dict(id="engine_running", label="Running engine", status=OK,
                detail=f"{len(live)} live MCP server(s) run the current engine build ({current})"
                       if live else "no live MCP server", fix=None)


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
    r = _health_run()
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
    # Engine-build drift is NOT a stale index, so it never falls through to the FAIL branch
    # below: that would flip the ordinary post-update run red over a manifest that is merely
    # left over from the previous release. Keyed on `engine_build.index_written_by`, never on
    # matching issue strings — and never on the field's mere presence, which rides on every
    # report since v0.20.7.
    #
    # Whether a reindex helps is DECIDED here rather than assumed. The engine offers both
    # remedies because it cannot see other processes; doctor computed the live-server picture
    # in this same pass, so `_drift_remedy` resolves it — and returns fix="reindex" only for a
    # fleet proven to be entirely on the current build. Auto-reindexing while an older server
    # is live is the v0.20.6 defect: it clears the CLI-side symptom, re-embeds every point
    # whose text moved under the new parser, and leaves that server just as broken.
    eb = rep.get("engine_build") or {}
    if _is_engine_drift(rep):
        state = _running_engine_state()
        evidence = None if state is None else (state.drift, state.unknown)
        detail, fix = _drift_remedy(eb.get("index_written_by"), eb.get("running"), evidence)
        # Drift is reported alone, but it is no longer only reported — it can now trigger a
        # reindex. Anything ELSE wrong in the same report (qdrant unreachable, an embedder
        # dim mismatch) would make that reindex fail, so surface those and drop the auto-fix
        # rather than firing a repair into a broken store.
        others = [str(i) for i in issues if "engine" not in str(i)]
        if others:
            detail = f"{detail}. Also: {'; '.join(others)[:160]}"
            fix = None
        return dict(id="health", label="Retrieval health", status=WARN,
                    detail=detail, fix=fix)
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


def _indexed_skill_names():
    """Names of all kind="base" points in the live index (paged scroll, no vectors).

    Excludes external catalog points (tier=external, ADR-0031): both callers here —
    flywheel coverage and trigger hygiene — concern the utterance layer, which skips
    externals by design (build_triggers.scroll_all_points), so counting them would
    report every catalog skill as a permanent "missing utterances" false gap."""
    url = QURL.rstrip("/") + f"/collections/{COLLECTION}/points/scroll"
    names, nxt = set(), None
    while True:
        body = {"limit": 256, "with_payload": True, "with_vector": False,
                "filter": {"must": [{"key": "kind", "match": {"value": "base"}}],
                           "must_not": [{"key": "tier", "match": {"value": "external"}}]}}
        if nxt is not None:
            body["offset"] = nxt
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                      headers={"Content-Type": "application/json"})
        res = json.loads(urllib.request.urlopen(req, timeout=5).read())["result"]
        for pt in res.get("points", []):
            n = pt.get("payload", {}).get("name")
            if n:
                names.add(n)
        nxt = res.get("next_page_offset")
        if nxt is None:
            break
    return names


def check_flywheel():
    """Retrieval-flywheel (ADR-0026 utterance layer) visibility. Read-only, fail-open: the
    flywheel is optional (no LLM configured -> graceful fallback to description+body
    retrieval), so this NEVER fails the doctor run — INFO/WARN only. Reports whether an
    LLM endpoint is configured + reachable (via flywheel_llm.ping()), and how much of the
    live index has LLM-generated utterance triggers (eval/triggers.json llm_triggers)."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import flywheel_llm
    import flywheel_manifest

    def _last_run_suffix():
        """Read-only, fail-open manifest summary appended to `detail` — never affects
        pass/fail. None when no run has ever completed (fresh install, hook never fired)."""
        try:
            run = flywheel_manifest.last_run()
        except Exception:
            return ""
        if not run:
            return ""
        t = run.get("totals", {})
        c = run.get("coverage", {})
        s = (f"; last run {run.get('timestamp', '?')}: "
             f"generated={t.get('generated', 0)} error={t.get('error', 0)} skipped={t.get('skipped', 0)}, "
             f"coverage {c.get('have', '?')}/{c.get('total', '?')}")
        if run.get("last_error"):
            s += f", last_error={run['last_error']}"
        return s

    configured = "FLYWHEEL_LLM_ENDPOINT" in os.environ or "FLYWHEEL_LLM_MODEL" in os.environ
    has_key = bool(os.environ.get("FLYWHEEL_LLM_API_KEY"))
    fix = "run the skill-concierge:flywheel skill"

    if not configured:
        return dict(id="flywheel", label="Retrieval flywheel", status=OK,
                    detail="not configured — utterance layer runs in fallback "
                           f"(description+body only){_last_run_suffix()}", fix=fix)

    endpoint_detail = f"{flywheel_llm.ENDPOINT} ({flywheel_llm.MODEL}" \
                       f"{', keyed' if has_key else ', no key'})"
    ok, ping_detail = flywheel_llm.ping()
    if not ok:
        return dict(id="flywheel", label="Retrieval flywheel", status=WARN,
                    detail=f"configured ({endpoint_detail}) but unreachable — "
                           f"{ping_detail}{_last_run_suffix()}",
                    fix=fix)

    # Coverage: indexed base-skill names vs eval/triggers.json entries with a non-empty
    # llm_triggers.triggers list.
    covered = set()
    if not TRIGGERS.exists():
        # Absent triggers file is NOT "nothing covered" — reporting 0/N here reads as a dead
        # flywheel when the real cause is a misresolved path. Say so instead of miscounting.
        return dict(id="flywheel", label="Retrieval flywheel", status=WARN,
                    detail=f"configured + reachable ({endpoint_detail}); coverage unknown — "
                           f"no triggers file at {TRIGGERS} (set SKILL_TRIGGERS)"
                           f"{_last_run_suffix()}", fix=fix)
    try:
        triggers = json.loads(TRIGGERS.read_text(encoding="utf-8"))
        covered = {k for k, v in triggers.items()
                   if isinstance(v, dict) and (v.get("llm_triggers", {}) or {}).get("triggers")}
    except Exception as e:
        return dict(id="flywheel", label="Retrieval flywheel", status=WARN,
                    detail=f"configured + reachable ({endpoint_detail}); coverage unknown — "
                           f"unreadable triggers file {TRIGGERS}: {e}{_last_run_suffix()}", fix=fix)
    try:
        indexed = _indexed_skill_names()
    except Exception:
        return dict(id="flywheel", label="Retrieval flywheel", status=OK,
                    detail=f"configured + reachable ({endpoint_detail}); "
                           "coverage unknown (index unreachable)", fix=fix)

    have = indexed & covered
    missing = sorted(indexed - covered)
    n, m = len(have), len(indexed)
    detail = f"configured + reachable ({endpoint_detail}); {n}/{m} skills have utterances"
    if missing:
        examples = ", ".join(missing[:5])
        detail += f"; {len(missing)} missing (examples: {examples})"
    detail += _last_run_suffix()
    return dict(id="flywheel", label="Retrieval flywheel", status=OK, detail=detail, fix=fix)


def _junk_triggers():
    """{skill: [bad phrase, ...]} for LIVE-indexed skills whose stored utterance layer
    contains phrases `clean_triggers()` would reject. Raises on an unreadable/absent
    triggers file or an unreachable index — callers decide the fail-open policy."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from llm_triggers import clean_triggers   # single definition of "junk" — do not restate it here

    triggers = json.loads(TRIGGERS.read_text(encoding="utf-8"))
    live = set(_indexed_skill_names())
    out = {}
    for name in live:
        entry = triggers.get(name)
        if not isinstance(entry, dict):
            continue
        stored = (entry.get("llm_triggers", {}) or {}).get("triggers", []) or []
        if not stored:
            continue
        kept = clean_triggers(stored)
        # clean_triggers() drops junk AND collapses duplicates, so a shrink means the
        # stored layer holds phrases that would not survive generation today.
        if len(kept) < len(stored):
            keep = {p.lower() for p in kept}
            out[name] = [p for p in stored
                         if not isinstance(p, str) or " ".join(p.split()).strip().lower() not in keep]
    return out


def check_trigger_hygiene():
    """Junk ALREADY AT REST in the utterance layer. Coverage measures presence, not validity:
    a skill whose triggers are empty strings / one-char noise / a repeated phrase still counts
    as 'covered', so a degraded generation run hides behind a green coverage number and the
    generator then SKIPS it forever (cache-hit + layer present). clean_triggers() gates new
    writes; nothing audited what earlier runs already stored. Read-only, fail-open."""
    if not TRIGGERS.exists():
        return dict(id="hygiene", label="Trigger hygiene", status=OK,
                    detail=f"no triggers file at {TRIGGERS} — utterance layer unused")
    try:
        bad = _junk_triggers()
    except Exception as e:
        return dict(id="hygiene", label="Trigger hygiene", status=OK,
                    detail=f"not audited ({type(e).__name__}: {e})")
    if not bad:
        return dict(id="hygiene", label="Trigger hygiene", status=OK,
                    detail="no junk phrases stored in the utterance layer")
    examples = ", ".join(f"{n} ({len(v)})" for n, v in list(sorted(bad.items()))[:4])
    return dict(id="hygiene", label="Trigger hygiene", status=WARN,
                detail=f"{len(bad)} skills store junk utterances — a degraded model wrote them "
                       f"and the generator now skips them as 'covered' (examples: {examples})",
                fix="purge_junk")


def check_catalogs():
    """External catalog roots (ADR-0031). Absent config = feature off = OK. A
    configured root whose path vanished (moved/renamed clone) WARNs: its skills go
    dark at the next reindex and any promoted symlinks into it dangle. Also
    compares the indexed catalog-point presence per alias when Qdrant is up."""
    cfg_path = Path(os.environ.get(
        "SKILL_CONCIERGE_CATALOG_ROOTS",
        Path.home() / ".claude" / "skill-concierge" / "catalog-roots.json"))
    if not cfg_path.exists():
        return None                                    # feature off — not a finding
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        assert isinstance(cfg, dict)
    except Exception:
        return dict(id="catalogs", label="External catalogs", status=WARN,
                    detail=f"{cfg_path} unreadable/malformed — catalogs silently OFF "
                           "(engine fails open to none)", fix=None)
    roots = {a: (s if isinstance(s, dict) else {"path": s}) for a, s in cfg.items()
             if isinstance(a, str) and not a.startswith("_")}
    missing = [a for a, s in roots.items()
               if not s.get("path") or not Path(os.path.expanduser(str(s["path"]))).is_dir()]
    if missing:
        return dict(id="catalogs", label="External catalogs", status=WARN,
                    detail=f"root path missing for: {', '.join(sorted(missing))} — skills go "
                           "dark at next reindex; fix the path or `catalogs.py remove`", fix=None)
    counts = {a: len(glob.glob(str(Path(os.path.expanduser(str(s['path']))) / '*' / 'SKILL.md')))
              for a, s in roots.items()}
    detail = ", ".join(f"{a}: {n} skills" for a, n in sorted(counts.items())) or "none configured"
    return dict(id="catalogs", label="External catalogs", status=OK, detail=detail, fix=None)


CHECKS = [check_python, check_venv, check_engine_freshness, check_running_engine,
          check_mcp_wiring, check_qdrant,
          check_engine_health, check_enrichment, check_multivector, check_prompt_intent,
          check_corpus_health, check_flywheel, check_trigger_hygiene, check_overrides,
          check_catalogs, check_ledger, check_dup_mcp]


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


def fix_purge_junk():
    """Drop junk utterance layers and their generation-cache keys, then reindex.

    Deliberately does NOT regenerate: that needs the LLM endpoint, which doctor never calls.
    Purging is the whole repair — a purged skill falls back to description+body retrieval
    (no worse than junk phrases pointing the wrong way) and, with its cache key gone, the
    next flywheel run rewrites it properly instead of skipping it as already covered.
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    import llm_triggers

    try:
        bad = _junk_triggers()
    except Exception as e:
        return False, f"could not audit triggers ({type(e).__name__}: {e})"
    if not bad:
        return True, "nothing to purge"

    backup = TRIGGERS.with_suffix(f".json.bak-junk-{int(time.time())}")
    try:
        shutil.copy2(TRIGGERS, backup)
        triggers = json.loads(TRIGGERS.read_text(encoding="utf-8"))
        for name in bad:
            entry = triggers.get(name) or {}
            prose = entry.get("prose_triggers") or []
            if prose:   # keep the hand/prose layer; only the LLM layer was poisoned
                triggers[name] = {"source": "prose-phrase", "triggers": prose, "n": len(prose)}
            else:
                triggers.pop(name, None)
        TRIGGERS.write_text(json.dumps(triggers, indent=2, ensure_ascii=False), encoding="utf-8")

        cache = llm_triggers.load_cache()
        for name in bad:
            cache.pop(llm_triggers.CACHE_PREFIX + name, None)
        llm_triggers.save_cache(cache)
    except Exception as e:
        return False, f"purge failed ({type(e).__name__}: {e}); backup at {backup}"

    msg = (f"purged {len(bad)} junk utterance layers (backup: {backup.name}); "
           f"the flywheel will regenerate them")
    if not SS_BIN.exists():
        return True, msg + " — reindex skipped (venv missing)"
    r = _run([str(SS_BIN), "--reindex"], env=_engine_env())
    return True, msg + ("; reindexed" if r.returncode == 0 else "; reindex FAILED — rerun doctor --fix")


AUTO_FIXERS = {"docker": fix_docker_start, "reindex": fix_reindex,
               "reapply": fix_reapply, "overrides": fix_overrides,
               "prompt_intent": fix_prompt_intent, "purge_junk": fix_purge_junk}


# ---------- run + report ----------

def run_all():
    # Invalidate the --health memo FIRST. It exists to stop two checks in one pass from
    # spawning the engine twice; it must not outlive the pass. `--fix` calls run_all() again
    # after repairing something, and a memo carried across that boundary would re-report the
    # very failure the fix just cleared — exiting 1 on a system doctor had already repaired.
    _reset_pass_caches()
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
    assert set(AUTO_FIXERS) <= {"docker", "reindex", "reapply", "overrides", "prompt_intent",
                                "purge_junk"}
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
    # ps etime -> seconds, all three formats the field can take, plus the junk cases
    assert _etime_seconds("05:30") == 330
    assert _etime_seconds("01:02:03") == 3723
    assert _etime_seconds("2-03:04:05") == 2 * 86400 + 3 * 3600 + 4 * 60 + 5
    assert _etime_seconds("garbage") is None and _etime_seconds("1:2:3:4") is None
    assert any(getattr(fn, "__name__", "") == "check_running_engine" for fn in CHECKS)
    # Engine drift must never be auto-"fixed" by a reindex: the remedy is a restart, and
    # a reindex would clear the CLI-side symptom while the live server stays broken.
    drift_rep = {"status": "degraded", "issues": ["engine ... restart"],
                 "engine_build": {"running": "aaaa", "index_written_by": "bbbb"}}
    assert _stale_only(drift_rep) is False
    # `engine_build` is published on EVERY report now, so its mere presence says nothing.
    # Drift is `index_written_by` being set; keying on presence would flag every healthy run.
    assert _is_engine_drift({"engine_build": {"running": "aaaa", "index_written_by": "bbbb"}})
    assert not _is_engine_drift({"engine_build": {"running": "aaaa", "index_written_by": None}})
    assert not _is_engine_drift({})

    # --- live-server classification: identity, never timestamps -----------
    # The bug this replaces: setup.sh re-copies the engine on every run, so file mtime/ctime
    # advance even when the bytes are identical, and dating a server against them flags every
    # live process after a routine no-op re-run. Builds are compared, so a no-op re-copy is
    # invisible here by construction.
    live = [("100", 1_000.0), ("200", 2_000.0), ("300", 3_000.0)]
    records = {
        "100": {"pid": 100, "build": "cur", "started_at": 1_000.0},   # matches -> clean
        "200": {"pid": 200, "build": "old", "started_at": 2_000.0},   # genuine drift
        # 300 has no record at all -> unknown
    }
    drift, unknown = _classify_servers(live, records, "cur")
    assert drift == ["200"], drift
    assert unknown == ["300"], unknown
    # A no-op re-copy changes no build id, so every server stays clean however new the files.
    assert _classify_servers([("100", 1_000.0)], records, "cur") == ([], [])
    # Pid reuse: the number is live again but belongs to a different process. A record whose
    # start time cannot be THIS process's must not lend it a build it never ran. A leftover
    # record ALWAYS predates the process that inherits its pid, so this is the negative side.
    recycled = [("100", 9_999.0)]
    assert _classify_servers(recycled, records, "cur") == ([], ["100"])
    # A record for a pid that is no longer live is simply not considered.
    assert _classify_servers([], records, "cur") == ([], [])
    # A build id we cannot read is UNKNOWN, never proven drift. "unknown" is the engine's own
    # fail-open sentinel from _engine_build(); server._engine_drift refuses to accuse on it for
    # the same reason — an accusation whose remedy is "restart" that the restart cannot clear.
    # Two copies of that rule exist now, so they are pinned to agree.
    for bad in ({"pid": 100, "build": "unknown", "started_at": 1_000.0},
                {"pid": 100, "started_at": 1_000.0}):
        assert _classify_servers([("100", 1_000.0)], {"100": bad}, "cur") == ([], ["100"])
    # Startup slack is ONE-SIDED. started_at is stamped after the launcher's prelude, which
    # includes the ADR-0018 pip resync — the one moment a plugin update makes drift matter
    # most, and the one most likely to run long. A symmetric window would file that server
    # under "publishes no build id" for its whole life, with a remedy that never clears it.
    slow = {"100": {"pid": 100, "build": "old", "started_at": 1_000.0 + 900}}
    assert _classify_servers([("100", 1_000.0)], slow, "cur") == (["100"], []), "slow startup"
    # ...but a record stamped BEFORE its process began is impossible for that process.
    early = {"100": {"pid": 100, "build": "old", "started_at": 1_000.0 - 900}}
    assert _classify_servers([("100", 1_000.0)], early, "cur") == ([], ["100"]), "pre-dated"
    # ps parsing: only real SERVER processes count. A `--reindex` can run for minutes and
    # matches the same binary path, but CLI runs write no build record — counting one would
    # report a permanent unknown-build server that is really just a busy reindex.
    ps_out = "\n".join([
        f"  501    02:00 {SS_BIN}",
        f"  502    01:00 {SS_BIN} --reindex --force",
        f"  503    00:30 {SS_BIN} --health",
        "  504    00:10 /usr/bin/python3 -m http.server",
        f"  505 garbage {SS_BIN}",
        f"  506    03:00 {SS_BIN} --some-future-flag",
    ])
    parsed = _parse_server_lines(ps_out, now=10_000.0)
    # 506 counts: an unrecognized flag falls through to the server branch upstream and DOES
    # write a record, so excluding it would hide a real server behind a green check.
    assert [p for p, _ in parsed] == ["501", "506"], parsed
    assert parsed[0][1] == 10_000.0 - 120                   # etime resolved to a start epoch
    # Pruning is keyed on "does this pid still exist", NOT on "did I see it in ps". The
    # records dir is shared by every install on the machine, but `ps` here only matches THIS
    # venv's binary — so pruning by the ps result would delete another install's LIVE record
    # and make its doctor report an unknown build. That is the very false alarm being fixed.
    # The --health memo must NOT survive a run_all() boundary. `doctor --fix` re-runs every
    # check AFTER repairing something; reusing the pre-fix report there makes the re-check
    # reprint the failure it just fixed and exit 1 on a system that is now healthy.
    # An unexpanded ${HOME} would silently point the reader at a directory no server writes
    # to, making every live server "unproven" forever — the failure this seam exists to avoid.
    assert "$" not in str(SERVER_RECORDS), f"unexpanded variable in {SERVER_RECORDS}"
    assert SERVER_RECORDS.is_absolute(), SERVER_RECORDS
    # Assert the WIRING, not the helper. Calling _reset_pass_caches() here and checking the
    # globals would pass while run_all() called a renamed/absent function — which is exactly
    # what happened once: the helper was verified in isolation, run_all() still named the old
    # one, and doctor died with a NameError that the green selftest had no way to see. So
    # drive the real run_all() and have a probe check what a check actually observes.
    global _HEALTH_RUN, _RUNNING_STATE
    seen = {}

    def _probe():
        seen["health"], seen["running"] = _HEALTH_RUN, _RUNNING_STATE
        return None

    _saved_checks = list(CHECKS)        # mutate in place: `global CHECKS` would have to be
    _HEALTH_RUN = "sentinel-from-a-previous-run"    # declared above its earlier reads here
    _RUNNING_STATE = "sentinel-from-a-previous-run"
    try:
        CHECKS[:] = [_probe]
        run_all()
    finally:
        CHECKS[:] = _saved_checks
    # BOTH per-pass caches reset from ONE place, so a future third cache cannot be added to
    # only half of the boundary. Any of them outliving a pass makes `--fix` re-report the
    # failure it just repaired and exit 1 on a system that is now healthy.
    assert seen.get("health") is None, "run_all() must invalidate the --health memo"
    assert seen.get("running") is _UNSET, "run_all() must invalidate the live-server memo"

    # --- drift remedy: doctor DECIDES what the engine can only offer as alternatives ---
    # The engine sees its own build and nothing else, so its message names both remedies.
    # doctor holds the live-server evidence in the same pass, so it resolves which applies.
    d, r = _drift_remedy("bbbb", "aaaa", ([], []))
    assert r == "reindex", "proven-clean must be auto-fixable — a reindex re-stamps it"
    assert "reindex" in d.lower() and "restart" not in d.lower(), d
    # A live server on an older build: a reindex writes OUR build and that server hands the
    # mismatch straight back. Auto-fixing here is the 0.20.6 defect, so fix must stay None.
    d, r = _drift_remedy("bbbb", "aaaa", (["77"], []))
    assert r is None and "restart" in d.lower() and "77" in d, d
    # Unproven is not proven-clean. Never auto-reindex on an unverified fleet.
    d, r = _drift_remedy("bbbb", "aaaa", ([], ["77"]))
    assert r is None and "restart" in d.lower(), d
    # No evidence at all (ps missing, engine too old to publish an id) -> stay conditional.
    d, r = _drift_remedy("bbbb", "aaaa", None)
    assert r is None and "reindex" in d.lower() and "restart" in d.lower(), d
    # The SEAM, not just the pure function. `_drift_remedy` can be perfect while
    # `check_engine_health` hands it the wrong fields — a mis-wire that names live pids as
    # "still on an older build" on a proven-CLEAN fleet, which is the exact failure this
    # release retires, and a selftest that only exercised `_drift_remedy` stayed green
    # through it. Everything here is patched, so nothing spawns, reads ps, or touches the
    # records dir: an earlier version called the real `_running_engine_state()` and deleted
    # files from ~/.cache/skill-search/servers as a side effect of running --selftest.
    _g = globals()
    _saved = {k: _g[k] for k in ("SS_BIN", "_health_run", "_running_engine_state")}
    try:
        _g["SS_BIN"] = Path(__file__)                       # merely has to exist
        _g["_health_run"] = lambda: subprocess.CompletedProcess(
            [], 0, stdout=json.dumps({
                "status": "degraded", "issues": ["engine drift"],
                "engine_build": {"running": "aaaa", "index_written_by": "bbbb"},
                "qdrant": {"reachable": True, "indexed": 418}}), stderr="")
        # Clean fleet, but two live pids present: the row must NOT name them as drifting.
        _g["_running_engine_state"] = lambda: RunningState("aaaa", ["11", "22"], [], [])
        row = check_engine_health()
        assert row["fix"] == "reindex", row
        assert "11" not in row["detail"] and "22" not in row["detail"], row
        # Same report, but one pid genuinely on another build -> never auto-fix.
        _g["_running_engine_state"] = lambda: RunningState("aaaa", ["11", "22"], ["11"], [])
        row = check_engine_health()
        assert row["fix"] is None and "11" in row["detail"], row
    finally:
        _g.update(_saved)
    assert _pid_alive(str(os.getpid())) is True
    assert _pid_alive("2147483646") is False                # far above any live pid
    assert _pid_alive("not-a-pid") is False
    with tempfile.TemporaryDirectory() as d:
        recs = Path(d)
        mine, dead = recs / f"{os.getpid()}.json", recs / "2147483646.json"
        for p in (mine, dead):
            p.write_text(json.dumps({"pid": int(p.stem), "build": "x", "started_at": 0}))
        _prune_server_records(recs)
        assert mine.exists(), "pruned a record whose process is still alive"
        assert not dead.exists(), "kept a record for a dead pid"
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
