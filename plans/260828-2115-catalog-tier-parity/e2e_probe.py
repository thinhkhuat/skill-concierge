#!/usr/bin/env python3
"""G3 probe — live end-to-end tier-parity check (ADR-0045).

Leg 1 (in-process, live embed + live Qdrant): _retrieve's merged pool must be able to
carry an external catalog row for a catalog-flavored intent (no installed skill matches
it well).
Leg 2 (subprocess, hook contract): the enforcer runs on a plain task prompt, exits 0,
emits a well-formed SKILL-FIRST offer in the tier-parity render (inline [external:*]
markers + get_skill footer when externals show; the ADR-0032 annex block is gone).
Ledger writes from both legs land in a throwaway log dir — real telemetry unpolluted.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "hooks" / "scripts"))

CATALOG_PROMPT = ("help me make my skill collection self-improve continuously "
                  "during development")
PLAIN_PROMPT = "plan the implementation phases for the payment integration feature"

fail = []


def leg1():
    import enforcer
    try:
        vector = enforcer._embed(CATALOG_PROMPT)
    except Exception as e:  # noqa: BLE001 — probe reports, not swallows
        fail.append(f"leg1: embed unavailable (is the shim up?): {type(e).__name__}: {e}")
        return
    rows, ext = enforcer._retrieve(vector)
    ext_rows = [(n, d, s) for (n, d, s) in rows if n in ext]
    print(f"leg1 merged top-{len(rows)}: "
          + ", ".join(f"{n}{'' if n not in ext else '[external:' + ext[n] + ']'}({s:.2f})"
                      for n, d, s in rows))
    if not rows:
        fail.append("leg1: merged retrieval returned zero rows")
    if not ext_rows:
        fail.append("leg1: NO external row in the merged pool for a catalog-flavored "
                    f"intent — tier parity is not live: {rows!r}")


def leg2():
    import enforcer  # noqa: F401 — ensure module caches are warm before subprocess
    with tempfile.TemporaryDirectory() as td:
        env = dict(os.environ)
        env["SKILL_CONCIERGE_LOG"] = td          # throwaway ledger — real one unpolluted
        payload = json.dumps({"prompt": PLAIN_PROMPT, "session_id": "parity-probe-g3"})
        proc = subprocess.run([sys.executable, str(ROOT / "hooks" / "scripts" / "enforcer.py")],
                              input=payload, capture_output=True, text=True,
                              env=env, timeout=30, cwd=str(ROOT))
        if proc.returncode != 0:
            fail.append(f"leg2: enforcer exited {proc.returncode}: {proc.stderr[:400]}")
            return
        try:
            out = json.loads(proc.stdout)
            ctx = out["hookSpecificOutput"]["additionalContext"]
        except (ValueError, KeyError, TypeError) as e:
            fail.append(f"leg2: stdout is not a well-formed hook injection: {e}: "
                        f"{proc.stdout[:200]}")
            return
        if "SKILL-FIRST · reply line 1" not in ctx:
            fail.append(f"leg2: missing SKILL-FIRST header: {ctx[:200]}")
        if "External catalog matches" in ctx:
            fail.append("leg2: the ADR-0032 annex block must be gone from the render")
        if "[external:" in ctx and "Rows marked [external:*]" not in ctx:
            fail.append("leg2: external rows shown without the get_skill footer")
        print(f"leg2 offer ({len(ctx)} chars): "
              + ("carries external rows" if "[external:" in ctx else "installed-only this turn"))


def main():
    leg1()
    leg2()
    if fail:
        print("E2E PARITY FAIL:")
        for f in fail:
            print("  -", f)
        return 1
    print("E2E PARITY OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
