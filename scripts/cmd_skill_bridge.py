#!/usr/bin/env python3
"""skill-concierge — the Command Code colon-name skill bridge.

Command Code validates a skill's frontmatter `name` strictly: lowercase letters, numbers and
single hyphens, at most 64 characters, and the skill's own directory must carry that same
name. A skill whose `name` breaks a rule is SKIPPED at discovery — it is not in `/skills`, not
in the `/` menu, not in the model's skill catalogue, and `/skill-name` cannot reach it.

The agentkit corpus (`ak:fix`, `ak:plan`, …) and several personal skills (`ck:copywriting`,
`ckm:competitor`, `microsoft-foundry:resource/create`) name themselves with a colon. Claude Code
resolves `ak:fix` to the `ak-fix` directory it already lives in; Command Code has no such rule,
so those skills simply never load there. A skill's DIRECTORY name is what every other layer uses
(the concierge's own index, its menu, the ledger), and it is already the legal name.

This module closes that gap without touching a single source file: it MATERIALIZES a normalized
copy of every unusable skill into a shelf directory that the `skill-bridge` Command Code mod
registers with `cmd.addSkillsPath()`. Each copy carries a legal `name:` matching its own
directory, so Command Code loads it and the model invokes `/ak-fix` — the name the concierge
menu has always shown.

Why a copy and not an edit: the source corpus is the user's (and agentkit's) file, and on this
machine `~/.commandcode/skills` is a SYMLINK to `~/.claude/skills`, so an in-place "fix" would
rewrite the Claude Code originals. Every source SKILL.md is therefore hashed into the manifest
and re-checked by `verify`, which proves the originals were never modified.

Rewrites applied to a copy, never to a source:
  • the top-level frontmatter `name:` becomes the normalized name;
  • in-body `<prefix>:<slug>` references (`ak:scout`, `/ak:scook`, aliases in prose) become
    `<prefix>-<slug>`, restricted to prefixes actually seen in frontmatter so `10:30`, `https://`
    and a `name: ak:<slug>` template placeholder are never touched;
  • relative references to a sibling skill (`../ak-brainstorm/references/x.md`) are re-resolved
    against the shelf, so a skill nested under a grouping directory (`ak-document-skills/ak-pptx`)
    keeps working after being flattened to the shelf's top level.

Commands: `build` (default), `verify`, `clean`, `list`. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

SHELF_ENV = "SKILL_CONCIERGE_BRIDGE_SHELF"
SHELF_DEFAULT = Path.home() / ".commandcode" / "skill-concierge-bridge"
MANIFEST_NAME = "_bridge.json"
MANIFEST_VERSION = 1
MAX_NAME = 64

# Command Code's own discovery rules, as the docs state them: "Use lowercase letters, numbers,
# and hyphens only / Max 64 characters / Must not start or end with hyphen / No consecutive
# hyphens", plus "The directory name must match the skill `name` field".
_LEGAL_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

# A skill's OWN subfolders are never scanned for more skills, so a nested skill directory found
# inside a skill is bridged separately and must not be copied along as payload. These never hold
# skills and are skipped outright.
SKIP_DIRS = {"node_modules", "__pycache__", ".git", ".venv", "venv", "synced", "plugins",
             ".claude-plugin", ".commandcode"}
TEXT_SUFFIX = ".md"
MAX_DEPTH = 3


# ── names ─────────────────────────────────────────────────────────────────────

def is_legal(name) -> bool:
    """True iff Command Code would accept this as a skill name (and, therefore, a directory)."""
    return bool(name) and len(name) <= MAX_NAME and bool(_LEGAL_RE.match(name))


def illegal_reasons(name) -> list:
    """Every rule `name` breaks, each named individually so a report says WHY, not just "invalid"."""
    if not name:
        return ["empty"]
    reasons = []
    if len(name) > MAX_NAME:
        reasons.append("too-long")
    if ":" in name:
        reasons.append("colon")
    if "/" in name:
        reasons.append("slash")
    if "_" in name:
        reasons.append("underscore")
    if " " in name:
        reasons.append("space")
    if any(c.isupper() for c in name):
        reasons.append("uppercase")
    if name.startswith("-"):
        reasons.append("leading-hyphen")
    if name.endswith("-"):
        reasons.append("trailing-hyphen")
    if "--" in name:
        reasons.append("consecutive-hyphens")
    if re.search(r"[^a-z0-9-]", name):
        reasons.append("illegal-char")
    return reasons


def normalize(name) -> str:
    """The Command Code name a skill's declared name maps onto: `ak:fix` -> `ak-fix`.

    Every illegal class is folded to a single hyphen, runs are collapsed, and the 64-character
    cap is applied without leaving a trailing hyphen (which would itself be illegal)."""
    s = str(name or "").strip().strip("\"'").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    if len(s) > MAX_NAME:
        s = s[:MAX_NAME].rstrip("-")
    return s


def frontmatter_name(text):
    """The top-level `name:` of a SKILL.md, or None. Indented keys (`metadata: name:`) are not it,
    and the scan stops at the closing `---` so a body line that starts with `name:` is ignored."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            return None
        m = re.match(r"^name:\s*(.+?)\s*$", line)
        if m:
            return m.group(1).strip().strip("\"'")
    return None


