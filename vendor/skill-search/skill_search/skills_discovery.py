#!/usr/bin/env python3
"""
skills_discovery
----------------
Single source of truth for "what skills exist and what are they called".

Both halves of skill-search depend on this agreeing exactly:
  * server.py            indexes these skills by `name`
  * generate_overrides.py frees these same `name`s from the 1% budget

If the two walked different sets (they used to), you could index a skill you
never freed, or free one you never indexed — silent budget leaks. Keep this the
ONLY place skill discovery lives.

No third-party deps and no network — safe to import from any script.
"""

import os
import re
import glob
import logging
from pathlib import Path

log = logging.getLogger("skill_search")

# Directories Claude Code loads skills from, in precedence order
# (personal first, then project — first writer wins on name collision).
SKILL_DIRS = [
    Path.home() / ".claude" / "skills",                 # personal (all projects)
    Path.cwd()  / ".claude" / "skills",                 # project-scoped
]
# Plugin-bundled skills. Scope to the *cache* (the installed/active copies Claude
# Code actually loads), NOT ~/.claude/plugins/marketplaces/** — that holds catalog
# source checkouts including skills that aren't installed, which would pollute the
# index with un-invokable results.
PLUGIN_GLOB = str(Path.home() / ".claude" / "plugins" / "cache" / "**" / "skills" / "*" / "SKILL.md")


def _namespaced_name(path: Path, base_name: str) -> str:
    """For installed plugin skills, prefix the plugin id so the name matches how
    Claude Code references (and overrides) them, e.g. 'context-mode:ctx-purge'.

    Cache layout: .../plugins/cache/<marketplace>/<plugin>/<version>/skills/<skill>/SKILL.md
    Non-plugin skills (personal/project) are returned unchanged.
    """
    parts = path.parts
    try:
        pi = parts.index("plugins")
    except ValueError:
        return base_name
    sub = parts[pi + 1:]
    if len(sub) >= 6 and sub[0] == "cache" and "skills" in sub:
        si = sub.index("skills")
        if si >= 3:                       # cache / <marketplace> / <plugin> / .../ skills
            plugin_id = sub[si - 2]
            # Some plugins self-namespace their frontmatter `name:` already
            # (e.g. ClaudeKit ships `name: ck:plan`) — don't double-prefix to `ck:ck:plan`.
            if base_name.startswith(f"{plugin_id}:"):
                return base_name
            return f"{plugin_id}:{base_name}"
    return base_name


# Body-trigger extraction: pulls short phrases out of the body's LABELED decision
# sections ("## When to Use", "Triggers:", "Use when:", …) for server.py's
# multi-vector trigger layer (SKILL_BODY_TRIGGERS). Hand-mirrors server._LABEL_RE's
# label vocabulary — kept in sync by hand, the same way server.py already
# hand-mirrors scripts/build_triggers.py (see VENDORED.md) — plus "when to use",
# which only ever shows up here as a markdown header, never in a one-line description.
_BODY_SECTION_RE = re.compile(
    r"^[ \t]{0,3}(#{1,6})?[ \t]*\**[ \t]*"
    r"(triggers?|examples?|use when|also use|use this skill|when to use)\b",
    re.IGNORECASE | re.MULTILINE)
_BODY_HEADER_RE = re.compile(r"^[ \t]{0,3}#{1,6}\s")
_BODY_NEGATIVE_RE = re.compile(r"^[ \t]{0,3}(do\s*not|don'?t|never|avoid)\s+use\b", re.IGNORECASE)
_BODY_BULLET_RE = re.compile(r"^[ \t]*[-*•]\s+")

# Trigger-purity lint (H4, ADR-0023). A body decision-section can carry
# workflow-SUMMARY lines — process narration ("Runs the plan→cook→test pipeline"),
# numbered steps ("1. Scaffold …") — that embed near generic process-prose rather
# than user INTENT, so indexing them as trigger points buries the real skill. This
# predicate flags such phrases. Applies superpowers' SDO law (a trigger must be a
# trigger-CONDITION, never a workflow summary — writing-skills/SKILL.md:152-158).
#
#   shadow (default): log would-drops `(skill, phrase)`, keep everything -> index
#                     is BYTE-IDENTICAL to today (measurement only, drops nothing).
#   active          : drop impure phrases. Filter-logic change -> needs a FULL
#                     reindex (`--reindex --force`), not the incremental path, or
#                     unchanged skills keep their old unfiltered phrases (mixed index).
#   off             : predicate never runs -> byte-identical to today.
#
# Deliberately CONSERVATIVE (shadow-first): only unambiguous workflow-summaries are
# flagged, so genuine triggering conditions ("use when …", task+domain noun phrases,
# even "generate a report" as a use-case) stay. Precision is reviewed on the live
# corpus before anyone flips this to `active` (see ADR-0023).
SKILL_TRIGGER_PURITY = os.environ.get("SKILL_TRIGGER_PURITY", "shadow").lower()

