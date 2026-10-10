#!/usr/bin/env python3
"""
skill-concierge — semantic skill-first enforcer (UserPromptSubmit hook).

Supersedes the lexical ~/.claude/hooks/skill_first_nudge.py. On a non-trivial
prompt it embeds the query via the local index owner, retrieves the top-k semantic
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
timeout (see EMBED_TIMEOUT_S for the calibration history; live default 500ms since
ADR-0054). Every network leg is separately capped, so the worst case is the sum of the
caps, not an unbounded wait: 500ms embed + 250ms installed query + up to 2x250ms
actionability gate + 250ms external annex + 250ms cross-harness annex ~= 1.75s, while the
ADR-0061 Jev router runs IN PARALLEL in a worker thread (catalogue scroll + 2 calls per bench tier; TypeSafe
~0.7s warm), joined under a hard 7.8s cap (ADR-0079: Command Code's 5.5s span, then TypeSafe) — ~8.9s worst
case against Claude Code's 10s hook timeout (JEV_BUDGET_S).
The annex legs run only on turns that actually carry an offer. On ANY of (a) embed
unreachable, (b) Qdrant unreachable, (c) embed exceeds the timeout, the hook serves the
Jev verdict when one arrived (`_jev_serve`), else the named-route hits or MANDATE-ONLY —
never silent, never crashing. (c) is load-bearing: a reachability check misses an
up-but-slow shim that would otherwise silently tax every prompt.

Telemetry. Emits an `offer` event to the shared invocation ledger so analyze.py
can compute hit@k and fallback rate:
  {t, sid, ev:"offer", band, offered:[[name,score]...], fallback, q:<≤120c>}
"""
from __future__ import annotations

import http.client
import json
import math
import os
import re
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# The one strict port grammar every port-deriving caller applies (vendor/skill-search/
# skill_search/ports.py: owner, doctor, server.py, this hook, the bash launcher, setup.sh)
# — ASCII digits only, 1-65535, deliberately narrower than a bare int() (which also accepts
# " 7363", "+7363", "7_363" and full-width digits). This hook must never crash on an import
# it doesn't strictly need to keep running: on any failure to import it, `ports` stays
# `None` and the two endpoints below fall back to the fixed well-known defaults directly —
# never a second copy of the grammar.
try:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "vendor" / "skill-search"))
    from skill_search import ports
except Exception:  # pragma: no cover - defensive; see comment above
    ports = None

# The one harness detector enforcer, doctrine and ledger share. Without it the offer could
# target the wrong harness's skills, so a copy that lacks it serves no menu (fail-silent).
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from harness import running_harness
except Exception:  # noqa: BLE001
    if __name__ == "__main__":
        sys.exit(0)  # a hook run stays silent on a broken install
    raise  # an importer (the findability sweep, skill_exclusions) handles the ImportError

# ── endpoints ────────────────────────────────────────────────────────────────
EMBED_HOST = os.environ.get("EMBED_SHIM_HOST", "127.0.0.1")
if ports is not None:
    EMBED_PORT = ports.embed_port(default=6363)
    QDRANT_URL, _qdrant_notice = ports.resolved_qdrant_url(default_port=6333)
    QDRANT_URL = QDRANT_URL.rstrip("/")
    if _qdrant_notice:
        print(f"skill-concierge enforcer: {_qdrant_notice}", file=sys.stderr)
else:
    EMBED_PORT = 6363
    QDRANT_URL = "http://localhost:6333"
EMBED_URL = f"http://{EMBED_HOST}:{EMBED_PORT}/embed"
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
# HARD embed and Qdrant caps (ADR-0054): 0.5 s / 0.25 s because the old caps were
# censoring real calls, not catching outages. Earlier cap history: ADR-0008, ADR-0054.
# Revert: ENFORCER_EMBED_TIMEOUT=0.35 ENFORCER_QDRANT_TIMEOUT=0.1.
EMBED_TIMEOUT_S = float(os.environ.get("ENFORCER_EMBED_TIMEOUT", "0.5"))
QDRANT_TIMEOUT_S = float(os.environ.get("ENFORCER_QDRANT_TIMEOUT", "0.25"))
TOP_K = int(os.environ.get("ENFORCER_TOP_K", "8"))   # offer-menu breadth (was 5; owner-widened 2026-07-05). Wider = more push-noise, against ADR-0009's noise-reduction intent — env-overridable, revert default 5.
GETAWAY_FLOOR = float(os.environ.get("ENFORCER_GETAWAY_FLOOR", "0.45"))  # top<this → silent. OPERATOR-SET 0.45 (2026-06-29, ADR-0009) raised from 0.40 on perceived behaviour; the ledger/corpus analysis argued AGAINST it (taken offers score LOWER than dodged, so a higher floor cuts the better-converting offers first). Do NOT change without re-opening ADR-0009 (data-backed alternative: 0.40 / env ENFORCER_GETAWAY_FLOOR).
ITEM_FLOOR = float(os.environ.get("ENFORCER_ITEM_FLOOR", "0.18"))       # per-candidate cutoff

# ── external catalog annex (ADR-0032) ─────────────────────────────────────────
# External catalog skills (tier=external) are appended as a marked annex, consumed via
# get_skill; the installed top-k is never displaced. The floor sits above ITEM_FLOOR so
# externals annex only on a strong match (ADR-0047: 0.40 → 0.32). ENFORCER_EXTERNAL_OFFER
# stays an alias. Revert: ENFORCER_EXTERNAL_ANNEX=0 (ADR-0031 search-only),
# ENFORCER_EXTERNAL_FLOOR=0.40.
EXTERNAL_ANNEX = os.environ.get(
    "ENFORCER_EXTERNAL_ANNEX",
    os.environ.get("ENFORCER_EXTERNAL_OFFER", "1")) != "0"
EXTERNAL_FLOOR = float(os.environ.get("ENFORCER_EXTERNAL_FLOOR", "0.32"))

# ── dynamic annex sizing (ADR-0036) ───────────────────────────────────────────
# An annex row needs >= max(pool floor, top_installed - ANNEX_MARGIN), capped at the pool's
# slot cap, so annex width tracks how well the installed shelf serves the intent; the
# installed TOP_K is never touched. Margin 0.08 (ADR-0047) sits under the measured 0.10
# saturation point. Revert: ENFORCER_ANNEX_MARGIN=0.05; ENFORCER_ANNEX_DYNAMIC=0 restores
# fixed sizing and the EXTERNAL_SLOTS default of 2.
ANNEX_DYNAMIC = os.environ.get("ENFORCER_ANNEX_DYNAMIC", "1") != "0"
ANNEX_MARGIN = float(os.environ.get("ENFORCER_ANNEX_MARGIN", "0.08"))
EXTERNAL_SLOTS = int(os.environ.get("ENFORCER_EXTERNAL_SLOTS", "4" if ANNEX_DYNAMIC else "2"))

# ── complement annex (ADR-0048) ────────────────────────────────────────────────
# The external annex complements the installed shelf instead of echoing it: when the
# installed top clears GETAWAY_FLOOR an external must beat it by ANNEX_BEAT, else the plain
# EXTERNAL_FLOOR applies. Externals with get_skill takes (auto_promote.py digest) sort first.
# Revert: ENFORCER_ANNEX_COMPLEMENT=0 (the ADR-0047 margin rule; ANNEX_MARGIN still governs
# the foreign annex).
ANNEX_COMPLEMENT = os.environ.get("ENFORCER_ANNEX_COMPLEMENT", "1") != "0"
ANNEX_BEAT = float(os.environ.get("ENFORCER_ANNEX_BEAT", "0.04"))
_TAKES_DIGEST_PATH = Path(os.environ.get(
    "SKILL_CONCIERGE_TAKES_DIGEST",
    Path.home() / ".claude" / "skill-concierge" / "external-takes.json"))


def _external_takes() -> dict:
    """{name: distinct-session take count} from the auto_promote digest, read live (the
    blocklist pattern: tiny file, user-session-cadence updates, fail-open when absent)."""
    try:
        data = json.loads(_TAKES_DIGEST_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, int) and v > 0}
    except (OSError, UnicodeError, ValueError):
        return {}


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
# Project isolation (v0.49.0): a project-scoped row (`<family>:<skills dir>`) from ANOTHER project
# is not invocable in this session, yet the exact-match foreign test could never catch it — the
# scope carries a path. Live case: from an unrelated cwd the Claude offer listed skills that exist
# only in one other project's .claude/skills. `=0` restores the pre-0.49.0 behaviour (project rows
# pass unless their exact scope string is in FOREIGN_SCOPES, which it never is).
PROJECT_ISOLATION = os.environ.get("ENFORCER_PROJECT_ISOLATION", "1") != "0"
# ADR-0052 per-session enablement gate: in Claude sessions a `plugin`-scoped row is
# offerable only when its plugin id sits in INVOCABLE_PLUGIN_IDS (the merged
# user+project+local enabledPlugins view computed below). Discovery indexes the
# machine-wide UNION (skills_discovery._layered_plugin_exclusions), so the session
# layer owns the subtraction; this flag is that subtraction's one-var revert.
PLUGIN_GATE = os.environ.get("ENFORCER_PLUGIN_GATE", "1") != "0"
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
    """Which harness is executing this hook: one of _HARNESS_ORDER's names (harness.py)."""
    return running_harness(__file__)


RUNNING_HARNESS = _running_harness()

# Cline skill roots (ADR-0051) — the twin test's filesystem rescue set. Mirrors
# skills_discovery.CLINE_PERSONAL_ROOT / CLINE_PROJECT_ROOT; stdlib-only duplicate
# because enforcer.py must not import the engine package.
_CLINE_PERSONAL_ROOT = Path.home() / ".cline" / "data" / "settings" / "skills"
_CLINE_PROJECT_ROOT = Path.cwd() / ".cline" / "skills"
# Cline Agent Plugins (agent-plugins.org, ADR-0086): <root>/<plugin>/plugin.json + skills/<skill>/.
# Cline lists a plugin skill as `<plugin>:<skill>`, the same form as a Claude plugin row.
_CLINE_AGENT_PLUGINS = Path.home() / ".agents" / "plugins"


def _cline_agent_plugin_skill(name: str) -> bool:
    """True when `plugin:skill` is a skill of a Cline Agent Plugin installed on this machine.
    OSError -> UNKNOWN -> True (fail-to-non-blocking, the twin rule)."""
    plugin, _, skill = name.partition(":")
    if not plugin or not skill or "/" in name or ".." in name:
        return False
    try:
        root = _CLINE_AGENT_PLUGINS / plugin
        return (root / "plugin.json").is_file() and (root / "skills" / skill / "SKILL.md").is_file()
    except (OSError, ValueError):
        return True

# OpenCode skill roots (ADR-0085) — the twin test's filesystem rescue set. Mirrors
# skills_discovery.OPENCODE_PERSONAL_ROOT / OPENCODE_PROJECT_ROOT plus OpenCode's documented
# compatibility reads (~/.claude/skills, ~/.agents/skills); stdlib-only duplicate, same rule.
_OPENCODE_PERSONAL_ROOT = Path(
    os.environ.get("SKILL_OPENCODE_HOME",
                   str(Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "opencode"))
) / "skills"
_OPENCODE_PROJECT_ROOT = Path.cwd() / ".opencode" / "skills"
# skill-concierge's own OpenCode skills (adapters/opencode/install.sh), registered in opencode.json.
_OPENCODE_CONCIERGE_ROOT = _OPENCODE_PERSONAL_ROOT.parent / "skill-concierge-skills"


# The cross-harness convention root (ZCode, DSH, Cline and OpenCode read it).
_AGENTS_SKILLS = Path.home() / ".agents" / "skills"


_HARNESS_ORDER = ("claude", "codex", "commandcode", "omp", "zcode", "dsh", "cline", "opencode")


def _scope_harness(scope: str) -> str:
    """The harness whose skill roots hold a row's indexed copy, from its scope family (the part
    before any `:`): `codex-plugin` -> codex, `omp-project:<dir>` -> omp, `claude-synced` ->
    claude; `personal`/`plugin`/`project` default to claude. The same head rule as the engine's
    `server._origin_head`/`_ORIGIN_HEADS` (pinned by tests/test_foreign_scope_completeness.py) —
    a stdlib duplicate because this hook must not import the engine. Each cross-harness annex row
    is marked with ITS OWN harness from this rule; a per-harness label typed by hand drifted from
    the scope tuples and named harnesses a row did not come from."""
    head = (scope or "").split(":", 1)[0].split("-", 1)[0]
    return head if head in _HARNESS_ORDER else "claude"





def _resolves_to_claude_personal(root: Path) -> bool:
    """True iff a harness's skills `root` resolves to Claude's personal root — the
    shared-shelf layout where every `personal`-scoped skill is invocable through the
    symlink. Anything else — divergent directory, missing directory, OSError — is NOT
    positive knowledge; the caller then treats `personal` as foreign. Resolved per
    session, never baked into the machine-global index (the ADR-0028 cwd-scoped-view
    hazard)."""
    try:
        claude = Path.home() / ".claude" / "skills"
        return root.is_dir() and claude.is_dir() and root.resolve() == claude.resolve()
    except (OSError, RuntimeError):
        return False


def _agents_shares_personal_shelf() -> bool:
    """~/.agents/skills is the cross-harness convention root that ZCode, DSH and Cline all read
    (ZCode: observed live 2026-08-28; DSH: dsh-skill-filesystem `user-agents` root; Cline: its
    skills-dir list and marketplace install target). On this machine it links to
    ~/.claude/skills, so every `personal` skill is invocable there too. When it does not, per-row
    survival moves to the `_invocable_twin` filesystem check."""
    return _resolves_to_claude_personal(_AGENTS_SKILLS)


def _commandcode_shares_personal_shelf() -> bool:
    """Command Code's ~/.commandcode/skills is the shared shelf (verified live 2026-09-18:
    ~/.commandcode/skills -> ~/.claude/skills, and `commandcode -p` returned a
    personal-scope skill's real content). When it is not, Command Code cannot see
    ~/.claude/skills and `personal` stays foreign (ADR-0057)."""
    return _resolves_to_claude_personal(Path.home() / ".commandcode" / "skills")


