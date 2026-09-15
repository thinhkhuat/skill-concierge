"""Pins on the SKILL-FIRST doctrine body and the enforcer's injected strings.

The doctrine body is injected into every agent session; the audit script counts a
`SKILL-CHECK:` line as a lawful skip by four locked signature phrases that live ONLY in the
enforcer's leg messages. A copy of a signature inside the doctrine would miscount real dodges
as authorized, so the body must never carry one. The body must also point only at things that
exist (no phantom skill names) and cache nothing the environment can answer (no catalogue count).
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCTRINE = ROOT / "hooks" / "doctrine" / "skill-first.md"
ENFORCER = ROOT / "hooks" / "scripts" / "enforcer.py"
AUDIT = ROOT / "skills" / "skill-usage-audit" / "scripts" / "audit_skill_usage.py"


def _body() -> str:
    text = DOCTRINE.read_text(encoding="utf-8")
    return text.split("<!-- DOCTRINE-START -->", 1)[1].split("<!-- DOCTRINE-END -->", 1)[0]


def _signatures() -> tuple[str, ...]:
    src = AUDIT.read_text(encoding="utf-8")
    m = re.search(r"_AUTHORIZED_SIGNATURES\s*=\s*\((.*?)\)", src, re.S)
    assert m, "audit script no longer declares _AUTHORIZED_SIGNATURES"
    return tuple(re.findall(r'"([^"]+)"', m.group(1)))


def test_locked_signatures_live_in_enforcer_not_doctrine():
    sigs = _signatures()
    assert len(sigs) == 4, sigs
    enforcer = ENFORCER.read_text(encoding="utf-8")
    body = _body()
    for s in sigs:
        assert s in enforcer, f"positive control: {s!r} missing from enforcer.py"
        assert s not in body, f"locked signature leaked into the doctrine body: {s!r}"
    assert "SKILL-CHECK:" in body, "doctrine must still explain the SKILL-CHECK: marker"


def test_doctrine_body_points_only_at_real_things():
    body = _body()
    assert "find-skills" not in body, "phantom skill name: find-skills is not an installed skill"
    assert "search_skills" in body and "get_skill" in body
    assert not re.search(r"~\d{3}", body), "catalogue count is an environment fact, not a cache"
    assert not re.search(r"ADR-\d{4}", body), "ADR labels are repo artifacts, not agent guidance"
    assert not re.search(r"\bv0\.\d+\.\d+", body), "version notes belong in the header, not the body"


def test_enforcer_strings_carry_no_phantom_pointer_or_stale_count():
    quoted = [ln for ln in ENFORCER.read_text(encoding="utf-8").splitlines()
              if ln.lstrip().startswith('"')]
    assert not [ln for ln in quoted if "find-skills" in ln]
    assert not [ln for ln in quoted if "~500" in ln]
