#!/usr/bin/env python3
"""The one list of index-shaping engine settings every reindex path forwards from .mcp.json.

A reindex run outside the query server (the SessionStart auto-reindex, the flywheel run,
doctor's repairs, setup.sh) must build the SAME index the server serves; a setting the server
reads from .mcp.json but the reindex does not see makes it rebuild at engine defaults and prune
what the server was configured with. INVARIANT: every engine setting that shapes the index
(which points exist, their vectors, where they live) belongs in ENGINE_ENV_KEYS. A value
already in the process environment wins; an unreadable .mcp.json falls back to the process
environment. Stdlib only, Python 3.9-compatible.

CLI (setup.sh):  engine_env.py [--root DIR] --exec CMD...
"""
import json
import os
import sys
from pathlib import Path

ENGINE_ENV_KEYS = (
    # store + embedder
    "SKILL_QDRANT_URL", "SKILL_COLLECTION", "SKILL_VECTOR_SIZE",
    "SKILL_EMBED_BACKEND", "SKILL_EMBED_MODEL", "SKILL_OLLAMA_URL", "SKILL_EMBED_TOKEN",
    # trigger layers
    "SKILL_MULTIVECTOR", "SKILL_LLM_TRIGGERS", "TRIGGERS_MAX", "SKILL_TRIGGERS",
    "SKILL_BODY_TRIGGERS", "SKILL_TRIGGER_PURITY", "SKILL_DECLARED_TRIGGERS",
    # which skills are discovered
    "SKILL_CONCIERGE_CATALOG_ROOTS", "SKILL_CODEX_ROOTS", "SKILL_COMMANDCODE_ROOTS",
    "SKILL_OMP_ROOTS", "SKILL_ZCODE_ROOTS", "SKILL_DSH_ROOTS", "SKILL_CLINE_ROOTS",
    "SKILL_OPENCODE_ROOTS", "SKILL_OPENCODE_HOME",
    "SKILL_HERMES_ROOTS", "SKILL_HERMES_HOME", "SKILL_HERMES_CONFIG",
    "SKILL_SYNCED_ROOTS", "SKILL_PLUGIN_FILTER", "SKILL_PLUGIN_LAYERED_ENABLEMENT",
    "SKILL_INSTALLED_PLUGINS", "SKILL_CLAUDE_SETTINGS", "SKILL_CLAUDE_PROJECTS_FILE",
    "SKILL_DSH_HOME", "SKILL_ZCODE_CONFIG", "SKILL_ZCODE_INSTALLED_PLUGINS",
    # what a reindex writes beside the index
    "SKILL_CONCIERGE_NEXT_SKILLS", "SKILL_META_PATH",
)

DEFAULT_ROOT = Path(__file__).resolve().parent.parent

# Machine-local engine settings that must NOT ship in `.mcp.json`: the bearer token above
# all (ADR-0097 says read it from the environment, never the descriptor), and the embedder
# URL, which is deployment-specific rather than a plugin default.
#
# Without this file the two keys reached a reindex ONLY through a shell that had sourced
# `~/.config/harness-env.sh`. A SessionStart hook is not such a shell: `selfheal.mcp_env`
# is exactly `os.environ` + `.mcp.json`, so a background reindex resolved
# SKILL_OLLAMA_URL to its `http://localhost:11434` DEFAULT and the token to empty —
# silently rebuilding points against a different embedder than the one serving queries.
# Measured 2026-11-07: 19,873 `catalog:antigravity` points stamped with the localhost
# embedder while 26,687 carried the GPU-host one. ADR-0098's provenance guard caught it.
LOCAL_ENV_PATH = Path(os.path.expandvars(os.environ.get(
    "SKILL_CONCIERGE_ENGINE_ENV",
    str(Path.home() / ".claude" / "skill-concierge" / "engine-env.json"))))


def local_engine_env(path=None):
    """The machine-local engine overrides, or {} when the file is absent/unreadable.

    Same shape as the `.mcp.json` env block. Fail-open on every bad input: a malformed
    file must degrade to "no overrides" (the engine's defaults), never raise into a hook.
    """
    try:
        conf = json.loads(Path(path or LOCAL_ENV_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(conf, dict):
        return {}
    return {k: v for k, v in conf.items()
            if k in ENGINE_ENV_KEYS and isinstance(v, str) and v != ""}


def engine_env(root=None):
    """os.environ plus every ENGINE_ENV_KEYS value the descriptor or the machine-local
    file pins and the environment lacks. Empty values are skipped: an empty flag would
    read as ON ("" != "0").

    Precedence, most authoritative first: the process environment (a caller that decided
    deliberately), the machine-local overrides, then `.mcp.json` (the shipped defaults).
    Local outranks the descriptor because the descriptor cannot carry a secret."""
    merged = dict(os.environ)
    try:
        conf = json.loads((Path(root or DEFAULT_ROOT) / ".mcp.json").read_text(encoding="utf-8"))[
            "mcpServers"]["skill-search"]["env"]
    except (OSError, ValueError, KeyError, TypeError):
        conf = {}
    for source in (local_engine_env(), conf if isinstance(conf, dict) else {}):
        for k in ENGINE_ENV_KEYS:
            v = source.get(k)
            if k not in merged and isinstance(v, str) and v != "":
                merged[k] = v
    return merged


def main(argv):
    root = DEFAULT_ROOT
    if argv[:1] == ["--root"] and len(argv) >= 2:
        root, argv = Path(argv[1]), argv[2:]
    if argv[:1] != ["--exec"] or len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    os.execvpe(argv[1], argv[1:], engine_env(root))
    return 0  # not reached


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
