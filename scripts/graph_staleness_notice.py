#!/usr/bin/env python3
"""
graph_staleness_notice.py — PreToolUse(Bash) NOTICE: the knowledge graph is behind the code.

WHY THIS EXISTS
    graphify-out/graph.json is a map of this codebase. It goes stale the moment the code
    moves, and a stale map gets read as authoritative — the same failure openwiki_parity_guard
    exists to prevent. But the remedy differs, so the verdict differs.

WHY THIS WARNS INSTEAD OF DENYING (deliberate — do not "upgrade" it to a deny)
    openwiki/ is COMMITTED: a stale wiki ships to every clone, and the fix is a sub-second
    text edit. Blocking is proportionate.

    graphify-out/ is GITIGNORED: it never ships, so a stale graph harms only the local
    session. And the fix is asymmetric — code staleness rebuilds via AST for free, but doc
    staleness needs LLM calls through the gateway (real money, real minutes). This repo is
    doc-heavy and generates plans/reports constantly; a deny would tax every commit and buy
    nothing a post-commit rebuild doesn't already give. Freshness is maintained by the
    post-commit auto-rebuild hook (`graphify hook install`); this notice covers the gap that
    hook leaves — DOC changes, which it deliberately ignores.

    A gate must be proportionate to the harm and the cost of the fix. This one isn't a gate.

SCOPE — GIT-TRACKED FILES ONLY (load-bearing)
    graphify indexes scratch dirs it finds on disk (.remember/, .memsearch/, .gjc/) which
    churn every single turn. Keyed on raw staleness this notice would fire on EVERY commit
    forever, and a warning that always fires is one you train yourself to ignore. Only files
    git actually tracks can make the graph "stale" in any sense worth reporting.

WHAT IT DOES
    Fires on PreToolUse for Bash. Not a `git commit` -> exits 0 silently (per the hooks spec,
    exit 0 with no output = "no decision to report"; silence is abstention, not approval, and
    the call proceeds through the normal permission flow).

    On a commit: asks graphify's OWN detect_incremental() which tracked files are new or
    modified since the manifest was written, then reports them as additionalContext. It never
    emits permissionDecision — emitting "allow" would bypass the user's permission prompt on
    every commit, which is a far worse bug than a stale graph.

ESCAPE HATCH
    GRAPH_NOTICE=0 -> skip entirely.

FAIL-OPEN, ALWAYS
    No graph yet (fresh clone), no graphify installed, any internal error -> exit 0, silent.
    A notice must never wedge the repo, and must never nag a clone that never opted in.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# `git commit`, tolerating compound commands and intervening flags:
#   git commit -m x   |   git add . && git commit   |   git -C path commit
COMMIT_RE = re.compile(r"\bgit\b(?:\s+-[^\s]+(?:\s+[^\s-][^\s]*)?)*\s+commit\b")

# How many stale files to name before truncating the message.
MAX_LISTED = 8


def _repo_root():
    """Project root, from the CLAUDE_PROJECT_DIR placeholder Claude Code exports."""
    root = os.environ.get("CLAUDE_PROJECT_DIR")
    return Path(root) if root else None


def _is_skill_concierge(root):
    """Guard only this repo. Defensive — project settings shouldn't load elsewhere anyway."""
    try:
        manifest = root / ".claude-plugin" / "plugin.json"
        return json.loads(manifest.read_text()).get("name") == "skill-concierge"
    except Exception:
        return False


def _graphify_python(root):
    """The interpreter that can `import graphify`.

    The graphify skill records it at graphify-out/.graphify_python. That path is gitignored,
    so on a fresh clone it is absent — which is exactly when we want to stay silent anyway.
    """
    pin = root / "graphify-out" / ".graphify_python"
    try:
        exe = pin.read_text(encoding="utf-8").strip()
        if exe and Path(exe).exists():
            return exe
    except Exception:
        pass
    return None