def _foreign_scopes() -> tuple:
    """The scopes whose skills the RUNNING harness cannot invoke: every OTHER harness's
    exclusive roots (ADR-0059). The tuples below are the truth; the branch comments say why a
    harness differs, and tests/test_foreign_scope_completeness.py fails on any scope discovery
    can emit that a tuple misses. `project:` scopes are cwd-derived and never foreign.
    `claude-synced` is foreign everywhere but Claude Code: only it loads the nested
    ~/.claude/skills/synced/<bucket>/ tree. `personal` is foreign where the harness's own
    personal root does not resolve to Claude's shelf (Command Code ADR-0057, ZCode ADR-0042,
    DSH ADR-0050, Cline ADR-0051); Codex, OMP and OpenCode always treat it as invocable.
    """
    if RUNNING_HARNESS == "commandcode":
        base = ("plugin", "codex-plugin", "codex-personal",
                "omp-personal", "omp-managed", "omp-plugin",
                "zcode-personal", "zcode-plugin",
                "dsh-personal", "cline-personal", "opencode-personal", "claude-synced")
        return base if _commandcode_shares_personal_shelf() else base + ("personal",)
    if RUNNING_HARNESS == "codex":
        return ("plugin", "commandcode-personal",
                "omp-personal", "omp-managed", "omp-plugin",
                "zcode-personal", "zcode-plugin",
                "dsh-personal", "cline-personal", "opencode-personal", "claude-synced")
    if RUNNING_HARNESS == "omp":
        return ("codex-plugin", "commandcode-personal", "zcode-personal", "zcode-plugin",
                "dsh-personal", "cline-personal", "opencode-personal", "claude-synced")
    if RUNNING_HARNESS == "zcode":
        base = ("plugin", "codex-plugin", "codex-personal", "commandcode-personal",
                "omp-personal", "omp-managed", "omp-plugin",
                "dsh-personal", "cline-personal", "opencode-personal", "claude-synced")
        return base if _agents_shares_personal_shelf() else base + ("personal",)
    if RUNNING_HARNESS == "dsh":
        # DSH reads its own roots (DSH_HOME/skills, <project>/.dsh/skills) plus the
        # ~/.agents/skills + <project>/.agents/skills convention roots (dsh-skill-filesystem
        # `roots()`). Every other harness scope is foreign — `personal` too, unless
        # ~/.agents/skills IS Claude's personal shelf (then every personal skill is invocable).
        base = ("plugin", "codex-personal", "codex-plugin",
                "commandcode-personal",
                "omp-personal", "omp-managed", "omp-plugin",
                "zcode-personal", "zcode-plugin", "cline-personal",
                "opencode-personal", "claude-synced")
        return base if _agents_shares_personal_shelf() else base + ("personal",)
    if RUNNING_HARNESS == "cline":
        # Cline (ADR-0051) reads ~/.cline/data/settings/skills and <cwd>/.cline/skills, and —
        # found in the installed binary for v0.49.0 — ~/.agents/skills (its skills-dir list and
        # marketplace install target). It reads NO plugin cache and no other harness's roots;
        # `personal` is foreign unless ~/.agents/skills IS Claude's personal shelf.
        base = ("plugin", "codex-personal", "codex-plugin",
                "commandcode-personal",
                "omp-personal", "omp-managed", "omp-plugin",
                "zcode-personal", "zcode-plugin", "dsh-personal",
                "opencode-personal", "claude-synced")
        return base if _agents_shares_personal_shelf() else base + ("personal",)
    if RUNNING_HARNESS == "opencode":
        # OpenCode v2 (ADR-0085) reads ~/.config/opencode/skills, <cwd>/.opencode/skills, and —
        # documented compatibility sources — ~/.claude/skills, ~/.agents/skills and their
        # project twins, so `personal` is invocable by CONSTRUCTION here (the docs table, not a
        # symlink guess: no shared-shelf condition applies). It reads NO plugin cache and no
        # other harness's exclusive roots; claude-synced stays Claude-Code-only (the nested
        # bucket is invisible to OpenCode's one-level compat scan too).
        return ("plugin", "codex-personal", "codex-plugin",
                "commandcode-personal",
                "omp-personal", "omp-managed", "omp-plugin",
                "zcode-personal", "zcode-plugin", "dsh-personal", "cline-personal",
                "claude-synced")
    return ("codex-plugin", "codex-personal", "commandcode-personal",
            "omp-personal", "omp-managed", "omp-plugin",
            "zcode-personal", "zcode-plugin",
            "dsh-personal", "cline-personal", "opencode-personal")

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
# The USER settings layer, behind the same env seam the engine honours
# (skills_discovery.CLAUDE_SETTINGS_JSON) so the hook and the server read one file.
_CLAUDE_SETTINGS_JSON = Path(os.environ.get(
    "SKILL_CLAUDE_SETTINGS", Path.home() / ".claude" / "settings.json"))

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
    enabled, matching Claude Code; the INDEX side computes the machine-wide union via
    `skills_discovery._layered_plugin_exclusions`, ADR-0052 — this merged per-cwd view is
    what `_plugin_gate_ok` subtracts). Under OMP the
    claude-plugins provider reads the SAME claude registry PLUS the OMP registry
    (`~/.omp/plugins/installed_plugins.json`) — OMP entries are authoritative for their plugin id
    (OMP source discovery/helpers.ts:1030-1078) — and BOTH registries' keys pass through the
    SAME merged settings-layer `enabledPlugins` view plus the per-entry `enabled` field
    (`enabled === false` hides the plugin; absent = enabled), mirroring OMP's provider, which
    honors claude enabledPlugins overrides AND entry.enabled === false (helpers.ts:1088-1118,
    1186, 1191-1192). This set is what `_plugin_gate_ok` subtracts under BOTH harnesses
    (ADR-0052 + ADR-0053).

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
    if RUNNING_HARNESS == "dsh":
        # DSH has no plugin registry (it uses Cordis plugins, not a skill plugin
        # manifest). Return None so the twin test filters nothing — every foreign
        # row with a plausible name survives until _invocable_twin resolves it
        # filesystem-side.
        return None
    if RUNNING_HARNESS == "cline":
        # Cline has no skill plugin registry either (ADR-0051: its code plugins
        # contribute rules/commands/mcpServers/hooks/tools — never skills; Agent Plugin
        # skills, ADR-0086, are found on disk by _cline_agent_plugin_skill).
        # Same None-means-UNKNOWN contract as DSH; the filesystem twin settles it.
        return None
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
    if RUNNING_HARNESS == "omp":
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
        layers = (_CLAUDE_SETTINGS_JSON,
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


_ZCODE_READ_ROOTS = (_AGENTS_SKILLS, Path.home() / ".zcode" / "skills")

# DSH home for filesystem twin checks (ADR-0050). Mirrors skills_discovery.py:
# explicit SKILL_DSH_HOME > DSH_HOME env > ~/.ohdsh (preferred, Oh-DSH Desktop)
# > ~/.dsh (legacy fallback). Resolved once at import, zero network.
_DSH_HOME_RAW = os.environ.get("SKILL_DSH_HOME") or os.environ.get("DSH_HOME")
_DSH_HOME = Path(_DSH_HOME_RAW) if _DSH_HOME_RAW else (
    Path.home() / ".ohdsh" if (Path.home() / ".ohdsh").is_dir() else Path.home() / ".dsh")


def _zcode_readable_skill(name: str) -> bool:
    """ADR-0042 filesystem twin: True when `<name>/SKILL.md` exists in a ZCode-readable
    personal root (~/.agents/skills — the shared shelf — or ~/.zcode/skills). This is how
    a `personal`-scoped row survives the foreign filter on machines where the two shelves
    are NOT one symlinked directory, and how un-namespaced foreign rows with a real local
    twin stay offerable."""
    return _has_skill_md(name, _ZCODE_READ_ROOTS)


def _has_skill_md(name: str, roots) -> bool:
    """True when `<root>/<name>/SKILL.md` exists under any of `roots`. OSError is UNKNOWN —
    returns True so the caller's drop-only-on-positive-knowledge rule keeps the row."""
    try:
        return any((root / name / "SKILL.md").exists() for root in roots)
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
    if RUNNING_HARNESS == "dsh":
        # DSH has no plugin registry; a foreign-scoped row survives here only through a
        # filesystem twin — the name exists as a directory under DSH_HOME/skills/
        # (the DSH personal skill root) or ~/.agents/skills.
        return _has_skill_md(name, (_DSH_HOME / "skills", _AGENTS_SKILLS))
    if RUNNING_HARNESS == "cline":
        # Cline has no skill-plugin registry (ADR-0051); a foreign-scoped row survives only
        # through a filesystem twin: a namespaced row in an installed Agent Plugin (ADR-0086),
        # a plain row in one of Cline's skill roots.
        if ":" in name:
            return _cline_agent_plugin_skill(name)
        return _has_skill_md(name, (_CLINE_PERSONAL_ROOT, _CLINE_PROJECT_ROOT, _AGENTS_SKILLS))
    if RUNNING_HARNESS == "opencode":
        # OpenCode v2 (ADR-0085) has no plugin registry; a foreign-scoped row survives only
        # through a filesystem twin in OpenCode's own roots or one of its documented
        # compatibility roots (~/.claude/skills, ~/.agents/skills).
        return _has_skill_md(name, (_OPENCODE_PERSONAL_ROOT, _OPENCODE_PROJECT_ROOT,
                                    _OPENCODE_CONCIERGE_ROOT,
                                    Path.home() / ".claude" / "skills", _AGENTS_SKILLS))
    if RUNNING_HARNESS not in ("claude", "omp") or not INVOCABLE_PLUGIN_IDS or ":" not in name:
        return False
    return name.split(":", 1)[0] in INVOCABLE_PLUGIN_IDS


_SYNCED_SIDECAR_CACHE: dict = {}


def _synced_sidecar_names() -> set:
    """Names in the chain sidecar's `claude-synced` bucket — how a hint or ROUTE candidate,
    which carries no payload scope, is recognised as an account-synced skill. Read once per
    sidecar path per hook process. Fail-open to an empty set."""
    key = str(_SIDECAR_PATH)
    if key not in _SYNCED_SIDECAR_CACHE:
        try:
            data = json.loads(_SIDECAR_PATH.read_text(encoding="utf-8"))
            bucket = data.get("claude-synced") if isinstance(data, dict) else None
            _SYNCED_SIDECAR_CACHE[key] = set(bucket) if isinstance(bucket, dict) else set()
        except (OSError, UnicodeError, ValueError):
            _SYNCED_SIDECAR_CACHE[key] = set()
    return _SYNCED_SIDECAR_CACHE[key]


def _plugin_gate_ok(name: str, scope: str | None = None) -> bool:
    """ADR-0052 + ADR-0053: True when THIS session may act on `name`. Discovery indexes the
    machine-wide union of enablement layers, so a `plugin:skill` row can name a plugin this
    session switched off. INVOCABLE_PLUGIN_IDS None (unreadable manifest = UNKNOWN) filters
    nothing, the ADR-0034 contract. Revert: ENFORCER_PLUGIN_GATE=0."""
    if not PLUGIN_GATE:
        return True
    # Account-synced skills are not plugins: Claude Code alone loads them, and they pass on
    # their SCOPE, never on the `anthropic-skills:` name, which any plugin could carry.
    if scope == "claude-synced":
        return RUNNING_HARNESS == "claude"
    if (scope is None and RUNNING_HARNESS == "claude"
            and name.startswith("anthropic-skills:") and name in _synced_sidecar_names()):
        return True
    if RUNNING_HARNESS in ("claude", "omp"):
        if INVOCABLE_PLUGIN_IDS is None or ":" not in name:
            return True
        return name.split(":", 1)[0] in INVOCABLE_PLUGIN_IDS
    if RUNNING_HARNESS == "cline":
        return ":" not in name or _cline_agent_plugin_skill(name)
    if RUNNING_HARNESS in ("dsh", "opencode"):
        return ":" not in name   # no skill-plugin registry (ADR-0050/0085)
    return True   # Codex, Command Code, ZCode: the foreign-scope/twin filter settles their rows
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
# via search_skills). Proposed by scripts/build_keep_off.py, saved only with Thinh's consent
# (ADR-0077: nothing builds or refreshes it automatically). FAIL-OPEN:
# missing/empty/bad file -> empty set -> no suppression. ADR-0054: the generated map lives in
# the canonical durable home (~/.claude/skill-concierge/keep-off.json — the keep-on/blocklist
# pattern) so a plugin update cannot wipe it; the shipped config/keep-off.json is the empty
# seed read only when no durable copy exists.
_KEEPOFF_DURABLE = Path.home() / ".claude" / "skill-concierge" / "keep-off.json"


def _keepoff_path() -> Path:
    override = os.environ.get("SKILL_CONCIERGE_KEEPOFF")
    if override:
        return Path(override)
    try:
        if _KEEPOFF_DURABLE.exists():
            return _KEEPOFF_DURABLE
    except OSError:
        pass
    return Path(__file__).resolve().parents[2] / "config" / "keep-off.json"


_KEEPOFF_PATH = _keepoff_path()


def _load_keepoff() -> frozenset:
    """ADR-0077: a map hides skills only when Thinh approved it (`approved_by_user: true`, written
    by `build_keep_off.py --apply` after his yes). An auto-built or unmarked map hides nothing."""
    try:
        data = json.loads(_KEEPOFF_PATH.read_text(encoding="utf-8"))
        if data.get("approved_by_user") is not True:
            return frozenset()
        return frozenset(n for n in data.get("keep_off", []) if isinstance(n, str))
    except (OSError, UnicodeError, ValueError, AttributeError, TypeError):
        return frozenset()  # fail-open: suppression-config must never break a turn


KEEPOFF = _load_keepoff()


def _drop_keepoff(cands: list, keepoff: frozenset):
    """Split retrieved cands into (survivors, dropped-names) by the keep-off set. Pure +
    order-preserving."""
    survivors = [c for c in cands if c[0] not in keepoff]
    dropped = [c[0] for c in cands if c[0] in keepoff]
    return survivors, dropped


# ── ADR-0046: user-ordered blocklist (disable tier) ──────────────────────
# The inverse of keep-on: skills the USER ordered off — never offered, never hinted,
# never routed to. Unlike keep-off (mined, offer-menu-only, still catalogue-reachable),
# the blocklist removes the skill from every concierge surface; invocation itself is
# denied by the PreToolUse guard (hooks/scripts/skill_guard.py), the layer that also
# catches command-files surfaced as skills (ADR-0001 keeps those out of the index, so
# no retrieval-side filter can ever see them). Name semantics, shared with the guard
# and the engine: a BARE entry blocks every qualified twin (`origin:name`); a qualified
# entry blocks only itself. FAIL-OPEN like every suppression config here.
# SKILL_BLOCKLIST=0 is the one-var kill-switch (guard passes, this filter no-ops,
# engine filter no-ops). SKILL_CONCIERGE_BLOCKLIST is the exact-file test seam.
_BLOCKLIST_PATH = Path(os.environ.get(
    "SKILL_CONCIERGE_BLOCKLIST",
    Path.home() / ".claude" / "skill-concierge" / "blocklist.json"))


def _load_blocklist() -> frozenset:
    if os.environ.get("SKILL_BLOCKLIST", "1") == "0":
        return frozenset()
    try:
        data = json.loads(_BLOCKLIST_PATH.read_text(encoding="utf-8"))
        lst = data.get("blocked", []) if isinstance(data, dict) else []
        if not isinstance(lst, list):
            return frozenset()  # wrong-typed value = total fail-open, not char-iterated noise
        return frozenset(n for n in lst if isinstance(n, str))
    except (OSError, UnicodeError, ValueError, AttributeError, TypeError):
        return frozenset()  # fail-open: the disable list must never break a turn


BLOCKLIST = _load_blocklist()


def _blocked(name: str) -> bool:
    """Exact entry match, or a BARE entry catching every qualified twin."""
    if not BLOCKLIST:
        return False
    if name in BLOCKLIST:
        return True
    return ":" in name and name.rsplit(":", 1)[1] in BLOCKLIST


def _drop_blocklisted(cands: list):
    """(survivors, dropped-names) by the blocklist. Pure + order-preserving, same
    contract as _drop_keepoff so the offer event's `dropped` field stays honest."""
    survivors = [c for c in cands if not _blocked(c[0])]
    dropped = [c[0] for c in cands if _blocked(c[0])]
    return survivors, dropped


# ── ADR-0083: owner reputation badges ─────────────────────────────────────────
# The owner's own ranking, rendered NEXT TO a menu row and never reordering it: the
# 2026-10-07 replay put tier-first ordering at 37 of 313 "used skill ranked first" against
# 100 for Jev's order. ❤️ house favourite / ⭐ trusted come from reputation.json
# ({"heart": [...], "star": [...]}; exact names or fnmatch family patterns such as
# `pstack:*`). An exact entry beats every pattern; between two matches of one kind, ❤️ wins.
# 🔥 proven = invoked in enough distinct sessions lately, digest written by auto_promote.py.
# Badges render on installed and pulled rows only: an external-catalogue or other-harness row is not
# the owner's installed skill (and `*:*` would otherwise match `antigravity:` and `vercel:` rows).
# The menu's legend line tells the agent how to choose with them. Read per turn (one hook process per
# turn), fail-open: an absent or malformed file shows no badge. SKILL_REPUTATION=0 turns every
# badge off; SKILL_CONCIERGE_REPUTATION / SKILL_CONCIERGE_PROVEN are the exact-file seams.
REPUTATION_ON = os.environ.get("SKILL_REPUTATION", "1") != "0"
_REPUTATION_PATH = Path(os.environ.get(
    "SKILL_CONCIERGE_REPUTATION",
    Path.home() / ".claude" / "skill-concierge" / "reputation.json"))
_PROVEN_PATH = Path(os.environ.get(
    "SKILL_CONCIERGE_PROVEN",
    Path.home() / ".claude" / "skill-concierge" / "proven.json"))
_TIERS = (("heart", "❤️"), ("star", "⭐"))
BADGE_LEGEND = ("Badges are the owner's ranking: ❤️ house favourite, ⭐ trusted, 🔥 used often here. "
                "Choose in two passes: mark every row (owner's list included) that does this task's job as "
                "its main purpose; among those take ❤️ first, then ⭐, then the rest, and inside each group "
                "prefer 🔥, then the higher row. The job qualifies a row; the badge picks among rows that "
                "qualify.\n")
# Only 🔥 on the menu (it is automatic, so this is the common case): the short form, not the owner rule.
PROVEN_LEGEND = ("🔥 = used often here: among rows that do this task's job as their main purpose, prefer 🔥, "
                 "then the higher row.\n")


def _load_reputation() -> dict:
    """{"heart": (...), "star": (...)} of non-empty string entries; fail-open to empty."""
    empty = {"heart": (), "star": ()}
    if not REPUTATION_ON:
        return empty
    try:
        data = json.loads(_REPUTATION_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return empty
    if not isinstance(data, dict):
        return empty
    out = {}
    for tier, _mark in _TIERS:
        lst = data.get(tier, [])
        out[tier] = tuple(n.strip() for n in lst if isinstance(n, str) and n.strip()) \
            if isinstance(lst, list) else ()
    return out


def _load_proven() -> frozenset:
    if not REPUTATION_ON:
        return frozenset()
    try:
        data = json.loads(_PROVEN_PATH.read_text(encoding="utf-8"))
        names = data.get("proven", []) if isinstance(data, dict) else []
        return frozenset(n for n in names if isinstance(n, str)) if isinstance(names, list) else frozenset()
    except (OSError, UnicodeError, ValueError):
        return frozenset()


REPUTATION = _load_reputation()
PROVEN = _load_proven()


def _is_pattern(entry: str) -> bool:
    return any(ch in entry for ch in "*?[")


def _owner_tier(name: str) -> str | None:
    """'heart' | 'star' | None. Exact entries first (either tier), then patterns."""
    import fnmatch
    rep = REPUTATION
    for tier, _mark in _TIERS:
        if name in rep.get(tier, ()):
            return tier
    for tier, _mark in _TIERS:
        for p in rep.get(tier, ()):
            try:
                if _is_pattern(p) and fnmatch.fnmatchcase(name, p):
                    return tier
            except re.error:
                continue      # a malformed pattern (`[z-a]*`) matches nothing, never breaks the turn
    return None


def _badge(name: str) -> str:
    """The marks rendered after a row's name: ' ❤️', ' ⭐🔥', ' 🔥', or ''."""
    tier = _owner_tier(name)
    mark = (dict(_TIERS).get(tier, "") if tier else "") + ("🔥" if name in PROVEN else "")
    return f" {mark}" if mark else ""


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
    if os.environ.get("SKILL_COMMANDCODE_ROOTS", "1") != "0":  # ADR-0038 commandcode mirror
        scopes += ["commandcode-personal"]
        if cwd is not None:
            scopes.append(f"commandcode-project:{cwd / '.commandcode' / 'skills'}")
    if os.environ.get("SKILL_OMP_ROOTS", "1") != "0":  # ADR-0039 omp mirror
        scopes += ["omp-personal", "omp-managed", "omp-plugin"]
        if cwd is not None:
            scopes.append(f"omp-project:{cwd / '.omp' / 'skills'}")
    if RUNNING_HARNESS == "claude":   # account-synced skills chain only where Claude Code loads them
        scopes.append("claude-synced")
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
    if _blocked(seed):        # ADR-0046: a disabled skill leaves no trace in offers
        return []
    names_map = _visible_sidecar_names()
    succ = names_map.get(seed)
    if not isinstance(succ, list) or not succ:
        return []
    shown = [n for n in succ
             if isinstance(n, str) and n and n in names_map and n not in KEEPOFF
             and not _blocked(n) and _plugin_gate_ok(n)]
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


# ── deterministic route overrides (config-driven, default ON since ADR-0054) ──────
# A tiny, high-precision whole-word phrase -> skill map for intents where semantic ranking is
# unreliable but the intent is unambiguous — above all a prompt that NAMES the skill
# ("/unlazy", "cook --auto", "progress-map"): 11 such prompts in the v0.46.0 epoch were
# missed by the preview. GUARANTEES the mapped skill leads the menu (score 1.0, retrieved
# twin dropped) — additive, never blocks, and a hit bypasses getaway + the actionability
# gate. Pure (no I/O), so it runs BEFORE the embed step and survives a shim/Qdrant timeout.
# DEFAULT ON: loaded from config/deterministic-routes.json; ENFORCER_DETERMINISTIC=0
# disables; missing/empty config -> no-op. CURATE SPARINGLY — this system's dodge is
# dominated by FALSE offers, so every route must be near-zero false-positive: a literal
# skill name, its slash form, or an alias replayed from a ledger miss. Format:
# {"routes":[{"contains":"<lowercased phrase>","skill":"<exact name>"}]}.
# WHOLE-WORD match: a route whose text starts or ends in a name character (ASCII letter, digit,
# `_`, `-`) must not continue into a longer word on that side — `/cook` pinned ak-cook three times
# from `docs.typesafe.ai/cookbooks` URLs (ledger, 2026-09-26). ASCII-only on purpose: route texts
# are ASCII skill names, and a route written between CJK characters (no spaces) must still fire.
# Replayed on the ledger's 120-char prompt heads the boundary drops only those three plus one
# `cook --auto` inside `/ak-cook --auto`, which the `ak-cook` route still catches.
_ROUTES_PATH = Path(os.environ.get(
    "SKILL_CONCIERGE_ROUTES",
    Path(__file__).resolve().parents[2] / "config" / "deterministic-routes.json"))


def _load_routes() -> list:
    if os.environ.get("ENFORCER_DETERMINISTIC", "1").strip() == "0":
        return []  # kill-switch
    try:
        data = json.loads(_ROUTES_PATH.read_text(encoding="utf-8"))
        return [(r["contains"].lower(), r["skill"]) for r in data.get("routes", [])
                if isinstance(r.get("contains"), str) and isinstance(r.get("skill"), str)
                and r["contains"].strip()]
    except (OSError, UnicodeError, ValueError, TypeError, AttributeError, KeyError):
        return []  # fail-open


_ROUTES = _load_routes()
_NAME_CHAR = re.compile(r"[\w-]", re.ASCII)


def _route_matches(sub: str, low: str) -> bool:
    """`sub` occurs in `low` as a whole word: no name character continues it on a side where
    `sub` itself begins or ends with one."""
    pat = re.escape(sub)
    if _NAME_CHAR.match(sub[0]):
        pat = r"(?<![\w-])" + pat
    if _NAME_CHAR.match(sub[-1]):
        pat += r"(?![\w-])"
    return re.search(pat, low, re.ASCII) is not None


def _route_hits(prompt: str, keepoff: frozenset = frozenset()) -> list:
    """Every configured route whose text is in the lowercased prompt as a whole word, as
    [(name, desc, 1.0)] in first-match order, de-duped. Pure (no I/O) so it runs before the
    embed step. NEVER resurfaces a keep-off'd (ADR-0011) or blocklisted (ADR-0046) skill —
    suppression outranks a route, else a co-configured route silently bypasses it. Inert
    when _ROUTES is empty."""
    if not _ROUTES:
        return []
    low = prompt.lower()
    out, seen = [], set()
    # ADR-0034 invariant: the offer holds only skills THIS harness can invoke. Every seeded
    # route names a bare personal-root skill; where `personal` is foreign a route may pin only
    # what the filesystem twin test rescues (DSH, Cline, divergent ZCode). Command Code has no
    # twin rescue, so on a divergent shelf a bare personal route goes inert (ADR-0057).
    personal_foreign = "personal" in FOREIGN_SCOPES
    for sub, skill in _ROUTES:
        if skill in seen or skill in keepoff or _blocked(skill) or not _route_matches(sub, low):
            continue
        if personal_foreign and ":" not in skill and not _invocable_twin(skill):
            continue
        out.append((skill, "named in the prompt — deterministic route", 1.0))
        seen.add(skill)
    return out


def _merge_route_hits(hits: list, cands: list) -> list:
    """Prepend route hits to the retrieved candidates so a NAMED skill leads at score 1.0 even
    when retrieval also found it further down (the preview shows only the top rows). A
    retrieved twin donates its real description and is dropped from the tail, so the menu
    never lists a skill twice. Order-preserving; a no-hit turn returns `cands` untouched."""
    if not hits:
        return cands
    desc = {n: d for (n, d, _s) in cands}
    names = {n for (n, _d, _s) in hits}
    return ([(n, desc.get(n, d), s) for (n, d, s) in hits]
            + [c for c in cands if c[0] not in names])


# Per-turn GATE TRIGGER — the cheap re-assert. The full SKILL-FIRST standing order
# is injected once at SessionStart (doctrine.py); this keeps it live in attention
# every turn without re-paying the rich version. Pre-commitment, not persuasion: it
# forces a line-1 token and turns "the few don't fit" into an order to SEARCH, never
# a skip. In-generation only — no post-turn detection.
MANDATE = (
    "SKILL-FIRST · reply line 1 = USING: <skill> | SEARCH: <query> | NO SKILL: <why>.\n"
    "No preview this turn. A task turn → run search_skills THIS reply with 2–3 intent+domain "
    "phrasings, then USING the fit, or NO SKILL: <why> only when that search finds nothing "
    "adaptable (query shown). [full order: session start]"
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


def _append_offer(sid: str, band: str, offered: list, fallback, q: str, **kw) -> None:
    """Append the offer event built by `_offer_ev`. Fail-silent: telemetry must never surface.
    ENFORCER_LEDGER=0 writes no row. ENFORCER_LEDGER=defer writes none either: the row goes back
    to the caller in the hook output (`skillConciergeOffer`), because the Cline plugin (ADR-0086)
    runs two passes per turn and only it knows which menu the model saw (ADR-0087)."""
    if os.environ.get("ENFORCER_LEDGER", "1") == "0":
        return
    try:
        ev = _offer_ev(sid, band, offered, fallback, q, **kw)
        if os.environ.get("ENFORCER_LEDGER") == "defer":
            _DEFERRED["skillConciergeOffer"] = ev
            return
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with LEDGER.open("a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    except (OSError, UnicodeError, ValueError, TypeError, OverflowError):
        return


def _offer_ev(sid: str, band: str, offered: list, fallback, q: str, dropped=None, embed_ms=None, qdrant_ms=None, ext=None, xh=None, n_intents=None, route=None, hint=None, pulled=None) -> dict:
    """Build the offer event that `_append_offer` writes (or, under ENFORCER_LEDGER=defer, hands back).
    ADR-0032: `ext` records the external annex names offered this turn (external offer→take
    is measured against the ADR-0031 get_skill takes); absent when no external annexed.
    ADR-0034: `xh` records the cross-harness annex the same way; absent when none annexed.
    ADR-0041: `n_intents` / `route` record the intent-cluster count and projected route
    rendered this turn (absent when 1 intent / no route) — the seed of the L4
    continuation-rate metric; additive keys, old analyzers ignore them.
    EPOCH NOTE: ADR-0034 changes what `offered` contains, so any offer-composition rate
    measured across the v0.25.0 boundary pools two different configs — window it.
    """
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
    if pulled:
        ev["pulled"] = pulled    # ADR-0083: owner-badged rows appended under Jev's rows
    # ADR-0083: the badges this turn showed, so a take of a badged row below row 1 is countable
    if band == "offer":    # a skip leg shows no menu, so it shows no badge
        _names = [r[0] if isinstance(r, (list, tuple)) else r
                  for grp in (offered, pulled) if isinstance(grp, list) for r in grp]
        badges = {n: b.strip() for n in _names if isinstance(n, str) and (b := _badge(n))}
        if badges:
            ev["badges"] = badges
    if embed_ms is not None:
        ev["embed_ms"] = int(embed_ms)
    if qdrant_ms is not None:
        ev["qdrant_ms"] = int(qdrant_ms)
    if _JEV_EVENT:
        ev["jev"] = _JEV_EVENT    # ADR-0061: routing telemetry (or error) on every row after an attempted route
    return ev


# ENFORCER_LEDGER=defer: the hook output and the offer row leave as ONE JSON object at exit.
_DEFERRED: dict = {}


def _inject(text: str) -> None:
    out = {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": text}}
    if os.environ.get("ENFORCER_LEDGER") == "defer":
        _DEFERRED.update(out)
        return
    sys.stdout.write(json.dumps(out))


# Authorization lines for the silent verdict legs (see AUTHORIZED_SKIP above). Burden of
# proof stays on SKIP: the getaway leg can't tell trivial from real-but-low-scoring, so it
# pushes ambiguous/real work back to a term-rich search_skills call rather than blessing the
# skip outright (the raw prompt is what just scored below the floor).
GETAWAY_SKIP_MSG = (
    AUTHORIZED_SKIP_MARKER + " full-catalogue retrieval ran (top {top:.2f} < floor {floor:.2f}); "
    "nothing cleared the floor. NO SKILL: hook-cleared is pre-authorized ONLY if this turn is genuinely "
    "non-task or conversational. Real or ambiguous work → SEARCH: run search_skills with 2–3 intent+domain "
    "phrasings (the raw prompt is what scored below the floor); burden of proof is on SKIP. If a "
    "hit's fit is unclear from its description, get_skill(<name>) before ruling."
)
INTENT_SKIP_MSG = (
    AUTHORIZED_SKIP_MARKER + " the intent-margin classifier judged this turn conversational/"
    "non-task. NO SKILL: hook-cleared is pre-authorized; no search_skills needed. If the turn does hand "
    "you work, that is the task: route it (SEARCH/USING)."
)
# H5 (ADR-0019): the 3rd AUTHORIZED-SKIP leg. Its signature phrase "self-referential recap lane" is
# a LOCKED cross-file contract — the audit (audit_skill_usage.py `_is_authorized_skip_line`) matches this exact
# substring to count the lane as an authorized-skip, NOT a false-skip. It is prose-unlikely and MUST
# NOT appear in the skill-first.md doctrine table, else a collision miscounts real dodges as authorized.
SELFREF_SKIP_MSG = (
    AUTHORIZED_SKIP_MARKER + " this turn only asks you to explain/rephrase your own "
    "immediately-prior message — the self-referential recap lane — with no external task, so no "
    "skill applies. NO SKILL: hook-cleared is pre-authorized; no search_skills needed. Any task tail "
    "beyond the recap is a task: route it (SEARCH/USING)."
)


# ADR-0054: the 4th AUTHORIZED-SKIP leg — harness-generated prompts. In the v0.46.0 epoch
# 344 of 581 enforcer decisions were on text no user typed (task notifications, monitor
# events, cross-session/teammate messages, idle reminders, OMP summarizer calls) and 168 of
# them got a full preview; 7 incidental takes followed. Its signature phrase
# "harness-message lane" is a LOCKED cross-file contract with the audit script
# (_AUTHORIZED_SIGNATURES) — same rule as the selfref leg above.
HARNESS_SKIP = os.environ.get("ENFORCER_HARNESS_SKIP", "1") != "0"
# Shapes with LEDGER evidence at the prompt head (whole ledger, 2026-09-15): <task-notification>
# 1,700 · OMP omp-msum 1,546 · <system-reminder> 36 · <cross-session-message 20. The remaining
# alternations are TRANSCRIPT-evidenced only (user records in ~/.claude/projects/**/*.jsonl:
# teammate messages, "Another Claude session sent…", interrupted/continued banners, "[SYSTEM
# NOTIFICATION"); the hook has never seen them at the head, so they are inert until the W1
# replay does. Slash commands reach the hook raw ("/name …", pre-gated) — no <command-name> form.
# Mirrored in scripts/build_keep_off.py (tests/test_harness_regex_parity.py pins equality).
_HARNESS_MSG_RE = re.compile(
    r"^\s*(?:<task-notification>|<system-reminder>|<cross-session-message\b|<teammate-message\b"
    r"|Another Claude session sent a message|\[Request interrupted by user"
    r"|\[SYSTEM NOTIFICATION\b|\[Cross-session idle notice\]"
    r"|This session is being continued from a previous conversation"
    r"|<file name=\"[^\"\n]*omp-msum-[^\"\n]*\">"
    # Cline on its claude-code provider runs Claude Code underneath; that inner session's
    # UserPromptSubmit carries Cline's whole system prompt, which the Cline plugin already
    # governs at the real prompt (ADR-0086).
    r"|You are Cline, an AI coding agent\b)")
HARNESS_SKIP_MSG = (
    AUTHORIZED_SKIP_MARKER + " this prompt is harness-generated, not a user task — the "
    "harness-message lane. NO SKILL: hook-cleared is pre-authorized; no search_skills needed. If the "
    "message itself hands you work to do, that is the task: route it (SEARCH/USING)."
)


# ADR-0061: the Jev skill router (supersedes ADR-0060's yes/no leg, whose 0.25 threshold rested on
# 22 hand-picked prompts and, replayed on real traffic, skipped 48 % of turns where the agent
# really used a skill). For an English prompt, Jev ranks the WHOLE invocable catalogue in one
# request (TypeSafe's skill-suggestion recipe: chunked Choice questions), re-checks the shortlist
# with one `fits` Noul per candidate, and offers its top 5 in the rerank Choice's order. Every
# number below is measured on real outcomes (turns where agents actually used a skill) by
# scripts/calibrate_jev_gate.py — never on a hand-written tuning set:
#   - the used skill is in Jev's offer 177/237 (75 %) vs 86/237 (36 %) for the 8-row embedding menu;
#   - best `fits` < 0.30 (vendor default; the holdout fit picked 0.34): 1/313 false NO, 1/105 on the
#     Sept holdout, 2 % of traffic skipped;
#   - a single confident lead (Choice confidence >= 0.70/0.90/0.95) LOWERED that recall to 62-65 %
#     (the lead was wrong 29 times in 73), so the offer is never collapsed to one row.
# English only (owner order 2026-09-26; Jev's primary training language is English): any other
# prompt, a missing key, or any Jev failure leaves the embedding path to decide, unchanged. A
# named deterministic route never asks Jev. The locked signature "Jev needs-a-skill gate" (audit
# _AUTHORIZED_SIGNATURES) now names the "no candidate fits" skip. `ENFORCER_JEV_ROUTER=0` — or the
# ADR-0060 `ENFORCER_JEV_GATE=0` — restores the pre-v0.50.0 embedding-only path byte-identically.
JEV_ROUTER = (os.environ.get("ENFORCER_JEV_ROUTER", "1") != "0"
              and os.environ.get("ENFORCER_JEV_GATE", "1") != "0")
JEV_URL = os.environ.get("ENFORCER_JEV_URL", "https://api.typesafe.ai/v1/systemone")
# The warm-connection relay in the local index owner. The key rides that request in clear text, so the relay
# is used only over loopback; any other shim host means direct HTTPS calls. The relay forwards to TypeSafe
# only, so another SystemOne endpoint (the owner's gateway, ADR-0075) is always called directly.
JEV_RELAY_URL = (f"http://{EMBED_HOST}:{EMBED_PORT}/jev"
                 if EMBED_HOST in ("127.0.0.1", "localhost", "::1")
                 and (urllib.parse.urlsplit(JEV_URL).hostname or "").lower() == "api.typesafe.ai" else None)
JEV_MODEL = os.environ.get("ENFORCER_JEV_MODEL", "jev-1.13.0")   # pinned: jev-latest drifts
JEV_TIMEOUT_S = float(os.environ.get("ENFORCER_JEV_TIMEOUT", "1.5"))   # per call; cold wide p90 1.25 s
# The owner's SystemOne gateway (ADR-0075): the FLYWHEEL_LLM_* seam's host, path /v1/systemone. Slower than
# TypeSafe's warm relay (wide p50 0.9-1.2 s, max 1.7 s measured 2026-10-03), hence its own per-call timeout.
_FW = urllib.parse.urlsplit(os.environ.get("FLYWHEEL_LLM_ENDPOINT", ""))
JEV_GW_HOST = (_FW.hostname or "").lower() if _FW.scheme == "https" else ""
JEV_GW_URL = f"https://{_FW.netloc}/v1/systemone" if JEV_GW_HOST else None
# Command Code's SystemOne endpoint (ADR-0079), the owner's preferred provider. It serves only the unversioned
# `typesafe/jev`, and its Cloudflare front refuses Python's default User-Agent (error 1010). A whole turn there
# took 2.3-9.4 s against TypeSafe's ~1 s (2026-10-06). Owner's decision: Command Code gets the whole span (5 s,
# refined to 5.5 s the same evening); its timeout is also the tier's SPAN, the most of the turn it may spend. Only
# an error, or no answer by the end of the span, sends the turn to the next tier.
JEV_CC_URL = os.environ.get("ENFORCER_JEV_CC_URL", "https://api.commandcode.ai/provider/v1/systemone")
JEV_CC_TIMEOUT_S = float(os.environ.get("ENFORCER_JEV_CC_TIMEOUT", "5.5"))
# The index owner's warm relay for Command Code (ADR-0081): its own path, /jev/cc, so an owner that predates
# it answers 404 and the call goes direct, never to TypeSafe's relay. Same loopback rule as JEV_RELAY_URL.
JEV_CC_RELAY_URL = (f"http://{EMBED_HOST}:{EMBED_PORT}/jev/cc"
                    if EMBED_HOST in ("127.0.0.1", "localhost", "::1")
                    and (urllib.parse.urlsplit(JEV_CC_URL).hostname or "").lower() == "api.commandcode.ai" else None)
JEV_USER_AGENT = "skill-concierge"
# jevd (ADR-0080; github.com/thinhkhuat/jevd), the optional warm local relay for SystemOne endpoints. When JEVD_URL
# names a loopback http address and jevd answers GET /ladder, the bench is jevd's ladder: its order, models,
# per-call limits and spans, configured in jevd alone (the owner's decision of 2026-10-06). jevd holds the keys and
# the kept-open connections; this hook still walks the ladder itself, because a turn is two linked calls (the wide
# ranking, then the rerank on the same provider), and pins each call to one provider. Unset, or jevd silent within
# JEVD_LADDER_TIMEOUT_S: ENFORCER_JEV_BENCH applies, as before.
_JD = urllib.parse.urlsplit(os.environ.get("JEVD_URL", ""))
JEVD_URL = (os.environ["JEVD_URL"].rstrip("/").removesuffix("/v1/systemone") if _JD.scheme == "http"
            and (_JD.hostname or "").lower() in ("127.0.0.1", "localhost", "::1") else None)
JEVD_LADDER_TIMEOUT_S = 0.3
# Each key goes only to its own endpoint's host over https (loopback for tests): TypeSafe's key to
# api.typesafe.ai, the gateway's key to the FLYWHEEL_LLM_* seam's host (ADR-0075), Command Code's to
# api.commandcode.ai (ADR-0079).
JEV_EP_HOSTS = {"ts": {"api.typesafe.ai"}, "gw": {JEV_GW_HOST} if JEV_GW_HOST else set(),
                "cc": {"api.commandcode.ai"}}
JEV_GW_TIMEOUT_S = float(os.environ.get("ENFORCER_JEV_GATEWAY_TIMEOUT", "2.0"))
# Thread start -> join. Capped at 7.8 s whatever the env says (ADR-0079; was 3.0): Command Code's 5.5 s span,
# then TypeSafe's 1.5 s call, plus 0.8 s for the catalogue read and thread start-up. Each router call is held to
# its limit by the clock (`_jev_call_capped`), because urllib's timeout bounds each socket operation, not the call,
# and live Command Code turns ran a second and more past the span. The annex queries run after the
# join and Claude Code kills the hook at 10 s (hooks/hooks.json), so a larger budget would trade a slow offer for
# no offer at all. A harness that kills the enforcer sooner passes a smaller budget.
JEV_BUDGET_S = min(float(os.environ.get("ENFORCER_JEV_BUDGET", "7.8")), 7.8)
JEV_FITS_FLOOR = float(os.environ.get("ENFORCER_JEV_FITS_FLOOR", "0.30"))
JEV_MAX_CHARS = 4000
JEV_CHUNK = 250          # a Choice holds at most 255 options
JEV_WIDE_DESC = 160      # catalogue descriptions in the wide call (~24k input tokens for ~500 skills)
JEV_PER_CHUNK = 5        # shortlist = top 5 of every chunk (chunk distributions are not comparable)
JEV_RERANK_DESC = 400
JEV_OFFER_ROWS = 5      # measured: top 5 -> 74 % recall, top 3 -> 65 %, today's 8-row menu -> 36 %
JEV_CTX_CHARS = 1500
# ADR-0087, the staged menu. The wide pass's own menu (its shortlist ordered by lift) is a result of its own:
# a turn whose rerank fails on every tier keeps it instead of dropping to the embedding menu.
# ENFORCER_JEV_TIER limits the route to one tier (a jevd provider name or a model id); the Cline plugin pins
# `typesafe` so its 2 s first-call wait gets the full route.
JEV_TIER_PIN = os.environ.get("ENFORCER_JEV_TIER", "").strip()
# jevd's provider names -> the ENFORCER_JEV_BENCH endpoint of the same provider, so a pin holds without jevd
JEV_PIN_EP = {"typesafe": "ts", "commandcode": "cc", "gateway": "gw"}
JEV_TAIL_BYTES = 262144  # transcript tail read for the conversation context

# Ported from fast-jev-compaction (MIT), src/state.ts estimateTokens: a word costs one token per six
# letters, a digit half a token, any other symbol nine tenths; lands 2-18 % above Jev's own counts.
_JEV_TOKEN_PIECES = re.compile(r"[A-Za-z]+|[0-9]+|[^\sA-Za-z0-9]")


def _jev_tokens(text: str) -> int:
    tokens = 0.0
    for m in _JEV_TOKEN_PIECES.finditer(text):
        piece = m.group(0)
        if piece[0].isascii() and piece[0].isdigit():
            tokens += len(piece) / 2
        elif piece[0].isascii() and piece[0].isalpha():
            tokens += 1 + (len(piece) - 1) // 6
        else:
            tokens += 0.9
    return math.ceil(tokens)


# Secret shapes replaced before any transcript text leaves the machine (ADR-0076).
_JEV_SECRET_RES = (
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"glpat-[A-Za-z0-9_-]{20,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{35}"),
    re.compile(r"xox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{12,}", re.I),
    re.compile(r"eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*"),            # a bare JWT
    # a secret-named key, quoted or not, any case (JSON `"OPENAI_API_KEY": "v"`, `api_key = v`, `x-api-key: v`)
    re.compile(r"(?:api[_-]?key|token|secret|passw(?:or)?d)[\"']?[ \t]*[=:][ \t]*[\"']?[^\s\"',;}]+", re.I),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"aws_secret_access_key\s*[=:]\s*\S+", re.I),
    re.compile(r"(?<=://)[^/\s:@]+:[^@\s]+(?=@)"),                                        # user:pass in a URL
    # a key block, to its END marker, or to the end of the text when a truncated paste has none
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.S),
)


def _jev_redact(text: str) -> str:
    for rx in _JEV_SECRET_RES:
        text = rx.sub("[redacted]", text)
    return text


# Plain user records that carry command output or wrappers, not words Thinh typed.
_JEV_NOT_TYPED = ("<bash-stdout>", "<bash-stderr>", "<bash-input>", "<local-command-stdout>",
                  "<local-command-stderr>", "<command-name>", "<command-message>",
                  "This session is being continued")
_JEV_REMINDER_RE = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
# Blocks other hooks and harnesses prepend to a typed prompt: the persona rules, and the injected skill
# list that runs up to the `[User Request]` marker (or, with no marker, to the end of the text).
_JEV_INJECTED_RES = (re.compile(r"\[Assistant Rules\].*?(?:\[/Assistant Rules\]|\Z)", re.S),
                     re.compile(r"\[Relevant skills for this request\].*?(?:\[User Request\]|\Z)", re.S))


def _jev_typed_user_text(record: dict):
    """The redacted text Thinh typed in a transcript `user` record, or None for anything else: meta and
    sidechain records, tool results, harness messages, command output and slash-command wrappers."""
    if not isinstance(record, dict) or record.get("type") != "user" or record.get("isMeta") \
            or record.get("isSidechain"):
        return None
    msg = record.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text = "\n".join(b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str))
    else:
        return None
    text = text.strip()
    if not text or _HARNESS_MSG_RE.match(text) or text.startswith(_JEV_NOT_TYPED):
        return None
    text = _JEV_REMINDER_RE.sub("", text)
    for rx in _JEV_INJECTED_RES:
        text = rx.sub("", text)
    text = text.strip()
    return _jev_redact(text) if text else None
# Verbatim from docs.typesafe.ai/cookbooks/skill_suggestion.md (fetched 2026-09-26).
JEV_CHOICE_INSTRUCTIONS = ("Which of these skills, if any, is the right one to load to help with the "
                           "user's latest request?")
JEV_SKIP_MSG = (
    AUTHORIZED_SKIP_MARKER + " the Jev needs-a-skill gate checked the skills that could apply and found "
    "none that does what this turn asks (best fit {fit:.2f} < {floor:.2f}). NO SKILL: hook-cleared is "
    "pre-authorized; no search_skills needed. If the turn does hand you a substantial task in a "
    "skill's domain, route it (SEARCH/USING)."
)
_JEV_EVENT = None   # this turn's Jev telemetry for the ledger row; one hook process = one turn
_NON_ASCII_LETTER = re.compile(r"[^\W\d_a-zA-Z]")
_SKILL_MD_PATH = re.compile(r"/([A-Za-z0-9][\w.:-]*)/SKILL\.md")
_SKILL_BASE_DIR = re.compile(r"Base directory for this skill: \S*?/([A-Za-z0-9][\w.:-]*)/?\s")


def _is_english(prompt: str) -> bool:
    """The calibration population's language rule: fewer than two non-ASCII letters."""
    return len(_NON_ASCII_LETTER.findall(prompt)) < 2


def _skill_key(name: str) -> str:
    """Namespaced and bare forms merge (`ak:cook` -> `ak-cook`), as the usage audit's norm()."""
    return (name or "").strip().lstrip("/").split(" ")[0].replace(":", "-").lower()


def _tail_lines(path: str, nbytes: int) -> list:
    """The lines of the last `nbytes` of `path`; the cut first line is dropped when the read
    starts mid-file."""
    with open(path, "rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(max(0, size - nbytes))
        return fh.read().decode("utf-8", "replace").splitlines()[1 if size > nbytes else 0:]


def _jev_context(transcript_path: str):
    """(tail of the last assistant message, last 3 skills loaded) from the session transcript, via
    a bounded tail read. Any problem -> empty context, never an error."""
    try:
        lines = _tail_lines(transcript_path, JEV_TAIL_BYTES)
    except (OSError, TypeError, ValueError):
        return "", []
    prev, skills = "", []

    def seen(name):
        k = _skill_key(name)
        if k:
            if k in skills:
                skills.remove(k)
            skills.append(k)
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict) or rec.get("isSidechain"):
            continue
        msg = rec.get("message")
        content = msg.get("content") if isinstance(msg, dict) else None
        if rec.get("type") == "assistant" and isinstance(content, list):
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text" and (b.get("text") or "").strip():
                    prev = b["text"]
                elif b.get("type") == "tool_use":
                    nm, inp = b.get("name") or "", b.get("input")
                    inp = inp if isinstance(inp, dict) else {}
                    if nm == "Skill":
                        seen(str(inp.get("skill") or ""))
                    elif nm.endswith("get_skill"):
                        seen(str(inp.get("name") or inp.get("skill") or ""))
                    elif nm in ("Read", "Bash"):
                        for m in _SKILL_MD_PATH.findall(str(inp.get("file_path") or inp.get("command") or "")):
                            seen(m)
        elif rec.get("type") == "user":
            text = content if isinstance(content, str) else " ".join(
                str(b.get("text") or "") for b in content or [] if isinstance(b, dict))
            for m in _SKILL_BASE_DIR.findall(text + " "):
                seen(m)
    return prev[-JEV_CTX_CHARS:], skills[-3:]


# ── rerank history (ENFORCER_JEV_HISTORY, default OFF) ──────────────────────────────────────────────
# Text only (ADR-0076): Thinh's typed words and assistant `text` blocks, secrets redacted, tools by NAME,
# never a tool input or output. Used by the rerank call only; the wide call keeps today's state.
JEV_HISTORY = os.environ.get("ENFORCER_JEV_HISTORY", "0") == "1"


def _env_int(name: str, default: int) -> int:
    """A malformed tunable falls back to its default: a hook never dies at import over an env typo."""
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    """_env_int's float twin: a malformed or non-finite value falls back to the default."""
    try:
        v = float(os.environ.get(name, default))
        return v if math.isfinite(v) else default
    except ValueError:
        return default


JEV_HISTORY_TOKENS = _env_int("ENFORCER_JEV_HISTORY_TOKENS", 10000)
JEV_HISTORY_BYTES = _env_int("ENFORCER_JEV_HISTORY_BYTES", 2097152)
JEV_HISTORY_PINNED = 6      # the last entries are shrunk last
JEV_HISTORY_JOIN_S = 0.2    # most the rerank waits for a history still being fitted
JEV_REASK_MIN_S = 0.5       # budget left that still allows the skip guard's second rerank
JEV_RERANK_MIN_S = 0.5      # time left in a tier below which its rerank is not sent (it could not finish)
JEV_HISTORY_NOTE = ("Earlier turns of this coding-assistant conversation, oldest first. Only typed text "
                    "and assistant replies are shown; tools are listed by name.")
_JEV_ABRIDGE_HEAD, _JEV_ABRIDGE_TAIL = 400, 150


def _jev_history_entries(lines: list, window: int = 0) -> list:
    """Allow-listed conversation entries from transcript JSONL lines, oldest first. Consecutive assistant
    records (text and tool_use blocks arrive as separate records) merge into one entry. Lines are read from
    the newest backwards and reading stops once the entries hold about `window` estimated tokens (0 = no
    limit): older turns could only be collapsed or left out by the fitter anyway, so decoding and
    tokenizing a 2 MiB tail of short turns would be wasted work."""
    out, seen = [], 0                       # newest first while reading
    for line in reversed(lines):
        if window and seen >= window:
            break
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict):
            continue
        if rec.get("type") == "user":
            text = _jev_typed_user_text(rec)
            if text:
                out.append({"role": "user", "text": text})
                seen += len(text) // 4 + 25
        elif rec.get("type") == "assistant" and not rec.get("isSidechain"):
            msg = rec.get("message")
            content = msg.get("content") if isinstance(msg, dict) else None
            if not isinstance(content, list):
                continue
            texts = [b["text"] for b in content if isinstance(b, dict) and b.get("type") == "text"
                     and isinstance(b.get("text"), str) and b["text"].strip()]
            tools = [b["name"] for b in content if isinstance(b, dict) and b.get("type") == "tool_use"
                     and isinstance(b.get("name"), str)]
            if not texts and not tools:
                continue
            text = _jev_redact("\n".join(texts).strip())
            if out and out[-1]["role"] == "assistant":      # an earlier record of the same reply
                last = out[-1]
                last["text"] = "\n".join(t for t in (text, last["text"]) if t)
                if tools:
                    last["tools"] = tools + last.get("tools", [])
            else:
                out.append({"role": "assistant", "text": text, **({"tools": tools} if tools else {})})
            seen += len(text) // 4 + 3 + 8 * len(tools)
    out.reverse()
    return out


