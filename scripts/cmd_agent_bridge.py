#!/usr/bin/env python3
"""skill-concierge — the Command Code agent-definition bridge.

Command Code reads subagent definitions from `~/.commandcode/agents/*.md`, parses their frontmatter
its own way, and resolves the `tools:` allowlist against its OWN tool ids. A Claude Code agent file
names its tools the Claude Code way (`Read`, `Write`, `Edit`, `WebFetch`, `TodoWrite`, `Task(...)`),
and Command Code has no translation for those names: they are dropped in silence and the subagent
launches with whatever happened to match — in practice `glob` and `grep`, the two ids whose Claude
spelling coincides with Command Code's. A `fullstack-developer` delegate that is supposed to write
files and run builds starts unable to do either, with nothing reporting the loss.

Claude Code is the source of truth for these files and this machine shares them: `~/.commandcode/agents`
is a symlink to `~/.claude/agents`, so the corpus is deliberately one copy across every harness.
Rewriting a source is not an option — it would edit the Claude Code originals and any other harness
that reads them.

This module closes the gap the same way the colon-name skill bridge does: it MATERIALIZES a normalized
mirror of every agent into the directory Command Code actually scans, translating each copy's
frontmatter and the parts of its body that name tools or invoke delegation. Sources are hashed into
the mirror manifest and `verify` proves none of them changed.

Why a mirror and not a mod: Command Code's ModApi exposes `cmd.addSkillsPath()` for skills but no
agent-path seam of any kind, and agent discovery is a flat scan of `~/.commandcode/agents` (personal)
plus project directories, first-definition-of-a-name-wins. There is nothing to register, so the mirror
is written where Command Code already looks.

Rewrites applied to a copy, never to a source:
  • `tools:` (and `disallowedTools:`) ids are translated through TOOL_MAP; an id with no Command Code
    counterpart is dropped from the allowlist and REPORTED — never invented, never silently kept;
  • `model:` is kept when it is `inherit` or a plausible Command Code id, and reset to `inherit` with a
    warning otherwise (a Claude alias such as `sonnet` is not a Command Code id and would be dropped
    by the harness, silently changing the model);
  • a body that relies on delegation (`Task(<agent>)`) or peer messaging (`SendMessage`,
    `shutdown_request`) gets ONE explicit adapter note saying Command Code subagents cannot spawn
    subagents and have no peer-messaging tool, so that work happens inline. The note is inserted, not
    substituted for the author's prose: those sentences cannot be mechanically re-expressed without
    inventing behavior the harness does not have;
  • tool ids written as tokens in the body are renamed when the Claude name is unambiguous
    (`TaskCreate` -> `task_create`); single-word names that are also ordinary English (`Read`,
    `Write`, `Edit`) are left alone, because rewriting the verb would corrupt the prompt.

Commands: `build` (default), `verify`, `clean`, `list`. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

DEST_ENV = "AGENT_BRIDGE_DEST"
DEST_DEFAULT = Path.home() / ".commandcode" / "agents"
MANIFEST_NAME = "_agent_bridge.json"
MANIFEST_VERSION = 1
TEXT_SUFFIX = ".md"

# Command Code ignores a custom agent whose name one of these owns.
RESERVED = {"explore", "plan", "review", "general"}

# Command Code's own tool ids, as the `tools:` map decides them: an id with no Command Code
# counterpart is dropped from the allowlist and reported. `None` means "no Command Code tool does
# this job" — the entry names WHY, so a warning says something a reader can act on.
TOOL_MAP = {
    # search / read
    "Glob": ("glob", None),
    "Grep": ("grep", None),
    "Read": ("read_file", None),
    "LS": ("read_directory", None),
    # write
    "Write": ("write_file", None),
    "Edit": ("edit_file", None),
    "MultiEdit": ("edit_file", "Command Code has no batch editor: rewrite the call as sequential "
                              "`edit_file` edits (one old_string/new_string pair each)"),
    "NotebookEdit": ("write_file", "Command Code edits a notebook as a file; keep the .ipynb JSON "
                                   "well-formed when overwriting it"),
    # shell
    "Bash": ("shell_command", None),
    "BashOutput": ("shell_output", None),
    "KillBash": ("kill_shell", None),
    # web
    "WebFetch": ("web_fetch", None),
    "WebSearch": ("web_search", None),
    # work state
    "TaskCreate": ("task_create", None),
    "TaskGet": ("task_get", None),
    "TaskUpdate": ("task_update", None),
    "TaskList": ("task_list", None),
    "TaskOutput": ("shell_output", None),
    "TodoWrite": ("todo_write", "the `todos` built-in mod must be enabled (`cmd mods enable todos`) "
                                "or the model never sees this tool"),
    # no Command Code counterpart
    "SendMessage": (None, "Command Code subagents have no peer-messaging tool: report to the caller "
                          "in your final message instead"),
    "ListMcpResourcesTool": (None, "Command Code has no MCP-resource listing tool"),
    "ReadMcpResourceTool": (None, "Command Code has no MCP-resource reading tool"),
    "NotebookRead": (None, "Command Code reads a notebook through `read_file`"),
    "ExitPlanMode": (None, "Command Code subagents never run in plan mode"),
    "EnterPlanMode": (None, "Command Code subagents never run in plan mode"),
}

# `Task(<agent>)` is Claude Code's subagent-spawn syntax. Command Code removes the `agent` and
# `agent_output` tools from every subagent (delegation is one level deep), so the token cannot be
# translated into anything that works.
TASK_SPAWN_RE = re.compile(r"\bTask\(([A-Za-z][A-Za-z0-9_-]*)\)")

# Body tokens that are renamed when written as a tool. Restricted on purpose: a Claude tool name
# that is also an ordinary English word (`Read`, `Write`, `Edit`, `Bash`) is NOT rewritten, because
# the prompt says "Read the file" as often as it names the tool.
BODY_RENAMES = {camel: target for camel, (target, _why) in TOOL_MAP.items()
                if target and re.search(r"[a-z][A-Z]", camel)}

# Idioms whose sentences cannot be re-expressed mechanically: they describe a multi-agent protocol
# Command Code does not implement. Their presence is what triggers the adapter note.
PEER_IDIOMS = ("SendMessage", "shutdown_request", "teammate", "teammates")

# A plausible Command Code model id (`/model` ids: `claude-opus-4-8`, `moonshotai/kimi-k2.6`) — used
# only to decide whether a pinned model survives; anything else falls back to `inherit`, which is
# always correct because it follows the session model.
MODEL_OK_RE = re.compile(r"^(inherit|[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*"
                         r"|claude-[a-z0-9][a-z0-9.-]*|gpt-[a-z0-9][a-z0-9.-]*"
                         r"|zai-org/[A-Za-z0-9._-]+|deepseek-[a-z0-9.-]+|gemini-[a-z0-9.-]+)$")

ADAPTER_NOTE = (
    "[command-code adapter] This prompt was mirrored for Command Code by "
    "scripts/cmd_agent_bridge.py. Command Code subagents cannot spawn other subagents and have no "
    "peer-messaging tool: where the text below tells you to delegate through `Task(<agent>)`, to use "
    "`SendMessage`, or to answer a `shutdown_request`, do that work inline instead and report the "
    "result in your final message."
)


# ── frontmatter ───────────────────────────────────────────────────────────────

def frontmatter_bounds(text: str):
    """(index of the first key line, index of the closing `---`) or None when there is none.

    Command Code's parser wants `---` on the first line; a body line that looks like a key is never
    read as frontmatter, which is why the scan stops at the closing fence."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            return (1, i)
    return None


