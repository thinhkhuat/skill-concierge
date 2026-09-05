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
import fnmatch
import hashlib
import logging
import textwrap
from pathlib import Path

log = logging.getLogger("skill_search")

# Directories Claude Code loads skills from, in precedence order
# (personal first, then project — first writer wins on name collision).
# Exactly ONE level deep, never recursive: a `**` here would walk the entire
# project tree, sweeping up vendored/cloned repos that ship their own SKILL.md.
PERSONAL_ROOT = Path.home() / ".claude" / "skills"      # personal (all projects)
PROJECT_ROOT = Path.cwd() / ".claude" / "skills"        # project-scoped, CWD-relative
# Codex skill roots (dual-harness parity, ADR-0033): Codex stores personal skills
# at ~/.codex/skills/ and plugin-bundled skills at ~/.codex/plugins/cache/**.
# ADDITIVE — both harnesses' skills index into the SAME Qdrant collection under
# DISTINCT scopes, so a reindex in one harness cannot prune the other's points.
# Paths that don't exist are silently skipped by discover_skill_paths()'s
# d.exists() check, so a Codex-less machine is unaffected. One-var revert:
# SKILL_CODEX_ROOTS=0 drops every Codex path + scope (byte-identical to the
# pre-dual-harness engine; a reindex prunes the codex-* points).
CODEX_ROOTS = os.environ.get("SKILL_CODEX_ROOTS", "1") != "0"
CODEX_PERSONAL_ROOT = Path.home() / ".codex" / "skills"      # Codex personal (all projects)
CODEX_PROJECT_ROOT = Path.cwd() / ".codex" / "skills"        # Codex project-scoped, CWD-relative
CODEX_PLUGIN_GLOB = str(Path.home() / ".codex" / "plugins" / "cache" / "**" / "skills" / "*" / "SKILL.md")

# Command Code skill roots (triple-harness parity, ADR-0038): Command Code stores
# personal skills at ~/.commandcode/skills/ and project skills at .commandcode/skills/.
COMMANDCODE_ROOTS = os.environ.get("SKILL_COMMANDCODE_ROOTS", "1") != "0"
COMMANDCODE_PERSONAL_ROOT = Path.home() / ".commandcode" / "skills"
COMMANDCODE_PROJECT_ROOT = Path.cwd() / ".commandcode" / "skills"
# OMP (Oh My Pi) skill roots (quad-harness parity, ADR-0038): OMP sets BOTH OMPCODE
# and CLAUDECODE in its environment, so CLAUDECODE alone is NOT proof the process is
# Claude Code — OMP's identity marker is OMPCODE=1 and a ".omp/" install path. OMP
# stores four skill roots, all distinct so a reindex in one harness prunes nothing
# of another's:
#   omp-personal : ~/.omp/agent/skills           (user native, all projects)
#   omp-project  : <cwd>/.omp/skills             (project native, CWD-relative)
#   omp-managed  : ~/.omp/agent/managed-skills   (auto-learned)
#   omp-plugin   : ~/.omp/plugins/cache/plugins/**/skills/**  (installed plugins)
# Same one-var revert as Codex/Command Code: SKILL_OMP_ROOTS=0 drops every OMP path
# + scope (byte-identical to the pre-OMP engine; a reindex prunes the omp-* points).
OMP_ROOTS = os.environ.get("SKILL_OMP_ROOTS", "1") != "0"
OMP_PERSONAL_ROOT = Path.home() / ".omp" / "agent" / "skills"        # OMP personal (all projects)
OMP_PROJECT_ROOT = Path.cwd() / ".omp" / "skills"                    # OMP project-scoped, CWD-relative
OMP_MANAGED_ROOT = Path.home() / ".omp" / "agent" / "managed-skills" # OMP auto-learned
# Installed marketplace plugins live under ~/.omp/plugins/cache/plugins/**
# (<marketplace>___<plugin>___<version>/skills/...). Glob the CACHE, never
# ~/.omp/plugins/node_modules — every entry there is a SYMLINK back into this same
# cache (effort-gate -> cache/plugins/effort-gate___effort-gate___0.1.1), so
# scanning node_modules would hand every skill back to us through a second path
# and mint it twice. The realpath dedup in discover_skills() already collapses
# the symlink twin, but skipping node_modules structurally keeps the glob honest
# and avoids glob() traversing those links at all.
OMP_PLUGIN_GLOB = str(Path.home() / ".omp" / "plugins" / "cache" / "plugins"
                      / "**" / "skills" / "*" / "SKILL.md")

# ZCode skill roots (quintuple-harness parity, ADR-0042): ZCode stores personal skills
# at ~/.zcode/skills/, project skills at .zcode/skills/ AND .agents/skills/, and plugin
# skills under ~/.zcode/cli/plugins/cache/<marketplace>/<plugin>/<version>/skills/ — the
# same cache layout as Claude's, so _namespaced_name needs no zcode branch.
# ~/.agents/skills is deliberately NOT a discovery root: on the reference machine it is
# a symlink to ~/.claude/skills (the shared shelf), so it would dedup into `personal`
# anyway, and baking a per-machine symlink into the machine-global index is the
# ADR-0028 hazard — per-session invocability of `personal` rows under ZCode is settled
# by the enforcer's twin check (ADR-0042), never by the index.
# Same one-var revert as the other harnesses: SKILL_ZCODE_ROOTS=0 drops every ZCode path
# + scope (byte-identical to the pre-ZCode engine; a reindex prunes the zcode-* points).
ZCODE_ROOTS = os.environ.get("SKILL_ZCODE_ROOTS", "1") != "0"
ZCODE_PERSONAL_ROOT = Path.home() / ".zcode" / "skills"           # ZCode personal (all projects)
ZCODE_PROJECT_ROOT = Path.cwd() / ".zcode" / "skills"             # ZCode project-scoped, CWD-relative
ZCODE_AGENTS_PROJECT_ROOT = Path.cwd() / ".agents" / "skills"     # agents-convention project dir ZCode also reads
ZCODE_PLUGIN_CACHE = Path.home() / ".zcode" / "cli" / "plugins" / "cache"
ZCODE_INSTALLED_PLUGINS_JSON = Path(os.environ.get(
    "SKILL_ZCODE_INSTALLED_PLUGINS", Path.home() / ".zcode" / "cli" / "plugins" / "installed_plugins.json"))