def _tracked(root):
    """Files git actually tracks. Anything else is scratch and cannot make the graph stale."""
    r = subprocess.run(
        ["git", "ls-files"], cwd=str(root), capture_output=True, text=True, timeout=15,
    )
    if r.returncode != 0:
        return None
    return {ln.strip() for ln in r.stdout.splitlines() if ln.strip()}


def _stale(root, python):
    """Tracked files new/modified since the manifest, via graphify's own incremental detector.

    Delegated rather than reimplemented: a second staleness definition would drift against
    graphify's, which is the failure this repo keeps catching itself on.
    """
    probe = (
        "import json;"
        "from pathlib import Path;"
        "from graphify.detect import detect_incremental;"
        "r=detect_incremental(Path.cwd(), kind='ast');"
        "print(json.dumps(r.get('new_files') or {}))"
    )
    r = subprocess.run(
        [python, "-c", probe], cwd=str(root),
        capture_output=True, text=True, timeout=25,
    )
    if r.returncode != 0:
        return None  # graphify unusable -> fail open
    new_files = json.loads(r.stdout.strip().splitlines()[-1])

    tracked = _tracked(root)
    if tracked is None:
        return None

    out = {"code": [], "document": []}
    base = str(root) + os.sep
    for cat, files in new_files.items():
        for f in files:
            rel = f[len(base):] if f.startswith(base) else f
            if rel not in tracked:
                continue  # scratch — not our business
            bucket = "code" if cat == "code" else "document"
            out[bucket].append(rel)
    return out


def _emit(code, docs):
    """Non-blocking. additionalContext reaches Claude next to the tool result (hooks spec);
    systemMessage reaches the user. permissionDecision is deliberately ABSENT — setting it to
    "allow" here would auto-approve every git commit and silently disable the permission prompt.
    """
    lines = []
    if code:
        shown = code[:MAX_LISTED]
        lines.append(
            "  CODE (%d) — free to refresh, AST only, no LLM:\n%s%s"
            % (
                len(code),
                "".join("    - %s\n" % f for f in shown),
                "    - ...and %d more\n" % (len(code) - len(shown)) if len(code) > len(shown) else "",
            )
        )
    if docs:
        shown = docs[:MAX_LISTED]
        lines.append(
            "  DOCS (%d) — refresh costs LLM calls through the gateway:\n%s%s"
            % (
                len(docs),
                "".join("    - %s\n" % f for f in shown),
                "    - ...and %d more\n" % (len(docs) - len(shown)) if len(docs) > len(shown) else "",
            )
        )

    body = (
        "graphify-out/ is behind the codebase. The commit is NOT blocked — this is a notice.\n\n"
        + "\n".join(lines)
        + "\nThe graph is a map that gets read as authoritative, so it is worth knowing when it\n"
          "has drifted. Refresh with:  /graphify . --update\n"
          "Code-only drift also self-heals via the post-commit hook (`graphify hook status`).\n"
          "Silence this notice: GRAPH_NOTICE=0."
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": body,
        },
        "systemMessage": "graphify: %d code + %d doc file(s) changed since the last graph build (commit not blocked)."
                         % (len(code), len(docs)),
    }))


def main():
    if os.environ.get("GRAPH_NOTICE") == "0":
        return 0

    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # unparseable input: not our business

    if payload.get("tool_name") != "Bash":
        return 0

    command = (payload.get("tool_input") or {}).get("command") or ""
    if not COMMIT_RE.search(command):
        return 0

    root = _repo_root()
    if not root or not _is_skill_concierge(root):
        return 0

    # No graph on disk -> nothing has gone stale. A clone that never ran graphify is not
    # "behind"; it simply never opted in. Stay silent.
    if not (root / "graphify-out" / "manifest.json").exists():
        return 0

    python = _graphify_python(root)
    if not python:
        return 0

    stale = _stale(root, python)
    if not stale:
        return 0

    code, docs = stale["code"], stale["document"]
    if not code and not docs:
        return 0

    _emit(code, docs)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # fail-open: a broken notice must never wedge the repo