def fm_value(text: str, key: str):
    """The raw value of a top-level frontmatter `key`, as (kind, payload, line_index).

    kind is `scalar` (payload is the text after the colon), `list` (payload is the list of items of a
    YAML block list, line_index the `key:` line), or None when the key is absent."""
    bounds = frontmatter_bounds(text)
    if not bounds:
        return None
    start, end = bounds
    lines = text.split("\n")
    for i in range(start, end):
        m = re.match(r"^" + re.escape(key) + r":(.*)$", lines[i])
        if not m:
            continue
        inline = m.group(1).strip()
        if inline:
            return ("scalar", inline, i)
        items = []
        for j in range(i + 1, end):
            item = re.match(r"^\s*-\s*(.+?)\s*$", lines[j])
            if not item:
                break
            items.append(item.group(1).strip().strip("\"'"))
        return ("list", items, i)
    return None


def parse_tools(raw) -> list:
    """The ids a `tools:`/`disallowedTools:` value names, in the form Command Code reads.

    `"*"` is preserved as the wildcard it is; a comma- or space-separated scalar splits on both (the
    shipped corpus uses commas, the docs also show spaces)."""
    kind, payload, _line = raw
    if kind == "list":
        return [str(x).strip().strip("\"'") for x in payload if str(x).strip()]
    value = payload.strip().strip("'\"")
    if value == "*":
        return ["*"]
    return [t for t in re.split(r"[,\s]+", value) if t]


def rewrite_key(text: str, key: str, value: str) -> str:
    """Replace a frontmatter key's value with `value`, collapsing a block list to one line.

    Every other byte — key order, quoting style elsewhere, comments — survives; a missing key is
    reported by the caller rather than invented here."""
    found = fm_value(text, key)
    if not found:
        return text
    _kind, _payload, line_index = found
    bounds = frontmatter_bounds(text)
    start, end = bounds
    lines = text.split("\n")
    last = line_index
    while last + 1 < end and re.match(r"^\s*-\s*.+$", lines[last + 1]):
        last += 1                                    # the block list's own item lines go with it
    lines[line_index:last + 1] = [f"{key}: {value}"]
    return "\n".join(lines)


