#!/usr/bin/env python3
"""
skill-concierge doctor — deployment-layer health check + safe auto-fix.

Diagnoses the things `setup.sh` provisions — the stable engine venv, the index
owner, the MCP wiring, the settings.json budget overrides, the ledger dir — and
DELEGATES the retrieval-path diagnostic (embedder reachability, indexed vs dark/stale
skills, freshness) to the engine's own `skill-search --health`, so the two never drift.

Pure stdlib. Read-only by default. With --fix it attempts ONLY fast, safe repairs:
  • start a stopped index owner              → python -m skill_search.index_owner
  • stop + disable a revived skill-concierge  → docker update --restart=no + docker stop,
    container on the owner ports (6333/6363)    then start the owner (only once the owner's
                                                SQLite index exists — the cutover latch)
  • reindex a degraded / stale index         → skill-search --reindex
    (a stale-but-serving index is WARN, not FAIL — it still matches the indexed
     skills; only newly added/removed ones are missing until the refresh)
  • re-apply the curated settings overrides  → scripts/apply-overrides.py

The heavy bootstrap (building the venv, the first index build) is intentionally NOT
auto-run — that is `./setup.sh` (the `skill-concierge:setup` skill). doctor points there.

Usage:
  python3 scripts/doctor.py          # report only; exit 0 = healthy, 1 = degraded (FAIL)
  python3 scripts/doctor.py --fix    # attempt safe fixes, then re-check
  python3 scripts/doctor.py --cutover  # harness-version rows FAIL below the switch-over release

Env seams (mirror setup.sh): SKILL_CONCIERGE_VENV, SKILL_QDRANT_URL, SKILL_QDRANT_CONTAINER,
SKILL_EMBED_BACKEND, SKILL_EMBED_MODEL, SKILL_CONCIERGE_SETTINGS, SKILL_CONCIERGE_LOG,
SKILL_TRIGGERS, SKILL_SERVER_RECORDS.
"""
import argparse
import collections
import glob
import hashlib
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent              # skill-concierge/
VENV = Path(os.environ.get("SKILL_CONCIERGE_VENV", Path.home() / ".claude/skill-concierge/venv"))
QNAME = os.environ.get("SKILL_QDRANT_CONTAINER", "skill-search-qdrant")
SETTINGS = Path(os.environ.get("SKILL_CONCIERGE_SETTINGS", Path.home() / ".claude/settings.json"))
LOGDIR = Path(os.environ.get("SKILL_CONCIERGE_LOG", Path.home() / ".claude/skill-concierge/logs"))
# OMP (Oh My Pi) harness surface (ADR-0040) — the 4th first-class harness after
# Claude Code / Codex / Command Code. OMP installs the plugin through its OWN
# marketplace system (recorded in installed_plugins.json, catalog cloned under
# cache/marketplaces/, content pinned under cache/plugins/<name>___<name>___<ver>/),
# so the plugin's version inside OMP can silently lag the .claude-plugin/plugin.json
# SSOT. These are read-only facts about a DIFFERENT product's state; deliberately no
# env seams (the doctor's seams mirror setup.sh, which has no OMP counterpart).
OMP_DIR = Path.home() / ".omp"
OMP_PLUGINS_FILE = OMP_DIR / "plugins" / "installed_plugins.json"
OMP_MARKETPLACE = OMP_DIR / "plugins" / "cache" / "marketplaces" / "skill-concierge"
OMP_PLUGIN_CACHE = OMP_DIR / "plugins" / "cache" / "plugins"
# Codex harness surface (ADR-0033) — skill-concierge is installed as a Codex plugin.
# The plugin clones the marketplace repo into ~/.codex/plugins/cache/<name>/<name>/<ver>/;
# there is no install-record file (Codex tracks enablement in config.toml, unparseable
# on stdlib 3.10), so version must be read from the cached .codex-plugin/plugin.json.
# WARN-only — a Codex-free machine is one 'codex: not installed' row, not a failure.
CODEX_DIR = Path.home() / ".codex"
CODEX_PLUGIN_CACHE = CODEX_DIR / "plugins" / "cache" / "skill-concierge" / "skill-concierge"
# ZCode harness surface (ADR-0042) — skill-concierge installs through ZCode's plugin
# marketplace, which natively reads .claude-plugin/ manifests, fires the plugin hooks,
# and auto-connects the plugin .mcp.json (no adapter vehicle — the first harness with
# full Claude-format plugin parity). Cache at
# ~/.zcode/cli/plugins/cache/skill-concierge/skill-concierge/<ver>/. WARN-only.
ZCODE_DIR = Path.home() / ".zcode"
ZCODE_PLUGIN_CACHE = ZCODE_DIR / "cli" / "plugins" / "cache" / "skill-concierge" / "skill-concierge"
# ZCode's own install registry (adapters/zcode/install.sh writes it) — a flat list keyed by
# "id", unlike Claude Code's/OMP's map-of-scopes shape.
ZCODE_PLUGINS_FILE = ZCODE_DIR / "cli" / "plugins" / "installed_plugins.json"
# Claude Code harness surface — the reference harness, kept current by
# adapters/claude-code/install.sh (a CLI refresh, falling back to a git-archive sync).
CLAUDE_PLUGINS_DIR = Path.home() / ".claude" / "plugins"
CLAUDE_PLUGINS_FILE = CLAUDE_PLUGINS_DIR / "installed_plugins.json"
# Command Code harness surface (ADR-0038) — skill-concierge integrates via a mod,
# SessionStart hooks in settings.json, and an mcp.json entry. No version record file
# (the mod and settings reference the dev path directly). WARN-only.
CCMD_DIR = Path.home() / ".commandcode"
CCMD_MOD = CCMD_DIR / "mods" / "skill-concierge.ts"
CCMD_SETTINGS = CCMD_DIR / "settings.json"
CCMD_MCP = CCMD_DIR / "mcp.json"
_CCMD_SETTINGS_HOOK_MARKER = "skill-concierge"  # SessionStart commands contain this string
# Command Code accepts exactly four hook events (its dist constant Ry). Any other key in
# settings.json is skipped with kind "unknown_event" and surfaces in the TUI as
# "1 hook config issue: 1 unknown event". Claude's five-event set (which adds
# UserPromptSubmit/PreCompact) must never be copied verbatim into CC settings.
CCMD_HOOK_EVENTS = frozenset({"PreToolUse", "PostToolUse", "Stop", "SessionStart"})
# Skills roots Command Code reads. A stray ~/.commandcode/skills/SKILL.md — a FILE at the
# ROOT of a skills dir — silently discards EVERY skill in that root (observed: 0 installed,
# then 647 with only that file moved out). ~/.agents/skills is the same symlinked shelf.
CCMD_SKILLS_ROOTS = (CCMD_DIR / "skills", Path.home() / ".agents" / "skills")
# DSH (DeepSeek Harness) surface (ADR-0050) — skill-concierge integrates via the
# Cordis composition patch system (cordis.patch.yml) and the dsh-mcp-client MCP bridge.
# DSH_HOME resolves to ~/.ohdsh (Oh-DSH Desktop) or ~/.dsh (legacy dsh CLI).
# WARN-only — no DSH install is one 'dsh: not installed' row, never a failure.
DSH_DIR = Path(os.environ.get(
    "SKILL_DSH_HOME",
    os.environ.get("DSH_HOME", (
        Path.home() / ".ohdsh" if (Path.home() / ".ohdsh").is_dir() else Path.home() / ".dsh"))))
DSH_PATCH = DSH_DIR / "profiles" / "desktop" / "cordis.patch.yml"
DSH_TUI_PATCH = DSH_DIR / "profiles" / "tui" / "cordis.patch.yml"
# Same seam as flywheel.py/llm_triggers.py: the engine reads triggers from SKILL_TRIGGERS. The
# env-less default is durable-home-first with the legacy repo-local path as fallback (the
# 0.25.1 thresholds pattern): the live .mcp.json pins the durable home, so a doctor run from a
# fresh plugin cache WITHOUT that env used to look at <cache>/eval/triggers.json — absent by
# construction — and report "utterance layer unused" against a working config (Codex
# revalidation defect D4).
_TRIGGERS_DURABLE = Path.home() / ".claude" / "skill-concierge" / "triggers.json"
_trig_env = os.environ.get("SKILL_TRIGGERS")
TRIGGERS = Path(_trig_env) if _trig_env else (
    _TRIGGERS_DURABLE if _TRIGGERS_DURABLE.exists() else ROOT / "eval" / "triggers.json")
COLLECTION = os.environ.get("SKILL_COLLECTION", "claude_skills")
MULTIVECTOR = os.environ.get("SKILL_MULTIVECTOR", "1") != "0"   # multi-vector trigger layer (default on)

OK, WARN, FAIL = "ok", "warn", "fail"
GLYPH = {OK: "✓", WARN: "!", FAIL: "✗"}           # ✓ ! ✗
JSON_READ_ERRORS = (OSError, AttributeError, KeyError, TypeError, ValueError)
NETWORK_READ_ERRORS = (*JSON_READ_ERRORS, http.client.HTTPException)


def read_mcp_env():
    """Embedder + store come from .mcp.json (single source of truth); env overrides win.
    Returns the merged mapping (mcp.json layer overlaid by the process env) — callers read
    whichever key they need from it, including the port-deriving keys ports.py owns."""
    conf = {}
    try:
        conf = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["skill-search"]["env"]
    except JSON_READ_ERRORS:
        conf = {}
    if not isinstance(conf, dict):
        conf = {}
    return {**conf, **os.environ}


sys.path.insert(0, str(ROOT / "vendor" / "skill-search"))
from skill_search import ports  # noqa: E402  (needs ROOT on sys.path first)

_MCP_ENV = read_mcp_env()
BACKEND = _MCP_ENV.get("SKILL_EMBED_BACKEND", "fastembed")
MODEL = _MCP_ENV.get("SKILL_EMBED_MODEL", "")
# The same strict grammar every port-deriving caller applies (skill_search.ports): ASCII
# digits only, 1-65535. A malformed OR merely absent port in SKILL_QDRANT_URL must land
# doctor on the SAME well-known default the index owner (index_owner.py) falls back to —
# reassigning QURL itself, not just a side variable, means every direct network call below
# that uses QURL gets the corrected address too. Left unfixed, a URL with no port at all
# (e.g. a trailing "http://127.0.0.1:") does not raise, but `http.client`/`urllib` then
# silently connect on port 80 (the browser default) instead of failing or using 6333.
QURL, _qurl_notice = ports.resolved_qdrant_url(env=_MCP_ENV, default_port=6333)
if _qurl_notice:
    print(f"skill-concierge doctor: {_qurl_notice}", file=sys.stderr)
SS_BIN = VENV / "bin" / "skill-search"
PY_BIN = VENV / "bin" / "python"
# The local index owner (skill_search.index_owner) replaces the Qdrant + embed-shim
# containers: Qdrant-compatible REST on the store port, /embed + /health on the embed port,
# one SQLite file it alone writes. `GET /` on the store port answers OWNER_TITLE — the same
# probe the owner itself uses to tell a sibling owner from a foreign answerer.
OWNER_TITLE = "skill-concierge index owner (Qdrant-compatible subset)"
INDEX_DB = Path(os.environ.get("SKILL_INDEX_DB", Path.home() / ".cache/skill-search/index.sqlite"))
OWNER_LOG = LOGDIR / "index-owner.log"
ENAME = os.environ.get("SKILL_EMBED_CONTAINER", "skill-concierge-embed-shim")

# The owner's two ports as configured (store URL + embed port), 6333/6363 by default: a
# container publishing either one is in the owner's way; one on some other port is not.
_store_port = urllib.parse.urlsplit(QURL).port
_embed_port = ports.embed_port(default=6363)
EMBED_BASE = f"http://127.0.0.1:{_embed_port}"
OWNER_PORTS = (str(_store_port), str(_embed_port))
# The embed parity probe: one English and one Vietnamese prompt, owner vs in-process.
PARITY_TEXTS = ("find the right skill to deploy a web app",
                "tìm kỹ năng phù hợp để triển khai ứng dụng web")
