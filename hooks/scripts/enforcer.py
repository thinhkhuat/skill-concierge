#!/usr/bin/env python3
"""
skill-concierge — semantic skill-first enforcer (UserPromptSubmit hook).

Supersedes the lexical ~/.claude/hooks/skill_first_nudge.py. On a non-trivial
prompt it embeds the query via the warm embed shim, retrieves the top-k semantic
candidates from the SAME Qdrant index skill-search serves, and injects an
enforcement mandate + those candidates (name · desc · score). It surfaces
semantically-relevant skills the old token-overlap scorer missed (e.g. an EN
prompt finding a VN-described skill with zero lexical overlap).

Design contract (mirrors the sibling ledger hook):
  • FAIL-SILENT — any error exits 0; a hook must never break or block a turn.
  • ADDITIVE-ONLY — only ever emits hookSpecificOutput.additionalContext.
  • NEVER BLOCKS — no exit-2, no "decision":"block".
  • STDLIB-ONLY + lazy — no heavy imports; the trivial-getaway path does no I/O.

Resilience / budget (Phase 3). The embed POST has a HARD client-side socket
timeout (see EMBED_TIMEOUT_S for the calibration history; live default 350ms). Every
network leg is separately capped, so the worst case is the sum of the caps, not an
unbounded wait: 350ms embed + 100ms installed query + up to 2x100ms actionability gate
+ 100ms external annex + 100ms cross-harness annex ~= 850ms, against a 5s hook timeout.
The happy path is ~100ms; the annex legs run only on turns that actually carry an offer. On ANY of (a) embed unreachable, (b) Qdrant unreachable, (c)
embed exceeds the timeout, the hook falls back to MANDATE-ONLY — never silent,
never crashing — and stays within the per-turn budget regardless of shim health.
(c) is load-bearing: a reachability check misses an up-but-slow shim that would
otherwise silently tax every prompt.

Telemetry. Emits an `offer` event to the shared invocation ledger so analyze.py
can compute hit@k and fallback rate:
  {t, sid, ev:"offer", band, offered:[[name,score]...], fallback, q:<≤120c>}
"""
import json
import os
import re
import sys
import tempfile
import time
import unicodedata
import urllib.request
from pathlib import Path

# ── endpoints ────────────────────────────────────────────────────────────────
EMBED_PORT = os.environ.get("EMBED_SHIM_PORT", "6363")
EMBED_HOST = os.environ.get("EMBED_SHIM_HOST", "127.0.0.1")
EMBED_URL = f"http://{EMBED_HOST}:{EMBED_PORT}/embed"
QDRANT_URL = os.environ.get("SKILL_QDRANT_URL", "http://localhost:6333").rstrip("/")
COLLECTION = os.environ.get("SKILL_COLLECTION", "claude_skills")
QUERY_GROUPS_URL = f"{QDRANT_URL}/collections/{COLLECTION}/points/query/groups"

# ── tuning (calibrated on the live mpnet index, 2026-06-26) ───────────────────
# mpnet multilingual cosines are compressed into a narrow band: pure trivia
# ("thanks, that worked") tops ~0.11; real tasks land ~0.22-0.40. A single LOW
# getaway floor cleanly drops trivia while still surfacing modest-but-real
# semantic-jump matches (the whole point of going semantic). The score is a
# RANK signal, not absolute confidence — so we show top-k above the floor rather
# than gating hard on a high threshold. Tune from the ledger's offered-but-never-
# taken rollups once data accrues.
# HARD embed cap. History: design nominal ~120ms → tuned to 90ms to fit a ≲150ms
# total budget. But LIVE dogfooding showed ~60% of turns hit embed_timeout: the
# single-threaded shim's inference, under real in-turn CPU contention (concurrent
# UserPromptSubmit hooks + overlapping sessions), exceeded 90ms even though it's
# ~18ms idle. Fix (owner-approved): threaded shim (embed_server.py) + relax the
# budget to ≲300ms total → 200ms embed cap (widened 0.20→0.35 in 0.22 to cut 65% fallback; hook budget is 5s, so the extra 150ms is cheap). Worst slow-path ≈ 50ms cold-start +
# 200ms cap ≈ 250ms ≲ 300ms; happy path stays ~100ms. Raise/lower via env.
EMBED_TIMEOUT_S = float(os.environ.get("ENFORCER_EMBED_TIMEOUT", "0.35"))
QDRANT_TIMEOUT_S = float(os.environ.get("ENFORCER_QDRANT_TIMEOUT", "0.1"))
TOP_K = int(os.environ.get("ENFORCER_TOP_K", "8"))   # offer-menu breadth (was 5; owner-widened 2026-07-05). Wider = more push-noise, against ADR-0009's noise-reduction intent — env-overridable, revert default 5.
GETAWAY_FLOOR = float(os.environ.get("ENFORCER_GETAWAY_FLOOR", "0.45"))  # top<this → silent. OPERATOR-SET 0.45 (2026-06-29, ADR-0009) raised from 0.40 on perceived behaviour; the ledger/corpus analysis argued AGAINST it (taken offers score LOWER than dodged, so a higher floor cuts the better-converting offers first). Do NOT change without re-opening ADR-0009 (data-backed alternative: 0.40 / env ENFORCER_GETAWAY_FLOOR).
ITEM_FLOOR = float(os.environ.get("ENFORCER_ITEM_FLOOR", "0.18"))       # per-candidate cutoff

# ── external catalog annex (ADR-0032) ─────────────────────────────────────────
# External catalog skills (payload tier=external, ADR-0031) become first-class in the
# per-turn offer as an ADDITIVE ANNEX: the installed top-k is untouched (zero displacement),
# and up to EXTERNAL_SLOTS externals scoring ≥ EXTERNAL_FLOOR are appended, marked, consumed
# via get_skill read-inline (they are not Skill-tool-invocable). This preserves the concierge's
# zero-resident-cost property (the offer is an on-demand query, not the resident listing) while
# giving the agent a genuinely large catalog. The external floor is deliberately HIGHER than the
# installed ITEM_FLOOR (0.18) so externals annex only on strong intent-match — most turns show
# none; this asymmetry is the injection-surface safeguard. Kill-switch EXTERNAL_ANNEX=0 restores
# the ADR-0031 search-only tier (must_not tier=external in the query, no annex).
EXTERNAL_ANNEX = os.environ.get("ENFORCER_EXTERNAL_ANNEX", "1") != "0"
EXTERNAL_FLOOR = float(os.environ.get("ENFORCER_EXTERNAL_FLOOR", "0.40"))

# ── dynamic annex sizing (ADR-0036) ───────────────────────────────────────────
# The annexes were fixed at 2 rows regardless of intent. Measured on the live index, that is
# wrong in BOTH directions: the external pool (~1.9k skills) has 8+ rows above the 0.40 floor on
# essentially every offer-bearing turn (an absolute floor discriminates nothing), while on
# strong-inventory turns the fixed 2 pads the offer with rows the installed shelf already beats.
#
# Competitive-margin rule: an annex row earns a slot by scoring >= max(pool floor,
# top_installed - ANNEX_MARGIN), capped at the pool's slot cap. The threshold RISES with the
# installed top, so a well-served intent shrinks the annex to 0-1 (less noise than fixed-2), and
# FALLS to the pool floor when the inventory is thin, widening the annex to its cap — the annex
# width itself becomes a read of "what the inventory can offer for this intent". Deterministic
# hits (score 1.0) push the threshold near 1.0 and naturally silence the annexes: explicit
# intent wants no alternatives. Margin 0.05 is measured, not guessed: on the compressed mpnet
# cosine band (real tasks ~0.5-0.9), 0.10+ saturates every annex at its cap while 0.05 cleanly
# separates strong-inventory intents (annex 1) from external-dominated ones (annex 4).
# ENFORCER_ANNEX_DYNAMIC=0 reverts byte-identically to the fixed sizing (and the old
# EXTERNAL_SLOTS default of 2). The installed TOP_K is untouched either way — dynamism governs
# annex WIDTH only; the ADR-0032/0034 zero-displacement invariant is not negotiable here.
ANNEX_DYNAMIC = os.environ.get("ENFORCER_ANNEX_DYNAMIC", "1") != "0"
ANNEX_MARGIN = float(os.environ.get("ENFORCER_ANNEX_MARGIN", "0.05"))
EXTERNAL_SLOTS = int(os.environ.get("ENFORCER_EXTERNAL_SLOTS", "4" if ANNEX_DYNAMIC else "2"))


def _annex_floor(pool_floor: float, top_installed: float) -> float:
    """The per-turn score threshold an annex row must clear. Fixed mode: the pool floor,
    unchanged. Dynamic mode: competitive with the best installed row, never below the floor.
    top_installed <= 0 means no installed candidates — fall back to the pool floor rather than
    suppressing the annex (an empty inventory is the case externals exist for)."""
    if not ANNEX_DYNAMIC or top_installed <= 0:
        return pool_floor
    return max(pool_floor, top_installed - ANNEX_MARGIN)

# ── cross-harness offer isolation (ADR-0034) ──────────────────────────────────
# ADR-0033 indexes BOTH harnesses' skill universes into one shared collection, and the
# installed query carried no scope filter — so in a Claude session the Codex plugin cache
# competed for the TOP_K installed slots with skills the Skill tool CANNOT invoke here
# (measured 2026-08-24: up to 6 of 8 offer rows), and the mirror held in Codex sessions for
# Claude's `plugin` scope. An offer row the agent cannot act on is worse than no row: it burns
# a slot AND invites a false `USING:`.
#
# Fix = the ADR-0032 shape, one layer up: keep foreign-harness skills out of the INSTALLED
# offer, then re-surface them as a SEPARATE marked annex consumed via get_skill.
# Discoverability is kept; invocability is never implied.
#
# WHY A POST-FILTER, NOT A QDRANT `must_not scope`. Scope records WHERE the indexed copy of a
# skill lives, which is NOT the same question as "can this harness invoke it". When the SAME
# plugin is installed on both sides, discovery dedups to ONE point and the Codex path can win
# the name — so a `codex-plugin` row may name a skill Claude invokes perfectly well. A pre-filter
# cannot see that and silently drops it (observed: 24 `agent-skills:*` skills). The query
# therefore over-fetches and the decision is made per row, where the twin test is available.
# Bonus: it keeps an unindexed keyword filter off the installed query's hot path.
CROSS_HARNESS = os.environ.get("ENFORCER_CROSS_HARNESS", "1") != "0"
# Over-fetch, post-filter, trim to TOP_K. The multiplier is HEADROOM, not a guarantee: in a
# domain the other harness dominates, more than RETRIEVE_LIMIT-TOP_K of the top groups can be
# foreign and the menu comes back short. Measured on the live index: x3 left two of
# thirty probes under-filled (5 and 7 rows, needing 30 and 25 groups); x4 still missed one of
# sixty ("vercel edge config feature flags", 7 rows, 35 groups needed); x5 covers every case
# observed so far, for about a millisecond of extra groups. It stays HEADROOM regardless — a
# shorter menu of invocable rows beats a full one padded with rows the agent cannot act on, so
# under-fill is the accepted degradation rather than a bug to pad around.
RETRIEVE_LIMIT = TOP_K * 5


def _running_harness() -> str:
    """Which harness is executing this hook.

    Returns one of: 'commandcode', 'codex', 'omp', 'zcode', or 'claude'.

    PRECEDENCE:
    1. Explicit env override: `SKILL_CONCIERGE_HARNESS` (used by the Command Code mod adapter
       and the OMP adapter; OMP also maps `oh-my-pi` so the natural name resolves).
    2. Native harness detection BEFORE path markers: `OMPCODE=1` -> 'omp'. OMP sets BOTH
       `OMPCODE` and `CLAUDE`'s own markers (`CLAUDE_PLUGIN_ROOT`, `CLAUDE.md` presence, etc.),
       so `OMPCODE=1` alone is proof of OMP; `CLAUDE`-only markers never are (OMP's provider
       union reads .claude too, but that is discovery, not the acting harness).
       `ZCODE_PLUGIN_ROOT` (absolute) -> 'zcode': ZCode injects it — alongside
       `CLAUDE_PLUGIN_ROOT` — into plugin-hook processes, so it is a positive zcode signal
       available before path markers; no other harness sets it. A falsy or non-absolute
       value is never probed (`Path("")` is the cwd, the ADR-0034 falsy-candidate rule).
    3. Where the hook/plugin was installed: `.omp` in path -> 'omp', `.codex` in path -> 'codex',
       `.zcode` in path -> 'zcode', `.claude` in path -> 'claude'.
    4. Fallback: 'claude' (the pre-ADR-0038 default; commandcode runs through its mod
       adapter, which sets SKILL_CONCIERGE_HARNESS explicitly).
    """
    explicit = os.environ.get("SKILL_CONCIERGE_HARNESS", "").strip().lower()
    if explicit in ("commandcode", "cmd", "command-code"):
        return "commandcode"
    if explicit in ("codex", "claude", "omp", "oh-my-pi"):
        return "omp" if explicit in ("omp", "oh-my-pi") else explicit
    if explicit in ("zcode", "z-code"):
        return "zcode"

    if os.environ.get("OMPCODE", "").strip() == "1":
        return "omp"

    _zpr = os.environ.get("ZCODE_PLUGIN_ROOT", "").strip()
    if _zpr and os.path.isabs(_zpr):
        return "zcode"

    marker_omp = f"{os.sep}.omp{os.sep}"
    marker_codex = f"{os.sep}.codex{os.sep}"
    marker_zcode = f"{os.sep}.zcode{os.sep}"
    marker_claude = f"{os.sep}.claude{os.sep}"
    for cand in (os.environ.get("CLAUDE_PLUGIN_ROOT"), __file__):
        if not cand or not os.path.isabs(cand):
            continue
        try:
            resolved = str(Path(cand).resolve())
        except OSError:
            resolved = ""
        if marker_omp in resolved:
            return "omp"
        if marker_codex in resolved:
            return "codex"
        if marker_zcode in resolved:
            return "zcode"
        if marker_claude in resolved:
            return "claude"
    return "claude"


RUNNING_HARNESS = _running_harness()
UNDER_CODEX = (RUNNING_HARNESS == "codex")
UNDER_COMMANDCODE = (RUNNING_HARNESS == "commandcode")
UNDER_OMP = (RUNNING_HARNESS == "omp")
UNDER_ZCODE = (RUNNING_HARNESS == "zcode")


def _foreign_harness_label() -> str:
    if RUNNING_HARNESS == "codex":
        return "claude"
    if RUNNING_HARNESS == "commandcode":
        return "claude/codex"
    if RUNNING_HARNESS == "omp":
        # OMP's native provider union (claude + claude-plugins + codex + native) reads the
        # claude/codex/omp scopes, so the cross-harness annex for an OMP session points at the
        # one harness it does NOT read: Command Code. The label drives the `[Commandcode]`
        # marker in the annex render.
        return "commandcode"
    if RUNNING_HARNESS == "zcode":
        # ZCode reads only its own roots (~/.zcode/skills, ~/.agents/skills, its plugin
        # cache) — every OTHER harness's scopes are foreign here, so the residual pool is
        # compound (Command Code's label precedent).
        return "claude/codex/omp"
    return "codex"


FOREIGN_HARNESS = _foreign_harness_label()


def _zcode_shares_personal_shelf() -> bool:
    """True iff ZCode's ~/.agents/skills root resolves to Claude's personal root — the
    shared-shelf layout where every `personal`-scoped skill is ZCode-invocable through
    the symlink (observed live 2026-08-28: ~/.agents/skills -> ~/.claude/skills). Anything
    else — divergent directory, missing directory, OSError — is NOT positive knowledge;
    the caller then treats `personal` as foreign and per-row survival moves to the
    filesystem twin check. Resolved per session, never baked into the machine-global
    index (the ADR-0028 cwd-scoped-view hazard)."""
    try:
        agents = Path.home() / ".agents" / "skills"
        claude = Path.home() / ".claude" / "skills"
        return agents.is_dir() and claude.is_dir() and agents.resolve() == claude.resolve()
    except (OSError, RuntimeError):
        return False


def _foreign_scopes() -> tuple:
    """The scopes whose skills the RUNNING harness cannot invoke.

    From Claude: both Codex scopes + commandcode-personal.
    From Codex: plugin + commandcode-personal.
    From Command Code: plugin + codex-plugin + codex-personal + personal (Command Code
    only loads its own personal/project roots + extra settings locations).
    From OMP: codex-plugin + commandcode-personal. OMP's provider union natively invokes the
    claude (user+project .claude/skills), claude-plugin (claude-plugins registry roots) and
    codex personal (.codex/skills) scopes, but NOT the Codex plugin cache — the codex provider
    scans only `~/.codex/skills` and `<cwd>/.codex/skills` (OMP source discovery/codex.ts:238-240,
    loadSkills), so `codex-plugin` rows are foreign here. commandcode scopes are foreign too
    (OMP never loads Command Code's personal/project roots).
    From ZCode (ADR-0042): every other harness's plugin caches and native roots. `personal`
    joins the foreign set ONLY when ZCode's ~/.agents/skills root does NOT resolve to
    Claude's personal root — the shared-shelf symlink is positive knowledge the whole
    scope is ZCode-invocable; on a divergent machine per-row survival moves to the
    `_invocable_twin` filesystem check instead.

    `project:` scopes are cwd-derived and shared by construction. Never foreign.
    """
    if RUNNING_HARNESS == "commandcode":
        return ("plugin", "codex-plugin", "codex-personal")
    if RUNNING_HARNESS == "codex":
        return ("plugin", "commandcode-personal")
    if RUNNING_HARNESS == "omp":
        return ("codex-plugin", "commandcode-personal")
    if RUNNING_HARNESS == "zcode":
        base = ("plugin", "codex-plugin", "codex-personal", "commandcode-personal",
                "omp-personal", "omp-managed", "omp-plugin")
        return base if _zcode_shares_personal_shelf() else base + ("personal",)
    return ("codex-plugin", "codex-personal", "commandcode-personal")

FOREIGN_SCOPES = _foreign_scopes()


FOREIGN_SLOTS = int(os.environ.get("ENFORCER_FOREIGN_SLOTS", "2"))
FOREIGN_FLOOR = float(os.environ.get("ENFORCER_FOREIGN_FLOOR", "0.40"))