# ── discovery ─────────────────────────────────────────────────────────────────

def _iter_skill_dirs(root: Path, max_depth: int = MAX_DEPTH):
    """(skill directory, nested) under `root`, down to `max_depth`.

    Acting on the rule Command Code states, a directory that directly holds a SKILL.md is a skill
    and is never scanned for more skills. This walker still descends through one, because the
    corpus has skill FAMILIES: `ak-document-skills/ak-pptx` is a real skill (`name: ak:pptx`)
    sitting inside a skill. A nested skill is only ever bridged when Command Code cannot load it
    (`ak:pptx`), so a deliberate internal module with a legal name (`app-builder/templates`,
    `fable-mode/fable-opus`) stays exactly where it is — payload of its parent."""
    if not root.is_dir():
        return
    stack = [(root, 1, False)]
    while stack:
        d, depth, inside = stack.pop()
        is_skill = d != root and (d / "SKILL.md").is_file()
        if is_skill:
            yield d, inside
        if depth >= max_depth:
            continue
        try:
            entries = sorted(d.iterdir())
        except OSError:
            continue
        for item in entries:
            if not item.is_dir() or item.name in SKIP_DIRS or item.name.startswith("."):
                continue
            stack.append((item, depth + 1, inside or is_skill))


def discover(roots) -> list:
    """Every skill directory under `roots`, realpath-deduped (so the ~/.commandcode/skills
    symlink to ~/.claude/skills is one corpus, not two). Sorted for a stable build order."""
    out, seen = [], set()
    for root in roots:
        root = Path(root).expanduser()
        for d, nested in _iter_skill_dirs(root):
            try:
                key = os.path.realpath(str(d))
            except OSError:
                continue
            if key in seen:
                continue
            seen.add(key)
            skill_md = d / "SKILL.md"
            try:
                text = skill_md.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            out.append({"skill_dir": d, "skill_md": skill_md, "text": text,
                        "raw": frontmatter_name(text), "dir_name": d.name,
                        "nested": nested, "root": root})
    out.sort(key=lambda r: str(r["skill_dir"]))
    return out


def classify(records) -> tuple:
    """Split discovery into (plan, collisions).

    A skill is bridged when Command Code cannot load it as it stands: its `name` is illegal, or
    it is legal but names a different directory than the one it lives in. Anything already legal
    AND correctly named is left alone. On a normalized-name collision the first source (by sorted
    path) wins and the loser is REPORTED, mirroring Command Code's own "never drop a row
    silently" rule for duplicate names."""
    plan, collisions = {}, []
    for rec in records:
        raw, dash = rec["raw"], rec["dash"]
        if raw is None or not is_legal(dash):
            continue
        if is_legal(raw) and raw == rec["dir_name"]:
            continue                              # already loadable: nothing to bridge
        reason = "dir-mismatch" if is_legal(raw) else ",".join(illegal_reasons(raw))
        prior = plan.get(dash)
        if prior is not None:
            collisions.append({"dash": dash, "winner": str(prior["skill_dir"]),
                               "loser": str(rec["skill_dir"]), "raw": raw})
            continue
        plan[dash] = {"dash": dash, "raw": raw, "source": str(rec["skill_dir"]),
                      "reason": reason, "skill_dir": rec["skill_dir"]}
    return plan, collisions


