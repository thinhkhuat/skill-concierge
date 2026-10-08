"""
skill-concierge — skill-invocation ledger (append-only telemetry).

Registered for two events (see ../hooks.json):
  • UserPromptSubmit → logs a `turn` per substantive prompt, or `manual` when the
    user typed a `/skill` (captured here because the slash path never reaches
    PostToolUse as a tool call).
  • PostToolUse (matcher `Skill|mcp__.*skill[-_]search__(search_skills|get_skill)`) → logs
    `auto` (a skill was invoked: the Skill tool, an adapter's `activate_skill` / `skill`, or
    OMP's `read` of `skill://<name>`), `search` (the semantic retriever) or `get_skill` (a
    deep pull).
Adapters also send `ConciergeOffer` (ADR-0087): the Cline plugin's offer row, appended as given.

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
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from harness import running_harness  # the detector enforcer, doctrine and ledger share
except Exception:  # noqa: BLE001 - fail-silent: no detector, no row
    sys.exit(0)


def _menu_name(name: str, harness: str) -> tuple:
    """(name as the menu shows it, typed form or None). A bare `/bro` or Skill-tool `bro` that
    Claude Code resolves to the one plugin skill of that name is recorded as `pstack:bro`, with
    the typed form kept beside it, so the 🔥 count lands on the menu's row (ADR-0083, 0.61.2).
    Claude Code's plugin registry only: other harnesses keep the name as given. Fail-open."""
    if (harness or "claude") != "claude":
        return name, None
    try:
        from skill_names import canonical
        full = canonical(name)
    except Exception:  # noqa: BLE001 — telemetry must never break a turn
        return name, None
    return (full, name) if full != name else (name, None)

LOG_DIR = Path(os.environ.get(
    "SKILL_CONCIERGE_LOG", Path.home() / ".claude" / "skill-concierge" / "logs"))
LEDGER = LOG_DIR / "skill-invocation-ledger.log"
# Suffix matches; tolerate the mcp__[plugin_...]__ namespace prefix (drift-proof — the bare name
# broke when the tool got plugin-namespaced) AND Codex's underscore normalization of the server
# name (a Codex session exposes mcp__skill_search__search_skills — hyphen flattened; observed
# live 2026-08-24). Codex fires no PostToolUse today, so the underscore forms are dormant — but
# without them, capture would silently miss the day it does (the two-layer D3 from the Codex
# revalidation). OMP flattens the WHOLE mangled name to single underscores — observed live
# 2026-08-26 as `mcp__skill_concierge_skill_search_search_skills` (colon AND hyphens AND the
# server/tool separator all become `_`), so neither the slash form nor the double-underscore
# form matches; the single-underscore suffixes below are the ones that actually catch it.
SEARCH_TOOLS = ("skill-search__search_skills", "skill_search__search_skills",
                "skill-search/search_skills", "skill_search_search_skills",
                "skill-search_search_skills")
GET_TOOLS = ("skill-search__get_skill", "skill_search__get_skill",
             "skill-search/get_skill", "skill_search_get_skill",
             "skill-search_get_skill")
# `id` is OpenCode's native skill-tool input key ({"id": "<skill>"}) — the others are the
# Claude Code Skill tool / command / subagent shapes seen live.
_NAME_KEYS = ("skill", "command", "name", "skill_name", "subagent_type", "id")


def _native_harness() -> str:
    """The stamp when neither the payload nor SKILL_CONCIERGE_HARNESS names the harness: ZCode
    (ADR-0042) and DSH (ADR-0050) from their native signals, via the shared detector. Every other
    harness, Claude included, keeps its rows unstamped."""
    harness = running_harness(__file__)
    return harness if harness in ("zcode", "dsh") else ""