ZCODE_CONFIG_JSON = Path(os.environ.get(
    "SKILL_ZCODE_CONFIG", Path.home() / ".zcode" / "cli" / "config.json"))

# DeepSeek Harness (DSH) skill roots (hexa-harness parity, ADR-0050): DSH — including
# Oh-DSH Desktop, the Electron distribution — stores skills in DSH_HOME/skills
# (personal; DSH_HOME resolves to ~/.ohdsh under Oh-DSH Desktop or ~/.dsh under the
# legacy dsh CLI) and <cwd>/.dsh/skills (project-scoped, CWD-relative). Home
# resolution matches dsh-skill-filesystem: explicit SKILL_DSH_HOME override, else
# the live DSH_HOME env, else Oh-DSH Desktop's ~/.ohdsh (the reference-machine
# shape), else the legacy ~/.dsh default.
# The `.agents/skills` convention dir is deliberately NOT a discovery root (the hard-won
# ADR-0042 rule: it realpath-dedups into `personal` on the shared-shelf machine and
# baking a per-machine symlink into the machine-global index is the ADR-0028 hazard —
# invocability stays the session-side twin check's job, never the index's).
# Same one-var revert as every other harness: SKILL_DSH_ROOTS=0 drops both paths +
# scope (byte-identical to the pre-DSH engine; a reindex prunes the dsh-* points).
DSH_ROOTS = os.environ.get("SKILL_DSH_ROOTS", "1") != "0"
_DSH_HOME_EXPLICIT = os.environ.get("SKILL_DSH_HOME") or os.environ.get("DSH_HOME")
_OHDSH_HOME = Path.home() / ".ohdsh"
DSH_HOME = Path(_DSH_HOME_EXPLICIT) if _DSH_HOME_EXPLICIT else (
    _OHDSH_HOME if _OHDSH_HOME.is_dir() else Path.home() / ".dsh")
DSH_PERSONAL_ROOT = DSH_HOME / "skills"                          # DSH personal (all projects)
DSH_PROJECT_ROOT = Path.cwd() / ".dsh" / "skills"                # DSH project-scoped, CWD-relative

# Cline skill roots (hepta-harness parity, ADR-0051): the Cline CLI/SDK agent runtime
# stores personal skills at ~/.cline/data/settings/skills/ and project skills at
# <cwd>/.cline/skills/ — plain SKILL.md directories invoked by the model via a
# `use_skill` tool (docs.cline.bot/features/skills; verified against Cline 3.0.60).
# Same one-var revert as every other harness: SKILL_CLINE_ROOTS=0 drops both paths +
# scope (byte-identical to the pre-Cline engine; a reindex prunes the cline-* points).
CLINE_ROOTS = os.environ.get("SKILL_CLINE_ROOTS", "1") != "0"
CLINE_PERSONAL_ROOT = Path.home() / ".cline" / "data" / "settings" / "skills"  # Cline personal
CLINE_PROJECT_ROOT = Path.cwd() / ".cline" / "skills"            # Cline project-scoped, CWD-relative

SKILL_DIRS = [PERSONAL_ROOT, PROJECT_ROOT] + (
    [CODEX_PERSONAL_ROOT, CODEX_PROJECT_ROOT] if CODEX_ROOTS else []
) + (
    [COMMANDCODE_PERSONAL_ROOT, COMMANDCODE_PROJECT_ROOT] if COMMANDCODE_ROOTS else []
) + (
    [OMP_PERSONAL_ROOT, OMP_PROJECT_ROOT, OMP_MANAGED_ROOT] if OMP_ROOTS else []
) + (
    [ZCODE_PERSONAL_ROOT, ZCODE_PROJECT_ROOT, ZCODE_AGENTS_PROJECT_ROOT] if ZCODE_ROOTS else []
) + (
    [DSH_PERSONAL_ROOT, DSH_PROJECT_ROOT] if DSH_ROOTS else []
) + (
    [CLINE_PERSONAL_ROOT, CLINE_PROJECT_ROOT] if CLINE_ROOTS else []
)
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

# Layered enablement (ADR-0052): Claude Code layers `enabledPlugins` across the USER
# settings file AND every project's .claude/settings.json / settings.local.json
# (last writer wins PER SESSION). The Qdrant index is machine-global (ADR-0028: no
# cwd-scoped view may be baked into it), so discovery indexes the UNION of all
# readable layers — a plugin is excluded only when the USER file says false AND no
# layer anywhere re-enables it — and per-session precision is the enforcer's gate
# (ENFORCER_PLUGIN_GATE, hooks/scripts/enforcer.py). Live bug this closes: a plugin
# disabled at user scope but re-enabled by one project (agent-skills) was indexed
# NOWHERE, leaving 25 invocable skills unretrievable in that project.
# The union's project enumeration reads Claude Code's own project registry
# (~/.claude.json "projects" keys; env-overridable so tests stay hermetic). `=0`
# restores user-file-only enablement (byte-identical exclusions).
SKILL_PLUGIN_LAYERED_ENABLEMENT = os.environ.get("SKILL_PLUGIN_LAYERED_ENABLEMENT", "1") != "0"
CLAUDE_PROJECTS_FILE = Path(os.environ.get(
    "SKILL_CLAUDE_PROJECTS_FILE", Path.home() / ".claude.json"))

