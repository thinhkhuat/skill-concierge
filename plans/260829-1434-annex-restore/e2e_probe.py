#!/usr/bin/env python3
"""G6 probe — live end-to-end annex-restore check (ADR-0047, reverting ADR-0045).

Leg 1 (in-process, live embed + live Qdrant): _retrieve must return INSTALLED rows only
(no catalog names — the tier filter is back), while _retrieve_external returns marked
annex rows for a catalog-flavored intent, capped at EXTERNAL_SLOTS.
Leg 2 (subprocess, hook contract): the enforcer emits a well-formed SKILL-FIRST offer in
the annex render — the "External catalog matches" block when externals clear the floor,
NO inline [external:*] marker inside the primary ranked list.
Leg 3 (zero displacement): the primary rows are byte-identical with the annex on vs off.
Ledger writes land in a throwaway dir — real telemetry unpolluted.
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

fail = []


def leg1():
    import enforcer
    try:
        vector = enforcer._embed(CATALOG_PROMPT)
    except Exception as e:  # noqa: BLE001 — probe reports, not swallows
        fail.append(f"leg1: embed unavailable (is the shim up?): {type(e).__name__}: {e}")
        return
    rows = enforcer._retrieve(vector)
    print(f"leg1 installed top-{len(rows)}: "
          + ", ".join(f"{n}({s:.2f})" for n, _d, s in rows))
    if not rows:
        fail.append("leg1: installed retrieval returned zero rows")
    # catalog aliases live in the catalog-roots config; any installed row named
    # <alias>:<x> for a configured alias means the tier filter is NOT back
    try:
        home = Path(os.environ.get("SKILL_CONCIERGE_HOME",
                                   Path.home() / ".claude" / "skill-concierge"))
        aliases = tuple(k + ":" for k, v in json.loads(
            (home / "catalog-roots.json").read_text()).items() if isinstance(v, dict))
    except Exception:  # noqa: BLE001
        aliases = ()
    leaked = [n for n, _d, _s in rows if aliases and n.startswith(aliases)]
    if leaked:
        fail.append(f"leg1: catalog rows leaked into the installed pool: {leaked}")
    top = rows[0][2] if rows else 0.0
    annex = enforcer._retrieve_external(vector, top)
    print(f"leg1 annex ({len(annex)} rows, floor {enforcer._annex_floor(enforcer.EXTERNAL_FLOOR, top):.2f}): "
          + ", ".join(f"{n}[external:{a}]({s:.2f})" for n, _d, s, a in annex))
    if len(annex) > enforcer.EXTERNAL_SLOTS:
        fail.append(f"leg1: annex exceeds EXTERNAL_SLOTS: {len(annex)}")
    if not annex:
        fail.append("leg1: annex EMPTY for a catalog-flavored intent — the restore is not "
                    "observably live (this prompt scores 0.75+ externals on the live index)")
    for n, _d, _s, a in annex:
        if not a or a == "?":
            fail.append(f"leg1: annex row {n} lost its alias")


def _run_enforcer(env_extra):
    env = dict(os.environ)
    env.update(env_extra)
    payload = json.dumps({"prompt": CATALOG_PROMPT, "session_id": "annex-probe-g6"})
    proc = subprocess.run([sys.executable, str(ROOT / "hooks" / "scripts" / "enforcer.py")],
                          input=payload, capture_output=True, text=True,
                          env=env, timeout=30, cwd=str(ROOT))
    if proc.returncode != 0:
        fail.append(f"enforcer exited {proc.returncode}: {proc.stderr[:400]}")
        return None
    try:
        return json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
    except (ValueError, KeyError, TypeError) as e:
        fail.append(f"stdout not a well-formed hook injection: {e}: {proc.stdout[:200]}")
        return None


def _primary_rows(ctx):
    """The ranked-list bullet lines BEFORE any annex/foreign block."""
    lines = []
    for ln in ctx.splitlines():
        if ln.startswith(("External catalog matches", "Other-harness matches")):
            break
        if ln.startswith("  • "):
            lines.append(ln)
    return lines


def leg2_leg3():
    with tempfile.TemporaryDirectory() as td:
        base = {"SKILL_CONCIERGE_LOG": td}
        ctx_on = _run_enforcer(base)
        ctx_off = _run_enforcer({**base, "ENFORCER_EXTERNAL_ANNEX": "0"})
        ctx_alias = _run_enforcer({**base, "ENFORCER_EXTERNAL_OFFER": "0"})
    if not (ctx_on and ctx_off and ctx_alias):
        return
    if "SKILL-FIRST · reply line 1" not in ctx_on:
        fail.append(f"leg2: missing SKILL-FIRST header: {ctx_on[:200]}")
    primary_on = _primary_rows(ctx_on)
    if any("[external:" in ln for ln in primary_on):
        fail.append("leg2: [external:*] marker inside the PRIMARY ranked list — "
                    "annex restore not live")
    has_annex = "External catalog matches" in ctx_on
    print(f"leg2 offer ({len(ctx_on)} chars): "
          + ("annex block present" if has_annex else "no annex this turn"))
    if has_annex and "get_skill(" not in ctx_on:
        fail.append("leg2: annex block missing the get_skill consumption instruction")
    if "External catalog matches" in ctx_off or "[external:" in ctx_off:
        fail.append("leg3: ENFORCER_EXTERNAL_ANNEX=0 must remove every external trace")
    if "External catalog matches" in ctx_alias or "[external:" in ctx_alias:
        fail.append("leg3: parity-era alias ENFORCER_EXTERNAL_OFFER=0 must still kill the annex")
    # Compare as SORTED sets: two independent live Qdrant queries give no ordering
    # guarantee for tied scores (validator-caught flake, 2026-08-29 — tied 0.73 rows
    # swapped between runs). The invariant is membership, not tie order.
    if sorted(primary_on) != sorted(_primary_rows(ctx_off)):
        fail.append("leg3: primary row SET differs with annex on vs off — displacement! "
                    f"on={primary_on!r} off={_primary_rows(ctx_off)!r}")
    else:
        print(f"leg3 zero-displacement: {len(primary_on)} primary rows identical as a set "
              "with annex on/off; alias kill-switch honored")


def main():
    leg1()
    leg2_leg3()
    if fail:
        print("E2E ANNEX-RESTORE FAIL:")
        for f in fail:
            print("  -", f)
        return 1
    print("E2E ANNEX-RESTORE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
