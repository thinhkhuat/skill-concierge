"""E2E for the ADR-0029 chain hint — runs the REAL enforcer hook as a subprocess.

Env seams (SKILL_CONCIERGE_LOG, SKILL_CONCIERGE_NEXT_SKILLS) point the hook at a
temp ledger seeded with a fresh `auto` seed and a temp sidecar declaring one
successor. Embed/Qdrant are NOT mocked: whichever inject-bearing leg fires
(ranked mandate, mandate-only fallback, or an authorized-skip line), the hint must
ride it — that is the ADR's all-legs placement contract. The negative case pins
the documented limit: the ≤3-word pre-gate injects nothing at all.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ENFORCER = REPO / "hooks" / "scripts" / "enforcer.py"


def run_hook(prompt: str, sid: str, ledger_lines: list, sidecar: dict) -> str:
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        led = td / "skill-invocation-ledger.log"   # enforcer derives this name from the dir
        led.write_text("\n".join(ledger_lines) + "\n", encoding="utf-8")
        sc = td / "next-skills.json"
        sc.write_text(json.dumps(sidecar), encoding="utf-8")
        env = dict(os.environ,
                   SKILL_CONCIERGE_LOG=str(td),
                   SKILL_CONCIERGE_NEXT_SKILLS=str(sc),
                   ENFORCER_CHAIN_HINT="1")
        p = subprocess.run(
            [sys.executable, str(ENFORCER)],
            input=json.dumps({"prompt": prompt, "session_id": sid}).encode(),
            capture_output=True, env=env, timeout=30)
        return p.stdout.decode()


def _fixtures():
    now = time.time()
    lines = [json.dumps({"t": now - 60, "sid": "e2e", "ev": "auto", "name": "seed-e2e"})]
    sidecar = {"personal": {"seed-e2e": ["next-e2e"], "next-e2e": []}}
    return lines, sidecar


def test_hint_rides_whichever_inject_bearing_leg_fires():
    lines, sidecar = _fixtures()
    out = run_hook("please continue with the documentation work now", "e2e", lines, sidecar)
    assert "CHAIN-HINT: after seed-e2e, catalogue declares: next-e2e" in out, out


def test_short_pregate_injects_nothing():
    """ADR-documented limit: the ≤3-word pre-gate (ADR-0010 operator floor) returns
    before ANY injection — no mandate, no hint. Do not carve around it."""
    lines, sidecar = _fixtures()
    out = run_hook("go ahead now", "e2e", lines, sidecar)
    assert out.strip() == "", out


def test_no_seed_no_hint():
    """Byte-identity arm: a session with no recent skill use gets exactly today's
    output — no CHAIN-HINT anywhere, even with a sidecar fully populated."""
    _, sidecar = _fixtures()
    out = run_hook("please continue with the documentation work now", "other-sid", [], sidecar)
    assert "CHAIN-HINT" not in out, out