# ── external catalog roots (ADR-0031) ────────────────────────────────────────
# Operator-owned config of EXTRA skill collections indexed for retrieval WITHOUT
# being installed into any Claude Code root — search-only citizens, consumed by
# reading their SKILL.md (get_skill), never by the Skill tool. Shape:
#   {"<alias>": {"path": "/abs/dir", "include": ["glob"...], "exclude": ["glob"...]}}
# (a bare string value is shorthand for {"path": ...}; keys starting with "_" are
# comments). Every catalog skill indexes as `<alias>:<dirname>` under scope
# `catalog:<alias>` and its points carry `tier: "external"` so the per-turn
# enforcer can exclude them (search-only tier). Absent/malformed file -> {} ->
# byte-identical behavior: absence IS the off-switch (ADR-0030 idiom).
CATALOG_ROOTS_PATH = Path(os.environ.get(
    "SKILL_CONCIERGE_CATALOG_ROOTS",
    Path.home() / ".claude" / "skill-concierge" / "catalog-roots.json"))
_ALIAS_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def catalog_roots() -> dict:
    """{alias: {"path": Path, "include": [...], "exclude": [...]}} — validated,
    fail-open to {}. A malformed entry is skipped with a warning, never fatal:
    catalog config must not dark the installed catalogue."""
    cfg = _read_json(CATALOG_ROOTS_PATH)
    if not isinstance(cfg, dict):
        return {}
    out: dict = {}
    for alias, spec in cfg.items():
        if not isinstance(alias, str) or alias.startswith("_"):
            continue
        if not _ALIAS_RE.match(alias):
            log.warning("catalog-roots: alias %r invalid (want [a-z0-9][a-z0-9_-]*) — skipped", alias)
            continue
        if isinstance(spec, str):
            spec = {"path": spec}
        if not isinstance(spec, dict) or not spec.get("path"):
            log.warning("catalog-roots: entry %r has no path — skipped", alias)
            continue
        p = Path(os.path.expanduser(str(spec["path"])))
        if not p.is_dir():
            log.warning("catalog-roots: %r path %s is not a directory — skipped", alias, p)
            continue
        out[alias] = {
            "path": p,
            "include": [g for g in (spec.get("include") or []) if isinstance(g, str)],
            "exclude": [g for g in (spec.get("exclude") or []) if isinstance(g, str)],
        }
    return out


def _catalog_dir_admitted(dirname: str, spec: dict) -> bool:
    """Per-root include/exclude glob gate on the skill's directory name.
    include empty = admit all; exclude always wins."""
    if spec["include"] and not any(fnmatch.fnmatch(dirname, g) for g in spec["include"]):
        return False
    return not any(fnmatch.fnmatch(dirname, g) for g in spec["exclude"])


def _catalog_skills() -> list[dict]:
    """Parsed skills from every configured catalog root: name `<alias>:<dirname>`,
    scope `catalog:<alias>`. One level deep like every other root (the `*` glob),
    never recursive."""
    out: list[dict] = []
    for alias, spec in sorted(catalog_roots().items()):
        for raw in sorted(glob.glob(str(spec["path"] / "*" / "SKILL.md"))):
            p = Path(raw)
            if not _catalog_dir_admitted(p.parent.name, spec):
                continue
            skill = parse_skill(p)
            if not skill or not skill["name"]:
                continue
            skill["name"] = f"{alias}:{skill['name']}"
            skill["scope"] = f"catalog:{alias}"
            out.append(skill)
    return out


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _layered_plugin_exclusions() -> set[str]:
    """Registry keys EXCLUDED under the machine-wide union rule (ADR-0052): the USER
    file says false AND no readable layer anywhere says true. A project-layer
    `false` alone never excludes — the index is machine-global, and the session's
    enforcer gate (ENFORCER_PLUGIN_GATE) subtracts per cwd. Every read fails open:
    an unreadable file contributes no signal, and no signal can never exclude.
    `SKILL_PLUGIN_LAYERED_ENABLEMENT=0` degrades to user-file-only exclusions
    (byte-identical to the pre-layering behavior)."""
    settings = _read_json(CLAUDE_SETTINGS_JSON) or {}
    user_enabled = settings.get("enabledPlugins")
    user_enabled = user_enabled if isinstance(user_enabled, dict) else {}
    user_false = {str(k) for k, v in user_enabled.items() if v is False}
    if not SKILL_PLUGIN_LAYERED_ENABLEMENT:
        return user_false
    any_true = {str(k) for k, v in user_enabled.items() if v is True}
    projects = _read_json(CLAUDE_PROJECTS_FILE)
    if isinstance(projects, dict) and isinstance(projects.get("projects"), dict):
        for proj in projects["projects"]:
            for layer in (Path(proj) / ".claude" / "settings.json",
                          Path(proj) / ".claude" / "settings.local.json"):
                data = _read_json(layer)
                if not isinstance(data, dict):
                    continue
                ep = data.get("enabledPlugins")
                if not isinstance(ep, dict):
                    continue
                any_true.update(str(k) for k, v in ep.items() if v is True)
    return user_false - any_true