def _scan(roots) -> tuple:
    """(records, plan, collisions, warnings) — discovery plus classification in one pass, with each
    record carrying the normalized name it would get and the reason it cannot be loaded."""
    records = discover(roots)
    for rec in records:
        rec["dash"] = normalize(rec["raw"]) if rec["raw"] else ""
    plan, collisions = classify(records)
    warnings = []
    for rec in records:
        raw = rec["raw"]
        if raw is None:
            warnings.append(f"{rec['skill_dir']}: no frontmatter `name:` — Command Code requires "
                            "the field, so this bridge cannot help it")
        elif not is_legal(rec["dash"]):
            warnings.append(f"{rec['skill_dir']}: `name: {raw}` normalizes to {rec['dash']!r}, "
                            "which is still not a legal Command Code name — skipped")
    for c in collisions:
        warnings.append(f"{c['loser']}: `{c['raw']}` collides with {c['winner']} on the name "
                        f"{c['dash']!r} — the first wins, this one is not bridged")
    return records, plan, collisions, warnings


# ── rewrites (applied to copies only) ─────────────────────────────────────────

def rewrite_frontmatter_name(text: str, new_name: str) -> str:
    """Replace the top-level `name:` value, preserving every other byte (quoting style included,
    since the replacement is written bare). No `name:` in the frontmatter leaves the text alone —
    that case is reported rather than invented."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return text
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            break
        if re.match(r"^name:\s*\S", line):
            lines[i] = f"name: {new_name}"
            break
    return "\n".join(lines)


# A reference only counts at a token boundary. A leading `/` IS one (the slash-invocation form
# the corpus uses: "run /ak:cook"), so the guard is an explicit boundary set rather than a
# lookbehind that would exclude `/` along with the rest.
_BOUNDARY = set(" \t\n\r([{<\"'`*>-/|")


def rewrite_colons(text: str, prefixes) -> str:
    """`<prefix>:<slug>` -> `<prefix>-<slug>` for the prefixes actually seen in frontmatter.

    Restricting to known prefixes is what keeps this safe: `10:30`, a YAML `key:`, a colon inside
    a URL path and a `name: ak:<slug>` template placeholder (the slug would start with `<`) all
    survive. The slug class has no dot, so `ak:fix.` -> `ak-fix.` rather than swallowing the
    sentence's period."""
    if not prefixes:
        return text
    alt = "|".join(re.escape(p) for p in sorted(prefixes, key=len, reverse=True) if p)
    if not alt:
        return text
    pattern = re.compile(r"(" + alt + r"):([A-Za-z0-9][A-Za-z0-9-]*(?:/[A-Za-z0-9-]+)*)")

    def sub(m):
        i = m.start()
        if i and text[i - 1] not in _BOUNDARY:
            return m.group(0)                 # mid-word (`xak:fix`), not a reference
        j = i
        while j > 0 and not text[j - 1].isspace():
            j -= 1
        if "://" in text[j:i]:
            return m.group(0)                 # inside a URL, never a skill invocation
        return f"{m.group(1)}-{m.group(2).lower().replace('/', '-')}"

    return pattern.sub(sub, text)


_REL_RE = re.compile(r"(?<![\w./-])((?:\.\./)+)([A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9._/-]*)?)")


