"""
skill-concierge — skill-invocation ledger (append-only telemetry).

Registered for two events (see ../hooks.json):
  • UserPromptSubmit → logs a `turn` per substantive prompt, or `manual` when the
    user typed a `/skill` (captured here because the slash path never reaches
    PostToolUse as a tool call).
  • PostToolUse (matcher Skill|mcp__skill-search__search_skills) → logs `auto`
    (Claude invoked a skill) or `search` (Claude called the semantic retriever).

Design contract (mirrors the sibling enforcement hooks):
  • FAIL-SILENT — any error exits 0; telemetry must never break or block a turn.
  • ADDITIVE-ONLY — never writes hook-decision output; just appends to the ledger.
  • COMPOUNDING — one append-only JSONL `.log`; no rotation/cap/delete here
    (lifecycle is logman's job downstream; run it with RETENTION_DAYS=0).

The PostToolUse `tool_input` schema is tool-dependent and the Skill tool's field
name is NOT documented, so we DO NOT assume one: we record the input KEYS (to learn
the real field from live data) plus a best-effort name from likely candidates —
without logging arbitrary input values.
"""
import json
import os
import sys
import time
from pathlib import Path

LOG_DIR = Path(os.environ.get(
    "SKILL_CONCIERGE_LOG", Path.home() / ".claude" / "skill-concierge" / "logs"))
LEDGER = LOG_DIR / "skill-invocation-ledger.log"
# Suffix matches; tolerate the mcp__[plugin_...]__ namespace prefix (drift-proof — the bare name
# broke when the tool got plugin-namespaced) AND Codex's underscore normalization of the server
# name (a Codex session exposes mcp__skill_search__search_skills — hyphen flattened; observed
# live 2026-08-24). Codex fires no PostToolUse today, so the underscore forms are dormant — but
# without them, capture would silently miss the day it does (the two-layer D3 from the Codex
# revalidation). OMP surfaces the tools as `skill-concierge:skill-search/search_skills`
# (namespaced plugin:server/tool, colon+slash separators) — the colon/slash suffixes below ride
# the same endswith matching (the mcp__/plugin prefixes are all on the LEFT, never the suffix).
SEARCH_TOOLS = ("skill-search__search_skills", "skill_search__search_skills",
                "skill-search/search_skills")
GET_TOOLS = ("skill-search__get_skill", "skill_search__get_skill",
             "skill-search/get_skill")
_NAME_KEYS = ("skill", "command", "name", "skill_name", "subagent_type")