def _installed_plugin_entries() -> dict[str, str] | None:
    """Registry key -> installPath for installed plugins surviving the union rule.

    Replaces the old roots view so the scan can be ROOT-RELATIVE and the plugin id
    can come from the REGISTRY KEY (both ADR-0052). None ONLY when the registry
    cannot be read — callers fall back to the whole cache (blind-spot-beats-stale).
    A readable registry that yields zero kept plugins returns {} — a POSITIVE
    empty: the layers just said every plugin is off, and resurrecting them through
    the fallback would undo the exclusion (the enforcer applies the identical
    principle to INVOCABLE_PLUGIN_IDS).

    Per key only the FIRST registry entry's installPath is scanned: Claude Code's
    registry lists the ACTIVE version dir first (validated live 2026-09-05 —
    agent-skills carries a user 0.6.9 entry followed by a project-local 0.6.8, and
    only 0.6.9 is walked; both ship identical skill sets, so the assumption is
    load-bearing but unexercised). If a future Claude Code ever demotes the active
    entry, the symptom is a missing-version skill set, not a wrong name."""
    installed = _read_json(INSTALLED_PLUGINS_JSON)
    if not isinstance(installed, dict) or "plugins" not in installed:
        return None
    excluded = _layered_plugin_exclusions()
    entries: dict[str, str] = {}
    for key, per_entries in installed["plugins"].items():
        key = str(key)
        if key in excluded:
            continue
        for entry in per_entries or []:
            p = entry.get("installPath")
            if p:
                entries[key] = str(p).rstrip("/")
                break
    return entries