def _jev_history_lines(lines: list, budget: int, prompt: str, skills: list = ()):
    """Pure. Transcript JSONL lines -> {"conversation", "stage", "tokens"} fitted under `budget` tokens
    (the whole rerank state counted), or None for an empty history or one that cannot fit. Never raises
    on malformed records. Stage order ported from fast-jev-compaction (MIT), src/state.ts fitState."""
    entries = _jev_history_entries(lines, 3 * budget)
    cur = {_jev_redact(prompt).strip(), prompt.strip()}
    if entries and entries[-1]["role"] == "user" and entries[-1]["text"].strip() in cur:
        entries.pop()
    if not entries:
        return None
    base = _jev_tokens(json.dumps({"request": prompt[:JEV_MAX_CHARS], "conversation_note": JEV_HISTORY_NOTE,
                                   "conversation": [], "skills_already_loaded_this_session": list(skills)},
                                  ensure_ascii=False))
    cost = [_jev_tokens(json.dumps(e, ensure_ascii=False)) + 1 for e in entries]
    total = sum(cost)           # running sum: each stage step adjusts it, so a stage is O(n), not O(n^2)

    def retoken(i):
        nonlocal total
        new = _jev_tokens(json.dumps(entries[i], ensure_ascii=False)) + 1
        total += new - cost[i]
        cost[i] = new

    def drop(i):
        nonlocal total
        total -= cost[i]
        cost[i] = 0

    n = len(entries)
    keep = [True] * n                                        # stages 5-6 leave entries out

    def finish(stage):
        return {"conversation": [e for e, k in zip(entries, keep) if k], "stage": stage, "tokens": base + total}

    if base + total <= budget:
        return finish("full")
    old = list(range(max(0, n - JEV_HISTORY_PINNED)))
    pinned = list(range(max(0, n - JEV_HISTORY_PINNED), n))
    cap = _JEV_ABRIDGE_HEAD + _JEV_ABRIDGE_TAIL
    for i in old + pinned:                                   # 2. long texts abridged, oldest first
        t = entries[i]["text"]
        if len(t) > cap:
            entries[i]["text"] = (t[:_JEV_ABRIDGE_HEAD] + f"\n[... {len(t) - cap} chars omitted ...]\n"
                                  + t[-_JEV_ABRIDGE_TAIL:])
            retoken(i)
            if base + total <= budget:
                return finish("texts abridged")
    for i in old:                                            # 3. old messages collapsed
        if entries[i]["text"]:
            entries[i]["text"] = f"[... {len(entries[i]['text'])} chars omitted ...]"
            retoken(i)
            if base + total <= budget:
                return finish("old messages collapsed")
    for i in old:                                            # 4. old tool lists become counts
        tools = entries[i].get("tools")
        if isinstance(tools, list):
            counts = {}
            for nm in tools:
                counts[nm] = counts.get(nm, 0) + 1
            entries[i]["tools"] = counts
            retoken(i)
            if base + total <= budget:
                return finish("old tools counted")
    for i in old:                                            # 5. old messages left out, oldest first
        keep[i] = False
        drop(i)
        if base + total <= budget:
            return finish("old messages left out")
    for i in pinned:                                         # 6. oldest dropped, pinned included
        keep[i] = False
        drop(i)
        if base + total <= budget:
            return finish("oldest dropped")
    return None