# Impure signal 1: a numbered step lead ("1. …", "2) …", "Step 3 …").
_IMPURE_STEP_RE = re.compile(r"^\s*(?:\d+[.)]\s|step\s+\d+\b)", re.IGNORECASE)
# Impure signal 2: a process-summary — a doing-verb lead whose object is a
# pipeline/workflow/report/steps (the phrasing of a workflow narration, not a
# use-condition). Both the verb AND the summary noun must be present to flag.
_IMPURE_PROCESS_RE = re.compile(
    r"^\s*(?:runs?|generates?|produces?|creates?)\b.*\b"
    r"(?:pipeline|workflow|report|steps)\b", re.IGNORECASE)


def _is_impure_trigger(phrase: str) -> bool:
    """True when a phrase reads as a workflow-SUMMARY (process narration / numbered
    step) rather than a triggering CONDITION. Kept narrow on purpose — see the
    SKILL_TRIGGER_PURITY note above."""
    return bool(_IMPURE_STEP_RE.match(phrase) or _IMPURE_PROCESS_RE.match(phrase))


def _extract_body_triggers(body: str, skill_name: str = "") -> list[str]:
    """Short phrases from the body's labeled decision-sections only — never the
    whole body. A markdown header ("## When to Use") pulls in every line below it
    up to the next header OR a "Do NOT use when" style exclusion line, whichever
    comes first, so negative/exclusion bullets (which often name OTHER skills)
    don't leak in as if they were triggers for this one. A plain inline label line
    ("Triggers: ...", "Use when: ...") is self-contained and taken as-is."""
    lines = body.splitlines()
    phrases: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        m = _BODY_SECTION_RE.match(lines[i])
        if not m:
            i += 1
            continue
        if m.group(1):                        # markdown header -> section body follows
            j = i + 1
            while j < n and not _BODY_HEADER_RE.match(lines[j]) \
                    and not _BODY_NEGATIVE_RE.match(lines[j]):
                j += 1
            block = lines[i + 1:j]
            i = j
        else:                                  # inline label line, self-contained
            block = [lines[i]]
            i += 1
        for line in block:
            line = _BODY_BULLET_RE.sub("", line).strip()
            if not line:
                continue
            # Trigger-purity lint (H4): in `active` drop workflow-summaries; in
            # `shadow` (default) log the would-drop but keep it (byte-identical
            # index); in `off` skip the check entirely.
            if SKILL_TRIGGER_PURITY != "off" and _is_impure_trigger(line):
                if SKILL_TRIGGER_PURITY == "active":
                    continue
                log.info("trigger-purity would-drop: (%r, %r)", skill_name, line)
            phrases.append(line)
    return phrases


def parse_skill(path: Path) -> dict | None:
    """Return {name, description, body, path} or None if no valid frontmatter."""
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception:
        return None

    fm = re.search(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", raw, re.DOTALL)
    if not fm:
        return None
    frontmatter, body = fm.group(1), fm.group(2)

    # name: explicit frontmatter, else directory name (matches Claude Code rule).
    name_m = re.search(r"^name:\s*(.+)$", frontmatter, re.MULTILINE)
    name = name_m.group(1).strip() if name_m else path.parent.name
    # Plugin skills are referenced namespaced (plugin:skill) — apply that here so
    # search results, get_skill lookups, and budget overrides all use one id.
    name = _namespaced_name(path, name)

    # description + optional when_to_use (both feed the semantic index).
    desc_m = re.search(r"^description:\s*(.+?)(?=\n\w+:|\Z)", frontmatter,
                       re.MULTILINE | re.DOTALL)
    when_m = re.search(r"^when_to_use:\s*(.+?)(?=\n\w+:|\Z)", frontmatter,
                       re.MULTILINE | re.DOTALL)
    description = (desc_m.group(1).strip() if desc_m else "")
    if when_m:
        description += "  " + when_m.group(1).strip()

    stripped_body = body.strip()
    return {
        "name": name,
        "description": description,
        "body": stripped_body[:4000],   # cap body so embeddings stay cheap
        # Extracted from the FULL body (not the 4000-char-capped copy above) so a
        # decision section late in a long SKILL.md still refreshes its trigger
        # points even when the capped base text is unaffected. Feeds the
        # multi-vector trigger layer only (server.SKILL_BODY_TRIGGERS); leaves
        # `description`/`body` untouched.
        "body_triggers": _extract_body_triggers(stripped_body, name),
        "path": str(path),
    }


def discover_skill_paths() -> list[Path]:
    """Every SKILL.md path across personal dirs, project dirs, and plugins."""
    paths: list[Path] = []
    for d in SKILL_DIRS:
        if d.exists():
            paths += [Path(p) for p in glob.glob(str(d / "*" / "SKILL.md"))]
    paths += [Path(p) for p in glob.glob(PLUGIN_GLOB, recursive=True)]
    return paths


def discover_skills() -> list[dict]:
    """Parsed skill dicts (deduped by name, precedence = personal -> project)."""
    found: dict[str, dict] = {}
    for p in discover_skill_paths():
        skill = parse_skill(p)
        if skill and skill["name"]:
            found.setdefault(skill["name"], skill)   # first writer wins
    return list(found.values())
