"""Shared, symlink- and permission-safe atomic writer for every skill-concierge
installer's own JSON/registry writes.

WHY THIS EXISTS
    Each installer used to hand-roll its own tmp-file-then-rename write. Plain
    `os.replace(tmp, path)` on a SYMLINKED path swaps the symlink itself for a plain file
    — breaking a dotfiles-manager setup that points settings.json elsewhere — and a tmp
    file created under the shell's default umask silently widens a restrictive existing
    file (0600, an API-token-bearing mcp.json) to whatever the umask allows (typically
    0644). ADR-0072 fixed exactly this for the Claude Code registry write; this module IS
    that fix, factored out so every installer's write calls the SAME code instead of a
    hand-rolled copy that can (and did, for the Command Code installer) drift from it.

WHAT IT PROVIDES
    write_text(path, text)   — atomic write of a config file that may or may not exist yet
                                (Command Code's settings.json/mcp.json, OMP's dev-mode
                                config.yml, the Cline/ZCode manual MCP-fallback merges).
    write_registry(...)      — the registry-repoint pattern shared by the Claude Code, OMP
                                and ZCode installers: read, mutate in memory, refuse if the
                                file changed on disk since it was read (a live harness
                                session writing it), back up + rotate, atomic swap.

    Both resolve `path` through `os.path.realpath` first, so a symlinked config is updated
    at the file it points to (the symlink itself is left untouched), and both copy the
    existing target's mode onto the replacement whenever the target exists — the mode is
    kept exactly, never widened.
"""
import json
import os
import shutil
import time
from pathlib import Path


def _tmp_beside(real_path):
    return real_path.with_name(real_path.name + f".tmp-{os.getpid()}")


def write_text(path, text, encoding="utf-8"):
    """Atomically writes `text` to `path`. Resolves a symlink to its real target first (a
    plain, non-symlinked path resolves to itself); creates the target's parent dir if
    missing; keeps the target's existing mode when it already exists. Returns the real
    path that was written."""
    real = Path(os.path.realpath(path))
    real.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp_beside(real)
    tmp.write_text(text, encoding=encoding)
    if real.exists():
        shutil.copymode(real, tmp)
    os.replace(tmp, real)
    return real


def write_registry(path, mutate, backup_prefix, keep=5):
    """Reads the JSON registry at `path`, calls `mutate(data)` to change the parsed dict
    IN PLACE, and writes the result back — atomically, symlink- and mode-safe like
    `write_text` — but only if the file is UNCHANGED on disk since it was read (a live
    harness session could have written it in between); raises `RuntimeError` otherwise,
    with nothing written. Before the swap, the ORIGINAL bytes are saved as a backup BESIDE
    `path` itself — the location the harness actually reads, which stays the symlink's own
    directory when `path` is a symlink, not the dotfiles target it resolves to — named
    `<name>.bak-<backup_prefix>-<timestamp>-<pid>`; only the newest `keep` backups sharing
    `backup_prefix` are kept. Returns `(real_path_written, backup_path)`."""
    orig = Path(path)
    real = Path(os.path.realpath(orig))
    raw = real.read_bytes()
    data = json.loads(raw.decode("utf-8"))
    mutate(data)
    tmp = _tmp_beside(real)
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    shutil.copymode(real, tmp)
    if real.read_bytes() != raw:
        tmp.unlink()
        raise RuntimeError(f"{real} changed while this ran (a live session?) — not repointed; re-run")
    reg_dir = orig.parent
    backup = reg_dir / f"{orig.name}.bak-{backup_prefix}-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
    backup.write_bytes(raw)
    for old in sorted(reg_dir.glob(f"{orig.name}.bak-{backup_prefix}-*"))[:-keep]:
        old.unlink()
    os.replace(tmp, real)
    return real, backup