def rewrite_relpaths(text: str, ctx: dict) -> str:
    """Re-resolve a relative reference to a BRIDGED sibling skill against the shelf copy.

    The copy keeps the skill's own internal layout, so an unchanged `../ak-x/f.md` stays correct
    whenever the two skills sit at the same depth. Only a flat-source/nested-source mismatch moves
    the answer — a skill nested one level deeper (`ak-document-skills/ak-pptx`) loses exactly one
    `../`. A reference that resolves to a skill this bridge did NOT copy is left alone and
    reported, since no rewrite can make it reachable from the shelf."""
    bridged, all_dirs = ctx["bridged"], ctx["all_dirs"]

    def sub(m):
        raw = m.group(0)
        base = Path(ctx["src_skill"]) / ctx["file_rel"]
        target = os.path.normpath(os.path.join(os.path.dirname(str(base)), raw))
        for src_dir, shelf_dir in bridged:
            if target == src_dir or target.startswith(src_dir + os.sep):
                rest = target[len(src_dir):].lstrip(os.sep)
                new_target = os.path.join(shelf_dir, rest) if rest else shelf_dir
                new_rel = os.path.relpath(new_target, os.path.dirname(
                    str(Path(ctx["dst_skill"]) / ctx["file_rel"])))
                return new_rel
        if any(target == d or target.startswith(d + os.sep) for d in all_dirs):
            ctx["dangling"].append(f"{ctx['dash']}/{ctx['file_rel']}: `{raw}` points at a skill "
                                   "this bridge did not copy; it cannot resolve from the shelf")
        return raw

    return _REL_RE.sub(sub, text)


# ── materializing a copy ──────────────────────────────────────────────────────

def _copy_tree(src_dir: Path, dst_dir: Path, entry: dict, prefixes, ctx: dict) -> None:
    """Copy one skill directory into the shelf, rewriting text files as they land.

    A nested skill inside the source is copied along with everything else: Command Code never
    scans a skill's own subfolders, so an `ak-docx/SKILL.md` under a copy is inert to it, while
    the container's own links to `ak-docx/SKILL.md` keep resolving. Each nested SKILL.md still
    gets its own bridged name, so nothing in the copy depends on an illegal one."""
    ctx["dst_root"] = str(dst_dir)
    _copy_tree_rel(src_dir, dst_dir, src_dir, entry, prefixes, ctx)


def _copy_tree_rel(src: Path, out: Path, src_dir: Path, entry, prefixes, ctx) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for item in sorted(src.iterdir()):
        o = out / item.name
        if item.is_dir():
            if item.name in SKIP_DIRS or item.name.startswith("."):
                continue
            _copy_tree_rel(item, o, src_dir, entry, prefixes, ctx)
        else:
            _copy_file_rel(item, o, src_dir, entry, prefixes, ctx)