# ── translations ──────────────────────────────────────────────────────────────

def add_key(text: str, key: str, value: str) -> str:
    """Add a frontmatter key that is absent, right after `description:` when there is one.

    Used only for the omitted-`tools:` case, where the absence itself is the defect: Claude Code
    reads a missing `tools` as "inherit every tool", Command Code reads it as "no tools at all", so
    the faithful translation has to say `*` out loud."""
    if fm_value(text, key):
        return text
    bounds = frontmatter_bounds(text)
    if not bounds:
        return f"---\n{key}: {value}\n---\n\n" + text
    start, end = bounds
    lines = text.split("\n")
    at = end
    for i in range(start, end):
        if re.match(r"^description:", lines[i]):
            at = i + 1
            break
    lines[at:at] = [f"{key}: {value}"]
    return "\n".join(lines)


def translate_tools(tokens) -> tuple:
    """(mapped ids, dropped [(token, reason)], notes [str]) for a tools list.

    A wildcard is passed through — it already means "everything", so no translation can narrow it.
    An MCP id passes through by its raw name, which is how Command Code registers MCP tools. An id
    nobody in TOOL_MAP claims is DROPPED and reported: keeping it would be a lie (Command Code drops
    it), and inventing a target would grant a tool the author never asked for."""
    mapped, dropped, notes, seen = [], [], [], set()
    for token in tokens:
        if token == "*":
            if token not in seen:
                seen.add(token)
                mapped.append("*")
            continue
        if token.startswith("mcp__"):
            if token not in seen:
                seen.add(token)
                mapped.append(token)
            continue
        if token not in TOOL_MAP:
            dropped.append((token, "not a Command Code tool id and not an MCP name"))
            continue
        target, why = TOOL_MAP[token]
        if target is None:
            dropped.append((token, why or "no Command Code counterpart"))
            continue
        if why:
            notes.append(f"{token} -> {target}: {why}")
        if target not in seen:
            seen.add(target)
            mapped.append(target)
    return mapped, dropped, notes


def translate_model(text: str) -> tuple:
    """(text, note) with `model:` reset to `inherit` when it is not a Command Code id."""
    found = fm_value(text, "model")
    if not found:
        return text, None
    kind, payload, _line = found
    if kind != "scalar":
        return rewrite_key(text, "model", "inherit"), "model list is not a Command Code value: -> inherit"
    value = payload.strip().strip("'\"")
    if MODEL_OK_RE.match(value):
        return text, None
    return (rewrite_key(text, "model", "inherit"),
            f"model `{value}` is not a Command Code /model id (a Claude alias is not one) and would "
            "be dropped by the harness: -> inherit")


def rename_body_tools(text: str) -> tuple:
    """(text, {token: count}) renaming unambiguous camel-case tool tokens in the body only."""
    bounds = frontmatter_bounds(text)
    head_end = bounds[1] + 1 if bounds else 0
    head, body = "\n".join(text.split("\n")[:head_end]), "\n".join(text.split("\n")[head_end:])
    edits = {}
    for camel in sorted(BODY_RENAMES, key=len, reverse=True):
        pattern = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(camel) + r"(?![A-Za-z0-9_])")
        found = pattern.findall(body)
        if found:
            edits[camel] = len(found)
            body = pattern.sub(BODY_RENAMES[camel], body)
    return (head + "\n" + body if bounds else body), edits


def body_needs_note(text: str) -> list:
    """The idioms in the body that the adapter note exists to address (empty when none)."""
    bounds = frontmatter_bounds(text)
    body = "\n".join(text.split("\n")[bounds[1] + 1:]) if bounds else text
    reasons = []
    if TASK_SPAWN_RE.search(body):
        reasons.append("Task(<agent>) delegation")
    for idiom in PEER_IDIOMS:
        if re.search(r"(?<![A-Za-z0-9_])" + re.escape(idiom) + r"(?![A-Za-z0-9_])", body):
            reasons.append(idiom)
    return reasons


def insert_note(text: str) -> str:
    """Put the adapter note directly under the frontmatter, ahead of the author's prompt."""
    bounds = frontmatter_bounds(text)
    if not bounds:
        return ADAPTER_NOTE + "\n\n" + text
    lines = text.split("\n")
    close = bounds[1]
    return "\n".join(lines[:close + 1] + ["", ADAPTER_NOTE] + lines[close + 1:])


# ── discovery ─────────────────────────────────────────────────────────────────

