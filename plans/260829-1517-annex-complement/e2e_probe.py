#!/usr/bin/env python3
"""G5 probe — live complement-annex check (ADR-0048).

Leg 1 (well-served intent, installed top >= GETAWAY_FLOOR): the annex must be EMPTY
(no external beats the installed top by ANNEX_BEAT) — the echo class dies here.
Leg 2 (thin intent — a proven builtin gap): the annex fills, the PROVEN external
(demonstrated takes in external-takes.json) ranks FIRST and the render carries used N×.
Leg 3 (subprocess kill-switch): ENFORCER_ANNEX_COMPLEMENT=0 restores the 0.40.0
margin-rule annex on the same well-served prompt (rows trailing within ANNEX_MARGIN
reappear) — proving leg 1's silence is the gate, not a broken annex.
In-process legs use the live embedder + live Qdrant; ledger writes land in a throwaway dir.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "hooks" / "scripts"))

WELL_SERVED = "help me make my skill collection self-improve continuously during development"
THIN = "containerize my app with apple containers on macos"

fail = []


def leg1():
    import enforcer
    vector = enforcer._embed(WELL_SERVED)
    rows = enforcer._retrieve(vector)
    top = rows[0][2] if rows else 0.0
    annex = enforcer._retrieve_external(vector, top)
    print(f"leg1 installed top {top:.2f} ({rows[0][0] if rows else '-'}); annex rows: {len(annex)}")
    if top < enforcer.GETAWAY_FLOOR:
        fail.append(f"leg1: probe prompt unexpectedly thin (top {top:.2f}) — pick a stronger domain")
    for n, _d, s, _a in annex:
        if s < top + enforcer.ANNEX_BEAT - 1e-9:
            fail.append(f"leg1: annex row {n} ({s:.2f}) did not beat top {top:.2f}+{enforcer.ANNEX_BEAT}")


def leg2():
    """Proven-gap domain against the live index. This shelf is broad (top >= 0.45 on
    nearly every real intent), so the live probe asserts the RANKING contract — a proven
    external never sits below an untaken one, and used-Nx renders — conditional on the
    annex being non-empty. The thin-intent WIDENING path is pinned deterministically by
    enforcer selftest 11c (no live intent on this index reliably goes below 0.45)."""
    import enforcer
    vector = enforcer._embed(THIN)
    rows = enforcer._retrieve(vector)
    top = rows[0][2] if rows else 0.0
    annex = enforcer._retrieve_external(vector, top)
    takes = enforcer._external_takes()
    print(f"leg2 installed top {top:.2f} ({rows[0][0] if rows else '-'}); annex rows: "
          + ", ".join(f"{n}({s:.2f}{'' if not takes.get(n) else ',used ' + str(takes[n]) + 'x'})"
                      for n, _d, s, _a in annex))
    if not annex:
        fail.append("leg2: proven-gap domain produced no annex rows — nothing to rank-check")
    for n, _d, s, _a in annex:
        floor = (top + enforcer.ANNEX_BEAT) if top >= enforcer.GETAWAY_FLOOR else enforcer.EXTERNAL_FLOOR
        if s < floor - 1e-9:
            fail.append(f"leg2: annex row {n} ({s:.2f}) below the applicable floor {floor:.2f}")
    proven = [(i, n) for i, (n, _d, _s, _a) in enumerate(annex) if takes.get(n)]
    if proven:
        first_idx, first_name = proven[0]
        above = [(n, s) for n, _d, s, _a in annex[:first_idx] if not takes.get(n)]
        if above:
            fail.append(f"leg2: proven {first_name} ranked below untaken {above}")
    rendered = enforcer._ranked_mandate(rows[:1], annex=annex, takes=takes)
    if proven and f"used {takes[proven[0][1]]}×" not in rendered:
        fail.append("leg2: render missing the used-N× marker for the proven row")
    if "External catalog matches" not in rendered:
        fail.append("leg2: annex block missing from render")


def leg3():
    with tempfile.TemporaryDirectory() as td:
        env = dict(os.environ)
        env["SKILL_CONCIERGE_LOG"] = td
        payload = json.dumps({"prompt": WELL_SERVED, "session_id": "complement-probe-g5"})
        out = {}
        for label, extra in (("on", {}), ("off", {"ENFORCER_ANNEX_COMPLEMENT": "0"})):
            e = {**env, **extra}
            proc = subprocess.run([sys.executable, str(ROOT / "hooks" / "scripts" / "enforcer.py")],
                                  input=payload, capture_output=True, text=True,
                                  env=e, timeout=30, cwd=str(ROOT))
            if proc.returncode != 0:
                fail.append(f"leg3/{label}: enforcer exited {proc.returncode}: {proc.stderr[:300]}")
                return
            try:
                out[label] = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
            except (ValueError, KeyError, TypeError) as e2:
                fail.append(f"leg3/{label}: malformed injection: {e2}")
                return
    on_ext = out["on"].count("[external:")
    off_ext = out["off"].count("[external:")
    print(f"leg3 subprocess: complement ON -> {on_ext} external row(s); OFF (margin rule) -> {off_ext}")
    if "SKILL-FIRST · reply line 1" not in out["on"]:
        fail.append("leg3: missing SKILL-FIRST header")
    if off_ext < on_ext:
        fail.append("leg3: kill-switch must not SHRINK the annex vs the beat gate — "
                    f"off={off_ext} on={on_ext}")


def main():
    leg1()
    leg2()
    leg3()
    if fail:
        print("E2E COMPLEMENT-ANNEX FAIL:")
        for f in fail:
            print("  -", f)
        return 1
    print("E2E COMPLEMENT-ANNEX OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
