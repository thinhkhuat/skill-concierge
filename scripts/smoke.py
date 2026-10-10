#!/usr/bin/env python3
"""Live smoke: one real headless turn per harness through the installed concierge.

Doctor proves files and config exist; this proves the concierge runs. Each harness answers one
side-effect-free prompt in its own empty temp folder, with SKILL_CONCIERGE_LOG pointing at that
folder, so every ledger row there came from that run and nothing reaches the live ledger, badges or
auto-promotion. PASS needs both rows a working install writes:

  offer   the per-turn enforcer ran (the turn row alone is written by ledger.py, so it proves less)
  search  the skill-search MCP tool reached the model and the post-tool hook logged it

A missing CLI is FAIL. ZCode has no command line, so it is UNPROVEN. Exit 1 on any FAIL, or on an
UNPROVEN harness not named in --accept-unproven. Stdlib only. Usage:

  python3 scripts/smoke.py [--accept-unproven zcode] [harness ...]
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

PROMPT = ('Use the search_skills tool exactly once with the query "haiku about weather". Then reply with '
          'only the name of the top result. Do not invoke any skill, do not use any other tool, do not '
          'edit any file.')
TIMEOUT = 300
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
OPENCODE_PORT = int(os.environ.get("SMOKE_OPENCODE_PORT", "4473"))


def verdict(rows: list[dict], cli_found: bool = True) -> tuple[str, str]:
    """PASS when the run's ledger holds an offer row and a search row; else FAIL naming what is missing."""
    if not cli_found:
        return "FAIL", "command line not found on PATH"
    evs = {r.get("ev") for r in rows}
    missing = [what for ev, what in (("offer", "no offer row: the per-turn enforcer did not run"),
                                     ("search", "no search row: search_skills did not reach the model"))
               if ev not in evs]
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


def _run_cli(harness: str, work: Path) -> str:
    argv = CLI[harness][1] + [PROMPT]
    env = dict(os.environ, SKILL_CONCIERGE_LOG=str(work / "logs"))
    try:
        p = subprocess.run(argv, cwd=work, env=env, stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, timeout=TIMEOUT)
        tail = (p.stdout + p.stderr).strip().splitlines()
        return f"exit {p.returncode}: {tail[-1][:300] if tail else ''}"
    except subprocess.TimeoutExpired:
        return f"timed out after {TIMEOUT} s"


def _run_opencode(work: Path) -> str:
    """A private `opencode serve`, started fresh so it loads the plugin just installed, driven over
    its HTTP API (`opencode run --server` can stall before creating a session). The prompt waits
    until skill-search reports connected for the folder: a fresh server connects its MCP servers
    after the session exists, and a model call made first gets no search_skills tool."""
    work = work.resolve()   # one OpenCode instance per folder: /var and /private/var would be two
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", OPENCODE_PORT)) == 0:
            return f"port {OPENCODE_PORT} is busy (set SMOKE_OPENCODE_PORT)"
    pw = secrets.token_hex(16)
    env = dict(os.environ, SKILL_CONCIERGE_LOG=str(work / "logs"), OPENCODE_SERVER_PASSWORD=pw)
    server = subprocess.Popen(["opencode", "serve", "--port", str(OPENCODE_PORT), "--hostname", "127.0.0.1"],
                              cwd=work, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    auth = "Basic " + base64.b64encode(f"opencode:{pw}".encode()).decode()

    def call(method: str, path: str, body=None):
        req = urllib.request.Request(f"http://127.0.0.1:{OPENCODE_PORT}{path}", method=method,
                                     data=None if body is None else json.dumps(body).encode())
        req.add_header("Authorization", auth)
        req.add_header("Content-Type", "application/json")
        req.add_header("x-opencode-directory", str(work))
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read()
        data = json.loads(raw) if raw else None
        return data.get("data", data) if isinstance(data, dict) else data

    try:
        for _ in range(60):
            try:
                call("GET", "/api/mcp")
                break
            except OSError:
                time.sleep(1)
        else:
            return "server did not start"
        # Asking for the folder's MCP status starts its servers; the session is created after
        # skill-search is connected, so its first model call already has the tool.
        for _ in range(60):
            if any(s.get("name") == "skill-search" and (s.get("status") or {}).get("status") == "connected"
                   for s in call("GET", "/api/mcp") or []):
                break
            time.sleep(1)
        else:
            return "the skill-search MCP server never reported connected"
        sid = call("POST", "/api/session", {"location": {"directory": str(work)}})["id"]
        threading.Thread(target=lambda: call("POST", f"/api/session/{sid}/prompt", {"text": PROMPT}),
                         daemon=True).start()
        deadline = time.time() + TIMEOUT
        while time.time() < deadline:
            # Answer only the skill-search tool's own permission request, once.
            for req in call("GET", f"/api/session/{sid}/permission") or []:
                if "skill-search" in json.dumps(req) or "skill_search" in json.dumps(req):
                    call("POST", f"/api/session/{sid}/permission/{req['id']}/reply", {"decision": "once"})
            if verdict(_rows(work / "logs"))[0] == "PASS":
                return "server turn finished"
            time.sleep(2)
        pending = call("GET", f"/api/session/{sid}/permission") or []
        messages = call("GET", f"/api/session/{sid}/message") or []   # newest first
        (work / "messages.json").write_text(json.dumps(messages, indent=1))
        (work / "context.json").write_text(json.dumps(call("GET", f"/api/session/{sid}/context"), indent=1))
        return (f"no offer + search rows within {TIMEOUT} s; pending permissions: "
                f"{json.dumps(pending)[:200]}; transcript in messages.json")
    except (OSError, ValueError, KeyError, TypeError) as e:
        return f"API error: {e}"
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()


def smoke(harness: str) -> tuple[str, str, float, Path | None]:
    if harness == "zcode":
        return "UNPROVEN", "no command line; drive one ZCode turn by hand", 0.0, None
    exe = "opencode" if harness == "opencode" else CLI[harness][0]
    if shutil.which(exe) is None:
        return (*verdict([], cli_found=False), 0.0, None)
    work = Path(tempfile.mkdtemp(prefix=f"sc-smoke-{harness}-"))
    t0 = time.time()
    note = _run_opencode(work) if harness == "opencode" else _run_cli(harness, work)
    status, detail = verdict(_rows(work / "logs"))
    if status == "FAIL":
        detail = f"{detail} ({note})" + (f". {HINTS[harness]}" if harness in HINTS else "")
    return status, detail, time.time() - t0, work


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("harness", nargs="*", help=f"any of {', '.join(HARNESSES)} (default: all)")
    ap.add_argument("--accept-unproven", default="", help="comma-separated harnesses allowed to stay UNPROVEN")
    args = ap.parse_args(argv)
    unknown = set(args.harness) - set(HARNESSES)
    if unknown:
        ap.error(f"unknown harness: {', '.join(sorted(unknown))}")
    accepted = {h.strip() for h in args.accept_unproven.split(",") if h.strip()}
    failed = False
    print("==> live smoke (one headless turn per harness)")
    for h in args.harness or HARNESSES:
        status, detail, secs, work = smoke(h)
        bad = status == "FAIL" or (status == "UNPROVEN" and h not in accepted)
        failed |= bad
        mark = {"PASS": "✓", "FAIL": "✗", "UNPROVEN": "?"}[status]
        print(f"  [{mark}] {h:<12} {status:<8} {secs:5.0f} s  {detail}")
        if work and status == "PASS":
            shutil.rmtree(work, ignore_errors=True)
        elif work:
            print(f"      evidence kept: {work}")
    print("smoke: FAIL" if failed else "smoke: OK")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