def _jev_history(transcript_path: str, prompt: str, skills: list = (), info: dict = None):
    """The fitted rerank history from a bounded transcript tail, or None. Catches every exception: the
    caller treats None as 'use today's state'. `info["err"]` names why, when a dict is passed."""
    try:
        res = _jev_history_lines(_tail_lines(transcript_path, JEV_HISTORY_BYTES), JEV_HISTORY_TOKENS, prompt, skills)
        if res is None and info is not None:
            info["err"] = "Empty"
        return res
    except Exception as e:  # noqa: BLE001 — history is an extra: any failure falls back to today's state
        if info is not None:
            info["err"] = type(e).__name__
        return None


def _jev_history_state(prompt: str, skills: list, hist: dict) -> dict:
    return {"request": prompt[:JEV_MAX_CHARS], "conversation_note": JEV_HISTORY_NOTE,
            "conversation": hist["conversation"], "skills_already_loaded_this_session": skills}


def _jev_history_start(transcript_path: str, prompt: str, skills: list):
    """Fit the history in a daemon thread so it overlaps the wide call. -> (thread, box)."""
    box = {}

    def work():
        t = time.time()
        info = {}
        try:
            box["hist"] = _jev_history(transcript_path, prompt, skills, info)
        except Exception as e:  # noqa: BLE001 — a patched or broken helper must not end the thread loudly
            box["hist"], info["err"] = None, type(e).__name__
        box["err"] = info.get("err")
        box["ms"] = int((time.time() - t) * 1000)
    th = threading.Thread(target=work, daemon=True)
    th.start()
    return th, box