def discover(roots) -> list:
    """Every agent `*.md` directly under `roots` (Command Code's own scan is flat and top-level only),
    realpath-deduped so a root that is a symlink to another is one corpus, not two."""
    out, seen = [], set()
    for root in roots:
        root = Path(root).expanduser()
        if not root.is_dir():
            continue
        for item in sorted(root.iterdir()):
            if not item.name.endswith(TEXT_SUFFIX) or item.name.startswith("."):
                continue                                  # `.DS_Store`, `_agent_bridge.json`
            if not item.is_file() and not item.is_symlink():
                continue
            try:
                key = os.path.realpath(str(item))
            except OSError:
                continue
            if key in seen:
                continue
            seen.add(key)
            try:
                text = item.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            out.append({"path": item, "name": item.name, "text": text, "root": root})
    out.sort(key=lambda r: r["name"])
    return out


def agent_id_of(record) -> str:
    """The agent id Command Code will use: the frontmatter `name`, sanitized, else the filename."""
    found = fm_value(record["text"], "name")
    raw = ""
    if found and found[0] == "scalar":
        raw = found[1].strip().strip("'\"")
    if not raw:
        raw = record["name"][:-len(TEXT_SUFFIX)]
    return re.sub(r"[^a-zA-Z0-9_-]", "_", raw)


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


# ── build ─────────────────────────────────────────────────────────────────────

def _dest_guard(dest: Path) -> str:
    """Refuse to write through a symlink. `~/.commandcode/agents` is a symlink to the Claude Code
    originals on this machine; writing into it would edit the one corpus every harness shares — the
    exact thing this bridge exists to avoid. Returns an error string, or "" when the dest is safe."""
    if dest.is_symlink():
        return (f"{dest} is a symlink (to {os.path.realpath(str(dest))}) — this bridge would write "
                "into the CLI's shared agent corpus. Remove the symlink first "
                "(`adapters/commandcode/install.sh` does that), then re-run.")
    if dest.exists() and not dest.is_dir():
        return f"{dest} exists and is not a directory"
    return ""