# Claude Code decides whether a plugin skill is invocable from TWO files, and skills_discovery
# consults them differently than a per-session view needs:
#   installed_plugins.json -> plugins[<id>@<marketplace>][].installPath   (is it on disk here)
#   settings enabledPlugins[<id>@<marketplace>] : bool                    (is it switched on)
# Enablement LAYERS across user -> project -> project-local, last writer wins, and a key ABSENT
# from enabledPlugins is ENABLED (skills_discovery.py mirrors that rule). skills_discovery reads
# the USER file only, so a plugin enabled just for this project is dropped from discovery and its
# sibling-harness twin wins the name — leaving a `codex-plugin` point for a skill Claude invokes
# fine. That is the twin test the post-filter needs, and it must be resolved HERE (per session,
# per cwd) rather than at index time: the index is machine-global and shared across sessions, so
# a cwd-scoped view baked into it would make concurrent sessions fight over each other's points
# (the ADR-0028 hazard).
_INSTALLED_PLUGINS_JSON = Path(os.environ.get(
    "SKILL_INSTALLED_PLUGINS", Path.home() / ".claude" / "plugins" / "installed_plugins.json"))

# OMP's claude-plugins provider ALSO loads ~/.omp/plugins/installed_plugins.json, treating its
# entries as authoritative over Claude's for the same plugin ID (OMP source discovery/helpers.ts:
# 1030-1078). Per-entry gating is the OMP registry's own `enabled` field — `enabled === false`
# hides the plugin (helpers.ts:1061); an absent field is enabled-by-default, mirroring the
# Claude-side rule. So an OMP session can invoke a plugin whose id lives in EITHER registry
# (and is not switched off), and the twin test must consult both when running under OMP.
_OMP_INSTALLED_PLUGINS_JSON = Path(os.environ.get(
    "SKILL_OMP_INSTALLED_PLUGINS", Path.home() / ".omp" / "plugins" / "installed_plugins.json"))

# ZCode's own registries (ADR-0042): installed_plugins.json is a LIST of
# {id: "<name>@<marketplace>", installPath, ...}; enablement lives in
# ~/.zcode/cli/config.json -> plugins.enabledPlugins (absent key = enabled) with
# plugins.suppressedBuiltins for the builtin plugins, which never appear in the registry.
_ZCODE_INSTALLED_PLUGINS_JSON = Path(os.environ.get(
    "SKILL_ZCODE_INSTALLED_PLUGINS", Path.home() / ".zcode" / "cli" / "plugins" / "installed_plugins.json"))
_ZCODE_CONFIG_JSON = Path(os.environ.get(
    "SKILL_ZCODE_CONFIG", Path.home() / ".zcode" / "cli" / "config.json"))
_ZCODE_PLUGIN_CACHE = Path(os.environ.get(
    "SKILL_ZCODE_PLUGIN_CACHE", Path.home() / ".zcode" / "cli" / "plugins" / "cache"))


def _zcode_invocable_plugin_ids():
    """Plugin NAME ids a ZCode session can invoke (ADR-0042).

    '<name>@<marketplace>' ids from ZCode's installed_plugins.json (installation checked —
    installPath on disk — like the Claude loop) plus the builtin cache plugins (newest
    version dir present), gated by config.json plugins.enabledPlugins (an explicit false
    disables; an absent key means enabled — ZCode writes explicit true entries and leaves
    the rest implied) minus suppressedBuiltins. Claude's registry/settings are never
    consulted under zcode: they describe a different harness's sessions.

    Returns None when NOTHING is positively readable — None means UNKNOWN and the caller
    filters nothing (fail toward ADR-0033's union). An empty-but-readable world is a
    positive empty set. Everything filesystem-touching is guarded (the deleted-cwd rule)."""
    ids: set = set()
    saw_any = False
    disabled: dict = {}
    suppressed: set = set()
    try:
        cfg = json.loads(_ZCODE_CONFIG_JSON.read_text(encoding="utf-8"))
        pcfg = cfg.get("plugins") if isinstance(cfg, dict) and isinstance(cfg.get("plugins"), dict) else {}
        em = pcfg.get("enabledPlugins") if isinstance(pcfg.get("enabledPlugins"), dict) else {}
        disabled = {str(k) for k, v in em.items() if v is False}
        suppressed = {str(s) for s in (pcfg.get("suppressedBuiltins") or []) if s}
    except (OSError, UnicodeError, ValueError, TypeError, AttributeError):
        pass
    registry_ids: set = set()
    try:
        installed = json.loads(_ZCODE_INSTALLED_PLUGINS_JSON.read_text(encoding="utf-8"))
        if isinstance(installed, dict) and isinstance(installed.get("plugins"), list):
            for entry in installed["plugins"]:
                if not isinstance(entry, dict):
                    continue
                pid = str(entry.get("id") or "")
                path = entry.get("installPath")
                if pid and path and Path(str(path)).is_dir():
                    saw_any = True
                    registry_ids.add(pid)
                    if pid not in disabled:
                        ids.add(pid.split("@", 1)[0])
    except (OSError, UnicodeError, ValueError, TypeError, AttributeError):
        pass
    # Builtins: cache plugin dirs with no registry entry (the official marketplaces'
    # plugins are enabled-but-unregistered). The cache is append-only, so "installed"
    # for a builtin = at least one version dir exists.
    try:
        for mkt in _ZCODE_PLUGIN_CACHE.iterdir():
            for plug in mkt.iterdir():
                pid = f"{plug.name}@{mkt.name}"
                if pid in registry_ids or pid in suppressed or pid in disabled:
                    continue
                if any(v.is_dir() for v in plug.iterdir()):
                    saw_any = True
                    ids.add(plug.name)
    except (OSError, ValueError, TypeError):
        pass
    if not saw_any:
        return None
    return ids


def _invocable_plugin_ids():
    """Plugin ids THIS session can invoke: present in an installed-plugins registry AND not
    explicitly switched off. Returns e.g. {'agent-skills', 'memsearch'}.

    Returns None when NO installed-plugins manifest can be read. None means UNKNOWN, and the
    caller must then filter NOTHING — failing toward ADR-0033's union, which is merely noisy and
    already shipped, never toward telling the agent a skill it CAN invoke is 'NOT invocable here'.

    Under Claude the manifest is `~/.claude/plugins/installed_plugins.json` and a plugin is
    disabled by an explicit `false` in the merged settings `enabledPlugins` layers (absent key =
    enabled, matching Claude Code and `skills_discovery._installed_plugin_roots`). Under OMP the
    claude-plugins provider reads the SAME claude registry PLUS the OMP registry
    (`~/.omp/plugins/installed_plugins.json`) — OMP entries are authoritative for their plugin id
    (OMP source discovery/helpers.ts:1030-1078) — and the OMP registry's per-entry `enabled`
    field gates each plugin (`enabled === false` hides it, helpers.ts:1061; absent = enabled).
    The OMP loop applies NO settings-layer enabledPlugins override, so OMP-side disablement is
    the per-entry field alone.

    Installation is checked, not just enablement: a plugin switched on in settings whose cache is
    absent is not invocable, and treating it as a twin would keep a genuinely dead row in the
    offer.

    Marketplace collisions resolve by UNION, not last-writer-wins: skill names carry only the bare
    plugin id, so if ANY `<id>@<marketplace>` copy is installed and on, the id is invocable.
    Everything touching the filesystem is inside the guard — `Path.cwd()` raises when the working
    directory has been deleted, and this runs at import, outside main()'s try."""
    if RUNNING_HARNESS == "zcode":
        # ZCode resolves invocability from ITS OWN registries (ADR-0042); Claude's
        # registry and settings layers describe a different harness's sessions and must
        # not leak ids into the twin test.
        return _zcode_invocable_plugin_ids()
    installed = {}
    saw_registry = False
    try:
        claude_plugins = json.loads(_INSTALLED_PLUGINS_JSON.read_text(encoding="utf-8"))["plugins"]
        if isinstance(claude_plugins, dict):
            installed.update(claude_plugins)
            saw_registry = True
    except (OSError, UnicodeError, ValueError, KeyError, TypeError):
        pass

    # Under OMP the claude-plugins provider ALSO honors the OMP registry (helpers.ts:1030-1078),
    # so an id there is invocable here too. Under Claude the OMP registry is not part of
    # discovery and must not leak ids into the twin test.
    if UNDER_OMP:
        try:
            omp_plugins = json.loads(_OMP_INSTALLED_PLUGINS_JSON.read_text(encoding="utf-8"))["plugins"]
            if isinstance(omp_plugins, dict):
                installed.update(omp_plugins)
                saw_registry = True
        except (OSError, UnicodeError, ValueError, KeyError, TypeError):
            pass

    # None only when NO registry could be read — i.e. the twin test is UNKNOWN (filter
    # nothing, the original claude-only semantics). An empty-but-readable registry is a
    # YES-I-know answer (no plugins installed -> no twins), returned as an empty set.
    if not saw_registry:
        return None

    disabled_by_key = {}
    try:
        layers = (Path.home() / ".claude" / "settings.json",
                  Path.cwd() / ".claude" / "settings.json",
                  Path.cwd() / ".claude" / "settings.local.json")
    except OSError:
        layers = ()
    for f in layers:
        try:
            data = json.loads(f.read_text(encoding="utf-8")).get("enabledPlugins", {})
        except (OSError, UnicodeError, ValueError, AttributeError):
            data = {}
        if isinstance(data, dict):
            disabled_by_key.update({str(k): not bool(v) for k, v in data.items()})
    out = set()
    for key, entries in installed.items():
        if disabled_by_key.get(str(key), False):
            continue
        if isinstance(entries, list) and entries and all(
                isinstance(e, dict) and e.get("enabled") is False for e in entries):
            continue  # every entry explicitly off
        out.add(str(key).split("@", 1)[0])
    return out


INVOCABLE_PLUGIN_IDS = _invocable_plugin_ids()


_ZCODE_READ_ROOTS = (Path.home() / ".agents" / "skills", Path.home() / ".zcode" / "skills")


def _zcode_readable_skill(name: str) -> bool:
    """ADR-0042 filesystem twin: True when `<name>/SKILL.md` exists in a ZCode-readable
    personal root (~/.agents/skills — the shared shelf — or ~/.zcode/skills). This is how
    a `personal`-scoped row survives the foreign filter on machines where the two shelves
    are NOT one symlinked directory, and how un-namespaced foreign rows with a real local
    twin stay offerable. OSError is UNKNOWN — returns True so the caller's
    drop-only-on-positive-knowledge rule keeps the row."""
    try:
        return any((root / name / "SKILL.md").exists() for root in _ZCODE_READ_ROOTS)
    except (OSError, ValueError):
        return True


def _invocable_twin(name: str) -> bool:
    """True when a foreign-scoped row names a skill THIS harness can invoke anyway, because the
    same plugin is installed and switched on here and its twin merely lost the discovery dedup.

    Meaningful from Claude and OMP: both harnesses' claude-plugins provider reads the claude/
    omp plugin registries, so a `claude-plugin` row may name a skill this session invokes.
    Under Codex/Command Code the plugin caches are isolated, so there is no twin to rescue.
    Under ZCode (ADR-0042) TWO rescues apply: the plugin-id twin (a namespaced `plugin:skill`
    row whose plugin is installed+enabled in Zcode's OWN registry) and a FILESYSTEM twin
    (`<name>/SKILL.md` present in a ZCode-readable personal root)."""
    if RUNNING_HARNESS == "zcode":
        if INVOCABLE_PLUGIN_IDS and ":" in name and name.split(":", 1)[0] in INVOCABLE_PLUGIN_IDS:
            return True
        return _zcode_readable_skill(name)
    if RUNNING_HARNESS not in ("claude", "omp") or not INVOCABLE_PLUGIN_IDS or ":" not in name:
        return False
    return name.split(":", 1)[0] in INVOCABLE_PLUGIN_IDS
MAX_SHORT_WORDS = 3   # ≤ this many words → trivial getaway, skip embed entirely. OPERATOR-SET 3 (2026-06-29, ADR-0010 supersedes ADR-0009 word floor) lowered from 5 so the now-language-aware imperative-veto sees 4-5w commands (incl. Vietnamese) the old floor dropped pre-veto; ≤3w ultra-short trivia still skipped. (data-backed analysis favored 2; operator chose 3.) Do NOT change without a superseding ADR.
_CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]")

def _word_count(prompt: str) -> int:
    """MAX_SHORT_WORDS's counting unit, language-aware. ADR-0010 made the floor
    "language-aware" for space-segmented scripts (Vietnamese) but whitespace
    .split() counts an entire Chinese/Japanese/Korean sentence as ONE word —
    every CJK task prompt, however long, hit the ≤3-word trivia pre-gate and
    bypassed mandate+offer entirely (found live 2026-08-25: a 12-char Chinese
    prompt logged a turn row and nothing else). CJK chars carry ~1 word each;
    take the max of the two counts so English behavior is byte-identical
    (zero CJK chars → plain len(split())) and a ≥4-char CJK prompt passes."""
    return max(len(prompt.split()), len(_CJK_RE.findall(prompt)))
_DESC_CHARS = 96

# ── AUTHORIZED-SKIP tier (Phase 1) ────────────────────────────────────────
# The two silent verdict paths below (getaway: top<floor; intent_skip: classified
# conversational) used to return 0 with zero additionalContext, so the agent had no
# signal the hook already ran retrieval + both gates — it would re-invoke search_skills
# to re-derive a verdict already computed here. AUTHORIZED_SKIP swaps that silence for a
# one-line authorization instead (mirrors the GETAWAY_FLOOR / MAX_SHORT_WORDS env-override
# pattern above). ON by default; export ENFORCER_AUTHORIZED_SKIP=0 to restore old silence.
AUTHORIZED_SKIP = os.environ.get("ENFORCER_AUTHORIZED_SKIP", "1") != "0"
# CROSS-FILE CONTRACT: skills/skill-usage-audit/scripts/audit_skill_usage.py (Phase 3) joins
# its false-skip exclusion on this exact literal. Keep the two in sync.
AUTHORIZED_SKIP_MARKER = "SKILL-CHECK:"

# ── actionability gate (prior-independent class-margin over the prompt_intent corpus) ─
# A relevant skill clearing the floor is NOT enough: most "dodged" offers land on
# conversational/status/meta turns that match a skill topically but want none. The gate
# suppresses an offer ONLY when the prompt is non-imperative AND sits closer to
# CONVERSATIONAL space than ACTIONABLE space by a margin (mean top-K cosine to each class).
# A class-MARGIN, not an absolute neighbour count, is used because conversational is the
# minority (~30%) of the ~1.7k-prompt corpus — an absolute count is biased by that prior
# and went inert on novel phrasing. Tuned M=0.03 -> ~2% false-suppression on a held-out
# backtest; validated to fire on out-of-distribution prompts. Fail-OPEN everywhere
# (missing collection / empty class / any error / imperative prompt -> offer).
PROMPT_INTENT_COLLECTION = os.environ.get("SKILL_PROMPT_INTENT_COLLECTION", "prompt_intent")
INTENT_QUERY_URL = f"{QDRANT_URL}/collections/{PROMPT_INTENT_COLLECTION}/points/query"
INTENT_K = int(os.environ.get("ENFORCER_INTENT_K", "10"))                # neighbours per class for the mean-similarity
INTENT_MARGIN = float(os.environ.get("ENFORCER_INTENT_MARGIN", "0.03"))  # suppress iff (conv_sim - act_sim) > this
_IMPERATIVE_VERBS = frozenset(
    ["fix", "build", "create", "add", "write", "implement", "refactor", "update", "integrate", "decouple", "run", "test", "debug", "remove", "delete", "rename", "convert", "migrate", "deploy", "generate", "make", "set", "install", "check", "verify", "review", "analyze", "analyse", "scan", "audit", "do", "apply", "enrich", "wire", "patch", "revert", "merge", "commit", "push", "save", "extract", "port", "draft", "design", "optimize", "optimise", "configure", "investigate", "trace", "diagnose", "produce", "render", "compile", "lint", "format", "sort", "filter", "parse", "split", "trash", "drop", "kill", "start", "stop", "restart", "clean", "tidy", "bump", "tag", "release", "clone", "pull", "fetch", "mine", "label", "embed"])
_FILLER = frozenset(
    ["now", "ok", "okay", "so", "well", "then", "please", "alright", "also", "and", "but", "lets", "let's", "pls", "just", "next", "first", "go", "right", "cool", "good", "great", "yes", "yeah", "sure", "hey", "actually", "hãy", "xin"])

# ── Vietnamese imperative lexicon (mirrors _IMPERATIVE_VERBS for VN task prompts) ──
# The English veto was blind to Vietnamese; the tokenizer now keeps diacritics, and these sets give
# the leading-token check Vietnamese verbs. Vietnamese is analytic — many task verbs are two
# syllables ("kiểm tra", "cài đặt") — so we test the leading token against _VN_VERBS AND the
# leading bigram against _VN_VERB_BIGRAMS. High-precision core; the kNN gate catches the long tail.
# ponytail: core lexicon — widen from real VN prompts if recall proves short.
_VN_VERBS = frozenset(
    ["sửa", "viết", "tạo", "chạy", "xóa", "xoá", "thêm", "dịch", "gỡ", "vá", "soạn", "lưu", "quét", "gộp", "tách", "mở", "đóng", "kéo", "đẩy", "tải", "đọc", "tìm", "lọc", "gọi", "dựng", "đổi", "thử", "dán", "nén", "bỏ", "cài", "vẽ"])
_VN_VERB_BIGRAMS = frozenset([
    ("kiểm", "tra"), ("rà", "soát"), ("cài", "đặt"), ("phân", "tích"), ("tối", "ưu"),
    ("triển", "khai"), ("xử", "lý"), ("cập", "nhật"), ("sửa", "lỗi"), ("chỉnh", "sửa"),
    ("thiết", "kế"), ("tích", "hợp"), ("gỡ", "lỗi"), ("kiểm", "thử"), ("biên", "dịch"),
    ("định", "dạng"), ("khởi", "động"), ("xác", "minh"), ("tái", "cấu"), ("dọn", "dẹp"),
    ("sao", "chép"), ("rà", "lại"),
])

# ── H5 self-referential over-fire lane (ADR-0019) ──────────────────────────
# The gate OVER-fires when a turn merely asks the agent to explain/rephrase its OWN
# immediately-prior message: no external task, no skill applies, yet the mandate would force a
# pointless search_skills. This NARROW lane authorizes that skip. The enforcer sees ONLY the user
# prompt (never the agent's self-narration, enforcer.py fires on UserPromptSubmit), so the detector
# matches a 2nd-person request to operate on the assistant's prior message — and it FALLS THROUGH
# (never fires) the moment any task verb or new-clause connector appears, so a self-ref opener with
# a task tail ("explain your answer AND implement X") routes normally. Default-ON; export
# ENFORCER_SELFREF_SKIP=0 to restore the old 2-lane behaviour. Fail-open: any error → normal routing.
SELFREF_SKIP = os.environ.get("ENFORCER_SELFREF_SKIP", "1") != "0"