PARITY_MIN_COSINE = 0.9999
# In-process model load for the parity probe (fastembed onnx, cold-start can be slow on a
# fresh cache) — bounded so a stuck load can never hang doctor forever.
EMBED_PARITY_LOAD_TIMEOUT_S = 60


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
    except JSON_READ_ERRORS:
        pinned = None
    raw = pinned or os.environ.get("SKILL_SERVER_RECORDS") or str(Path.home() / ".cache/skill-search/servers")
    return Path(os.path.expandvars(raw)).expanduser()


# One `<pid>.json` per live MCP server, naming the engine build that process actually runs.
SERVER_RECORDS = read_server_records_dir()


def _run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, check=False, **kw)


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
    except (TypeError, ValueError):
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
    """The query server's engine settings (scripts/engine_env.py), doctor's resolved store on top."""
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        import engine_env
        base = engine_env.engine_env(ROOT)
    except Exception:
        base = dict(os.environ)
    return {**base, "SKILL_QDRANT_URL": QURL,
            "SKILL_EMBED_BACKEND": BACKEND, "SKILL_EMBED_MODEL": MODEL}


def _qdrant_reachable(timeout=3):
    for u in (QURL.rstrip("/") + "/healthz", QURL):
        try:
            with urllib.request.urlopen(u, timeout=timeout) as resp:
                reachable = resp.status == 200
        except (OSError, ValueError, http.client.HTTPException):
            reachable = False
        if reachable:
            return True
    return False


def _get_json(url, timeout=3):
    """Parsed JSON body of a GET, or None on any network/parse failure."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read())
    except (*NETWORK_READ_ERRORS, urllib.error.URLError):
        return None


def _store_title():
    """`GET /` title of whatever answers the store URL; None when nothing answers. A loading
    owner answers 503 with its title, so an HTTP error body is read too."""
    try:
        with urllib.request.urlopen(QURL.rstrip("/") + "/", timeout=3) as resp:
            root = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        try:
            root = json.loads(exc.read())
        except (*NETWORK_READ_ERRORS, urllib.error.URLError):
            return None
    except (*NETWORK_READ_ERRORS, urllib.error.URLError):
        return None
    return root.get("title") if isinstance(root, dict) else None


def _owner_health():
    """The owner's `/health` JSON on the embed port, or None when it does not answer."""
    h = _get_json(EMBED_BASE + "/health")
    return h if isinstance(h, dict) else None


def _wait_owner(timeout=90):
    """The owner binds first, then loads the index and the model (503 until loaded) — poll
    /health so a fix that starts it doesn't race the reindex that follows."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        h = _owner_health()
        if h and h.get("status") == "ok":
            return True
        time.sleep(1)
    return False


def _publishing_containers():
    """[(name, ports)] of running containers that publish an owner port, or None when
    docker is unavailable. Parsed from `docker ps` "Ports" (e.g. `127.0.0.1:6333->6333/tcp`)."""
    docker = shutil.which("docker")
    if not docker:
        return None
    r = _run([docker, "ps", "--format", "{{.Names}}\t{{.Ports}}"])
    if r.returncode != 0:
        return None
    return _parse_publishers(r.stdout)


def _parse_publishers(text):
    out = []
    for line in text.splitlines():
        name, _, ports = line.partition("\t")
        host_ports = {seg.split("->")[0].rsplit(":", 1)[-1]
                      for seg in ports.split(",") if "->" in seg}
        if host_ports & set(OWNER_PORTS):
            out.append((name.strip(), ports.strip()))
    return out


def start_owner():
    """Start the index owner detached from the shared venv; never waited on here.

    Always `python -m skill_search.index_owner` from the stable venv, never from a harness
    plugin cache. A duplicate start is harmless: the second owner loses the file lock (or the
    port bind) and exits in milliseconds. Returns (ok, message)."""
    if not PY_BIN.exists():
        return False, f"venv python missing at {PY_BIN} — run ./setup.sh"
    OWNER_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(OWNER_LOG, "ab") as log:
        subprocess.Popen([str(PY_BIN), "-m", "skill_search.index_owner"],
                         stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                         start_new_session=True)
    return True, "started the index owner"


def _last_line(text):
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    return lines[-1] if lines else ""


# ---------- checks: each returns a dict (or None to skip) ----------

def check_python():
    if SS_BIN.exists():
        return None                                        # venv built — prereq moot
    found = next((c for c in ("python3.12", "python3.11", "python3.10") if shutil.which(c)), None)
    if found:
        return {"id": "python", "label": "Python 3.10-3.12", "status": OK, "detail": found, "fix": None}
    return {"id": "python", "label": "Python 3.10-3.12", "status": FAIL,
                "detail": "no python3.10-3.12 on PATH (set SKILL_PYTHON, then ./setup.sh)", "fix": "setup"}


def check_venv():
    if SS_BIN.exists() and os.access(SS_BIN, os.X_OK):
        return {"id": "venv", "label": "Engine venv", "status": OK, "detail": str(VENV), "fix": None}
    return {"id": "venv", "label": "Engine venv", "status": FAIL,
                "detail": f"no skill-search bin at {SS_BIN} — run ./setup.sh", "fix": "setup"}


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
        except OSError:
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
        return {"id": "engine_fresh", "label": "Engine freshness", "status": WARN,
                    "detail": "venv engine code DIFFERS from the deployed plugin source — the MCP is "
                           "serving STALE engine code after a plugin update; rerun ./setup.sh "
                           "(skill-concierge:setup), then restart Claude Code", "fix": "setup"}
    return {"id": "engine_fresh", "label": "Engine freshness", "status": OK,
                "detail": "venv engine matches deployed source", "fix": None}


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
    except ValueError:
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
        except JSON_READ_ERRORS:
            rec = None
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
        return {"id": "engine_running", "label": "Running engine", "status": WARN,
                    "detail": f"{len(drift)} live MCP server(s) run a DIFFERENT engine build than "
                           f"the one on disk ({current}) — pid {', '.join(drift)}. They execute "
                           f"the OLD code, which shows up as a false 'disk changed since last "
                           f"index'. Restart Claude Code; reindexing will not fix it", "fix": None}
    if unknown:
        # State the OBSERVATION, not a cause. Several paths land here and they do not share a
        # remedy: a server predating this engine (a restart clears it), an unwritable records
        # dir, a `SKILL_SERVER_RECORDS` that differs between the server's env and this one, or
        # a record naming no build. Asserting "started before this engine" would send the user
        # to restart on the ones a restart cannot fix.
        return {"id": "engine_running", "label": "Running engine", "status": WARN,
                    "detail": f"no build record for {len(unknown)} live MCP server(s) (pid "
                           f"{', '.join(unknown)}), so their engine cannot be compared with the "
                           f"one on disk ({current}). Usual cause: they started before this "
                           f"engine was installed — restart Claude Code and it clears. If it "
                           f"persists after a restart, check {SERVER_RECORDS} is writable and "
                           f"that SKILL_SERVER_RECORDS is not set differently for the server "
                           f"than for this shell", "fix": None}
    return {"id": "engine_running", "label": "Running engine", "status": OK,
                "detail": f"{len(live)} live MCP server(s) run the current engine build ({current})"
                       if live else "no live MCP server", "fix": None}


def check_mcp_wiring():
    launcher = ROOT / "bin" / "skill-search-mcp"
    probs = []
    mcp = ROOT / ".mcp.json"
    if not mcp.exists():
        probs.append(".mcp.json missing")
    else:
        try:
            json.loads(mcp.read_text(encoding="utf-8"))
        except JSON_READ_ERRORS:
            probs.append(".mcp.json invalid JSON")
    if not launcher.exists():
        probs.append("bin/skill-search-mcp missing")
    elif not os.access(launcher, os.X_OK):
        probs.append("bin/skill-search-mcp not executable (chmod +x)")
    if probs:
        return {"id": "mcp", "label": "MCP wiring", "status": FAIL, "detail": "; ".join(probs), "fix": None}
    return {"id": "mcp", "label": "MCP wiring", "status": OK, "detail": "launcher + .mcp.json present", "fix": None}


def _owner_row(status, detail, fix=None):
    return {"id": "owner", "label": "Index owner", "status": status, "detail": detail, "fix": fix}


def _sqlite_report(db):
    """(integrity, {collection: points}) of the owner's SQLite file, opened READ-ONLY — the
    owner is its only writer. Raises sqlite3.Error / OSError on an unreadable file."""
    import sqlite3
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
    try:
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        counts = dict(con.execute("SELECT collection, COUNT(*) FROM points GROUP BY collection"))
    finally:
        con.close()
    return integrity, counts


def check_owner():
    """The index owner: who answers the store port, its /health + code_version, the REST
    point count, and the SQLite file's integrity + point counts.

    FAIL when the store port answers with anything that is not the owner (a revived Qdrant
    container wins `localhost` there) or nothing answers at all (fix: start the owner)."""
    title = _store_title()
    if title is None:
        return _owner_row(FAIL, f"nothing answers {QURL} — the index owner is down", "owner")
    if title != OWNER_TITLE:
        return _owner_row(FAIL, f"{QURL} answers as '{title}', not the index owner — stop that "
                                "service (doctor --fix stops a revived skill-concierge container)",
                          "containers")
    health = _owner_health()
    if not health or health.get("status") != "ok":
        return _owner_row(FAIL, f"owner answers {QURL} but {EMBED_BASE}/health is not ok "
                                f"({health}) — still loading, or the embed port is taken")
    notes = []
    code = health.get("code_version")
    stamp = None
    try:
        stamp = (VENV / ".engine-plugin-version").read_text(encoding="utf-8").strip()
    except OSError:
        pass
    status = OK
    if stamp and code != stamp:
        status = WARN
        notes.append(f"owner runs code_version {code} but the venv stamp is {stamp} "
                     "(a downgraded stamp is ignored — the owner keeps serving code_version "
                     "unchanged; it only exits and restarts when the stamp is rewritten upward)")
    info = _get_json(f"{QURL.rstrip('/')}/collections/{COLLECTION}")
    rest_points = ((info or {}).get("result") or {}).get("points_count")
    if not rest_points:
        return _owner_row(FAIL, f"owner has no points in '{COLLECTION}' — run ./setup.sh "
                                "(reindex)", "reindex")
    try:
        integrity, counts = _sqlite_report(INDEX_DB)
    except Exception as exc:   # sqlite3.Error is imported lazily; any failure is the finding
        return _owner_row(FAIL, f"cannot read {INDEX_DB} ({type(exc).__name__}: {exc})")
    if integrity != "ok":
        return _owner_row(FAIL, f"{INDEX_DB} PRAGMA integrity_check: {integrity}")
    if counts.get(COLLECTION) != rest_points:
        status = WARN
        notes.append(f"SQLite holds {counts.get(COLLECTION)} points, REST reports {rest_points} "
                     "(a write landed between the two reads, or the owner serves another file)")
    detail = (f"{QURL} + {EMBED_BASE}; code_version {code}; {rest_points} points; "
              f"db {INDEX_DB} integrity ok")
    return _owner_row(status, "; ".join([detail] + notes))


def check_owner_ports():
    """FAIL when any container publishes an owner port: after the cutover nothing but the
    owner may hold 6333/6363. An old harness copy's setup.sh or doctor --fix revives Docker."""
    pubs = _publishing_containers()
    if pubs is None:
        return {"id": "owner_ports", "label": "Owner ports", "status": OK,
                "detail": "docker not available — no container can hold the owner ports", "fix": None}
    if not pubs:
        return {"id": "owner_ports", "label": "Owner ports", "status": OK,
                "detail": f"no container publishes {'/'.join(OWNER_PORTS)}", "fix": None}
    ours = [n for n, _ in pubs if n in (QNAME, ENAME)]
    return {"id": "owner_ports", "label": "Owner ports", "status": FAIL,
            "detail": "container publishes an owner port: "
                      + ", ".join(f"{n} ({p})" for n, p in pubs)
                      + ("" if ours else " — not a skill-concierge container; stop it by hand"),
            "fix": "containers" if ours else None}