def _row_invocable(name: str, scope) -> bool:
    """The per-row test `_retrieve` applies (project isolation, cross-harness twin, the session's
    plugin gate) — shared so the Jev catalogue offers exactly what retrieval could.

    INVOCABLE_PLUGIN_IDS None means the manifest was unreadable, i.e. the twin test cannot be
    made: drop ONLY on positive knowledge — an unknown must filter nothing, or an unreadable
    settings file silently reinstates the very mislabelling this replaced. The exception is DSH,
    Cline and OpenCode, which have NO skill-plugin registry by design: their verdict is the scope +
    filesystem twin, so a None there must not switch the whole filter off (it did before
    v0.49.0). The last test is ADR-0052's: a plugin disabled in THIS session's merged layers."""
    if CROSS_HARNESS and PROJECT_ISOLATION and _project_row_verdict(scope, name) == "other":
        return False
    if (CROSS_HARNESS and (INVOCABLE_PLUGIN_IDS is not None
                           or RUNNING_HARNESS in ("dsh", "cline", "opencode"))
            and _scope_is_foreign(scope) and not _invocable_twin(name)):
        return False
    return _plugin_gate_ok(name, scope)


def _jev_catalog() -> list:
    """[(name, description)] this session can invoke: every installed skill's base point (tier
    external excluded), through `_row_invocable`, keep-off and the blocklist."""
    rows, seen, off = [], set(), None
    while True:
        body = {"limit": 2000, "with_payload": ["name", "description", "scope"], "with_vector": False,
                "filter": {"must": [{"key": "kind", "match": {"value": "base"}}],
                           "must_not": [{"key": "tier", "match": {"value": "external"}}]}}
        if off is not None:
            body["offset"] = off
        res = _post_json(f"{QDRANT_URL}/collections/{COLLECTION}/points/scroll", body,
                         JEV_TIMEOUT_S)["result"]
        for pt in res.get("points", []):
            pl = pt.get("payload") or {}
            n = pl.get("name")
            if n and n not in seen:
                seen.add(n)
                if _row_invocable(n, pl.get("scope")):
                    rows.append((n, pl.get("description") or "", 0.0))
        off = res.get("next_page_offset")
        if off is None:
            break
    rows, _ = _drop_keepoff(rows, KEEPOFF)
    rows, _ = _drop_blocklisted(rows)
    return [(n, d) for n, d, _s in rows]


def _jev_fits_text(name: str, desc: str) -> str:
    return (f"Does the skill '{name}' do the specific thing the user's request asks for? "
            f"It is described as: {desc}")


def _prob(x) -> float:
    """`x` as a probability; raises on NaN or out of range, which must never reach the renderer or
    the ledger."""
    v = float(x)
    if not (math.isfinite(v) and 0.0 <= v <= 1.0):
        raise ValueError("probability out of range")
    return v


def _jev_wide_rows(answers: dict, catalog: list) -> list:
    """The wide pass's own menu (ADR-0087): the shortlist (top JEV_PER_CHUNK of every chunk) ordered by lift,
    a candidate's probability times its chunk's size, i.e. how far above an even split it stands; top
    JEV_OFFER_ROWS as (name, desc, share of the shown lift). Raw probabilities favour a small chunk, whose few
    options split the same mass (a one-option chunk always answers 1.0). Replayed on 233 real skill turns,
    lift and raw order find the used skill alike (top 5: 70.8 % vs 71.2 %; top 1: 36.5 % vs 36.1 %)."""
    desc = dict(catalog)
    lifts = {}
    for k, a in answers.items():
        if not k.startswith("wide::"):
            continue
        i = int(k.split("::")[1])
        size = len(catalog[i * JEV_CHUNK:(i + 1) * JEV_CHUNK]) or 1
        pr = {n: _prob(v) for n, v in a["probabilities"].items()}
        for n in sorted(pr, key=lambda n: -pr[n])[:JEV_PER_CHUNK]:
            if n in desc:
                lifts[n] = pr[n] * size
    top = sorted(lifts, key=lambda n: -lifts[n])[:JEV_OFFER_ROWS]
    if not top:
        raise ValueError("wide answer names none of the catalogue")
    total = sum(lifts[n] for n in top) or 1.0
    return [(n, desc[n], lifts[n] / total) for n in top]


def _jev_wide_questions(catalog: list) -> dict:
    """The whole catalogue as parallel Choice questions of at most JEV_CHUNK options each."""
    return {f"wide::{i // JEV_CHUNK}": {
                "type": "choice", "instructions": JEV_CHOICE_INSTRUCTIONS,
                "criteria": {n: (d or n)[:JEV_WIDE_DESC] for n, d in catalog[i:i + JEV_CHUNK]}}
            for i in range(0, len(catalog), JEV_CHUNK)}


def _jev_shortlist(answers: dict) -> list:
    """Top JEV_PER_CHUNK names of every wide chunk, chunk order kept."""
    out = []
    for k in sorted((k for k in answers if k.startswith("wide::")), key=lambda k: int(k.split("::")[1])):
        pr = answers[k]["probabilities"]
        out += sorted(pr, key=lambda n: -pr[n])[:JEV_PER_CHUNK]
    return out


def _jev_rerank_questions(shortlist: list) -> dict:
    """shortlist = [(name, desc)] -> one Choice over it plus one `fits` Noul per candidate."""
    qs = {"which": {"type": "choice", "instructions": JEV_CHOICE_INSTRUCTIONS,
                    "criteria": {n: (d or n)[:JEV_RERANK_DESC] for n, d in shortlist}}}
    for i, (n, d) in enumerate(shortlist):
        qs[f"fits::{i}"] = {"type": "noul", "instructions": _jev_fits_text(n, (d or n)[:JEV_RERANK_DESC])}
    return qs


def _jev_decide(answers: dict, shortlist: list):
    """Pure policy over one rerank answer -> (verdict, rows, confidence, best_fit).
    "skip" when no candidate's `fits` reaches JEV_FITS_FLOOR; otherwise "offer" with the top
    JEV_OFFER_ROWS rows (name, desc, probability) in Choice order. Raises on a malformed answer."""
    best = max(_prob(answers[f"fits::{i}"]["noul"]) for i in range(len(shortlist)))
    which = answers["which"]
    conf = _prob(which["confidence"])
    if best < JEV_FITS_FLOOR:
        return "skip", [], conf, best
    desc = dict(shortlist)
    probs = {n: _prob(p) for n, p in which["probabilities"].items() if n in desc}
    order = sorted(probs, key=lambda n: -probs[n])
    if not order:
        raise ValueError("choice names none of the shortlist")
    rows = [(n, desc[n], probs[n]) for n in order[:JEV_OFFER_ROWS]]
    return "offer", rows, conf, best


# ADR-0083 pull-in: a ❤️/⭐ skill Jev judged but ranked below its JEV_OFFER_ROWS is appended
# under them — never displacing one — when its own `fits` clears REPUTATION_PULL_FIT; at most
# REPUTATION_PULL_MAX, looked for only down to Choice rank REPUTATION_PULL_DEPTH. The owner's pick
# (2026-10-07) over the replay's narrower recommendation: on 313 real skill turns the used skill sat
# in ranks 6-10 on 13; with ak-*/pstack/Matt Pocock standing in for the list, bar 0.5 added 0.44
# rows a turn. SKILL_REPUTATION_PULL_MAX=0 turns pull-in off and keeps the badges.
REPUTATION_PULL_FIT = min(1.0, max(0.0, _env_float("SKILL_REPUTATION_PULL_FIT", 0.5)))
REPUTATION_PULL_MAX = max(0, _env_int("SKILL_REPUTATION_PULL_MAX", 2))
REPUTATION_PULL_DEPTH = max(0, _env_int("SKILL_REPUTATION_PULL_DEPTH", 10))


def _jev_pull_ins(answers: dict, shortlist: list, rows: list) -> list:
    """Pure: [(name, desc, probability)] of owner-badged shortlist rows to append under `rows`."""
    if REPUTATION_PULL_MAX <= 0 or not rows:
        return []
    probs = answers["which"]["probabilities"]
    idx = {n: i for i, (n, _d) in enumerate(shortlist)}
    desc = dict(shortlist)
    shown = {n for (n, _d, _p) in rows}
    order = sorted((n for n in probs if n in idx), key=lambda n: -float(probs[n]))
    out = []
    for n in order[len(rows):REPUTATION_PULL_DEPTH]:
        if n in shown or not _owner_tier(n):
            continue
        if float(answers[f"fits::{idx[n]}"]["noul"]) >= REPUTATION_PULL_FIT:
            out.append((n, desc[n], float(probs[n])))
            if len(out) >= REPUTATION_PULL_MAX:
                break
    return out


class JevModelMismatch(ValueError):
    """Jev answered with a model other than the pinned one: the calibration does not hold for it."""


def _jevd_ladder():
    """jevd's ladder as bench tiers (ADR-0080), or None when JEVD_URL is unset or jevd does not answer in time.
    A tier is one jevd provider: its name (the pin), model, per-call `timeout`, `span` when jevd sets span_s,
    and whether jevd holds its key. No key ever reaches this hook."""
    if JEVD_URL is None:
        return None
    try:
        req = urllib.request.Request(JEVD_URL + "/ladder", headers={"User-Agent": JEV_USER_AGENT})
        with _OPENER.open(req, timeout=JEVD_LADDER_TIMEOUT_S) as resp:
            providers = json.loads(resp.read())["providers"]
        tiers = []
        for p in providers:
            tier = {"ep": "jevd", "name": str(p["name"]), "model": str(p["model"]),
                    "url": JEVD_URL + "/v1/systemone", "timeout": float(p["timeout_s"]), "keyed": bool(p.get("key"))}
            if p.get("span_s"):
                tier["span"] = float(p["span_s"])
            tiers.append(tier)
        return tiers or None
    except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException):
        return None