# Gate 1 (positive anchor): opens — after fillers — with a recap verb operating on the assistant's
# OWN prior message via a 2nd-person / deictic object. High precision: a generic "explain how DNS
# works" has no such object and falls through. The recap verbs are deliberately NONE of the
# _IMPERATIVE_VERBS, so gate 2 never self-vetoes on the opener.
_SELFREF_RE = re.compile(
    r"^\s*(?:please\s+|just\s+|can\s+you\s+|could\s+you\s+|would\s+you\s+)*"
    r"(?:explain|rephrase|reword|restate|clarify|expand(?:\s+on)?|elaborate(?:\s+on)?|"
    r"summari[sz]e|recap|unpack|simplify)\s+"
    r"(?:your|that|this|the\s+(?:above|last|previous|prior)|what\s+you)\b",
    re.IGNORECASE)

# Gate 3 (tail veto): a new-clause connector after the recap request = an external object → NOT a
# pure recap. Kills the task-tail bypass ("... as a working config", "... by writing the code",
# "... and then deploy") that the verb veto alone can miss when the tail carries no lexicon verb.
_SELFREF_TAIL_RE = re.compile(
    r"\b(?:and|then|also|plus|into|by|using)\b|\bas\s+an?\b|\bso\s+that\b|"
    r"\bto\s+(?:a|an|the)\b|\bwith\s+(?:a|an|the)\b",
    re.IGNORECASE)


LOG_DIR = Path(os.environ.get(
    "SKILL_CONCIERGE_LOG", Path.home() / ".claude" / "skill-concierge" / "logs"))
LEDGER = LOG_DIR / "skill-invocation-ledger.log"

# ── offer-suppression keep-off map (ADR-0011) ────────────────────────────
# Hard-drop chronic never-take skills from the OFFER MENU only (still catalogue-reachable
# via search_skills). Generated by scripts/build_keep_off.py from a post-enrichment clean
# window. FAIL-OPEN: missing/empty/bad file -> empty set -> no suppression.
_KEEPOFF_PATH = Path(os.environ.get(
    "SKILL_CONCIERGE_KEEPOFF",
    Path(__file__).resolve().parents[2] / "config" / "keep-off.json"))


def _load_keepoff() -> frozenset:
    try:
        data = json.loads(_KEEPOFF_PATH.read_text(encoding="utf-8"))
        return frozenset(n for n in data.get("keep_off", []) if isinstance(n, str))
    except (OSError, UnicodeError, ValueError, AttributeError, TypeError):
        return frozenset()  # fail-open: suppression-config must never break a turn


KEEPOFF = _load_keepoff()


def _drop_keepoff(cands: list, keepoff: frozenset):
    """Split retrieved cands into (survivors, dropped-names) by the keep-off set. Pure +
    order-preserving so P6's later gap-collapse runs over the POST-suppression set."""
    survivors = [c for c in cands if c[0] not in keepoff]
    dropped = [c[0] for c in cands if c[0] in keepoff]
    return survivors, dropped


# ── ADR-0029: next-skill chain hint ─────────────────────────────────────────
# Soft chaining: when this session used skill A (auto OR manual — the ledger records
# both) within the TTL and A declares `next-skills:`, append ONE candidate line to
# every inject-bearing leg. Zero network: two bounded local reads (ledger tail +
# sidecar map). The hint BYPASSES NO floor and no gate — hinted names never enter
# `cands`; the line is context only. Filters are mechanized, not asserted:
#   • keep-off (ADR-0011 outranks ANY resurfacing path — `_deterministic_hits` precedent)
#   • catalogue membership via sidecar key presence in a scope VISIBLE from this cwd
#     (kills dangling authoring AND other projects' dead recommendations, ADR-0028).
# Known limit (ADR): the ≤3-word pre-gate (MAX_SHORT_WORDS) injects nothing at all,
# so two-word "go ahead" turns never see a hint — recorded, not carved around.
# Repetition semantics: repeats on each inject-bearing turn within the TTL (one line,
# bounded); consume-on-fire is the recorded upgrade if the epoch shows push-noise
# (it would require re-introducing persistent hint state).
CHAIN_HINT = os.environ.get("ENFORCER_CHAIN_HINT", "1") != "0"
CHAIN_TTL_S = float(os.environ.get("ENFORCER_CHAIN_TTL_S", "900"))
_SIDECAR_PATH = Path(os.environ.get(
    "SKILL_CONCIERGE_NEXT_SKILLS",
    Path.home() / ".claude" / "skill-concierge" / "next-skills.json"))

# ADR-0030: operator-owned chain overrides. next-skills frontmatter lives in the
# SKILL.md that UPSTREAM owns — a plugin/marketplace/AgentKit upgrade rewrites the
# file and the next reindex silently regenerates the sidecar without every curated
# chain (owner-reported 2026-08-20: "GONE without anyone noticed"). Curation of
# third-party skills lives in THIS file instead: flat {name: [successors]} merged at
# READ time, override-wins, [] deliberately suppresses, fail-open. Reader-side on
# purpose: the enforcer is the sidecar's ONLY consumer, so no engine patch, no
# reindex coupling, none of the ADR-0026 env-forwarding gap class. File absent →
# byte-identical behavior.
_NEXT_SKILLS_OVERRIDES = Path(os.environ.get(
    "SKILL_CONCIERGE_NEXT_SKILLS_OVERRIDES",
    Path.home() / ".claude" / "skill-concierge" / "next-skills-overrides.json"))

# ADR-0040: behavior-mined chains (plans/260828-0004 Phase 1). The ledger already
# records ground-truth skill sequences; scripts/build_chains.py mines them offline into
# this durable-home map (support x lift filtered — closure skills that follow everything
# die on lift). Merged as the LOWEST layer under ADR-0030 overrides and ADR-0029 declared
# frontmatter: mined only ever FILLS a name the two human layers left unchained — a name
# present in either layer (even as an explicit [] suppression) is final, never backfilled.
# Keys and successors must resolve in the VISIBLE declared union (same scope-visibility
# rule the declared layer filters by). Default ON: the result rides the existing
# context-only CHAIN-HINT line — no gate, no floor, no candidate-list entry — so the
# blast radius is exactly ADR-0029's one line, sourced from observed behaviour instead
# of 0.4% authoring coverage.
MINED_CHAINS = os.environ.get("ENFORCER_MINED_CHAINS", "1") != "0"
_MINED_CHAINS_PATH = Path(os.environ.get(
    "SKILL_CONCIERGE_MINED_CHAINS",
    Path.home() / ".claude" / "skill-concierge" / "mined-chains.json"))


