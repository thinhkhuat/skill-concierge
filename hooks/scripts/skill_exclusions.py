#!/usr/bin/env python3
"""skill-concierge — echo a loaded skill's own exclusion lines back to the agent (PostToolUse(Skill)).

Invariant: when the agent loads a skill whose SKILL.md says what it is NOT for — a description
sentence opening "Not for…" / "Don't use…", or the bullets under a "Don't use for" / "Do not use
for" / "When not to use" / "Not for" header — those lines are repeated as additionalContext right
after the load, next to the decision they bear on. The agent then re-rules in the open instead of
switching procedure silently while a `USING:` line it no longer believes stays on the record.
This is deterministic: it reads the file, it never asks the agent to report on itself.

Resolution: the loaded text itself when the payload's `tool_response` carries it (a get_skill
body, an OMP `read`, an adapter-forwarded result) — so the echo quotes the copy the agent
actually read, never a same-named copy from another root. Else the index payload path (Qdrant
retrieve by the engine's point id), else a bare name under any harness's personal skill root or
the matching <cwd> project root. Silent when nothing
is found, when the skill excludes nothing, and on every error — a hook failure must never block
or noise a turn.

Input is the Claude-format PostToolUse payload. Claude Code and ZCode send it natively through
hooks.json; the OMP, Command Code, Cline and DSH adapters send the SAME payload they build for
ledger.py, so the load shapes read here are ledger's: the Skill tool (`Skill`, Command Code's
`activate_skill`), OMP's `read` of a `skill://<name>` root, and the skill-search get_skill tool
under every harness's mangled name. Stdlib only, Python 3.9-safe at import time.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from ledger import GET_TOOLS, _NAME_KEYS  # the one place load shapes are decided
except Exception:  # sibling missing, or ledger's annotations break a 3.9 system python
    _NAME_KEYS = ("skill", "command", "name", "skill_name")
    GET_TOOLS = ("skill-search__get_skill", "skill_search__get_skill",
                 "skill-search/get_skill", "skill_search_get_skill")

QDRANT_URL = os.environ.get("SKILL_QDRANT_URL", "http://localhost:6333").rstrip("/")
COLLECTION = os.environ.get("SKILL_COLLECTION", "claude_skills")
try:
    QDRANT_TIMEOUT_S = float(os.environ.get("ENFORCER_QDRANT_TIMEOUT", "0.25"))
except ValueError:
    QDRANT_TIMEOUT_S = 0.25
# Personal skill roots per harness, then the same dot-dirs under the cwd — used only when the
# index cannot answer (Qdrant down): a non-Claude session's skill must still echo.
_HOME_ROOTS = (".claude/skills", ".codex/skills", ".commandcode/skills", ".omp/agent/skills",
               ".omp/agent/managed-skills", ".zcode/skills", ".agents/skills", ".ohdsh/skills",
               ".dsh/skills", ".cline/data/settings/skills")
_CWD_ROOTS = (".claude/skills", ".codex/skills", ".commandcode/skills", ".omp/skills",
              ".zcode/skills", ".agents/skills", ".dsh/skills", ".cline/skills")
try:
    FALLBACK_ROOTS = ([Path.home() / r for r in _HOME_ROOTS]
                      + [Path.cwd() / r for r in _CWD_ROOTS])
except (OSError, RuntimeError):   # deleted cwd / no home: the index path still resolves
    FALLBACK_ROOTS = []
MAX_LINES = 6
MAX_CHARS = 200

_HEADER_RE = re.compile(r"^#{1,6}\s")
_EXCL_HEADER_RE = re.compile(r"^#{1,6}\s*(don'?t use for|do not use for|when not to use|not for)\b",
                             re.I)
_BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(.*\S)")
# Bold-label form: "**When NOT to use:** text", or a "**NOT for:**" line followed by bullets.
_EXCL_LABEL_RE = re.compile(
    r"^\s*\*\*(when not to use|not for|do(?:n'?t| not) use(?: (?:for|when))?)\s*:?\s*\*\*:?\s*(.*)$",
    re.I)
_ANY_LABEL_RE = re.compile(r"^\s*\*\*[^*]+\*\*:?")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_DESC_EXCL_RE = re.compile(r"^(not for|don'?t use|do not use)\b", re.I)
_SENTENCE_RE = re.compile(r"(?<=[.;!?])\s+")


def _point_id(name: str) -> str:
    """Same id the engine writes (server._point_id)."""
    return str(uuid.UUID(hashlib.md5(name.encode()).hexdigest()))


def _qdrant_path(name: str) -> str | None:
    try:
        req = urllib.request.Request(
            f"{QDRANT_URL}/collections/{COLLECTION}/points",
            data=json.dumps({"ids": [_point_id(name)], "with_payload": ["path"]}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=QDRANT_TIMEOUT_S) as resp:
            rows = json.loads(resp.read()).get("result") or []
        return (rows[0].get("payload") or {}).get("path") if rows else None
    except Exception:
        return None


def _resolve(name: str) -> Path | None:
    p = _qdrant_path(name)
    if p and Path(p).is_file():
        return Path(p)
    if ":" in name:
        return None  # namespaced names live in plugin caches; only the index knows the path
    for root in FALLBACK_ROOTS:
        cand = root / name / "SKILL.md"
        if cand.is_file():
            return cand
    return None


def _split_frontmatter(text: str) -> tuple[str, str]:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[3:end], text[end + 4:]
    return "", text


def _description(front: str) -> str:
    lines = front.splitlines()
    for i, ln in enumerate(lines):
        m = re.match(r"^description:\s*(.*)$", ln)
        if not m:
            continue
        val = m.group(1).strip()
        if val in ("|", ">", "|-", ">-", ""):
            val = " ".join(x.strip() for x in lines[i + 1:] if x.startswith((" ", "\t")))
        return val.strip().strip("\"'")
    return ""


def exclusions(text: str) -> list:
    """The skill's own "not for" lines, capped at MAX_LINES × MAX_CHARS."""
    front, body = _split_frontmatter(text.replace("\u2019", "'"))   # curly apostrophes
    out = [s.strip() for s in _SENTENCE_RE.split(_description(front)) if _DESC_EXCL_RE.match(s.strip())]
    in_section = in_fence = label_section = False
    label_items = 0
    for ln in body.splitlines():
        if _FENCE_RE.match(ln):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if _HEADER_RE.match(ln):
            in_section, label_section = bool(_EXCL_HEADER_RE.match(ln)), False
            continue
        lab = _EXCL_LABEL_RE.match(ln)
        if lab:
            in_section = label_section = True
            label_items = 0
            if lab.group(2).strip():
                out.append(lab.group(2).strip())
                label_items = 1
            continue
        if _ANY_LABEL_RE.match(ln):
            in_section = False
            continue
        if in_section:
            m = _BULLET_RE.match(ln)
            if m:
                out.append(m.group(1))
                label_items += 1
            elif label_section and (ln.strip() or label_items):
                in_section = False   # a bold-label list ends at its first plain or blank line
    return [ln[:MAX_CHARS] for ln in out[:MAX_LINES]]


