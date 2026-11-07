"""skill-concierge — Hermes Agent adapter (ADR-0100).

Hermes Agent's governance vehicle is a **user plugin** (`~/.hermes/plugins/<name>/` with a
`plugin.yaml` manifest and an `__init__.py` exposing `register(ctx)`). Hermes fires plugin hooks in
BOTH the CLI and the gateway (unlike its `~/.hermes/hooks/` gateway-only system), which is what
makes it a first-class harness here rather than a partial one.

Hook mapping — Claude Code parity, one row per gate the reference harness has:

| Claude Code            | Hermes                                        | script                |
|------------------------|-----------------------------------------------|-----------------------|
| SessionStart           | `pre_llm_call` on `is_first_turn`             | `doctrine.py`         |
| SessionStart self-heal | `on_session_start`                            | `auto_*.py` (detached)|
| UserPromptSubmit       | `pre_llm_call` every turn                     | `enforcer.py`         |
| UserPromptSubmit row   | `pre_llm_call` every turn                     | `ledger.py`           |
| PreToolUse(Skill)      | `pre_tool_call` on `skill_view`               | `skill_guard.py`      |
| PostToolUse row        | `post_tool_call`                              | `ledger.py`           |
| PostToolUse context    | `transform_tool_result`                       | `skill_exclusions.py` |

Two shapes are Hermes-specific and worth naming, because both differ from every other adapter:

1. **`pre_llm_call` returns CONTEXT, not a transcript append.** A non-empty string (or
   `{"context": ...}`) is appended to the current turn's user message. That is the exact
   equivalent of Claude Code's `additionalContext`, and it is cache-safe: the system prompt is
   never touched (Hermes invariant — never break prompt caching).
2. **`post_tool_call` cannot return anything** (observer). The "not for" echo therefore rides
   `transform_tool_result`, which replaces the model-bound result *after* `post_tool_call` — the
   same ordering Claude Code gives PostToolUse `additionalContext`, expressed the way Hermes
   expresses it.

Everything here is fail-open on purpose. Hermes abandons a hook that blocks past
`plugins.hook_callback_timeout` (30 s default), and a `pre_tool_call` that times out is treated as
a BLOCK — so the guard's own subprocess is bounded well under that, and any exception returns
"no directive" instead of a block.

Scripts are invoked through `sys.executable` (the interpreter Hermes itself runs on) rather than a
PATH lookup: the gateway is a launchd service with no shell rc, and a leaked PYTHONPATH has
already shadowed a child interpreter's own site-packages on this machine (scrubbed in
`_env()` below).
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
from pathlib import Path

log = logging.getLogger("plugins.skill-concierge")

HARNESS = "hermes"

# Timeouts, milliseconds->seconds. The enforcer window is deliberately the Command Code / DSH
# budget (ADR-0079): the Jev router gets ENFORCER_JEV_BUDGET=1.6 s inside a 2.5 s kill window, so a
# slow tier is skipped instead of stalling the turn. Everything else is a local file read.
ENFORCER_TIMEOUT = 2.5
DOCTRINE_TIMEOUT = 5.0
GUARD_TIMEOUT = 2.0
EXCLUSIONS_TIMEOUT = 3.0
LEDGER_TIMEOUT = 5.0

# The skill-load tool. Hermes serves skills through `skill_view` (`tools/skills_tool.py`), whose
# name parameter is `name` — the same lane Claude Code calls `Skill` and DSH calls `skill`.
SKILL_LOAD_TOOL = "skill_view"


def _plugin_root() -> Path:
    """This checkout's root.

    Ladder: explicit `SKILL_CONCIERGE_ROOT` > the plugin's own resolved location. The installer
    symlinks `~/.hermes/plugins/skill-concierge` at `<checkout>/adapters/hermes/plugin`, so
    resolving `__file__` (which follows the symlink) puts the checkout three parents up. The
    `.hermes` path marker in `hooks/scripts/harness.py` covers the other direction.
    """
    env = os.environ.get("SKILL_CONCIERGE_ROOT", "").strip()
    if env and (Path(env) / "hooks" / "scripts" / "enforcer.py").is_file():
        return Path(env)
    try:
        here = Path(__file__).resolve()
        for cand in here.parents:
            if (cand / "hooks" / "scripts" / "enforcer.py").is_file():
                return cand
        return here.parent
    except (OSError, RuntimeError):
        return Path(".")


PLUGIN_ROOT = _plugin_root()
SCRIPTS = PLUGIN_ROOT / "hooks" / "scripts"
SELF_HEAL = ("auto_reindex.py", "auto_overrides.py", "auto_flywheel.py", "auto_promote.py")


def _env(extra=None) -> dict:
    """Child environment: the harness stamp, minus the two leaked-interpreter variables.

    PYTHONPATH/PYTHONHOME shadow a child interpreter's own site-packages (measured on this
    machine: the Hermes venv's pydantic reached a pyenv python and broke `import`), and every
    script here is stdlib-only, so neither is ever needed.
    """
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env["SKILL_CONCIERGE_HARNESS"] = HARNESS
    if extra:
        env.update(extra)
    return env


def _python() -> str:
    """The interpreter Hermes runs on — never a PATH lookup (the gateway has no shell rc)."""
    return sys.executable or "python3"


def _run(script: str, payload: dict, timeout: float, extra_env=None) -> dict:
    """Run one hook script with a Claude-hook-shaped payload on stdin; return its JSON object.

    Returns {} on any failure — a missing checkout, a non-zero exit, a timeout, or unparseable
    output. Callers treat {} as "no directive", which is the fail-open direction for every gate.
    """
    path = SCRIPTS / script
    try:
        if not path.is_file():
            return {}
        proc = subprocess.run(
            [_python(), str(path)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_env(extra_env),
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return {}
        out = json.loads(proc.stdout)
        return out if isinstance(out, dict) else {}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}


def _context(out: dict) -> str:
    """`hookSpecificOutput.additionalContext` out of a script's response, or ""."""
    hso = out.get("hookSpecificOutput") if isinstance(out, dict) else None
    ctx = hso.get("additionalContext") if isinstance(hso, dict) else None
    return ctx if isinstance(ctx, str) and ctx.strip() else ""


