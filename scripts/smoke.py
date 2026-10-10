#!/usr/bin/env python3
"""Live smoke: one real headless turn per harness through the installed concierge.

Doctor proves files and config exist; this proves the concierge runs. Each harness answers one
side-effect-free prompt in its own empty temp folder, with SKILL_CONCIERGE_LOG pointing at that
folder, so every ledger row there came from that run and nothing reaches the live ledger, badges or
auto-promotion. PASS needs both rows a working install writes:

  offer   the per-turn enforcer ran retrieval (band offer or jev_skip; the turn row alone is written
          by ledger.py, and an early-exit band never touches the index)
  search  the skill-search MCP tool reached the model and the post-tool hook logged it

A missing CLI is FAIL. ZCode has no command line, so it is UNPROVEN. Exit 1 on any FAIL or UNPROVEN
harness, unless that harness is advisory: --advisory (default: $SMOKE_ADVISORY), comma-separated. An
advisory harness still runs and still prints its FAIL or UNPROVEN row; it only stops blocking the run.
--accept-unproven is the older name and adds to the same list. Stdlib only. Usage:

  python3 scripts/smoke.py [--advisory codex,dsh,zcode] [harness ...]
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# No "do not" clauses: a prompt that refuses skills takes the enforcer's negation exit before any
# retrieval, and a broken index would still pass.
PROMPT = 'Call the search_skills tool once with the query "haiku about weather", then reply with only the name of the top result.'
# Offer-row bands that prove retrieval ran: a ranked menu, Jev judging the whole catalogue and finding
# no fit, or a skip decided after the embedding and index lookup (getaway: top hit under the floor;
# intent_skip: conversational turn). Every other band is an early exit before retrieval
# (negation, harness, self-reference, consult route) or an outage (fallback).
RETRIEVAL_BANDS = ("offer", "jev_skip", "getaway", "intent_skip")
# A row carrying one of these fallbacks was written while the embedder or the index was down.
OUTAGE_FALLBACKS = ("embed_timeout", "embed_down", "qdrant_down")
TIMEOUT = 300
KILL_GRACE = 5      # seconds between SIGTERM and SIGKILL for a child's process group
LEDGER_GRACE = 5    # seconds to wait for detached ledger writers after a CLI exits
STARTUP = 60        # seconds for opencode serve to listen and report skill-search connected
POLL = 2            # seconds between ledger checks while the opencode turn runs
POLL_START = 0.5    # seconds between startup probes of opencode serve
# Removed from every child's environment: a forced harness label would mislabel the run, the
# Claude Code session marker would make a nested claude think it runs inside this session, and the
# metered API key must never bill a smoke turn. Install settings (SKILL_CONCIERGE_ROOT, _VENV,
# _CATALOG_ROOTS …) stay: a harness needs them to run as it does day to day.
SCRUBBED_ENV = ("SKILL_CONCIERGE_HARNESS", "CLAUDECODE", "ANTHROPIC_API_KEY")
# (executable, argv before the prompt). The prompt is the last argument.
CLI = {
    "claude": ("claude", ["claude", "-p"]),
    "codex": ("codex", ["codex", "exec", "--skip-git-repo-check"]),
    "omp": ("omp", ["omp", "-p"]),
    "commandcode": ("cmd", ["cmd", "-p"]),
    "cline": ("cline", ["cline", "--json"]),
    "dsh": ("dsh", ["dsh", "headless"]),
}
HARNESSES = (*CLI, "opencode", "zcode")
HINTS = {"codex": "Codex skips a hook whose definition changed until it is trusted again: open Codex "
                  "and approve the skill-concierge hooks"}
OPENCODE_CMD = ["opencode"]
OPENCODE_PORT = int(os.environ.get("SMOKE_OPENCODE_PORT", "4473"))


def verdict(rows: list[dict], cli_found: bool = True) -> tuple[str, str]:
    """PASS when the run's ledger holds an offer row and a search row; else FAIL naming what is missing."""
    if not cli_found:
        return "FAIL", "command line not found on PATH"
    bands = [r.get("band") for r in rows if r.get("ev") == "offer"]
    missing = []
    if not bands:
        missing.append("no offer row: the per-turn enforcer did not run")
    elif any(r.get("fallback") in OUTAGE_FALLBACKS for r in rows if r.get("ev") == "offer"):
        missing.append("offer row records an outage: "
                       + ", ".join(sorted({r["fallback"] for r in rows if r.get("fallback") in OUTAGE_FALLBACKS})))
    elif not set(bands) & set(RETRIEVAL_BANDS):
        missing.append(f"offer band {bands[-1]}: the enforcer exited before retrieval")
    if not any(r.get("ev") == "search" for r in rows):
        missing.append("no search row: search_skills was not called, or its hook did not log it")
    return ("FAIL", "; ".join(missing)) if missing else ("PASS", "offer + search")


