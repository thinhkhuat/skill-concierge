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
    Every word of every command is checked, not just the first: wherever a `git` word
    (any path to it, `\\git`, or the fused `git-stash`) appears, the guard skips git's
    own global options (`-C <path>`, `-c k=v`, `--git-dir=`, `--no-pager`, …) and, if the
    subcommand is `stash`, DENIES unless the next word is exactly `list` or `show`.
    Checking every position, instead of stripping a known list of prefixes, is what
    makes wrappers and their options (`nice -n 10`, `time -p`, `sudo -u x`, `env A=1`),
    shell keywords (`if`/`then`, `case … in x)`), grouping (`( … )`, `{ …; }`) and
    environment prefixes (`GIT_DIR=x`) irrelevant: none of them can hide the git word.
    Also checked, recursively: a shell running a command string (`bash -c '…'`,
    `bash -lc '…'`, `$SHELL -c '…'`: any shell name or variable followed by a flag
    cluster holding `c`), `eval`'s arguments, and command substitution (`$(…)`, backticks)
    wherever it sits. Separators (`&&`, `||`, `;`, `|`, `&`, newline) split commands.

    A command that only mentions the word inside a quoted string (a commit message,
    `git log --grep stash`, `echo 'git stash'`) passes. An UNQUOTED `git stash` anywhere
    in a command is denied even when it is only an argument (`echo git stash`): the
    guard fails safe rather than guess which words a program will execute.

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
REASON_TOO_COMPLEX = (
    "This command is too large or too deeply nested for the git-stash guard to check in time, "
    "so it is blocked rather than let through unchecked (a hook that times out does not block). "
    "Split it into smaller commands, or write long text to a file first. Deliberate human "
    "override: GIT_STASH_GUARD=0.")
# Characters one verdict may examine, recursion included, plus 10 per nested check. A
# 10,000-line script costs about 400,000; the cap keeps the slowest command near one second,
# far inside the hook's 10 s timeout.
_WORK_LIMIT = 1_000_000


class _TooComplex(Exception):
    pass

_GIT_GLOBAL_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}
_SHELLS = {"bash", "sh", "zsh", "dash", "ksh", "mksh", "ash", "yash", "posh", "fish",
           "csh", "tcsh", "pwsh"}
_SEPARATORS = {"&&", "||", ";", "|", "&"}
_VAR_WORD_RE = re.compile(r"^\$(\{[^}]*\}|[A-Za-z_0-9]+)$")    # $SHELL, ${SHELL:-bash}
_C_FLAG_RE = re.compile(r"^-[A-Za-z]*c[A-Za-z]*$")             # -c, -lc, -ic, -xc

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


def _stash_first_arg_denied(toks, i):
    """TOKS[i] is `stash` (or just past `git-stash`); deny unless the next word is a
    read-only subcommand."""
    first = toks[i] if i < len(toks) else ""
    return first not in READ_ONLY


def _group_is_denied(toks, budget):
    """TOKS is one already-separated command (no `&&`/`;`/`|`/`&` inside it). Return
    True if ANY word in it starts a state-changing `git stash`, whatever precedes it."""
    shell_checked = eval_checked = False
    for idx, tok in enumerate(toks):
        base = os.path.basename(tok)
        if not shell_checked and (base in _SHELLS or _VAR_WORD_RE.match(tok)):
            # `-c` alone or inside a flag cluster (`-lc`, `-ic`): the shell runs its first
            # operand. Every later operand, and the word right after each such cluster, is
            # checked, so no option can shift the command string out of view. Only the
            # first shell word per command needs this: a later one's words are a subset of
            # these, and checking each would cost time quadratic in the command's length.
            shell_checked = True
            rest = toks[idx + 1:]
            if any(_C_FLAG_RE.match(t) for t in rest) and any(
                    (not t.startswith("-") or (j and _C_FLAG_RE.match(rest[j - 1])))
                    and _decide(t, budget) is not None for j, t in enumerate(rest)):
                return True
        elif base == "eval" and not eval_checked and idx + 1 < len(toks):
            # The first `eval` checks everything after it; a later one's words are a subset.
            # Checking each would double the work per `eval`.
            eval_checked = True
            if _decide(" ".join(toks[idx + 1:]), budget) is not None:
                return True
        elif base == "git-stash":
            if _stash_first_arg_denied(toks, idx + 1):
                return True
        elif base == "git":
            i = idx + 1
            while i < len(toks) and toks[i].startswith("-"):   # git -C <path>, -c k=v, ...
                i += 2 if toks[i] in _GIT_GLOBAL_WITH_VALUE and i + 1 < len(toks) else 1
            if i < len(toks) and toks[i] == "stash" and _stash_first_arg_denied(toks, i + 1):
                return True
    return False


def decide(command: str):
    """'deny' reason string if COMMAND runs a state-changing git stash anywhere in it
    (any word position, a shell `-c` string, `eval`, or a `$(...)`/backtick
    substitution), else None. A command too large or too deeply nested to check within
    _WORK_LIMIT is denied with REASON_TOO_COMPLEX: a hook that times out, or crashes and
    fails open, would let it through unchecked."""
    try:
        return _decide(command or "", [_WORK_LIMIT])
    except (_TooComplex, RecursionError):
        return REASON_TOO_COMPLEX


def _decide(command, budget):
    budget[0] -= len(command) + 10          # a fixed share for the call itself
    if budget[0] < 0:
        raise _TooComplex
    outer, inners = _extract_substitutions(command)
    for inner in inners:
        if _decide(inner, budget) is not None:
            return REASON

    toks = [t for t in _tokenize(outer) if t not in (")", "}")]
    group = []
    for t in toks:
        if t in _SEPARATORS:
            if _group_is_denied(group, budget):
                return REASON
            group = []
        else:
            group.append(t)
    if _group_is_denied(group, budget):
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
        "xargs git stash", "echo git stash",
        "case x in x) git stash;; esac", "nice -n 10 git stash", "time -p git stash",
        "sudo -u me git stash", "env -i A=1 git stash", "eval 'git stash'",
        "bash -lc 'git stash'", "zsh -ic 'git stash'", "$SHELL -c 'git stash'",
        "bash -c -- 'git stash'", "# don't touch\ngit stash\n# it's fine", "# it's\n(git stash)",
    ]
    allow = [
        "git stash list", "git stash show -p", "git status", "git commit -m 'stash'",
        "ls stash", "git show HEAD:x", "git -C x stash list", "echo 'git stash'",
        "git log --grep stash", "grep stash file",
    ]
    bad = [c for c in deny if not decide(c)] + [c for c in allow if decide(c)]
    print("selftest ok" if not bad else f"selftest FAIL: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(_selftest() if "--selftest" in sys.argv else main())
