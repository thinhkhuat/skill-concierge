"""Pins on the SKILL-FIRST doctrine body and the enforcer's injected strings.

The doctrine body is injected into every agent session; the audit script counts a
`SKILL-CHECK:` line as a lawful skip by five locked signature phrases that live ONLY in the
enforcer's leg messages. A copy of a signature inside the doctrine would miscount real dodges
as authorized, so the body must never carry one. The body must also point only at things that
exist (no phantom skill names) and cache nothing the environment can answer (no catalogue count).
"""
import ast
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
    assert len(sigs) == 5, sigs
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


def _section(body: str, start: str, end: str) -> str:
    i = body.index(start)
    return body[i:body.index(end, i)]


def test_doctrine_orders_off_list_read_before_using():
    """A skill picked outside the hits is reached through line-1 SEARCH, read, and quoted
    before `USING:`; ANY loaded body that excludes the task forces a visible re-rule; rule 5
    keeps switched-off skills off. Pinned to the rule each sentence must live in."""
    body = _body()
    rule3 = _section(body, "3. **Rule on the hits", "4. **A lawful skip")
    off_list = _section(rule3, "**Picking outside the hits.**", "\n\n")
    route = [off_list.index(x) for x in
             ("line 1 `SEARCH:`", "load its body", "quote the line", "`USING: <name>`")]
    assert route == sorted(route), "off-list route must run SEARCH -> load -> quote -> USING"
    assert "excludes the task" not in off_list, "the re-rule duty must cover hits too"
    rerule = _section(rule3, "**A loaded body that excludes the task**", "\n\n")
    for phrase in ("a hit's or not", "`(re-rule: <old>)`", "excluding line", "tell the user"):
        assert phrase in rerule, phrase
    # Continuing a skill already invoked this session: the re-read replaces the search (ADR-0063).
    cont = _section(rule3, "**Continuing a skill.**", "\n\n")
    for phrase in ("invoked earlier this session", "the new work is the same task",
                   "`USING: <name> (continuing)`", "re-read its body", "with `get_skill` (rule 5)",
                   "skill tool only when that call is unavailable or cannot find the skill",
                   "stands in for the search", "re-ruled"):
        assert phrase in cont, phrase
    rule5 = _section(body, "5. **", "6. **")
    assert "disabled_in" in rule5 and "switched off" in rule5
    assert "The name matches" in _section(body, "6. **", "Worked example")
    # One consumption literal: harness adapters rewrite the search-tool literals, and a second
    # get_skill copy would drift from them silently.
    assert body.count('get_skill("<name>")') == 1
    assert "RETRACT" not in body
    assert len(body) <= 4217 + 900, f"doctrine body grew to {len(body)} chars"


def test_one_skip_token_everywhere_agents_are_told_it():
    """Agents are told `NO SKILL: <why>` (ADR-0062) — by the standing order and by every enforcer
    message; the old `SKIPPING` token survives only in the readers that parse old transcripts."""
    body = _body()
    assert "NO SKILL: <why>" in body and "SKIPPING" not in body
    # Every string literal in the enforcer, however it is laid out (implicit concatenation folds
    # into one constant; docstrings included — none may teach the old token either).
    strings = [n.value for n in ast.walk(ast.parse(ENFORCER.read_text(encoding="utf-8")))
               if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert not [s for s in strings if "SKIPPING" in s]
    assert any("NO SKILL: <why>" in s for s in strings)