def _copy_file_rel(src: Path, out: Path, src_dir: Path, entry, prefixes, ctx) -> None:
    file_rel = str(src.relative_to(src_dir))
    try:
        if src.suffix == TEXT_SUFFIX:
            text = src.read_text(encoding="utf-8", errors="strict")
        else:
            text = None
    except (OSError, UnicodeError):
        text = None                            # binary or undecodable: byte copy below
    if text is None:
        shutil.copy2(src, out)
        return
    if src.name == "SKILL.md":
        # The name this very SKILL.md must declare: its own skill's, which for a nested skill is
        # not the copy's name. Falls back to the copy's name when the source is unknown.
        own = ctx["name_map"].get(str(src.parent), entry["dash"])
        text = rewrite_frontmatter_name(text, own)
    scratch = dict(ctx, file_rel=file_rel, dash=entry["dash"],
                   src_skill=str(src_dir), dst_skill=ctx["dst_root"], dangling=[])
    text = rewrite_relpaths(text, scratch)
    text = rewrite_colons(text, prefixes)
    ctx["dangling"].extend(scratch["dangling"])
    out.write_text(text, encoding="utf-8")
    try:
        shutil.copystat(src, out)
    except OSError:
        pass


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def build(roots, shelf=None, force=False, quiet=False) -> dict:
    """Materialize the shelf. Returns a report dict; the manifest is written LAST, so an
    interrupted build never leaves a manifest claiming copies it did not finish."""
    shelf = Path(shelf or os.environ.get(SHELF_ENV) or SHELF_DEFAULT).expanduser()
    records, plan, collisions, warnings = _scan(roots)
    # Only names that actually carry a colon define a prefix. Taking the head of EVERY name would
    # put `pdf`, `tdd`, `templates`… into the set, and a body line like `pdf: 50 MB` would then be
    # rewritten. A legal name has no namespace to prefix a reference with.
    prefixes = {r["raw"].split(":", 1)[0] for r in records if r["raw"] and ":" in r["raw"]}
    fingerprint = hashlib.sha1(json.dumps(
        [[str(r["skill_dir"]), r["raw"], r["dash"]] for r in records] +
        [str(p) for p in roots] + [MANIFEST_VERSION], sort_keys=True).encode()).hexdigest()

    manifest_path = shelf / MANIFEST_NAME
    old = _read_manifest(manifest_path)
    if not force and old and old.get("fingerprint") == fingerprint and _copies_intact(shelf, plan):
        report = {"status": "unchanged", "shelf": str(shelf),
                  "counts": _counts(plan, collisions, warnings),
                  "entries": sorted(plan), "collisions": collisions, "warnings": warnings}
        if not quiet:
            print(f"cmd-skill-bridge: shelf up to date — {len(plan)} bridged skill(s)")
        return report

    shelf.mkdir(parents=True, exist_ok=True)
    entries, entries_report, dangling = [], [], []
    bridged = [(str(p["skill_dir"]), str(shelf / d)) for d, p in sorted(plan.items())]
    all_dirs = [str(r["skill_dir"]) for r in records]
    # Every skill's final name, so a nested SKILL.md inside a copy declares its OWN name rather
    # than its parent's. A skill Command Code can already load keeps the name it has.
    name_map = {str(r["skill_dir"]): r["dash"] for r in records if is_legal(r["dash"])}
    for dash, p in sorted(plan.items()):
        dst = shelf / dash
        if dst.exists():
            shutil.rmtree(dst)                  # regenerate from scratch: the shelf is derived data
        ctx = {"bridged": bridged, "all_dirs": all_dirs, "dangling": [], "name_map": name_map}
        _copy_tree(p["skill_dir"], dst, p, prefixes, ctx)
        dangling.extend(ctx["dangling"])
        src_md = p["skill_dir"] / "SKILL.md"
        entries.append({"dash": dash, "raw": p["raw"], "reason": p["reason"],
                        "source": p["source"], "source_sha256": _sha256(src_md)})
        entries_report.append({"dash": dash, "raw": p["raw"], "reason": p["reason"],
                               "source": p["source"]})

    # Every copy is on disk now, so prove the bridge broke no reference that used to work.
    regressions = _link_regressions(shelf, plan)

    # Stale copies from a previous build (a source skill that was renamed or removed) go now.
    removed = []
    for stale in (old or {}).get("entries", []):
        d = stale.get("dash", "")
        if d in plan or not is_legal(d):
            continue
        victim = shelf / d
        if victim.is_dir() and victim.parent == shelf:
            shutil.rmtree(victim)
            removed.append(d)

    manifest = {"_note": "Generated by scripts/cmd_skill_bridge.py — do not edit. Every directory "
                         "here is a normalized copy of a skill Command Code could not load as-is; "
                         "run `cmd_skill_bridge.py build --force` to regenerate.",
                "version": MANIFEST_VERSION, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "shelf": str(shelf), "roots": [str(Path(r).expanduser()) for r in roots],
                "fingerprint": fingerprint, "prefixes": sorted(prefixes),
                "entries": entries, "collisions": collisions,
                "warnings": warnings + dangling + regressions, "removed": removed}
    _write_manifest(manifest_path, manifest)

    if not quiet:
        c = _counts(plan, collisions, manifest["warnings"])
        print(f"cmd-skill-bridge: {c['bridged']} bridged, {c['collisions']} collision(s), "
              f"{c['warnings']} warning(s), {len(removed)} stale removed -> {shelf}")
        for w in manifest["warnings"]:
            print(f"  [w] {w}")
        for c2 in collisions:
            print(f"  [!] {c2['dash']}: {c2['loser']} lost to {c2['winner']}")
    return {"status": "built", "shelf": str(shelf),
            "counts": _counts(plan, collisions, manifest["warnings"]),
            "entries": entries_report, "collisions": collisions, "removed": removed,
            "warnings": manifest["warnings"]}


def _counts(plan, collisions, warnings=None) -> dict:
    by_reason = {}
    for p in plan.values():
        by_reason[p["reason"]] = by_reason.get(p["reason"], 0) + 1
    return {"bridged": len(plan), "collisions": len(collisions),
            "warnings": len(warnings or []), "by_reason": by_reason}


