"""A PATH for installer tests: the test's fake CLIs first, then links to the system tools the
installers and their doctor step use. The machine's own PATH is left out, so a real `claude`,
`codex`, `omp`, `zcode` or `docker` can never run under a test."""
import os
import shutil

_TOOLS = ("bash", "sh", "env", "python3", "git", "tar", "awk", "grep", "egrep", "sed", "diff", "cmp",
          "date", "mktemp", "mv", "rm", "mkdir", "rmdir", "chmod", "cat", "cp", "ln", "ls", "dirname",
          "basename", "head", "tail", "sort", "uniq", "find", "readlink", "realpath", "stat", "touch",
          "tr", "wc", "cut", "uname", "id", "xargs", "printf", "sleep", "tee", "true", "false", "expr",
          "test", "hostname", "whoami", "ps", "pgrep", "lsof", "curl", "shasum", "od", "file", "du")


def hermetic_path(tmp_path, *front):
    """`front` dirs (the fake CLIs), then a per-test dir of links to the tools above."""
    tools = tmp_path / "toolbin"
    if not tools.exists():
        tools.mkdir()
        for name in _TOOLS:
            src = shutil.which(name)
            if src:
                (tools / name).symlink_to(src)
    return os.pathsep.join([*map(str, front), str(tools)])


def installer_env(tmp_path, home, *front, **extra):
    """The environment an installer test runs under: throwaway HOME, hermetic PATH, no bytecode
    written into HOME by any Python, and a Qdrant URL that nothing answers."""
    return {**os.environ, "HOME": str(home), "PATH": hermetic_path(tmp_path, *front),
            "PYTHONDONTWRITEBYTECODE": "1", "SKILL_QDRANT_URL": "http://127.0.0.1:9",
            "EMBED_SHIM_PORT": "9", "SKILL_OWNER_AUTOSTART": "0", **extra}
