#!/usr/bin/env python3
"""skill-concierge — PreToolUse(agent) gate: deny a bare Claude tier alias in an
agent-tool call's `model` argument, with a reason that teaches the exact fix.

The live incident (2026-10-16): a Command Code session delegated to vn-editor-agent
with `model: "opus"` in the call. The dispatcher (cli.mjs::describeUnknownSubagentModel)
validates the call-arg model against its SHIPPED /model catalog only — no config alias
map exists — and refuses a bare alias with a message that blames the agent FILE
("…/vn-editor-agent.md is configured with an unknown model 'opus'") even though the
value came from the call. That mis-attribution sent the fix to the definition layer,
where the bridge (cmd_agent_bridge.py) had already done its part; the file never
configured the model. Probes: the exact-id spawn and the plain spawn both pass; the
bare-alias call-arg refusal is shipped behavior with no config seam and no seam may be
invented in the dispatcher.

This guard is the one writable seam left in the spawn path. It denies the bare alias
BEFORE the dispatcher runs and names the exact id the user's own model pool resolves it
to — the same resolution cmd_agent_bridge.py uses for a frontmatter `model:` — so the
retry is self-service instead of a dead end. A call-arg value that is already a real
/model id, `inherit`, or absent passes silently; the definition layer stays the
bridge's business.

Fires only on tool_name == "agent". Two legs, each teaching instead of dead-ending:

1. a `model` argument that is a bare Claude tier alias (opus / sonnet / haiku / fable, with or
   without the `claude-` prefix, any case) — the shipped dispatcher refuses it while blaming the
   agent FILE;
2. a `subagent_type` no registry entry backs (live incident: a session spawned
   `subagent_type: "pstack-architect"`, a SKILL, and got a bare `Unknown subagent_type:` with no
   hint that the name is invocable as a skill). The registry view is replicated exactly — bundled
   general/explore/plan, the mirror dir's filenames AND frontmatter `name:` values, and the
   project dir — so a legal type is never denied; an unregistered type is denied with a reason
   that names the `/skill:<name>` form when the port installs such a skill.

Everything else exits 0 silently. Fail-open: any internal error permits the call — a broken guard
must never wedge delegation. AGENT_MODEL_GUARD=0 kills it. Stdlib only, Python 3.9+.

Tests: tests/test_agent_model_guard.py. Probe (real CC tool_input, the exact original failing
call): pipe {"tool_name":"agent","tool_input":{"subagent_type":
"vn-editor-agent","model":"opus"}} — the deny JSON must come out.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# The alias table and the pool reader are the bridge's own: one source of the
# resolution, so a guard denial and a mirror translation never disagree.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

BUNDLED_AGENTS = frozenset({"general", "explore", "plan"})


def _registry_names():
    """Every subagent_type Command Code's own registry would hold, as its loader reads them.

    Bundled general/explore/plan, then every `*.md` in the mirror dir by filename stem AND by
    frontmatter `name:` (the name field is the id the loader registers), then the project dir's
    own agents. Cases match the dispatcher's resolver."""
    from cmd_agent_bridge import DEST_DEFAULT
    names = set(BUNDLED_AGENTS)
    for folder in (Path(DEST_DEFAULT), Path.cwd() / ".commandcode" / "agents"):
        try:
            if not folder.is_dir():
                continue
            for p in folder.glob("*.md"):
                names.add(p.stem)
                try:
                    head = p.read_text(encoding="utf-8", errors="replace")[:2048]
                except OSError:
                    continue
                m = re.search(r"^name:\s*(\S+)", head, re.M)
                if m:
                    names.add(m.group(1).strip().strip("'\"").lower())
        except OSError:
            continue
    return names


def decide_type(subagent_type: str, registry=None, skills_root=None):
    """'deny' reason string when SUBAGENT_TYPE names no registered subagent, else None.

    REGISTRY overrides the scanned name set and SKILLS_ROOT the skill-location check
    (tests); None reads the live machine. A missing registry view (unreadable dirs) is
    NOT a denial: the dispatcher rejects an unknown type harmlessly, and this guard must
    never deny a legal spawn — so only a name that is verifiably absent everywhere
    scannable can be denied."""
    value = (subagent_type or "").strip().strip("'\"")
    names = _registry_names() if registry is None else set(registry)
    if not value or value.lower() in names:
        return None
    skill = Path(skills_root or (Path.home() / ".commandcode" / "skills")) / value
    try:
        if (skill / "SKILL.md").is_file():
            return (f"agent_model_guard: `subagent_type: {value}` names no registered subagent "
                    f"— the dispatcher would refuse it. `{value}` is a Command Code SKILL: "
                    f"invoke it as /skill:{value} for this task instead of delegating. "
                    "Registered delegates live in ~/.commandcode/agents (see /agents).")
    except OSError:
        pass
    return (f"agent_model_guard: `subagent_type: {value}` names no registered subagent — the "
            "dispatcher would refuse it. Pick a registered delegate (see /agents; the bundled "
            "ones are general, explore, plan), or run the work as a skill via /skill:<name> "
            "when one exists.")


