#!/usr/bin/env python3
"""
skill-concierge — SKILL-FIRST doctrine injector (SessionStart hook).

The caveman-proven half of the split the enforcer was missing. caveman governs by
injecting its FULL ruleset at SessionStart (not a 2-sentence summary — the summary
drifts away mid-conversation, especially after compaction) and re-asserting a cheap
trigger per turn (the enforcer's job). This hook is the SessionStart half: it reads
the rich standing order from hooks/doctrine/skill-first.md AT RUNTIME and emits it as
session context, so editing the doctrine propagates with no code change.

Session-scoping (H3, ADR-0020): the ONE detection here is subagent-scoping — if the
SessionStart payload carries the common `agent_id` field (present only when the hook
fires inside a subagent call, per the live hooks docs) and SKILL_SUBAGENT_STOP is on,
injection is suppressed, so scoped workers that can't act on the doctrine aren't nagged
and the usage ledger stays clean. Everything else is unchanged: the doctrine shapes
generation by being present in the model's context as it writes (prevention, not
policing); there is no post-turn gate.

Design contract (mirrors the sibling enforcer/ledger hooks):
  • FAIL TOWARD INJECTION — a top-level session must NEVER lose the doctrine; any stdin
    parse/detection error falls through to inject (suppression needs a POSITIVE agent_id
    proof). A genuine doctrine-file read error still exits 0 (nothing to inject anyway).
  • ADDITIVE-ONLY — only ever emits hookSpecificOutput.additionalContext.
  • STDLIB-ONLY — no heavy imports, no network, no I/O beyond stdin + the one doctrine read.

Per ~/.claude docs (working-with-claude-code/hooks.md): SessionStart stdout is added
to the context; exit 0. We use the structured hookSpecificOutput form for clarity.
"""
import json
import os
import sys
from pathlib import Path

# Doctrine lives two levels up from this script: hooks/scripts/doctrine.py →
# hooks/doctrine/skill-first.md. Resolved from __file__ so it is install-location
# independent (the plugin cache path differs from the dev repo path).
DOCTRINE_PATH = Path(__file__).resolve().parent.parent / "doctrine" / "skill-first.md"

# Only the body between these markers is injected — the file's own header/usage note
# is for human maintainers, not the model's context.
_START = "<!-- DOCTRINE-START -->"
_END = "<!-- DOCTRINE-END -->"

# H3 subagent-scoping (ADR-0020). Default-ON, one-var revert (mirrors ENFORCER_AUTHORIZED_SKIP /
# SKILL_BODY_TRIGGERS). `=0` → old unconditional injection, byte-identical.
SUBAGENT_STOP = os.environ.get("SKILL_SUBAGENT_STOP", "1") != "0"


def _body(text: str) -> str:
    """Return the doctrine body between the markers, or the whole file if markers
    are absent (so a malformed edit degrades to over-injecting, never to silence)."""
    i = text.find(_START)
    j = text.find(_END)
    if i != -1 and j != -1 and j > i:
        return text[i + len(_START):j].strip()
    return text.strip()


def _is_subagent(raw: str) -> bool:
    """Positive subagent proof for H3 scoping (ADR-0020). True ONLY when the SessionStart payload
    carries the common `agent_id` field — present only when the hook fires inside a subagent call
    (live hooks docs, code.claude.com/docs/en/hooks). Keyed on `agent_id`, NOT `agent_type`
    (agent_type also appears for top-level `--agent`/persona sessions, which MUST keep the doctrine).
    Any parse error → False, i.e. fail TOWARD injection: a top-level session must never lose the
    doctrine on a detection glitch (suppression requires a positive proof, never absence-of-signal)."""
    try:
        data = json.loads(raw) if raw.strip() else {}
        if not isinstance(data, dict):
            return False
        aid = data.get("agent_id")
        return isinstance(aid, str) and aid.strip() != ""
    except json.JSONDecodeError:
        return False