def _jev_bench() -> list:
    """The ordered SystemOne tiers one turn may try: jevd's ladder when jevd answers (ADR-0080), else
    ENFORCER_JEV_BENCH (ADR-0075): space-separated `<endpoint>:<model>`, endpoint `ts` (TypeSafe:
    ENFORCER_JEV_URL, TYPESAFE_API_KEY, the warm relay), `gw` (the owner's gateway, JEV_GW_URL) or `cc`
    (Command Code, CMD_API_KEY, ADR-0079; its tier carries a `span`). Unset = TypeSafe alone with JEV_MODEL, as
    before. A malformed entry, or a `gw` entry with no gateway configured, is dropped — the hook never fails on
    config."""
    jevd = _jevd_ladder()
    if jevd is not None and any(t["keyed"] for t in jevd):   # a jevd without keys must not switch Jev off
        return jevd
    tiers = []
    for entry in os.environ.get("ENFORCER_JEV_BENCH", f"ts:{JEV_MODEL}").split():
        ep, _, model = entry.partition(":")
        if not model:
            continue
        if ep == "ts":
            tiers.append({"ep": "ts", "model": model, "url": JEV_URL, "timeout": JEV_TIMEOUT_S})
        elif ep == "gw" and JEV_GW_URL:
            tiers.append({"ep": "gw", "model": model, "url": JEV_GW_URL, "timeout": JEV_GW_TIMEOUT_S})
        elif ep == "cc":
            tiers.append({"ep": "cc", "model": model, "url": JEV_CC_URL, "timeout": JEV_CC_TIMEOUT_S,
                          "span": JEV_CC_TIMEOUT_S})
    return tiers


def _jev_key(tier: dict) -> str:
    """Per endpoint, read per call: TypeSafe's own key, the gateway's (ENFORCER_JEV_KEY, else the
    FLYWHEEL_LLM_* seam's key), or Command Code's (CMD_API_KEY). A jevd tier has no key here: jevd holds it,
    and the marker returned only says it does (it is never sent)."""
    if tier["ep"] == "jevd":
        return "jevd" if tier.get("keyed") else ""
    if tier["ep"] == "gw":
        return os.environ.get("ENFORCER_JEV_KEY") or os.environ.get("FLYWHEEL_LLM_API_KEY", "")
    if tier["ep"] == "cc":
        return os.environ.get("CMD_API_KEY", "")
    return os.environ.get("TYPESAFE_API_KEY", "")


def _jev_direct_url(url: str, ep: str) -> str:
    """`url`, refused unless it is https to endpoint `ep`'s own host, or a loopback host (tests) — so a
    mis-set variable cannot send a key to another host, and neither key can reach the other endpoint."""
    u = urllib.parse.urlsplit(url)
    host = (u.hostname or "").lower()
    if (u.scheme == "https" and host in JEV_EP_HOSTS.get(ep, set())) or host in ("127.0.0.1", "localhost", "::1"):
        return url
    raise ValueError(f"Jev URL for endpoint {ep!r} must be https to {sorted(JEV_EP_HOSTS.get(ep, set()))}")


def _jev_model_base(model: str) -> str:
    """`openrouter/typesafe/jev-1.13` and `typesafe/jev-1.13-20260917` -> `jev-1.13`: a gateway's provider
    path and a dated snapshot suffix name the same model; the version does not."""
    return re.sub(r"-\d{8}$", "", model.rsplit("/", 1)[-1])


def _jev_answers(resp: dict, pinned: str = None):
    """(answers, the model id Jev returned) after checking it ran the pinned model, up to provider path and
    snapshot date. Both TypeSafe and the gateway return `model` (verified 2026-10-03); the exact id is kept
    because a new dated snapshot under the same pin is a model update the ledger should show."""
    pinned = pinned or JEV_MODEL
    model = resp.get("model")
    if model is not None and _jev_model_base(model) != _jev_model_base(pinned):
        raise JevModelMismatch(f"Jev answered with {model!r}, pinned {pinned!r}")
    return resp["answers"], model


def _jev_call(state: dict, questions: dict, tier: dict, key: str, timeout: float):
    """One System One request on one bench tier -> (answers, via, returned model). A TypeSafe or Command Code
    tier goes through the local index owner's warm relay (/jev, /jev/cc: fixed destinations, ADR-0081); an
    owner without the route (404) or not listening falls back to one direct call. A gateway tier is always direct.
    A timeout is not retried on the same tier. A jevd tier is pinned to its provider, sends no key, and gives jevd
    this call's limit as its budget."""
    body = {"model": tier["model"], "state": state, "questions": questions}
    if tier["ep"] == "jevd":
        hdr = {"User-Agent": JEV_USER_AGENT, "X-Jevd-Provider": tier["name"], "X-Jevd-Budget": f"{timeout:.3f}"}
        answers, model = _jev_answers(_post_json(_jev_direct_url(tier["url"], "jevd"), body, timeout, hdr),
                                      tier["model"])
        return answers, "jevd", model
    auth = {"Authorization": "Bearer " + key, "User-Agent": JEV_USER_AGENT}
    relay = {"ts": JEV_RELAY_URL, "cc": JEV_CC_RELAY_URL}.get(tier["ep"])
    if relay is not None:
        try:
            answers, model = _jev_answers(_post_json(relay, body, timeout,
                                                     {**auth, "X-Jev-Timeout": str(timeout)}), tier["model"])
            return answers, "relay", model
        except urllib.error.HTTPError as e:
            # The relay answers an upstream timeout with 502 {"error": "<exception class>"}: recorded as the
            # timeout it is, never re-sent direct to the same upstream.
            if e.code == 502 and _jev_relay_timeout(e):
                raise TimeoutError("relay: upstream timeout") from e
            if e.code != 404:
                raise
        except urllib.error.URLError as e:
            if not isinstance(e.reason, ConnectionRefusedError):
                raise
    answers, model = _jev_answers(_post_json(_jev_direct_url(tier["url"], tier["ep"]), body, timeout, auth),
                                  tier["model"])
    return answers, "direct", model


def _jev_call_capped(state: dict, questions: dict, tier: dict, key: str, timeout: float):
    """`_jev_call` under a wall-clock limit (ADR-0079). urllib's timeout bounds each socket operation, not the
    call: live Command Code turns ran a second and more past their 5 s span, which left TypeSafe no time and the
    turn no verdict. Past the limit the call is abandoned (its daemon thread ends with its own socket timeout or
    with the hook) and reported as a timeout, so the next tier starts on time."""
    box = {}

    def run():
        try:
            box["ok"] = _jev_call(state, questions, tier, key, timeout)
        except BaseException as e:  # noqa: BLE001 — re-raised in the caller's thread
            box["err"] = e
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise TimeoutError(f"no answer within {timeout:.2f} s")
    if "err" in box:
        raise box["err"]
    return box["ok"]

def _jev_relay_timeout(e: urllib.error.HTTPError) -> bool:
    """True when a relay 502's JSON body names a timeout class."""
    try:
        err = json.loads(e.read()).get("error")
    except (OSError, ValueError, AttributeError):
        return False
    return err in ("TimeoutError", "timeout", "ReadTimeout")


def _jev_route(prompt: str, transcript_path: str, sink: dict | None = None) -> dict:
    """One ADR-0061 routing decision -> {"result": (verdict, rows, best_fit, pulled) | None, "event": {...}}.
    Result None = not eligible or failed: the embedding path decides. Runs in a worker thread, so
    it returns its telemetry instead of writing module state. ADR-0087: the event's `stage` says whether the
    result is the full (reranked) menu or the wide pass's own menu, kept when no tier finished its rerank."""
    if not (JEV_ROUTER and _is_english(prompt)):
        return {"result": None, "event": None}
    t0 = time.time()   # before the jevd ladder fetch, so the fetch spends this turn's budget
    bench = _jev_bench()
    if JEV_TIER_PIN:   # ADR-0087: one tier only, by jevd provider name, model, or (no jevd) endpoint
        bench = [t for t in bench if JEV_TIER_PIN in (t.get("name"), t["model"])
                 or JEV_PIN_EP.get(JEV_TIER_PIN) == t["ep"]]
    if not any(_jev_key(t) for t in bench):
        return {"result": None, "event": None}
    deadline = t0 + JEV_BUDGET_S
    src = {"bench": "jevd" if bench[0]["ep"] == "jevd" else "env"}
    fell, err = [], "NoTier"
    try:
        catalog = _jev_catalog()
        prev, skills = _jev_context(transcript_path)
    except (OSError, ValueError, KeyError, TypeError, IndexError, UnicodeError,
            http.client.HTTPException) as e:
        return {"result": None, "event": {**_jev_err(type(e).__name__, t0), **src}}
    if JEV_HISTORY:   # the history's redaction rule covers every text this flag lets leave the machine
        prev = _jev_redact(prev)
    state = {"request": prompt[:JEV_MAX_CHARS], "recent_context": prev,
             "skills_already_loaded_this_session": skills}
    desc = dict(catalog)
    hth = hbox = None
    if JEV_HISTORY:   # fitted alongside the wide call, never ahead of it
        hth, hbox = _jev_history_start(transcript_path, prompt, skills)
    hist_ev = None
    wide_menu = None   # ADR-0087: the first tier's wide menu, kept in case no tier finishes its rerank
    # ADR-0075 tiers in order; ADR-0079: any failure, a timeout included, moves the turn to the next tier that
    # can still finish inside the budget (a timed-out call may still be billed — the owner's accepted cost). A
    # tier with a `span` (Command Code) may spend only that much of the turn, so the tiers behind it keep theirs.
    for i, tier in enumerate(bench):
        key = _jev_key(tier)
        if not key:
            fell.append([tier["model"], "NoKey"])
            continue
        if deadline - time.time() < tier["timeout"]:
            fell.append([tier["model"], "NoTime"])
            continue
        tdl = min(deadline, time.time() + tier.get("span", JEV_BUDGET_S))
        try:
            wide, via, answered = _jev_call_capped(state, _jev_wide_questions(catalog), tier, key,
                                  min(tier["timeout"], tdl - time.time()))
            t1 = time.time()
            shortlist = [(n, desc[n]) for n in _jev_shortlist(wide) if n in desc]
            if not shortlist:
                raise ValueError("wide answer names none of the catalogue")
            wide_ev = {"stage": "wide", "ms": int((t1 - t0) * 1000), "wide_ms": int((t1 - t0) * 1000),
                       "via": via, "n": len(catalog), "ctx": bool(prev), "model": tier["model"], "rmodel": answered,
                       "tier": i, "to": tier["timeout"], **({"prov": tier["name"]} if "name" in tier else {}), **src}
            if wide_menu is None:
                wide_menu = (_jev_wide_rows(wide, catalog), wide_ev)
                wide_ev["lead"] = wide_menu[0][0][0]
                if sink is not None:   # the join may give up before this route does; it serves this then
                    sink["wide"] = {"result": ("offer", wide_menu[0], None, []), "event": dict(wide_ev, **src)}
            rstate, hist_ev = state, None
            if hth is not None:
                # leave the rerank one call's time; a span tier's timeout is its whole span, so reserve TypeSafe's
                need = JEV_TIMEOUT_S if "span" in tier else tier["timeout"]
                hth.join(min(JEV_HISTORY_JOIN_S, max(0.0, tdl - time.time() - need)))
                hist = None if hth.is_alive() else hbox.get("hist")
                if hist is not None:
                    rstate = _jev_history_state(prompt, skills, hist)
                    hist_ev = {"tok": hist["tokens"], "stage": hist["stage"], "ms": hbox["ms"],
                               "used": True, "reask": False}
                else:
                    hist_ev = {"err": "Slow" if hth.is_alive() else (hbox.get("err") or "Empty")}
            questions = _jev_rerank_questions(shortlist)
            if tdl - time.time() < JEV_RERANK_MIN_S:   # a doomed call would still be billed: hand over now
                raise TimeoutError("tier time spent before the rerank")
            rerank, _, _ = _jev_call_capped(rstate, questions, tier, key,
                                  max(0.05, min(tier["timeout"], tdl - time.time())))
            verdict, rows, conf, best = _jev_decide(rerank, shortlist)
            if verdict == "skip" and rstate is not state:
                # History alone must never cause the authorized skip: a skip needs today's state to agree.
                hist_ev["reask"] = True
                if tdl - time.time() < JEV_REASK_MIN_S:
                    if wide_menu is not None:   # ADR-0087: the wide menu stands, as when a rerank fails
                        return {"result": ("offer", wide_menu[0], None, []),
                                "event": {**wide_menu[1], "ms": int((time.time() - t0) * 1000),
                                          "err": "HistorySkip", "hist": hist_ev}}
                    return {"result": None, "event": {**_jev_err("HistorySkip", t0), "model": tier["model"],
                                                      "hist": hist_ev, **src}}
                rerank, _, _ = _jev_call_capped(state, questions, tier, key,
                                      max(0.05, min(tier["timeout"], tdl - time.time())))
                verdict, rows, conf, best = _jev_decide(rerank, shortlist)
        except (OSError, ValueError, KeyError, TypeError, IndexError, UnicodeError,
                http.client.HTTPException) as e:
            err = type(e).__name__
            fell.append([tier["model"], err])
            continue
        try:   # advisory: a pull-in failure never costs the turn its Jev verdict
            pulled = _jev_pull_ins(rerank, shortlist, rows) if verdict == "offer" else []
        except (KeyError, TypeError, ValueError):
            pulled = []
        return {"result": (verdict, rows, best, pulled), "event": {
            "stage": "full", "ms": int((time.time() - t0) * 1000), "wide_ms": int((t1 - t0) * 1000),
            "conf": round(conf, 3), "fit": round(best, 3), "via": via, "n": len(catalog),
            "ctx": bool(prev), "lead": rows[0][0] if rows else None,
            # which tier answered (`rmodel` = the exact id Jev returned: a new dated snapshot under the same
            # pin shows here), and the env-tunable settings, which leave no commit for the epoch windows to see
            "model": tier["model"], "rmodel": answered, "tier": i, "floor": JEV_FITS_FLOOR,
            "to": tier["timeout"], **({"prov": tier["name"]} if "name" in tier else {}), **src,
            **({"fell": fell} if fell else {}), **({"hist": hist_ev} if hist_ev else {}),
            **({"pulled": [n for (n, _d, _p) in pulled]} if pulled else {})}}
    if wide_menu is not None:   # ADR-0087 safety net: no tier finished its rerank; the wide menu stands
        rows, ev = wide_menu
        return {"result": ("offer", rows, None, []),
                "event": {**ev, "ms": int((time.time() - t0) * 1000), "fell": fell}}
    return {"result": None, "event": {**_jev_err(err, t0), "fell": fell, **src}}


def _jev_err(name: str, t0: float) -> dict:
    """A router error event. `leg` tells it apart from the v0.50.0 leg's `{err, ms}` rows, which
    sessions still on the old hook keep writing into the same ledger."""
    return {"err": name, "ms": int((time.time() - t0) * 1000), "leg": "router"}


def _jev_start(prompt: str, transcript_path: str):
    """Run `_jev_route` in a daemon thread so it overlaps the embed and Qdrant legs."""
    box = {}
    t0 = time.time()

    def work():
        try:
            box.update(_jev_route(prompt, transcript_path, box))
        except Exception as e:  # noqa: BLE001 — the thread boundary: a hook never lets an error escape
            box.update({"result": None, "event": _jev_err(type(e).__name__, t0)})
    t = threading.Thread(target=work, daemon=True)
    t.start()
    return t, box, time.time() + JEV_BUDGET_S


def _jev_join(job):
    """-> (verdict, rows, best_fit, pulled) or None (the embedding path decides); `pulled` (ADR-0083)
    is a list of owner-badged rows to show under `rows`, empty when none. Records this turn's Jev
    telemetry for the ledger row; a route still running at the deadline is abandoned."""
    global _JEV_EVENT
    if job is None:
        return None
    t, box, deadline = job
    t.join(max(0.0, deadline - time.time()))
    if t.is_alive():
        wide = box.get("wide")   # ADR-0087: the wide menu the route already had still stands
        _JEV_EVENT = {"err": "BudgetExceeded", "ms": int(JEV_BUDGET_S * 1000), "leg": "router"}
        if wide is not None:
            _JEV_EVENT = {**wide["event"], **_JEV_EVENT}
            return wide["result"]
        return None
    _JEV_EVENT = box.get("event")
    return box.get("result")


