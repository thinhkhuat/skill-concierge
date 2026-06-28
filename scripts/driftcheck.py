#!/usr/bin/env python3
"""
driftcheck.py — a project-agnostic drift guard.

THE IDEA: any fact stated in 2+ places (a version in code AND in the README, a
test-count in the suite's output AND in the docs, a path in prose AND on disk)
will eventually drift. This guard names ONE source of truth (SSOT) per fact,
re-derives that fact from its SSOT at run time, and fails loudly if any copy
disagrees. It is the mechanical backstop against "the docs say X, the code does Y".

It is deliberately dumb and portable: Python 3.7+ stdlib only, no dependencies, no
network, no project assumptions. You describe your facts in a JSON config; this
engine checks them. Drop it into any repo — Python, JS, Rust, Go, docs-only — wire
it into your test run or CI, and a green build can no longer hide a stale copy you
declared. (It checks DECLARED facts only — it cannot find a duplicate you never wrote down.)

USAGE
    python3 driftcheck.py [config.json]      # default: ./driftcheck.json
    python3 driftcheck.py --help

Exit 0 = everything in sync. Exit 1 = drift (each mismatch printed). Exit 2 = bad config.
All paths in the config resolve relative to the CONFIG FILE's directory (the project root).

CONFIG SHAPE (see references/config-reference.md for the full spec + recipes)
    {
      "facts": [
        {
          "name": "version",
          "source": {"file": "pkg/__init__.py", "regex": "__version__ = \"([^\"]+)\""},
          "mirrors": [
            {"file": "README.md", "regex": "Status:\\s*v([0-9.]+)"},
            {"file": "README.md", "regex": "^### v([0-9.]+)", "occurrence": "first", "before": "## Changelog"}
          ]
        },
        {
          "name": "test-count",
          "source": {"command": "python3 test.py", "regex": "(\\d+ passed)", "env": {"GUARD_RUNNING": "1"}},
          "mirrors": [{"file": "README.md", "regex": "(\\d+ passed)", "before": "## Changelog"}]
        }
      ],
      "paths_exist": ["scripts/foo.py", "docs/"],
      "command_checks": [{"name": "toc-complete", "command": "python3 scripts/check_toc.py"}]
    }

Each source/mirror extracts CAPTURE GROUP 1 of its regex. `before`/`after` slice the
file to a region first (so historical sections — e.g. a changelog — can be excluded).
`occurrence` is "all" (default: every match must equal the SSOT) or "first".
"""
import json
import os
import re
import subprocess
import sys

problems = []
def drift(msg): problems.append(msg); print(f"  [DRIFT] {msg}")
def ok(msg):    print(f"  [ok]    {msg}")
def info(msg):  print(f"  [info]  {msg}")


def _slice(text, spec):
    """Restrict text to a region via optional 'before'/'after' literal markers."""
    if "after" in spec:
        i = text.find(spec["after"])
        if i != -1:
            text = text[i + len(spec["after"]):]
    if "before" in spec:
        i = text.find(spec["before"])
        if i != -1:
            text = text[:i]
    return text


def _read(root, rel):
    with open(os.path.join(root, rel), encoding="utf-8") as f:
        return f.read()


def _extract_source(root, src):
    """Return the SSOT value (capture group 1) from a file or a command's stdout."""
    if "file" in src:
        text = _read(root, src["file"])
        where = f"file {src['file']}"
    elif "command" in src:
        env = {**os.environ, **src.get("env", {})}
        text = subprocess.run(src["command"], shell=True, cwd=root, env=env,
                              capture_output=True, text=True, timeout=src.get("timeout", 120)).stdout
        where = f"command `{src['command']}`"
    else:
        raise ValueError("source needs a 'file' or 'command' key")
    m = re.search(src["regex"], _slice(text, src), re.M)
    if not m:
        raise LookupError(f"SSOT regex /{src['regex']}/ matched nothing in {where}")
    return m.group(1).strip(), where


def _check_mirror(root, fact_name, ssot, where, mir):
    text = _slice(_read(root, mir["file"]), mir)
    matches = [m.group(1).strip() for m in re.finditer(mir["regex"], text, re.M)]
    if not matches:
        drift(f"{fact_name}: mirror {mir['file']} — regex /{mir['regex']}/ matched nothing (expected {ssot!r})")
        return
    targets = matches[:1] if mir.get("occurrence") == "first" else matches
    bad = [v for v in targets if v != ssot]
    if bad:
        drift(f"{fact_name}: {mir['file']} has {sorted(set(bad))} but SSOT ({where}) is {ssot!r}")
    else:
        ok(f"{fact_name}: {mir['file']} matches SSOT {ssot!r} ({len(targets)} occurrence(s))")


def check_facts(root, facts):
    for fact in facts:
        name = fact.get("name", "?")
        try:
            ssot, where = _extract_source(root, fact["source"])
        except Exception as e:
            drift(f"{name}: cannot derive SSOT — {e}")
            continue
        info(f"{name}: SSOT = {ssot!r} (from {where})")
        for mir in fact.get("mirrors", []):
            try:
                _check_mirror(root, name, ssot, where, mir)
            except FileNotFoundError:
                drift(f"{name}: mirror file not found: {mir['file']}")


def check_paths(root, paths):
    for p in paths:
        if os.path.exists(os.path.join(root, p)):
            ok(f"path exists: {p}")
        else:
            drift(f"path missing: {p}")


def check_commands(root, checks):
    for c in checks:
        name = c.get("name", c["command"])
        rc = subprocess.run(c["command"], shell=True, cwd=root,
                            env={**os.environ, **c.get("env", {})}, timeout=c.get("timeout", 120)).returncode
        ok(f"command check passed: {name}") if rc == 0 else drift(f"command check failed (exit {rc}): {name}")


def main(argv):
    if "--help" in argv or "-h" in argv:
        print(__doc__); return 0
    cfg_path = next((a for a in argv[1:] if not a.startswith("-")), "driftcheck.json")
    if not os.path.exists(cfg_path):
        print(f"config not found: {cfg_path}\n(run with --help for the config shape)", file=sys.stderr); return 2
    try:
        cfg = json.load(open(cfg_path, encoding="utf-8"))
    except Exception as e:
        print(f"bad config JSON ({cfg_path}): {e}", file=sys.stderr); return 2
    root = os.path.dirname(os.path.abspath(cfg_path))

    print(f"drift-guard — {os.path.basename(cfg_path)} (root: {root})\n" + "=" * 48)
    if cfg.get("facts"):          print("facts:");          check_facts(root, cfg["facts"])
    if cfg.get("paths_exist"):    print("paths:");          check_paths(root, cfg["paths_exist"])
    if cfg.get("command_checks"): print("command checks:"); check_commands(root, cfg["command_checks"])
    print("=" * 48)
    if problems:
        print(f"DRIFT: {len(problems)} problem(s) — source of truth and its copies disagree.")
        return 1
    print("IN SYNC: every fact matches its source of truth.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