def _drop_duplicate_or_line(text: str) -> str:
    """Harnesses with no slash-command form rewrite BOTH search bullets to the same tool
    name; keep the `tool:` bullet and drop the now-identical `or:` bullet."""
    out, seen = [], None
    for line in text.splitlines(keepends=True):
        s = line.strip()
        if s.startswith("- tool: "):
            seen = s[len("- tool: "):].strip()
        elif s.startswith("- or:") and seen and s[len("- or:"):].strip() == seen:
            continue
        out.append(line)
    return "".join(out)


def _harness_adapt(doctrine: str) -> str:
    """Adapt tool and slash-command names to the executing harness.

    Under Claude Code (plugin installed):
      tool: `mcp__plugin_skill-concierge_skill-search__search_skills`
      slash: `/skill-concierge:skill-search`

    Under Command Code or Codex:
      tool: `mcp__skill-search__search_skills` (or `mcp__skill_search__search_skills`)
      slash: `/skill-search`

    Under OMP:
      tool: `mcp__skill_concierge_skill_search_search_skills` — OMP mints every MCP tool name as
      `mcp__<server>_<tool>` with each run of non-alphanumerics folded to one `_` (OMP
      src/mcp/tool-bridge.ts mintMCPToolName; observed live 2026-08-26, see the OMP adapter).
      slash: none — the slash hint is rewritten to the same tool name.
      The rule-5 `get_skill("<name>")` hint is NOT rewritten: `read("skill://<name>")` resolves only
      skills OMP itself loaded (src/internal-urls/skill-protocol.ts: `getActiveSkills()`, else
      "Unknown skill"), and rule 5 governs exactly the hits OMP did not load — the skill-search
      get_skill tool reads any indexed skill. (Before v0.49.0 both hints pointed at names OMP
      could not serve.)

    Under ZCode (ADR-0042): NO rewrite — ZCode flattens plugin MCP ids exactly like Claude
    Code (`mcp__plugin_skill-concierge_skill-search__search_skills`, verified live
    2026-08-28) and resolves plugin skills by the same `plugin:skill` alias, so the
    Claude-default rendering above is already the ZCode-correct one. `SKILL_CONCIERGE_HARNESS=zcode`
    therefore falls through every rewrite branch unchanged.

    Under DSH (ADR-0050): DSH's MCP client bridges MCP tools as
    `mcp__<serverName>__<rawName>`. The skill-search server has no plugin namespace
    prefix in DSH (it rides the plain `dsh-mcp-client` entry, not a plugin manifest).
    So the tool name is `mcp__skill-search__search_skills` — same as commandcode.
    DSH has no slash-commands; the hint is rewritten to reference the skill tool
    instead (`skill` + skill name lookup). The rule-5 `get_skill("<name>")` hint is left as
    written: it names the tool by its short name, which the agent resolves to the bridged form.
    """
    harness = os.environ.get("SKILL_CONCIERGE_HARNESS", "").strip().lower()
    if harness in ("omp", "oh-my-pi"):
        harness = "omp"
    if harness in ("commandcode", "cmd", "command-code"):
        harness = "commandcode"
    if harness in ("zcode", "z-code"):
        return doctrine  # ZCode rendering is Claude-default; no rewrite (ADR-0042)
    if harness in ("dsh", "deepseek-harness", "oh-dsh", "ohdsh"):
        harness = "dsh"
    if harness in ("cline", "cline-cli"):
        harness = "cline"
    if not harness and os.environ.get("OMPCODE", "").strip() == "1":
        harness = "omp"
    _zpr = os.environ.get("ZCODE_PLUGIN_ROOT", "").strip()
    if not harness and _zpr and os.path.isabs(_zpr):
        harness = "zcode"
        return doctrine
    if not harness and os.environ.get("DSH_SHELL", "").strip() == "1":
        harness = "dsh"
    if not harness:
        marker_omp = f"{os.sep}.omp{os.sep}"
        marker_codex = f"{os.sep}.codex{os.sep}"
        marker_zcode = f"{os.sep}.zcode{os.sep}"
        marker_cmd = f"{os.sep}.commandcode{os.sep}"
        marker_dsh = f"{os.sep}.dsh{os.sep}"
        marker_ohdsh = f"{os.sep}.ohdsh{os.sep}"
        marker_claude = f"{os.sep}.claude{os.sep}"
        for cand in (os.environ.get("CLAUDE_PLUGIN_ROOT"), __file__):
            if not cand or not os.path.isabs(cand):
                continue
            try:
                resolved = str(Path(cand).resolve())
            except (OSError, RuntimeError):
                resolved = ""
            if marker_omp in resolved:
                harness = "omp"
                break
            if marker_codex in resolved:
                harness = "codex"
                break
            if marker_zcode in resolved:
                harness = "zcode"
                return doctrine
            if marker_cmd in resolved:
                harness = "commandcode"
                break
            if marker_dsh in resolved or marker_ohdsh in resolved:
                harness = "dsh"
                break
            if marker_claude in resolved:
                harness = "claude"
                break
    if harness == "dsh":
        # DSH's MCP client bridges as `mcp__<serverName>__<rawName>` — same naming
        # as Command Code. No slash-commands in DSH; rewrite to reference the skill
        # tool and the MCP-bridged get_skill form.
        return _drop_duplicate_or_line(doctrine.replace(
            "mcp__plugin_skill-concierge_skill-search__search_skills",
            "mcp__skill-search__search_skills"
        ).replace(
            "/skill-concierge:skill-search",
            "mcp__skill-search__search_skills"
        ).replace(
            "/skill-search",
            "mcp__skill-search__search_skills"
        ))
    if harness == "cline":
        # Cline (ADR-0051): the MCP server rides the plain global mcpServers map (no
        # plugin namespace). LIVE-VERIFIED 2026-09-01 on Cline CLI 3.0.60: the CLI is
        # built on the Claude Agent SDK (embedded @anthropic-ai/claude-agent-sdk in
        # the shipped binary), so MCP tools surface FLATTENED as `<server>__<tool>` —
        # there is no `use_mcp_tool` in the model-facing tool surface. No
        # slash-commands hint form either.
        _cline_tool = "skill-search__search_skills"
        return _drop_duplicate_or_line(doctrine.replace(
            "mcp__plugin_skill-concierge_skill-search__search_skills",
            _cline_tool
        ).replace(
            "/skill-concierge:skill-search",
            _cline_tool
        ).replace(
            "/skill-search",
            _cline_tool
        ))
    if harness == "omp":
        return _drop_duplicate_or_line(doctrine.replace(
            "mcp__plugin_skill-concierge_skill-search__search_skills",
            "mcp__skill_concierge_skill_search_search_skills"
        ).replace(
            "/skill-concierge:skill-search",
            "mcp__skill_concierge_skill_search_search_skills"
        ))
    if harness in ("commandcode", "cmd", "command-code"):
        return doctrine.replace(
            "mcp__plugin_skill-concierge_skill-search__search_skills",
            "mcp__skill-search__search_skills"
        ).replace(
            "/skill-concierge:skill-search",
            "/skill-search"
        )
    if harness == "codex":
        return doctrine.replace(
            "mcp__plugin_skill-concierge_skill-search__search_skills",
            "mcp__skill_search__search_skills"
        ).replace(
            "/skill-concierge:skill-search",
            "/skill-search"
        )
    return doctrine