def _fire(script: str, payload: dict, timeout: float = LEDGER_TIMEOUT) -> None:
    """Fire-and-forget: telemetry and maintenance never hold a turn."""
    def work():
        _run(script, payload, timeout)
    try:
        threading.Thread(target=work, name=f"skill-concierge-{script}", daemon=True).start()
    except (RuntimeError, OSError):
        pass


def _fire_detached(script: str) -> None:
    """Launch one self-heal script without waiting for it (the script throttles itself)."""
    path = SCRIPTS / script
    try:
        if not path.is_file():
            return
        subprocess.Popen(
            [_python(), str(path)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=_env(),
            start_new_session=True,
        )
    except (OSError, ValueError):
        pass


def _prompt_text(user_message) -> str:
    """The typed prompt from Hermes's `user_message`, which is a `str` for a text turn and a list
    of content parts for a multimodal one (exactly as sent, before any skill injection)."""
    try:
        if isinstance(user_message, str):
            return user_message.strip()
        if isinstance(user_message, list):
            for part in user_message:
                if isinstance(part, dict) and part.get("type") == "text":
                    text = part.get("text")
                    if isinstance(text, str) and text.strip():
                        return text.strip()
    except (TypeError, ValueError):
        pass
    return ""


def _skill_load_payload(tool_name: str, args) -> dict | None:
    """The ledger/echo payload for a skill load or a skill-search call, else None.

    `skill_view` is Hermes's Skill lane. The MCP tools keep their bridged names
    (`mcp_skill_search_search_skills`, `mcp_skill_search_get_skill` at the server named
    `skill-search`), so the regexes match the server and tool segments independently of the
    separator Hermes folds them with.
    """
    name = str(tool_name or "")
    params = args if isinstance(args, dict) else {}
    if name == SKILL_LOAD_TOOL:
        return {"tool_name": "Skill", "tool_input": {"skill": params.get("name", "")}}
    if name.startswith("mcp_") and "skill" in name:
        if name.endswith("get_skill") or name.endswith("search_skills"):
            return {"tool_name": name, "tool_input": params}
    return None


def register(ctx):
    """Hermes plugin entry point. Registers five hooks; nothing else is touched."""
    doctrine_sessions: set = set()   # sessions already given the standing order
    subagent_sessions: set = set()   # session ids seen with a parent (delegate_task children)

    # ── 1. Session start: the standing order, then the self-heal scripts ────────────────────────
    def on_session_start(session_id: str = "", **kwargs):
        try:
            for script in SELF_HEAL:
                _fire_detached(script)
        except Exception:  # noqa: BLE001 — a maintenance script must never fail a session
            log.debug("skill-concierge: self-heal dispatch failed", exc_info=True)

    # ── 2. Every turn: doctrine (first turn only) + the semantic enforcer ───────────────────────
    def pre_llm_call(session_id: str = "", user_message=None, is_first_turn: bool = False,
                     parent_session_id: str = "", **kwargs):
        try:
            if parent_session_id:
                # ADR-0020 parity: a subagent session gets no doctrine, no mandate and no turn
                # row. Remembered so its tool calls are stamped as subagent rows below.
                if session_id:
                    subagent_sessions.add(session_id)
                return None

            chunks = []
            if is_first_turn and session_id not in doctrine_sessions:
                doctrine = _context(_run(
                    "doctrine.py",
                    {"hook_event_name": "SessionStart", "session_id": session_id},
                    DOCTRINE_TIMEOUT,
                ))
                if doctrine:
                    chunks.append(doctrine.strip())
                    doctrine_sessions.add(session_id)

            prompt = _prompt_text(user_message)
            if prompt:
                _fire("ledger.py", {"hook_event_name": "UserPromptSubmit", "session_id": session_id,
                                    "prompt": prompt, "harness": HARNESS})
                context = _context(_run(
                    "enforcer.py",
                    {"hook_event_name": "UserPromptSubmit", "session_id": session_id,
                     "prompt": prompt},
                    ENFORCER_TIMEOUT,
                    {"ENFORCER_JEV_BUDGET": "1.6"},
                ))
                if context:
                    chunks.append(context.strip())

            if not chunks:
                return None
            return {"context": "\n\n".join(chunks)}
        except Exception:  # noqa: BLE001 — never block a turn
            log.debug("skill-concierge: pre_llm_call failed", exc_info=True)
            return None

    # ── 3. Blocklist: the user-ordered disable tier, enforced at invocation (ADR-0046) ────────
    def pre_tool_call(tool_name: str = "", args=None, task_id: str = "", **kwargs):
        try:
            if tool_name != SKILL_LOAD_TOOL:
                return None
            params = args if isinstance(args, dict) else {}
            out = _run(
                "skill_guard.py",
                {"hook_event_name": "PreToolUse", "tool_name": "Skill",
                 "tool_input": {"skill": params.get("name", "")}, "session_id": task_id},
                GUARD_TIMEOUT,
            )
            hso = out.get("hookSpecificOutput") if isinstance(out, dict) else None
            if not isinstance(hso, dict) or hso.get("permissionDecision") != "deny":
                return None
            # Hermes's pre_tool_call block shape; `message` is what the model is told.
            return {"action": "block",
                    "message": str(hso.get("permissionDecisionReason") or "blocked by skill-concierge")}
        except Exception:  # noqa: BLE001 — a broken guard must never wedge a tool call
            log.debug("skill-concierge: pre_tool_call failed", exc_info=True)
            return None

    # ── 4. Skill loads land in the shared ledger (PostToolUse parity) ──────────────────────────
    def post_tool_call(tool_name: str = "", args=None, result=None, session_id: str = "",
                       task_id: str = "", status: str = "", **kwargs):
        try:
            if status and status != "ok":
                # A blocked or failed call is not a use — Claude Code fires no PostToolUse for one.
                return None
            load = _skill_load_payload(tool_name, args)
            if not load:
                return None
            sid = session_id or task_id
            payload = {"hook_event_name": "PostToolUse", "session_id": sid, "harness": HARNESS,
                       "tool_response": result, **load}
            if sid and sid in subagent_sessions:
                payload["agent_id"] = sid      # the ledger stamps subagent rows `sub`
            _fire("ledger.py", payload)
        except Exception:  # noqa: BLE001 — telemetry only
            log.debug("skill-concierge: post_tool_call failed", exc_info=True)

    # ── 5. The "not for" echo, appended to the loaded body (PostToolUse context parity) ────────
    def transform_tool_result(tool_name: str = "", args=None, result=None, session_id: str = "",
                              **kwargs):
        try:
            load = _skill_load_payload(tool_name, args)
            if not load or str(load["tool_name"]).endswith("search_skills"):
                return None      # a search row carries no skill body to echo
            echo = _context(_run(
                "skill_exclusions.py",
                {"hook_event_name": "PostToolUse", "session_id": session_id, "harness": HARNESS,
                 "tool_response": result, **load},
                EXCLUSIONS_TIMEOUT,
            ))
            if not echo:
                return None
            body = result if isinstance(result, str) else json.dumps(result)
            return f"{body}\n\n{echo.strip()}"
        except Exception:  # noqa: BLE001 — never corrupt a tool result
            log.debug("skill-concierge: transform_tool_result failed", exc_info=True)
            return None

    ctx.register_hook("on_session_start", on_session_start)
    ctx.register_hook("pre_llm_call", pre_llm_call)
    ctx.register_hook("pre_tool_call", pre_tool_call)
    ctx.register_hook("post_tool_call", post_tool_call)
    ctx.register_hook("transform_tool_result", transform_tool_result)