def _jev_serve(sid: str, prompt: str, jev, offered: list, outage: str, **ledger) -> bool:
    """Act on a Jev verdict when no embedding result is available to combine it with (embed or
    Qdrant down). True when it decided the turn. The outage stays visible: the offer row's
    `fallback` and the `jev.outage` field both name it, so fallback rates still count it."""
    if jev is None:
        return False
    if _JEV_EVENT is not None:
        _JEV_EVENT["outage"] = outage
    verdict, rows, best = jev[:3]
    pulled = jev[3] if len(jev) > 3 else []
    if verdict == "skip":
        _append_offer(sid, "jev_skip", offered, "jev_no_fit", prompt, **ledger)
        _authorized_skip_inject("jev", sid, fit=best, floor=JEV_FITS_FLOOR)
        return True
    _inject(_ranked_mandate(rows, whole_shelf=True, pulled=pulled) + _chain_hint(sid))
    _append_offer(sid, "offer", [[n, round(p, 4)] for (n, _d, p) in rows], outage, prompt,
                  pulled=[[n, round(p, 4)] for (n, _d, p) in pulled] or None, **ledger)
    return True


def _authorized_skip_inject(kind: str, sid: str = "", hint: bool = True, **fmt) -> None:
    """Emit the AUTHORIZED-SKIP line for a silent verdict leg ("getaway" | "intent_skip" |
    "selfref" | "harness" | "jev") when the kill-switch is on; no-op when off. ADR-0029: the CHAIN-HINT
    line (when one is due) rides these legs too — the vague ≥4-word continuations hints exist
    for land HERE, not on the ranked mandate — except the harness leg (`hint=False`): a
    notification is not the user's continuation, and 14 of the 19 ROUTE projections in the
    v0.46.0 epoch fired on exactly such text with zero follow. Wrapped so a bad format kwarg or
    a stdout error can never escape — this hook is additive-only and must never block a turn."""
    if not AUTHORIZED_SKIP:
        return
    try:
        msg = {"getaway": GETAWAY_SKIP_MSG,
               "intent_skip": INTENT_SKIP_MSG,
               "selfref": SELFREF_SKIP_MSG,
               "harness": HARNESS_SKIP_MSG,
               "jev": JEV_SKIP_MSG}[kind]
        _inject(msg.format(**fmt) + (_chain_hint(sid) if hint else ""))
    except (OSError, UnicodeError, ValueError, KeyError):
        return


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Every call here is a POST to a fixed service; a 3xx is an error, never a hop. urllib's default
    re-sends the Authorization header (the TypeSafe key) to the redirect target on 301/302/303."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None   # urllib then raises HTTPError for the 3xx


_OPENER = urllib.request.build_opener(_NoRedirect)