def main() -> int:
    # Read the SessionStart payload FIRST — but NEVER let a stdin/parse failure suppress the
    # doctrine. is_subagent stays False on any error (fail TOWARD injection); suppression fires
    # only on a positive `agent_id` proof AND the kill-switch on.
    raw = ""
    try:
        raw = sys.stdin.read()
    except (OSError, ValueError):
        raw = ""
    if SUBAGENT_STOP and _is_subagent(raw):
        return 0  # subagent session — scoped worker can't act on the doctrine; skip injection

    try:
        text = DOCTRINE_PATH.read_text(encoding="utf-8")
        doctrine = _body(text)
        if not doctrine:
            return 0
        doctrine = _harness_adapt(doctrine)
        sys.stdout.write(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": doctrine,
            }
        }))
    except (OSError, UnicodeError):
        return 0  # fail-silent on a genuine doctrine-file read error (nothing to inject anyway)
    return 0


def _run_capture(payload_raw: str, subagent_stop: bool) -> str:
    """Run main() with a fake stdin + captured stdout; return what was written. Test-only."""
    import io
    global SUBAGENT_STOP
    saved_stop, saved_in, saved_out = SUBAGENT_STOP, sys.stdin, sys.stdout
    SUBAGENT_STOP = subagent_stop
    sys.stdin, sys.stdout = io.StringIO(payload_raw), io.StringIO()
    try:
        main()
        return sys.stdout.getvalue()
    finally:
        SUBAGENT_STOP, sys.stdin, sys.stdout = saved_stop, saved_in, saved_out