# Lines the owner writes when it refuses to take over a port or sees a downgraded venv stamp.
_OWNER_LOG_ALARM = ("port conflict", "port-conflict", "downgrade")


def check_owner_log():
    """FAIL when index-owner.log holds a downgrade or port-conflict line: the owner refused a
    port some other service answered, or an old harness copy downgraded the shared venv."""
    try:
        lines = OWNER_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {"id": "owner_log", "label": "Owner log", "status": OK,
                "detail": f"no {OWNER_LOG.name} yet", "fix": None}
    hits = [ln for ln in lines if any(k in ln.lower() for k in _OWNER_LOG_ALARM)]
    if not hits:
        return {"id": "owner_log", "label": "Owner log", "status": OK,
                "detail": f"{OWNER_LOG.name}: no downgrade or port-conflict line", "fix": None}
    return {"id": "owner_log", "label": "Owner log", "status": FAIL,
            "detail": f"{len(hits)} alarm line(s) in {OWNER_LOG}; latest: {hits[-1].strip()[:200]} "
                      "— resolve the cause, then truncate the log", "fix": None}


_PARITY_SCRIPT = (
    "import json,sys\n"
    "from fastembed import TextEmbedding\n"
    "m=TextEmbedding(model_name=sys.argv[1])\n"
    "print(json.dumps([list(map(float,v)) for v in m.embed(json.loads(sys.argv[2]))]))\n")


