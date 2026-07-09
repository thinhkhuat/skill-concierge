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
import json
import glob
import hashlib
import logging
from pathlib import Path

log = logging.getLogger("skill_search")

# Directories Claude Code loads skills from, in precedence order
# (personal first, then project — first writer wins on name collision).
# Exactly ONE level deep, never recursive: a `**` here would walk the entire
# project tree, sweeping up vendored/cloned repos that ship their own SKILL.md.
PERSONAL_ROOT = Path.home() / ".claude" / "skills"      # personal (all projects)
PROJECT_ROOT = Path.cwd() / ".claude" / "skills"        # project-scoped, CWD-relative
SKILL_DIRS = [PERSONAL_ROOT, PROJECT_ROOT]
# Plugin-bundled skills. Scope to the *cache* (the installed/active copies Claude
# Code actually loads), NOT ~/.claude/plugins/marketplaces/** — that holds catalog
# source checkouts including skills that aren't installed, which would pollute the
# index with un-invokable results.
PLUGIN_GLOB = str(Path.home() / ".claude" / "plugins" / "cache" / "**" / "skills" / "*" / "SKILL.md")

# The cache is append-only: it retains EVERY version ever installed, and keeps
# plugins the user has since disabled. Globbing it wholesale therefore indexed
# skills that Claude Code will not load — ancient versions (observed:
# skill-concierge:doctor resolving to 0.3.0 while 0.18.1 was installed, across 31
# cached versions) and disabled plugins (observed: superpowers:* offered while
# `enabledPlugins` had it False). Both classes are un-invokable results, the exact
# pollution PLUGIN_GLOB already avoids for marketplaces/.
#
# Claude Code's own manifests are the source of truth, so read them rather than
# guessing from version strings:
#   installed_plugins.json -> plugins[<id>@<marketplace>][].installPath
#   settings.json          -> enabledPlugins[<id>@<marketplace>] : bool
INSTALLED_PLUGINS_JSON = Path(os.environ.get(
    "SKILL_INSTALLED_PLUGINS",
    Path.home() / ".claude" / "plugins" / "installed_plugins.json"))
CLAUDE_SETTINGS_JSON = Path(os.environ.get(
    "SKILL_CLAUDE_SETTINGS",
    Path.home() / ".claude" / "settings.json"))
# Escape hatch: `=0` restores the pre-filter behaviour (index the whole cache).
SKILL_PLUGIN_FILTER = os.environ.get("SKILL_PLUGIN_FILTER", "1") != "0"


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _installed_plugin_roots() -> set[str] | None:
    """Install directories of the currently installed AND enabled plugins.

    Returns None when the manifests cannot be read, which callers treat as
    "don't filter" — an index missing every plugin skill is far worse than one
    carrying a few stale entries.
    """
    installed = _read_json(INSTALLED_PLUGINS_JSON)
    if not isinstance(installed, dict) or "plugins" not in installed:
        return None
    settings = _read_json(CLAUDE_SETTINGS_JSON) or {}
    enabled = settings.get("enabledPlugins")
    if not isinstance(enabled, dict):
        enabled = {}

    roots: set[str] = set()
    for key, entries in installed["plugins"].items():
        # A plugin absent from enabledPlugins is enabled by default.
        if not enabled.get(key, True):
            continue
        for entry in entries or []:
            p = entry.get("installPath")
            if p:
                roots.add(str(p).rstrip("/"))
    return roots or None


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


def _plugin_paths() -> list[Path]:
    """Cache SKILL.md paths, narrowed to the installed + enabled plugin versions."""
    hits = glob.glob(PLUGIN_GLOB, recursive=True)
    if not SKILL_PLUGIN_FILTER:
        return [Path(p) for p in hits]

    roots = _installed_plugin_roots()
    if roots is None:
        log.warning("plugin manifests unreadable — indexing the whole cache "
                    "(stale versions and disabled plugins included)")
        return [Path(p) for p in hits]

    kept = [p for p in hits if any(p.startswith(r + os.sep) for r in roots)]
    if not kept:
        log.warning("installed/enabled filter matched no cache skills — "
                    "falling back to the unfiltered cache")
        return [Path(p) for p in hits]
    if len(kept) < len(hits):
        log.info("plugin cache: kept %d of %d SKILL.md (installed+enabled only)",
                 len(kept), len(hits))
    return [Path(p) for p in kept]


def discover_skill_paths() -> list[Path]:
    """Every SKILL.md path across personal dirs, project dirs, and plugins."""
    paths: list[Path] = []
    for d in SKILL_DIRS:
        if d.exists():
            paths += [Path(p) for p in glob.glob(str(d / "*" / "SKILL.md"))]
    paths += _plugin_paths()
    return paths


def _scope_for(path: Path) -> str:
    """The scope that OWNS this skill: 'personal' | 'plugin' | 'project:<root>'.

    Claude Code runs one MCP server per session, each with its own CWD, and they
    all share one Qdrant collection. Points must record who owns them so a
    reindex in session A cannot prune session B's project skills (they simply
    look "deleted from disk" from A's vantage point).
    """
    p = str(path)
    if p.startswith(str(PERSONAL_ROOT) + os.sep):
        return "personal"
    if f"{os.sep}plugins{os.sep}cache{os.sep}" in p:
        return "plugin"
    return f"project:{PROJECT_ROOT}"


def visible_scopes() -> set[str]:
    """Scopes THIS process is authoritative for — may prune and may search."""
    return {"personal", "plugin", f"project:{PROJECT_ROOT}"}


def manifest_key() -> str:
    """Short, stable id for this session's project root.

    The index manifest stores a disk signature computed from THIS session's view
    (personal + plugin + this project). A single shared manifest file therefore
    ping-pongs between sessions with different project roots, and every one of
    them reports a false 'disk changed since last index'. Keying the manifest per
    project root gives each session a signature it can actually match.
    """
    return hashlib.md5(str(PROJECT_ROOT).encode()).hexdigest()[:8]


def discover_skills() -> list[dict]:
    """Parsed skill dicts (deduped by name, precedence = personal -> project)."""
    found: dict[str, dict] = {}
    for p in discover_skill_paths():
        skill = parse_skill(p)
        if skill and skill["name"]:
            skill["scope"] = _scope_for(p)
            found.setdefault(skill["name"], skill)   # first writer wins
    return list(found.values())