def build(roots, dest=None, force=False, quiet=False) -> dict:
    """Materialize the mirror. The manifest is written LAST, so an interrupted build never claims
    copies it did not finish. Sources are never written to."""
    dest = Path(dest or os.environ.get(DEST_ENV) or DEST_DEFAULT).expanduser()
    problem = _dest_guard(dest)
    if problem:
        raise SystemExit(f"cmd-agent-bridge: {problem}")
    records = discover(roots)
    manifest_path = dest / MANIFEST_NAME
    old = _read_manifest(manifest_path)
    ours = {e.get("file") for e in (old or {}).get("entries", [])}

    fingerprint = hashlib.sha1(json.dumps(
        [[r["name"], _sha256(r["path"])] for r in records] + [str(Path(r).expanduser()) for r in roots]
        + [MANIFEST_VERSION], sort_keys=True).encode()).hexdigest()
    if not force and old and old.get("fingerprint") == fingerprint and _mirror_intact(dest, old):
        report = {"status": "unchanged", "dest": str(dest), "counts": _counts(old),
                  "entries": sorted(e.get("file", "") for e in old.get("entries", [])),
                  "preserved": old.get("preserved", []), "warnings": old.get("warnings", [])}
        if not quiet:
            print(f"cmd-agent-bridge: mirror up to date — {len(old.get('entries', []))} mirrored "
                  f"agent(s) in {dest}")
        return report

    dest.mkdir(parents=True, exist_ok=True)
    entries, warnings, collisions = [], [], []
    bridged_files = set()
    for rec in records:
        name = rec["name"]
        agent_id = agent_id_of(rec)
        if agent_id in RESERVED:
            warnings.append(f"{name}: agent id `{agent_id}` is reserved by Command Code ("
                            f"{', '.join(sorted(RESERVED))}) — the file is ignored by the harness, "
                            "so it is not mirrored")
            continue
        target = dest / name
        if target.exists() and name not in ours:
            collisions.append({"file": name, "source": str(rec["path"]),
                               "reason": "a file this bridge does not own already exists here"})
            warnings.append(f"{name}: {target} exists and was not written by this bridge — left "
                            "untouched, and this agent is NOT mirrored")
            continue

        tokens_raw = fm_value(rec["text"], "tools")
        text = rec["text"]
        dropped, notes = [], []
        if tokens_raw:
            mapped, dropped, notes = translate_tools(parse_tools(tokens_raw))
            text = rewrite_key(text, "tools", '"*"' if mapped == ["*"] else ", ".join(mapped))
        else:
            text = add_key(text, "tools", '"*"')
            notes.append("no `tools:` key: Claude Code inherits every tool, Command Code would grant "
                         'NONE — wrote `tools: "*"`')
        for deny_key in ("disallowedTools", "disallowed_tools"):
            deny_raw = fm_value(text, deny_key)
            if deny_raw:
                mapped, dropped_deny, _ = translate_tools(parse_tools(deny_raw))
                text = rewrite_key(text, deny_key, '"*"' if mapped == ["*"] else ", ".join(mapped))
                dropped.extend(dropped_deny)
        text, model_note = translate_model(text)
        text, body_edits = rename_body_tools(text)
        note_reasons = body_needs_note(text)
        if note_reasons:
            text = insert_note(text)
        for token, why in dropped:
            warnings.append(f"{name}: `{token}` dropped from the allowlist — {why}")
        for n in notes + ([model_note] if model_note else []):
            warnings.append(f"{name}: {n}")

        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, target)
        bridged_files.add(name)
        entries.append({
            "file": name, "source": str(rec["path"]), "source_sha256": _sha256(rec["path"]),
            "agent_id": agent_id,
            "tools_before": parse_tools(tokens_raw) if tokens_raw else [],
            "tools_after": parse_tools(fm_value(text, "tools")) if fm_value(text, "tools") else [],
            "dropped": [t for t, _w in dropped],
            "body_edits": body_edits, "note_inserted": bool(note_reasons),
            "note_reasons": note_reasons,
        })

    # Stale copies from a previous build (source renamed or removed) go now — but only files the
    # manifest names, so a file this bridge did not write is never deleted.
    removed = []
    for stale in {e.get("file") for e in (old or {}).get("entries", [])} - bridged_files:
        if not stale or "/" in stale:
            continue
        victim = dest / stale
        if victim.is_file() and victim.parent == dest:
            try:
                victim.unlink()
                removed.append(stale)
            except OSError:
                warnings.append(f"{stale}: stale mirror file could not be removed")

    preserved = sorted(p.name for p in dest.iterdir()
                       if p.name.endswith(TEXT_SUFFIX) and p.name not in bridged_files
                       and not p.is_symlink() and p.is_file())
    if preserved:
        warnings.append(f"{len(preserved)} file(s) in {dest} were not written by this bridge and were "
                        "left alone: " + ", ".join(preserved))

    manifest = {"_note": "Generated by scripts/cmd_agent_bridge.py — do not edit. Every file listed "
                         "here is a Command Code-native copy of an agent whose source lives in the "
                         "Claude Code agent corpus; run `cmd_agent_bridge.py build --force` to "
                         "regenerate. Files NOT listed here were not written by this bridge.",
                "version": MANIFEST_VERSION, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "dest": str(dest), "roots": [str(Path(r).expanduser()) for r in roots],
                "fingerprint": fingerprint, "entries": entries, "collisions": collisions,
                "preserved": preserved, "warnings": warnings, "removed": removed}
    _write_manifest(manifest_path, manifest)
    if not quiet:
        print(f"cmd-agent-bridge: {len(entries)} mirrored, {len(collisions)} collision(s), "
              f"{len(warnings)} warning(s), {len(removed)} stale removed, {len(preserved)} preserved "
              f"-> {dest}")
        for w in warnings:
            print(f"  [w] {w}")
    return {"status": "built", "dest": str(dest), "counts": _counts(manifest),
            "entries": [e["file"] for e in entries], "collisions": collisions,
            "preserved": preserved, "removed": removed, "warnings": warnings}


def _counts(manifest) -> dict:
    entries = manifest.get("entries", [])
    return {"mirrored": len(entries), "dropped_tokens": sum(len(e.get("dropped", [])) for e in entries),
            "collisions": len(manifest.get("collisions", [])),
            "preserved": len(manifest.get("preserved", [])),
            "warnings": len(manifest.get("warnings", []))}


def _read_manifest(path: Path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, UnicodeError, ValueError):
        return None