def _rows(logdir: Path) -> list[dict]:
    ledger = logdir / "skill-invocation-ledger.log"
    out = []
    for line in ledger.read_text(encoding="utf-8").splitlines() if ledger.exists() else []:
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


# The session-start self-heal scripts throttle on stamps in the log folder. An empty one would let
# all four run unthrottled against live state (a reindex, settings sync, LLM trigger generation,
# promotion), so each run's log folder starts with fresh stamps: they are not what this tests.
SELF_HEAL_STAMPS = (".auto-reindex-stamp", ".auto-overrides-stamp", ".auto-flywheel-stamp",
                    ".auto-promote-stamp")


def _workdir(harness: str) -> Path:
    work = Path(tempfile.mkdtemp(prefix=f"sc-smoke-{harness}-")).resolve()
    (work / "logs").mkdir()
    for stamp in SELF_HEAL_STAMPS:
        (work / "logs" / stamp).write_text(str(int(time.time())))
    return work


def _child_env(work: Path, **extra: str) -> dict:
    """The parent environment minus SCRUBBED_ENV, with this run's own log folder."""
    env = {k: v for k, v in os.environ.items() if k not in SCRUBBED_ENV}
    env["SKILL_CONCIERGE_LOG"] = str(work / "logs")
    env.update(extra)
    return env