def _log(ev: dict, sub: bool, harness: str) -> None:
    """Stamp the subagent flag and harness when set, then append."""
    if sub:
        ev["sub"] = True
    if harness:
        ev["harness"] = harness
    _append(ev)


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

        harness = (d.get("harness")
                   or os.environ.get("SKILL_CONCIERGE_HARNESS", "").strip().lower()
                   or _native_harness())

        if evt == "UserPromptSubmit":
            prompt = d.get("prompt") or ""
            s = prompt.strip()
            if not s:
                return 0  # empty prompt is not a turn — don't log noise
            if s.startswith("/"):
                # user-typed slash = manual /skill (or a built-in command)
                name = s[1:].split()[0] if len(s) > 1 else ""
                name, typed = _menu_name(name, harness)
                ev = {"t": t, "sid": sid, "ev": "manual", "name": name}
                if typed:
                    ev["typed"] = typed
                _log(ev, sub, harness)
            else:
                # turn boundary — lets the analyzer segment uptake per prompt.
                # Log the STRIPPED prompt so analyze.py can join this `turn` to
                # the enforcer's `offer` event by (sid, q) — the enforcer logs q
                # stripped, so an unstripped q here would break the join for any
                # whitespace-bearing prompt and silently undercount hit@k.
                _log({"t": t, "sid": sid, "ev": "turn", "q": s[:120]}, False, harness)

        elif evt == "PostToolUse":
            tool = d.get("tool_name", "")
            # "skill" (lowercase) is OpenCode's native skill tool (ADR-0085); the
            # others are the Claude Code / harness shapes seen live.
            if tool in ("Skill", "activate_skill", "skill"):
                ti = d.get("tool_input", {})
                name, keys = "", []
                if isinstance(ti, dict):
                    keys = list(ti.keys())
                    for k in _NAME_KEYS:
                        if isinstance(ti.get(k), str):
                            name = ti[k]
                            break
                name, typed = _menu_name(name, harness)
                ev = {"t": t, "sid": sid, "ev": "auto",
                      "name": name, "input_keys": keys}
                if typed:
                    ev["typed"] = typed
                _log(ev, sub, harness)
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
                _log(ev, sub, harness)
            elif tool.endswith(SEARCH_TOOLS):
                _log({"t": t, "sid": sid, "ev": "search"}, sub, harness)
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
                _log(ev, sub, harness)
        elif evt == "ConciergeOffer":
            # ADR-0087: the Cline plugin hands back the offer row of the menu the model actually
            # saw on its first call (`seen`), or a late full-pass row kept apart as `offer_late`.
            offer = d.get("offer")
            if isinstance(offer, dict) and offer.get("ev") in ("offer", "offer_late"):
                _append(offer)
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
            # a throwaway plugin registry: `bro` is one plugin's skill, `tdd` two plugins' (ambiguous),
            # `doctor` and `keep-on` none — so only `bro` may be recorded under its plugin name
            import skill_names
            for plugin, skill in (("pstack", "bro"), ("pstack", "tdd"), ("matt", "tdd")):
                d = Path(td) / plugin / "skills" / skill
                d.mkdir(parents=True)
                (d / "SKILL.md").write_text("---\nname: x\n---\n")
            (Path(td) / "reg.json").write_text(json.dumps({"plugins": {
                "pstack@m": [{"installPath": str(Path(td) / "pstack")}],
                "matt@m": [{"installPath": str(Path(td) / "matt")}]}}))
            _seams = (skill_names.REGISTRY, skill_names.SKILLS_ROOT)
            skill_names.REGISTRY, skill_names.SKILLS_ROOT = Path(td) / "reg.json", Path(td) / "personal"

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
            feed({"hook_event_name": "UserPromptSubmit", "session_id": "t", "prompt": "/bro say it plainly"})
            feed({"hook_event_name": "PostToolUse", "session_id": "t",
                  "tool_name": "Skill", "tool_input": {"skill": "tdd"}})
            feed({"hook_event_name": "UserPromptSubmit", "session_id": "t", "prompt": "/bro x",
                  "harness": "codex"})
            rows = [json.loads(l) for l in LEDGER.read_text().splitlines()]
            skill_names.REGISTRY, skill_names.SKILLS_ROOT = _seams
    finally:
        sys.stdin = sys.__stdin__
        LEDGER, LOG_DIR = saved
    evs = [(r["ev"], r.get("name")) for r in rows]
    want = [("get_skill", "antigravity:seo"), ("auto", "doctor"),
            ("search", None), ("search", None),
            ("get_skill", "mattpocock-skills:tdd"),
            ("search", None), ("get_skill", "claude-hud:theme"),
            ("auto", "doctor"), ("auto", "memsearch"),
            ("manual", "keep-on"),
            ("manual", "pstack:bro"),        # unique plugin skill -> the menu's name
            ("auto", "tdd"),                 # two plugins own it -> left as typed
            ("manual", "bro")]               # another harness -> Claude's registry does not apply
    if [r.get("typed") for r in rows[-3:]] != ["bro", None, None]:
        print(f"ledger --selftest FAIL: typed form not kept: {rows[-3:]!r}")
        return 1
    if evs != want:
        print(f"ledger --selftest FAIL: {evs!r} != {want!r}")
        return 1
    print("ledger --selftest OK: get_skill/auto/search/manual classification"
          " + omp namespaced tools + skill:// read activation + bare plugin names recorded as the menu shows them")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    sys.exit(main())
