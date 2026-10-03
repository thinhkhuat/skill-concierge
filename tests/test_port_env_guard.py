"""Static guard: `skill_search.ports` (vendor/skill-search/skill_search/ports.py) is the ONE
place in the repo that reads `SKILL_QDRANT_URL`, `EMBED_SHIM_PORT`, `SKILL_OWNER_QUERY_PORT`
or `SKILL_OWNER_EMBED_PORT` from an environment mapping. Patching the port rule caller by
caller never held, because nothing stopped a NEW raw read from creeping back in outside that
one home — this test is that stop.

It parses every `.py` file in the repo that git does not ignore (excluding `tests/` and `vendor/skill-search/tests/`,
which legitimately set these vars to configure the process under test, and `ports.py` itself)
and fails if any file contains a RAW READ of one of the four names from an environment-like
mapping:
  - `<anything>.get("<KEY>", ...)` / `<anything>.get("<KEY>")`
  - `os.getenv("<KEY>", ...)`
  - a subscript read `<anything>["<KEY>"]` (Load context only — an assignment target such as
    `env["<KEY>"] = value` is a WRITE and is never flagged)

`.setdefault("<KEY>", ...)` is a WRITE (it seeds a fixed literal default for a LATER,
ports.py-mediated read) and is likewise never flagged — see the ALLOWLIST entries below for
the two call sites that still do this on purpose, each with its own reason.

A caller that has already read the value into a plain local variable (`base = dict(os.environ)`
then `base["SKILL_QDRANT_URL"] = QURL`, or a literal-keyed dict `{**base, "SKILL_QDRANT_URL":
QURL}`) is a WRITE/forward too and never matches these patterns — only a literal-keyed READ of
one of the four names does.

Every exemption is an explicit (file, key) -> (count, reason) entry. A file not listed gets
zero raw reads; a listed file gets exactly the recorded count — one more occurrence than
recorded (a NEW raw read added later) still fails the guard.
"""
import ast
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

WATCHED_KEYS = ("SKILL_QDRANT_URL", "EMBED_SHIM_PORT",
                "SKILL_OWNER_QUERY_PORT", "SKILL_OWNER_EMBED_PORT")

PORTS_MODULE = "vendor/skill-search/skill_search/ports.py"

EXCLUDED_PREFIXES = ("tests/", "vendor/skill-search/tests/", ".git/", "__pycache__/")

# (relpath, key) -> (expected_count, reason). Every entry here would be a deliberate, narrow
# exception — a pure forwarder/setter, never a second copy of the port grammar. Empty: every
# caller in the repo routes through a skill_search.ports function; nothing needs one. Keep
# this dict (rather than deleting the mechanism) so a future caller that genuinely needs a
# raw read has somewhere to record why, instead of reaching for a bare `os.environ.get(...)`.
ALLOWLIST = {}


def _repo_py_files():
    """Tracked plus untracked-but-not-ignored `.py` files: git-ignored output (a stale
    `vendor/**/build/`, venvs) is not source and is never shipped. Without a usable git, every
    file on disk is scanned, as before."""
    try:
        out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", "*.py"],
                             cwd=ROOT, capture_output=True, check=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return sorted(ROOT.rglob("*.py"))
    return sorted({ROOT / rel for rel in out.decode().split("\0") if rel})