def _stop_group(p: subprocess.Popen) -> None:
    """Stop the child's whole process group (started with start_new_session, so the group id is its
    pid): SIGTERM, a grace period, then SIGKILL for whatever is left."""
    def alive() -> bool:
        p.poll()   # reap the leader, or its zombie keeps the group listed
        try:
            os.killpg(p.pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    try:
        os.killpg(p.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    deadline = time.time() + KILL_GRACE
    while alive() and time.time() < deadline:
        time.sleep(0.05)
    if alive():
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        p.wait(timeout=KILL_GRACE)
    except subprocess.TimeoutExpired:
        pass


def _exit_on_signal(signum, _frame):
    raise SystemExit(128 + signum)   # unwinds through the finally blocks that stop the children


def _run_cli(harness: str, work: Path) -> str:
    argv = CLI[harness][1] + [PROMPT]
    out = work / "output.txt"
    p = None
    try:
        with open(out, "wb") as sink:
            p = subprocess.Popen(argv, cwd=work, env=_child_env(work), stdin=subprocess.DEVNULL,
                                 stdout=sink, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                rc = p.wait(timeout=TIMEOUT)
            except subprocess.TimeoutExpired:
                return f"timed out after {TIMEOUT} s; output in output.txt"
        tail = out.read_text(encoding="utf-8", errors="replace").strip().splitlines()
        return f"exit {rc}: {tail[-1][:300] if tail else ''}; output in output.txt"
    except OSError as e:
        return f"could not run {argv[0]}: {e}"
    finally:
        if p is not None:
            _stop_group(p)


def _describe(e: BaseException) -> str:
    if isinstance(e, urllib.error.HTTPError):
        return f"HTTP {e.code} from {urllib.parse.urlparse(e.url).path}"
    return f"{type(e).__name__}: {e}"


def _pending_summary(pending: list) -> str:
    parts = []
    for r in pending:
        if isinstance(r, dict) and ("action" in r or "resources" in r):
            parts.append(f"{r.get('action')} on {json.dumps(r.get('resources'))}")
        else:
            parts.append(json.dumps(r)[:200])
    return "; ".join(parts)[:400]


def _run_opencode(work: Path) -> str:
    """A private `opencode serve`, started fresh so it loads the plugin just installed, driven over
    its HTTP API (`opencode run --server` can stall before creating a session). The prompt waits
    until skill-search reports connected for the folder: a fresh server connects its MCP servers
    after the session exists, and a model call made first gets no search_skills tool. Nothing is
    ever approved: a permission request still pending at the timeout is named in the failure."""
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", OPENCODE_PORT)) == 0:
            return f"port {OPENCODE_PORT} is busy (set SMOKE_OPENCODE_PORT)"
    pw = secrets.token_hex(16)
    env = _child_env(work, OPENCODE_SERVER_PASSWORD=pw)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    auth = "Basic " + base64.b64encode(f"opencode:{pw}".encode()).decode()

    def call(method: str, path: str, body=None):
        req = urllib.request.Request(f"http://127.0.0.1:{OPENCODE_PORT}{path}", method=method,
                                     data=None if body is None else json.dumps(body).encode())
        req.add_header("Authorization", auth)
        req.add_header("Content-Type", "application/json")
        req.add_header("x-opencode-directory", str(work))
        with opener.open(req, timeout=TIMEOUT) as resp:
            raw = resp.read()
        data = json.loads(raw) if raw else None
        return data.get("data", data) if isinstance(data, dict) else data

    def exited(server: subprocess.Popen) -> str | None:
        rc = server.poll()
        return None if rc is None else f"opencode serve exited {rc}"

    server = None
    thread = None
    prompt_errors: list[BaseException] = []
    try:
        server = subprocess.Popen([*OPENCODE_CMD, "serve", "--port", str(OPENCODE_PORT), "--hostname", "127.0.0.1"],
                                  cwd=work, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  start_new_session=True)
        deadline = time.time() + STARTUP
        while True:
            if gone := exited(server):
                return gone
            try:
                call("GET", "/api/mcp")
                break
            except urllib.error.HTTPError:
                raise   # the server is up and refused the request: not a startup wait
            except OSError:
                pass    # connection refused: not listening yet
            if time.time() >= deadline:
                return "server did not start"
            time.sleep(POLL_START)
        # Asking for the folder's MCP status starts its servers; the session is created after
        # skill-search is connected, so its first model call already has the tool.
        deadline = time.time() + STARTUP
        while not any(s.get("name") == "skill-search" and (s.get("status") or {}).get("status") == "connected"
                      for s in call("GET", "/api/mcp") or []):
            if gone := exited(server):
                return gone
            if time.time() >= deadline:
                return "the skill-search MCP server never reported connected"
            time.sleep(POLL_START)
        sid = call("POST", "/api/session", {"location": {"directory": str(work)}})["id"]

        def prompt():
            try:
                call("POST", f"/api/session/{sid}/prompt", {"text": PROMPT})
            except Exception as e:   # recorded and judged by the poll loop; a daemon thread must not print
                prompt_errors.append(e)

        thread = threading.Thread(target=prompt, daemon=True)
        thread.start()

        def keep_transcript():
            for name, path in (("messages.json", f"/api/session/{sid}/message"),
                               ("context.json", f"/api/session/{sid}/context")):
                try:
                    (work / name).write_text(json.dumps(call("GET", path), indent=1))
                except Exception:   # best-effort evidence: the failure being reported matters more
                    pass

        deadline = time.time() + TIMEOUT
        while time.time() < deadline:
            if verdict(_rows(work / "logs"))[0] == "PASS":
                return "server turn finished"
            if prompt_errors:
                keep_transcript()
                return f"prompt request failed: {_describe(prompt_errors[0])}; transcript in messages.json"
            if gone := exited(server):
                return gone
            time.sleep(POLL)
        try:
            pending = _pending_summary(call("GET", f"/api/session/{sid}/permission") or []) or "none"
        except Exception as e:
            pending = f"unreadable ({_describe(e)})"
        keep_transcript()
        return (f"no offer + search rows within {TIMEOUT} s; pending permission requests: {pending}; "
                "transcript in messages.json")
    except urllib.error.HTTPError as e:
        return f"API error: {_describe(e)}"
    except (OSError, ValueError, KeyError, TypeError) as e:
        return f"API error: {e}"
    finally:
        if server is not None:
            _stop_group(server)
        if thread is not None:
            thread.join(timeout=5)


def _await_rows(logdir: Path) -> list[dict]:
    """Ledger writers are detached and can land after the CLI exits: poll up to LEDGER_GRACE s."""
    deadline = time.time() + LEDGER_GRACE
    while True:
        rows = _rows(logdir)
        if verdict(rows)[0] == "PASS" or time.time() >= deadline:
            return rows
        time.sleep(0.25)


def smoke(harness: str) -> tuple[str, str, float, Path | None]:
    if harness == "zcode":
        return "UNPROVEN", "no command line; drive one ZCode turn by hand", 0.0, None
    exe = OPENCODE_CMD[0] if harness == "opencode" else CLI[harness][0]
    if shutil.which(exe) is None:
        return (*verdict([], cli_found=False), 0.0, None)
    work = _workdir(harness)
    t0 = time.time()
    if harness == "opencode":
        note = _run_opencode(work)
        rows = _rows(work / "logs")
    else:
        note = _run_cli(harness, work)
        rows = _await_rows(work / "logs")
    status, detail = verdict(rows)
    if status == "FAIL":
        detail = f"{detail} ({note})" + (f". {HINTS[harness]}" if harness in HINTS else "")
    return status, detail, time.time() - t0, work


def _run_all(harnesses: list[str], advisory: set[str]) -> int:
    failed, waived = False, []
    for h in harnesses:
        try:
            status, detail, secs, work = smoke(h)
        except Exception as e:   # one harness's surprise must not abort the table
            status, detail, secs, work = "FAIL", f"{type(e).__name__}: {e}", 0.0, None
        if status != "PASS" and h in advisory:
            waived.append(h)
            detail += " (advisory: does not block)"
        else:
            failed |= status != "PASS"
        mark = {"PASS": "✓", "FAIL": "✗", "UNPROVEN": "?"}[status]
        print(f"  [{mark}] {h:<12} {status:<8} {secs:5.0f} s  {detail}")
        if work and status == "PASS":
            shutil.rmtree(work, ignore_errors=True)
        elif work:
            print(f"      evidence kept: {work}")
    note = f" (advisory, not proven: {', '.join(waived)})" if waived else ""
    print(("smoke: FAIL" if failed else "smoke: OK") + note)
    return 1 if failed else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("harness", nargs="*", help=f"any of {', '.join(HARNESSES)} (default: all)")
    ap.add_argument("--advisory", default=os.environ.get("SMOKE_ADVISORY", ""),
                    help="comma-separated harnesses whose FAIL or UNPROVEN does not block (default: $SMOKE_ADVISORY)")
    ap.add_argument("--accept-unproven", default="", help="older name; adds to --advisory")
    args = ap.parse_args(argv)
    unknown = set(args.harness) - set(HARNESSES)
    if unknown:
        ap.error(f"unknown harness: {', '.join(sorted(unknown))}")
    advisory = {h.strip() for h in f"{args.advisory},{args.accept_unproven}".split(",") if h.strip()}
    if advisory - set(HARNESSES):
        ap.error(f"unknown advisory harness: {', '.join(sorted(advisory - set(HARNESSES)))}")
    print("==> live smoke (one headless turn per harness)")
    previous = {}
    if threading.current_thread() is threading.main_thread():
        for name in ("SIGTERM", "SIGHUP"):
            if hasattr(signal, name):
                previous[getattr(signal, name)] = signal.signal(getattr(signal, name), _exit_on_signal)
    try:
        return _run_all(args.harness or list(HARNESSES), advisory)
    finally:
        for sig, old in previous.items():
            signal.signal(sig, old)


if __name__ == "__main__":
    sys.exit(main())