def _append(ev: dict) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with LEDGER.open("a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001, S110 (fail-silent telemetry boundary)
        pass  # fail-silent: a telemetry write must never surface to the turn


def main() -> int:
    try:
        raw = sys.stdin.read()
        d = json.loads(raw) if raw.strip() else {}
        if not isinstance(d, dict):
            return 0
        evt = d.get("hook_event_name", "")
        sid = d.get("session_id", "")
        t = round(time.time(), 3)
        # ADR-0020 positive proof: hooks firing inside a subagent call carry
        # `agent_id` (main-session hook input never does). Stamping auto/manual
        # events lets the enforcer's chain-hint tail-read and analyze.py exclude
        # subagent lanes instead of mixing them into the main session's chains.
        sub = bool(d.get("agent_id"))

        harness = d.get("harness") or os.environ.get("SKILL_CONCIERGE_HARNESS", "").strip().lower() or None

        if evt == "UserPromptSubmit":
            prompt = d.get("prompt") or ""
            s = prompt.strip()
            if not s:
                return 0  # empty prompt is not a turn — don't log noise
            if s.startswith("/"):
                # user-typed slash = manual /skill (or a built-in command)
                name = s[1:].split()[0] if len(s) > 1 else ""
                ev = {"t": t, "sid": sid, "ev": "manual", "name": name}
                if sub:
                    ev["sub"] = True
                if harness:
                    ev["harness"] = harness
                _append(ev)
            else:
                # turn boundary — lets the analyzer segment uptake per prompt.
                # Log the STRIPPED prompt so analyze.py can join this `turn` to
                # the enforcer's `offer` event by (sid, q) — the enforcer logs q
                # stripped, so an unstripped q here would break the join for any
                # whitespace-bearing prompt and silently undercount hit@k.
                ev = {"t": t, "sid": sid, "ev": "turn", "q": s[:120]}
                if harness:
                    ev["harness"] = harness
                _append(ev)

        elif evt == "PostToolUse":
            tool = d.get("tool_name", "")
            if tool in ("Skill", "activate_skill"):
                ti = d.get("tool_input", {})
                name, keys = "", []
                if isinstance(ti, dict):
                    keys = list(ti.keys())
                    for k in _NAME_KEYS:
                        if isinstance(ti.get(k), str):
                            name = ti[k]
                            break
                ev = {"t": t, "sid": sid, "ev": "auto",
                      "name": name, "input_keys": keys}
                if sub:
                    ev["sub"] = True
                if harness:
                    ev["harness"] = harness
                _append(ev)
            elif tool == "read":
                # OMP activation lane: OMP consumes skills via the read tool on
                # `skill://<name>` URLs (no Skill-tool call fires, and the OMP MCP surface is
                # only the search/get_skill pair — the body pull is a read). Name = the segment
                # after `skill://` up to the first `/` (matches the skill:// URL shape OMP uses
                # for both `skill://<name>` and namespaced `skill://plugin:name` forms). This
                # lane also benefits any harness where the agent reads skill:// paths directly.
                ti = d.get("tool_input", {})
                path = ti.get("path", "") if isinstance(ti, dict) else ""
                name = path.split("skill://", 1)[1].split("/", 1)[0] \
                    if isinstance(path, str) and path.startswith("skill://") else ""
                ev = {"t": t, "sid": sid, "ev": "auto", "name": name}
                if sub:
                    ev["sub"] = True
                if harness:
                    ev["harness"] = harness
                _append(ev)
            elif tool.endswith(SEARCH_TOOLS):
                ev = {"t": t, "sid": sid, "ev": "search"}
                if harness:
                    ev["harness"] = harness
                _append(ev)
            elif tool.endswith(GET_TOOLS):
                # ADR-0031 external-take leg: a get_skill deep pull is how an
                # external catalog skill is consumed (read-inline). Log EVERY pull
                # with its name; whether the name is external (catalog alias
                # prefix) is classified downstream in analyze.py, so this row
                # stays useful for installed deep pulls too. Epoch-scoped like
                # all ledger metrics.
                ti = d.get("tool_input", {})
                name = ti.get("name", "") if isinstance(ti, dict) else ""
                ev = {"t": t, "sid": sid, "ev": "get_skill",
                      "name": name if isinstance(name, str) else ""}
                if sub:
                    ev["sub"] = True
                if harness:
                    ev["harness"] = harness
                _append(ev)
    except Exception:  # noqa: BLE001 (fail-silent hook boundary)
        return 0
    return 0


def _selftest() -> int:
    """Pin the event classification: a get_skill PostToolUse yields an `ev:get_skill`
    row with the pulled name (ADR-0031 external-take telemetry), a Skill call yields
    `auto`, a search yields `search`, and a slash prompt yields `manual`."""
    import io
    import tempfile
    global LEDGER, LOG_DIR
    saved = (LEDGER, LOG_DIR)
    rows = []
    try:
        with tempfile.TemporaryDirectory() as td:
            LOG_DIR = Path(td)
            LEDGER = LOG_DIR / "ledger.log"

            def feed(payload):
                sys.stdin = io.StringIO(json.dumps(payload))
                main()

            feed({"hook_event_name": "PostToolUse", "session_id": "t",
                  "tool_name": "mcp__x__skill-search__get_skill",
                  "tool_input": {"name": "antigravity:seo"}})
            feed({"hook_event_name": "PostToolUse", "session_id": "t",
                  "tool_name": "Skill", "tool_input": {"skill": "doctor"}})
            feed({"hook_event_name": "PostToolUse", "session_id": "t",
                  "tool_name": "mcp__x__skill-search__search_skills"})
            # Codex underscore normalization (server name hyphen flattened by the harness,
            # observed live 2026-08-24): must classify identically to the hyphen forms.
            feed({"hook_event_name": "PostToolUse", "session_id": "t",
                  "tool_name": "mcp__skill_search__search_skills"})
            feed({"hook_event_name": "PostToolUse", "session_id": "t",
                  "tool_name": "mcp__skill_search__get_skill",
                  "tool_input": {"name": "mattpocock-skills:tdd"}})
            # OMP MCP surface: namespaced plugin:server/tool (colon+slash) must classify
            # identically to the mcp__ forms.
            feed({"hook_event_name": "PostToolUse", "session_id": "t",
                  "tool_name": "skill-concierge:skill-search/search_skills"})
            feed({"hook_event_name": "PostToolUse", "session_id": "t",
                  "tool_name": "skill-concierge:skill-search/get_skill",
                  "tool_input": {"name": "claude-hud:theme"}})
            # OMP activation lane: skills are consumed via the read tool on skill:// URLs.
            feed({"hook_event_name": "PostToolUse", "session_id": "t",
                  "tool_name": "read", "tool_input": {"path": "skill://doctor"}})
            # A namespaced skill:// URL (plugin:skill form — OMP namespaced skills carry a
            # colon, and a trailing /sub path must not leak past the first segment).
            feed({"hook_event_name": "PostToolUse", "session_id": "t",
                  "tool_name": "read", "tool_input": {"path": "skill://memsearch/extra"}})
            feed({"hook_event_name": "UserPromptSubmit", "session_id": "t",
                  "prompt": "/keep-on list"})
            rows = [json.loads(l) for l in LEDGER.read_text().splitlines()]
    finally:
        sys.stdin = sys.__stdin__
        LEDGER, LOG_DIR = saved
    evs = [(r["ev"], r.get("name")) for r in rows]
    want = [("get_skill", "antigravity:seo"), ("auto", "doctor"),
            ("search", None), ("search", None),
            ("get_skill", "mattpocock-skills:tdd"),
            ("search", None), ("get_skill", "claude-hud:theme"),
            ("auto", "doctor"), ("auto", "memsearch"),
            ("manual", "keep-on")]
    if evs != want:
        print(f"ledger --selftest FAIL: {evs!r} != {want!r}")
        return 1
    print("ledger --selftest OK: get_skill/auto/search/manual classification"
          " + omp namespaced tools + skill:// read activation")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    sys.exit(main())
