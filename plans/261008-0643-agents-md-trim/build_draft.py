#!/usr/bin/env python3
"""Build the AGENTS.md / CLAUDE.md trim draft into ./draft/ and prove nothing was lost.

Moves the full "Repository layout" and "Runtime flags" sections of AGENTS.md verbatim
(relative links re-based for docs/) into docs/repository-layout.md and docs/runtime-flags.md,
replaces them in AGENTS.md with parts/*-compact.md, and collapses CLAUDE.md's governance-flags
bullet to a pointer. Reads the live repo files; writes only under ./draft/.
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT = HERE / "draft"
LINK = re.compile(r"\]\(([^)\s]+)\)")


def sections(text):
    """[(heading or '', body)] split on '## ' headings, heading line kept in body."""
    parts, cur, head = [], [], ""
    for ln in text.splitlines(keepends=True):
        if ln.startswith("## "):
            parts.append((head, "".join(cur)))
            cur, head = [], ln[3:].strip()
        cur.append(ln)
    parts.append((head, "".join(cur)))
    return parts


def rebase(text, to_dir):
    def fix(m):
        t = m.group(1)
        if re.match(r"^[a-z]+:", t) or t.startswith("#"):
            return m.group(0)
        path, _, frag = t.partition("#")
        new = os.path.relpath(REPO / path, REPO / to_dir)
        return "](" + new + ("#" + frag if frag else "") + ")"
    return LINK.sub(fix, text)


def body_without_heading(sec):
    return sec.split("\n", 1)[1].lstrip("\n")


agents = (REPO / "AGENTS.md").read_text(encoding="utf-8")
claude = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
secs = dict(sections(agents))
layout_old, flags_old = secs["Repository layout"], secs["Runtime flags"]

flags_doc = (
    "# Runtime flags — full reference\n\n"
    "Moved verbatim from `AGENTS.md` → *Runtime flags* on 2026-10-08 (only relative links re-based for `docs/`). "
    "`AGENTS.md` keeps the one-line index table and the two invariants; this file keeps each flag's full text. "
    "Edit a flag's entry here when you change its code or default, and its table row in `AGENTS.md` in the same commit.\n\n"
    + rebase(body_without_heading(flags_old), "docs")
)
layout_doc = (
    "# Repository layout — full reference\n\n"
    "Moved verbatim from `AGENTS.md` → *Repository layout* on 2026-10-08 (only relative links re-based for `docs/`). "
    "`AGENTS.md` keeps one line per area.\n\n"
    + rebase(body_without_heading(layout_old), "docs")
)
new_agents = agents.replace(layout_old, (HERE / "parts/layout-compact.md").read_text() + "\n") \
                   .replace(flags_old, (HERE / "parts/flags-compact.md").read_text() + "\n")

bullet = next(ln for ln in claude.splitlines(keepends=True) if ln.startswith("- **Governance flags"))
pointer = ("- **Governance flags (one-var reverts):** every flag, with its default, code and ADR, is indexed in "
           "[`AGENTS.md`](AGENTS.md) → *Runtime flags* (one-line table plus the `ENGINE_ENV_KEYS` invariant); each flag's "
           "full text, tuning knobs and preconditions are in [`docs/runtime-flags.md`](docs/runtime-flags.md). On this machine's Claude Code, "
           "`ENFORCER_MULTI_INTENT=0` is set in `~/.claude/settings.json` env as a trial "
           "([ADR-0055](docs/adr/0055-multi-intent-off-projection-pending.md)).\n")
new_claude = claude.replace(bullet, pointer)
OLD_TAIL = "Repo layout, full conventions, and guardrails are all in [`AGENTS.md`](AGENTS.md)."
assert new_claude.count(OLD_TAIL) == 1
new_claude = new_claude.replace(OLD_TAIL, "Repo layout, full conventions, and guardrails are all in [`AGENTS.md`](AGENTS.md); "
                                "per-file layout detail is in [`docs/repository-layout.md`](docs/repository-layout.md).")

if OUT.exists():
    shutil.rmtree(OUT)
(OUT / "docs").mkdir(parents=True)
files = {"AGENTS.md": new_agents, "CLAUDE.md": new_claude,
         "docs/runtime-flags.md": flags_doc, "docs/repository-layout.md": layout_doc}
for rel, text in files.items():
    (OUT / rel).write_text(text, encoding="utf-8")

fail = 0
flags_doc_moved = flags_doc  # the verbatim check below runs on this
# Corrections to the moved text, each found by the 2026-10-08 validator and checked in code:
CORRECTIONS = [
    ("which all five reindex paths (`auto_reindex.py`, `auto_flywheel.py`, `flywheel.py`, `doctor.py`, `setup.sh`) now call through",
     "which all six reindex paths (`auto_reindex.py`, `auto_flywheel.py`, `flywheel.py`, `doctor.py`, `setup.sh`, `trigger_filter.py reindex`) now call through"),
]
for a, b in CORRECTIONS:
    assert flags_doc.count(a) == 1, a[:50]
    flags_doc = flags_doc.replace(a, b)
flags_doc += ("\n- `SKILL_COMMANDCODE_ROOTS` (`vendor/skill-search/skill_search/skills_discovery.py`) — default ON (added 2026-10-08; "
              "the flag predates this file but had no entry): index Command Code's skill roots, `~/.commandcode/skills` and "
              "`<cwd>/.commandcode/skills`, alongside the other harnesses' roots. In `ENGINE_ENV_KEYS`. `=0` + a reindex "
              "reverts. [ADR-0038](adr/0038-command-code-triple-harness-parity.md).\n")
files["docs/runtime-flags.md"] = flags_doc
(OUT / "docs/runtime-flags.md").write_text(flags_doc, encoding="utf-8")
# 1. Verbatim move: every old line (link-rebased) appears in the new doc.
for name, old, doc in (("flags", flags_old, flags_doc_moved), ("layout", layout_old, layout_doc)):
    lost = [ln for ln in rebase(body_without_heading(old), "docs").splitlines() if ln.strip() and ln not in doc]
    print(f"[verbatim {name}] lines lost: {len(lost)}")
    fail |= bool(lost)

# 2. CLAUDE.md bullet: every backtick token, ADR number and decimal number survives somewhere.
union = "\n".join(files.values())
tokens = set(re.findall(r"`([^`]+)`", bullet)) | set(re.findall(r"ADR-\d{4}", bullet)) \
    | set(re.findall(r"\b\d+\.\d+\b", bullet))
# Same fact, other spelling in the new files (checked by hand, 2026-10-08):
EQUIV = {"SKILL_REPUTATION_PULL_MAX=0": "`SKILL_REPUTATION_PULL_MAX` (2; `0` keeps the badges",
         "hooks/scripts/skill_exclusions.py": "`skill_exclusions.py` (PostToolUse(Skill|get_skill)",
         "~/.codex/**": "`~/.codex/skills` + `~/.codex/plugins/cache/**`"}
missing = sorted(t for t in tokens if t not in union and t.replace("ADR-", "") not in union
                 and EQUIV.get(t, "\0") not in union)
print(f"[claude bullet] {len(tokens)} tokens checked, missing: {missing}")
fail |= bool(missing)

# 3. Every relative link resolves from the file's future location in the repo.
for rel, text in files.items():
    base = (REPO / rel).parent
    for t in LINK.findall(text):
        if re.match(r"^[a-z]+:", t) or t.startswith("#"):
            continue
        p = (base / t.split("#")[0]).resolve()
        future = OUT / os.path.relpath(p, REPO)
        if not (p.exists() or future.exists()):
            print(f"[link] BROKEN in {rel}: {t}")
            fail = 1

# 4. Repo guards against the draft (skill-list parity, scratch-dir parity).
env = dict(os.environ, SKILL_CONCIERGE_ROOT=str(OUT))
os.symlink(REPO / "skills", OUT / "skills")
r = subprocess.run([sys.executable, str(REPO / "scripts/check_skill_list_parity.py")], env=env,
                   capture_output=True, text=True)
print(r.stdout.strip() or r.stderr.strip()); fail |= r.returncode
(OUT / "scripts").mkdir()
shutil.copy(REPO / "scripts/check_doc_parity.py", OUT / "scripts/")
r = subprocess.run([sys.executable, str(OUT / "scripts/check_doc_parity.py")], capture_output=True, text=True)
print(r.stdout.strip() or r.stderr.strip()); fail |= r.returncode
shutil.rmtree(OUT / "scripts"); os.unlink(OUT / "skills")

# 5. Sizes.
for rel in ("AGENTS.md", "CLAUDE.md"):
    print(f"[size] {rel}: {len((REPO / rel).read_bytes()):,} -> {len(files[rel].encode()):,} bytes")
for rel in ("docs/runtime-flags.md", "docs/repository-layout.md"):
    print(f"[size] {rel}: new, {len(files[rel].encode()):,} bytes")
print("RESULT:", "FAIL" if fail else "PASS")
sys.exit(1 if fail else 0)