def _apply_chain_overrides(names: dict) -> dict:
    """Merge the operator-owned override map over the sidecar-derived names.
    Override-wins per whole name; an empty list suppresses that skill's chain.
    Fail-open: unreadable/malformed file returns the input unchanged."""
    try:
        data = json.loads(_NEXT_SKILLS_OVERRIDES.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return names
    if not isinstance(data, dict):
        return names
    for k, v in data.items():
        if isinstance(k, str) and isinstance(v, list):
            names[k] = [s for s in v if isinstance(s, str)]
    return names


def _visible_sidecar_names() -> dict:
    """{name: [successors]} unioned across scopes visible from THIS cwd — mirrors
    skills_discovery scope naming ('personal' | 'plugin' | 'project:<root>' plus the
    codex-* scopes, ADR-0033). A name absent from the union is dangling or
    out-of-scope and cannot be hinted. Fail-open to {} (no hint, never an error)."""
    try:
        data = json.loads(_SIDECAR_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict = {}
    # Path.cwd() raises when the working directory has been deleted (a worktree removed under a
    # live session). This runs on the chain-hint path, evaluated BEFORE _inject, so an unguarded
    # raise here costs the WHOLE offer — silently, exit 0. Fall back to the machine-wide scopes;
    # a project-scoped chain simply does not fire for that turn.
    try:
        cwd = Path.cwd()
    except OSError:
        cwd = None
    scopes = ["personal", "plugin"]
    if cwd is not None:
        scopes.append(f"project:{cwd / '.claude' / 'skills'}")
    if os.environ.get("SKILL_CODEX_ROOTS", "1") != "0":  # ADR-0033 dual-harness mirror
        scopes += ["codex-personal", "codex-plugin"]
        if cwd is not None:
            scopes.append(f"codex-project:{cwd / '.codex' / 'skills'}")
    if os.environ.get("SKILL_ZCODE_ROOTS", "1") != "0":  # ADR-0042 zcode mirror
        scopes += ["zcode-personal", "zcode-plugin"]
        if cwd is not None:
            scopes += [f"zcode-project:{cwd / '.zcode' / 'skills'}",
                       f"zcode-project:{cwd / '.agents' / 'skills'}"]
    for scope in scopes:
        m = data.get(scope)
        if isinstance(m, dict):
            out.update(m)
    filled = _merge_mined_chains(out)     # ADR-0040: observed behaviour fills the unchained
    return _apply_chain_overrides(filled)  # ADR-0030: operator curation wins over BOTH layers


def _merge_mined_chains(names: dict) -> dict:
    """ADR-0040 lowest chain layer. Mined successors backfill ONLY names whose declared
    value is empty — the sidecar writes `[]` for every skill whose author declared no
    next-skills (the 99.6% default), which is absent authoring, NOT suppression; a
    NON-empty declared chain is a real authoring decision and wins. Deliberate
    suppression stays expressible because _apply_chain_overrides runs AFTER this and
    its `[]` replaces whatever mined filled in. Both the key and each successor must be
    keys of the pre-merge map, i.e. members of the catalogue VISIBLE from this cwd — a
    mined name from a foreign project scope must not be hinted here. Fail-open: flag
    off, absent file, malformed file, or wrong shape all return the input unchanged."""
    if not MINED_CHAINS:
        return names
    try:
        doc = json.loads(_MINED_CHAINS_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return names
    chains = doc.get("chains") if isinstance(doc, dict) else None
    if not isinstance(chains, dict):
        return names
    visible = set(names)
    for k, v in chains.items():
        if not isinstance(k, str) or k not in visible or names.get(k) or not isinstance(v, list):
            continue
        succ = [s for s in v if isinstance(s, str) and s in visible]
        if succ:
            names[k] = succ
    return names


def _last_used_skill(sid: str):
    """Most recent non-subagent `auto`/`manual` ledger event for this sid within the
    TTL (ADR-0020: sub-stamped rows are a different lane and must not steer the main
    session). Bounded 64KB tail read; newest-first scan; fail-open to None."""
    if not sid:
        return None
    try:
        with LEDGER.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 65536))
            tail = f.read().decode("utf-8", "replace")
        cutoff = time.time() - CHAIN_TTL_S
        for line in reversed(tail.splitlines()):
            line = line.strip()
            if not line or '"sid"' not in line:
                continue
            try:
                e = json.loads(line)
            except (ValueError, TypeError):
                e = None
            if not isinstance(e, dict):
                continue
            if e.get("sid") != sid or e.get("ev") not in ("auto", "manual") or e.get("sub"):
                continue
            if float(e.get("t", 0)) < cutoff:
                return None  # newest matching event is already stale; older is staler
            name = e.get("name")
            return name if isinstance(name, str) and name else None
        return None
    except (OSError, UnicodeError, ValueError, TypeError, AttributeError):
        return None


def _chain_hint_data(sid: str) -> list:
    """(seed, successors) the CHAIN-HINT line would name this turn, or [].
    Split out from the renderer so the offer event can log the SAME data the
    injected line carried (ADR-0041 L4: hint-continuation metric)."""
    if not CHAIN_HINT:
        return []
    seed = _last_used_skill(sid)
    if not seed:
        return []
    names_map = _visible_sidecar_names()
    succ = names_map.get(seed)
    if not isinstance(succ, list) or not succ:
        return []
    shown = [n for n in succ
             if isinstance(n, str) and n and n in names_map and n not in KEEPOFF]
    return [seed] + shown if shown else []


def _chain_hint(sid: str) -> str:
    """The CHAIN-HINT line for this turn, or ''. Wording deliberately avoids the
    audit's locked literals (`SKILL-CHECK:` and the `_AUTHORIZED_SIGNATURES`
    phrases) so a collision can never miscount dodges as authorized — parity-pinned
    by selftest (9)."""
    data = _chain_hint_data(sid)
    if not data:
        return ""
    return ("\nCHAIN-HINT: after " + data[0] + ", catalogue declares: "
            + ", ".join(data[1:]) + " — candidates, fit still required.")


# ── per-skill calibrated tau (Phase D wiring, default-INERT) ───────────────
# Wire eval/thresholds.json so an `ok`-calibrated skill gates on ITS OWN tau instead of the
# single global GETAWAY_FLOOR. DEFAULT OFF (ENFORCER_PER_SKILL_TAU unset) -> _PER_SKILL_TAU is
# empty -> _floor_for() returns the global floor -> behaviour byte-identical to today.
# WHY OFF BY DEFAULT (data, 2026-06-30): all 5 current `ok` skills calibrate to tau < 0.45 (one
# negative), so arming this LOWERS their bar and ADDS the false-offers ADR-0009 tuned against.
# On the compressed-cosine band the lever is index CONTENT (multi-vector), not thresholds —
# calibrate_thresholds.py says the same. Mechanism shipped + tested; arm only after a substrate
# change lifts separation. Opt in: export ENFORCER_PER_SKILL_TAU=1.  FAIL-OPEN on a bad file.
# The calibration artifact lives in the DURABLE HOME, not the plugin cache: every
# `/plugin update` mints a fresh cache dir, so a generated file kept under the plugin root
# silently dies with each release (observed 2026-08-24 — the 0.25.0 cache shipped without it,
# muting doctor's Corpus health row and every per-skill tau). Same class, same fix as the
# flywheel manifest (ADR-0027) and SKILL_TRIGGERS (0.21.1). Legacy cache-local copies are
# still honored as a read fallback so an un-migrated install keeps working.
_THRESHOLDS_DURABLE = Path.home() / ".claude" / "skill-concierge" / "thresholds.json"
_THRESHOLDS_LEGACY = Path(__file__).resolve().parents[2] / "eval" / "thresholds.json"
_env_thresholds = os.environ.get("SKILL_THRESHOLDS")
_THRESHOLDS_PATH = Path(_env_thresholds) if _env_thresholds else (
    _THRESHOLDS_DURABLE if _THRESHOLDS_DURABLE.exists() else _THRESHOLDS_LEGACY)


def _load_per_skill_tau() -> dict:
    if not os.environ.get("ENFORCER_PER_SKILL_TAU", "").strip():
        return {}  # default-inert
    try:
        data = json.loads(_THRESHOLDS_PATH.read_text(encoding="utf-8"))
        return {k: float(v["tau"]) for k, v in data.items()
                if v.get("status") == "ok" and isinstance(v.get("tau"), (int, float))}
    except (OSError, UnicodeError, ValueError, TypeError, AttributeError, KeyError):
        return {}  # fail-open: a bad thresholds file must never break a turn


_PER_SKILL_TAU = _load_per_skill_tau()


def _floor_for(name: str) -> float:
    """Getaway floor for a candidate: its calibrated per-skill tau when armed AND `ok`,
    else the global floor. Inert by default (_PER_SKILL_TAU empty)."""
    return _PER_SKILL_TAU.get(name, GETAWAY_FLOOR)


# ── deterministic route overrides (default-INERT) ──────────────────────────
# A tiny, high-precision exact-substring -> skill map for intents where semantic ranking is
# unreliable but the intent is unambiguous. GUARANTEES the mapped skill in the menu (prepended,
# deduped) — additive, never blocks, and a hit bypasses getaway + the actionability gate.
# DEFAULT OFF: loaded only when ENFORCER_DETERMINISTIC is set; missing/empty config -> no-op.
# CURATE SPARINGLY — this system's dodge is dominated by FALSE offers, so every route must be
# near-zero false-positive. config/deterministic-routes.json: {"routes":[{"contains":"<lower
# substring>","skill":"<exact name>"}]}.  Opt in: export ENFORCER_DETERMINISTIC=1.
_ROUTES_PATH = Path(os.environ.get(
    "SKILL_CONCIERGE_ROUTES",
    Path(__file__).resolve().parents[2] / "config" / "deterministic-routes.json"))


def _load_routes() -> list:
    if not os.environ.get("ENFORCER_DETERMINISTIC", "").strip():
        return []  # default-inert
    try:
        data = json.loads(_ROUTES_PATH.read_text(encoding="utf-8"))
        return [(r["contains"].lower(), r["skill"]) for r in data.get("routes", [])
                if isinstance(r.get("contains"), str) and isinstance(r.get("skill"), str)
                and r["contains"].strip()]
    except (OSError, UnicodeError, ValueError, TypeError, AttributeError, KeyError):
        return []  # fail-open


_ROUTES = _load_routes()


def _deterministic_hits(prompt: str, cands: list, keepoff: frozenset = frozenset()) -> list:
    """Skills whose exact-substring route matches the prompt but retrieval missed. Returns
    [(name, desc, score)] to PREPEND (score=1.0 so it leads + clears every floor). Order-
    preserving, de-duped against cands, and NEVER resurfaces a keep-off'd skill — ADR-0011
    suppression outranks a route, else a co-configured route silently bypasses it. Inert by
    default (_ROUTES empty)."""
    if not _ROUTES:
        return []
    low = prompt.lower()
    have = {n for (n, _d, _s) in cands}
    out = []
    for sub, skill in _ROUTES:
        if sub in low and skill not in have and skill not in keepoff:
            out.append((skill, "deterministic route", 1.0))
            have.add(skill)
    return out


# ── P6: runner-up-gap menu collapse (default-INERT) ──────────────────
# Collapse the menu to the top skill when it is clearly ahead of the runner-up by RAW-score
# gap (NOT %-share, which never concentrates: top-share maxes ~0.285 on the live ledger).
# Default OFF — no evidence collapsing improves conversion; gap>=1.25 fires only ~5%. Opt in
# by exporting ENFORCER_DOMINANCE_RATIO=<ratio>.
_DR = os.environ.get("ENFORCER_DOMINANCE_RATIO", "").strip()
try:
    DOMINANCE_RATIO = float(_DR) if _DR else None
except ValueError:
    DOMINANCE_RATIO = None  # fail-silent on a malformed opt-in value (hook contract)

# Per-turn GATE TRIGGER — the cheap re-assert. The full SKILL-FIRST standing order
# is injected once at SessionStart (doctrine.py); this keeps it live in attention
# every turn without re-paying the rich version. Pre-commitment, not persuasion: it
# forces a line-1 token and turns "the few don't fit" into an order to SEARCH, never
# a skip. In-generation only — no post-turn detection.
# (EFFORT was decoupled to the standalone effort-gate plugin in v0.4.0; this hook
# now governs which/whether a skill only.)
MANDATE = (
    "SKILL-FIRST · reply line 1 = USING <skill> | SEARCH <query> | SKIPPING none.\n"
    "Shown skills are a PREVIEW of ~500, not all. \"Few don't fit\" / \"I'm confident\" / "
    "\"you named a tool\" are NOT skips — run search_skills THIS reply before any SKIPPING (show the "
    "query). SKIPPING is lawful only on a no-task turn, or after a search finds nothing adaptable. "
    "USING never takes \"none\". [full order: session start]"
)


# Explicit skill-refusal pattern (Phase A / C3, verified 2026-06-28). mpnet cosine
# does NOT encode negation: an affirmed vs negated prompt embeds ~0.65-0.87 cosine,
# so a refusal like "do not use the <X> skill" still retrieves <X> at full score. A
# BROAD any-negation rule (the bm25 hook's approach) over-suppresses — bug-report
# prompts ("tests are not passing", "never finishes") carry a negation token yet
# genuinely need skills (3/4 wrongly suppressed in testing). So anchor on negation +
# an explicit INVOCATION-META verb (use/invoke/apply/call/rely-on/trigger/activate),
# NOT action verbs that recur in bug reports. High precision, low recall by design;
# a leaked offer is additive + low-blast (the agent reads the real prompt and won't
# act on a refused skill). Contract pinned in `--selftest`.
_REFUSAL_RE = re.compile(
    r"\b(?:do\s+not|do\s*n['\u2019]?t|don['\u2019]?t|never|please\s+do\s*n['\u2019]?t)\s+"
    r"(?:use|using|invoke|invoking|apply|applying|call|calling|trigger|activate|rely\s+on)\b"
    r"|\bwithout\s+(?:use|using|invoking|applying|calling)\b"
    r"|\bskip\s+\w+ing\b",
    re.IGNORECASE,
)


def _clean(s: str) -> str:
    return " ".join((s or "").split())


def _append_offer(sid: str, band: str, offered: list, fallback, q: str, dropped=None, embed_ms=None, qdrant_ms=None, ext=None, xh=None, n_intents=None, route=None, hint=None) -> None:
    """Append the offer event. Fail-silent: telemetry must never surface.
    ADR-0032: `ext` records the external annex names offered this turn (external offer→take
    is measured against the ADR-0031 get_skill takes); absent when no external annexed.
    ADR-0034: `xh` records the cross-harness annex the same way; absent when none annexed.
    ADR-0041: `n_intents` / `route` record the intent-cluster count and projected route
    rendered this turn (absent when 1 intent / no route) — the seed of the L4
    continuation-rate metric; additive keys, old analyzers ignore them.
    EPOCH NOTE: ADR-0034 changes what `offered` contains, so any offer-composition rate
    measured across the v0.25.0 boundary pools two different configs — window it."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        ev = {"t": round(time.time(), 3), "sid": sid, "ev": "offer",
              "band": band, "offered": offered, "fallback": fallback, "q": q[:120],
              "harness": RUNNING_HARNESS}
        if dropped:
            ev["dropped"] = dropped
        if ext:
            ev["ext"] = ext
        if xh:
            ev["xh"] = xh
        if n_intents and n_intents > 1:
            ev["n_intents"] = n_intents
        if route:
            ev["route"] = route
        if hint and len(hint) >= 2:
            ev["hint"] = hint    # ADR-0041 L4: [seed] + successors named by the CHAIN-HINT line
        if embed_ms is not None:
            ev["embed_ms"] = int(embed_ms)
        if qdrant_ms is not None:
            ev["qdrant_ms"] = int(qdrant_ms)
        with LEDGER.open("a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    except (OSError, UnicodeError, ValueError, TypeError, OverflowError):
        return


def _inject(text: str) -> None:
    sys.stdout.write(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": text,
        }
    }))


# Authorization lines for the two silent verdict legs (see AUTHORIZED_SKIP above). Burden of
# proof stays on SKIP: the getaway leg can't tell trivial from real-but-low-scoring, so it
# pushes ambiguous/real work back to find-skills rather than blessing the skip outright.
GETAWAY_SKIP_MSG = (
    AUTHORIZED_SKIP_MARKER + " full-catalogue retrieval ran (top {top:.2f} < floor {floor:.2f}); "
    "nothing cleared the floor. SKIPPING: none is pre-authorized ONLY if this turn is genuinely "
    "trivial/non-task — if it's real or ambiguous work, do NOT skip: escalate to find-skills "
    "instead (burden of proof is on SKIP). If a surfaced candidate's fit is unclear from its "
    "short description, call get_skill(<name>) first."
)
INTENT_SKIP_MSG = (
    AUTHORIZED_SKIP_MARKER + " the intent-margin classifier judged this turn conversational/"
    "non-task. SKIPPING: none is pre-authorized — no further search_skills needed."
)
# H5 (ADR-0019): the 3rd AUTHORIZED-SKIP leg. Its signature phrase "self-referential recap lane" is
# a LOCKED cross-file contract — the audit (audit_skill_usage.py `_is_authorized_skip_line` at :93, called :289) matches this exact
# substring to count the lane as an authorized-skip, NOT a false-skip. It is prose-unlikely and MUST
# NOT appear in the skill-first.md doctrine table, else a collision miscounts real dodges as authorized.
SELFREF_SKIP_MSG = (
    AUTHORIZED_SKIP_MARKER + " this turn only asks you to explain/rephrase your own "
    "immediately-prior message — the self-referential recap lane — with no external task, so no "
    "skill applies. SKIPPING: none is pre-authorized; no further search_skills needed."
)


def _authorized_skip_inject(kind: str, sid: str = "", **fmt) -> None:
    """Emit the AUTHORIZED-SKIP line for a silent verdict leg ("getaway" | "intent_skip" |
    "selfref") when the kill-switch is on; no-op when off. ADR-0029: the CHAIN-HINT line
    (when one is due) rides these legs too — the vague ≥4-word continuations hints exist
    for land HERE, not on the ranked mandate. Wrapped so a bad format kwarg or a
    stdout error can never escape — this hook is additive-only and must never block a turn."""
    if not AUTHORIZED_SKIP:
        return
    try:
        msg = {"getaway": GETAWAY_SKIP_MSG,
               "intent_skip": INTENT_SKIP_MSG,
               "selfref": SELFREF_SKIP_MSG}[kind]
        _inject(msg.format(**fmt) + _chain_hint(sid))
    except (OSError, UnicodeError, ValueError, KeyError):
        return


def _post_json(url: str, payload: dict, timeout: float) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _embed(text: str) -> list:
    """Embed via the warm shim under a HARD timeout. Raises on down/slow so the
    caller falls back to mandate-only."""
    return _post_json(EMBED_URL, {"text": text}, EMBED_TIMEOUT_S)["vector"]


def _retrieve(vector: list) -> list:
    """Top-k INSTALLED skills from Qdrant via raw REST (stdlib only), MAX-pooled: group_by name
    with one best point per skill (group_size=1). Returns [(name, desc, score)].

    ADR-0031 search-only tier: external catalog points (tier=external) are excluded from this
    query so the INSTALLED offer is exactly the top-k installed skills — byte-identical whether
    or not the ADR-0032 annex is enabled. The annex comes from a SEPARATE `_retrieve_external`
    call, so externals can NEVER displace an installed offer slot (the design's hard invariant).
    Two small queries beat one widened query, which would drop installed skills out of the limit
    window whenever externals ranked high in it.

    ADR-0034 cross-harness: rows the running harness cannot invoke are dropped HERE, per row,
    after over-fetching to RETRIEVE_LIMIT — never via a Qdrant `must_not scope`. Scope says
    where the indexed copy LIVES, not whether this harness can invoke it: when the same plugin
    is installed on both sides, dedup keeps one point and the Codex path can win the name, so a
    `codex-plugin` row may name a skill Claude invokes fine. `_invocable_twin` is the test a
    query-side filter cannot make. Trimmed back to TOP_K, so the offer's width is unchanged.
    ENFORCER_CROSS_HARNESS=0 issues the pre-ADR-0034 request byte-identically."""
    payload = ["name", "description", "scope"] if CROSS_HARNESS else ["name", "description"]
    res = _post_json(QUERY_GROUPS_URL,
                     {"query": vector, "group_by": "name",
                      "limit": RETRIEVE_LIMIT if CROSS_HARNESS else TOP_K,
                      "group_size": 1, "with_payload": payload,
                      "filter": {"must_not": [
                          {"key": "tier", "match": {"value": "external"}}]}},
                     QDRANT_TIMEOUT_S)
    out = []
    for g in res.get("result", {}).get("groups", []):
        hits = g.get("hits", [])
        if not hits:
            continue
        pl = hits[0].get("payload", {}) or {}
        name = pl.get("name", g.get("id", "?"))
        # INVOCABLE_PLUGIN_IDS is None means the manifest was unreadable, i.e. the twin test
        # cannot be made. Drop ONLY on positive knowledge — an unknown must filter nothing, or
        # an unreadable settings file silently reinstates the very mislabelling this replaced.
        if (CROSS_HARNESS and INVOCABLE_PLUGIN_IDS is not None
                and pl.get("scope") in FOREIGN_SCOPES and not _invocable_twin(name)):
            continue
        out.append((name, pl.get("description", ""), float(hits[0].get("score", 0.0))))
        if len(out) >= TOP_K:
            break
    return out


def _retrieve_external(vector: list, top_installed: float = 0.0) -> list:
    """ADR-0032 external annex: up to EXTERNAL_SLOTS catalog skills clearing the per-turn annex
    floor (`_annex_floor(EXTERNAL_FLOOR, top_installed)` — competitive with the installed top
    under ADR-0036, the plain pool floor when dynamic sizing is off), from a SEPARATE query
    filtered to tier=external. Returns [(name, desc, score, alias)]. A dedicated query (not a
    partition of a widened installed query) is what guarantees the installed offer is never
    displaced. Empty when the annex is off; the caller wraps this in a try/except so an
    external-query failure degrades to no-annex, never breaks the installed offer."""
    if not EXTERNAL_ANNEX:
        return []
    floor = _annex_floor(EXTERNAL_FLOOR, top_installed)
    res = _post_json(QUERY_GROUPS_URL,
                     {"query": vector, "group_by": "name", "limit": EXTERNAL_SLOTS,
                      "group_size": 1, "with_payload": ["name", "description", "scope"],
                      "filter": {"must": [
                          {"key": "tier", "match": {"value": "external"}}]}},
                     QDRANT_TIMEOUT_S)
    out = []
    for g in res.get("result", {}).get("groups", []):
        hits = g.get("hits", [])
        if not hits:
            continue
        score = float(hits[0].get("score", 0.0))
        if score < floor:
            continue
        pl = hits[0].get("payload", {}) or {}
        alias = str(pl.get("scope") or "").split(":", 1)[1] if ":" in str(pl.get("scope") or "") else "?"
        out.append((pl.get("name", g.get("id", "?")), pl.get("description", ""), score, alias))
    return out


def _retrieve_foreign(vector: list, top_installed: float = 0.0) -> list:
    """ADR-0034 cross-harness annex: the top skills in the OTHER harness's scopes scoring
    >= FOREIGN_FLOOR, from a SEPARATE query. Returns [(name, desc, score)].

    Same hard invariant as the ADR-0032 external annex: a dedicated query, never a partition of
    a widened installed query, so a foreign skill can NEVER displace an installed offer slot.
    The floor is deliberately the external floor's height (0.40) rather than ITEM_FLOOR (0.18)
    — a row the agent cannot invoke earns its place only on strong intent-match.

    An invocable twin is skipped: it is already IN the installed offer, and repeating it here
    under "NOT invocable" would state the opposite of the truth. Over-fetches for the same
    reason `_retrieve` does, so a skipped twin does not cost a real annex slot. Empty when the
    mechanism is off; the caller wraps this so a failed query degrades to no-annex.

    ADR-0036: the per-turn floor is `_annex_floor(FOREIGN_FLOOR, top_installed)` — same
    competitive-margin rule as the external annex, one mechanism for both."""
    if not CROSS_HARNESS:
        return []
    floor = _annex_floor(FOREIGN_FLOOR, top_installed)
    res = _post_json(QUERY_GROUPS_URL,
                     {"query": vector, "group_by": "name", "limit": FOREIGN_SLOTS * 3,
                      "group_size": 1, "with_payload": ["name", "description"],
                      "filter": {"must": [
                          {"key": "scope", "match": {"any": list(FOREIGN_SCOPES)}}]}},
                     QDRANT_TIMEOUT_S)
    out = []
    for g in res.get("result", {}).get("groups", []):
        hits = g.get("hits", [])
        if not hits:
            continue
        score = float(hits[0].get("score", 0.0))
        if score < floor:
            continue
        pl = hits[0].get("payload", {}) or {}
        name = pl.get("name", g.get("id", "?"))
        if _invocable_twin(name):
            continue
        out.append((name, pl.get("description", ""), score))
        if len(out) >= FOREIGN_SLOTS:
            break
    return out


def _apply_dominance(cands: list) -> list:
    """P6 (default-inert): collapse to the top skill when it is clearly ahead of the runner-up by
    RAW-score gap. Decided HERE (not in _ranked_mandate) so the CALLER logs the post-collapse menu —
    agent and ledger see the same set. Off unless ENFORCER_DOMINANCE_RATIO is set."""
    if (DOMINANCE_RATIO and len(cands) >= 2 and cands[1][2] > 0
            and cands[0][2] / cands[1][2] >= DOMINANCE_RATIO):
        return [cands[0]]
    return cands


def _blurb(desc: str) -> str:
    b = _clean(desc)
    return b[:_DESC_CHARS].rsplit(" ", 1)[0] + "…" if len(b) > _DESC_CHARS else b


# ── ADR-0041: multi-intent offer shaping + route projection ─────────────────
# Two upgrades to the OFFER itself (ADR-0040 fed the chain data; these use it at
# turn zero instead of only after a skill fires):
#   • INTENT CLUSTERING — deterministic, zero-network, post-processing of the already-
#     fetched candidates. A prompt carrying "research it, build it, ship it" blends one
#     embedding; the top-8 then mixes three intents and the secondary intents starve.
#     Greedy lexical clustering (Jaccard on name+description tokens) detects >=2
#     DISTINCT intent groups; the render leads with each cluster's best candidate.
#   • ROUTE PROJECTION — when the top candidate has successors in the merged chain map
#     (ADR-0030 overrides > ADR-0029 declared > ADR-0040 mined), one bounded line shows
#     the typical continuation route (max 4 nodes, cycle-safe) BEFORE anything is used.
# Both are context-only: no gate, no floor, no slot displacement — the candidate SET and
# its scores are untouched; only ordering emphasis and advisory text change. The locked
# header/footer literals are byte-identical (audit parity), and single-intent turns with
# no route render byte-identically to pre-0041.
MULTI_INTENT = os.environ.get("ENFORCER_MULTI_INTENT", "1") != "0"
CHAIN_PROJECTION = os.environ.get("ENFORCER_CHAIN_PROJECTION", "1") != "0"
INTENT_MERGE_J = float(os.environ.get("ENFORCER_INTENT_MERGE_J", "0.30"))   # overlap-coefficient threshold (see _intent_clusters)
INTENT2_RATIO = float(os.environ.get("ENFORCER_INTENT2_RATIO", "0.75"))
MAX_INTENTS = int(os.environ.get("ENFORCER_MAX_INTENTS", "3"))   # >3 "intents" is a clustering miss, not a task shape
_ROUTE_MAX = 4

# Domain-generic tokens present in nearly every skill description — dropping them is
# what makes lexical overlap track INTENT (deploy/diagnose/document…) rather than
# shared boilerplate (skill/code/task/agent…).
_INTENT_STOP = frozenset(
    "the a an and or for to of in on with this that use using when your you it is are be "
    "by from as at into not but also its their them new create make build work works "
    "working code task tasks skill skills agent agents claude user users help helps need "
    "needs best better via per all any can will should must does done like about more "
    "most other others before after then than so if no yes one two how what which".split())


# Domain synonym families (fold AFTER singularization, BEFORE clustering). Live smoke
# 2026-08-28 exposed why lexical-only fails: same-family skills share no surface tokens
# — "verify/validate/check/smoke", "fix/debug/repair", "bug/error/failure" — so a
# single-intent "fix the failing test" turn split into 7 fake intents. Folding these
# families makes overlap track intent, not vocabulary choice. Conservative and
# inspectable; grows only with observed mis-splits.
_INTENT_FOLD = {}
for _fam in (
    ("verify", "validate", "check", "confirm", "audit", "smoke", "prove", "vet"),
    ("test", "coverage", "qa", "e2e", "regression"),
    ("fix", "debug", "diagnose", "repair", "troubleshoot"),
    ("bug", "defect", "error", "failure", "failing", "broken", "crash"),
    ("research", "investigate", "study", "evaluate", "analyze"),
    ("document", "docs", "documentation", "readme"),
    ("plan", "roadmap", "phase", "milestone", "scope"),
    ("deploy", "ship", "release", "publish", "launch"),
):
    for _w in _fam[1:]:
        _INTENT_FOLD[_w] = _fam[0]


def _intent_tokens(name: str, desc: str) -> frozenset:
    # Naive singularization (drop a trailing 's' on >=4-char tokens, guard 'ss') so
    # report/reports and suite/suites count as overlap — without it, plural siblings
    # of ONE intent split into fake separate intents. Consistent on both sides, so
    # imperfect stems (analysis) only ever merge with themselves.
    toks = set()
    for t in re.findall(r"[a-z0-9]+", f"{name} {desc}".lower()):
        if len(t) < 2 or t in _INTENT_STOP:
            continue
        if len(t) >= 4 and t.endswith("s") and not t.endswith("ss"):
            t = t[:-1]
        toks.add(_INTENT_FOLD.get(t, t))
    return frozenset(toks)


def _intent_clusters(cands: list) -> list:
    """Greedy lexical clustering of the shown candidates, best-score-first.

    Each candidate joins the first cluster whose token union overlaps it by Jaccard
    >= INTENT_MERGE_J; otherwise it opens a new cluster. Deterministic and pure —
    same input, same clusters, no network, O(n * k) on <= TOP_K candidates. Cluster
    leads are simply each cluster's first (highest-scoring) member; intra-cluster
    score order is preserved.
    """
    # OVERLAP coefficient (inter / min(|a|,|b|)), not Jaccard: sibling skills share
    # intent vocabulary but carry long, skill-specific tails (playwright/vitest/k6 vs
    # execution/analysis/report), and Jaccard punishes that breadth — a same-family
    # pair at inter=3, |a|=11, |b|=8 scores 3/16 = 0.19 (split) on Jaccard but
    # 3/8 = 0.38 (merge) on overlap. Disjoint intents stay 0 on either metric.
    clusters, unions = [], []
    for name, desc, _score in cands:
        toks = _intent_tokens(name, desc)
        placed = False
        for i, u in enumerate(unions):
            inter = len(toks & u)
            if inter and inter / min(len(toks), len(u)) >= INTENT_MERGE_J:
                clusters[i].append((name, desc, _score))
                unions[i] = u | toks
                placed = True
                break
        if not placed:
            clusters.append([(name, desc, _score)])
            unions.append(set(toks))
    return clusters


def _qualifying_intents(clusters: list) -> list:
    """Clusters allowed to be ANNOUNCED as intents. The top's own cluster always
    qualifies; every further cluster needs >= 2 candidates — a single stray
    lexically-disjoint row (ego-browser on a test-family retrieval, design-system on
    a planning retrieval) is retrieval breadth, not evidence of an intent. Cluster
    order (by lead score) is preserved."""
    return clusters[:1] + [c for c in clusters[1:] if len(c) >= 2]


def _multi_intent_gate(clusters: list) -> bool:
    """>=2 QUALIFYING clusters AND the second intent's lead is not a weak neighbour:
    its score must be >= INTENT2_RATIO of the first lead's. Without the strength gate,
    a lexically odd but low-scoring sibling would split a single-intent turn into
    fake 'intents'."""
    qual = _qualifying_intents(clusters)
    if len(qual) < 2:
        return False
    top = qual[0][0][2]
    return top > 0 and qual[1][0][2] >= INTENT2_RATIO * top


def _route_of(seed: str, names_map: dict | None = None, max_nodes: int = _ROUTE_MAX) -> list:
    """Bounded continuation walk from `seed` through the merged chain map: strongest
    successor per hop, cycle-safe (visited set), capped at max_nodes, successors must
    be live map keys (the same catalogue-membership rule _chain_hint filters by).
    Returns [] when seed has no successors — a route of one node is not a route."""
    if not CHAIN_PROJECTION or not seed:
        return []
    names_map = names_map if names_map is not None else _visible_sidecar_names()
    route, seen = [seed], {seed}
    cur = seed
    while len(route) < max_nodes:
        succ = names_map.get(cur)
        if not isinstance(succ, list):
            break
        nxt = next((s for s in succ
                    if isinstance(s, str) and s and s not in seen and s in names_map), None)
        if not nxt:
            break
        route.append(nxt)
        seen.add(nxt)
        cur = nxt
    return route if len(route) >= 2 else []


def _ranked_mandate(cands: list, annex: list | None = None, foreign: list | None = None) -> str:
    # %-SHARE is RELATIVE rank among the shown few, NOT absolute confidence — raw mpnet cosines
    # (~0.18-0.40) read as noise; share disambiguates WHICH fits. Shown only with 2+ candidates
    # (a lone candidate is always 100% → meaningless). Raw scores still logged to the ledger.
    # ADR-0032: `annex` (external catalog skills) renders as a SEPARATE block below the installed
    # offer — they never share the %-share pool (the installed ranking is untouched) and carry
    # the get_skill consumption instruction, since they are not Skill-tool-invocable.
    # ADR-0034: `foreign` (other-harness plugin skills) renders as its own third block for the
    # same reason and with the same consumption path — installed on the sibling harness, indexed
    # here, but not invocable here. Kept distinct from the external block so provenance stays
    # legible: "on disk under the other harness" is not "in a search-only catalog".
    total = sum(s for (_n, _d, s) in cands) or 1.0
    multi = len(cands) > 1
    # ADR-0041 multi-intent: cluster the SHOWN set; when >=2 clusters clear the strength
    # gate, reorder leads-first and say so. Single-intent turns take the same list in the
    # same order (clusters preserve score order), rendering byte-identically.
    ordered = list(cands)
    n_intents = 1
    if MULTI_INTENT and multi:
        _clusters = _qualifying_intents(_intent_clusters(cands))
        if _multi_intent_gate(_intent_clusters(cands)):
            # ADR-0041 amendment (0.32.1): a task with >3 genuinely distinct intents
            # is vanishingly rare — beyond the cap, extra clusters are a clustering
            # miss and fold back in as supporting rows, not announced intents.
            _extras = []
            if len(_clusters) > MAX_INTENTS:
                _ranked = sorted(_clusters, key=lambda c: -c[0][2])
                _clusters = _ranked[:MAX_INTENTS]
                _extras = [m for c in _ranked[MAX_INTENTS:] for m in c]
                n_intents = MAX_INTENTS
            else:
                n_intents = len(_clusters)
            # leads-first: rows 1..N name the N primaries (one per intent), then the
            # supporting rows grouped behind their lead — the "first N rows" the note
            # promises. Intra-cluster score order preserved within each group.
            ordered = ([c[0] for c in _clusters]
                       + [m for c in _clusters for m in c[1:]] + _extras)
    lines = [f"  • {name}{(f' ({round(score / total * 100)}%)' if multi else '')} — {_blurb(desc)}"
             for name, desc, score in ordered]
    if multi and n_intents > 1:
        note = (f"\nReads as {n_intents} distinct intents — the first {n_intents} rows are the "
                "strongest fit per intent; run them in the order the task needs, one USING per "
                "intent at its moment. Shares are RELATIVE rank among these few (all above the "
                "noise floor), not confidence.")
    else:
        note = ("\nShares are RELATIVE rank among these few (all above the noise floor), not confidence — "
                "pick the one matching the intent.") if multi else ""
    # ADR-0041 route projection: the whole-route line at turn zero, from the merged
    # chain map (ADR-0030 overrides > declared > ADR-0040 mined). Advisory only —
    # wording stays clear of the audit's locked literals (parity with CHAIN-HINT).
    route_line = ""
    if cands:
        _route = _route_of(cands[0][0])
        if _route:
            route_line = ("\nROUTE: if " + _route[0] + " fits, the catalogue's typical "
                          "continuation is " + " -> ".join(_route)
                          + " (projection, fit still required).")
    annex_block = ""
    if annex:
        alines = [f"  • {name} [external:{alias}] — {_blurb(desc)}"
                  for (name, desc, _s, alias) in annex]
        annex_block = (
            "\nExternal catalog matches (NOT installed — consume with get_skill, do not use the "
            "Skill tool):\n" + "\n".join(alines) +
            "\nTo use one: `USING: <name>` then get_skill(\"<name>\") and follow its SKILL.md inline.")
    foreign_block = ""
    if foreign:
        flines = [f"  • {name} [{FOREIGN_HARNESS}] — {_blurb(desc)}"
                  for (name, desc, _s) in foreign]
        foreign_block = (
            f"\nOther-harness matches (installed under {FOREIGN_HARNESS.capitalize()}, NOT "
            "invocable here — consume with get_skill, do not use the Skill tool):\n"
            + "\n".join(flines) +
            "\nTo use one: `USING: <name>` then get_skill(\"<name>\") and follow its SKILL.md inline.")
    return (
        "SKILL-FIRST · reply line 1 = USING <skill> | SEARCH <query> | SKIPPING none.\n"
        "Preview for this task (NOT the full ~500 shelf):\n"
        + "\n".join(lines) + note + route_line + annex_block + foreign_block + "\n"
        "None fit → run search_skills THIS reply before any SKIPPING; show the query. "
        "A loosely-adaptable fit is a USING. [full order: session start]"
    )


def _is_imperative(prompt: str) -> bool:
    """Veto signal for the actionability gate: does the prompt OPEN with a task verb
    (after skipping leading fillers and 'can you'-style openers)? Imperative turns are
    NEVER suppressed — they are the actionable turns the gate must protect, since a
    false-suppressed offer is the costly error. High precision on the open, low recall by
    design (most real tasks don't open with a clean verb — the kNN catches those)."""
    toks = re.findall(r"[^\W\d_]+(?:'[^\W\d_]+)*", unicodedata.normalize("NFC", prompt).lower())
    i = 0
    skips = {("can", "you"), ("could", "you"), ("would", "you"), ("i", "want"), ("i", "need"),
             ("làm", "ơn"), ("vui", "lòng")}
    while i < len(toks):
        if toks[i] in _FILLER:
            i += 1
            continue
        if i + 1 < len(toks) and (toks[i], toks[i + 1]) in skips:
            i += 2
            continue
        break
    if i >= len(toks):
        return False
    if toks[i] in _IMPERATIVE_VERBS or toks[i] in _VN_VERBS:
        return True
    return i + 1 < len(toks) and (toks[i], toks[i + 1]) in _VN_VERB_BIGRAMS


def _is_selfref(prompt: str) -> bool:
    """H5 over-fire lane. True ONLY for a narrow class: a user prompt whose WHOLE payload is a
    request to explain/rephrase the assistant's own immediately-prior message, with NO external
    task. Three gates, all required:
      (1) opens with a recap verb on a 2nd-person / deictic object (_SELFREF_RE);
      (2) whole-prompt task-verb veto — ANY _IMPERATIVE_VERBS ∪ _VN_VERBS token (or VN bigram)
          ANYWHERE → not selfref. This is the Red-Team F1 fix: _is_imperative checks only the
          LEADING token, so "explain your answer and implement X" would slip a lead-token check;
          scanning every token vetoes it.
      (3) no new-clause connector introducing an external object (_SELFREF_TAIL_RE).
    Fails toward NOT firing (→ normal routing): a missed selfref costs only a harmless forced
    search, while a false-fire would bless real work — the exact dodge the doctrine fights."""
    norm = unicodedata.normalize("NFC", prompt or "").strip()
    if not _SELFREF_RE.match(norm):
        return False
    low = norm.lower()
    toks = re.findall(r"[^\W\d_]+(?:'[^\W\d_]+)*", low)
    if any(t in _IMPERATIVE_VERBS or t in _VN_VERBS for t in toks):
        return False
    if any((toks[i], toks[i + 1]) in _VN_VERB_BIGRAMS for i in range(len(toks) - 1)):
        return False
    return not _SELFREF_TAIL_RE.search(low)


def _intent_conversational(vector: list) -> bool:
    """Prior-independent actionability gate: True only when the prompt sits closer to
    CONVERSATIONAL space than ACTIONABLE space by a margin. Two label-filtered kNN queries
    over prompt_intent; mean cosine of the top-INTENT_K per class; suppress iff
    (conv_mean - act_mean) > INTENT_MARGIN. Reuses the embedding the enforcer already
    computed. Fail-OPEN: missing collection / empty class / any error -> False (offer)."""
    def _class_sim(label):
        res = _post_json(INTENT_QUERY_URL,
                         {"query": vector,
                          "filter": {"must": [{"key": "label", "match": {"value": label}}]},
                          "limit": INTENT_K},
                         QDRANT_TIMEOUT_S)
        pts = res.get("result", {}).get("points", []) or []
        return (sum(float(p.get("score", 0.0)) for p in pts) / len(pts)) if pts else None
    try:
        conv_sim = _class_sim("conversational")
        act_sim = _class_sim("actionable")
        if conv_sim is None or act_sim is None:
            return False
        return (conv_sim - act_sim) > INTENT_MARGIN
    except (OSError, UnicodeError, ValueError, TypeError, AttributeError, KeyError):
        return False


def main() -> int:
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
        if not isinstance(data, dict):
            return 0
        prompt = (data.get("prompt") or "").strip()
        sid = data.get("session_id", "")

        # Cheap pre-gate (no I/O): empty, explicit slash-command (user already
        # chose a route), or an ultra-short acknowledgement. These never embed.
        if not prompt or prompt.startswith("/"):
            return 0
        if _word_count(prompt) <= MAX_SHORT_WORDS:
            return 0

        # Explicit skill-refusal -> MANDATE-ONLY (never surface the skill the user
        # just refused; keep the SKILL-FIRST discipline live). See _REFUSAL_RE.
        if _REFUSAL_RE.search(prompt):
            _inject(MANDATE)
            _append_offer(sid, "negation", [], "skill_refusal", prompt)
            return 0

        # H5 over-fire lane (no I/O): a purely self-referential recap of the agent's OWN prior
        # message needs no skill — authorize the skip instead of forcing a pointless search. Narrow
        # by construction (see _is_selfref); any task tail falls through to normal routing below.
        if SELFREF_SKIP and _is_selfref(prompt):
            _append_offer(sid, "selfref_skip", [], "self_referential", prompt)
            _authorized_skip_inject("selfref", sid)
            return 0

        # Embed (HARD timeout, EMBED_TIMEOUT_S) → mandate-only on down/slow.
        embed_ms = None
        t0 = time.time()
        try:
            vector = _embed(prompt)
            embed_ms = (time.time() - t0) * 1000
        except TimeoutError:
            embed_ms = (time.time() - t0) * 1000
            _inject(MANDATE + _chain_hint(sid))
            _append_offer(sid, "fallback", [], "embed_timeout", prompt, embed_ms=embed_ms)
            return 0
        except (OSError, UnicodeError, ValueError, TypeError, AttributeError, KeyError):
            embed_ms = (time.time() - t0) * 1000
            _inject(MANDATE + _chain_hint(sid))
            _append_offer(sid, "fallback", [], "embed_down", prompt, embed_ms=embed_ms)
            return 0
        # Retrieve → mandate-only fallback if Qdrant is unreachable.
        qdrant_ms = None
        t1 = time.time()
        try:
            cands = _retrieve(vector)
            qdrant_ms = (time.time() - t1) * 1000
        except (OSError, UnicodeError, ValueError, TypeError, AttributeError, KeyError, IndexError):
            qdrant_ms = (time.time() - t1) * 1000
            _inject(MANDATE + _chain_hint(sid))
            _append_offer(sid, "fallback", [], "qdrant_down", prompt, embed_ms=embed_ms, qdrant_ms=qdrant_ms)
            return 0
        # P5 (ADR-0011): hard-drop chronic never-take skills BEFORE floors/gate/rank, so they
        # vanish from the menu and from P6's collapse set. Fail-open (KEEPOFF empty -> no-op).
        cands, _dropped = _drop_keepoff(cands, KEEPOFF)

        # Deterministic routes (default-inert): guarantee an unambiguously-intended skill in
        # the menu even when semantic ranking missed it. A hit leads (score 1.0) and bypasses
        # both the getaway and the actionability gate (the intent is explicit).
        det = _deterministic_hits(prompt, cands, KEEPOFF)
        if det:
            cands = det + cands

        top = cands[0][2] if cands else 0.0
        offered = [[n, round(s, 4)] for (n, _d, s) in cands]

        # Getaway: top candidate below its floor (per-skill tau when armed+`ok`, else the
        # global floor). A deterministic hit always clears — it IS the intent.
        floor = _floor_for(cands[0][0]) if cands else GETAWAY_FLOOR
        if not det and top < floor:
            # No semantic fit → trivial/out-of-catalogue. Log the consideration so
            # coverage/fallback stats stay honest, then authorize the skip (or stay fully
            # silent if the kill-switch is off) instead of leaving the agent to re-derive
            # this verdict via a fresh search_skills call.
            _append_offer(sid, "getaway", offered, None, prompt, dropped=_dropped or None, embed_ms=embed_ms, qdrant_ms=qdrant_ms)
            _authorized_skip_inject("getaway", sid, top=top, floor=floor)
            return 0

        # Actionability gate (prior-independent class-margin). A relevant skill cleared the
        # floor — but if this is a NON-imperative turn that leans conversational over
        # actionable, the offer is noise the agent reliably dodges. Suppress it. Fail toward
        # offering (imperative OR any error -> offer). Backtest ~2% false-suppression; fires on novel input.
        if not det and not _is_imperative(prompt) and _intent_conversational(vector):
            _append_offer(sid, "intent_skip", offered, "conversational", prompt, dropped=_dropped or None, embed_ms=embed_ms, qdrant_ms=qdrant_ms)
            _authorized_skip_inject("intent_skip", sid)
            return 0

        # Annex queries, issued ONLY once the turn is known to carry an offer.
        #
        # Both are SEPARATE queries so `cands` (installed) and the whole pipeline above
        # (keepoff, deterministic, getaway, intent gate, ITEM_FLOOR, dominance) run
        # byte-identical — an annex can never touch the installed ranking or displace a slot.
        # ADR-0032 supplies the external-catalog annex, ADR-0034 the cross-harness one; each is
        # best-effort, so a failed annex query degrades to no-annex and never breaks the offer.
        #
        # POSITION IS LOAD-BEARING. They sit AFTER the getaway and actionability gates, not
        # before: an annex rides only this path, so a suppressed turn that issued them paid two
        # Qdrant round-trips for a result it then discarded. With ADR-0034 adding a third
        # round-trip that waste doubled, and the enforcer runs inside a hard per-turn budget.
        # Same rendered output, strictly less work on every suppressed turn.
        # (A strong annex hit on an installed-getaway turn still injects nothing — no installed
        # offer to append to. That remains the deliberate ADR-0032 scope, unchanged here.)
        _atop = cands[0][2] if cands else 0.0   # post-keepoff/deterministic installed top
        try:
            _external = _retrieve_external(vector, _atop)
        except (OSError, UnicodeError, ValueError, TypeError, AttributeError, KeyError, IndexError):
            _external = []
        try:
            _foreign = _retrieve_foreign(vector, _atop)
        except (OSError, UnicodeError, ValueError, TypeError, AttributeError, KeyError, IndexError):
            _foreign = []

        shown = [(n, d, s) for (n, d, s) in cands if s >= ITEM_FLOOR] or cands[:1]
        shown = _apply_dominance(shown)   # P6 collapse decided once: agent + ledger see the same set
        _inject(_ranked_mandate(shown, annex=_external, foreign=_foreign) + _chain_hint(sid))
        # ADR-0041 telemetry — computed from the same pure helpers the renderer used, so
        # the ledger row and the injected text can never disagree.
        _ni = 1
        if MULTI_INTENT and len(shown) > 1:
            _cls = _qualifying_intents(_intent_clusters(shown))
            if _multi_intent_gate(_intent_clusters(shown)):
                _ni = min(len(_cls), MAX_INTENTS)   # same qualification + cap the renderer applies
        _append_offer(sid, "offer",
                      [[n, round(s, 4)] for (n, _d, s) in shown], None, prompt,
                      dropped=_dropped or None, embed_ms=embed_ms, qdrant_ms=qdrant_ms,
                      ext=[[n, round(s, 4)] for (n, _d, s, _a) in _external] or None,
                      xh=[[n, round(s, 4)] for (n, _d, s) in _foreign] or None,
                      n_intents=_ni, route=_route_of(shown[0][0]) if shown else None,
                      hint=_chain_hint_data(sid))
    except (OSError, UnicodeError, ValueError, TypeError, AttributeError, KeyError, IndexError,
            OverflowError):
        return 0  # fail-silent, never block
    return 0


def _selftest() -> int:
    """Pin two contracts: (1) the refusal guard fires on explicit skill-refusal and
    stays silent on affirmations + bug-report negations; (2) _ranked_mandate renders
    %-share + a disambiguation note for 2+ candidates, and neither for a lone one.
    Run: python3 enforcer.py --selftest"""
    must_fire = [
        "do not use the <skill> here",
        "please don't invoke that skill",
        "without using the test skill, just patch it",
        "skip reviewing this file",
        "never apply the formatter",
    ]
    must_not_fire = [
        "use the test skill to check this",                # affirmation
        "fix the bug where login does not work",           # bug report
        "the tests are not passing, help me debug",        # bug report
        "this deploy never finishes, investigate why",     # bug report
        "this function does not return the right value",   # bug report
        "ship this application to production",             # affirmation
    ]
    bad = []
    for t in must_fire:
        if not _REFUSAL_RE.search(t):
            bad.append("MISS (should fire): " + repr(t))
    for t in must_not_fire:
        if _REFUSAL_RE.search(t):
            bad.append("FALSE-FIRE (should stay silent): " + repr(t))
    # (1b) MAX_SHORT_WORDS counting is CJK-aware: a no-space script must not
    # collapse to one "word" (the 2026-08-25 live miss), English unchanged.
    if _word_count("帮我分析中医体质数据") <= MAX_SHORT_WORDS:
        bad.append("word_count: CJK task prompt collapsed to <=3 words (pre-gate swallow)")
    if _word_count("帮我 analyze 这个 bug today") != 5:
        bad.append("word_count: mixed CJK+English count wrong")
    if _word_count("ok 好") > MAX_SHORT_WORDS:
        bad.append("word_count: genuinely-short mixed prompt must stay <=3")
    for t in ("fix the typo", "run tests now", "one two three"):
        if _word_count(t) != len(t.split()):
            bad.append("word_count: pure-English count changed: " + repr(t))
    # (2) ranked-mandate %-share + disambiguation note
    multi = _ranked_mandate([("alpha", "desc alpha", 0.30), ("beta", "desc beta", 0.10)])
    if "(75%)" not in multi or "(25%)" not in multi:
        bad.append("ranked_mandate: expected 75%/25% shares")
    if "RELATIVE rank" not in multi:
        bad.append("ranked_mandate: missing relative-rank note for 2+ candidates")
    lone = _ranked_mandate([("alpha", "desc alpha", 0.25)])
    if "%" in lone or "RELATIVE rank" in lone:
        bad.append("ranked_mandate: lone candidate must show no share and no note")
    if "• alpha — desc alpha" not in lone:
        bad.append("ranked_mandate: lone candidate line malformed")

    # (3) actionability gate — the imperative VETO fires on task-verb openers and stays
    # off for conversational/question/approval turns (the gate suppresses ONLY non-imperatives).
    # NOTE: production main() drops prompts with <= MAX_SHORT_WORDS (3) words BEFORE _is_imperative
    # runs, so the veto only matters for >5-word prompts. The >5-word VN cases below represent that
    # production-reachable population; the <=5-word cases pin the function's correctness directly.
    imp_fire = ["fix the typo on line 12", "now, write the handoff", "please run the tests",
                "can you refactor this", "delete the cloned copy", "integrate the EFFORT gate",
                "let's run the tests",
                "sửa lỗi ở dòng 12", "hãy viết báo cáo", "chạy test giúp mình",
                "kiểm tra file này", "cài đặt thư viện", "phân tích log lỗi",
                "làm ơn dịch đoạn này", "tối ưu hàm này",
                "hãy sửa giúp mình cái lỗi đăng nhập ở trang chủ",
                "phân tích các log lỗi trong thư mục build hôm nay"]
    imp_off = ["how's the documentation status?", "good direction we're heading",
               "what does this function do", "i think we should reconsider",
               "thanks that worked", "yes please",
               "tài liệu thế nào rồi", "hàm này làm gì vậy",
               "mình nghĩ nên xem lại", "cảm ơn nhé",
               "cái hàm xử lý đăng nhập này hoạt động như thế nào vậy",
               "theo bạn thì mình có nên viết lại phần này không"]
    for t in imp_fire:
        if not _is_imperative(t):
            bad.append("imperative MISS (should fire): " + repr(t))
    for t in imp_off:
        if _is_imperative(t):
            bad.append("imperative FALSE-FIRE (should stay off): " + repr(t))

    # (4) keep-off hard-drop: listed names removed, order preserved, fail-open on empty set.
    surv, drp = _drop_keepoff([("a", "", 0.3), ("bad", "", 0.2), ("c", "", 0.1)], frozenset({"bad"}))
    if [n for n, _, _ in surv] != ["a", "c"] or drp != ["bad"]:
        bad.append(f"keepoff drop wrong: survivors={[n for n, _, _ in surv]} dropped={drp}")
    s2, d2 = _drop_keepoff([("a", "", 0.3)], frozenset())
    if [n for n, _, _ in s2] != ["a"] or d2 != []:
        bad.append("keepoff empty-set must pass everything through")

    # (5) P6 gap-collapse: decided in _apply_dominance (so the CALLER logs the post-collapse menu),
    # default-inert. Plus a collapsed input must render as a lone candidate (no %-share, no note).
    global DOMINANCE_RATIO
    _saved = DOMINANCE_RATIO
    try:
        DOMINANCE_RATIO = 1.25
        if _apply_dominance([("a", "da", 0.30), ("b", "db", 0.20)]) != [("a", "da", 0.30)]:
            bad.append("dominance: should collapse to top when gap >= ratio")
        if len(_apply_dominance([("a", "da", 0.30), ("b", "db", 0.28)])) != 2:
            bad.append("dominance: should NOT collapse a flat menu (gap < ratio)")
        DOMINANCE_RATIO = None
        if len(_apply_dominance([("a", "da", 0.30), ("b", "db", 0.20)])) != 2:
            bad.append("dominance: default-inert must not collapse")
    finally:
        DOMINANCE_RATIO = _saved
    lone_collapsed = _ranked_mandate([("a", "da", 0.30)])
    if "%" in lone_collapsed or "RELATIVE rank" in lone_collapsed:
        bad.append("collapsed render must be lone (no %-share / note)")

    # (6) per-skill tau + deterministic routes — BOTH default-INERT (no env set in this test).
    global _PER_SKILL_TAU, _ROUTES
    if _PER_SKILL_TAU != {}:
        bad.append("per-skill tau must be empty/inert by default (ENFORCER_PER_SKILL_TAU unset)")
    if _ROUTES != []:
        bad.append("deterministic routes must be empty/inert by default (ENFORCER_DETERMINISTIC unset)")
    if _floor_for("whatever") != GETAWAY_FLOOR:
        bad.append("floor_for must return the global floor when inert")
    _saved_tau, _saved_routes = _PER_SKILL_TAU, _ROUTES
    try:
        _PER_SKILL_TAU = {"vn-author": 0.30}
        if _floor_for("vn-author") != 0.30:
            bad.append("floor_for must use per-skill tau for an armed `ok` skill")
        if _floor_for("uncalibrated") != GETAWAY_FLOOR:
            bad.append("floor_for must fall back to the global floor for an uncalibrated skill")
        _ROUTES = [("open a pull request", "ck:git")]
        hit = [n for n, _d, _s in _deterministic_hits("please open a pull request now", [("o", "", 0.3)])]
        if hit != ["ck:git"]:
            bad.append(f"deterministic route must fire on a substring match: {hit}")
        if _deterministic_hits("an unrelated prompt", [("o", "", 0.3)]) != []:
            bad.append("deterministic route must not fire without a match")
        if _deterministic_hits("open a pull request", [("ck:git", "", 0.3)]) != []:
            bad.append("deterministic route must not duplicate an already-present skill")
    finally:
        _PER_SKILL_TAU, _ROUTES = _saved_tau, _saved_routes

    # (6b) keep-off must survive a co-configured deterministic route (ADR-0011): a route
    # pointing at a keep-off'd skill must NOT resurface it at score 1.0 (which would bypass
    # both the getaway and actionability gates). Reproduces the drop-then-route interaction.
    _saved_routes2 = _ROUTES
    try:
        _ROUTES = [("deploy the app", "chronic")]
        keepoff = frozenset({"chronic"})
        surv, _drp = _drop_keepoff([("chronic", "", 0.2), ("other", "", 0.15)], keepoff)
        det = _deterministic_hits("please deploy the app now", surv, keepoff)
        if any(n == "chronic" for n, _d, _s in det):
            bad.append("keep-off skill resurfaced via a deterministic route (ADR-0011 bypass)")
    finally:
        _ROUTES = _saved_routes2

    # (7) AUTHORIZED-SKIP tier: both legs inject the marker + required content when the
    # kill-switch is on, and stay fully silent (no inject call at all) when it's off.
    # Monkeypatch _inject to capture without touching real stdout.
    global _inject, AUTHORIZED_SKIP
    _saved_inject, _saved_authorized_skip = _inject, AUTHORIZED_SKIP
    _captured = []

    def _fake_inject(text):
        _captured.append(text)

    _inject = _fake_inject
    try:
        AUTHORIZED_SKIP = True
        _authorized_skip_inject("getaway", top=0.30, floor=0.45)
        _authorized_skip_inject("intent_skip")
        _authorized_skip_inject("selfref")
        if len(_captured) != 3:
            bad.append(f"authorized-skip: expected 3 injects when flag ON, got {len(_captured)}")
        else:
            if not all(c.startswith(AUTHORIZED_SKIP_MARKER) for c in _captured):
                bad.append("authorized-skip: injected text must start with the marker")
            if "find-skills" not in _captured[0] or "get_skill(" not in _captured[0]:
                bad.append("authorized-skip: getaway message missing find-skills escalation or get_skill nudge")
            if "0.30" not in _captured[0] or "0.45" not in _captured[0]:
                bad.append("authorized-skip: getaway message did not interpolate top/floor")
            if "conversational" not in _captured[1]:
                bad.append("authorized-skip: intent_skip message missing conversational rationale")
            # H5 [xcut#1]: the selfref leg carries the LOCKED cross-file signature (audit matches
            # this exact substring), and the signature is UNIQUE to it — a collision with the
            # getaway/intent messages (or, downstream, the H2 doctrine-table row) makes the audit
            # miscount real false-skips as authorized, masking the exact dodges H1 measures.
            if "self-referential recap lane" not in _captured[2]:
                bad.append("authorized-skip: selfref message missing the locked signature phrase")
            if ("self-referential recap lane" in _captured[0]
                    or "self-referential recap lane" in _captured[1]):
                bad.append("authorized-skip: selfref signature must NOT appear in getaway/intent messages")

        _captured.clear()
        AUTHORIZED_SKIP = False
        _authorized_skip_inject("getaway", top=0.30, floor=0.45)
        _authorized_skip_inject("intent_skip")
        _authorized_skip_inject("selfref")
        if _captured:
            bad.append("authorized-skip: must stay silent when the kill-switch is off")
    finally:
        _inject, AUTHORIZED_SKIP = _saved_inject, _saved_authorized_skip

    # (8) H5 self-referential over-fire lane — fires ONLY on a pure recap of the agent's own prior
    # message; the whole-prompt task-verb veto + connector veto keep any task-tail prompt OUT (the
    # must-NOT-fire bypasses are the red-team's core H5 correctness case).
    selfref_fire = [
        "explain your last answer again",
        "can you rephrase your previous response",
        "summarize what you just said please",
        "expand on that point a little more",
        "reword your explanation more simply",
        "clarify your previous answer",
    ]
    selfref_off = [
        "explain your answer and implement the migration",   # task tail (verb veto)
        "rephrase your last answer as a working config",     # task tail (connector veto)
        "clarify your point by writing the actual code",     # task tail (connector veto)
        "explain how the auth middleware works",             # external object, real question
        "summarize the changes then deploy them",            # external object + task
        "rephrase the readme into plain english",            # object is the readme, not the agent
    ]
    for t in selfref_fire:
        if not _is_selfref(t):
            bad.append("selfref MISS (should fire): " + repr(t))
    for t in selfref_off:
        if _is_selfref(t):
            bad.append("selfref FALSE-FIRE (should route normally): " + repr(t))
    if SELFREF_SKIP is not True:
        bad.append("ENFORCER_SELFREF_SKIP must default ON")

    # (9) ADR-0029 chain hint — fires on a fresh same-sid seed (auto AND manual/slash),
    # survives a NEWER sub-stamped row (ADR-0020 lane), drops keep-off'd and dangling
    # successors, silent on TTL-expired / other-sid / absent-sidecar / flag-off, and the
    # line carries neither the audit marker nor the locked signature phrases (parity).
    global CHAIN_HINT, CHAIN_TTL_S, _SIDECAR_PATH, LEDGER, KEEPOFF, _NEXT_SKILLS_OVERRIDES
    global MINED_CHAINS, _MINED_CHAINS_PATH
    _saved_chain = (CHAIN_HINT, CHAIN_TTL_S, _SIDECAR_PATH, LEDGER, KEEPOFF, _NEXT_SKILLS_OVERRIDES,
                    MINED_CHAINS, _MINED_CHAINS_PATH)
    with tempfile.TemporaryDirectory() as _td:
        _tdp = Path(_td)
        try:
            _sidecar = _tdp / "next-skills.json"
            _sidecar.write_text(json.dumps({
                "personal": {"seed-a": ["succ-b", "succ-c", "dead-x"],
                             "succ-b": [], "succ-c": [], "seed-k": ["succ-c"]},
                "plugin": {"pk:s": ["pk:t"], "pk:t": []},
                "project:elsewhere": {"ghost": ["spooky"], "spooky": []},
            }), encoding="utf-8")
            _led = _tdp / "ledger.log"
            _SIDECAR_PATH, LEDGER, KEEPOFF = _sidecar, _led, frozenset({"succ-c"})
            CHAIN_HINT, CHAIN_TTL_S = True, 900.0
            _now = time.time()
            _led.write_text("\n".join([
                json.dumps({"t": _now - 400, "sid": "s1", "ev": "auto", "name": "seed-a"}),
                json.dumps({"t": _now - 300, "sid": "s2", "ev": "manual", "name": "pk:s"}),
                json.dumps({"t": _now - 200, "sid": "s1", "ev": "auto", "name": "other", "sub": True}),
            ]) + "\n", encoding="utf-8")
            h = _chain_hint("s1")
            if "CHAIN-HINT: after seed-a" not in h or "succ-b" not in h:
                bad.append(f"chain-hint: expected seed-a -> succ-b line, got {h!r}")
            if "succ-c" in h or "dead-x" in h:
                bad.append(f"chain-hint: keep-off'd / dangling successors must be dropped: {h!r}")
            h2 = _chain_hint("s2")
            if "pk:s" not in h2 or "pk:t" not in h2:
                bad.append(f"chain-hint: manual (slash) seed must work via plugin scope: {h2!r}")
            # audit parity: the hint line itself must not match the marker or the
            # locked signature (else a collision miscounts real dodges as authorized).
            for _lit in ("SKILL-CHECK:", "self-referential recap lane"):
                if _lit in h:
                    bad.append(f"chain-hint: line must not contain locked literal {_lit!r}")
            # leg wiring: the hint rides an AUTHORIZED-SKIP line too (target population).
            _saved_inject2 = _inject
            _cap = []
            _inject = _cap.append
            try:
                _authorized_skip_inject("intent_skip", "s1")
                if len(_cap) != 1 or "SKILL-CHECK:" not in _cap[0] or "CHAIN-HINT:" not in _cap[0]:
                    bad.append(f"chain-hint: authorized-skip leg must carry both lines, got {_cap!r}")
            finally:
                _inject = _saved_inject2
            # TTL expiry
            _led.write_text(json.dumps(
                {"t": _now - 2000, "sid": "s1", "ev": "auto", "name": "seed-a"}) + "\n",
                encoding="utf-8")
            if _chain_hint("s1"):
                bad.append("chain-hint: TTL-expired seed must not hint")
            # other sid
            _led.write_text(json.dumps(
                {"t": _now - 10, "sid": "s9", "ev": "auto", "name": "seed-a"}) + "\n",
                encoding="utf-8")
            if _chain_hint("s1"):
                bad.append("chain-hint: another session's seed must not hint this one")
            # all-successors-keep-off'd
            _led.write_text(json.dumps(
                {"t": _now - 10, "sid": "s1", "ev": "auto", "name": "seed-k"}) + "\n",
                encoding="utf-8")
            if _chain_hint("s1"):
                bad.append("chain-hint: all-keep-off successors must yield no line")
            # absent sidecar -> fail open; flag off -> suppress
            _led.write_text(json.dumps(
                {"t": _now - 10, "sid": "s1", "ev": "auto", "name": "seed-a"}) + "\n",
                encoding="utf-8")
            _SIDECAR_PATH = _tdp / "nope.json"
            if _chain_hint("s1"):
                bad.append("chain-hint: absent sidecar must fail open to no hint")
            _SIDECAR_PATH = _sidecar
            CHAIN_HINT = False
            if _chain_hint("s1"):
                bad.append("chain-hint: flag off must suppress the line")
            CHAIN_HINT = True
            # (9b) ADR-0030 operator-owned overrides: override-wins over the sidecar
            # entry, keep-off still drops override successors, [] suppresses, and both
            # absent-file and malformed-file fail open to the sidecar value.
            _ovr = _tdp / "next-skills-overrides.json"
            _NEXT_SKILLS_OVERRIDES = _ovr
            _led.write_text(json.dumps(
                {"t": _now - 10, "sid": "s1", "ev": "auto", "name": "seed-a"}) + "\n", encoding="utf-8")
            _ovr.write_text(json.dumps({"seed-a": ["pk:t"]}), encoding="utf-8")
            h3 = _chain_hint("s1")
            if "pk:t" not in h3 or "succ-b" in h3:
                bad.append(f"chain-hint: override must win over the sidecar entry: {h3!r}")
            _ovr.write_text(json.dumps({"seed-a": ["not-in-catalogue"]}), encoding="utf-8")
            if _chain_hint("s1"):
                bad.append("chain-hint: override successor absent from the catalogue must drop (dangling)")
            _ovr.write_text(json.dumps({"seed-a": ["succ-c"]}), encoding="utf-8")
            if _chain_hint("s1"):
                bad.append("chain-hint: keep-off'd override successor must yield no line")
            _ovr.write_text(json.dumps({"seed-a": []}), encoding="utf-8")
            if _chain_hint("s1"):
                bad.append("chain-hint: empty override list must suppress the chain")
            _NEXT_SKILLS_OVERRIDES = _tdp / "nope-ovr.json"
            if "succ-b" not in _chain_hint("s1"):
                bad.append("chain-hint: absent overrides file must leave the sidecar value")
            _ovr.write_text("{not json", encoding="utf-8")
            _NEXT_SKILLS_OVERRIDES = _ovr
            if "succ-b" not in _chain_hint("s1"):
                bad.append("chain-hint: malformed overrides file must fail open to the sidecar value")
            _NEXT_SKILLS_OVERRIDES = _tdp / "nope-ovr.json"
            # (9c) ADR-0040 mined chains — lowest layer: fills an EMPTY declared entry
            # (with catalogue-visible successors only), never overrides a non-empty
            # declared value, is replaced by an explicit operator [] (applied after),
            # ignores keys from non-visible scopes, and fails open on flag-off /
            # absent / malformed file.
            _mined = _tdp / "mined-chains.json"
            _MINED_CHAINS_PATH = _mined
            _mined.write_text(json.dumps({"chains": {
                "succ-b": ["seed-a", "dead-z"],   # fills an empty declared entry
                "seed-a": ["pk:t"],               # declared non-empty -> mined ignored
                "ghost": ["seed-a"],              # key not visible (project:elsewhere)
            }}), encoding="utf-8")
            _led.write_text(json.dumps(
                {"t": _now - 10, "sid": "s1", "ev": "auto", "name": "succ-b"}) + "\n", encoding="utf-8")
            hm = _chain_hint("s1")
            if "seed-a" not in hm or "dead-z" in hm:
                bad.append(f"chain-hint: mined must fill empty declared entry, filtered: {hm!r}")
            _led.write_text(json.dumps(
                {"t": _now - 10, "sid": "s1", "ev": "auto", "name": "seed-a"}) + "\n", encoding="utf-8")
            hm2 = _chain_hint("s1")
            if "succ-b" not in hm2 or "pk:t" in hm2:
                bad.append(f"chain-hint: mined must not override a declared value: {hm2!r}")
            MINED_CHAINS = False
            _led.write_text(json.dumps(
                {"t": _now - 10, "sid": "s1", "ev": "auto", "name": "succ-b"}) + "\n", encoding="utf-8")
            if _chain_hint("s1"):
                bad.append("chain-hint: flag off must suppress the mined layer")
            MINED_CHAINS = True
            _ovr.write_text(json.dumps({"succ-b": []}), encoding="utf-8")
            _NEXT_SKILLS_OVERRIDES = _ovr
            if _chain_hint("s1"):
                bad.append("chain-hint: operator [] must replace a mined fill")
            _NEXT_SKILLS_OVERRIDES = _tdp / "nope-ovr.json"
            _led.write_text(json.dumps(
                {"t": _now - 10, "sid": "s1", "ev": "auto", "name": "seed-a"}) + "\n", encoding="utf-8")
            _MINED_CHAINS_PATH = _tdp / "nope-mined.json"
            if "succ-b" not in _chain_hint("s1"):
                bad.append("chain-hint: absent mined file must fail open to declared")
            _mined.write_text("{not json", encoding="utf-8")
            _MINED_CHAINS_PATH = _mined
            if "succ-b" not in _chain_hint("s1"):
                bad.append("chain-hint: malformed mined file must fail open to declared")
            _MINED_CHAINS_PATH = _tdp / "nope-mined.json"
        finally:
            CHAIN_HINT, CHAIN_TTL_S, _SIDECAR_PATH, LEDGER, KEEPOFF, _NEXT_SKILLS_OVERRIDES, \
                MINED_CHAINS, _MINED_CHAINS_PATH = _saved_chain

    # (10) ADR-0031 installed query: _retrieve ALWAYS carries must_not tier=external
    # (byte-identical whether or not the ADR-0032 annex is on — externals cannot displace
    # installed). Its limit is RETRIEVE_LIMIT while ADR-0034's post-filter is on (over-fetch,
    # then trim to TOP_K) and exactly TOP_K when it is off. Pin the REQUEST SHAPE
    # (monkeypatched transport) and the 3-tuple parse.
    #
    # ONE consolidated `global` for every module name cases (10)-(12) rebind. Declaring them
    # per-case made a later case silently depend on an earlier one's declaration, so deleting
    # or reordering a case turned the next into an UnboundLocalError at its own save-line.
    global _post_json, EXTERNAL_ANNEX, EXTERNAL_SLOTS, EXTERNAL_FLOOR
    global CROSS_HARNESS, FOREIGN_SLOTS, FOREIGN_FLOOR, FOREIGN_SCOPES, INVOCABLE_PLUGIN_IDS
    global ANNEX_DYNAMIC, ANNEX_MARGIN, UNDER_CODEX, RUNNING_HARNESS, FOREIGN_HARNESS
    global _zcode_readable_skill, _zcode_shares_personal_shelf
    _saved_dyn12 = ANNEX_DYNAMIC
    _saved_post = _post_json
    _reqs = []

    def _fake_post(url, payload, timeout):
        _reqs.append(payload)
        return {"result": {"groups": [
            {"id": "x", "hits": [{"payload": {"name": "inst", "description": "d"},
                                  "score": 0.5}]}]}}

    _post_json = _fake_post
    try:
        got = _retrieve([0.1, 0.2])
        flt = (_reqs[0] or {}).get("filter", {})
        if {"key": "tier", "match": {"value": "external"}} not in flt.get("must_not", []):
            bad.append(f"retrieve: missing must_not tier=external filter (installed query): {flt!r}")
        if _reqs[0].get("limit") != (RETRIEVE_LIMIT if CROSS_HARNESS else TOP_K):
            bad.append("retrieve: installed limit must over-fetch when ADR-0034 is on, "
                       "and be exactly TOP_K when off: {!r}".format(_reqs[0].get("limit")))
        if got != [("inst", "d", 0.5)]:
            bad.append(f"retrieve: response parse changed: {got!r}")
    finally:
        _post_json = _saved_post

    # (11) ADR-0032 external annex: _retrieve_external issues a SEPARATE must tier=external query
    # (never touches the installed query), applies EXTERNAL_FLOOR + EXTERNAL_SLOTS, derives the
    # alias, and _ranked_mandate renders a distinct annex block with the get_skill instruction.
    # Kill-switch off -> empty (no query issued).
    _saved = (EXTERNAL_ANNEX, EXTERNAL_SLOTS, EXTERNAL_FLOOR, _post_json,
              ANNEX_DYNAMIC, ANNEX_MARGIN)
    _ereqs = []

    def _fake_ext_post(url, payload, timeout):
        _ereqs.append(payload)
        return {"result": {"groups": [
            {"id": "1", "hits": [{"payload": {"name": "cat:hi", "description": "dh",
                                              "scope": "catalog:cat"}, "score": 0.75}]},
            {"id": "2", "hits": [{"payload": {"name": "cat:low", "description": "dl",
                                              "scope": "catalog:cat"}, "score": 0.30}]}]}}

    try:
        EXTERNAL_ANNEX, EXTERNAL_SLOTS, EXTERNAL_FLOOR = True, 2, 0.40
        ANNEX_DYNAMIC, ANNEX_MARGIN = False, 0.05
        _post_json = _fake_ext_post
        ext = _retrieve_external([0.1])
        req = _ereqs[0]
        if {"key": "tier", "match": {"value": "external"}} not in req.get("filter", {}).get("must", []):
            bad.append("annex query: must carry must tier=external filter: {!r}".format(req.get("filter")))
        if req.get("limit") != EXTERNAL_SLOTS:
            bad.append("annex query: limit must be EXTERNAL_SLOTS")
        if [n for n, _d, _s, _a in ext] != ["cat:hi"]:
            bad.append(f"annex: only ≥FLOOR externals kept (0.30 dropped): {ext!r}")
        if ext and ext[0][3] != "cat":
            bad.append("annex: alias not derived from scope")
        rendered = _ranked_mandate([("inst-a", "da", 0.9)], annex=ext)
        if "[external:cat]" not in rendered or "get_skill" not in rendered:
            bad.append("annex: render missing external marker or get_skill instruction")
        if "cat:low" in rendered:
            bad.append("annex: below-floor external must not render")
        # kill-switch off -> empty, no query issued
        EXTERNAL_ANNEX = False
        _ereqs.clear()
        if _retrieve_external([0.1]) != [] or _ereqs:
            bad.append("annex: kill-switch off must issue no external query and return []")
        if "[external:" in _ranked_mandate([("a", "d", 0.3)], annex=[]):
            bad.append("annex: empty annex must render no external block")

        # (11b) ADR-0036 dynamic annex floor. The rule in one function, pinned in both modes:
        # fixed mode ignores the installed top; dynamic mode is competitive with it, never
        # below the pool floor, and an absent installed top (<=0) falls back to the floor —
        # an empty inventory is the case the annex exists for, not a reason to suppress it.
        EXTERNAL_ANNEX = True
        ANNEX_DYNAMIC = False
        if _annex_floor(0.40, 0.90) != 0.40:
            bad.append("annex-floor: fixed mode must ignore the installed top")
        ANNEX_DYNAMIC = True
        if abs(_annex_floor(0.40, 0.90) - 0.85) > 1e-9:
            bad.append("annex-floor: dynamic must be top_installed - margin when above the floor")
        if _annex_floor(0.40, 0.42) != 0.40:
            bad.append("annex-floor: dynamic must never drop below the pool floor")
        if _annex_floor(0.40, 0.0) != 0.40:
            bad.append("annex-floor: no installed candidates must fall back to the pool floor")
        # end-to-end: a strong installed top prunes the 0.75 external; a weak one keeps it
        if [n for n, _d, _s, _a in _retrieve_external([0.1], top_installed=0.90)] != []:
            bad.append("annex: dynamic floor must prune externals losing to a strong installed top")
        if [n for n, _d, _s, _a in _retrieve_external([0.1], top_installed=0.55)] != ["cat:hi"]:
            bad.append("annex: dynamic floor must keep externals competitive with a weak installed top")
    finally:
        (EXTERNAL_ANNEX, EXTERNAL_SLOTS, EXTERNAL_FLOOR, _post_json,
         ANNEX_DYNAMIC, ANNEX_MARGIN) = _saved

    # (12) ADR-0034 cross-harness. Pins the four things the design rests on:
    #   - a foreign-scope row is dropped from the INSTALLED offer, and the offer still fills to
    #     TOP_K from the over-fetch (no shrinkage);
    #   - an invocable TWIN in a foreign scope is KEPT installed and NOT repeated in the annex
    #     (the defect that made a pre-filter unusable: scope != invocability);
    #   - the annex query filters on the foreign scope SET, applies the floor, and renders with
    #     the harness marker + get_skill instruction, never joining the installed %-share pool;
    #   - the kill-switch restores the pre-ADR-0034 request shape and output exactly.
    _saved_xh = (CROSS_HARNESS, FOREIGN_SLOTS, FOREIGN_FLOOR, FOREIGN_SCOPES,
                 INVOCABLE_PLUGIN_IDS, _post_json)
    _freqs = []

    def _grp(gid, name, score, scope=None):
        pl = {"name": name, "description": "d-" + name}
        if scope:
            pl["scope"] = scope
        return {"id": gid, "hits": [{"payload": pl, "score": score}]}

    def _fake_xh_post(url, payload, timeout):
        _freqs.append(payload)
        flt = payload.get("filter", {})
        if flt.get("must"):                                   # the annex query
            return {"result": {"groups": [
                _grp("1", "otherpl:hi", 0.72), _grp("2", "twinpl:dup", 0.71),
                _grp("3", "otherpl:low", 0.31)]}}
        # the installed query: 2 foreign rows (one a twin), then plenty of installed filler
        return {"result": {"groups": [
            _grp("f1", "otherpl:hi", 0.9, "codex-plugin"),
            _grp("f2", "twinpl:dup", 0.89, "codex-plugin")]
            + [_grp(f"i{k}", f"inst-{k}", 0.8 - k / 100, "personal") for k in range(TOP_K)]}}

    _saved_uc = UNDER_CODEX
    _saved_rh = RUNNING_HARNESS
    _saved_fh = FOREIGN_HARNESS
    try:
        if FOREIGN_HARNESS not in ("codex", "claude", "claude/codex", "commandcode",
                                   "claude/codex/omp") or not FOREIGN_SCOPES:
            bad.append(f"cross-harness: harness label / foreign scopes unset: {FOREIGN_HARNESS!r}/{FOREIGN_SCOPES!r}")
        if RUNNING_HARNESS == "claude" and not all(x.startswith(("codex-", "commandcode-")) for x in FOREIGN_SCOPES):
            bad.append(f"cross-harness: claude harness label disagrees with the foreign scope set: {FOREIGN_HARNESS!r}/{FOREIGN_SCOPES!r}")
        # Nothing at module scope may touch the filesystem unguarded: `Path.cwd()` raises when
        # the working directory has been deleted (a worktree removed under a live session), and
        # an import-time raise turns a fail-silent hook into a traceback on every turn.
        _cwd = os.getcwd()
        _tmpd = tempfile.mkdtemp()
        try:
            os.chdir(_tmpd)
            os.rmdir(_tmpd)                  # cwd now deleted
            _invocable_plugin_ids()          # must not raise
            _visible_sidecar_names()         # nor this — it runs before _inject, so a raise
                                             # here costs the whole offer, silently
        except (OSError, UnicodeError, ValueError, TypeError, AttributeError, KeyError) as _e:
            bad.append("cross-harness: the import-time settings read and the chain-hint scope "
                       f"mirror must BOTH survive a deleted cwd: {type(_e).__name__}: {_e}")
        finally:
            os.chdir(_cwd)
            # os.rmdir above normally removed it; this only fires if os.chdir raised first.
            try:
                os.rmdir(_tmpd)
            except OSError:
                pass

        # `Path("").resolve()` is the CWD — a falsy env var must never be probed as a path.
        _cpr = os.environ.pop("CLAUDE_PLUGIN_ROOT", None)
        try:
            os.environ["CLAUDE_PLUGIN_ROOT"] = ""
            if (_running_harness() == "codex") != (f"{os.sep}.codex{os.sep}"
                                                   in str(Path(__file__).resolve())):
                bad.append("cross-harness: empty CLAUDE_PLUGIN_ROOT must fall through to "
                           "__file__, never resolve to the cwd")
            # A LITERAL like `$HOME/.claude` (a settings-level env block never shell-expands)
            # must also fall through — machine config debris cannot decide the harness.
            os.environ["CLAUDE_PLUGIN_ROOT"] = "$HOME/.claude"
            if (_running_harness() == "codex") != (f"{os.sep}.codex{os.sep}"
                                                   in str(Path(__file__).resolve())):
                bad.append("cross-harness: a non-absolute CLAUDE_PLUGIN_ROOT literal must fall "
                           "through to __file__, never be resolved against the cwd")
        finally:
            os.environ.pop("CLAUDE_PLUGIN_ROOT", None)
            if _cpr is not None:
                os.environ["CLAUDE_PLUGIN_ROOT"] = _cpr

        CROSS_HARNESS, FOREIGN_SLOTS, FOREIGN_FLOOR = True, 2, 0.40
        ANNEX_DYNAMIC = False   # case (12) pins the ADR-0034 shape; (11b) owns the dynamic rule
        # Pin the HARNESS DIRECTION too, not just the scope world. The assertions below model the
        # Claude-side twin rescue; run from a Codex cache path (or under garbage env) the module
        # derives UNDER_CODEX=True, _invocable_twin goes deliberately blind, and exactly the three
        # twin assertions fail — a false alarm on the documented post-deploy verification command
        # (found by the first live Codex revalidation, defect D1).
        UNDER_CODEX = False
        RUNNING_HARNESS = "claude"
        FOREIGN_HARNESS = "codex"
        FOREIGN_SCOPES, INVOCABLE_PLUGIN_IDS = ("codex-plugin", "codex-personal"), {"twinpl"}
        _post_json = _fake_xh_post

        _freqs.clear()
        inst = _retrieve([0.1])
        names = [n for n, _d, _s in inst]
        if _freqs[0].get("limit") != RETRIEVE_LIMIT:
            bad.append("cross-harness: installed query must over-fetch to RETRIEVE_LIMIT")
        if "scope" not in (_freqs[0].get("with_payload") or []):
            bad.append("cross-harness: installed query must request the scope payload")
        if any(c.get("key") == "scope"
               for c in _freqs[0].get("filter", {}).get("must_not", [])):
            bad.append("cross-harness: scope must be post-filtered, never a query condition "
                       "(scope != invocability): {!r}".format(_freqs[0].get("filter")))
        if "otherpl:hi" in names:
            bad.append("cross-harness: a non-invocable foreign row must not reach the offer")
        if "twinpl:dup" not in names:
            bad.append("cross-harness: an INVOCABLE twin must stay in the installed offer")
        if len(inst) != TOP_K:
            bad.append(f"cross-harness: offer must refill to TOP_K after the drop: {len(inst)}")

        # UNKNOWN must filter NOTHING. A None manifest means the twin test cannot be made, and
        # dropping on that reinstates the exact mislabelling the post-filter replaced.
        INVOCABLE_PLUGIN_IDS = None
        _freqs.clear()
        if "otherpl:hi" not in [n for n, _d, _s in _retrieve([0.1])]:
            bad.append("cross-harness: unknown plugin manifest must filter NOTHING, "
                       "never drop every foreign row")
        INVOCABLE_PLUGIN_IDS = {"twinpl"}

        _freqs.clear()
        fgn = _retrieve_foreign([0.1])
        cond = (_freqs[0].get("filter", {}).get("must") or [{}])[0]
        if cond.get("key") != "scope" or set(cond.get("match", {}).get("any") or []) != \
                set(FOREIGN_SCOPES):
            bad.append(f"cross-harness: annex query must match the foreign scope SET: {cond!r}")
        if [n for n, _d, _s in fgn] != ["otherpl:hi"]:
            bad.append("cross-harness: annex keeps only above-floor non-twins "
                       f"(0.31 below floor, twinpl:dup invocable here): {fgn!r}")
        rendered = _ranked_mandate([("inst-a", "da", 0.9)], foreign=fgn)
        if f"[{FOREIGN_HARNESS}]" not in rendered or "get_skill" not in rendered:
            bad.append("cross-harness: render missing harness marker or get_skill instruction")
        if "otherpl:low" in rendered or "twinpl:dup" in rendered:
            bad.append("cross-harness: below-floor or twin row must not render in the annex")
        if "%" in rendered.split("Other-harness")[0].split("inst-a")[1][:12]:
            bad.append("cross-harness: foreign must not join the installed %-share pool")

        # OMP direction: harness detection, foreign label/scopes, and the twin test.
        # Pin the OMP env forms and the natural marker + OMPCODE detection, then the
        # foreign-scope world and the union rule (plugin ids invocable here).
        _saved_omp_env = (os.environ.get("SKILL_CONCIERGE_HARNESS"), os.environ.get("OMPCODE"))
        _saved_rh2, _saved_fh2 = RUNNING_HARNESS, FOREIGN_HARNESS
        _saved_fs2, _saved_inv2 = FOREIGN_SCOPES, INVOCABLE_PLUGIN_IDS
        try:
            # explicit env forms
            os.environ["SKILL_CONCIERGE_HARNESS"] = "omp"
            os.environ["OMPCODE"] = ""
            if _running_harness() != "omp":
                bad.append("cross-harness: SKILL_CONCIERGE_HARNESS=omp must resolve to omp")
            os.environ["SKILL_CONCIERGE_HARNESS"] = "oh-my-pi"
            if _running_harness() != "omp":
                bad.append("cross-harness: SKILL_CONCIERGE_HARNESS=oh-my-pi must resolve to omp")
            # OMP with CLAUDE markers set must resolve to omp (OMPCODE is the proof), never claude
            os.environ["SKILL_CONCIERGE_HARNESS"] = ""
            os.environ["OMPCODE"] = "1"
            if _running_harness() != "omp":
                bad.append("cross-harness: OMPCODE=1 must force omp even under claude markers")
            # claude/codex explicit values unchanged (not hijacked by OMPCODE)
            os.environ["SKILL_CONCIERGE_HARNESS"] = "claude"
            if _running_harness() != "claude":
                bad.append("cross-harness: SKILL_CONCIERGE_HARNESS=claude must stay claude")
            os.environ["SKILL_CONCIERGE_HARNESS"] = "codex"
            if _running_harness() != "codex":
                bad.append("cross-harness: SKILL_CONCIERGE_HARNESS=codex must stay codex")
            RUNNING_HARNESS = "omp"
            if _foreign_harness_label() != "commandcode":
                bad.append("cross-harness: omp foreign label must be commandcode: "
                           f"{_foreign_harness_label()!r}")
            if _foreign_scopes() != ("codex-plugin", "commandcode-personal"):
                bad.append("cross-harness: omp foreign scopes wrong: "
                           f"{_foreign_scopes()!r}")
            # twin test is active under omp (plugin ids invocable via the claude/omp union)
            INVOCABLE_PLUGIN_IDS = {"twinpl"}
            if not _invocable_twin("twinpl:dup"):
                bad.append("cross-harness: omp must rescue an invocable plugin twin")
            INVOCABLE_PLUGIN_IDS = None
            if _invocable_twin("twinpl:dup"):
                bad.append("cross-harness: omp unknown manifest must not rescue a twin")
        finally:
            os.environ.pop("SKILL_CONCIERGE_HARNESS", None)
            os.environ.pop("OMPCODE", None)
            if _saved_omp_env[0] is not None:
                os.environ["SKILL_CONCIERGE_HARNESS"] = _saved_omp_env[0]
            if _saved_omp_env[1] is not None:
                os.environ["OMPCODE"] = _saved_omp_env[1]
            RUNNING_HARNESS, FOREIGN_HARNESS = _saved_rh2, _saved_fh2
            FOREIGN_SCOPES, INVOCABLE_PLUGIN_IDS = _saved_fs2, _saved_inv2

        # ZCode direction (ADR-0042): detection (explicit env, ZCODE_PLUGIN_ROOT env with the
        # falsy/non-absolute fallthroughs, explicit-env precedence), foreign label/scopes with
        # the shared-shelf personal rule, the registry twin, and the filesystem twin.
        # Mirrors the OMP direction block above.
        _saved_z_env = (os.environ.get("SKILL_CONCIERGE_HARNESS"),
                        os.environ.get("ZCODE_PLUGIN_ROOT"))
        _saved_rh3, _saved_fs3, _saved_inv3 = RUNNING_HARNESS, FOREIGN_SCOPES, INVOCABLE_PLUGIN_IDS
        _saved_fstwin, _saved_shelf = _zcode_readable_skill, _zcode_shares_personal_shelf
        try:
            os.environ["SKILL_CONCIERGE_HARNESS"] = "zcode"
            if _running_harness() != "zcode":
                bad.append("cross-harness: SKILL_CONCIERGE_HARNESS=zcode must resolve to zcode")
            os.environ["SKILL_CONCIERGE_HARNESS"] = ""
            os.environ["ZCODE_PLUGIN_ROOT"] = "/tmp/.zcode/cli/plugins/cache/p/x/1.0"
            if _running_harness() != "zcode":
                bad.append("cross-harness: ZCODE_PLUGIN_ROOT set must resolve to zcode")
            os.environ["ZCODE_PLUGIN_ROOT"] = ""
            if _running_harness() == "zcode":
                bad.append("cross-harness: empty ZCODE_PLUGIN_ROOT must fall through (never the cwd)")
            os.environ["ZCODE_PLUGIN_ROOT"] = "relative/path"
            if _running_harness() == "zcode":
                bad.append("cross-harness: non-absolute ZCODE_PLUGIN_ROOT must fall through")
            # explicit SKILL_CONCIERGE_HARNESS outranks the zcode env signal
            os.environ["SKILL_CONCIERGE_HARNESS"] = "claude"
            if _running_harness() != "claude":
                bad.append("cross-harness: SKILL_CONCIERGE_HARNESS=claude must stay claude under ZCODE_PLUGIN_ROOT")
            os.environ.pop("SKILL_CONCIERGE_HARNESS", None)
            os.environ.pop("ZCODE_PLUGIN_ROOT", None)

            RUNNING_HARNESS = "zcode"
            if _foreign_harness_label() != "claude/codex/omp":
                bad.append(f"cross-harness: zcode foreign label wrong: {_foreign_harness_label()!r}")
            _zcode_shares_personal_shelf = lambda: True
            _fs = _foreign_scopes()
            if "personal" in _fs or "zcode-personal" in _fs or \
                    not {"plugin", "codex-plugin", "commandcode-personal", "omp-managed"} <= set(_fs):
                bad.append(f"cross-harness: zcode shared-shelf foreign scopes wrong: {_fs!r}")
            _zcode_shares_personal_shelf = lambda: False
            if "personal" not in _foreign_scopes():
                bad.append("cross-harness: zcode divergent-shelf must foreign personal "
                           "(the per-row filesystem twin rescues what is actually readable)")
            _zcode_shares_personal_shelf = _saved_shelf
            # twins: registry plugin twin, filesystem twin, a true non-twin, and the
            # unknown-manifest rule (must not rescue — mirrors the OMP assertion).
            FOREIGN_SCOPES = ("personal", "plugin")
            INVOCABLE_PLUGIN_IDS = {"twinpl"}
            if not _invocable_twin("twinpl:dup"):
                bad.append("cross-harness: zcode must rescue a registry plugin twin")
            _zcode_readable_skill = lambda n: n == "fstwin"
            INVOCABLE_PLUGIN_IDS = set()
            if not _invocable_twin("fstwin"):
                bad.append("cross-harness: zcode must rescue a filesystem twin")
            if _invocable_twin("other:nope"):
                bad.append("cross-harness: zcode must not rescue a row with no twin")
            _zcode_readable_skill = _saved_fstwin
            INVOCABLE_PLUGIN_IDS = None
            if _invocable_twin("twinpl:dup"):
                bad.append("cross-harness: zcode unknown manifest must not rescue a plugin twin")
        finally:
            os.environ.pop("SKILL_CONCIERGE_HARNESS", None)
            os.environ.pop("ZCODE_PLUGIN_ROOT", None)
            if _saved_z_env[0] is not None:
                os.environ["SKILL_CONCIERGE_HARNESS"] = _saved_z_env[0]
            if _saved_z_env[1] is not None:
                os.environ["ZCODE_PLUGIN_ROOT"] = _saved_z_env[1]
            RUNNING_HARNESS, FOREIGN_SCOPES, INVOCABLE_PLUGIN_IDS = _saved_rh3, _saved_fs3, _saved_inv3
            _zcode_readable_skill, _zcode_shares_personal_shelf = _saved_fstwin, _saved_shelf

        # kill-switch off -> pre-ADR-0034 request shape and output
        CROSS_HARNESS = False
        _freqs.clear()
        _retrieve([0.1])
        if _freqs[0].get("limit") != TOP_K or "scope" in (_freqs[0].get("with_payload") or []):
            bad.append(f"cross-harness: kill-switch off must issue the pre-ADR-0034 request: {_freqs[0]!r}")
        _freqs.clear()
        if _retrieve_foreign([0.1]) != [] or _freqs:
            bad.append("cross-harness: kill-switch off must issue no annex query and return []")
        if "Other-harness" in _ranked_mandate([("a", "d", 0.3)], foreign=[]):
            bad.append("cross-harness: empty foreign annex must render no block")
    finally:
        (CROSS_HARNESS, FOREIGN_SLOTS, FOREIGN_FLOOR, FOREIGN_SCOPES,
         INVOCABLE_PLUGIN_IDS, _post_json) = _saved_xh
        ANNEX_DYNAMIC = _saved_dyn12
        UNDER_CODEX = _saved_uc
        RUNNING_HARNESS = _saved_rh
        FOREIGN_HARNESS = _saved_fh

    # (13) ADR-0041 multi-intent shaping + route projection. Pins: two lexically
    # disjoint, score-comparable candidate groups split into 2 intents with
    # leads-first ordering; a weak second cluster does NOT split; siblings of one
    # intent stay one intent (byte-identical note); _route_of walks successors,
    # caps at 4 nodes, breaks cycles and dead ends; flags off revert to the
    # pre-0041 render; and the new lines carry neither the audit marker nor the
    # locked signature phrases (parity, same rule as the CHAIN-HINT line).
    # (_SIDECAR_PATH / _NEXT_SKILLS_OVERRIDES / _MINED_CHAINS_PATH were declared
    # global with case (9); they are only REBOUND here.)
    global MULTI_INTENT, CHAIN_PROJECTION
    _saved_41 = (MULTI_INTENT, CHAIN_PROJECTION, _MINED_CHAINS_PATH)
    try:
        _plan = ("plan", "scope a feature into a phased implementation roadmap with acceptance criteria", 0.40)
        _road = ("roadmap", "phased implementation roadmap milestones deliverables sequencing", 0.30)
        _test = ("test", "run the unit and integration suites, coverage gaps, failing checks", 0.36)
        _cov = ("coverage", "coverage of the unit and integration suites, gaps in assertions", 0.28)
        _c41 = [_plan, _test, _road, _cov]
        _cls = _intent_clusters(_c41)
        if len(_cls) != 2 or {c[0][0] for c in _cls} != {"plan", "test"}:
            bad.append(f"0041: expected plan/test clusters, got {[ [m[0] for m in c] for c in _cls ]!r}")
        if not _multi_intent_gate(_cls):
            bad.append("0041: comparable second cluster must pass the multi-intent gate")
        r41 = _ranked_mandate(_c41)
        if "Reads as 2 distinct intents" not in r41:
            bad.append("0041: two-intent render must carry the intent note")
        _first_rows = [l for l in r41.splitlines() if l.startswith("  • ")][:2]
        if not (_first_rows[0].startswith("  • plan") and _first_rows[1].startswith("  • test")):
            bad.append(f"0041: leads must render first, got {_first_rows!r}")
        # smoke-shaped regression (live 0.32.0 over-split): one test/fix family with
        # synonym vocabulary must NOT split into fake intents; and >MAX_INTENTS clusters
        # are capped, folding extras back as supporting rows.
        _t1 = ("ak-web-testing", "Web testing with Playwright, Vitest, k6. E2E/unit/integration/load/security/visual/a11y", 0.34)
        _t2 = ("ak-fix", "Fix bugs, errors, test failures, and CI/CD issues with intelligent routing", 0.33)
        _t3 = ("ak-test", "Run unit, integration, e2e, and UI tests. Test execution, coverage analysis, QA reports", 0.32)
        _t4 = ("dogfood", "Systematically explore and test a web application to find bugs, UX issues", 0.30)
        _t5 = ("ak-debug", "Debug systematically with root cause analysis before fixes. For bugs, test failures", 0.29)
        _smoke_cls = _intent_clusters([_t1, _t2, _t3, _t4, _t5])
        if len(_smoke_cls) > 2:
            bad.append(f"0041: same-family synonyms must not fake-split: {[ [m[0] for m in c] for c in _smoke_cls ]!r}")
        _smoke_render = _ranked_mandate([_t1, _t2, _t3, _t4, _t5])
        if "distinct intents" in _smoke_render and "8 distinct" in _smoke_render:
            bad.append("0041: smoke regression — absurd intent count")
        # cap: 4 two-member disjoint clusters -> at most MAX_INTENTS announced
        # (each non-first intent qualifies with 2 members; the 4th folds back as support)
        _dis = [("aa", "alpha beta gamma delta epsilon zeta", 0.40),
                ("aa2", "alpha beta gamma delta epsilon", 0.39),
                ("bb", "eta theta iota kappa lambda mu", 0.38),
                ("bb2", "eta theta iota kappa lambda", 0.37),
                ("cc", "nu xi omicron pi rho sigma", 0.36),
                ("cc2", "nu xi omicron pi rho", 0.35),
                ("dd", "tau upsilon phi chi psi omega", 0.34),
                ("dd2", "tau upsilon phi chi psi", 0.33)]
        _cap_render = _ranked_mandate(_dis)
        if f"Reads as {MAX_INTENTS} distinct intents" not in _cap_render:
            bad.append(f"0041: >MAX_INTENTS clusters must cap at {MAX_INTENTS}: "
                       + repr([l for l in _cap_render.splitlines() if "distinct intents" in l]))
        # singleton second cluster no longer qualifies (0.32.2 precision rule)
        _solo = [("aa", "alpha beta gamma delta epsilon zeta", 0.40),
                 ("zz", "unrelated disjoint vocabulary entirely", 0.39)]
        if "distinct intents" in _ranked_mandate(_solo):
            bad.append("0041: a singleton second cluster must not be announced as an intent")
        # weak second cluster: low score -> no split, standard note
        _weak = [_plan, ("test", "run the unit and integration suites, coverage gaps, failing checks", 0.10)]
        if "distinct intents" in _ranked_mandate(_weak):
            bad.append("0041: weak second cluster must not split the turn")
        # one intent, lexically close siblings -> original note, no split
        _single = [_plan, _road]
        r_single = _ranked_mandate(_single)
        if "distinct intents" in r_single or "pick the one matching the intent" not in r_single:
            bad.append("0041: single-intent siblings must keep the pre-0041 note")
        # _route_of: walk, cap, cycle, dead-end
        _saved_41_paths = (_SIDECAR_PATH, _NEXT_SKILLS_OVERRIDES)
        with tempfile.TemporaryDirectory() as _td41:
            _tdp41 = Path(_td41)
            _sc41 = _tdp41 / "ns.json"
            _sc41.write_text(json.dumps({"personal": {
                "a": ["b", "x"], "b": ["c"], "c": ["a"],        # a->b->c->a cycle
                "d": [],                                          # dead end
            }}), encoding="utf-8")
            _SIDECAR_PATH = _sc41
            _NEXT_SKILLS_OVERRIDES = _tdp41 / "nope.json"
            _MINED_CHAINS_PATH = _tdp41 / "nope2.json"
            _m41 = _visible_sidecar_names()
            if _route_of("a", _m41) != ["a", "b", "c"]:
                bad.append(f"0041: route must walk a->b->c and cap before the cycle: {_route_of('a', _m41)!r}")
            if _route_of("b", _m41) != ["b", "c", "a"]:
                bad.append(f"0041: mid-chain seed must walk its tail, cycle-blocked at the 4th hop: {_route_of('b', _m41)!r}")
            if _route_of("d", _m41):
                bad.append("0041: dead-end seed must yield no route")
            if _route_of("ghost", _m41):
                bad.append("0041: unknown seed must yield no route")
            if "ROUTE: if a fits" not in _ranked_mandate([("a", "desc", 0.4), ("z", "desc", 0.3)]):
                bad.append("0041: top candidate with successors must render the ROUTE line")
            for _lit in ("SKILL-CHECK:", "self-referential recap lane"):
                if _lit in _ranked_mandate([("a", "desc", 0.4)]):
                    bad.append(f"0041: render must not contain locked literal {_lit!r}")
            CHAIN_PROJECTION = False
            if "ROUTE:" in _ranked_mandate([("a", "desc", 0.4)]):
                bad.append("0041: projection flag off must suppress the ROUTE line")
            CHAIN_PROJECTION = True
            MULTI_INTENT = False
            if "distinct intents" in _ranked_mandate(_c41):
                bad.append("0041: multi-intent flag off must revert to the pre-0041 note")
            MULTI_INTENT = True
        _SIDECAR_PATH, _NEXT_SKILLS_OVERRIDES = _saved_41_paths
    finally:
        MULTI_INTENT, CHAIN_PROJECTION, _MINED_CHAINS_PATH = _saved_41

    if bad:
        print("enforcer --selftest FAIL:")
        for b in bad:
            print("  " + b)
        return 1
    print(f"enforcer --selftest OK: refusal guard ({len(must_fire)} fire / "
          f"{len(must_not_fire)} silent) + ranked-mandate %-share "
          f"+ actionability imperative-veto ({len(imp_fire)} fire / {len(imp_off)} off) "
          "+ keepoff-drop + gap-collapse "
          "+ per-skill-tau/deterministic-routes (default-inert) + authorized-skip tier "
          f"(3 injects on / silent-off) + selfref over-fire lane ({len(selfref_fire)} fire / "
          f"{len(selfref_off)} off) "
          "+ cross-harness annex "
          "+ CJK word-count (pre-gate no longer swallows no-space scripts)")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    sys.exit(main())