def _selftest() -> int:
    """Pin H3 subagent-scoping (ADR-0020): subagent(agent_id) suppresses; top-level +
    persona(agent_type-only) + malformed/empty stdin all INJECT (fail toward injection); flag-off is
    byte-identical regardless of agent_id. Run: python3 doctrine.py --selftest"""
    bad = []
    top = '{"hook_event_name":"SessionStart","source":"startup","session_id":"s"}'
    sub = '{"hook_event_name":"SessionStart","source":"startup","session_id":"s","agent_id":"a1"}'
    persona = '{"hook_event_name":"SessionStart","source":"startup","session_id":"s","agent_type":"claudia"}'
    malformed = '{ not valid json'
    empty = ''

    if "additionalContext" not in _run_capture(top, True):
        bad.append("top-level session must inject the doctrine")
    if _run_capture(sub, True).strip():
        bad.append("subagent session (agent_id present) must NOT inject when flag ON")
    if "additionalContext" not in _run_capture(persona, True):
        bad.append("top-level --agent/persona (agent_type, no agent_id) must keep the doctrine")
    if "additionalContext" not in _run_capture(malformed, True):
        bad.append("malformed stdin must still inject (fail toward injection)")
    if "additionalContext" not in _run_capture(empty, True):
        bad.append("empty stdin must still inject (fail toward injection)")
    off_sub, off_top = _run_capture(sub, False), _run_capture(top, False)
    if "additionalContext" not in off_sub:
        bad.append("SKILL_SUBAGENT_STOP=0 must inject unconditionally (byte-identical old behaviour)")
    if off_sub != off_top:
        bad.append("flag-off output must be identical regardless of agent_id")
    if _run_capture(top, True) != off_top:
        bad.append("flag-on top-level injection must be byte-identical to flag-off")

    # OMP harness adaptation: OMP's minted MCP tool name replaces both the claude tool + slash
    # hint; the rule-5 get_skill hint stays — read(skill://...) cannot load a skill OMP did not
    # discover, which is every hit rule 5 governs.
    # The sample is the LIVE doctrine body, not a fixture: a fixture kept passing while the
    # doctrine's own get_skill hint had drifted away from the rewrite target (2026-09-15).
    try:
        _sample = _body(DOCTRINE_PATH.read_text(encoding="utf-8"))
    except OSError:
        _sample = ""
    if "get_skill(\"<name>\")" not in _sample or "mcp__plugin_skill-concierge_skill-search__search_skills" not in _sample:
        bad.append("doctrine body must carry the claude-form search tool and the get_skill(\"<name>\") hint the harness rewrites target")
    _saved_env = os.environ.get("SKILL_CONCIERGE_HARNESS")
    os.environ["SKILL_CONCIERGE_HARNESS"] = "omp"
    try:
        _adapted = _harness_adapt(_sample)
    finally:
        if _saved_env is None:
            os.environ.pop("SKILL_CONCIERGE_HARNESS", None)
        else:
            os.environ["SKILL_CONCIERGE_HARNESS"] = _saved_env
    if "mcp__skill_concierge_skill_search_search_skills" not in _adapted:
        bad.append("omp adapt: search tool must be OMP's minted mcp__skill_concierge_skill_search_search_skills")
    if "/skill-concierge:skill-search" in _adapted or "/skill-search" in _adapted:
        bad.append("omp adapt: no slash-command form under omp")
    if 'get_skill("<name>")' not in _adapted or "skill://" in _adapted:
        bad.append("omp adapt: rule 5 must keep get_skill(\"<name>\") — skill:// reads only skills OMP loaded")
    if _adapted.count("mcp__skill_concierge_skill_search_search_skills") != 1:
        bad.append("omp adapt: the search tool must be named once (duplicate `or:` bullet dropped)")

    # Command Code (ADR-0038): rewrites the plugin-namespaced MCP + slash to the
    # bare `mcp__skill-search__search_skills` / `/skill-search` Command Code
    # actually exposes (verified via the mod adapter's SKILL_CONCIERGE_HARNESS).
    # Pin the explicit env and the .commandcode path-marker fallback.
    _saved_cc = os.environ.get("SKILL_CONCIERGE_HARNESS")
    for _env_val in ("commandcode", "cmd"):
        os.environ["SKILL_CONCIERGE_HARNESS"] = _env_val
        try:
            _adapted = _harness_adapt(_sample)
        finally:
            pass
        if "mcp__skill-search__search_skills" not in _adapted:
            bad.append(f"commandcode adapt ({_env_val}): tool must be mcp__skill-search__search_skills")
        if "/skill-search" not in _adapted or "/skill-concierge:skill-search" in _adapted:
            bad.append(f"commandcode adapt ({_env_val}): slash must be /skill-search")
        if "mcp__plugin_skill-concierge" in _adapted:
            bad.append(f"commandcode adapt ({_env_val}): must not keep the plugin-namespaced tool")
    if _saved_cc is None:
        os.environ.pop("SKILL_CONCIERGE_HARNESS", None)
    else:
        os.environ["SKILL_CONCIERGE_HARNESS"] = _saved_cc
    # Path-marker fallback: a script under .commandcode/ without the env var must
    # still resolve to commandcode (ADR-0038 SessionStart hooks run without the
    # mod's env). Monkey-patch __file__ to a fake .commandcode path.
    import types as _types  # local import so selftest stays stdlib
    _orig_file = __file__
    try:
        globals()["__file__"] = "/tmp/.commandcode/hooks/scripts/doctrine.py"
        os.environ.pop("SKILL_CONCIERGE_HARNESS", None)
        os.environ.pop("OMPCODE", None)
        os.environ.pop("ZCODE_PLUGIN_ROOT", None)
        if _harness_adapt(_sample) == _sample:
            bad.append("commandcode marker: .commandcode path must trigger the commandcode rewrite")
        elif "mcp__skill-search__search_skills" not in _harness_adapt(_sample):
            bad.append("commandcode marker: path fallback must yield the bare tool name")
    finally:
        globals()["__file__"] = _orig_file
        if _saved_cc is None:
            os.environ.pop("SKILL_CONCIERGE_HARNESS", None)
        else:
            os.environ["SKILL_CONCIERGE_HARNESS"] = _saved_cc

    # ZCode (ADR-0042): NO rewrite — the Claude-default rendering is already ZCode-correct
    # (identical flattened plugin MCP tool id + plugin:skill alias), so an explicit zcode
    # harness must return the doctrine byte-identical. Pin it so a future rewrite branch
    # cannot silently mangle the zcode rendering.
    _saved_z = os.environ.get("SKILL_CONCIERGE_HARNESS")
    os.environ["SKILL_CONCIERGE_HARNESS"] = "zcode"
    try:
        if _harness_adapt(_sample) != _sample:
            bad.append("zcode adapt: SKILL_CONCIERGE_HARNESS=zcode must leave the doctrine "
                       "byte-identical (claude-default rendering is zcode-correct)")
    finally:
        if _saved_z is None:
            os.environ.pop("SKILL_CONCIERGE_HARNESS", None)
        else:
            os.environ["SKILL_CONCIERGE_HARNESS"] = _saved_z

    if bad:
        print("doctrine --selftest FAIL:")
        for b in bad:
            print("  " + b)
        return 1
    print("doctrine --selftest OK: subagent(agent_id) suppressed + top-level/persona(agent_type)/"
          "malformed/empty all inject (fail toward injection) + flag-off byte-identical"
          " + omp harness adaptation")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    sys.exit(main())