def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def check_embed_parity():
    """The owner's /embed must match the in-process model the MCP falls back to (EN + VN,
    cosine ≥ PARITY_MIN_COSINE) — otherwise the index and the query side disagree."""
    health = _owner_health()
    if not health or health.get("status") != "ok":
        return None                      # check_owner already reports a down owner
    model = health.get("model") or MODEL
    owner = []
    try:
        for text in PARITY_TEXTS:
            req = urllib.request.Request(
                EMBED_BASE + "/embed", data=json.dumps({"text": text}).encode("utf-8"),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                owner.append(json.loads(resp.read())["vector"])
    except (*NETWORK_READ_ERRORS, urllib.error.URLError) as exc:
        return {"id": "embed_parity", "label": "Embed parity", "status": FAIL,
                "detail": f"owner /embed failed ({type(exc).__name__}: {exc})", "fix": None}
    if not PY_BIN.exists():
        return {"id": "embed_parity", "label": "Embed parity", "status": WARN,
                "detail": "venv missing — in-process side of the probe unavailable", "fix": "setup"}
    try:
        r = _run([str(PY_BIN), "-c", _PARITY_SCRIPT, model, json.dumps(list(PARITY_TEXTS))],
                 timeout=EMBED_PARITY_LOAD_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return {"id": "embed_parity", "label": "Embed parity", "status": WARN,
                "detail": f"in-process embed load timed out after {EMBED_PARITY_LOAD_TIMEOUT_S}s "
                          "(model load stuck?)", "fix": None}
    try:
        local = json.loads(r.stdout)
    except ValueError:
        return {"id": "embed_parity", "label": "Embed parity", "status": WARN,
                "detail": f"in-process embed failed: {_last_line(r.stderr)}", "fix": None}
    cos = [_cosine(a, b) for a, b in zip(owner, local)]
    low = min(cos) if cos else 0.0
    status = OK if len(cos) == len(PARITY_TEXTS) and low >= PARITY_MIN_COSINE else FAIL
    return {"id": "embed_parity", "label": "Embed parity", "status": status,
            "detail": f"{model}: EN {cos[0]:.6f}, VN {cos[-1]:.6f} (bar {PARITY_MIN_COSINE})",
            "fix": None}


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
        return {"id": "health", "label": "Retrieval health", "status": FAIL,
                    "detail": "engine venv missing — run ./setup.sh", "fix": "setup"}
    r = _health_run()
    try:
        rep = json.loads(r.stdout)
    except (TypeError, ValueError):
        rep = None
    if not isinstance(rep, dict):
        return {"id": "health", "label": "Retrieval health", "status": FAIL,
                    "detail": (r.stderr.strip() or "could not parse --health output")[:200], "fix": "reindex"}
    issues = rep.get("issues") or []
    idx = rep.get("qdrant", {}).get("indexed", "?")
    if rep.get("status") == "ok" and not issues:
        return {"id": "health", "label": "Retrieval health", "status": OK,
                    "detail": f"{idx} skills indexed; embedder + qdrant reachable{_fresh(rep)}", "fix": None}
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
        return {"id": "health", "label": "Retrieval health", "status": WARN,
                    "detail": detail, "fix": fix}
    # Stale-but-serving is degraded, not broken: WARN (auto-fixable via reindex) so the
    # exit code distinguishes "index needs a refresh" from "retrieval is down".
    if _stale_only(rep):
        return {"id": "health", "label": "Retrieval health", "status": WARN,
                    "detail": f"index stale{_fresh(rep)} — {idx} indexed & serving; run reindex to refresh",
                    "fix": "reindex"}
    return {"id": "health", "label": "Retrieval health", "status": FAIL,
                "detail": "; ".join(str(i) for i in issues)[:300], "fix": "reindex"}


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
    except NETWORK_READ_ERRORS:
        return {"id": "prompt_intent", "label": "Actionability gate", "status": WARN,
                    "detail": f"'{coll}' collection missing — gate fails-open (no suppression); "
                           "rebuild from transcripts", "fix": "prompt_intent"}
    if not total:
        return {"id": "prompt_intent", "label": "Actionability gate", "status": WARN,
                    "detail": f"'{coll}' empty — gate fails-open; rebuild from transcripts",
                    "fix": "prompt_intent"}
    return {"id": "prompt_intent", "label": "Actionability gate", "status": OK,
                "detail": f"{total} labelled prompts in '{coll}'", "fix": None}


def check_overrides():
    if not SETTINGS.exists():
        return {"id": "overrides", "label": "Settings overrides", "status": WARN,
                    "detail": f"{SETTINGS} not found", "fix": "overrides"}
    try:
        s = json.loads(SETTINGS.read_text(encoding="utf-8"))
    except JSON_READ_ERRORS:
        s = None
    if not isinstance(s, dict):
        return {"id": "overrides", "label": "Settings overrides", "status": FAIL,
                    "detail": f"{SETTINGS} invalid JSON", "fix": None}
    ov = s.get("skillOverrides")
    if not ov:
        return {"id": "overrides", "label": "Settings overrides", "status": WARN,
                    "detail": "no skillOverrides — budget not applied", "fix": "overrides"}
    on = sum(1 for v in ov.values() if v == "on")
    base = f"{on} on / {len(ov) - on} name-only"
    # Drift check: is the override map still in sync with the installed catalogue? The
    # detector lives in apply-overrides.py (--check) so the discovery logic stays in ONE
    # place. It exits 1 on drift AND on applier errors, so key off the "drift:" marker in
    # stdout — an error (invalid keep-on / no skills) must not masquerade as drift. Fail-open.
    py = PY_BIN if PY_BIN.exists() else Path(sys.executable)
    r = _run([str(py), str(ROOT / "scripts" / "apply-overrides.py"), "--check"])
    if r.returncode == 1 and "drift:" in r.stdout:
        return {"id": "overrides", "label": "Settings overrides", "status": WARN,
                    "detail": f"{base} — {_last_line(r.stdout)} "
                           f"(auto-heals on session start; or run apply-overrides)", "fix": "overrides"}
    return {"id": "overrides", "label": "Settings overrides", "status": OK, "detail": base, "fix": None}


def check_blocklist():
    """ADR-0046 disable tier. An absent file IS the healthy no-op default (nothing
    disabled); a present file must parse and carry a "blocked" list, and the
    PreToolUse deny guard must exist or no disable is actually enforced."""
    guard = ROOT / "hooks" / "scripts" / "skill_guard.py"
    if not guard.exists():
        return {"id": "blocklist", "label": "Blocklist", "status": FAIL,
                    "detail": f"{guard} missing — the PreToolUse deny gate is gone "
                              "(re-install the plugin)", "fix": None}
    path = Path(os.environ.get(
        "SKILL_CONCIERGE_BLOCKLIST",
        Path.home() / ".claude" / "skill-concierge" / "blocklist.json"))
    if not path.exists():
        return {"id": "blocklist", "label": "Blocklist", "status": OK,
                    "detail": "no blocklist (nothing disabled)", "fix": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except JSON_READ_ERRORS:
        return {"id": "blocklist", "label": "Blocklist", "status": FAIL,
                    "detail": f"{path} invalid JSON — guard fails open, nothing is denied",
                    "fix": None}
    lst = data.get("blocked") if isinstance(data, dict) else None
    if not isinstance(lst, list):
        return {"id": "blocklist", "label": "Blocklist", "status": FAIL,
                    "detail": f"{path} has no \"blocked\" list", "fix": None}
    return {"id": "blocklist", "label": "Blocklist", "status": OK,
                "detail": f"{len(lst)} skill(s) disabled — {path}", "fix": None}


def check_ledger():
    try:
        LOGDIR.mkdir(parents=True, exist_ok=True)
        writable = os.access(LOGDIR, os.W_OK)
    except OSError as exc:
        return {"id": "ledger", "label": "Ledger dir", "status": WARN, "detail": str(exc), "fix": None}
    return {"id": "ledger", "label": "Ledger dir", "status": (OK if writable else WARN),
                "detail": str(LOGDIR), "fix": None}


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


def _skill_search_statuses(mcp_list_text):
    """{name: status-text} for real skill-search installs, from `claude mcp list`.

    Same line shape and same exclusion as _skill_search_servers (an unexpanded
    ${CLAUDE_PLUGIN_ROOT} is this repo's own .mcp.json template being auto-loaded as a project
    MCP when CWD is the source repo, not an install). The status is whatever follows the LAST
    " - " on the row: "✔ Connected", "⊘ Disabled for this project (...)", "⏸ Pending approval
    (...)", "✘ Failed ...".
    """
    out = {}
    for ln in mcp_list_text.splitlines():
        name, sep, rest = ln.partition(": ")
        if not sep:
            continue
        name = name.strip()
        if not (name == "skill-search" or name.endswith(":skill-search")):
            continue
        if "${CLAUDE_PLUGIN_ROOT}" in rest:
            continue
        out[name] = rest.rsplit(" - ", 1)[-1].strip() if " - " in rest else ""
    return out


def check_mcp_enabled():
    """Is the skill-search MCP actually REACHABLE from this project?

    Every other check here answers "is the index healthy". None of them answers "can the agent
    reach it", and the two come apart: an install disabled for the current project (`/mcp`, or a
    project-scoped `disabledMcpjsonServers`) leaves the whole engine green while the agent has no
    `search_skills` tool at all. Observed 2026-08-24 — a full session ran with the concierge dark
    while doctor reported OK on every line. That is precisely the "skills go dark silently" mode
    this script exists to catch, so it gets its own check rather than riding on `Duplicate MCP`,
    which counts installs and says nothing about their state.

    The enforcer offer is NOT affected (it queries the index owner directly over REST), so this is a WARN,
    not a FAIL: retrieval still works, the pull tool does not. Fail-open to N/A whenever the CLI
    is missing or the call fails — an unreadable status is not evidence of a problem.
    """
    claude = shutil.which("claude")
    if not claude:
        return None
    r = _run([claude, "mcp", "list"])
    if r.returncode != 0:
        return None
    statuses = _skill_search_statuses(r.stdout)
    if not statuses:
        return {"id": "mcpenabled", "label": "MCP reachable", "status": WARN,
                    "detail": "no skill-search MCP install found in `claude mcp list` — the "
                           "search_skills / get_skill tools are unavailable in this project "
                           "(the enforcer's per-turn offer is unaffected; it queries the "
                           "index owner directly). Install or re-enable the plugin.", "fix": None}
    live = [n for n, st in statuses.items() if "Connected" in st]
    if live:
        return {"id": "mcpenabled", "label": "MCP reachable", "status": OK,
                    "detail": f"{live[0]} connected", "fix": None}
    worst = "; ".join(f"{n}: {st or 'unknown state'}" for n, st in sorted(statuses.items()))
    return {"id": "mcpenabled", "label": "MCP reachable", "status": WARN,
                "detail": f"skill-search is installed but NOT connected here — {worst}. "
                       "search_skills / get_skill are unavailable in this project even though "
                       "the index is healthy; re-enable via /mcp. The enforcer's per-turn offer "
                       "is unaffected (it queries the index owner over REST).", "fix": None}


def check_dup_mcp():
    claude = shutil.which("claude")
    if not claude:
        return None
    r = _run([claude, "mcp", "list"])
    if r.returncode != 0:
        return None
    servers = _skill_search_servers(r.stdout)
    if len(servers) > 1:
        return {"id": "dupmcp", "label": "Duplicate MCP", "status": WARN,
                    "detail": f"{len(servers)} skill-search installs ({', '.join(servers)}) — "
                           f"remove the extra: claude mcp remove <name> (check its scope first)",
                    "fix": None}
    return {"id": "dupmcp", "label": "Duplicate MCP", "status": OK, "detail": "single skill-search MCP", "fix": None}


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
    except NETWORK_READ_ERRORS:
        return None
    if trig == 0:
        if MULTIVECTOR:
            # env expects multi-vector but the index has none -> retrieval silently degraded to
            # single-vector (lower recall, more getaways). This is the "skills go dark silently"
            # mode the doctor exists to catch — WARN, auto-fixable by reindex.
            return {"id": "multivector", "label": "Multi-vector layer", "status": WARN,
                        "detail": "SKILL_MULTIVECTOR on but 0 trigger points — retrieval degraded to "
                               "single-vector; reindex to build the trigger layer", "fix": "reindex"}
        return {"id": "multivector", "label": "Multi-vector layer", "status": OK,
                    "detail": "off — one bare vector per skill", "fix": None}
    return {"id": "multivector", "label": "Multi-vector layer", "status": OK,
                "detail": f"{trig} trigger points (+ base) of {total} total — MAX-pooled retrieval",
                "fix": None}


def check_corpus_health():
    """Per-skill calibration corpus health. Reads eval/thresholds.json (from
    calibrate_thresholds.py): how many skills have cosine separation strong enough for a
    trustworthy per-skill tau. `weak`/`no-signal` skills can't be fixed by ANY threshold —
    the lever is index content (e.g. multi-vector) or contrastive negatives. Surfaced here
    so the fix-list is visible in the normal health workflow. Read-only, fail-open: missing
    file -> N/A (calibration is optional); WARN only if calibration is wholly signal-less."""
    # Durable home first (survives /plugin update), then the legacy cache-local copy, honoring
    # the same SKILL_THRESHOLDS env seam the calibrator uses — this check
    # previously hardcoded the cache path and went silently N/A on every fresh release cache.
    env = os.environ.get("SKILL_THRESHOLDS")
    durable = Path.home() / ".claude" / "skill-concierge" / "thresholds.json"
    legacy = ROOT / "eval" / "thresholds.json"
    path = Path(env) if env else (durable if durable.exists() else legacy)
    if not path.exists():
        return None  # calibration is optional; its absence is not a deployment fault
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except JSON_READ_ERRORS:
        return {"id": "corpus", "label": "Corpus health", "status": WARN,
                    "detail": f"{path.name} invalid JSON — re-run calibrate_thresholds.py", "fix": None}
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
    return {"id": "corpus", "label": "Corpus health", "status": status, "detail": detail, "fix": None}


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
        except JSON_READ_ERRORS:
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
        # (b) per-skill error detail — the run's `skills[].detail` (when present) is the
        # only place that records WHY a specific skill failed (timeout vs validation vs
        # rate-limit). Old runs have no `detail` key — gracefully ignored.
        try:
            errs = [sk for sk in (run.get("skills") or []) if sk.get("status") == "error" and sk.get("detail")]
            if errs:
                # Keep doctor detail on one line — truncate to first 2 with ellipsis
                sample = "; ".join(f"{e['name']}: {e['detail']}" for e in errs[:2])
                s += f" — per-skill errors ({len(errs)}): {sample}"
                if len(errs) > 2:
                    s += f" (+{len(errs)-2} more; see manifest)"
        except Exception:
            pass
        return s

    configured = "FLYWHEEL_LLM_ENDPOINT" in os.environ or "FLYWHEEL_LLM_MODEL" in os.environ
    has_key = bool(os.environ.get("FLYWHEEL_LLM_API_KEY"))
    fix = "run the skill-concierge:flywheel skill"

    if not configured:
        return {"id": "flywheel", "label": "Retrieval flywheel", "status": OK,
                    "detail": "not configured — utterance layer runs in fallback "
                           f"(description+body only){_last_run_suffix()}", "fix": fix}

    endpoint_detail = f"{flywheel_llm.ENDPOINT} ({flywheel_llm.MODEL}" \
                       f"{', keyed' if has_key else ', no key'})"
    ok, ping_detail = flywheel_llm.ping()
    if not ok:
        return {"id": "flywheel", "label": "Retrieval flywheel", "status": WARN,
                    "detail": f"configured ({endpoint_detail}) but unreachable — "
                           f"{ping_detail}{_last_run_suffix()}",
                    "fix": fix}

    # Coverage: indexed base-skill names vs eval/triggers.json entries with a non-empty
    # llm_triggers.triggers list.
    covered = set()
    if not TRIGGERS.exists():
        # Absent triggers file is NOT "nothing covered" — reporting 0/N here reads as a dead
        # flywheel when the real cause is a misresolved path. Say so instead of miscounting.
        return {"id": "flywheel", "label": "Retrieval flywheel", "status": WARN,
                    "detail": f"configured + reachable ({endpoint_detail}); coverage unknown — "
                           f"no triggers file at {TRIGGERS} (set SKILL_TRIGGERS)"
                           f"{_last_run_suffix()}", "fix": fix}
    try:
        triggers = json.loads(TRIGGERS.read_text(encoding="utf-8"))
        covered = {k for k, v in triggers.items()
                   if isinstance(v, dict) and (v.get("llm_triggers", {}) or {}).get("triggers")}
    except JSON_READ_ERRORS as exc:
        return {"id": "flywheel", "label": "Retrieval flywheel", "status": WARN,
                    "detail": f"configured + reachable ({endpoint_detail}); coverage unknown — "
                           f"unreadable triggers file {TRIGGERS}: {exc}{_last_run_suffix()}", "fix": fix}
    try:
        indexed = _indexed_skill_names()
    except NETWORK_READ_ERRORS:
        return {"id": "flywheel", "label": "Retrieval flywheel", "status": OK,
                    "detail": f"configured + reachable ({endpoint_detail}); "
                           "coverage unknown (index unreachable)", "fix": fix}

    have = indexed & covered
    missing = sorted(indexed - covered)
    n, m = len(have), len(indexed)
    detail = f"configured + reachable ({endpoint_detail}); {n}/{m} skills have utterances"
    if missing:
        examples = ", ".join(missing[:5])
        detail += f"; {len(missing)} missing (examples: {examples})"
    detail += _last_run_suffix()
    return {"id": "flywheel", "label": "Retrieval flywheel", "status": OK, "detail": detail, "fix": fix}


def _junk_triggers():
    """{skill: [bad phrase, ...]} for LIVE-indexed skills whose stored utterance layer
    contains phrases `clean_triggers()` would reject. Raises on an unreadable/absent
    triggers file or an unreachable index — callers decide the fail-open policy."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from llm_triggers import (
        clean_triggers,  # single definition of "junk" — do not restate it here
    )

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
        return {"id": "hygiene", "label": "Trigger hygiene", "status": OK,
                    "detail": f"no triggers file at {TRIGGERS} — utterance layer unused"}
    try:
        bad = _junk_triggers()
    except (ImportError, AttributeError, *NETWORK_READ_ERRORS) as exc:
        return {"id": "hygiene", "label": "Trigger hygiene", "status": OK,
                    "detail": f"not audited ({type(exc).__name__}: {exc})"}
    if not bad:
        return {"id": "hygiene", "label": "Trigger hygiene", "status": OK,
                    "detail": "no junk phrases stored in the utterance layer"}
    examples = ", ".join(f"{n} ({len(v)})" for n, v in sorted(bad.items())[:4])
    return {"id": "hygiene", "label": "Trigger hygiene", "status": WARN,
                "detail": f"{len(bad)} skills store junk utterances — a degraded model wrote them "
                       f"and the generator now skips them as 'covered' (examples: {examples})",
                "fix": "purge_junk"}


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
    except JSON_READ_ERRORS:
        cfg = None
    if not isinstance(cfg, dict):
        return {"id": "catalogs", "label": "External catalogs", "status": WARN,
                    "detail": f"{cfg_path} unreadable/malformed — catalogs silently OFF "
                           "(engine fails open to none)", "fix": None}
    roots = {a: (s if isinstance(s, dict) else {"path": s}) for a, s in cfg.items()
             if isinstance(a, str) and not a.startswith("_")}
    missing = [a for a, s in roots.items()
               if not s.get("path") or not Path(os.path.expanduser(str(s["path"]))).is_dir()]
    if missing:
        return {"id": "catalogs", "label": "External catalogs", "status": WARN,
                    "detail": f"root path missing for: {', '.join(sorted(missing))} — skills go "
                           "dark at next reindex; fix the path or `catalogs.py remove`", "fix": None}
    counts = {a: len(glob.glob(str(Path(os.path.expanduser(str(s['path']))) / '*' / 'SKILL.md')))
              for a, s in roots.items()}
    detail = ", ".join(f"{a}: {n} skills" for a, n in sorted(counts.items())) or "none configured"
    return {"id": "catalogs", "label": "External catalogs", "status": OK, "detail": detail, "fix": None}


def _descriptor_version(path):
    """The version a plugin descriptor declares, or None when unreadable/absent."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))["version"]
    except JSON_READ_ERRORS:
        return None


def _ver_tuple(s: str) -> tuple:
    """Dotted-integer version sort key ("0.33.10" > "0.33.9"); non-numeric parts fold to 0."""
    return tuple(int(x) if x.isdigit() else 0 for x in s.split("."))


# Harness rows whose installed copy must reach the switch-over release before the cutover.
# Command Code, DSH and Cline launch from the dev repo path, not a versioned cache — no row.
CUTOVER_HARNESSES = ("claude-code", "codex", "omp", "zcode")
CUTOVER = False     # set by --cutover


def apply_cutover(results, release=None):
    """--cutover: every Claude/Codex/OMP/ZCode row turns FAIL when either its installed
    version is below the switch-over release (the SSOT version this tree ships), or the
    harness IS installed but the version could not be determined (a None/empty `version`
    can't prove the copy is caught up, so it FAILs rather than silently passing). An
    old or unknown copy has no owner start path, and its setup.sh would restart Docker on
    the owner's ports.

    A harness that is simply not installed is left alone — there is no copy to hold back.
    That covers two distinct states, both skipped the same way: the harness itself is
    absent (check_claude_code/check_codex/check_omp/check_zcode key that row on the
    literal "not installed" phrase in `detail`), or the harness IS present but
    skill-concierge was never installed into it — no cache dir, no install record. The
    second state is read from each row's own `plugin_installed` flag (set by the check_*
    function at the exact point it determines there is no record/cache for skill-concierge
    at all), never sniffed from prose: a `version=None` row can also mean "installed but
    the version could not be resolved" (a corrupt cache), which must still FAIL."""
    release = release or _descriptor_version(ROOT / ".claude-plugin" / "plugin.json")
    if not release:
        return results
    for r in results:
        if (r.get("id") not in CUTOVER_HARNESSES or "not installed" in r.get("detail", "")
                or r.get("plugin_installed") is False):
            continue
        ver = r.get("version")
        if not ver:
            r["status"] = FAIL
            r["detail"] = ("CUTOVER: installed version unknown — cannot confirm it is at or "
                           f"above the switch-over release v{release}; " + r["detail"])
        elif _ver_tuple(ver) < _ver_tuple(release):
            r["status"] = FAIL
            r["detail"] = (f"CUTOVER: v{ver} is below the switch-over release v{release} — "
                           f"update this harness's plugin copy first; " + r["detail"])
    return results


def _registry_entry_state(path, plugin_key):
    """Reads a plugin-cache registry JSON file at `path` for `plugin_key`'s install
    entry and returns `(state, head)`:
      - `("missing", None)`    — `path` does not exist: no install has ever touched
                                  this registry. WARN as "never installed"; `--cutover`
                                  skips the row, same as always.
      - `("unreadable", None)` — `path` exists but does not parse, or its shape is not
                                  one a real registry ever writes (not a dict, `plugins`
                                  not a dict, entry not a dict/list-of-dicts): install
                                  state cannot be determined from it. Never collapse
                                  this into "missing" — `--cutover` must FAIL an unknown
                                  install state rather than silently skip it.
      - `("ok", head)`         — the file parses and the shape is sound; `head` is the
                                  plugin's own registry entry (a dict), or `None` when
                                  the registry is well-formed but has no entry for it.
    """
    if not path.exists():
        return "missing", None
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
        entry = rec["plugins"].get(plugin_key)
    except JSON_READ_ERRORS:
        return "unreadable", None
    if not entry:
        return "ok", None
    head = entry[0] if isinstance(entry, list) else entry
    if not isinstance(head, dict):
        return "unreadable", None
    return "ok", head


def _record_state(state, head):
    """"missing" | "unreadable" | "present" from `_registry_entry_state`'s result.
    Existence, not the parsed field, proves an install happened; an unreadable registry
    proves nothing either way, so it is reported and treated as installed-with-unknown-
    version rather than never-installed."""
    if state == "unreadable":
        return "unreadable"
    return "present" if isinstance(head, dict) else "missing"


def _omp_marketplace_version():
    """Version the OMP marketplace catalog clone advertises — what the next plugin
    update would fetch. None when the clone is missing/unreadable (updates blind)."""
    try:
        d = json.loads((OMP_MARKETPLACE / ".claude-plugin" / "marketplace.json")
                       .read_text(encoding="utf-8"))
        return d["plugins"][0].get("version")
    except JSON_READ_ERRORS:
        return None


def check_omp():
    """OMP marketplace install state — the 4th first-class harness (ADR-0040).

    OMP installs skill-concierge through its own marketplace plugin system, entirely
    outside the Claude/Codex/Command Code surfaces every other check covers: the
    install record lives in ~/.omp/plugins/installed_plugins.json, the catalog clone
    under cache/marketplaces/skill-concierge/, and the version-pinned plugin content
    under cache/plugins/skill-concierge___skill-concierge___<ver>/. None of it is
    required for the plugin to work in the other harnesses, so every absence or
    drift here is WARN — never FAIL — and an OMP-less machine is one 'omp: not
    installed' warn row, not a failed run (exit status unchanged).

    Three signals, weakest to strongest:
      1. install record — the version OMP believes it installed vs the plugin.json SSOT
         (a silent lag until the next /plugin marketplace update).
      2. marketplace clone — the version the catalog advertises; stale means the clone
         was not refreshed since the SSOT bump.
      3. cache surface — the version-pinned plugin dir plus adapters/omp/skill-concierge.ext.ts,
         the OMP extension surface added in 0.28.0; a pre-0.28.0 cache cannot have it.
    """
    if not OMP_DIR.exists():
        return {"id": "omp", "label": "OMP integration", "status": WARN,
                "detail": "omp: not installed (no ~/.omp) — optional harness, no action needed",
                "fix": None}
    findings = []
    ssot = _descriptor_version(ROOT / ".claude-plugin" / "plugin.json")
    # The record keys plugins by '<name>@<marketplace>' and stores a LIST (one entry per
    # install scope); `_registry_entry_state` tolerates both list and bare-dict shapes.
    state, head = _registry_entry_state(OMP_PLUGINS_FILE, "skill-concierge@skill-concierge")
    ver, enabled = (None, None) if head is None else (head.get("version"), head.get("enabled"))
    record_state = _record_state(state, head)
    # A missing registry proves no install ever happened (existing WARN-only, cutover-skips
    # behavior). An unreadable one proves nothing either way, so it is NOT collapsed into
    # "missing": install state is unknown, and --cutover must fail that, not skip it.
    plugin_installed = record_state != "missing"
    if record_state == "missing":
        findings.append("skill-concierge has no OMP install record (installed_plugins.json)")
    elif record_state == "unreadable":
        findings.append(f"OMP install record ({OMP_PLUGINS_FILE}) exists but could not be "
                        "read as JSON — install state unknown")
    else:
        if ver is None:
            findings.append("OMP install record has no version field")
        if enabled is False:
            findings.append(f"OMP plugin v{ver} installed but DISABLED")
        if ver and ssot and ver != ssot:
            findings.append(f"OMP cache v{ver} != SSOT v{ssot} — run /plugin marketplace update")
    mkt = _omp_marketplace_version()
    if mkt is None:
        findings.append("no OMP marketplace catalog clone (updates would be blind)")
    elif ssot and mkt != ssot:
        findings.append(f"marketplace catalog stale (v{mkt} vs SSOT v{ssot})")
    if ver:
        pinned = OMP_PLUGIN_CACHE / f"skill-concierge___skill-concierge___{ver}"
        if not pinned.is_dir():
            findings.append(f"install record points at {pinned} but the cache dir is missing")
        elif not (pinned / "adapters" / "omp" / "skill-concierge.ext.ts").exists():
            findings.append(f"OMP cache v{ver} predates the 0.28.0 OMP adapter — no "
                            "adapters/omp/skill-concierge.ext.ts; update the plugin")
    if findings:
        return {"id": "omp", "label": "OMP integration", "status": WARN,
                "detail": "; ".join(findings), "fix": None, "version": ver,
                "plugin_installed": plugin_installed}
    return {"id": "omp", "label": "OMP integration", "status": OK,
            "detail": f"OMP plugin v{ver} matches SSOT v{ssot}; marketplace + extension surface in sync",
            "fix": None, "version": ver, "plugin_installed": plugin_installed}

_VERSION_DIRNAME = re.compile(r"^\d+(\.\d+)*$")


def _codex_cached_version():
    """Version of the Codex-cached plugin clone under
    ~/.codex/plugins/cache/<name>/<name>/<ver>/, or None when absent/unreadable. Multiple
    version dirs can sit side by side there between installer runs (a manually-synced
    fallback dir is never pruned by this repo's own tooling, and the installer's own
    `.staging.*` / `*.replaced-*` dirs can sit there too; Codex keeps its own
    `plugin-install-<random>` staging one level up, and its `plugin add` was observed to
    wipe this whole directory on its next successful refresh) — `codex plugin list --json` resolves the semver-NEWEST one, so
    this filters to all-numeric dotted-version dir names and sorts by the dotted-integer
    tuple key `_ver_tuple` (same key `check_zcode()` uses), never lexically: a plain
    string sort ranks "0.9.0" above "0.52.3" ('9' > '5' at the first differing
    character)."""
    try:
        base = CODEX_PLUGIN_CACHE
        if not base.is_dir():
            return None
        candidates = sorted(
            (d for d in base.iterdir() if d.is_dir() and _VERSION_DIRNAME.match(d.name)),
            key=lambda d: _ver_tuple(d.name), reverse=True)
        if not candidates:
            return None
        # Each candidate e.g. "0.28.1" — read the plugin.json inside for confirmation
        for cand in candidates:
            pf = cand / ".codex-plugin" / "plugin.json"
            if pf.exists():
                return _descriptor_version(pf)
        return None
    except (OSError, PermissionError):
        return None


def _codex_cache_has_version_dir():
    """True when at least one version-named dir sits in the Codex plugin cache, regardless
    of whether its plugin.json is present or readable. Existence of the install, not a
    successfully parsed version, is what `--cutover` must key its FAIL rule on."""
    try:
        base = CODEX_PLUGIN_CACHE
        if not base.is_dir():
            return False
        return any(d.is_dir() and _VERSION_DIRNAME.match(d.name) for d in base.iterdir())
    except (OSError, PermissionError):
        return False


def check_codex():
    """Codex harness install state — version parity and surface presence (ADR-0033).

    Codex installs skill-concierge through its own plugin marketplace system. The
    cached clone lives under ~/.codex/plugins/cache/skill-concierge/skill-concierge/<ver>/;
    `_codex_cached_version()` resolves the semver-NEWEST version dir there. Unlike OMP,
    Codex has no user-level install-record file — enablement is in config.toml (TOML, not
    stdlib-parseable on 3.10). Version is read from the cached .codex-plugin/plugin.json
    and compared to the SSOT in the source repo. Every check is WARN-only — no Codex
    install is one 'codex: not installed' row, never a failure.

    Two signals:
      1. install presence — cached plugin dir with .codex-plugin/plugin.json
      2. version parity — cached version vs SSOT; a stale cache gets a WARN row
    """
    if not CODEX_DIR.exists():
        return {"id": "codex", "label": "Codex integration", "status": WARN,
                "detail": "codex: not installed (no ~/.codex) — optional harness, no action needed",
                "fix": None}
    findings = []
    ssot = _descriptor_version(ROOT / ".codex-plugin" / "plugin.json")
    cached_ver = _codex_cached_version()
    plugin_installed = _codex_cache_has_version_dir()
    if cached_ver is None:
        if plugin_installed:
            findings.append("Codex plugin cache has a version dir but its plugin.json is "
                            "missing or unreadable — run adapters/codex/install.sh")
        else:
            findings.append("no Codex plugin cache found (never installed via marketplace)")
    else:
        if ssot and cached_ver != ssot:
            findings.append(f"Codex cache v{cached_ver} != SSOT v{ssot} — "
                            "run adapters/codex/install.sh")
    # Surface: verify skills dir exists in the cached version
    if cached_ver:
        skills_dir = CODEX_PLUGIN_CACHE / cached_ver / "skills"
        if not skills_dir.is_dir():
            findings.append(f"Codex cache v{cached_ver} missing skills/ dir — incomplete install")
        # Codex starts ./bin/skill-search-mcp itself (no interpreter in its mcp.json), so the
        # launcher and its exec bit are load-bearing, as is the MCP descriptor.
        launcher = CODEX_PLUGIN_CACHE / cached_ver / "bin" / "skill-search-mcp"
        if not (launcher.is_file() and os.access(launcher, os.X_OK)):
            findings.append(f"Codex cache v{cached_ver} launcher bin/skill-search-mcp missing or not "
                            "executable — run adapters/codex/install.sh")
        # The installer's verify requires the same two descriptors Codex reads from the tree.
        for rel in (".codex-plugin/mcp.json", ".codex/hooks.json"):
            if not (CODEX_PLUGIN_CACHE / cached_ver / rel).is_file():
                findings.append(f"Codex cache v{cached_ver} missing {rel} — incomplete install; "
                                "run adapters/codex/install.sh")
    if findings:
        return {"id": "codex", "label": "Codex integration", "status": WARN,
                "detail": "; ".join(findings), "fix": None, "version": cached_ver,
                "plugin_installed": plugin_installed}
    return {"id": "codex", "label": "Codex integration", "status": OK,
            "detail": f"Codex cache v{cached_ver} matches SSOT v{ssot}; skills, launcher, MCP "
                      "descriptor and hooks present",
            "fix": None, "version": cached_ver, "plugin_installed": plugin_installed}

def check_commandcode():
    """Command Code harness install state — mod + settings + MCP surface (ADR-0038).

    Command Code integrates skill-concierge through a TypeScript mod, SessionStart hooks,
    and an MCP server entry — all installed by adapters/commandcode/install.sh into
    ~/.commandcode/. There is no version manifest or plugin cache; the installed mod
    references the dev path (or $SKILL_CONCIERGE_ROOT) directly. Three presence signals:
      1. mod file at ~/.commandcode/mods/skill-concierge.ts
      2. SessionStart hooks in ~/.commandcode/settings.json referencing skill-concierge
      3. MCP skill-search entry in ~/.commandcode/mcp.json
    WARN-only — absent Command Code is one row, never a failure.
    """
    if not CCMD_DIR.exists():
        return {"id": "commandcode", "label": "Command Code integration", "status": WARN,
                "detail": "commandcode: not installed (no ~/.commandcode) — optional harness, no action needed",
                "fix": None}
    findings = []
    # 1. Mod presence
    if not CCMD_MOD.exists():
        findings.append("no skill-concierge mod at ~/.commandcode/mods/skill-concierge.ts")
    else:
        # The installer COPIES the mod, so a repo change (e.g. the 0.49.0 exclusion echo) never
        # reaches Command Code until install.sh reruns — a stale copy is silent otherwise.
        src = ROOT / "adapters" / "commandcode" / "skill-concierge.mod.ts"
        try:
            if src.exists() and CCMD_MOD.read_bytes() != src.read_bytes():
                findings.append("installed mod differs from adapters/commandcode/skill-concierge.mod.ts "
                                "(a stale copy) — re-run adapters/commandcode/install.sh")
        except OSError:
            pass
    # 2. SessionStart hooks referencing skill-concierge: our marker string inside a hook command
    settings = None
    hook_found = False
    try:
        settings = json.loads(CCMD_SETTINGS.read_text(encoding="utf-8"))
        for hooks_list in settings.get("hooks", {}).values():
            for block in hooks_list:
                for h in block.get("hooks", []):
                    cmd = h.get("command", "")
                    if _CCMD_SETTINGS_HOOK_MARKER in cmd:
                        hook_found = True
                        break
                if hook_found:
                    break
    except JSON_READ_ERRORS:
        findings.append(f"unreadable settings.json at {CCMD_SETTINGS}")
    if not hook_found:
        findings.append("no skill-concierge hooks found in Command Code settings.json")
    # 3. MCP skill-search entry
    mcp_found = False
    try:
        mcp = json.loads(CCMD_MCP.read_text(encoding="utf-8"))
        for name in mcp.get("mcpServers", {}):
            if "skill" in name:
                mcp_found = True
                break
    except JSON_READ_ERRORS:
        findings.append(f"unreadable mcp.json at {CCMD_MCP}")
    if not mcp_found:
        findings.append("no skill-search MCP entry in Command Code mcp.json")
    # 4. Hook events outside CC's supported four. Claude's set (which adds UserPromptSubmit
    #    and PreCompact) copied verbatim here is skipped as "unknown event" — a silent no-op.
    #    An unreadable settings.json was already reported above.
    hooks = settings.get("hooks", {}) if isinstance(settings, dict) else None
    if isinstance(hooks, dict):
        unknown = sorted(set(hooks) - CCMD_HOOK_EVENTS)
        if unknown:
            findings.append(
                "settings.json has hook event(s) Command Code does not support: "
                + ", ".join(f'"{e}"' for e in unknown)
                + " — it accepts only PreToolUse, PostToolUse, Stop, SessionStart")
    # 5. Stray root-level SKILL.md — a FILE at the root of a Command Code skills dir.
    #    It carries a name that cannot match the directory, and CC responds by discarding
    #    the whole root: every skill under it disappears from `commandcode skills list`.
    for root in CCMD_SKILLS_ROOTS:
        stray = root / "SKILL.md"
        try:
            if stray.is_file():
                findings.append(
                    f"stray {stray} (a FILE at the root of a Command Code skills root) — "
                    "Command Code discards every skill in that root; move it out of the "
                    "skills dir, e.g. to ~/.claude/_quarantine/")
        except OSError:
            continue
    if findings:
        return {"id": "commandcode", "label": "Command Code integration", "status": WARN,
                "detail": "; ".join(findings), "fix": None}
    return {"id": "commandcode", "label": "Command Code integration", "status": OK,
            "detail": "Mod + SessionStart hooks + skill-search MCP all present",
            "fix": None}


def _zcode_record():
    """skill-concierge@skill-concierge's entry in ZCode's own install registry
    (~/.zcode/cli/plugins/installed_plugins.json), or None when there is no record or the
    registry is unreadable. Existence, not the resolved version, proves an install happened.
    Unlike Codex — proven live to always load the semver-newest cache dir regardless of any
    registry — ZCode's registry is the one signal that names which cache copy is actually
    active (`installPath`), so it is preferred over the newest-by-name heuristic."""
    try:
        data = json.loads(ZCODE_PLUGINS_FILE.read_text(encoding="utf-8"))
    except JSON_READ_ERRORS:
        return None
    return next((p for p in data.get("plugins", [])
                 if isinstance(p, dict) and p.get("id") == "skill-concierge@skill-concierge"), None)


def _zcode_installed_path():
    """installPath of the ZCode install record, or None."""
    return (_zcode_record() or {}).get("installPath") or None


def check_zcode():
    """ZCode harness install state — cache presence, version parity, exec bits (ADR-0042).

    ZCode installs skill-concierge through its plugin marketplace (it natively reads
    `.claude-plugin/` manifests, fires the plugin hooks/hooks.json, and auto-connects
    the plugin `.mcp.json` — the first harness in the set needing NO adapter vehicle).
    The cached copy lives under ~/.zcode/cli/plugins/cache/skill-concierge/skill-concierge/<ver>/.
    Two signals beyond codex's, both born from the live 2026-08-28 validation:
      1. version parity — cached vs SSOT; a stale cache WARNs (it also can no longer
         downgrade the shared venv — the launcher's one-directional guard — but its
         hooks/enforcer/doctrine still run the old behavior, so staleness stays loud);
      2. exec bits — ZCode's cache copy has been observed shipping bin/ without +x
         (the exact cause of a dead MCP). The .mcp.json interpreter form makes the bit
         cosmetic, but the row keeps the regression visible.
    WARN-only — no ZCode install is one 'zcode: not installed' row, never a failure.

    Version resolution: ZCode's own install registry names which cache copy is
    active (`installPath`) — read that copy's OWN .claude-plugin/plugin.json first, since
    trusting "newest dir by name" could report a version ZCode isn't actually running (a
    manually-dropped or half-synced newer dir would outrank the active one). Fall back to
    the newest-cache-dir heuristic only when the registry has no usable record — the
    earlier newest-by-name behavior, kept as a safety net rather than reporting nothing.
    """
    if not ZCODE_DIR.exists():
        return {"id": "zcode", "label": "ZCode integration", "status": WARN,
                "detail": "zcode: not installed (no ~/.zcode) — optional harness, no action needed",
                "fix": None}
    findings = []
    ssot = _descriptor_version(ROOT / ".claude-plugin" / "plugin.json")
    record = _zcode_record()
    record_present = record is not None
    install_path = (record or {}).get("installPath") or None
    cached_ver = None
    if install_path:
        cached_ver = _descriptor_version(Path(install_path) / ".claude-plugin" / "plugin.json")
    if not record_present and cached_ver is None:
        # No registry entry at all — fall back to the newest-cache-dir heuristic (the
        # earlier safety net) rather than reporting nothing. Never used when a registry
        # record IS present: a record with an unreadable manifest must stay version=None,
        # not silently resolve to whichever dir happens to sort newest by name.
        try:
            if ZCODE_PLUGIN_CACHE.is_dir():
                versions = sorted((d for d in ZCODE_PLUGIN_CACHE.iterdir() if d.is_dir()),
                                  key=lambda d: _ver_tuple(d.name), reverse=True)
                if versions:
                    cached_ver = versions[0].name
        except (OSError, ValueError):
            pass
    plugin_installed = record_present or cached_ver is not None
    if not plugin_installed:
        findings.append("no ZCode plugin cache found (never installed via the skill-concierge marketplace)")
    else:
        if record_present and cached_ver is None:
            findings.append(
                f"the ZCode registry points at {install_path or 'an install record with no installPath'} "
                "whose plugin manifest is unreadable or missing — re-run adapters/zcode/install.sh")
        elif cached_ver and ssot and cached_ver != ssot:
            findings.append(f"ZCode cache v{cached_ver} != SSOT v{ssot} — update via "
                            "Settings → Plugin Management (skill-concierge marketplace)")
        # Anchor the launcher check on the registry's OWN installPath when we have one — the
        # copy ZCode actually runs — rather than reconstructing a path from cached_ver, which
        # could point at a differently-named dir if the two ever disagree.
        active_dir = Path(install_path) if install_path else (
            ZCODE_PLUGIN_CACHE / cached_ver if cached_ver else None)
        if active_dir is not None:
            launcher = active_dir / "bin" / "skill-search-mcp"
            if not launcher.is_file():
                findings.append(
                    f"bin/skill-search-mcp missing from the ZCode cache v{cached_ver or '?'} — "
                    "the MCP server cannot start; re-run adapters/zcode/install.sh")
            elif not os.access(launcher, os.X_OK):
                findings.append(
                    f"bin/skill-search-mcp in the ZCode cache v{cached_ver or '?'} lost its exec bit "
                    "(cosmetic under the interpreter-form .mcp.json; repair: chmod +x)")
    if findings:
        return {"id": "zcode", "label": "ZCode integration", "status": WARN,
                "detail": "; ".join(findings), "fix": None, "version": cached_ver,
                "plugin_installed": plugin_installed}
    return {"id": "zcode", "label": "ZCode integration", "status": OK,
            "detail": f"ZCode cache v{cached_ver} matches SSOT v{ssot}; launcher executable",
            "fix": None, "version": cached_ver, "plugin_installed": plugin_installed}


def check_claude_code():
    """Claude Code harness install state — install record vs deployed content vs SSOT.

    Claude Code is the reference harness: skill-concierge is installed once via
    `claude plugin marketplace add` + `claude plugin install`, then kept current by
    adapters/claude-code/install.sh (a `claude plugin update` CLI refresh, falling back
    to a local git-archive sync when the marketplace remote hasn't caught up to this
    checkout yet). Two signals:
      1. deployed content — the installed path's OWN .claude-plugin/plugin.json version vs
         the SSOT; "content decides, not the record" — a hand-repointed registry entry could
         lie. An unreadable manifest (or no installPath) is a finding, and the row's
         `version` is then None: the registry's value is a claim, not what is deployed.
      2. launcher — bin/skill-search-mcp under the installed path, present and executable.
    WARN-only — a plugin-free dev checkout is one 'not installed' row, never a failure.
    """
    if not CLAUDE_PLUGINS_DIR.exists():
        return {"id": "claude-code", "label": "Claude Code integration", "status": WARN,
                "detail": "claude-code: not installed (no ~/.claude/plugins) — optional "
                          "harness, no action needed",
                "fix": None, "version": None}
    findings = []
    ssot = _descriptor_version(ROOT / ".claude-plugin" / "plugin.json")
    # Same map-of-lists shape as OMP's (one entry per install scope); the head entry is the
    # active scope.
    state, head = _registry_entry_state(CLAUDE_PLUGINS_FILE, "skill-concierge@skill-concierge")
    installed_ver, install_path = ((None, None) if head is None
                                   else (head.get("version"), head.get("installPath")))
    record_state = _record_state(state, head)
    deployed_ver = None
    # A missing registry proves no install ever happened (existing WARN-only, cutover-skips
    # behavior). An unreadable one proves nothing either way, so it is NOT collapsed into
    # "missing": install state is unknown, and --cutover must fail that, not skip it.
    plugin_installed = record_state != "missing"
    if record_state == "missing":
        findings.append("skill-concierge has no Claude Code install record (installed_plugins.json)")
    elif record_state == "unreadable":
        findings.append(f"Claude Code install record ({CLAUDE_PLUGINS_FILE}) exists but could "
                        "not be read as JSON — install state unknown")
    else:
        if installed_ver is None:
            findings.append("Claude Code install record has no version field")
        if install_path:
            deployed_ver = _descriptor_version(Path(install_path) / ".claude-plugin" / "plugin.json")
        if deployed_ver is None:
            where = install_path or "no installPath in the install record"
            shown = f"v{installed_ver}" if installed_ver else "no version"
            findings.append(f"the Claude Code cache manifest is unreadable ({where}); the record says "
                            f"{shown} — re-run adapters/claude-code/install.sh")
        elif ssot and deployed_ver != ssot:
            findings.append(f"Claude Code plugin v{deployed_ver} != SSOT v{ssot} — "
                            "re-run adapters/claude-code/install.sh")
        if install_path:
            launcher = Path(install_path) / "bin" / "skill-search-mcp"
            shown = deployed_ver or installed_ver or "?"
            if not launcher.is_file():
                findings.append(f"bin/skill-search-mcp missing from the Claude Code cache v{shown} — "
                                "the MCP server cannot start; re-run adapters/claude-code/install.sh")
            elif not os.access(launcher, os.X_OK):
                findings.append(f"bin/skill-search-mcp in the Claude Code cache v{shown} "
                                "lost its exec bit — re-run adapters/claude-code/install.sh")
    # `version` is the deployed content's own version (what Claude Code will load), not the record's;
    # None when that content cannot be read.
    if findings:
        return {"id": "claude-code", "label": "Claude Code integration", "status": WARN,
                "detail": "; ".join(findings), "fix": None, "version": deployed_ver,
                "plugin_installed": plugin_installed}
    return {"id": "claude-code", "label": "Claude Code integration", "status": OK,
            "detail": f"Claude Code plugin v{deployed_ver} matches SSOT v{ssot}; launcher executable",
            "fix": None, "version": deployed_ver, "plugin_installed": plugin_installed}


_DSH_OWN_IDS = ("skill-concierge", "unlazy-stop", "skill-concierge-enforcer")


def _dsh_patch_defects(text: str) -> list:
    """Shapes of a cordis.patch.yml that DSH will not load, found without a YAML parser
    (doctor is stdlib-only). Both shipped in skill-concierge installs before 0.49.0:
    a bare `[]` line followed by list items is not YAML (DSH refuses the whole user
    layer and the profile does not boot), and a bare top-level `- id: <new id>` only
    overrides an existing entry — adding a plugin takes `- insert: [ {id, ...} ]`."""
    lines = text.splitlines()
    defects = []
    top_empty = any(ln[:1] not in (" ", "\t") and ln.split("#", 1)[0].strip() == "[]" for ln in lines)
    if top_empty and any(ln.startswith("- ") for ln in lines):   # column 0 only: an indented [] is a value
        defects.append("a bare `[]` line precedes list items (not YAML — DSH cannot load the profile)")
    bare = [i for i in _DSH_OWN_IDS if f"- id: {i}" in lines]
    if bare:
        defects.append("entries not wrapped in `- insert:` (DSH skips them as unknown ids): "
                       + ", ".join(bare))
    if not any(ln.strip() == "- id: skill-concierge-enforcer" for ln in lines):
        defects.append("the skill-concierge enforcement plugin is not wired (no `skill-concierge-enforcer` insert)")
    return defects


def check_dsh():
    """DSH (DeepSeek Harness) install state — Cordis patch presence, MCP server wiring (ADR-0050).

    DSH integrates skill-concierge through its Cordis composition system: the
    skill-search MCP server is registered in a cordis.patch.yml that the DSH
    runtime merges into the host profile. DSH has no marketplace plugin for
    skill-concierge, so the signals are:
      1. Profile presence — at least one DSH profile directory exists
      2. Cordis patch — the MCP server entry in cordis.patch.yml
      3. Launcher — the skill-search-mcp binary exists and is executable
    WARN-only — no DSH install is one 'dsh: not installed' row, never a failure.
    """
    if not DSH_DIR.exists():
        return {"id": "dsh", "label": "DSH integration", "status": WARN,
                "detail": "dsh: not installed (no DSH_HOME) — optional harness, no action needed",
                "fix": None}
    findings = []
    # 1. Profile presence
    desktop_profile = DSH_DIR / "profiles" / "desktop"
    tui_profile = DSH_DIR / "profiles" / "tui"
    if not desktop_profile.exists() and not tui_profile.exists():
        findings.append("no DSH profile directories found (no profiles/desktop or profiles/tui)")
    # 2. Cordis patch with skill-search entry
    for label, patch_file in [("desktop", DSH_PATCH), ("tui", DSH_TUI_PATCH)]:
        if patch_file.exists():
            try:
                text = patch_file.read_text(encoding="utf-8")
                if "skill-search" in text and "skill-concierge" in text:
                    findings += [f"{label} cordis.patch.yml: {d} — re-run adapters/dsh/install.sh"
                                 for d in _dsh_patch_defects(text)]
                else:
                    findings.append(f"{label} cordis.patch.yml missing skill-search entry")
            except (OSError, UnicodeError):
                findings.append(f"{label} cordis.patch.yml unreadable")
    # 3. Launcher
    launcher = ROOT / "bin" / "skill-search-mcp"
    if not launcher.exists():
        findings.append("skill-search-mcp launcher missing from the repo bin/")
    elif not os.access(launcher, os.X_OK):
        findings.append("skill-search-mcp launcher not executable")
    # 4. Enforcer present
    enforcer = ROOT / "hooks" / "scripts" / "enforcer.py"
    if not enforcer.exists():
        findings.append("enforcer.py missing from the repo hooks/scripts/")
    if findings:
        return {"id": "dsh", "label": "DSH integration", "status": WARN,
                "detail": "; ".join(findings), "fix": None}
    return {"id": "dsh", "label": "DSH integration", "status": OK,
            "detail": "DSH profile + cordis.patch.yml + MCP launcher + enforcer all present",
            "fix": None}


# Cline surface (ADR-0086): a one-line loader in ~/.cline/plugins/skill-concierge.ts
# re-exports this checkout's code plugin, and ~/.agents/plugins/skill-concierge is the
# Agent Plugin adapters/cline/agent_plugin.py builds (plugin.json + mcp.json + skills/).
# Leftovers of the removed file-hook vehicle (ADR-0051: marked shims in ~/.cline/hooks/, a
# skill-search row in cline_mcp_settings.json) would govern a turn twice; install.sh retires them.
# WARN-only — no Cline install is one 'cline: not installed' row, never a failure.
CLINE_DIR = Path.home() / ".cline"
CLINE_HOOKS = CLINE_DIR / "hooks"
CLINE_MCP_SETTINGS = CLINE_DIR / "data" / "settings" / "cline_mcp_settings.json"
CLINE_LOADER = CLINE_DIR / "plugins" / "skill-concierge.ts"
CLINE_AGENT_DIR = Path.home() / ".agents" / "plugins" / "skill-concierge"
CLINE_OLD_SHIMS = ("UserPromptSubmit.cjs", "PostToolUse.cjs", "TaskStart.cjs", "PreToolUse.cjs")


def _cline_leftovers():
    """What the removed file-hook installer left behind: its marked shims and its MCP row."""
    left = []
    for shim in CLINE_OLD_SHIMS:
        try:
            if "GENERATED by adapters/cline/install.sh" in (CLINE_HOOKS / shim).read_text(encoding="utf-8"):
                left.append(f"old file-hook shim {shim}")
        except (OSError, UnicodeError):
            continue
    try:
        servers = json.loads(CLINE_MCP_SETTINGS.read_text(encoding="utf-8")).get("mcpServers")
        row = servers.get("skill-search") if isinstance(servers, dict) else None
        args = row.get("args") if isinstance(row, dict) else None
        if isinstance(args, list) and args and str(args[0]).endswith("/bin/skill-search-mcp"):
            left.append("old skill-search row in cline_mcp_settings.json")
    except (OSError, UnicodeError, ValueError, AttributeError):
        pass
    return left


def check_cline():
    """Cline install state — plugin loader + generated Agent Plugin (ADR-0086)."""
    if not CLINE_DIR.exists():
        return {"id": "cline", "label": "Cline integration", "status": WARN,
                "detail": "cline: not installed (no ~/.cline) — optional harness, no action needed",
                "fix": None}
    fix = f"bash {ROOT / 'adapters' / 'cline' / 'install.sh'}"
    leftovers = _cline_leftovers()
    try:
        loader = CLINE_LOADER.read_text(encoding="utf-8") if CLINE_LOADER.exists() else ""
    except (OSError, UnicodeError):
        loader = ""
    if not loader:
        detail = "Cline present but skill-concierge is not installed for it"
        if leftovers:
            detail += " (only leftovers of the removed file-hook vehicle: " + ", ".join(leftovers) + ")"
        return {"id": "cline", "label": "Cline integration", "status": WARN, "detail": detail, "fix": fix}
    findings = [f"{x} still installed (a turn is governed twice)" for x in leftovers]
    plugin_ts = (ROOT / "adapters" / "cline" / "skill-concierge.cline-plugin.ts").resolve()
    m = re.search(r'from\s+("(?:[^"\\]|\\.)*")', loader)
    try:
        named = json.loads(m.group(1)) if m else "?"    # the installer writes a JSON string
    except ValueError:
        named = "?"
    target = Path(named).resolve() if m else None
    if target != plugin_ts:
        findings.append(f"plugin loader points at {named}, not this checkout")
    elif not target.exists():
        findings.append("plugin loader target is missing")
    if not (CLINE_AGENT_DIR / "plugin.json").is_file():
        findings.append("Agent Plugin ~/.agents/plugins/skill-concierge missing")
    else:
        try:
            r = subprocess.run([sys.executable, str(ROOT / "adapters" / "cline" / "agent_plugin.py"),
                                "check", str(CLINE_AGENT_DIR)], capture_output=True, text=True, timeout=30)
            if r.returncode != 0:
                stale = r.stdout.split()
                findings.append(f"Agent Plugin out of date ({r.stdout.count('stale:')} file(s), "
                                f"e.g. {stale[1] if len(stale) > 1 else '?'}); "
                                "the next Cline session re-syncs it")
        except (OSError, subprocess.SubprocessError) as exc:
            findings.append(f"Agent Plugin check failed: {exc}")
    if os.environ.get("CLINE_SESSION_BACKEND_MODE", "").strip().lower() != "local":
        # ADR-0086: a session that attaches to a running Cline hub (the VS Code extension's
        # sidecar) is built with no plugins, so it runs ungoverned.
        findings.append("CLINE_SESSION_BACKEND_MODE is not 'local': a Cline CLI session that "
                        "attaches to a running hub (e.g. the VS Code extension) runs no plugin")
    if findings:
        return {"id": "cline", "label": "Cline integration", "status": WARN,
                "detail": "; ".join(findings), "fix": fix}
    return {"id": "cline", "label": "Cline integration", "status": OK,
            "detail": "plugin loader + Agent Plugin → this checkout", "fix": None}


# OpenCode v2 surface (ADR-0085) — skill-concierge integrates as a NATIVE OpenCode
# plugin: the package at adapters/opencode/plugin registered in the global
# ~/.config/opencode/opencode.json `plugins` array (the plugin itself registers the
# skill-search MCP server via ctx.mcp.transform — nothing on disk to check for MCP),
# plus the re-rooted plugin skills under ~/.config/opencode/skills/. WARN-only — no
# OpenCode install is one 'opencode: not installed' row, never a failure.
OPENCODE_HOME = Path(os.environ.get(
    "SKILL_OPENCODE_HOME",
    Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "opencode"))
OPENCODE_JSON = OPENCODE_HOME / "opencode.json"
OPENCODE_SKILLS = OPENCODE_HOME / "skills"


def check_opencode():
    """OpenCode v2 install state — plugin entry, plugin package, re-rooted skills (ADR-0085).

    WARN-only — no OpenCode install is one 'opencode: not installed' row, never a failure.
    """
    if not OPENCODE_HOME.exists():
        return {"id": "opencode", "label": "OpenCode integration", "status": WARN,
                "detail": "opencode: not installed (no ~/.config/opencode) — optional harness, no action needed",
                "fix": None}
    findings = []
    # 1. Plugin package in the repo
    for f in ("index.ts", "package.json"):
        if not (ROOT / "adapters" / "opencode" / "plugin" / f).exists():
            findings.append(f"plugin package incomplete (missing adapters/opencode/plugin/{f})")
    # 2. Global config carries the plugin entry
    try:
        cfg = json.loads(OPENCODE_JSON.read_text(encoding="utf-8"))
        entries = cfg.get("plugins", [])
        if not isinstance(entries, list):
            findings.append("opencode.json plugins is not a list")
        elif not any(isinstance(e, (str, dict)) and (
                e == str(ROOT / "adapters" / "opencode" / "plugin")
                or (isinstance(e, dict) and e.get("package") == str(ROOT / "adapters" / "opencode" / "plugin")))
                for e in entries):
            findings.append("opencode.json missing the skill-concierge plugin entry (run adapters/opencode/install.sh)")
    except FileNotFoundError:
        findings.append("opencode.json missing (no global config yet — run adapters/opencode/install.sh)")
    except (OSError, UnicodeError, ValueError):
        findings.append("opencode.json unreadable/invalid JSON (JSONC comments must be removed)")
    # 3. Re-rooted plugin skills (the opencode-personal discovery root)
    if not OPENCODE_SKILLS.is_dir():
        findings.append("skills root missing (~/.config/opencode/skills — run adapters/opencode/install.sh)")
    if findings:
        return {"id": "opencode", "label": "OpenCode integration", "status": WARN,
                "detail": "; ".join(findings), "fix": None}
    return {"id": "opencode", "label": "OpenCode integration", "status": OK,
            "detail": "plugin package + opencode.json entry + skills root all present",
            "fix": None}


KEEPOFF_DURABLE = Path(os.environ.get(
    "SKILL_CONCIERGE_KEEPOFF", Path.home() / ".claude" / "skill-concierge" / "keep-off.json"))


def check_keepoff():
    """ADR-0011 offer-suppression map, consent-only since ADR-0077. Doctor only READS it: no
    fixer builds or refreshes it. A map hides skills only when it carries `approved_by_user:
    true` (saved by `build_keep_off.py --apply` after Thinh's yes); any other map hides nothing."""
    path = KEEPOFF_DURABLE
    how = "propose with scripts/build_keep_off.py; save with --apply only after Thinh approves"
    if not path.exists():
        return {"id": "keepoff", "label": "Keep-off", "status": OK,
                "detail": f"no approved map — nothing hidden ({how})", "fix": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except JSON_READ_ERRORS:
        return {"id": "keepoff", "label": "Keep-off", "status": WARN,
                "detail": f"{path} invalid JSON — enforcer fails open, nothing hidden", "fix": None}
    names = data.get("keep_off") if isinstance(data, dict) else None
    if not isinstance(names, list):
        return {"id": "keepoff", "label": "Keep-off", "status": WARN,
                "detail": f"{path} has no \"keep_off\" list — nothing hidden", "fix": None}
    if data.get("approved_by_user") is not True:
        return {"id": "keepoff", "label": "Keep-off", "status": OK,
                "detail": f"{path} is not approved by Thinh — it hides nothing ({len(names)} names "
                          f"ignored, generated {data.get('generated_at', '?')}; {how})", "fix": None}
    return {"id": "keepoff", "label": "Keep-off", "status": OK,
            "detail": f"{len(names)} skill(s) hidden from the menu by Thinh's approved map "
                      f"(window {data.get('window', '?')}, saved {data.get('generated_at', '?')}) — {path}",
            "fix": None}


def check_findability():
    """ADR-0074 findability ratchet (v0.55.0). Doctor only READS the JSON the detached,
    throttled `python -m skill_search.findability --sweep` writes after an index-changing
    reindex — this check never sweeps, never talks to the owner, and never spends an
    embed/LLM call. An absent file is the healthy "nothing has changed the index yet, or
    the plugin was just installed" state, not a defect."""
    path = Path(os.environ.get(
        "SKILL_FINDABILITY_PATH", Path.home() / ".claude" / "skill-concierge" / "findability.json"))
    if not path.exists():
        return {"id": "findability", "label": "Findability", "status": OK,
                "detail": "not yet swept (runs after the next index-changing reindex)",
                "fix": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except JSON_READ_ERRORS:
        return {"id": "findability", "label": "Findability", "status": WARN,
                "detail": f"{path} unreadable/malformed — re-swept on the next "
                          "index-changing reindex", "fix": None}
    if not isinstance(data, dict):
        return {"id": "findability", "label": "Findability", "status": WARN,
                "detail": f"{path} has an unexpected shape — re-swept on the next reindex",
                "fix": None}
    swept_at, backlog, warnings = data.get("swept_at"), data.get("backlog"), data.get("warnings")
    if (not isinstance(swept_at, (int, float)) or isinstance(swept_at, bool)
            or not isinstance(backlog, int) or isinstance(backlog, bool)
            or not isinstance(warnings, list)):
        return {"id": "findability", "label": "Findability", "status": WARN,
                "detail": f"{path} has an unexpected shape — re-swept on the next reindex",
                "fix": None}
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(swept_at))
    if warnings:
        shown = "; ".join(str(w) for w in warnings[:5])
        more = f" (+{len(warnings) - 5} more)" if len(warnings) > 5 else ""
        return {"id": "findability", "label": "Findability", "status": WARN,
                "detail": f"{len(warnings)} warning(s): {shown}{more} — backlog {backlog}, "
                          f"swept {when}", "fix": None}
    return {"id": "findability", "label": "Findability", "status": OK,
            "detail": f"backlog {backlog} skill(s) not top-3 for their own name word, "
                      f"swept {when}", "fix": None}


CHECKS = [check_python, check_venv, check_engine_freshness, check_running_engine,
          check_mcp_wiring, check_owner, check_owner_ports, check_owner_log, check_embed_parity,
          check_engine_health, check_multivector, check_prompt_intent,
          check_corpus_health, check_flywheel, check_trigger_hygiene, check_overrides,
          check_blocklist, check_keepoff, check_findability,
          check_catalogs, check_omp, check_codex, check_commandcode, check_zcode,
          check_claude_code, check_dsh, check_cline, check_opencode,
          check_ledger, check_dup_mcp, check_mcp_enabled]


# ---------- auto-fixers: return (ok, message). Only the safe/fast ones. ----------

def fix_owner_start():
    ok, msg = start_owner()
    if not ok:
        return ok, msg
    if _wait_owner():
        return True, msg + " (ready)"
    return True, msg + " (still loading — re-run doctor shortly)"


def fix_containers():
    """Stop and disable a revived skill-concierge container on an owner port, then start the
    owner. Only the two containers this plugin ever ran are touched; anything else holding
    the port is reported for a human to stop.

    Latched on the owner's SQLite file: before the cutover moves the staged index into place
    there is nothing for an owner to serve, so stopping Qdrant would only take search down."""
    if not INDEX_DB.exists():
        return False, (f"no owner index at {INDEX_DB} — the cutover has not run; "
                       "leaving the containers alone")
    docker = shutil.which("docker")
    pubs = _publishing_containers() or []
    ours = [n for n, _ in pubs if n in (QNAME, ENAME)]
    if not docker or not ours:
        return fix_owner_start()
    for name in ours:
        r = _run([docker, "update", "--restart=no", name])
        if r.returncode != 0:
            return False, f"docker update --restart=no {name} failed: {r.stderr.strip()}"
        r = _run([docker, "stop", name])
        if r.returncode != 0:
            return False, f"docker stop {name} failed: {r.stderr.strip()}"
    ok, msg = fix_owner_start()
    return ok, f"stopped + disabled {', '.join(ours)}; {msg}"


def fix_reindex():
    if not SS_BIN.exists():
        return False, "venv missing — run ./setup.sh first"
    r = _run([str(SS_BIN), "--reindex"], env=_engine_env())
    if r.returncode != 0:
        return False, (r.stderr.strip() or "reindex failed")
    return True, _last_line(r.stdout) or "reindexed"


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
    except (ImportError, AttributeError, *NETWORK_READ_ERRORS) as exc:
        return False, f"could not audit triggers ({type(exc).__name__}: {exc})"
    if not bad:
        return True, "nothing to purge"

    import flywheel_lock
    if not flywheel_lock.acquire(block=False):
        return False, "flywheel running; retry later"
    backup = TRIGGERS.with_suffix(f".json.bak-junk-{int(time.time())}")
    try:
        shutil.copy2(TRIGGERS, backup)
        triggers = json.loads(TRIGGERS.read_text(encoding="utf-8"))
        # Drop the generation-cache keys FIRST: if the triggers save then fails, the junk stays and is
        # regenerated; the other order could leave a purged entry that the flywheel believes is current.
        cache = llm_triggers.load_cache()
        for name in bad:
            cache.pop(llm_triggers.CACHE_PREFIX + name, None)
        llm_triggers.save_cache(cache)
        for name in bad:
            entry = triggers.get(name) or {}
            prose = entry.get("prose_triggers") or []
            if prose:   # keep the hand/prose layer; only the LLM layer was poisoned
                triggers[name] = {"source": "prose-phrase", "triggers": prose, "n": len(prose)}
                jev = (entry.get("llm_triggers") or {}).get("jev")
                if isinstance(jev, dict) and jev:   # the Jev audit (dropped phrases, scores) outlives the purge
                    triggers[name]["llm_triggers"] = {"jev": jev}
            else:
                triggers.pop(name, None)
        llm_triggers.save_triggers(triggers, TRIGGERS)
    except (OSError, TypeError, ValueError, AttributeError) as exc:
        return False, f"purge failed ({type(exc).__name__}: {exc}); backup at {backup}"
    finally:
        flywheel_lock.release()

    msg = (f"purged {len(bad)} junk utterance layers (backup: {backup.name}); "
           f"the flywheel will regenerate them")
    if not SS_BIN.exists():
        return True, msg + " — reindex skipped (venv missing)"
    r = _run([str(SS_BIN), "--reindex"], env=_engine_env())
    return True, msg + ("; reindexed" if r.returncode == 0 else "; reindex FAILED — rerun doctor --fix")


AUTO_FIXERS = {"owner": fix_owner_start, "containers": fix_containers, "reindex": fix_reindex,
               "overrides": fix_overrides,
               "prompt_intent": fix_prompt_intent, "purge_junk": fix_purge_junk}   # ADR-0077: no fixer for the keep-off map — it is saved only with Thinh's consent


# ---------- run + report ----------

def run_all():
    # Invalidate the --health memo FIRST. It exists to stop two checks in one pass from
    # spawning the engine twice; it must not outlive the pass. `--fix` calls run_all() again
    # after repairing something, and a memo carried across that boundary would re-report the
    # very failure the fix just cleared — exiting 1 on a system doctor had already repaired.
    _reset_pass_caches()
    results = [c for c in (_run_check(fn) for fn in CHECKS) if c]
    return apply_cutover(results) if CUTOVER else results


def _run_check(fn):
    """One check that raises must not take the whole report down with it: the other rows
    still print, and the broken one becomes a FAIL row naming the exception — the same exit
    status an uncaught crash gave, without hiding every other check's answer."""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001 - any crash in a check is reported, never raised
        name = getattr(fn, "__name__", "check").removeprefix("check_")
        return {"id": name, "label": name.replace("_", " ").capitalize(), "status": FAIL,
                "detail": f"the check itself crashed: {type(e).__name__}: {e}", "fix": None}


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


def main():
    ap = argparse.ArgumentParser(description="skill-concierge deployment health check")
    ap.add_argument("--fix", action="store_true", help="attempt safe auto-fixes, then re-check")
    ap.add_argument("--cutover", action="store_true",
                    help="cutover precondition: harness-version rows FAIL below the switch-over release")
    ap.add_argument("--selftest", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.selftest:
        # chisle: docs and plans cite `--selftest`; its body lives in tests/ to stay out of the shipped script.
        body = ROOT / "tests" / "doctor_selftest.py"
        if not body.is_file():
            print(f"doctor --selftest: {body} not found (the self-test ships only with a repo checkout)",
                  file=sys.stderr)
            return 2
        exec(compile(body.read_text(encoding="utf-8"), str(body), "exec"), globals())
        return globals()["_selftest"]()  # defined by the exec above
    global CUTOVER
    CUTOVER = args.cutover

    print(f"skill-concierge doctor   (store={QURL}  venv={VENV}"
          f"{'  mode=cutover' if CUTOVER else ''})\n")
    results = run_all()
    report(results)

    if args.fix:
        todo = [r for r in results if r.get("fix") in AUTO_FIXERS and r["status"] in (FAIL, WARN)]
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