def _namespaced_name(path: Path, base_name: str) -> str:
    """For installed plugin skills, prefix the plugin id so the name matches how
    Claude Code references (and overrides) them, e.g. 'context-mode:ctx-purge'.

    Cache layout: .../plugins/cache/<marketplace>/<plugin>/<version>/skills/<skill>/SKILL.md
    Non-plugin skills (personal/project) are returned unchanged.

    OMP (ADR-0038) adds one extra directory level: .../plugins/cache/plugins/
    <marketplace>___<plugin>___<version>/skills/<skill>/SKILL.md, where the plugin
    directory is the marketplace/plugin/version fused into ONE dirname. The plugin
    id OMP itself uses is the `___`-middle component — it matches the node_modules/
    symlink alias (verified: node_modules/memsearch -> memsearch-plugins___memsearch
    ___0.4.18), and it is what the agent looks skills up as. Without this branch the
    generic sub[si-2] heuristic reads the literal "plugins" segment and mines every
    OMP skill as `plugins:<skill>` — a cross-plugin collision that would silently
    drop all but the first plugin's same-named skills.
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
            # OMP cache: the extra "plugins" level sits between "cache" and the fused
            # <mkt>___<plugin>___<ver> dirname, shifting every index down one — so
            # sub[1] == "plugins" and the real id is the middle `___` component of
            # sub[2]. Detected by the OMP cache marker in the path, not by index
            # arithmetic (si is 3 for OMP, 4 for claude/codex).
            if plugin_id == "plugins" and \
                    f"{os.sep}.omp{os.sep}plugins{os.sep}cache{os.sep}plugins{os.sep}" in str(path):
                fused = sub[2]
                # <mkt>___<plugin>___<version> -> plugin; missing separators leave
                # the whole dirname as the id rather than inventing a sub-component.
                mid = (fused + "___").split("___")[1] if "___" in fused else fused
                plugin_id = mid
            # Defensive: never double-prefix a name that already carries the plugin id.
            # base_name is now the skill's directory name, which in practice never
            # contains a colon — this only fires on an oddly-named directory.
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


# Lookahead ending a frontmatter value: the next `key:` line, or end of frontmatter.
# `[\w-]` not `\w` — hyphenated keys are common in SKILL.md frontmatter.
_FM_NEXT_KEY = r"(?=\n[\w-]+:|\Z)"

# A block-scalar header: `|`, `>`, plus optional chomping (`+`/`-`) and indent digits.
_BLOCK_SCALAR = re.compile(r"^([|>])[0-9+\-]*$")


def _unwrap_scalar(raw: str) -> str:
    """Reduce a raw frontmatter value to the plain text YAML would have yielded.

    The value arrives exactly as authored, scalar syntax and all. Untouched,
    `description: >-` keeps the literal ">-" plus every continuation line's newline
    and indent, and `description: "…"` keeps its surrounding quotes. That text is
    what gets embedded, so the retriever ends up scoring skills partly on punctuation
    noise. Measured on 210 of 416 skills on the maintainer's machine.

    Deliberately NOT a YAML parser — this module is dependency-free by contract (see
    the header) and frontmatter values only ever take three shapes: a block scalar,
    a quoted flow scalar, or a plain (possibly line-wrapped) scalar.
    """
    if not raw:
        return ""
    lines = raw.split("\n")
    m = _BLOCK_SCALAR.match(lines[0].strip())
    if m:
        body = "\n".join(lines[1:])
        # Common leading indent is YAML block structure, not content.
        body = textwrap.dedent(body).strip()
        if m.group(1) == "|":            # literal: line breaks are content
            return body
        # folded: a blank line is a paragraph break, every other newline folds to a space
        paras = [" ".join(p.split()) for p in re.split(r"\n\s*\n", body)]
        return "\n".join(p for p in paras if p).strip()

    # Flow scalar. A wrapped plain/quoted value folds its newlines to spaces first,
    # so the quote test below sees the true first and last characters.
    text = " ".join(ln.strip() for ln in lines).strip()
    for quote in ('"', "'"):
        if len(text) >= 2 and text[0] == quote and text[-1] == quote:
            text = text[1:-1]
            text = text.replace('\\"', '"') if quote == '"' else text.replace("''", "'")
            break
    return text.strip()


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

    # name: the DIRECTORY name, always — that is how Claude Code identifies a skill.
    # Frontmatter `name:` is NOT the identity and must not be read here. Verified
    # against a live catalogue: ~/.claude/skills/zread-cli ships `name: zread` — a
    # perfectly valid slug, so this is not merely a fallback for unparseable names —
    # and Claude Code still lists and overrides it as `zread-cli`.
    # Preferring frontmatter silently mismatched every skill whose two names differ:
    # the override key was written under a name Claude Code never looks up, so the
    # skill's budget override never applied and its full description stayed resident
    # in every turn, while apply-overrides still reported "in sync, no drift".
    name = path.parent.name
    # Plugin skills are referenced namespaced (plugin:skill) — apply that here so
    # search results, get_skill lookups, and budget overrides all use one id.
    name = _namespaced_name(path, name)
    # ADR-0052: under the root-relative scan the id is the REGISTRY key's, not path
    # arithmetic. _FORCED_PLUGIN_NAMES is populated by _plugin_paths before any
    # parse in a discovery pass (see the global's contract note).
    if _FORCED_PLUGIN_NAMES:
        name = _FORCED_PLUGIN_NAMES.get(str(path), name)

    # description + optional when_to_use (both feed the semantic index).
    # The value runs until the NEXT frontmatter key. That terminator must admit
    # hyphens: `\w` is [A-Za-z0-9_] and excludes `-`, so keys like `user-invocable:`,
    # `argument-hint:` and `allowed-tools:` did not stop the capture and were swallowed
    # into the description — polluting the skill listing and, worse, the embedded text
    # (a vector carrying the literal "user-invocable: true" is noise that degrades
    # retrieval). Observed on 168 of 356 personal skills.
    desc_m = re.search(r"^description:\s*(.+?)" + _FM_NEXT_KEY, frontmatter,
                       re.MULTILINE | re.DOTALL)
    when_m = re.search(r"^when_to_use:\s*(.+?)" + _FM_NEXT_KEY, frontmatter,
                       re.MULTILINE | re.DOTALL)
    # next-skills (ADR-0029 chain hints): optional comma/space-separated successor
    # names, e.g. `next-skills: plan, cook, test`. NOT embedded and NOT a payload
    # field — it feeds the sidecar map written at index time (server.build_index).
    # Successors must match catalogue ids exactly (namespaced for plugin skills).
    next_m = re.search(r"^next-skills:\s*(.+?)" + _FM_NEXT_KEY, frontmatter,
                       re.MULTILINE | re.DOTALL)
    description = _unwrap_scalar(desc_m.group(1)) if desc_m else ""
    when_to_use = _unwrap_scalar(when_m.group(1)) if when_m else ""
    if when_to_use:
        description += "  " + when_to_use

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
        # ADR-0029: [] when unauthored. Every skill carries the key so the sidecar
        # doubles as a catalogue-membership view for the enforcer's hint filter.
        "next_skills": [t for t in re.split(r"[,\s]+", _unwrap_scalar(next_m.group(1))
                                            if next_m else "") if t],
        "path": str(path),
    }


def _nested_glob(g: str) -> str:
    """The same plugin glob with ONE extra directory level under `skills/`.

    Some plugins group their skills into categories — `skills/<category>/<skill>/
    SKILL.md` (observed: `mattpocock-skills` 1.2.3, 35 skills under
    `skills/engineering/`). The single-star glob missed every one of them, so they
    were installed and Skill-tool-invocable yet permanently unretrievable.

    Bounded to exactly one extra level on purpose: an unbounded `**` would mint a
    phantom skill out of any SKILL.md buried anywhere under a real skill's own
    directory. (One extra level is still exposed to `skills/<skill>/references/
    SKILL.md`, which _glob_both_depths filters structurally — see there.)

    DERIVED at call time from the base glob rather than defined as a second module
    constant, so the test conftest's single monkeypatch of PLUGIN_GLOB /
    CODEX_PLUGIN_GLOB keeps discovery hermetic. A second constant would be a second
    thing to pin, and an unpinned one leaks the real machine's cache into the
    fixtures — the exact ADR-0033 hermeticity trap.
    """
    tail = f"{os.sep}skills{os.sep}*{os.sep}SKILL.md"
    return g[: -len(tail)] + f"{os.sep}skills{os.sep}*{os.sep}*{os.sep}SKILL.md" \
        if g.endswith(tail) else g


def _glob_both_depths(g: str) -> list[str]:
    """Plugin-cache hits at `skills/<skill>/` AND `skills/<category>/<skill>/`.

    When the glob has no `skills/*/SKILL.md` tail to rewrite (test fixtures pin
    shapes like `<tmp>/none/**/SKILL.md`), _nested_glob returns it unchanged — glob
    ONCE in that case, or every hit would be listed twice.

    The two patterns are ALMOST disjoint by depth, not entirely: a path ending
    `skills/skills/<x>/SKILL.md` satisfies both, since the leading `**` can absorb one
    `skills` component. Nothing on a real cache looks like that, but "almost disjoint"
    is not an invariant — so the result is order-preservingly de-duplicated rather than
    argued to be unique.

    PHANTOM GUARD, structural rather than a denylist of directory names: a nested hit
    is dropped when its grandparent already matched the FLAT glob. A directory holding
    its own SKILL.md is a skill, so anything below it (`references/`, `assets/`, an
    example skill shipped as documentation) is that skill's payload, not a sibling
    skill. A genuine category directory has no SKILL.md of its own and survives.
    """
    hits = glob.glob(g, recursive=True)
    nested_pat = _nested_glob(g)
    if nested_pat == g:
        return hits
    skill_dirs = {os.path.dirname(h) for h in hits}
    seen = set(hits)
    out = list(hits)
    for n in glob.glob(nested_pat, recursive=True):
        if n in seen or os.path.dirname(os.path.dirname(n)) in skill_dirs:
            continue
        seen.add(n)
        out.append(n)
    return out


def _ver_key(s: str) -> tuple:
    """Version-dir sort key ("0.33.10" > "0.33.9"). Non-numeric components fold to 0."""
    return tuple(int(x) if x.isdigit() else 0 for x in s.split("."))


def _zcode_plugin_roots() -> set[str] | None:
    """Install directories of ZCode's installed+enabled plugins (ADR-0042).

    ZCode's registry (installed_plugins.json) is a LIST of
    {id: "<name>@<marketplace>", installPath: <version dir>} — unlike Claude's
    name-keyed dict — and its BUILTIN plugins (the official marketplaces' plugins)
    are enabled-but-absent from the registry, so they are enumerated from the cache
    tree itself, newest version dir only. Enablement lives in
    ~/.zcode/cli/config.json plugins.enabledPlugins (absent key = enabled, mirroring
    the Claude rule); suppressedBuiltins is the builtin opt-out.

    Returns None when nothing is positively known (no cache tree / nothing readable)
    — the caller then falls back to the whole cache, the same blind-spot-beats-stale
    trade _installed_plugin_entries makes for Claude.
    """
    if not ZCODE_PLUGIN_CACHE.is_dir():
        return None
    config = _read_json(ZCODE_CONFIG_JSON) or {}
    plugins_cfg = config.get("plugins") if isinstance(config.get("plugins"), dict) else {}
    enabled_map = (plugins_cfg.get("enabledPlugins")
                   if isinstance(plugins_cfg.get("enabledPlugins"), dict) else {})
    suppressed = {str(s) for s in (plugins_cfg.get("suppressedBuiltins") or []) if s}

    roots: set[str] = set()
    registry_ids: set[str] = set()
    installed = _read_json(ZCODE_INSTALLED_PLUGINS_JSON)
    if isinstance(installed, dict) and isinstance(installed.get("plugins"), list):
        for entry in installed["plugins"]:
            if not isinstance(entry, dict):
                continue
            pid = str(entry.get("id") or "")
            if not pid:
                continue
            registry_ids.add(pid)
            if enabled_map.get(pid, True) is False:
                continue  # explicitly switched off in enabledPlugins
            p = entry.get("installPath")
            if p:
                roots.add(str(p).rstrip("/"))
    # Builtins: cache plugin dirs with no registry entry — newest version dir wins.
    # The ZCode cache is append-only exactly like Claude's; indexing every retained
    # version would be the ADR-0028 stale-copy pollution class.
    try:
        market_dirs = sorted(ZCODE_PLUGIN_CACHE.iterdir())
    except OSError:
        market_dirs = []
    for mkt in market_dirs:
        try:
            plugin_dirs = sorted(mkt.iterdir())
        except OSError:
            continue
        for plug in plugin_dirs:
            pid = f"{plug.name}@{mkt.name}"
            if pid in registry_ids:
                continue  # the registry's installPath is authoritative for this one
            if pid in suppressed or enabled_map.get(pid, True) is False:
                continue
            try:
                versions = [v for v in plug.iterdir() if v.is_dir()]
            except OSError:
                continue
            if versions:
                roots.add(str(max(versions, key=lambda v: _ver_key(v.name))).rstrip("/"))
    return roots or None


def _zcode_plugin_paths() -> list[Path]:
    """SKILL.md paths under ZCode's plugin cache roots (ADR-0042), both depths.

    Registry-enumerated rather than a wholesale cache glob. Unreadable-everything
    degrades to the whole-cache glob with a warning — a few stale entries beat a
    blind spot over an entire harness's plugin universe (the _installed_plugin_entries
    trade). Returns [] when SKILL_ZCODE_ROOTS=0 or no cache exists."""
    if not ZCODE_ROOTS or not ZCODE_PLUGIN_CACHE.is_dir():
        return []
    roots = _zcode_plugin_roots()
    if roots is None:
        log.warning("ZCode plugin registries unreadable — indexing the whole ZCode cache")
        hits: list[str] = []
        for pat in (str(ZCODE_PLUGIN_CACHE / "**" / "skills" / "*" / "SKILL.md"),
                    str(ZCODE_PLUGIN_CACHE / "**" / "skills" / "*" / "*" / "SKILL.md")):
            hits += glob.glob(pat, recursive=True)
        return [Path(p) for p in dict.fromkeys(hits)]
    out: list[str] = []
    for r in sorted(roots):
        for pat in (str(Path(r) / "skills" / "*" / "SKILL.md"),
                    str(Path(r) / "skills" / "*" / "*" / "SKILL.md")):
            out += glob.glob(pat)
    return [Path(p) for p in dict.fromkeys(out)]


# {SKILL.md path: "plugin:skill"} for registry-rooted Claude plugin skills, set by
# _claude_plugin_skill_paths() on every discovery pass. parse_skill reads it AFTER
# _plugin_paths has run — the population-precedes-parse ordering holds in every
# discovery pass. A parse outside a discovery pass (server-side incremental
# re-embed of one changed file) sees the previous pass's map: for exact cache
# layouts the heuristic fallback names identically, and interposed-dir layouts are
# payload trees that root-relative enumeration excludes anyway.
_FORCED_PLUGIN_NAMES: dict[str, str] = {}


def _claude_plugin_skill_paths(entries: dict[str, str]) -> list[Path]:
    """SKILL.md paths under each install root, both depths, registry-named (ADR-0052).

    Root-relative enumeration makes whole pollution classes structurally
    unreachable: retained old versions (only installPath is walked), the plugin's
    own payload trees (examples/, docs/ — anything outside <root>/skills/; the live
    phantom was `examples:workflow` minted by the sub[si-2] heuristic), and
    marketplace temp_git_* clones (no installPath). Nested category hits keep the
    whole-cache phantom guard: a directory that IS a skill (flat hit) owns
    everything below it."""
    global _FORCED_PLUGIN_NAMES
    out: list[Path] = []
    forced: dict[str, str] = {}
    for key in sorted(entries):
        root = Path(entries[key])
        pid = key.split("@", 1)[0]
        flat = glob.glob(str(root / "skills" / "*" / "SKILL.md"))
        skill_dirs = {os.path.dirname(f) for f in flat}
        hits = list(flat)
        for n in glob.glob(str(root / "skills" / "*" / "*" / "SKILL.md")):
            if os.path.dirname(os.path.dirname(n)) in skill_dirs:
                continue          # phantom guard: payload inside a real skill dir
            hits.append(n)
        for h in hits:
            forced[h] = f"{pid}:{Path(h).parent.name}"
            out.append(Path(h))
    _FORCED_PLUGIN_NAMES = forced
    return out


def _plugin_paths() -> list[Path]:
    """Cache SKILL.md paths from the harness plugin caches (ADR-0033/0038/0042/0052).

    Claude hits are enumerated ROOT-RELATIVELY from installed_plugins.json
    installPaths (registry ids, union enablement — see _installed_plugin_entries),
    narrowed to installed+enabled. Codex and OMP hits are unfiltered whole-cache
    globs: Codex tracks enablement in config.toml (TOML, not stdlib-parseable on
    the 3.10 floor), and OMP ships no manifest seam either — a few stale entries
    beat a blind spot over an entire harness's skill universe. OMP's cache holds
    only INSTALLED plugins by construction (node_modules/ is a symlink farm back
    into it). ZCode hits are registry-enumerated (ADR-0042) — pre-filtered by
    construction. Every non-Claude cache is globbed at two depths (see
    _nested_glob) so category-grouped plugins are not silently invisible.

    SKILL_PLUGIN_FILTER=0 restores the pre-filter whole-cache Claude behaviour
    (naming falls back to the _namespaced_name heuristic)."""
    # _glob_both_depths yields raw glob STRINGS; every path leaving this function
    # must be a Path — discover_skill_paths concatenates them and parse_skill calls
    # .read_text on each (a stray str crashes every hit of that harness, swallowed
    # by parse_skill's read guard as a silent drop).
    codex_hits = [Path(p) for p in _glob_both_depths(CODEX_PLUGIN_GLOB)] if CODEX_ROOTS else []
    omp_hits = [Path(p) for p in _glob_both_depths(OMP_PLUGIN_GLOB)] if OMP_ROOTS else []
    zcode_hits = _zcode_plugin_paths()

    if not SKILL_PLUGIN_FILTER:
        claude_hits = [Path(p) for p in _glob_both_depths(PLUGIN_GLOB)]
        return claude_hits + codex_hits + omp_hits + zcode_hits

    entries = _installed_plugin_entries()
    if entries is not None:
        # Positive-empty ({}) is respected: the readable layers just said every
        # plugin is off, and a whole-cache fallback here would resurrect exactly
        # what the exclusion rule removed.
        return _claude_plugin_skill_paths(entries) + codex_hits + omp_hits + zcode_hits

    log.warning("plugin manifests unreadable — indexing the whole cache "
                "(stale versions and disabled plugins included)")
    claude_hits = [Path(p) for p in _glob_both_depths(PLUGIN_GLOB)]
    return claude_hits + codex_hits + omp_hits + zcode_hits


def discover_skill_paths() -> list[Path]:
    """Every SKILL.md path across personal dirs, project dirs, and plugins."""
    paths: list[Path] = []
    for d in SKILL_DIRS:
        if d.exists():
            paths += [Path(p) for p in glob.glob(str(d / "*" / "SKILL.md"))]
    paths += _plugin_paths()
    return paths


def _scope_for(path: Path) -> str:
    """The scope that OWNS this skill.

    Claude Code runs one MCP server per session, each with its own CWD, and they
    all share one Qdrant collection. Points must record who owns them so a
    reindex in session A cannot prune session B's project skills (they simply
    look "deleted from disk" from A's vantage point). Codex, Command Code and
    OMP paths get DISTINCT scope names (ADR-0033, ADR-0038) so all harnesses'
    skills stay identifiable while any session on the machine can prune skills
    genuinely gone from disk.
    """
    p = str(path)
    if p.startswith(str(PERSONAL_ROOT) + os.sep):
        return "personal"
    if p.startswith(str(CODEX_PERSONAL_ROOT) + os.sep):
        return "codex-personal"
    if p.startswith(str(COMMANDCODE_PERSONAL_ROOT) + os.sep):
        return "commandcode-personal"
    if p.startswith(str(OMP_PERSONAL_ROOT) + os.sep):
        return "omp-personal"
    if p.startswith(str(OMP_MANAGED_ROOT) + os.sep):
        return "omp-managed"
    if p.startswith(str(ZCODE_PERSONAL_ROOT) + os.sep):
        return "zcode-personal"
    if p.startswith(str(DSH_PERSONAL_ROOT) + os.sep):
        return "dsh-personal"
    if p.startswith(str(CLINE_PERSONAL_ROOT) + os.sep):
        return "cline-personal"
    if f"{os.sep}plugins{os.sep}cache{os.sep}" in p:
        if f"{os.sep}.codex{os.sep}" in p:
            return "codex-plugin"
        # OMP's plugin cache lives under ~/.omp/plugins/cache/plugins/**; the
        # ".omp" path segment distinguishes it from Claude's own cache.
        if f"{os.sep}.omp{os.sep}" in p:
            return "omp-plugin"
        # ZCode's cache lives under ~/.zcode/cli/plugins/cache/** — checked BEFORE
        # the generic fallthrough so a ZCode plugin skill never lands in Claude's
        # `plugin` scope (ADR-0042; live defect this closes: the shared /plugins/cache/
        # substring alone misattributed it).
        if f"{os.sep}.zcode{os.sep}" in p:
            return "zcode-plugin"
        return "plugin"
    if p.startswith(str(CODEX_PROJECT_ROOT) + os.sep):
        return f"codex-project:{CODEX_PROJECT_ROOT}"
    if p.startswith(str(COMMANDCODE_PROJECT_ROOT) + os.sep):
        return f"commandcode-project:{COMMANDCODE_PROJECT_ROOT}"
    if p.startswith(str(OMP_PROJECT_ROOT) + os.sep):
        return f"omp-project:{OMP_PROJECT_ROOT}"
    if p.startswith(str(ZCODE_PROJECT_ROOT) + os.sep):
        return f"zcode-project:{ZCODE_PROJECT_ROOT}"
    if p.startswith(str(ZCODE_AGENTS_PROJECT_ROOT) + os.sep):
        return f"zcode-project:{ZCODE_AGENTS_PROJECT_ROOT}"
    if p.startswith(str(DSH_PROJECT_ROOT) + os.sep):
        return f"dsh-project:{DSH_PROJECT_ROOT}"
    if p.startswith(str(CLINE_PROJECT_ROOT) + os.sep):
        return f"cline-project:{CLINE_PROJECT_ROOT}"
    return f"project:{PROJECT_ROOT}"


def visible_scopes() -> set[str]:
    """Scopes THIS process is authoritative for — may prune and may search.
    Catalog scopes (ADR-0031) are machine-wide like `personal`: the config lives
    in the machine-global durable home, so every session sees the same set and no
    cross-session prune war is possible. Removing a root from the config removes
    its scope here, and the next reindex prunes its points via the existing
    scope-visibility mechanism — teardown needs nothing new."""
    scopes = {"personal", "plugin", f"project:{PROJECT_ROOT}"}
    if CODEX_ROOTS:
        scopes |= {"codex-personal", "codex-plugin", f"codex-project:{CODEX_PROJECT_ROOT}"}
    if COMMANDCODE_ROOTS:
        scopes |= {"commandcode-personal", f"commandcode-project:{COMMANDCODE_PROJECT_ROOT}"}
    if OMP_ROOTS:
        scopes |= {"omp-personal", "omp-managed", "omp-plugin", f"omp-project:{OMP_PROJECT_ROOT}"}
    if ZCODE_ROOTS:
        scopes |= {"zcode-personal", "zcode-plugin",
                   f"zcode-project:{ZCODE_PROJECT_ROOT}",
                   f"zcode-project:{ZCODE_AGENTS_PROJECT_ROOT}"}
    if DSH_ROOTS:
        scopes |= {"dsh-personal", f"dsh-project:{DSH_PROJECT_ROOT}"}
    if CLINE_ROOTS:
        scopes |= {"cline-personal", f"cline-project:{CLINE_PROJECT_ROOT}"}
    return scopes | {f"catalog:{a}" for a in catalog_roots()}


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
    """Parsed skill dicts (deduped by name, precedence = personal -> project ->
    plugin -> catalog). Catalog skills (ADR-0031) come LAST so anything installed
    always wins a name collision, and a catalog skill whose SKILL.md resolves to
    the same file as an already-found skill (a promoted symlink in
    ~/.claude/skills pointing back into the catalog clone) is suppressed — the
    promoted personal copy is the invokable truth, the catalog twin is noise."""
    found: dict[str, dict] = {}
    for p in discover_skill_paths():
        skill = parse_skill(p)
        if skill and skill["name"]:
            skill["scope"] = _scope_for(p)
            found.setdefault(skill["name"], skill)   # first writer wins
    seen_real = set()
    for s in found.values():
        try:
            seen_real.add(os.path.realpath(s["path"]))
        except OSError:
            pass
    for skill in _catalog_skills():
        try:
            if os.path.realpath(skill["path"]) in seen_real:
                continue                             # promoted twin — personal copy wins
        except OSError:
            pass
        found.setdefault(skill["name"], skill)       # installed name always wins
    return list(found.values())
