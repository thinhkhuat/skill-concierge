#!/usr/bin/env python3
"""
git_stash_guard.py — PreToolUse(Bash) gate: deny any git stash invocation that can
change state.

WHY THIS EXISTS
    The owner's standing rule is "no git stash". A stash silently lifts uncommitted work
    out of the working tree; in a multi-agent repo another agent (or a later compaction)
    can lose track of it, and a forgotten stash is invisible in `git status`. On
    2026-09-27 a release builder ran `git stash` twice despite the rule being in its
    brief (both times popped at once, no loss). A rule that lives only in prompts is a
    symptom-level control; this hook enforces it where the command runs.

WHAT IT DOES — DENY BY DEFAULT
    Any command that runs `git ... stash` in any recognized form is DENIED unless the
    token immediately following `stash` is exactly `list` or `show`. Recognized forms:
      - global git options before the subcommand: `-C <path>`, `-c k=v`, `--git-dir=`,
        `--work-tree=`, `--namespace=`, `--no-pager`, and other dash flags
      - an environment-variable prefix: `GIT_DIR=x git stash`
      - wrappers: `env`, `command`, `sudo`, `time`, `nice`, `exec`, `eval`, `xargs`
      - shell keywords that can precede a command word: `if`/`then`/`elif`/`else`/
        `while`/`until`/`do`/`done`/`fi`/`case`/`esac`
      - grouping: `( ... )`, `{ ... ; }`
      - an absolute or relative git path (`/usr/bin/git`), a backslash-escaped
        invocation (`\\git`), and the fused porcelain executable name `git-stash`
      - a shell interpreter running a command string: `bash -c '...'`, `sh -c "..."`
      - command substitution, wherever it sits in the surrounding command:
        `$(git stash)`, `` `git stash` ``
      - command separators: `&&`, `||`, `;`, `|`, `&`, newline
    A command that never runs `git ... stash` at all — including one that merely
    mentions the word ("git log --grep stash", "echo git stash", a quoted string) —
    passes through with no decision.

    Deliberate obfuscation is OUT OF SCOPE: a string built by concatenation, base64, or
    a Python/Perl one-liner that shells out is not analyzed. This guard catches the
    forms an agent or a human is likely to type by accident or by habit, not a
    determined attempt to defeat it.

SAFE ALTERNATIVES (named in the denial)
    Compare against an earlier version with `git show <ref>:<path>` or `git diff <ref>`;
    keep work with a WIP commit on a branch; isolate with `git worktree add`.

FAILS OPEN
    Any internal error exits 0 (the openwiki guard's rule: a broken guard must never
    wedge the repo). Override for a deliberate human use: GIT_STASH_GUARD=0.
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

_GIT_GLOBAL_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}
_WRAPPERS = {"command", "env", "sudo", "time", "nice", "exec", "eval", "xargs"}
_KEYWORDS = {"if", "then", "elif", "else", "while", "until", "do", "done", "fi", "case", "esac"}
_SHELLS = {"bash", "sh", "zsh", "dash", "ksh", "ash"}
_SEPARATORS = {"&&", "||", ";", "|", "&"}

_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def _extract_substitutions(command):
    """Return (outer, inners): OUTER has every top-level `$(...)` and backtick span
    replaced with a space; INNERS holds their contents so the caller can check each of
    them too, regardless of where they sit inside the surrounding command (the shell
    runs a substitution before the command that contains it ever sees its output)."""
    outer = []
    inners = []
    i, n = 0, len(command)
    while i < n:
        ch = command[i]
        if ch == "$" and i + 1 < n and command[i + 1] == "(":
            depth = 1
            j = i + 2
            while j < n and depth:
                if command[j] == "(":
                    depth += 1
                elif command[j] == ")":
                    depth -= 1
                j += 1
            inners.append(command[i + 2:j - 1 if depth == 0 else j])
            outer.append(" ")
            i = j
            continue
        if ch == "`":
            j = command.find("`", i + 1)
            if j == -1:
                outer.append(ch)
                i += 1
                continue
            inners.append(command[i + 1:j])
            outer.append(" ")
            i = j + 1
            continue
        outer.append(ch)
        i += 1
    return "".join(outer), inners


def _tokenize(text):
    """Split TEXT into shell words plus control-operator tokens (`&&`, `;`, `(`, ...),
    quote-aware. Falls back to a naive whitespace split on malformed input (an
    unterminated quote) rather than raising."""
    try:
        lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        return list(lexer)
    except Exception:
        return text.split()


def _strip_leaders(toks):
    """Drop leading env assignments, wrappers, shell keywords, and a group-open token;
    a `git ... stash` command word can follow any of them."""
    changed = True
    while toks and changed:
        changed = False
        head = toks[0]
        if _ASSIGN_RE.match(head) or head in _WRAPPERS or head in _KEYWORDS or head in ("(", "{"):
            toks = toks[1:]
            changed = True
    return toks


def _shell_dash_c_argument(toks):
    """If TOKS runs a shell interpreter with `-c`, return its command-string argument
    (the next token after `-c`), else None."""
    if not toks or os.path.basename(toks[0]) not in _SHELLS:
        return None
    for idx in range(1, len(toks) - 1):
        if toks[idx] == "-c":
            return toks[idx + 1]
    return None


def _group_is_denied(toks):
    """TOKS is one already-separated command (no `&&`/`;`/`|`/`&` inside it). Return
    True if it runs a state-changing `git stash` in any recognized form."""
    toks = _strip_leaders(toks)
    if not toks:
        return False

    nested = _shell_dash_c_argument(toks)
    if nested is not None:
        return decide(nested) is not None

    base = os.path.basename(toks[0])
    if base == "git-stash":
        rest = toks[1:]
        first = rest[0] if rest else ""
        return first not in READ_ONLY

    if base != "git":
        return False

    i = 1
    while i < len(toks) and toks[i].startswith("-"):        # git -C <path>, -c k=v, --git-dir=...
        if toks[i] in _GIT_GLOBAL_WITH_VALUE and i + 1 < len(toks):
            i += 2
        else:
            i += 1
    if i >= len(toks) or toks[i] != "stash":
        return False
    first = toks[i + 1] if i + 1 < len(toks) else ""
    return first not in READ_ONLY


def decide(command: str):
    """'deny' reason string if COMMAND runs a state-changing git stash anywhere —
    directly, through a wrapper, inside a subshell/brace/if block, in the background,
    or via `$(...)`/backtick substitution — else None."""
    command = command or ""
    outer, inners = _extract_substitutions(command)
    for inner in inners:
        if decide(inner) is not None:
            return REASON

    toks = [t for t in _tokenize(outer) if t not in (")", "}")]
    group = []
    for t in toks:
        if t in _SEPARATORS:
            if _group_is_denied(group):
                return REASON
            group = []
        else:
            group.append(t)
    if _group_is_denied(group):
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
    deny = [
        "git stash", "git stash -u", "git stash push -m x", "git stash pop", "git stash apply",
        "git stash drop", "git stash clear", "git -C /tmp/x stash", "git add . && git stash -u",
        "FOO=1 git stash save wip", "cd a; git stash branch b", "git -c k=v stash",
        "git --git-dir=/x stash", "git --no-pager stash", "GIT_DIR=x git stash",
        "/usr/bin/git stash", "\\git stash", "git-stash push -m x",
        "git stash -m list", "git stash -m show", "git stash -- list",
        "(cd sub && git stash)", "(git stash)", "{ git stash; }",
        "if true; then git stash; fi", "time git stash", "nice git stash", "exec git stash",
        "git stash&", "bash -c 'git stash'", "echo $(git stash)", "eval git stash",
        "xargs git stash",
    ]
    allow = [
        "git stash list", "git stash show -p", "git status", "echo git stash", "git commit -m 'stash'",
        "ls stash", "git show HEAD:x", "git -C x stash list", "echo 'git stash'",
        "git log --grep stash", "grep stash file",
    ]
    bad = [c for c in deny if not decide(c)] + [c for c in allow if decide(c)]
    print("selftest ok" if not bad else f"selftest FAIL: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(_selftest() if "--selftest" in sys.argv else main())