def _post_json(url: str, payload: dict, timeout: float, headers: dict = None) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})})
    with _OPENER.open(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _embed(text: str) -> list:
    """Embed via the warm shim under a HARD timeout. Raises on down/slow so the
    caller falls back to mandate-only."""
    return _post_json(EMBED_URL, {"text": text}, EMBED_TIMEOUT_S)["vector"]


# ── index owner autostart (replaces Docker's restart policy) ─────────────────
# The embed call is the first to fail when the owner is down, so its `embed_down` branch
# starts the owner — ONLY on "connection refused": a timeout or a 503 means busy or loading,
# and a restart there would only race the live owner. Detached, never waited on, at most
# once per OWNER_AUTOSTART_EVERY_S machine-wide (one stamp file). SKILL_OWNER_AUTOSTART=0
# disables it (tests that run the real enforcer).
OWNER_AUTOSTART = os.environ.get("SKILL_OWNER_AUTOSTART", "1") != "0"
OWNER_AUTOSTART_STAMP = Path.home() / ".claude" / "skill-concierge" / "owner-autostart.stamp"
OWNER_AUTOSTART_EVERY_S = 60
OWNER_VENV = Path(os.environ.get(
    "SKILL_CONCIERGE_VENV", Path.home() / ".claude" / "skill-concierge" / "venv"))


def _connection_refused(exc: BaseException) -> bool:
    return isinstance(exc, ConnectionRefusedError) or isinstance(
        getattr(exc, "reason", None), ConnectionRefusedError)


def _owner_autostart(exc: BaseException) -> bool:
    """Start the index owner when `exc` is a refused connection. True when a start was
    spawned. Never raises — this hook is additive-only."""
    if not OWNER_AUTOSTART or not _connection_refused(exc):
        return False
    try:
        try:
            if time.time() - OWNER_AUTOSTART_STAMP.stat().st_mtime < OWNER_AUTOSTART_EVERY_S:
                return False
        except FileNotFoundError:
            pass
        python = OWNER_VENV / "bin" / "python"
        if not python.exists():
            return False
        OWNER_AUTOSTART_STAMP.parent.mkdir(parents=True, exist_ok=True)
        OWNER_AUTOSTART_STAMP.write_text(str(os.getpid()), encoding="utf-8")
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        import subprocess
        with open(LOG_DIR / "index-owner.log", "ab") as log:
            subprocess.Popen([str(python), "-m", "skill_search.index_owner"],
                             stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                             start_new_session=True)
        return True
    except (OSError, ValueError):
        return False


def _project_row_verdict(scope: str, name: str) -> str:
    """For a project-scoped row (`<family>:<skills dir>`), one of:
    'other'   — the row belongs to a different project and this session holds no copy of it;
    'this'    — the row belongs to this session's project (or the test cannot be made);
    ''        — not a project-scoped row (personal/plugin/harness-personal/catalog).

    Same project means the row's project root (the skills dir's grandparent) is the cwd or an
    ancestor/descendant of it, compared on resolved paths — nested project layouts are kept,
    never guessed at: the drop needs positive knowledge that the two projects are unrelated.
    An 'other' row is still kept when the session dir or a parent holds a same-named copy at the
    same relative path. Any OSError reads as 'this' (keep). Not visible to this hook: skill dirs
    a session adds with --add-dir or /cd."""
    fam, sep, path = (scope or "").partition(":")
    if not sep or fam == "catalog" or not path:
        return ""
    try:
        # Root and relative path come from the UNRESOLVED scope path (the engine records
        # `<project>/.claude/skills` as found); resolving first would follow a symlinked skills dir
        # to its target and misplace the project (drop its own rows, or leak a `../skills` link's
        # rows into every sibling). Resolve only to compare.
        skills_dir = Path(path)
        raw_root = skills_dir.parent.parent
        root = raw_root.resolve()
        cwd = Path.cwd().resolve()
        if root == cwd or root in cwd.parents or cwd in root.parents:
            return "this"
        # Shared kit: the index keeps ONE point per skill name and the last project to reindex
        # owns its scope, so a same-named copy here (session dir or any parent — Claude Code
        # loads .claude/skills up to the repo root) makes the row invocable in this session.
        rel, bare = skills_dir.relative_to(raw_root), name.split(":", 1)[-1]
        if any((d / rel / bare / "SKILL.md").exists() for d in (cwd, *cwd.parents)):
            return "this"
        return "other"
    except (OSError, ValueError, RuntimeError):
        return "this"


def _scope_is_foreign(scope: str) -> bool:
    """Whether this harness cannot invoke rows of `scope` (before any twin rescue). Exact
    FOREIGN_SCOPES membership for machine-wide scopes; a same-project harness scope
    (`codex-project:<cwd>/.codex/skills`) takes the verdict of that harness's personal scope —
    OMP reads <cwd>/.codex/skills, Claude does not. Claude's own `project:` stays never-foreign."""
    fam, sep, path = (scope or "").partition(":")
    if not sep:
        return scope in FOREIGN_SCOPES
    if not PROJECT_ISOLATION or fam in ("project", "catalog"):
        return False
    if path.rstrip("/").endswith("/.agents/skills"):
        # The .agents convention root (indexed under zcode-project) is read by ZCode, OMP, Codex,
        # DSH, Cline and OpenCode (a documented compatibility source there); Claude Code reads
        # only .claude/skills. Command Code: unverified -> keep.
        return RUNNING_HARNESS == "claude"
    return fam.rsplit("-", 1)[0] + "-personal" in FOREIGN_SCOPES


def _retrieve(vector: list) -> list:
    """Top-k INSTALLED skills from Qdrant via raw REST (stdlib only), MAX-pooled: group_by name
    with one best point per skill (group_size=1). Returns [(name, desc, score)].

    ADR-0031 search-only tier: external catalog points (tier=external) are excluded from this
    query so the INSTALLED offer is exactly the top-k installed skills — byte-identical whether
    or not the ADR-0032 annex is enabled. The annex comes from a SEPARATE `_retrieve_external`
    call, so externals can NEVER displace an installed offer slot (the design's hard invariant).
    Two small queries beat one widened query, which would drop installed skills out of the limit
    window whenever externals ranked high in it.

    ADR-0034 cross-harness: rows the running harness cannot invoke are dropped HERE, per row
    (`_row_invocable`), after over-fetching to RETRIEVE_LIMIT — a post-filter, not a Qdrant
    `must_not scope`; the module's cross-harness block says why. Trimmed back to TOP_K, so the
    offer's width is unchanged. ENFORCER_CROSS_HARNESS=0 issues the pre-ADR-0034 request
    byte-identically."""
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
        if not _row_invocable(name, pl.get("scope")):
            continue
        out.append((name, pl.get("description", ""), float(hits[0].get("score", 0.0))))
        if len(out) >= TOP_K:
            break
    return out


def _retrieve_external(vector: list, top_installed: float = 0.0) -> list:
    """ADR-0032 external annex: up to EXTERNAL_SLOTS catalog skills clearing the per-turn annex
    gate, from a SEPARATE query filtered to tier=external. Returns [(name, desc, score, alias)].
    ADR-0048 complement gate (default): when the installed top clears GETAWAY_FLOOR the
    builtin answers the intent, so an external must BEAT that top by ANNEX_BEAT; below it
    (thin inventory) the plain EXTERNAL_FLOOR applies and the annex widens to cap. Rows
    then rank by demonstrated usage first (distinct-session get_skill takes, digest via
    auto_promote), score second. Kill-switch ENFORCER_ANNEX_COMPLEMENT=0 restores the
    ADR-0036/0047 competitive-margin floor and score-only order. A dedicated query (not a
    partition of a widened installed query) is what guarantees the installed offer is never
    displaced. Empty when the annex is off; the caller wraps this in a try/except so an
    external-query failure degrades to no-annex, never breaks the installed offer."""
    if not EXTERNAL_ANNEX:
        return []
    if ANNEX_COMPLEMENT and top_installed >= GETAWAY_FLOOR:
        floor = top_installed + ANNEX_BEAT      # well-served intent: complement, not echo
    elif ANNEX_COMPLEMENT:
        floor = EXTERNAL_FLOOR                  # thin intent: the case externals exist for
    else:
        floor = _annex_floor(EXTERNAL_FLOOR, top_installed)   # ADR-0047 margin rule
    res = _post_json(QUERY_GROUPS_URL,
                     {"query": vector, "group_by": "name", "limit": EXTERNAL_SLOTS * 3,
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
        name = pl.get("name", g.get("id", "?"))
        if _blocked(name):   # ADR-0046: a disabled skill gets no annex row either
            continue
        alias = str(pl.get("scope") or "").split(":", 1)[1] if ":" in str(pl.get("scope") or "") else "?"
        out.append((name, pl.get("description", ""), score, alias))
    if ANNEX_COMPLEMENT:
        takes = _external_takes()
        out.sort(key=lambda r: (-takes.get(r[0], 0), -r[2]))   # proven first, score second
    return out[:EXTERNAL_SLOTS]


def _retrieve_foreign(vector: list, top_installed: float = 0.0,
                      installed_bare: frozenset = frozenset()) -> list:
    """ADR-0034 cross-harness annex: the top skills in the OTHER harness's scopes scoring
    >= FOREIGN_FLOOR, from a SEPARATE query. Returns [(name, desc, score, harness)] — the
    harness whose roots hold that row's copy (`_scope_harness`), rendered per row.

    Skipped rows: an invocable twin (already IN the installed offer) and, ADR-0054, a row whose
    bare name is in `installed_bare` (the same skill re-rooted for another harness, e.g. `doctor`
    under ~/.ohdsh/skills beside the invocable `skill-concierge:doctor`). Listing either under
    "NOT invocable" would state the opposite of the truth. Over-fetches for the same reason
    `_retrieve` does, so a skipped twin does not cost a real annex slot.

    Same hard invariant as the ADR-0032 external annex: a dedicated query, never a partition of
    a widened installed query, so a foreign skill can NEVER displace an installed offer slot.
    FOREIGN_FLOOR (0.40) sits far above ITEM_FLOOR (0.18): a row the agent cannot invoke earns
    its place only on strong intent-match. Empty when the mechanism is off; the caller wraps
    this so a failed query degrades to no-annex.

    ADR-0036: the per-turn floor is `_annex_floor(FOREIGN_FLOOR, top_installed)` — same
    competitive-margin rule as the external annex, one mechanism for both."""
    if not CROSS_HARNESS:
        return []
    floor = _annex_floor(FOREIGN_FLOOR, top_installed)
    res = _post_json(QUERY_GROUPS_URL,
                     {"query": vector, "group_by": "name", "limit": FOREIGN_SLOTS * 3,
                      "group_size": 1, "with_payload": ["name", "description", "scope"],
                      "filter": {"must": [
                          {"key": "scope", "match": {"any": [
                              sc for sc in FOREIGN_SCOPES if sc != "claude-synced"]}}]}},
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
        if _invocable_twin(name) or _blocked(name):   # ADR-0046: blocked = no annex row
            continue
        if name.split(":", 1)[-1] in installed_bare:   # ADR-0054: re-rooted twin of an offered skill
            continue
        out.append((name, pl.get("description", ""), score, _scope_harness(pl.get("scope", ""))))
        if len(out) >= FOREIGN_SLOTS:
            break
    return out


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


def _route_of(seed: str, names_map: dict | None = None) -> list:
    """Bounded continuation walk from `seed` through the merged chain map: strongest
    successor per hop, cycle-safe (visited set), capped at _ROUTE_MAX, successors must
    be live map keys (the same catalogue-membership rule _chain_hint filters by).
    Returns [] when seed has no successors — a route of one node is not a route."""
    if not CHAIN_PROJECTION or not seed:
        return []
    names_map = names_map if names_map is not None else _visible_sidecar_names()
    route, seen = [seed], {seed}
    cur = seed
    while len(route) < _ROUTE_MAX:
        succ = names_map.get(cur)
        if not isinstance(succ, list):
            break
        nxt = next((s for s in succ
                    if isinstance(s, str) and s and s not in seen and s in names_map
                    and not _blocked(s) and _plugin_gate_ok(s)), None)
        if not nxt:
            break
        route.append(nxt)
        seen.add(nxt)
        cur = nxt
    return route if len(route) >= 2 else []


def _intent_plan(cands: list) -> tuple:
    """ADR-0041 multi-intent: (rows in render order, intent count) for the SHOWN set — the one
    computation the renderer and the ledger row both read. When >=2 clusters clear the strength
    gate, rows go leads-first; otherwise the list and its order are unchanged (one intent)."""
    if not (MULTI_INTENT and len(cands) > 1):
        return list(cands), 1
    clusters = _intent_clusters(cands)
    if not _multi_intent_gate(clusters):
        return list(cands), 1
    qual = _qualifying_intents(clusters)
    # ADR-0041 amendment (0.32.1): beyond MAX_INTENTS, extra clusters are a clustering miss
    # and fold back in as supporting rows, not announced intents.
    extras = []
    if len(qual) > MAX_INTENTS:
        ranked = sorted(qual, key=lambda c: -c[0][2])
        qual, extras = ranked[:MAX_INTENTS], [m for c in ranked[MAX_INTENTS:] for m in c]
    # leads-first: rows 1..N name the N primaries (one per intent), then the supporting rows
    # grouped behind their lead. Intra-cluster score order preserved within each group.
    return [c[0] for c in qual] + [m for c in qual for m in c[1:]] + extras, len(qual)


PREVIEW_HEAD = "Preview for this task (the top few of a shelf of hundreds, not the shelf):\n"
PREVIEW_TAIL = "None fit → run search_skills THIS reply before any NO SKILL; show the query. "
WHOLE_SHELF_HEAD = "Whole-shelf ranking for this task (every skill you can use judged):\n"
WHOLE_SHELF_TAIL = ("None fit, even loosely adapted → rule out the top row by name: NO SKILL: whole-shelf — "
                    "<top row>: <what it does>; <why this task lies outside it and the rows below>. Expect a "
                    "skill this ranking missed → run search_skills THIS reply with terms it may have missed "
                    "(a tool, a file type, a domain name). ")


def _ranked_mandate(cands: list, annex: list | None = None, foreign: list | None = None,
                    takes: dict | None = None, whole_shelf: bool = False,
                    pulled: list | None = None) -> str:
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
    ordered, n_intents = _intent_plan(cands)
    lines = [f"  • {name}{_badge(name)}{(f' ({round(score / total * 100)}%)' if multi else '')} — {_blurb(desc)}"
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
        takes = takes or {}
        alines = [f"  • {name} [external:{alias}{'' if not takes.get(name) else f', used {takes[name]}×'}] — {_blurb(desc)}"
                  for (name, desc, _s, alias) in annex]
        annex_block = (
            "\nExternal catalog matches (NOT installed here — consume via get_skill):\n"
            + "\n".join(alines) +
            "\nTo use one: `USING: <name>` then get_skill(\"<name>\") and follow its SKILL.md inline.")
    foreign_block = ""
    if foreign:
        flines = [f"  • {name} [{h}] — {_blurb(desc)}" for (name, desc, _s, h) in foreign]
        shown_in = "/".join(h for h in _HARNESS_ORDER if any(r[3] == h for r in foreign))
        foreign_block = (
            f"\nOther-harness matches (installed under {shown_in}, NOT "
            "invocable here — consume via get_skill):\n"
            + "\n".join(flines) +
            "\nTo use one: `USING: <name>` then get_skill(\"<name>\") and follow its SKILL.md inline.")
    # A router turn (`whole_shelf`) ranked every skill this session can use;
    # saying "the top few, not the shelf" there would misinform the agent. Its no-fit advice is to
    # search with terms the ranking could have missed, not to repeat its question.
    head, tail = ((WHOLE_SHELF_HEAD, WHOLE_SHELF_TAIL) if whole_shelf else (PREVIEW_HEAD, PREVIEW_TAIL))
    # ADR-0083: owner-badged rows Jev ranked below its cut, shown under the ranking, never in it.
    pulled_block = ""
    if pulled:
        pulled_block = ("\nOn the owner's list, ranked lower by Jev but judged a fit for this task:\n"
                        + "\n".join(f"  • {n}{_badge(n)} — {_blurb(d)}" for (n, d, _p) in pulled))
    marks = "".join(_badge(n) for n in [c[0] for c in cands] + [r[0] for r in (pulled or [])])
    legend = BADGE_LEGEND if ("❤️" in marks or "⭐" in marks) else (PROVEN_LEGEND if "🔥" in marks else "")
    return (
        "SKILL-FIRST · reply line 1 = USING: <skill> | SEARCH: <query> | NO SKILL: <why>.\n"
        + head + "\n".join(lines) + note + pulled_block + route_line + annex_block + foreign_block + "\n"
        + legend + tail + "A loosely-adaptable fit is a USING. [full order: session start]"
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


# ADR-0049 phase 2: consult-intent routing. A deliberation-shaped turn gets the
# consult skill MANDATED instead of the reflex offer — the funnel runs its own wide
# sieve, so the leg returns before any embed/retrieve I/O. Subagent sessions never
# route (ADR-0020: their payloads carry agent_id; a subagent consulting would recurse
# the deliberation lane). The ledger kind `consult_route` carries the prompt verbatim
# so false routes can be replayed from the ledger before the phrase list is widened
# (epoch-watch v0.43.0 watch item).
CONSULT_ROUTE = os.environ.get("SKILL_CONSULT_ROUTE", "1") != "0"
# High-precision EN phrase class v2 (widened 2026-08-30 from REPLAYED ledger evidence,
# per the epoch-watch W1 rule — never from vibes): the live first-dish miss was
# "which set of skills that we should be using" — intervening words, we-form, progressive
# — so the anchor pairs are now windowed (which/what … skills … modal … i/we) and accept
# the plural pronoun. The blind tester's parked over-fires (past-conditional
# "should I have used", org-talk "skills gap", reflexive past) are held out by
# _CONSULT_NEG_RE. A bare 'skill' noun still never fires.
_CONSULT_RE = re.compile(
    r"\b(?:which|what)\b[^.\n]{0,30}\bskills?\b[^.\n]{0,25}\b(?:should|do|can|to|would|might|shall)\b[^.\n]{0,12}\b(?:i|we)\b"
    r"|\b(?:which|what) skills? (?:to|for)\b"
    r"|\bwhich (?:combo|chain|set|mix|sequence) of skills?\b"
    r"|\bskill[-\s]strateg(?:y|ies)\b"
    r"|\bbest (?:combo|chain|combination|set|sequence|mix) of skills?\b"
    r"|\b(?:consult|curate)\b[^.\n]{0,40}\bskills?\b"
    r"|\bconsult which\b",
    re.IGNORECASE)
# Tense/reflexive/genre guards — a positive match with any of these stays silent.
_CONSULT_NEG_RE = re.compile(
    r"\bshould (?:i|we) have\b"
    r"|\bdid (?:you|i|we) (?:just )?(?:use|pick|choose|run|invoke)\b"
    r"|\bskills? gap\b",
    re.IGNORECASE)
CONSULT_MANDATE = (
    "CONSULT-ROUTE · this turn asks for a deliberated skill curation.\n"
    "reply line 1 = USING: skill-concierge:consult\n"
    "Invoke the consult skill NOW with the user's task as its argument; it composes the "
    "chain, including any follow-on work the task names. Answer the \"which skills\" "
    "question from its verdict card, never from a per-turn preview alone. Routed consults "
    "default to --fast unless the user asks to go deep.")


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

        # ADR-0054 harness-message lane (no I/O): text the harness generated — task
        # notifications, monitor events, cross-session/teammate messages, idle reminders,
        # OMP summarizer calls — is not a user task. Authorize the skip and stop before the
        # refusal guard, consult route, embed and every Qdrant round-trip. Anchored at the
        # prompt head so a user who PASTES such a block mid-prompt is still routed normally.
        if HARNESS_SKIP and _HARNESS_MSG_RE.match(prompt):
            _append_offer(sid, "harness_skip", [], "harness_message", prompt)
            _authorized_skip_inject("harness", sid, hint=False)
            return 0

        # Explicit skill-refusal -> MANDATE-ONLY (never surface the skill the user
        # just refused; keep the SKILL-FIRST discipline live). See _REFUSAL_RE.
        if _REFUSAL_RE.search(prompt):
            _inject(MANDATE)
            _append_offer(sid, "negation", [], "skill_refusal", prompt)
            return 0

        # ADR-0049 phase 2: consult-intent → mandate the deliberation lane and return
        # BEFORE the embed/retrieve pipeline (the funnel sieves itself; paying the
        # reflex offer's I/O here would be the exact waste the annex-position note
        # below warns about). Runs after the refusal guard: an explicit user refusal
        # of skill behavior outranks routing into a skill-planning turn.
        if (CONSULT_ROUTE and not data.get("agent_id")
                and _CONSULT_RE.search(prompt) and not _CONSULT_NEG_RE.search(prompt)):
            _inject(CONSULT_MANDATE)
            _append_offer(sid, "consult_route", [], "consult_intent", prompt)
            return 0

        # H5 over-fire lane (no I/O): a purely self-referential recap of the agent's OWN prior
        # message needs no skill — authorize the skip instead of forcing a pointless search. Narrow
        # by construction (see _is_selfref); any task tail falls through to normal routing below.
        if SELFREF_SKIP and _is_selfref(prompt):
            _append_offer(sid, "selfref_skip", [], "self_referential", prompt)
            _authorized_skip_inject("selfref", sid)
            return 0

        # ADR-0054: deterministic routes run BEFORE the embed step (pure, no I/O) so a skill
        # the user NAMED still leads the menu when the shim or Qdrant times out — 4 of the 11
        # named-and-missed prompts in the v0.46.0 epoch were lost on exactly that path.
        _hits = _route_hits(prompt, KEEPOFF)
        _hits_offered = [[n, 1.0] for (n, _d, _s) in _hits]

        # ADR-0061 Jev skill router: after every no-I/O lane; started NOW in a worker thread so
        # it overlaps the embed and Qdrant legs, joined once retrieval is done. A NAMED skill
        # (deterministic hit) is explicit intent and never asks Jev.
        _jev_job = _jev_start(prompt, data.get("transcript_path") or "") if not _hits else None

        def _fallback(reason: str, **ms) -> int:
            """Outage leg: the Jev verdict if one arrived, else the named hits or MANDATE-ONLY."""
            if _jev_serve(sid, prompt, _jev_join(_jev_job), _hits_offered, reason, **ms):
                return 0
            _inject((_ranked_mandate(_hits) if _hits else MANDATE) + _chain_hint(sid))
            _append_offer(sid, "fallback", _hits_offered, reason, prompt, **ms)
            return 0

        # Embed (HARD timeout, EMBED_TIMEOUT_S) → mandate-only on down/slow (named hits survive).
        embed_ms = None
        t0 = time.time()
        try:
            vector = _embed(prompt)
            embed_ms = (time.time() - t0) * 1000
        except TimeoutError:
            return _fallback("embed_timeout", embed_ms=(time.time() - t0) * 1000)
        except (OSError, UnicodeError, ValueError, TypeError, AttributeError, KeyError) as exc:
            embed_ms = (time.time() - t0) * 1000
            _owner_autostart(exc)
            return _fallback("embed_down", embed_ms=embed_ms)
        # Retrieve → mandate-only fallback if Qdrant is unreachable.
        qdrant_ms = None
        t1 = time.time()
        try:
            cands = _retrieve(vector)
            qdrant_ms = (time.time() - t1) * 1000
        except (OSError, UnicodeError, ValueError, TypeError, AttributeError, KeyError, IndexError):
            return _fallback("qdrant_down", embed_ms=embed_ms, qdrant_ms=(time.time() - t1) * 1000)
        # P5 (ADR-0011): hard-drop chronic never-take skills BEFORE floors/gate/rank, so they
        # vanish from the menu. Fail-open (KEEPOFF empty -> no-op).
        cands, _dropped = _drop_keepoff(cands, KEEPOFF)
        # ADR-0046: user-ordered disable outranks everything — a blocked skill never
        # reaches floors, gates, or the menu. Dropped names ride the same `dropped`
        # field so the ledger keeps the full picture.
        cands, _bl_dropped = _drop_blocklisted(cands)
        _dropped = _dropped + _bl_dropped

        if _hits:   # a named skill leads the menu and bypasses both gates below
            cands = _merge_route_hits(_hits, cands)

        top = cands[0][2] if cands else 0.0
        offered = [[n, round(s, 4)] for (n, _d, s) in cands]

        # ADR-0061: a Jev verdict replaces the embedding getaway/actionability gates and the
        # menu; the embedding results still size the annexes. `offered` in a jev_skip row is
        # what retrieval would have shown, kept for comparison.
        _jev = _jev_join(_jev_job)
        if _jev is not None and _jev[0] == "skip":
            _append_offer(sid, "jev_skip", offered, "jev_no_fit", prompt, dropped=_dropped or None,
                          embed_ms=embed_ms, qdrant_ms=qdrant_ms)
            _authorized_skip_inject("jev", sid, fit=_jev[2], floor=JEV_FITS_FLOOR)
            return 0
        _jev_rows = _jev[1] if _jev is not None else None
        _jev_pulled = (_jev[3] if _jev is not None and len(_jev) > 3 else []) or []

        # Getaway: top candidate below the global floor. A deterministic hit always clears —
        # it IS the intent. ADR-0061 (owner-approved 2026-09-26): on a turn the Jev router
        # decided (`_jev_rows`), Jev's verdict replaces this floor and the actionability gate
        # below — measured on 313 real English skill turns, these two gates wrongly skip 24,
        # Jev 1. Every other turn keeps both.
        if not _hits and not _jev_rows and top < GETAWAY_FLOOR:
            # No semantic fit → trivial/out-of-catalogue. Log the consideration so
            # coverage/fallback stats stay honest, then authorize the skip (or stay fully
            # silent if the kill-switch is off) instead of leaving the agent to re-derive
            # this verdict via a fresh search_skills call.
            _append_offer(sid, "getaway", offered, None, prompt, dropped=_dropped or None, embed_ms=embed_ms, qdrant_ms=qdrant_ms)
            _authorized_skip_inject("getaway", sid, top=top, floor=GETAWAY_FLOOR)
            return 0

        # Actionability gate (prior-independent class-margin). A relevant skill cleared the
        # floor — but if this is a NON-imperative turn that leans conversational over
        # actionable, the offer is noise the agent reliably dodges. Suppress it. Fail toward
        # offering (imperative OR any error -> offer). Backtest ~2% false-suppression; fires on novel input.
        if not _hits and not _jev_rows and not _is_imperative(prompt) and _intent_conversational(vector):
            _append_offer(sid, "intent_skip", offered, "conversational", prompt, dropped=_dropped or None, embed_ms=embed_ms, qdrant_ms=qdrant_ms)
            _authorized_skip_inject("intent_skip", sid)
            return 0

        # Annex queries, issued ONLY once the turn is known to carry an offer.
        #
        # Both are SEPARATE queries so `cands` (installed) and the whole pipeline above
        # (keepoff, deterministic, getaway, intent gate, ITEM_FLOOR) run
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
        try:
            _external = _retrieve_external(vector, top)
        except (OSError, UnicodeError, ValueError, TypeError, AttributeError, KeyError, IndexError):
            _external = []
        try:
            _foreign = _retrieve_foreign(
                vector, top, frozenset(n.split(":", 1)[-1] for (n, _d, _s) in
                          (_jev_rows or []) + (_jev_pulled if _jev_rows else []) + cands))
        except (OSError, UnicodeError, ValueError, TypeError, AttributeError, KeyError, IndexError):
            _foreign = []

        if _jev_rows:   # ADR-0061: the rerank Choice's top JEV_OFFER_ROWS, in its order
            shown = _jev_rows
        else:
            shown = [(n, d, s) for (n, d, s) in cands if s >= ITEM_FLOOR] or cands[:1]
        _ext_takes = _external_takes() if (ANNEX_COMPLEMENT and _external) else None
        _pulled = _jev_pulled if _jev_rows else []
        _inject(_ranked_mandate(shown, annex=_external, foreign=_foreign, takes=_ext_takes,
                                whole_shelf=bool(_jev_rows), pulled=_pulled) + _chain_hint(sid))
        _ni = _intent_plan(shown)[1]   # ADR-0041: the same plan the renderer used
        _append_offer(sid, "offer",
                      [[n, round(s, 4)] for (n, _d, s) in shown], None, prompt,
                      dropped=_dropped or None, embed_ms=embed_ms, qdrant_ms=qdrant_ms,
                      ext=[[n, round(s, 4)] for (n, _d, s, _a) in _external] or None,
                      xh=[[n, round(s, 4)] for (n, _d, s, _h) in _foreign] or None,
                      n_intents=_ni, route=_route_of(shown[0][0]) if shown else None,
                      hint=_chain_hint_data(sid),
                      pulled=[[n, round(s, 4)] for (n, _d, s) in _pulled] or None)
    except (OSError, UnicodeError, ValueError, TypeError, AttributeError, KeyError, IndexError,
            OverflowError):
        return 0  # fail-silent, never block
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        # chisle: the --selftest CLI is cited by immutable ADRs; its body lives in tests/ so the
        # per-prompt hook never compiles it. Exec'd in this namespace, so its globals are ours.
        _st = Path(__file__).resolve().parents[2] / "tests" / "enforcer_selftest.py"
        try:
            _src = _st.read_text(encoding="utf-8")
        except OSError:
            print(f"enforcer --selftest: {_st} not found (stripped install?)", file=sys.stderr)
            sys.exit(2)
        exec(compile(_src, str(_st), "exec"), globals())
        sys.exit(globals()["_selftest"]())  # defined by the exec above
    _rc = main()
    if _DEFERRED:
        try:
            sys.stdout.write(json.dumps(_DEFERRED, allow_nan=False))
        except (ValueError, TypeError, OSError):   # an unwritable value must never cost the turn its menu
            if "hookSpecificOutput" in _DEFERRED:
                sys.stdout.write(json.dumps({"hookSpecificOutput": _DEFERRED["hookSpecificOutput"]}))
    sys.exit(_rc)