def _write_manifest(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _mirror_intact(dest: Path, manifest) -> bool:
    for e in manifest.get("entries", []):
        f = e.get("file", "")
        if not f or "/" in f or not (dest / f).is_file():
            return False
    return True


# ── verify / clean ────────────────────────────────────────────────────────────

def verify(dest=None) -> dict:
    """Prove every mirrored file is loadable by Command Code AND that no source was modified.

    Each row is a rule this bridge exists to satisfy: the file exists, its frontmatter parses, every
    id on its `tools:` line is one this bridge produced (`*`, an MCP name, or a TOOL_MAP target), and
    the source it came from is byte-identical to what the manifest recorded."""
    dest = Path(dest or os.environ.get(DEST_ENV) or DEST_DEFAULT).expanduser()
    manifest = _read_manifest(dest / MANIFEST_NAME)
    problems, checked = [], 0
    if not manifest:
        return {"ok": False, "dest": str(dest), "checked": 0,
                "problems": [f"no manifest at {dest / MANIFEST_NAME} — run `build` first"]}
    legal_targets = {t for t, _w in TOOL_MAP.values() if t}
    for e in manifest.get("entries", []):
        f = e.get("file", "")
        checked += 1
        if not f or "/" in f:
            problems.append(f"manifest entry {f!r} is not a plain filename")
            continue
        path = dest / f
        if not path.is_file():
            problems.append(f"{f}: {path} missing")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if not frontmatter_bounds(text):
            problems.append(f"{f}: no parseable frontmatter — Command Code would not read it as an agent")
        tools_raw = fm_value(text, "tools")
        if not tools_raw:
            problems.append(f"{f}: no `tools:` line — Command Code grants such an agent NO tools "
                            "(it does not inherit the caller's set)")
        else:
            for token in parse_tools(tools_raw):
                if token != "*" and not token.startswith("mcp__") and token not in legal_targets:
                    problems.append(f"{f}: `{token}` on the tools line is not a Command Code tool id — "
                                    "the harness drops it silently")
        model = fm_value(text, "model")
        if model and model[0] == "scalar" and not MODEL_OK_RE.match(model[1].strip().strip("'\"")):
            problems.append(f"{f}: model {model[1]!r} is not a Command Code id or `inherit`")
        src = Path(e.get("source", ""))
        if e.get("source_sha256"):
            if not src.is_file():
                problems.append(f"{f}: source {src} is gone")
            elif _sha256(src) != e["source_sha256"]:
                problems.append(f"{f}: source {src} CHANGED since the build — a source mismatch means "
                                "the mirror is stale, or that something wrote to the Claude corpus")
    return {"ok": not problems, "dest": str(dest), "checked": checked,
            "mirrored": len(manifest.get("entries", [])), "collisions": manifest.get("collisions", []),
            "preserved": manifest.get("preserved", []), "warnings": manifest.get("warnings", []),
            "problems": problems}


def clean(dest=None, quiet=False) -> dict:
    """Remove the mirrored files this bridge wrote. A file the manifest does not name is never
    touched: the directory can hold agents created in Command Code itself."""
    dest = Path(dest or os.environ.get(DEST_ENV) or DEST_DEFAULT).expanduser()
    manifest = _read_manifest(dest / MANIFEST_NAME) or {}
    removed, kept = [], []
    for e in manifest.get("entries", []):
        f = e.get("file", "")
        victim = dest / f
        if f and "/" not in f and victim.is_file() and victim.parent == dest:
            try:
                victim.unlink()
                removed.append(f)
            except OSError:
                kept.append(f)
    try:
        (dest / MANIFEST_NAME).unlink()
    except OSError:
        pass
    if not quiet:
        print(f"cmd-agent-bridge: removed {len(removed)} mirrored file(s) from {dest}"
              + (f" ({len(kept)} could not be removed)" if kept else ""))
        if dest.is_dir():
            for p in sorted(x.name for x in dest.iterdir()
                            if x.name.endswith(TEXT_SUFFIX) and x.name not in removed):
                print(f"  [i] left in place (not written by this bridge): {p}")
    return {"removed": removed, "kept": kept, "dest": str(dest)}


# ── cli ───────────────────────────────────────────────────────────────────────

DEFAULT_ROOTS = [Path.home() / ".claude" / "agents"]


def _roots(args) -> list:
    return [Path(r).expanduser() for r in (args.root or DEFAULT_ROOTS)]


def _plan(roots) -> tuple:
    """Read-only preview: what each source needs and what would move. Never writes."""
    rows, warnings = [], []
    for rec in discover(roots):
        agent_id = agent_id_of(rec)
        tokens_raw = fm_value(rec["text"], "tools")
        mapped, dropped, notes = translate_tools(parse_tools(tokens_raw)) if tokens_raw else ([], [], [])
        if not tokens_raw:
            mapped = ["*"]
            notes = ["no `tools:` key: Claude Code inherits every tool, Command Code would grant NONE "
                     '— the mirror gets `tools: "*"`']
        model_note = None
        if fm_value(rec["text"], "model"):
            _t, model_note = translate_model(rec["text"])
        _t2, body_edits = rename_body_tools(rec["text"])
        reasons = body_needs_note(rec["text"])
        if agent_id in RESERVED:
            warnings.append(f"{rec['name']}: agent id `{agent_id}` is reserved — Command Code ignores it")
        rows.append({"file": rec["name"], "source": str(rec["path"]), "agent_id": agent_id,
                     "tools_before": parse_tools(tokens_raw) if tokens_raw else [],
                     "tools_after": mapped, "dropped": [t for t, _w in dropped],
                     "notes": notes + ([model_note] if model_note else []),
                     "body_edits": body_edits, "note_reasons": reasons})
    return rows, warnings


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in argv:
        return _selftest()
    ap = argparse.ArgumentParser(description="Mirror Claude-style agent definitions into Command Code.")
    ap.add_argument("command", nargs="?", default="build",
                    choices=["build", "verify", "clean", "list", "selftest"])
    ap.add_argument("--root", action="append", help="agent source directory to scan (repeatable)")
    ap.add_argument("--dest", help=f"mirror directory (default: ${DEST_ENV} or {DEST_DEFAULT})")
    ap.add_argument("--force", action="store_true", help="rebuild even when nothing changed")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--json", action="store_true", help="machine-readable report on stdout")
    args = ap.parse_args(argv)

    if args.command == "selftest":
        return _selftest()
    if args.command == "verify":
        rep = verify(args.dest)
        print(json.dumps(rep, indent=1) if args.json else
              (f"cmd-agent-bridge verify: {'OK' if rep['ok'] else 'FAILED'} — {rep['checked']} "
               "mirrored file(s) checked"
               + "".join(f"\n  [!] {p}" for p in rep["problems"])))
        return 0 if rep["ok"] else 1
    if args.command == "clean":
        rep = clean(args.dest, args.quiet)
        if args.json:
            print(json.dumps(rep, indent=1))
        return 0
    if args.command == "list":
        rows, warnings = _plan(_roots(args))
        if args.json:
            print(json.dumps({"rows": rows, "warnings": warnings}, indent=1))
        else:
            print(f"{len(rows)} agent file(s) under {', '.join(str(r) for r in _roots(args))}:")
            for r in rows:
                dropped = f" drops {','.join(r['dropped'])}" if r["dropped"] else ""
                edits = (" edits " + ",".join(f"{k}x{v}" for k, v in r["body_edits"].items())
                         ) if r["body_edits"] else ""
                note = " +adapter-note" if r["note_reasons"] else ""
                print(f"  {r['file']:<52} {len(r['tools_before']):>2} tools -> "
                      f"{len(r['tools_after']):>2}{dropped}{edits}{note}")
            for w in warnings:
                print(f"  [w] {w}")
        return 0

    rep = build(_roots(args), args.dest, force=args.force, quiet=args.quiet)
    if args.json:
        print(json.dumps(rep, indent=1))
    return 0


def _selftest() -> int:
    """The translation rules on fixtures, with no access to the live corpus."""
    ok = True
    # every Claude id the shared corpus uses maps to a Command Code id, or is a deliberate drop
    for token in ("Read", "Bash", "Glob", "Grep", "Write", "Edit", "MultiEdit", "NotebookEdit",
                  "WebFetch", "WebSearch", "TaskCreate", "TaskGet", "TaskUpdate", "TaskList",
                  "BashOutput", "KillBash", "LS", "SendMessage"):
        if token not in TOOL_MAP:
            print(f"  [!] {token} has no mapping")
            ok = False
    mapped, dropped, notes = translate_tools(["Glob", "Grep", "Read", "Edit", "MultiEdit", "Write",
                                              "NotebookEdit", "Bash", "WebFetch", "WebSearch",
                                              "TaskCreate", "TaskGet", "TaskUpdate", "TaskList",
                                              "SendMessage", "Task(Explore)", "mcp__exa__web_search_exa"])
    ok &= mapped == ["glob", "grep", "read_file", "edit_file", "write_file", "shell_command",
                     "web_fetch", "web_search", "task_create", "task_get", "task_update", "task_list",
                     "mcp__exa__web_search_exa"]
    ok &= sorted(t for t, _w in dropped) == ["SendMessage", "Task(Explore)"]
    ok &= any("MultiEdit" in n for n in notes) and any("todo_write" in n or "NotebookEdit" in n
                                                       for n in notes)
    ok &= translate_tools(["*"]) == (["*"], [], [])
    # an unknown id is dropped and reported, never invented
    ok &= translate_tools(["TotallyMadeUp"]) == ([], [("TotallyMadeUp",
                                                       "not a Command Code tool id and not an MCP name")], [])
    # frontmatter: scalar, block list, wildcard
    fm = "---\nname: x\ndescription: y\ntools: Read, Write\nmodel: sonnet\n---\n\nbody\n"
    ok &= parse_tools(fm_value(fm, "tools")) == ["Read", "Write"]
    ok &= rewrite_key(fm, "tools", "read_file, write_file").split("\n")[3] == "tools: read_file, write_file"
    block = "---\nname: x\ntools:\n  - Read\n  - Grep\nmodel: inherit\n---\nb\n"
    ok &= parse_tools(fm_value(block, "tools")) == ["Read", "Grep"]
    out = rewrite_key(block, "tools", "read_file, grep")
    ok &= "tools: read_file, grep\n" in out and "- Read" not in out and out.count("tools:") == 1
    ok &= parse_tools(fm_value("---\ntools: \"*\"\n---\n", "tools")) == ["*"]
    # a bare `*` is a YAML alias (Command Code patches exactly this), so the mirror quotes it
    ok &= 'tools: "*"' in rewrite_key("---\ntools: *\n---\n", "tools", '"*"')
    # model: a Claude alias is not a Command Code id; inherit and a real id survive
    _o, note = translate_model(fm)
    ok &= note is not None and "-> inherit" in note
    ok &= translate_model("---\nmodel: inherit\n---\n")[1] is None
    ok &= translate_model("---\nmodel: claude-opus-4-8\n---\n")[1] is None
    ok &= translate_model("---\nname: a\n---\n")[1] is None            # absent: nothing to say
    # the note goes under the frontmatter, ahead of the prompt
    noted = insert_note(fm)
    ok &= noted.startswith("---\nname: x") and ADAPTER_NOTE in noted and noted.rstrip().endswith("body")
    ok &= body_needs_note("---\nname: a\n---\nUse Task(Explore) to scan.\n") == ["Task(<agent>) delegation"]
    ok &= body_needs_note("---\nname: a\n---\nplain prompt\n") == []
    # a body tool token is renamed only when the name is unambiguous
    text = "---\nname: a\n---\nCall TaskUpdate(status: \"completed\"), then WebFetch it. Read the file.\n"
    renamed, edits = rename_body_tools(text)
    ok &= "task_update(" in renamed and "web_fetch" in renamed
    ok &= edits == {"TaskUpdate": 1, "WebFetch": 1}
    ok &= "Read the file." in renamed                        # an English verb is not a tool reference
    ok &= "TaskUpdate" not in renamed.split("---")[2]
    # a frontmatter key is never rewritten by the body pass
    _r2, e2 = rename_body_tools("---\ntools: Read, WebFetch\n---\nbody\n")
    ok &= e2 == {}
    # an omitted `tools:` key is the defect itself: Claude Code inherits all, Command Code grants none
    added = add_key("---\nname: a\ndescription: d\n---\n\nbody\n", "tools", '"*"')
    ok &= added.split("\n")[3] == 'tools: "*"' and added.split("\n")[2] == "description: d"
    ok &= add_key(fm, "tools", '"*"') == fm                       # an existing key is never duplicated
    ok &= add_key("plain text\n", "tools", '"*"').startswith('---\ntools: "*"\n---')
    # discovery is flat, skips dotfiles and non-.md, and follows a file symlink
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        src = t / "src"
        (src / "sub").mkdir(parents=True)
        (src / "a.md").write_text("---\nname: a\n---\nx\n")
        (src / "sub" / "nested.md").write_text("---\nname: n\n---\nx\n")
        (src / ".hidden.md").write_text("---\nname: h\n---\nx\n")
        (src / "b.txt").write_text("x")
        (src / "linked.md").symlink_to(src / "a.md")
        got = sorted(r["name"] for r in discover([src]))
        ok &= got == ["a.md"]                                # flat, no dotfiles, one realpath
        dest = t / "dest"
        rep = build([src], dest, quiet=True)
        ok &= rep["status"] == "built" and (dest / "a.md").is_file()
        ok &= (dest / MANIFEST_NAME).is_file()
        # a source with no `tools:` key is mirrored WITH one — the omission would cost every tool
        ok &= 'tools: "*"' in (dest / "a.md").read_text()
        ok &= any("no `tools:` key" in w for w in rep["warnings"])
        # a same-name file the bridge does not own is preserved, never clobbered
        (src / "native.md").write_text("---\nname: native\n---\nx\n")
        (dest / "native.md").write_text("hand-written in Command Code\n")
        rep = build([src], dest, force=True, quiet=True)
        ok &= (dest / "native.md").read_text() == "hand-written in Command Code\n"
        ok &= any("native.md" == c["file"] for c in rep["collisions"])
        ok &= "native.md" in rep["preserved"]
        # verify passes, then fails when a source changes under it
        ok &= verify(dest)["ok"]
        (src / "a.md").write_text("---\nname: a\n---\nCHANGED\n")
        bad = verify(dest)
        ok &= not bad["ok"] and any("CHANGED" in p for p in bad["problems"])
        # clean removes only what the manifest names
        clean(dest, quiet=True)
        ok &= not (dest / "a.md").exists() and (dest / "native.md").read_text().startswith("hand")
        # a symlinked dest is refused: writing there would edit the shared corpus
        link = t / "link"
        link.symlink_to(dest)
        try:
            build([src], link, quiet=True)
            print("  [!] a symlinked dest must be refused")
            ok = False
        except SystemExit:
            pass
    print("cmd-agent-bridge --selftest " + ("OK" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