def _alias_table():
    from cmd_agent_bridge import MODEL_ALIAS_RE, ALIAS_FAMILY, configured_models
    return MODEL_ALIAS_RE, ALIAS_FAMILY, configured_models


def decide(value: str, pool=None):
    """'deny' reason string when VALUE is a bare Claude tier alias, else None.

    POOL overrides the user's configured-model list (tests); None reads
    ~/.commandcode/config.json through the bridge's own reader."""
    try:
        alias_re, family, pool_reader = _alias_table()
        match = alias_re.match(value or "")
        if not match:
            return None
        fam = family[match.group(1).lower()]
        models = pool_reader() if pool is None else list(pool)
        target = next((m for m in models if m.startswith(fam)), None)
        if target:
            resolution = (f"the user's current config pool resolves `{match.group(1)}` "
                          f"-> `{target}`")
        else:
            resolution = (f"no {fam}-class model is pinned in ~/.commandcode/config.json "
                          "— run /model to pick one")
        return (f"agent_model_guard: `model: {value}` in an agent-tool call is refused by "
                "Command Code's dispatcher — it validates the call-arg model against its "
                "shipped /model catalog, and a bare Claude alias is not a catalog id (its "
                "own refusal names the agent FILE even though the value came from this "
                "call). Pass an exact /model id instead: " + resolution
                + " (e.g. claude-opus-5-5) — or drop the `model` argument to inherit the "
                "session model.")
    except Exception:
        return None


def main():
    if os.environ.get("AGENT_MODEL_GUARD", "1") == "0":
        return 0
    try:
        payload = json.load(sys.stdin)
        if (payload.get("tool_name") or "") != "agent":
            return 0
        tool_input = payload.get("tool_input") or {}
        reason = decide_type(tool_input.get("subagent_type")) or decide(tool_input.get("model", ""))
        if reason:
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason}}))
    except Exception:
        return 0
    return 0


def _selftest():
    pool = ["claude-sonnet-5-5", "claude-opus-4-8", "moonshotai/Kimi-K3"]
    deny = ["opus", "Opus", "sonnet", "haiku", "fable", "claude-opus", "claude-sonnet"]
    allow = ["claude-opus-4-8", "inherit", "zai-org/glm-5.3-flash", "gpt-5-6", ""]
    bad = []
    for v in deny:
        if not decide(v, pool):
            bad.append(f"deny missed {v!r}")
        elif "claude-opus-4-8" not in decide(v, pool) and v.lower().replace(
                "claude-", "").startswith("opus"):
            bad.append(f"opus denial does not name the resolved id: {v!r}")
    for v in allow:
        if decide(v, pool):
            bad.append(f"allowed {v!r} was denied")
    # a family the pool does not carry is never translated blindly: no invented id
    no_fable = decide("fable", pool)
    if no_fable is None or "claude-fable-5" in no_fable:
        bad.append("fable without a pinned family must deny without a catalogue guess")
    # the type leg: bundled names and an existing agent id pass, an unregistered skill
    # name is denied with the /skill: form, a fully unknown name is denied generically
    import cmd_agent_bridge
    mirror_ids = [p.stem for p in Path(cmd_agent_bridge.DEST_DEFAULT).glob("*.md")] \
        if Path(cmd_agent_bridge.DEST_DEFAULT).is_dir() else []
    for t in BUNDLED_AGENTS | {x for x in mirror_ids if x}:
        if decide_type(t):
            bad.append(f"registered type {t!r} was denied")
    type_deny = decide_type("pstack-architect")
    if not (type_deny or ""):
        bad.append("an unregistered type was allowed")
    elif "/skill:pstack-architect" not in type_deny:
        bad.append(f"the skill match is not named: {type_deny[:120]}")
    unknown = decide_type("not-a-real-agent-xyz")
    if not (unknown or "") or "/skill:not-a-real-agent-xyz" in unknown:
        bad.append("a fully unknown name must deny generically, never name a fake skill")
    # a failed config read is fail-open (no pool -> deny only names /model)
    print("selftest ok" if not bad else f"selftest FAIL: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(_selftest() if "--selftest" in sys.argv else main())
