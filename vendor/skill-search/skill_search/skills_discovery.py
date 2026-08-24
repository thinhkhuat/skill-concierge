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
SKILL_DIRS = [PERSONAL_ROOT, PROJECT_ROOT] + (
    [CODEX_PERSONAL_ROOT, CODEX_PROJECT_ROOT] if CODEX_ROOTS else [])
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


def _plugin_paths() -> list[Path]:
    """Cache SKILL.md paths from BOTH harnesses' plugin caches (ADR-0033).

    Claude hits are narrowed to installed+enabled via installed_plugins.json.
    Codex hits are unfiltered: Codex tracks enablement in config.toml (TOML,
    not stdlib-parseable on the 3.10 floor), and a few stale entries beat a
    blind spot over Codex's entire skill universe — the same trade the
    unreadable-manifest fallback already makes for Claude.

    Both caches are globbed at two depths (see _nested_glob) so category-grouped
    plugins are not silently invisible.
    """
    hits = _glob_both_depths(PLUGIN_GLOB)
    codex_hits = _glob_both_depths(CODEX_PLUGIN_GLOB) if CODEX_ROOTS else []
    if not SKILL_PLUGIN_FILTER:
        return [Path(p) for p in hits + codex_hits]

    roots = _installed_plugin_roots()
    if roots is None:
        log.warning("plugin manifests unreadable — indexing the whole cache "
                    "(stale versions and disabled plugins included)")
        return [Path(p) for p in hits + codex_hits]

    kept = [p for p in hits if any(p.startswith(r + os.sep) for r in roots)]
    kept += codex_hits
    if not kept:
        log.warning("installed/enabled filter matched no cache skills — "
                    "falling back to the unfiltered cache")
        return [Path(p) for p in hits + codex_hits]
    if len(kept) < len(hits) + len(codex_hits):
        log.info("plugin cache: kept %d of %d SKILL.md (Claude installed+enabled; all Codex)",
                 len(kept), len(hits) + len(codex_hits))
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
    """The scope that OWNS this skill.

    Claude Code runs one MCP server per session, each with its own CWD, and they
    all share one Qdrant collection. Points must record who owns them so a
    reindex in session A cannot prune session B's project skills (they simply
    look "deleted from disk" from A's vantage point). Codex paths get DISTINCT
    scope names (ADR-0033) so the two harnesses' skills stay identifiable while
    any session on the machine can prune skills genuinely gone from disk.
    """
    p = str(path)
    if p.startswith(str(PERSONAL_ROOT) + os.sep):
        return "personal"
    if p.startswith(str(CODEX_PERSONAL_ROOT) + os.sep):
        return "codex-personal"
    if f"{os.sep}plugins{os.sep}cache{os.sep}" in p:
        if f"{os.sep}.codex{os.sep}" in p:
            return "codex-plugin"
        return "plugin"
    if p.startswith(str(CODEX_PROJECT_ROOT) + os.sep):
        return f"codex-project:{CODEX_PROJECT_ROOT}"
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