def _iter_py_files():
    for p in _repo_py_files():
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT).as_posix()
        if rel == PORTS_MODULE:
            continue
        if any(rel.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
            continue
        yield rel, p


def _literal_str(node):
    if node is not None and isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _subscript_key(node):
    """The literal string key of a Subscript node, across the pre-3.9 ast.Index wrapper and
    the 3.9+ bare-expression slice."""
    sl = node.slice
    if sl.__class__.__name__ == "Index":   # pragma: no cover - pre-3.9 AST shape
        sl = sl.value
    return _literal_str(sl)


class _RawReadFinder(ast.NodeVisitor):
    """Collects (key, lineno) for every raw READ of a watched key: `.get(KEY, ...)`,
    `os.getenv(KEY, ...)`, or a Load-context `[KEY]` subscript. `.setdefault(KEY, ...)` is
    deliberately NOT visited as a read (it establishes a default; it never returns the
    current value to a caller that would parse it as a port)."""

    def __init__(self):
        self.hits = []

    def visit_Call(self, node):
        func = node.func
        attr = func.attr if isinstance(func, ast.Attribute) else None
        name = func.id if isinstance(func, ast.Name) else None
        if node.args and (attr == "get" or attr == "getenv" or name == "getenv"):
            key = _literal_str(node.args[0])
            if key in WATCHED_KEYS:
                self.hits.append((key, node.lineno))
        self.generic_visit(node)

    def visit_Subscript(self, node):
        if isinstance(node.ctx, ast.Load):
            key = _subscript_key(node)
            if key in WATCHED_KEYS:
                self.hits.append((key, node.lineno))
        self.generic_visit(node)


def _scan(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    finder = _RawReadFinder()
    finder.visit(tree)
    return finder.hits


def test_no_raw_reads_of_the_watched_port_env_vars_outside_ports_py():
    violations = []
    seen_allowlist_keys = set()
    for rel, path in _iter_py_files():
        hits = _scan(path)
        if not hits:
            continue
        by_key = {}
        for key, lineno in hits:
            by_key.setdefault(key, []).append(lineno)
        for key, linenos in by_key.items():
            allowed_count, _reason = ALLOWLIST.get((rel, key), (0, None))
            if allowed_count:
                seen_allowlist_keys.add((rel, key))
            if len(linenos) > allowed_count:
                violations.append(
                    f"{rel}: {len(linenos)} raw read(s) of {key!r} at line(s) "
                    f"{linenos} (allowlisted: {allowed_count})")
    assert not violations, (
        "raw reads of a port-shaping env var found outside skill_search.ports — route them "
        "through a ports.py function, or add a justified ALLOWLIST entry:\n  "
        + "\n  ".join(violations))
    # An allowlist entry for a (file, key) that no longer reads it at all is dead weight that
    # would hide a REMOVED read looking like nothing changed — keep the list honest.
    stale = set(ALLOWLIST) - seen_allowlist_keys
    assert not stale, f"stale ALLOWLIST entries (no longer read raw): {sorted(stale)}"


def test_ports_module_itself_reads_every_watched_key():
    """Sanity check on the guard's own key list: ports.py must actually read all four names
    (otherwise the guard would be vacuously enforcing a rule with a hole in the key list)."""
    path = ROOT / PORTS_MODULE
    hits = _scan(path)
    found = {key for key, _ in hits}
    missing = set(WATCHED_KEYS) - found
    assert not missing, f"ports.py never reads {missing} — the guard's key list is incomplete"


# Shell scripts run before the vendored package is importable, so the two bash entry points
# keep a native `_safe_port`. Every OTHER shell expansion of a watched name is a raw read that
# would bypass it. These are the only lines allowed to expand one, each for a stated reason.
SHELL_ALLOWED_LINES = {
    ("bin/skill-search-mcp", 'EMBED_PORT="$(_safe_port "${EMBED_SHIM_PORT:-}" 6363)"'):
        "the launcher's one derivation through its own _safe_port",
    ("setup.sh", 'EPORT="$(_safe_port "${EMBED_SHIM_PORT:-}" 6363)"'):
        "setup.sh's one embed-port derivation through its own _safe_port",
    ("setup.sh", 'QURL="${SKILL_QDRANT_URL:-$(read_mcp SKILL_QDRANT_URL)}"'):
        "forwards the URL unparsed; the store port comes from skill_search.ports.url_port",
}

_SHELL_EXPANSION = __import__("re").compile(
    r"\$\{?(" + "|".join(WATCHED_KEYS) + r")\b")


def _shell_files():
    import subprocess
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files"], capture_output=True,
                         text=True, check=True).stdout.splitlines()
    return [f for f in out if f.endswith(".sh") or f.startswith("bin/")]


def _shell_expansions(text, rel):
    return [(rel, line.strip()) for line in text.splitlines()
            if _SHELL_EXPANSION.search(line) and not line.lstrip().startswith("#")]


def test_no_shell_script_expands_a_port_setting_outside_the_allowed_lines():
    found = []
    for rel in _shell_files():
        found += _shell_expansions((ROOT / rel).read_text(errors="replace"), rel)
    unexpected = [f for f in found if f not in SHELL_ALLOWED_LINES]
    assert not unexpected, f"raw shell reads of a port setting: {unexpected}"


def test_shell_guard_bites_on_a_raw_expansion():
    raw = 'if ! curl -s "http://127.0.0.1:${EMBED_SHIM_PORT:-6363}/health"; then :; fi'
    assert _shell_expansions(raw, "bin/skill-search-mcp") == [("bin/skill-search-mcp", raw)]
    assert _shell_expansions(raw, "bin/skill-search-mcp")[0] not in SHELL_ALLOWED_LINES