def _read_manifest(path: Path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, UnicodeError, ValueError):
        return None


def _write_manifest(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _copies_intact(shelf: Path, plan) -> bool:
    for dash in plan:
        if not (shelf / dash / "SKILL.md").is_file():
            return False
    return True


# ── verify / clean ────────────────────────────────────────────────────────────

def verify(shelf=None) -> dict:
    """Prove the shelf is loadable by Command Code AND that no source file was modified.

    Each row is a Command Code rule this bridge exists to satisfy: a legal name, equal to the
    copy's own directory name, with the declared value matching what the mod registers."""
    shelf = Path(shelf or os.environ.get(SHELF_ENV) or SHELF_DEFAULT).expanduser()
    manifest = _read_manifest(shelf / MANIFEST_NAME)
    problems, checked = [], 0
    if not manifest:
        return {"ok": False, "shelf": str(shelf), "checked": 0,
                "problems": [f"no manifest at {shelf / MANIFEST_NAME} — run `build` first"]}
    for e in manifest.get("entries", []):
        dash = e.get("dash", "")
        checked += 1
        skill_md = shelf / dash / "SKILL.md"
        if not is_legal(dash):
            problems.append(f"{dash}: not a legal Command Code name")
            continue
        if not skill_md.is_file():
            problems.append(f"{dash}: {skill_md} missing")
            continue
        declared = frontmatter_name(skill_md.read_text(encoding="utf-8", errors="replace"))
        if declared != dash:
            problems.append(f"{dash}: frontmatter declares {declared!r}; Command Code requires the "
                            f"declared name to equal the skill's own directory ({skill_md.parent.name}) "
                            "or the skill is SKIPPED")
        src = Path(e.get("source", ""))
        if e.get("source_sha256"):
            if not (src / "SKILL.md").is_file():
                problems.append(f"{dash}: source {src}/SKILL.md is gone")
            elif _sha256(src / "SKILL.md") != e["source_sha256"]:
                problems.append(f"{dash}: source {src}/SKILL.md CHANGED since the build — the "
                                "bridge must never modify a source skill")
    return {"ok": not problems, "shelf": str(shelf), "checked": checked,
            "bridged": len(manifest.get("entries", [])),
            "collisions": manifest.get("collisions", []),
            "warnings": manifest.get("warnings", []), "problems": problems}


def _rel_ref(text: str) -> set:
    """Every relative reference to another skill in `text`, as written."""
    return {m.group(0) for m in _REL_RE.finditer(text)}


def _link_regressions(shelf: Path, plan) -> list:
    """References a copy can no longer resolve although its SOURCE could.

    The copy exists so a skill can load in Command Code; a reference that worked before and not
    after would be damage the bridge caused, and a bridge that breaks a skill while fixing its
    name is not a fix. A reference that was already broken in the source is NOT reported — the
    corpus has those (`../../../../docs/…` into a repo the skill only ever reached through a
    symlink), and calling them this change's fault would be false."""
    out = []
    for dash, p in sorted(plan.items()):
        for md in sorted((shelf / dash).rglob("*.md")):
            src = p["skill_dir"] / md.relative_to(shelf / dash)
            if not src.is_file():
                continue
            try:
                stext = src.read_text(encoding="utf-8", errors="replace")
                ktext = md.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            krefs = _rel_ref(ktext)
            for raw in _rel_ref(stext):
                if not os.path.exists(os.path.normpath(os.path.join(str(src.parent), raw))):
                    continue                       # already broken before the bridge
                if not any(os.path.exists(os.path.normpath(os.path.join(str(md.parent), r)))
                           for r in krefs):
                    out.append(f"{dash}/{md.relative_to(shelf / dash)}: `{raw}` resolved in the "
                               "source but not in the copy")
    return out


def clean(shelf=None, quiet=False) -> dict:
    """Remove the copies this bridge made. A directory the manifest does not name is never
    touched — the shelf can sit beside anything, and deleting a stranger's work is worse than
    leaving derived data behind."""
    shelf = Path(shelf or os.environ.get(SHELF_ENV) or SHELF_DEFAULT).expanduser()
    manifest = _read_manifest(shelf / MANIFEST_NAME) or {}
    removed = []
    for e in manifest.get("entries", []):
        dash = e.get("dash", "")
        victim = shelf / dash
        if is_legal(dash) and victim.is_dir() and victim.parent == shelf:
            shutil.rmtree(victim)
            removed.append(dash)
    try:
        (shelf / MANIFEST_NAME).unlink()
    except OSError:
        pass
    return {"removed": removed, "shelf": str(shelf)}


# ── cli ───────────────────────────────────────────────────────────────────────

DEFAULT_ROOTS = [Path.home() / ".claude" / "skills", Path.home() / ".commandcode" / "skills"]


def _roots(args) -> list:
    return [Path(r).expanduser() for r in (args.root or DEFAULT_ROOTS)]


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in argv:                       # sibling-script convention (enforcer, doctor)
        return _selftest()
    ap = argparse.ArgumentParser(description="Bridge colon-named skills into Command Code.")
    ap.add_argument("command", nargs="?", default="build",
                    choices=["build", "verify", "clean", "list", "selftest"])
    ap.add_argument("--root", action="append", help="skills root to scan (repeatable)")
    ap.add_argument("--shelf", help=f"shelf directory (default: ${SHELF_ENV} or {SHELF_DEFAULT})")
    ap.add_argument("--force", action="store_true", help="rebuild even when nothing changed")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--json", action="store_true", help="machine-readable report on stdout")
    args = ap.parse_args(argv)

    if args.command == "selftest":
        return _selftest()
    if args.command == "verify":
        rep = verify(args.shelf)
        print(json.dumps(rep, indent=1) if args.json else
              (f"cmd-skill-bridge verify: {'OK' if rep['ok'] else 'FAILED'} — "
               f"{rep['checked']} copy(ies) checked" + "".join(f"\n  [!] {p}" for p in rep["problems"])))
        return 0 if rep["ok"] else 1
    if args.command == "clean":
        rep = clean(args.shelf, args.quiet)
        print(json.dumps(rep, indent=1) if args.json else
              f"cmd-skill-bridge: removed {len(rep['removed'])} copy(ies) from {rep['shelf']}")
        return 0
    if args.command == "list":
        # Read-only by contract: `list` answers "what would be bridged" and must never write a
        # shelf, so a look at the corpus cannot change the machine.
        _records, plan, collisions, warnings = _scan(_roots(args))
        rows = [dict(dash=d, raw=p["raw"], reason=p["reason"], source=p["source"])
                for d, p in sorted(plan.items())]
        if args.json:
            print(json.dumps({"counts": _counts(plan, collisions, warnings), "entries": rows,
                              "collisions": collisions, "warnings": warnings}, indent=1))
        else:
            c = _counts(plan, collisions, warnings)
            print(f"{c['bridged']} bridgeable skill(s) ({c['collisions']} collision(s), "
                  f"{c['warnings']} warning(s)):")
            for e in rows:
                print(f"  {e['dash']:<34} <- {e['raw']:<34} ({e['reason']}) {e['source']}")
            for w in warnings:
                print(f"  [w] {w}")
        return 0

    rep = build(_roots(args), args.shelf, force=args.force, quiet=args.quiet)
    if args.json:
        print(json.dumps(rep, indent=1))
    return 0


def _selftest() -> int:
    """The name rules and the two rewrites, on fixtures, with no filesystem access."""
    import tempfile
    ok = True
    # every illegal class is named, alone, and consoles into a legal name
    for raw, reason in [("ak:fix", "colon"), ("micro:res/create", "slash"), ("ck_ci", "underscore"),
                        ("ak ci", "space"), ("ck:CI", "uppercase"), ("-ak", "leading-hyphen"),
                        ("ak-", "trailing-hyphen"), ("ak--fix", "consecutive-hyphens"),
                        ("ak.fix", "illegal-char"), ("a" * 65, "too-long")]:
        ok &= reason in illegal_reasons(raw)
        ok &= not is_legal(raw)
        out = normalize(raw)
        if not is_legal(out):
            print(f"  [!] {raw!r} -> {out!r} is still illegal")
            ok = False
    # the one input with no legal output: an absent name stays absent (and is reported, never
    # invented) — Command Code requires the field, so a copy with no name is worse than none
    ok &= normalize("") == "" and not is_legal("") and "empty" in illegal_reasons("")
    ok &= normalize("ak:ui-ux-pro-max") == "ak-ui-ux-pro-max"
    ok &= normalize("microsoft-foundry:resource/create") == "microsoft-foundry-resource-create"
    ok &= len(normalize("ak:" + "x" * 80)) <= 64 and not normalize("ak:" + "x" * 80).endswith("-")
    ok &= is_legal("ak-fix") and not is_legal("ak:fix")
    # frontmatter rewrite touches only the top-level key
    fm = "---\nname: ak:fix\ndescription: x\nmetadata:\n  name: keep\n---\n\n# body\n"
    out = rewrite_frontmatter_name(fm, "ak-fix")
    ok &= "name: ak-fix\n" in out and out.count("name: ak-fix") == 1
    ok &= "  name: keep" in out and out.endswith("# body\n")
    # colon rewrite: known prefixes only, no URL, no clock, no placeholder, no dot-swallow
    body = ("Activate `ak:scout` then /ak:cook. See https://x/ak:no and 10:30. "
            "Template: ak:<slug>. File ak:docs.md ends. Word xak:fix stays.")
    got = rewrite_colons(body, {"ak"})
    ok &= "`ak-scout`" in got and "/ak-cook." in got
    ok &= "https://x/ak:no" in got and "10:30" in got
    ok &= "ak:<slug>" in got and "ak-docs.md" in got and "xak:fix" in got
    ok &= rewrite_colons(body, set()) == body
    # an unknown prefix is never touched, and a known one is rewritten whatever its case
    ok &= "ck:CI" in rewrite_colons("x ck:CI y", {"ak"})
    ok &= rewrite_colons("ck:CI", {"ck"}) == "ck-ci"
    # relpath: identical depth keeps the reference verbatim
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        (t / "src" / "ak-docs").mkdir(parents=True)
        (t / "shelf" / "ak-docs").mkdir(parents=True)
        ctx = {"bridged": [(str(t / "src" / "ak-test"), str(t / "shelf" / "ak-test"))],
               "all_dirs": [str(t / "src" / "ak-test")], "dangling": [],
               "src_skill": str(t / "src" / "ak-docs"), "dst_skill": str(t / "shelf" / "ak-docs")}
        (t / "src" / "ak-test" / "references").mkdir(parents=True)
        (t / "shelf" / "ak-test" / "references").mkdir(parents=True)
        same = rewrite_relpaths("see ../ak-test/references/x.md here",
                               dict(ctx, file_rel="SKILL.md"))
        ok &= "../ak-test/references/x.md" in same
        # a nested source loses exactly one `../`
        (t / "src" / "grp").mkdir()
        (t / "src" / "grp" / "ak-pdf").mkdir()
        ctx2 = dict(ctx, src_skill=str(t / "src" / "grp" / "ak-pdf"),
                    dst_skill=str(t / "shelf" / "ak-pdf"))
        (t / "shelf" / "ak-pdf").mkdir()
        nested = rewrite_relpaths("see ../../ak-test/references/x.md there",
                                 dict(ctx2, file_rel="SKILL.md"))
        ok &= "../../ak-test/references/x.md" not in nested
        ok &= "/ak-test/references/x.md" in nested or "ak-test" in nested
        # a reference to a skill this bridge did not copy is reported, not silently rewritten
        shot = {"bridged": [], "all_dirs": [str(t / "src" / "ak-other")], "dangling": [],
                "src_skill": str(t / "src" / "ak-docs"), "dst_skill": str(t / "shelf" / "ak-docs"),
                "file_rel": "SKILL.md", "dash": "ak-docs"}
        (t / "src" / "ak-other").mkdir()
        ok &= rewrite_relpaths("see ../ak-other/x.md", shot) == "see ../ak-other/x.md"
        ok &= len(shot["dangling"]) == 1
    print("cmd-skill-bridge --selftest " + ("OK" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
