#!/usr/bin/env python3
"""consult-mode e2e probe (ADR-0049).

Leg 1 (in-process, live embed + live Qdrant): consult_candidates() returns fused rows
for a multi-sub-goal query set, carries capsule_coverage, degrades cleanly with an
empty query list, and honors the SKILL_CONSULT=0 kill-switch.
Leg 2 (subprocess, the real MCP server binary): initialize → tools/list MUST expose
consult_candidates, and a tools/call round-trip MUST return parseable rows — proving
the venv redeploy actually serves the new tool, not just that it imports.

Run with the ENGINE VENV python: ~/.claude/skill-concierge/venv/bin/python3 e2e_probe.py
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VENV_BIN = Path(os.environ.get("SKILL_CONCIERGE_VENV",
                               Path.home() / ".claude/skill-concierge/venv")) / "bin"

fail = []


def _mcp_env():
    """The real server's env from .mcp.json (the single source of truth) — the probe
    must exercise the PRODUCTION-shaped store (Docker Qdrant), not fall into local
    path mode, where an in-process leg1 would hold the storage lock the subprocess
    leg2 then contends on (diagnosed live 2026-08-29: child went silent-exit-0)."""
    try:
        env = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8")
                         )["mcpServers"]["skill-search"]["env"]
    except (KeyError, OSError, ValueError):
        env = {}
    merged = dict(os.environ)
    merged.update({k: v for k, v in env.items()})
    return merged


MCP_ENV = _mcp_env()


def leg1():
    for k, v in MCP_ENV.items():
        os.environ.setdefault(k, v)
    from skill_search import server
    out = json.loads(server.consult_candidates(
        queries=["write automated tests for python code",
                 "debug a failing pytest suite"], top_n=12))
    if "error" in out:
        fail.append(f"leg1: unexpected error: {out['error']}")
        return
    rows = out.get("results", [])
    if len(rows) < 3:
        fail.append(f"leg1: expected >=3 fused rows, got {len(rows)}")
    if "capsule_coverage" not in out:
        fail.append("leg1: capsule_coverage missing from payload")
    for r in rows:
        if "name" not in r or "score" not in r:
            fail.append(f"leg1: malformed row {r!r}")
            break
        ext = r.get("external")
        path = r.get("path")
        if ext is None and path is None:
            fail.append(f"leg1: installed row carries no path: {r.get('name')!r}")
            break
    bad = json.loads(server.consult_candidates(queries=["", "  "]))
    if "error" not in bad:
        fail.append("leg1: empty query list must return an error")
    os.environ["SKILL_CONSULT"] = "0"
    try:
        off = json.loads(server.consult_candidates(queries=["x y"]))
        if "error" not in off:
            fail.append("leg1: SKILL_CONSULT=0 must disable the tool")
    finally:
        os.environ.pop("SKILL_CONSULT", None)
    print(f"leg1 OK: {len(rows)} rows, capsule_coverage={out['capsule_coverage']}")


def leg2():
    import select
    proc = subprocess.Popen(
        [str(VENV_BIN / "skill-search")],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, env=MCP_ENV)

    def send(m):
        proc.stdin.write(json.dumps(m) + "\n")
        proc.stdin.flush()

    def read_until(want_ids, deadline_s=120.0):
        """Hold stdin OPEN and collect replies until want_ids seen or deadline —
        closing stdin after the burst lets the server exit on EOF before finishing
        the in-flight tools/call (embed takes seconds; the reply is lost)."""
        got, t0 = {}, time.time()
        while not want_ids.issubset(got):
            if time.time() - t0 > deadline_s:
                return got, True
            r, _, _ = select.select([proc.stdout], [], [], 1.0)
            if not r:
                continue
            line = proc.stdout.readline()
            if not line:
                return got, True
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if "id" in d:
                got[d["id"]] = d
        return got, False

    send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2024-11-05", "capabilities": {},
        "clientInfo": {"name": "consult-probe", "version": "0"}}})
    got, timed_out = read_until({1})
    send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    got, _ = read_until({2})
    tools = got.get(2, {}).get("result", {}).get("tools", [])
    names = [t.get("name") for t in tools]
    if "consult_candidates" not in names:
        fail.append(f"leg2: tools/list lacks consult_candidates: {names}")
        proc.kill()
        return
    send({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
        "name": "consult_candidates",
        "arguments": {"queries": ["plan a skill strategy for a task"],
                      "top_n": 8}}})
    got, timed_out = read_until({3})
    try:
        proc.stdin.close()
        proc.terminate()
    except OSError:
        pass
    if timed_out or 3 not in got:
        fail.append(f"leg2: tools/call reply never arrived (timeout={timed_out})")
        return
    call = got[3]
    if "error" in call:
        fail.append(f"leg2: tools/call errored: {call['error']}")
        return
    result = call.get("result", {})
    text = (result.get("content") or [{}])[0].get("text", "")
    try:
        payload = json.loads(text)
    except ValueError:
        fail.append(f"leg2: call text not JSON (isError={result.get('isError')}): "
                    f"{text[:300]!r}")
        return
    n = len(payload.get("results", []))
    if "error" in payload or n < 1:
        fail.append(f"leg2: call payload thin: {text[:200]}")
        return
    print(f"leg2 OK: server exposes consult_candidates; live call returned {n} rows")


def main():
    t0 = time.time()
    # leg2 FIRST: the subprocess must run before any in-process import can touch a
    # local-mode store (see _mcp_env note) — production env makes that moot, but the
    # order also keeps the probe robust on a machine where .mcp.json is absent.
    leg2()
    leg1()
    print(f"probe done in {time.time() - t0:.1f}s")
    if fail:
        print("FAIL:")
        for f in fail:
            print(f"  - {f}")
        return 1
    print("PASS: consult layer live (engine venv serving the new tool)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
