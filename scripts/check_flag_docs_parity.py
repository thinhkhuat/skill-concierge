#!/usr/bin/env python3
"""Flag-docs parity: the AGENTS.md "Runtime flags" table, docs/runtime-flags.md and the code agree.

Each runtime flag is described twice: a one-line row in the AGENTS.md table and a full entry in
docs/runtime-flags.md. SSOT for a flag's default = the code's `os.environ.get("<FLAG>", "<0|1>")`
(hooks/scripts, vendor/skill-search/skill_search, scripts, bin). Fails when:
  - a full entry (`- `FLAG` (...` bullet) in docs/runtime-flags.md has no table row;
  - a table row's flag is never named in docs/runtime-flags.md;
  - a table row's ON/OFF default, or a docs entry's stated default, differs from the code default;
  - a table row says ON/OFF but no code default for that flag exists;
  - a docs entry states no default ("default ON", "default OFF", "default `0`/`1`", or "Unset = `<v>`");
  - a setting that is not on/off (table cell "unset = `<v>`", e.g. `ENFORCER_JEV_BENCH`) differs between
    the table, its docs entry ("Unset = `<v>`") and the code's string default, where an f-string's
    `{CONST}` reads as `<ENV>` when the code sets `CONST = os.environ.get("ENV", ...)`; an empty-string
    default is written "unset = (empty)" in both places (e.g. `ENFORCER_JEV_TIER`);
  - a table default cell is neither ON/OFF nor "unset = `<v>`".
Stdlib-only. Exit 0 = parity, 1 = drift.
ROOT override via SKILL_CONCIERGE_ROOT (used by tests/test_flag_docs_parity.py)."""
import os
import re
import sys
from pathlib import Path

ROOT = Path(os.environ.get("SKILL_CONCIERGE_ROOT", Path(__file__).resolve().parent.parent))
CODE_DIRS = ("hooks/scripts", "vendor/skill-search/skill_search", "scripts", "bin")
ROW = re.compile(r"^\| `([A-Z][A-Z0-9_]+)` \| ([^|]+) \|", re.M)
ENTRY = re.compile(r"^- `([A-Z][A-Z0-9_]+)` \(", re.M)
DOC_DEFAULT = re.compile(r"default\W{0,4}(ON|OFF|`0`|`1`)")


def section(text, heading):
    m = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1) if m else ""


def on_off(cell):
    word = cell.strip().split()[0] if cell.strip() else ""
    return word if word in ("ON", "OFF") else None


def code_defaults():
    found = {}
    pat = re.compile(r"""["']([A-Z][A-Z0-9_]+)["']\s*,\s*(?:os\.environ\.get\([^)]*?,\s*)?["']([01])["']""")
    for d in CODE_DIRS:
        base = ROOT / d
        if not base.is_dir():
            continue
        for f in base.rglob("*"):
            if not f.is_file() or f.suffix not in ("", ".py"):
                continue
            try:
                text = f.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            for flag, val in pat.findall(text):
                found.setdefault(flag, set()).add("ON" if val == "1" else "OFF")
    return found


def code_strings():
    """Non-boolean defaults: {FLAG: {default with every {CONST} shown as <ENV>}}."""
    texts = []
    for d in CODE_DIRS:
        base = ROOT / d
        if base.is_dir():
            texts += [f.read_text(encoding="utf-8", errors="ignore") for f in base.rglob("*.py")]
    blob = "\n".join(texts)
    consts = dict(re.findall(r"""^(\w+)\s*=\s*[\w.]*?os\.environ\.get\(\s*["']([A-Z][A-Z0-9_]+)["']""", blob, re.M))
    out = {}
    for flag, val in re.findall(r"""os\.environ\.get\(\s*["']([A-Z][A-Z0-9_]+)["']\s*,\s*f?["']([^"']*)["']""", blob):
        val = re.sub(r"\{(\w+)\}", lambda m: f"<{consts.get(m.group(1), m.group(1))}>", val)
        out.setdefault(flag, set()).add(val)
    return out


agents = section((ROOT / "AGENTS.md").read_text(encoding="utf-8"), "Runtime flags")
docs = (ROOT / "docs" / "runtime-flags.md").read_text(encoding="utf-8")
rows = dict(ROW.findall(agents))
if not rows:
    print("flag-docs-parity: no flag table found under AGENTS.md '## Runtime flags'"); sys.exit(1)

entries = {}   # flag -> its bullet text up to the next bullet
heads = list(ENTRY.finditer(docs))
for i, m in enumerate(heads):
    end = heads[i + 1].start() if i + 1 < len(heads) else len(docs)
    entries.setdefault(m.group(1), docs[m.start():end])

code = code_defaults()
strings = code_strings()
UNSET = re.compile(r"[Uu]nset = (?:`([^`]+)`|\(empty\))")
problems = []
n_table = n_docs = 0
for flag in sorted(set(entries) - set(rows)):
    problems.append(f"docs/runtime-flags.md has an entry for {flag} but the AGENTS.md table has no row")
for flag in sorted(rows):
    if f"`{flag}`" not in docs and f"{flag}=" not in docs:
        problems.append(f"AGENTS.md table row {flag} is never named in docs/runtime-flags.md")
    want = on_off(rows[flag])
    if want is None:
        m = UNSET.match(rows[flag].strip())
        if not m:
            problems.append(f"AGENTS.md row {flag} has a default cell that is neither ON/OFF nor 'unset = `<v>`'")
            continue
        v, n_table = m.group(1) or "", n_table + 1
        said = f"nset = `{v}`" if v else "nset = (empty)"
        if said not in entries.get(flag, ""):
            problems.append(f"AGENTS.md says {flag} unset = {v!r}, its docs entry does not say 'U{said}'")
        if v not in strings.get(flag, set()):
            problems.append(f"AGENTS.md says {flag} unset = {v!r}, code says {sorted(strings.get(flag, set()))}")
        continue
    have = code.get(flag)
    n_table += 1
    if not have:
        problems.append(f"AGENTS.md says {flag} defaults {want}, but no code default for it was found")
    elif want not in have or len(have) > 1:
        problems.append(f"AGENTS.md says {flag} defaults {want}, code says {sorted(have)}")
for flag, text in sorted(entries.items()):
    m = DOC_DEFAULT.search(text)
    if not m and not UNSET.search(text):
        problems.append(f"docs/runtime-flags.md entry {flag} states no default")
        continue
    have = code.get(flag)
    if not m or not have or len(have) > 1:
        continue
    n_docs += 1
    said = {"`0`": "OFF", "`1`": "ON"}.get(m.group(1), m.group(1))
    if said not in have:
        problems.append(f"docs/runtime-flags.md says {flag} defaults {said}, code says {sorted(have)}")

if problems:
    print("flag-docs-parity DRIFT:")
    for p in problems:
        print(f"  {p}")
    sys.exit(1)
print(f"flag-docs-parity OK: {len(rows)} table rows, {len(entries)} full entries; "
      f"{n_table} table defaults and {n_docs} stated docs defaults match the code")
sys.exit(0)