def loaded_skill(data) -> str:
    """The skill a PostToolUse payload just loaded, or "" when the call loaded none. A `read`
    counts only on a skill's root (`skill://<name>` or `.../SKILL.md`), never a sub-resource."""
    tool = data.get("tool_name") if isinstance(data, dict) else None
    ti = data.get("tool_input") if isinstance(data, dict) else None
    if not isinstance(tool, str) or not isinstance(ti, dict):
        return ""
    if tool == "read":
        path = ti.get("path")
        if not (isinstance(path, str) and path.startswith("skill://")):
            return ""
        name, _, rest = path[len("skill://"):].partition("/")
        return name.strip() if rest in ("", "SKILL.md") else ""
    if tool in ("Skill", "activate_skill") or tool.endswith(GET_TOOLS):
        name = next((ti[k] for k in _NAME_KEYS if isinstance(ti.get(k), str) and ti[k].strip()), "")
        return name.strip().lstrip("/")
    return ""


def _text_of(resp) -> str:
    """Flatten a tool response (a string, content blocks, or a {content|result|text} wrapper)."""
    if isinstance(resp, str):
        return resp
    if isinstance(resp, list):
        return "\n".join(_text_of(x) for x in resp)
    if isinstance(resp, dict):
        for key in ("content", "result", "text", "output"):
            if key in resp:
                return _text_of(resp[key])
    return ""


def main(raw: str) -> str | None:
    try:
        data = json.loads(raw)
        name = loaded_skill(data)
        if not name:
            return None
        loaded = _text_of(data.get("tool_response")).lstrip()
        if loaded.startswith("{") and '"error"' in loaded:
            try:
                if "error" in json.loads(loaded):   # a refused load (blocklisted / not found)
                    return None
            except ValueError:
                pass
        if loaded.startswith("---"):          # the SKILL.md the agent just read
            lines = exclusions(loaded)
        else:
            path = _resolve(name)
            lines = exclusions(path.read_text(encoding="utf-8")) if path else []
        if not lines:
            return None
        msg = (f"SKILL-EXCLUDES: the skill you just loaded ({name}) carries these exclusions: "
               + " • ".join(ln.rstrip(" .;") for ln in lines)
               + f". If this task matches one, re-rule now: a new USING: or SEARCH: line ending "
                 f"(re-rule: {name}), one sentence quoting the excluding line, and tell the user "
                 "you switched.")
        return json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                                  "additionalContext": msg}})
    except Exception:
        return None


if __name__ == "__main__":
    try:
        out = main(sys.stdin.read())
        if out:
            print(out)
    except Exception:
        pass
    sys.exit(0)
