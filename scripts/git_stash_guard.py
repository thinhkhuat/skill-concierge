#!/usr/bin/env python3
"""
git_stash_guard.py — PreToolUse(Bash) gate: no `git stash` that moves work out of the tree.

WHY THIS EXISTS
    The owner's standing rule is "no git stash". A stash silently lifts uncommitted work out
    of the working tree; in a multi-agent repo another agent (or a later compaction) can
    lose track of it, and a forgotten stash is invisible in `git status`. On 2026-09-27 a
    release builder ran `git stash` twice despite the rule being in its brief (both times
    popped at once, no loss). A rule that lives only in prompts is a symptom-level control;
    this hook enforces it where the command runs.

WHAT IT DOES
    Non-git or non-stash Bash calls: exit 0 silently (no decision; normal permission flow).
    `git stash` in any form that changes state (push, save, bare `git stash`, pop, apply,
    drop, clear, store, create, branch, `-u`/`-a`/`-p`/`--keep-index` variants), including
    compound commands (`a && git stash`) and `git -C <path> stash`: permissionDecision
    "deny", naming the safe alternatives. Read-only `git stash list` / `git stash show`
    pass, so an agent can still inspect and recover an existing stash.

SAFE ALTERNATIVES (named in the denial)
    Compare against an earlier version with `git show <ref>:<path>` or `git diff <ref>`;
    keep work with a WIP commit on a branch; isolate with `git worktree add`.

FAILS OPEN
    Any internal error exits 0 (the openwiki guard's rule: a broken guard must never wedge
    the repo). Override for a deliberate human use: GIT_STASH_GUARD=0.
"""
import json
import os
import re
import shlex
import sys

READ_ONLY = {"list", "show"}
REASON = ("git stash is blocked in this repo (owner rule: no git stash). A stash lifts "
          "uncommitted work out of sight of `git status` and other agents. Instead: compare "
          "with `git show <ref>:<path>` / `git diff <ref>`, keep work in a WIP commit on a "
          "branch, or isolate it with `git worktree add`. `git stash list` / `git stash show` "
          "stay allowed. Deliberate human override: GIT_STASH_GUARD=0.")

_SPLIT = re.compile(r"&&|\|\||;|\||\n")


def _stash_subcommand(segment: str):
    """Return the stash subcommand ('' for bare `git stash`) if SEGMENT runs git stash."""
    try:
        toks = shlex.split(segment, posix=True)
    except ValueError:
        toks = segment.split()
    # skip env assignments and wrappers like `command`, `env`, `sudo`
    while toks and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", toks[0]) or toks[0] in ("command", "env", "sudo")):
        toks = toks[1:]
    if not toks or os.path.basename(toks[0]) != "git":
        return None
    i = 1
    while i < len(toks) and toks[i].startswith("-"):      # git -C <path>, -c k=v, --git-dir=...
        if toks[i] in ("-C", "-c", "--git-dir", "--work-tree", "--namespace") and i + 1 < len(toks):
            i += 2
        else:
            i += 1
    if i >= len(toks) or toks[i] != "stash":
        return None
    rest = [t for t in toks[i + 1:] if not t.startswith("-")]
    return rest[0] if rest else ""


def decide(command: str):
    """'deny' reason string if COMMAND runs a state-changing git stash, else None."""
    for seg in _SPLIT.split(command or ""):
        sub = _stash_subcommand(seg.strip())
        if sub is not None and sub not in READ_ONLY:
            return REASON
    return None


def main():
    if os.environ.get("GIT_STASH_GUARD", "1") == "0":
        return 0
    try:
        payload = json.load(sys.stdin)
        cmd = (payload.get("tool_input") or {}).get("command", "")
        reason = decide(cmd)
        if reason:
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason}}))
    except Exception:
        return 0
    return 0


def _selftest():
    deny = ["git stash", "git stash -u", "git stash push -m x", "git stash pop", "git stash apply",
            "git stash drop", "git stash clear", "git -C /tmp/x stash", "git add . && git stash -u",
            "FOO=1 git stash save wip", "cd a; git stash branch b"]
    allow = ["git stash list", "git stash show -p", "git status", "echo git stash", "git commit -m 'stash'",
             "ls stash", "git show HEAD:x"]
    bad = [c for c in deny if not decide(c)] + [c for c in allow if decide(c)]
    print("selftest ok" if not bad else f"selftest FAIL: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(_selftest() if "--selftest" in sys.argv else main())
