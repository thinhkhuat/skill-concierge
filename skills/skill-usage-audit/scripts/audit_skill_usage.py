"""Audit real skill USAGE from Claude Code's transcript store — the source that
answers "do agents know + use the RIGHT skill", which the invocation-ledger does NOT.

Counts three signals over ~/.claude/projects/**/*.jsonl, optionally windowed to a
post-change ship time, with self/meta (dogfood) sessions flagged so organic usage
is separable:

  1. Skill-tool invocations  : assistant tool_use blocks  name=="Skill" -> input.skill
  2. /slash invocations      : <command-name>/foo</command-name> typed by the user
  3. SKILL-FIRST trail        : assistant text lines 'USING <skill>' / 'SEARCH' / 'SKIPPING'
                                — the ONLY signal that captures INLINE skill use (declare +
                                read SKILL.md + execute, no Skill tool fired). The ledger and
                                the usage-tracker both miss this.
  4. FALSE-SKIPPING verdict    : per turn, did a 'SKIPPING' declaration fire WITHOUT a real
                                search_skills call in the same turn? (the doctrine's hardest
                                rule — 'no search, no skip'). The ledger can't see this; it
                                needs the transcript declaration trail joined per turn.

Names are canonicalized (strip '/', drop args, ':'->'-', lowercase) so 'ck:journal'
merges with 'journal' before any counting/join.

H3 (ADR-0020) scopes the real-usage denominator: subagent (Task sidechain) turns and dispatched
team-teammate sessions are excluded from the ORGANIC counts (global totals stay whole). H1
(ADR-0021) adds --harvest: capture the verbatim SKIPPING clauses of false-skip turns (scrubbed,
gitignored, local-only) to feed doctrine authoring. Both are default-ON behind SKILL_SUBAGENT_STOP
(=0 reverts to byte-identical pre-H3 output). --harvest is dodge-rate machinery, NOT a usefulness
metric, and the re-measure leg is epoch-scoped (see ADR-0021 / AGENTS.md Guardrails).

Pure stdlib, read-only (except --harvest, which writes only its gitignored sink). Usage:
  python3 audit_skill_usage.py [--since "YYYY-MM-DD HH:MM:SS"] [--meta-keyword KW ...]
  python3 audit_skill_usage.py --since "2026-06-29 01:06:35"
  python3 audit_skill_usage.py --harvest            # -> ./logs/skill-rationalizations.txt
  SKILL_SUBAGENT_STOP=0 python3 audit_skill_usage.py   # revert H3 scoping
"""
import argparse
import datetime as dt
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict

PROJECTS = os.path.join(os.path.expanduser("~"), ".claude", "projects")

# Default self/meta markers: prompts about auditing/tuning the gate itself are NOT organic
# usage. Override/extend with --meta-keyword. Kept conservative on purpose.
DEFAULT_META = ["skill-concierge", "enforcer", "gate floor", "getaway_floor",
                "max_short_words", "dogfood", "threshold", "impact analysis",
                "skill-usage-audit", "verify-as-claimed"]

# Where a ruling may start. Bare at the line start, the old optional-colon forms still read; inside
# markdown (`USING: x`, **SEARCH:** y, > NO SKILL: z) the colon is required, so a bold prose heading
# ("**Search results**") is not a ruling. `{w}` is the ruling word(s).
_LEAD = r'^(?:[ \t]*|[ \t`*>]*[`*>][ \t]*(?={w}:))'
# A name wrapped in markdown (`USING: `x``) reads only after the colon: "Using `rg` to …" is prose.
_USING = re.compile(r'(?im)' + _LEAD.format(w='USING')
                    + r'USING(?::[*`]*\s+[`*]*|\s+)([a-z0-9][a-z0-9:_\-]*)')
# Rule 3's continuation (ADR-0063/0064): `USING: <name> (continuing)`, and the forms agents write —
# `(continuing the earlier work)`, `(continued …)`, `(continuation …)`, several names joined by + , &.
# The bare `USING <name> (continuing)` reads in capitals only, as `_USING` reads it ("Using rg
# (continuing …)" is prose). A parenthetical that negates the word itself — "(not continuing x)",
# "(instead of continuing x)" — or names a new task or new work, as an agent obeying the red-flags
# row writes, is a fresh ruling. A negation elsewhere in the note ("same task, no new search —
# continuing", "not a new task — continuing") is the doctrine's own justification and still reads.
_NEGATED_NOTE = (r"[^)\n]*?(?:\b(?:not|no|never)\s+(?:a\s+|an\s+)?continu|n't\s+continu"
                 r"|\b(?:instead\s+of|rather\s+than|without)\s+continu"
                 r"|(?<!not a )(?<!no )\bnew\s+(?:task|work)\b)")
_CONTINUING = re.compile(r'(?im)' + _LEAD.format(w='USING')
                         + r'(?:USING:[*`]*\s+|(?-i:USING)\s+)([^\n(]*?)[`*\s]*\('
                         + r'(?!' + _NEGATED_NOTE + r')'
                         + r'[^)\n]*\bcontinu(?:ing|ed|ation)\b[^)\n]*\)')
_FILLER = {"then", "and", "also", "plus", "with", "for", "name", "skill"}
_SKILL_NAME = re.compile(r'[a-z0-9][a-z0-9:_\-]*', re.I)
STALE_TURNS = 5   # a continuation whose skill was last used more turns ago than this is likelier new work


def _continued_names(txt):
    """The skill names an assistant text continues, in order, without repeats. The first part
    names its skill in its first word ("ak-cook for the build"). A later part names one when it is a
    single word after filler ("then study") or opens with a hyphenated or namespaced name
    ("+ ak-git for the commit"), so prose after a comma ("then run the tests") is not read."""
    out = []
    for grp in _CONTINUING.findall(txt):
        for i, part in enumerate(re.split(r"\s*(?:\+|,|&|\band\b)\s*", grp)):
            words = [w.strip("`*") for w in part.split() if w.strip("`*").lower() not in _FILLER]
            if not words or (i and len(words) > 1 and not re.search(r"[-:]", words[0])):
                continue
            m = _SKILL_NAME.match(words[0])   # anchored: the quoted `<name>` placeholder never matches
            n = norm(m.group(0)) if m else None
            if n and n not in _NOT_A_SKILL and n not in _FILLER and n not in out:
                out.append(n)
    return out


def _continuation_counts(units):
    """(total, re-read in the turn, no earlier use this session, last used > STALE_TURNS turns ago)."""
    return (len(units), sum(1 for u in units if u[3]), sum(1 for u in units if u[4] is None),
            sum(1 for u in units if u[4] is not None and u[4] > STALE_TURNS))


# Which prompt heads hand the agent work. A `<tag>` record is harness output (notifications,
# local-command output, `!` shell echoes, teammate messages) except pasted content and a pasted
# HTML comment. A slash command is work when it carries arguments (`/ak:cook fix the parser`),
# unless it is a builtin that configures the session. A bracketed head is typed text (a relayed
# chat message) except the notices below — the enforcer's harness-message lane plus scheduled tasks.
_WORK_TAGS = ("<pasted_content", "<!--")
_NOT_WORK_BRACKETS = ("[Request interrupted", "[Scheduled Task", "[Cross-session idle notice]",
                      "[SYSTEM NOTIFICATION")
_NOT_WORK_TEXT = ("Another Claude session", "/compact",
                  # a team runner's inbox relays and scaffolding (no origin fields of their own)
                  "## New Messages", "## Team Governance", "## Turn Context", 'Team: "')
# The harness's own record fields, where present, decide before the text does: an origin other than
# a human (a task notification, an auto-continuation), a system prompt, or an SDK prompt sent by a
# program (`sdk-ts`/`sdk-cli` entrypoints: summarizers, probes, evals) is not work. A typed prompt
# (`origin.kind` human, or a typed/queued/accepted-suggestion `promptSource`) passes the list-form
# guard, so "[Image #1] what is this" reads; its text still goes through the head rules.
_TYPED_SOURCES = ("typed", "queued", "suggestion_accepted")
_BUILTIN_COMMANDS = {"add-dir", "cd", "clear", "compact", "config", "effort", "export", "fast",
                     "model", "plugin", "reload-plugins", "resume", "theme"}
_CMD_ARGS = re.compile(r"<command-args>([\s\S]*?)</command-args>")


def role_is_user_prompt(rec, msg):
    """A user record whose content is the prompt string (not a tool result echoing a transcript)."""
    return rec.get("type") == "user" and isinstance(msg, dict) and isinstance(msg.get("content"), str)


def _prompt_text(rec):
    """A user record's prompt: its string content, or the text of a list holding only text and
    image blocks (a typed prompt stored in list form). None for anything else — a tool result."""
    msg = rec.get("message")
    c = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(c, str):
        return c
    if isinstance(c, list) and c and all(isinstance(b, dict) and b.get("type") in ("text", "image") for b in c):
        return " ".join(b.get("text", "") for b in c if b.get("type") == "text")
    return None


def _hands_over_work(rec):
    """True for a user prompt that hands the agent work: typed text, a relayed chat message, pasted
    content or a skill command with arguments — not a harness, hook, notification or compaction
    record. The stale gap counts only these."""
    if rec.get("type") != "user" or rec.get("isMeta") or rec.get("isCompactSummary"):
        return False
    s = _prompt_text(rec)
    if s is None:
        return False
    origin = rec.get("origin") if isinstance(rec.get("origin"), dict) else {}
    kind, source = origin.get("kind"), rec.get("promptSource")
    if (kind not in (None, "human") or source == "system"
            or (source == "sdk" and str(rec.get("entrypoint") or "").startswith("sdk-"))):
        return False
    typed = kind == "human" or source in _TYPED_SOURCES
    s = s.lstrip()
    if not s:
        return False
    if not typed and not isinstance(rec["message"]["content"], str) and s[0] in "<[":
        return False   # list-form wrappers: interrupts, relayed conversation history
    if s.startswith("<command-"):
        name, args = _CMD.search(s), _CMD_ARGS.search(s)
        return bool(name and args and args.group(1).strip() and norm(name.group(1)) not in _BUILTIN_COMMANDS)
    if s.startswith("<"):
        return s.startswith(_WORK_TAGS)
    if s.startswith("["):
        return not s.startswith(_NOT_WORK_BRACKETS)
    return not s.startswith(_NOT_WORK_TEXT)


def _same_skill(a, b):
    """Name forms of one skill: `plugin:name` (normalized `plugin-name`) and bare `name`."""
    return a == b or a.endswith("-" + b) or b.endswith("-" + a)


def _loaded_skill(blk):
    """The skill a tool_use block loads — the Skill tool or skill-search's own get_skill — or None."""
    nm = blk.get("name") or ""
    if nm != "Skill" and not (("skill-search" in nm or "skill_search" in nm) and nm.endswith("get_skill")):
        return None
    inp = blk.get("input") or {}
    return norm(inp.get("skill") or inp.get("name") or inp.get("skill_name") or inp.get("command"))
_SEARCH = re.compile(r'(?im)' + _LEAD.format(w='SEARCH') + r'SEARCH:?[*`]*\s+')
# The skip ruling. `NO SKILL: <why>` since v0.52.0 (ADR-0062); the old `SKIPPING: none` still
# reads, so transcripts from before the rename stay comparable. The new form needs its colon —
# prose opening "No skill applies…" is not a ruling; `No skill: <why>` in any case is.
_SKIPPING = re.compile(r'(?im)' + _LEAD.format(w='(?:SKIPPING|NO SKILL)')
                       + r'(?:(?P<old>SKIPPING):?[*`]*\s+|(?P<new>NO SKILL):)')
_NO_SKILL_ANY_CASE = re.compile(r'(?i)NO SKILL:')   # raw-line prefilter for _SKIPPING's new form
# Doctrine rule 3 (v0.49.0): a re-rule line — the reply switching away from a skill whose loaded
# body excludes the task — ends `(re-rule: <old>)`. The old skill's USING is retracted, not uptake.
_RERULE = re.compile(r'(?im)' + _LEAD.format(w='(?:USING|SEARCH)')
                     + r'(?:USING|SEARCH):?[*`]*\s+[^\n]*\(re-rule:\s*([a-z0-9][a-z0-9:_\-]*)\s*\)')
_NOT_A_SKILL = ("the", "none", "a", "an", "it", "this", "that")
_CMD = re.compile(r"<command-name>\s*(/?[^<]+?)\s*</command-name>")
# The semantic-search tool, normalized — a SKIPPING is only lawful if one of these fired
# in the same turn (an actual search_skills call, not a bare `SEARCH:` line which is itself
# the 'ritual SEARCH' failure mode).
_SEARCH_SLUGS = {"skill-search", "skill-concierge-skill-search"}
# Cross-file contract with hooks/scripts/enforcer.py (Phase 1) — keep in sync. The enforcer
# injects this literal marker on its two silent verdict legs (getaway skip, intent skip) to
# pre-authorize a skip ruling; a turn carrying it is a lawful hook-authorized skip, not a false
# skip. Only the enforcer's own hook output may carry it (see _enforcer_output).
AUTHORIZED_SKIP_MARKER = "SKILL-CHECK:"


def _note_used(rec, last_used, turn_no):
    """Record in `last_used` (name -> turn number) the skills a record uses: Skill / get_skill calls,
    USING lines, a user's slash command."""
    msg = rec.get("message")
    if role_is_user_prompt(rec, msg):
        for m in _CMD.findall(msg["content"]):
            if norm(m):
                last_used[norm(m)] = turn_no
    if rec.get("type") != "assistant" or not isinstance(msg, dict) or not isinstance(msg.get("content"), list):
        return
    for blk in msg["content"]:
        if not isinstance(blk, dict):
            continue
        if blk.get("type") == "tool_use":
            n = _loaded_skill(blk)
            if n:
                last_used[n] = turn_no
        elif blk.get("type") == "text":
            for n in _declared(blk.get("text", ""))[0]:
                last_used[n] = turn_no


# How every enforcer output string begins (hooks/scripts/enforcer.py: MANDATE / _ranked_mandate,
# the *_SKIP_MSG legs, CONSULT_MANDATE). Keep in sync with those constants.
_ENFORCER_HEADS = ("SKILL-FIRST", AUTHORIZED_SKIP_MARKER, "CONSULT-ROUTE")


def _enforcer_output(rec):
    """The strings the enforcer itself injected in this record, or [] — its UserPromptSubmit
    hook output, as the harness stores it: an `attachment` of type `hook_additional_context`
    whose content string starts with one of _ENFORCER_HEADS. Nothing else counts: not the agent's
    text, a tool result, a typed prompt, another hook's output (file echoes, memory recalls), an
    instructions/memory/@-file attachment or the SessionStart standing order — any of those can
    quote an authorization line, and counting it would let an agent authorize itself."""
    a = rec.get("attachment")
    if rec.get("type") != "attachment" or not isinstance(a, dict):
        return []
    if a.get("type") != "hook_additional_context" or a.get("hookEvent") != "UserPromptSubmit":
        return []
    c = a.get("content")
    return [x for x in (c if isinstance(c, list) else [c])
            if isinstance(x, str) and x.lstrip().startswith(_ENFORCER_HEADS)]

# ── H3 subagent/dispatch scoping (ADR-0020) ───────────────────────────────────
# Default-ON, one-var revert (mirrors ENFORCER_AUTHORIZED_SKIP / SKILL_BODY_TRIGGERS).
# SKILL_SUBAGENT_STOP=0 restores byte-identical pre-H3 output.
SKILL_SUBAGENT_STOP = os.environ.get("SKILL_SUBAGENT_STOP", "1") != "0"

# Subagent (Task sidechain) transcripts live in their OWN file under a `subagents/` dir yet carry
# the PARENT session's sessionId — so they can NOT be excluded by sid (that would drop the parent's
# organic turns too). Detect per FILE by path. Verified against the live store: every isSidechain
# file is under this path and 0 files mix parent+subagent records, so the file flag is exact.
_SUBAGENT_PATH = os.sep + "subagents" + os.sep

# Dispatched (team teammate / spawned-agent) sessions ARE top-level (own sid) and carry injected
# team-governance scaffolding. These 3 phrases are prose-unlikely and appear ONLY in that
# scaffolding (grounded on the store: 0 hits under /subagents/, ~7-9 dispatched sessions each) —
# matched against the RAW line (not the 400-char-capped sess_text) so the marker is never truncated.
_DISPATCH_MARKERS = ("You are a Team Member", "You have been spawned as a teammate",
                     "Team Coordination Tools")

# ── H1 rationalization harvest (ADR-0021) ─────────────────────────────────────
# The enforcer's AUTHORIZED-skip signature substrings. A captured SKIPPING clause echoing one of
# these is a LAWFUL, hook-authorized skip — NEVER a rationalization to harvest (else H2 would
# refute the excuse the enforcer just authorized, Red-Team F4/F8). Keep in sync with
# GETAWAY_SKIP_MSG / INTENT_SKIP_MSG / SELFREF_SKIP_MSG / HARNESS_SKIP_MSG / JEV_SKIP_MSG (ADR-0061) in hooks/scripts/enforcer.py.
_AUTHORIZED_SIGNATURES = ("full-catalogue retrieval ran", "intent-margin classifier",
                          "self-referential recap lane", "harness-message lane",
                          "Jev needs-a-skill gate")


def _is_authorized_skip_line(line):
    """True iff `line` is the enforcer's OWN SKILL-CHECK authorization line — anchored on its
    five message signatures (_AUTHORIZED_SIGNATURES), NOT the bare marker. The marker literal
    also appears in the skill-first.md doctrine and in any prose/tool-result that discusses the
    feature; matching those would over-count authorized_skip and mask false-skips. Fails SAFE:
    if the enforcer wording drifts from these signatures we under-count authorized (over-flag
    false), never the reverse. Single source of truth for count-side (saw_marker) AND harvest-side
    (H1 exclusion) so the two legs can never drift. Keep _AUTHORIZED_SIGNATURES in sync with
    GETAWAY_SKIP_MSG / INTENT_SKIP_MSG / SELFREF_SKIP_MSG / HARNESS_SKIP_MSG / JEV_SKIP_MSG (ADR-0061) in hooks/scripts/enforcer.py."""
    return AUTHORIZED_SKIP_MARKER in line and any(s in line for s in _AUTHORIZED_SIGNATURES)

# Default harvest sink — gitignored scratch under logs/ (never committed; see ADR-0021 + .gitignore).
DEFAULT_HARVEST_SINK = os.path.join("logs", "skill-rationalizations.txt")

# Minimal secret/path scrub for the harvest sink (data-safety, Red-Team F7). Redacts absolute home
# paths and common token shapes so a verbatim clause can't leak a secret/path. Best-effort, not a
# vault — the sink is gitignored + local-only regardless.
_SCRUB = [
    (re.compile(r'/Users/[^/\s]+'), '/Users/<user>'),
    (re.compile(r'/home/[^/\s]+'), '/home/<user>'),
    (re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b'), '<email>'),
    (re.compile(r'\b(?:sk|pk|ghp|gho|xox[baprs])[-_][A-Za-z0-9]{10,}\b'), '<token>'),
    (re.compile(r'\b[A-Fa-f0-9]{32,}\b'), '<hex>'),
]


def norm(name):
    """Canonicalize a skill/slash name so namespaced and bare forms merge."""
    if not name:
        return None
    name = name.strip().lstrip("/")
    parts = name.split()
    name = (parts[0] if parts else name).replace(":", "-").lower()
    return name or None


def _declared(txt):
    """(USING names declared in an assistant text, names a re-rule line in it retracts). A second
    USING without the marker is a multi-intent reply and retracts nothing. Pure so --selftest pins
    the counting."""
    used = [n for n in (norm(m) for m in _USING.findall(txt)) if n and n not in _NOT_A_SKILL]
    return used, [n for n in (norm(m) for m in _RERULE.findall(txt)) if n]


def _tally(used, retracted, sid, using, sess_raw, rerules):
    """Count one assistant text's declarations. A retraction undoes only a USING the SAME session
    declared (floor 0) — another session's USING of that skill is never touched, whatever the file
    order. Every retraction is tallied in `rerules`. Returns the names actually undone. Pure (only
    mutates the passed counters) so --selftest pins it."""
    for n in used:
        using[n] += 1
        sess_raw[sid][n] += 1
    undone = []
    for n in retracted:
        rerules[n] += 1
        if sess_raw[sid][n] > 0:
            sess_raw[sid][n] -= 1
            using[n] -= 1
            undone.append(n)
    return undone


def build_catalogue():
    """Every SKILL.md-backed skill name (normalized) — used to exclude builtin slashes
    (/clear, /compact, /plugin, ...) from the user channel so they don't inflate usage."""
    cat = set()
    for base in (os.path.join(os.path.expanduser("~"), ".claude", "skills"),
                 os.path.join(os.path.expanduser("~"), ".claude", "plugins")):
        for sm in glob.glob(os.path.join(base, "**", "SKILL.md"), recursive=True):
            n = norm(os.path.basename(os.path.dirname(sm)))
            if n:
                cat.add(n)
    return cat


def ts_epoch(rec):
    t = rec.get("timestamp")
    if not isinstance(t, str):
        return None
    try:
        return dt.datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp()
    except (OSError, OverflowError, ValueError):
        return None


def parse_since(s):
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(s, fmt).astimezone().timestamp()
        except ValueError:
            continue
    raise SystemExit(f"--since: cannot parse '{s}' (epoch or 'YYYY-MM-DD HH:MM:SS')")


def _skip_verdicts(turns):
    """Pure verdict over per-turn flags [{'saw_search':bool,'saw_skip':bool,'saw_marker':bool}, ...].

    Returns (false_skip, lawful_skip, authorized_skip). The doctrine's hardest rule is 'no
    search, no skip': a turn that DECLARED `SKIPPING` with NO `search_skills` call in the
    SAME turn is a false skip; one with a search is lawful. A turn carrying the enforcer's
    AUTHORIZED_SKIP_MARKER is a lawful, hook-pre-authorized skip — tallied separately as
    `authorized_skip` so it never inflates the false-skip count, even without a search.
    Turns without a SKIPPING are ignored. Kept pure so --selftest pins the branching without
    touching the filesystem."""
    false_skip = lawful_skip = authorized_skip = 0
    for t in turns:
        if not t.get("saw_skip"):
            continue
        if t.get("saw_marker"):
            authorized_skip += 1
        elif t.get("saw_search"):
            lawful_skip += 1
        else:
            false_skip += 1
    return false_skip, lawful_skip, authorized_skip


def _scrub(text):
    """Redact obvious secrets/paths from a harvested clause before it hits the (gitignored) sink."""
    for pat, repl in _SCRUB:
        text = pat.sub(repl, text)
    return text


def _looks_authorized(clause):
    """A captured SKIPPING clause echoing an enforcer AUTHORIZED-skip signature is a lawful skip,
    not a rationalization — never harvest it (Red-Team F4/F8; re-verify item 2e, all 3 live msgs
    incl. SELFREF)."""
    return any(sig in clause for sig in _AUTHORIZED_SIGNATURES)


def _false_skip_turns(turns):
    """Pure: turns that declared SKIPPING with NO same-turn search and NO authorized marker — the
    false skips whose rationalizations H1 harvests."""
    return [t for t in turns
            if t.get("saw_skip") and not t.get("saw_search") and not t.get("saw_marker")]


def _harvest_corpus(turns, meta_sessions=None, subagent_stop=True):
    """Pure: deduped rationalization corpus (clause -> count) over false-skip turns, scrubbed at
    capture. When subagent_stop is on, EXCLUDES self/meta/dispatch sessions (by sid) and subagent
    turns (by the per-file `sub` flag — subagent files share the parent sid, so sid can't separate
    them). Authorized skips are dropped regardless of the flag. Kept pure so --selftest pins the
    filter without touching the filesystem."""
    meta_sessions = meta_sessions or set()
    corpus = Counter()
    for t in _false_skip_turns(turns):
        if subagent_stop and (t.get("sub") or t.get("sid") in meta_sessions):
            continue
        clause = (t.get("skip_text") or "").strip()
        if not clause or _looks_authorized(clause):
            continue
        corpus[_scrub(clause)] += 1
    return corpus


def _read_lines(path):
    """Yield transcript lines while reporting files that cannot be read completely."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            yield from fh
    except OSError as exc:
        print(f"warning: cannot read transcript {path}: {exc}", file=sys.stderr)


def audit(since=None, meta_keywords=None, subagent_stop=None):
    if subagent_stop is None:
        subagent_stop = SKILL_SUBAGENT_STOP
    meta_keywords = [k.lower() for k in (meta_keywords or DEFAULT_META)]
    skill_tool = Counter()
    slash = Counter()
    using = Counter()
    rerules = Counter()   # retracted USING declarations, moved out of `using`
    sess_raw = defaultdict(Counter)   # every USING per session (subagent files included) — the undo base
    n_search = n_skip = n_skip_new = 0
    cont_units = []    # one per continued skill per turn: (sid, epoch, name, re-read, work turns since last use)
    unit_at = {}       # (record uuid, name) -> (index in cont_units, read from the session's own file)

    def _close_continuations(turn):
        for name, (gap, sid_, ts_, uuid_, own_file) in turn["cont"].items():
            reread = any(_same_skill(name, x) for x in turn["loads"])
            unit = (sid_, ts_, name, reread, gap)
            key = (uuid_, name)
            if uuid_ and key in unit_at:
                # A resumed session's file copies the records it continues from; the copy in the
                # session's own file wins, whatever order the files are read in.
                i, had_own = unit_at[key]
                if own_file and not had_own:
                    cont_units[i], unit_at[key] = unit, (i, True)
                continue
            unit_at[key] = (len(cont_units), own_file)
            cont_units.append(unit)
    # per-session prompt text, to flag self/meta sessions
    sess_text = defaultdict(str)
    sess_skill = defaultdict(Counter)
    sess_using = defaultdict(Counter)
    turns = []  # per-turn {saw_search, saw_skip, saw_marker, skip_text, sid, sub}
    dispatch_sessions = set()  # H3: team teammate / dispatched sessions (own sid), excluded when ON

    def _new_turn(active):
        return {"saw_search": False, "saw_skip": False, "saw_marker": False, "saw_hook": False,
                "marker_at_skip": False, "hook_at_skip": False, "search_at_skip": False,
                "cont": {}, "loads": set(), "used_before": {},
                "active": active, "skip_text": "", "sid": None}

    for fp in sorted(glob.glob(os.path.join(PROJECTS, "**", "*.jsonl"), recursive=True)):   # fixed order
        # H3: subagent (Task sidechain) transcripts sit under a `subagents/` dir but carry the
        # PARENT's sid — flag them per FILE (not sid) so the parent's organic turns survive.
        is_sub = _SUBAGENT_PATH in fp
        file_dispatch = False   # a team/dispatched scaffolding marker seen in this file
        file_sid = None
        own_sid = os.path.basename(fp)[:-len(".jsonl")]   # a session's own file is named for it
        file_uuids = set()
        last_used = {}      # skill -> turn number of its last use this session (Skill, get_skill, USING, slash)
        turn_no = 0
        # Turn segmentation: a user record with string `content` opens a turn, and so does a typed
        # prompt stored as a list of text/image blocks; a tool_result user record (a list) does
        # not. We accumulate, per turn, whether a SKIPPING was declared and whether a real
        # search_skills call fired in the SAME turn, judging at the boundary so SEARCH-then-SKIPPING
        # order is handled.
        cur = _new_turn(False)
        for line in _read_lines(fp):
            if '"timestamp"' not in line:
                continue
            # H3 dispatch: scan the RAW line (not the 400-char-capped sess_text) so the team
            # scaffolding marker is never truncated; short-circuit once the file is flagged.
            if subagent_stop and not file_dispatch and any(dm in line for dm in _DISPATCH_MARKERS):
                file_dispatch = True
            is_user = ('"type":"user"' in line or '"type": "user"' in line)
            is_list_content = ('"content":[' in line or '"content": [' in line)
            maybe_prompt = is_user and not (is_list_content and '"tool_result"' in line)
            # User prompt lines must always reach sess_text below for meta classification, even
            # when they carry none of these tool/doctrine markers (e.g. "review the
            # skill-concierge gate" has no USING/SEARCH/SKIPPING token).
            has_marker = ('"Skill"' in line or "<command-name>" in line or "search_skills" in line
                          or "USING" in line or "SEARCH" in line or "SKIPPING" in line
                          or "NO SKILL:" in line or AUTHORIZED_SKIP_MARKER in line
                          # Widened only on the record kinds that need it: a line admitted here
                          # also feeds a user record's text to the meta classifier below. The
                          # attachment clause is load-bearing: the June 2026 enforcer head
                          # "SKILL-FIRST (standing …" carries neither USING nor SKILL-CHECK:.
                          or (('"type":"assistant"' in line or '"type": "assistant"' in line)
                              and (_NO_SKILL_ANY_CASE.search(line) or "get_skill" in line))
                          or ('"attachment"' in line and ("SKILL-FIRST" in line or "CONSULT-ROUTE" in line)))
            if not (has_marker or maybe_prompt):
                continue
            try:
                rec = json.loads(line.strip())
            except json.JSONDecodeError as exc:
                print(f"warning: invalid JSON record in {fp}: {exc}", file=sys.stderr)
                continue
            uid = rec.get("uuid")
            if uid:   # a record line duplicated in the file is read once
                if uid in file_uuids:
                    continue
                file_uuids.add(uid)
            opens = role_is_user_prompt(rec, rec.get("message")) or _hands_over_work(rec)
            if opens:   # a user prompt -> new turn
                _close_continuations(cur)
                if cur["active"] and cur["saw_skip"]:
                    turns.append({"saw_search": cur["search_at_skip"], "saw_skip": True,
                                  "saw_marker": cur["marker_at_skip"], "saw_hook": cur["hook_at_skip"], "skip_text": cur["skip_text"],
                                  "sid": cur["sid"], "sub": is_sub})
                cur = _new_turn(True)
                turn_no += _hands_over_work(rec)   # the stale gap counts work turns only
                cur["used_before"] = dict(last_used)   # "earlier use" means before this turn
            elif not has_marker:
                continue
            # Count ONLY the enforcer's own authorization line: from its own hook output
            # (_enforcer_output), anchored on its message signatures (_is_authorized_skip_line) —
            # the marker literal also appears in the doctrine, in files and in prose about it.
            own = _enforcer_output(rec)
            if any(_is_authorized_skip_line(x) for x in own):
                cur["saw_marker"] = True
            # The enforcer ran this turn: its offer, consult route or SKILL-CHECK: line reached the
            # agent. Turns without it (Stop-hook feedback, subagent prompts) measure other hooks.
            if own:
                cur["saw_hook"] = True
            if since is not None:
                e = ts_epoch(rec)
                if e is None or e < since:
                    _note_used(rec, last_used, turn_no)   # a continuation in the window may lean on it
                    continue
            sid = rec.get("sessionId") or fp
            cur["sid"] = file_sid = sid  # file = one session; thread onto the turn for the sid-join
            role = rec.get("type")
            # user /slash (a skill-search slash also credits a same-turn search)
            for m in _CMD.findall(line):
                n = norm(m)
                if n:
                    slash[n] += 1
                    msg0 = rec.get("message")
                    if role_is_user_prompt(rec, msg0):
                        last_used[n] = turn_no   # the user invoked it
                    if n in _SEARCH_SLUGS:
                        cur["saw_search"] = True
            msg = rec.get("message")
            # User-role string content (typed prompts, but also relayed teammate/command/task
            # messages) carries meta-keyword signal that list-wrapped content does not always
            # surface early enough — capture it for meta-classification. Harmless if broader
            # than typed prompts: every session flagged by this path so far also has a typed hit.
            if role == "user" and isinstance(msg, dict) and isinstance(msg.get("content"), str):
                sess_text[sid] += " " + msg["content"][:400].lower()
            if not (isinstance(msg, dict) and isinstance(msg.get("content"), list)):
                continue
            for blk in msg["content"]:
                if not isinstance(blk, dict):
                    continue
                if blk.get("type") == "tool_use":
                    nm = blk.get("name") or ""
                    n0 = _loaded_skill(blk)
                    if n0:
                        cur["loads"].add(n0)   # a load anywhere in the turn is the continuation's re-read
                        last_used[n0] = turn_no
                    if nm == "Skill":
                        n = norm((blk.get("input") or {}).get("skill"))
                        if n:
                            skill_tool[n] += 1
                            # H3: keep global totals whole, but keep subagent traffic OUT of the
                            # per-session ORGANIC denominator (sid can't exclude it — files share sid).
                            if not (subagent_stop and is_sub):
                                sess_skill[sid][n] += 1
                            if n in _SEARCH_SLUGS:
                                cur["saw_search"] = True
                    elif ("skill-search" in nm or "skill_search" in nm) and nm.endswith("search_skills"):
                        cur["saw_search"] = True
                if blk.get("type") == "text":
                    txt = blk.get("text", "")
                    if role == "user":
                        sess_text[sid] += " " + txt[:400].lower()
                    if role == "assistant":
                        used, retracted = _declared(txt)
                        if not (subagent_stop and is_sub):
                            for c in _continued_names(txt):
                                if c not in cur["cont"]:
                                    last = [t for n, t in cur["used_before"].items() if _same_skill(c, n)]
                                    gap = (turn_no - max(last)) if last else None
                                    cur["cont"][c] = (gap, sid, ts_epoch(rec) or 0.0, rec.get("uuid"), sid == own_sid)
                        for n in used:
                            last_used[n] = turn_no
                        undone = _tally(used, retracted, sid, using, sess_raw, rerules)
                        if not (subagent_stop and is_sub):  # H3: organic denominator only
                            for n in used:
                                sess_using[sid][n] += 1
                            for n in undone:   # the switched-away-from skill was not uptake
                                if sess_using[sid][n] > 0:
                                    sess_using[sid][n] -= 1
                        if _SEARCH.search(txt):
                            n_search += 1
                        m = _SKIPPING.search(txt)
                        if m:
                            n_skip += 1
                            n_skip_new += bool(m.group("new"))
                            if not cur["saw_skip"]:
                                # What the agent had been told when it ruled: a SKILL-CHECK: or an offer
                                # that arrives later in the turn (a queued notification) cannot
                                # authorize a skip already written.
                                cur["marker_at_skip"] = cur["saw_marker"]
                                cur["hook_at_skip"] = cur["saw_hook"]
                                # Rule 4 backs a skip with a search shown BEFORE the ruling.
                                cur["search_at_skip"] = cur["saw_search"]
                                # H1: capture ONLY the judged (first) clause line WHILE `txt` is
                                # valid (Red-Team F5). Cap to the clause for data-safety (F7).
                                ls = txt.rfind("\n", 0, m.start()) + 1
                                le = txt.find("\n", m.start())
                                cur["skip_text"] = txt[ls: le if le != -1 else len(txt)].strip()
                            cur["saw_skip"] = True
        _close_continuations(cur)
        if cur["active"] and cur["saw_skip"]:  # flush the file's last turn
            turns.append({"saw_search": cur["search_at_skip"], "saw_skip": True,
                          "saw_marker": cur["marker_at_skip"], "saw_hook": cur["hook_at_skip"], "skip_text": cur["skip_text"],
                          "sid": cur["sid"], "sub": is_sub})
        if file_dispatch and file_sid:
            dispatch_sessions.add(file_sid)

    false_skip, lawful_skip, authorized_skip = _skip_verdicts(turns)
    enforcer_verdicts = _skip_verdicts([t for t in turns if t.get("saw_hook")])

    # Exclude builtin slashes (/clear, /compact, /plugin, ...) by catalogue membership so
    # they don't inflate "skill usage" — mirrors the skill-usage-tracker's known-skill filter.
    known = build_catalogue() | set(skill_tool) | set(using)
    slash_skill = Counter({n: c for n, c in slash.items() if n in known})

    # H3: real-usage denominator drops self/meta (keyword) + dispatched team sessions (dispatch
    # markers, own sid). Subagent turns are already kept out of sess_* above (they share sid).
    meta_sessions = {sid for sid, t in sess_text.items()
                     if any(kw in t for kw in meta_keywords)} | dispatch_sessions
    return {
        "skill_tool": skill_tool, "slash": slash_skill, "using": +using, "rerules": rerules,
        "n_search": n_search, "n_skip": n_skip, "n_skip_new": n_skip_new,
        "continuations": _continuation_counts(cont_units),
        "continuations_organic": _continuation_counts([u for u in cont_units if u[0] not in meta_sessions]),
        "continuation_units": sorted(((u, u[0] in meta_sessions) for u in cont_units), key=lambda x: x[0][1]),
        "false_skip": false_skip, "lawful_skip": lawful_skip, "authorized_skip": authorized_skip,
        "enforcer_verdicts": enforcer_verdicts,
        "sess_skill": sess_skill, "sess_using": sess_using,
        "meta_sessions": meta_sessions, "dispatch_sessions": dispatch_sessions,
        "turns": turns, "subagent_stop": subagent_stop,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", metavar="WHEN",
                    help="only events at/after WHEN (epoch or 'YYYY-MM-DD HH:MM:SS', local)")
    ap.add_argument("--meta-keyword", action="append", default=None, metavar="KW",
                    help="mark a session self/meta if a user prompt contains KW (repeatable; "
                         "replaces the default set)")
    ap.add_argument("--selftest", action="store_true",
                    help="run the false-SKIPPING verdict + H1 harvest-filter self-check and exit")
    ap.add_argument("--continuations", action="store_true",
                    help="also list each continuation (session id prefix, time, skill, re-read, turns since last use)")
    ap.add_argument("--harvest", nargs="?", const="", default=None, metavar="PATH",
                    help="H1: write the deduped false-skip rationalization corpus to PATH and exit "
                         f"(default: ./{DEFAULT_HARVEST_SINK}; gitignored + scrubbed, local-only)")
    args = ap.parse_args()
    if args.selftest:
        t = [{"saw_skip": True, "saw_search": False, "saw_marker": False},  # SKIPPING, no search -> false
             {"saw_skip": True, "saw_search": True, "saw_marker": False},   # SKIPPING after a search -> lawful
             {"saw_skip": False, "saw_search": True, "saw_marker": False},  # no SKIPPING -> ignored
             {"saw_skip": True, "saw_search": False, "saw_marker": True}]   # SKILL-CHECK: then SKIPPING -> authorized
        fs, ls, az = _skip_verdicts(t)
        verdict_ok = (fs == 1 and ls == 1 and az == 1)
        # H1 harvest filter: capture rationalizations for false-skip turns ONLY, excluding
        # meta/self/dispatch (by sid) + subagent (by `sub`) turns + authorized-signature clauses.
        ht = [{"saw_skip": True, "saw_search": False, "saw_marker": False, "sid": "s1", "sub": False,
               "skip_text": "SKIPPING: none - mechanical git check, no skill applies"},   # -> harvested
              {"saw_skip": True, "saw_search": False, "saw_marker": False, "sid": "meta1", "sub": False,
               "skip_text": "SKIPPING: none - trivial"},                                  # meta sid -> excluded
              {"saw_skip": True, "saw_search": False, "saw_marker": False, "sid": "s1", "sub": True,
               "skip_text": "SKIPPING: none - inside a subagent"},                        # subagent -> excluded
              {"saw_skip": True, "saw_search": False, "saw_marker": False, "sid": "s2", "sub": False,
               "skip_text": "SKIPPING: none - self-referential recap lane"},              # authorized -> excluded
              {"saw_skip": True, "saw_search": True, "saw_marker": False, "sid": "s3", "sub": False,
               "skip_text": "SKIPPING: none - after a search"}]                           # searched -> not a false skip
        corpus = _harvest_corpus(ht, meta_sessions={"meta1"}, subagent_stop=True)
        harvest_ok = (list(corpus) == ["SKIPPING: none - mechanical git check, no skill applies"]
                      and sum(corpus.values()) == 1)
        # revert parity: subagent_stop=0 lifts the sub/meta exclusion (authorized still dropped,
        # searched still not a false skip) -> git + meta + subagent clauses = 3 distinct.
        corpus_off = _harvest_corpus(ht, meta_sessions={"meta1"}, subagent_stop=False)
        revert_ok = (len(corpus_off) == 3)
        # SELFREF parity (H5/ADR-0019): the count-side matcher must recognize the enforcer's 3rd
        # authorized-skip leg, AND the "self-referential recap lane" anchor must stay UNIQUE — never
        # colliding with the getaway/intent authorization lines or a bare doctrine-table mention of
        # the marker. Else a lawful selfref-skip miscounts as false (anchor missed) or a real dodge
        # masks as authorized (anchor over-matches). Fixtures mirror GETAWAY/INTENT/SELFREF_SKIP_MSG.
        SIG = "self-referential recap lane"
        getaway = (AUTHORIZED_SKIP_MARKER + " full-catalogue retrieval ran (top 0.30 < floor 0.40); "
                   "nothing cleared the floor. SKIPPING: none is pre-authorized.")
        intent = (AUTHORIZED_SKIP_MARKER + " the intent-margin classifier judged this turn "
                  "conversational/non-task. SKIPPING: none is pre-authorized.")
        selfref = (AUTHORIZED_SKIP_MARKER + " this turn only asks you to explain/rephrase your own "
                   "immediately-prior message — the " + SIG + " — with no external task. "
                   "SKIPPING: none is pre-authorized.")
        # a skill-first.md doctrine Red-Flags row: names the marker, carries NO signature phrase.
        doctrine = "| a SKILL-CHECK: line marks the AUTHORIZED-SKIP tier | go to SKIPPING: none |"
        selfref_ok = (
            _is_authorized_skip_line(selfref)                       # 3rd leg counted authorized (the fix)
            and _is_authorized_skip_line(getaway)                   # existing legs still match
            and _is_authorized_skip_line(intent)
            and not _is_authorized_skip_line(doctrine)              # bare doctrine marker -> NOT authorized
            and not _is_authorized_skip_line("SKIPPING: none - " + SIG)  # signature w/o marker -> NOT authorized
            and SIG not in getaway and SIG not in intent and SIG not in doctrine)  # anchor is unique
        # Re-rule counting: the marked line retracts the old USING; an unmarked second USING
        # (a multi-intent reply) retracts nothing; a SEARCH re-rule retracts too.
        rerule_ok = (
            _declared("USING: sk-a\nits body says not for this\nUSING: sk-b (re-rule: sk-a)")
            == (["sk-a", "sk-b"], ["sk-a"])
            and _declared("USING: sk-a\nlater, intent two\nUSING: sk-b") == (["sk-a", "sk-b"], [])
            and _declared("SEARCH: fold lessons into skills (re-rule: sk-a)") == ([], ["sk-a"])
            and _declared("prose mentioning (re-rule: sk-a) mid-sentence") == ([], []))
        # A retraction is per session: session B re-ruling away from sk-a must not erase session
        # A's legitimate USING of sk-a — in either file order.
        for order in (("A", "B"), ("B", "A")):
            _u, _raw, _rr = Counter(), defaultdict(Counter), Counter()
            for _sid in order:
                if _sid == "A":
                    _tally(["sk-a"], [], "A", _u, _raw, _rr)
                else:
                    _tally(["sk-b"], ["sk-a"], "B", _u, _raw, _rr)
            rerule_ok = rerule_ok and +_u == Counter({"sk-a": 1, "sk-b": 1}) and _rr["sk-a"] == 1
        _u, _raw, _rr = Counter(), defaultdict(Counter), Counter()
        _tally(["sk-a"], [], "S", _u, _raw, _rr)
        _tally(["sk-b"], ["sk-a"], "S", _u, _raw, _rr)
        rerule_ok = rerule_ok and +_u == Counter({"sk-b": 1})   # same session: undone
        # Both skip forms are rulings; prose opening "No skill" is not; a hook authorization counts
        # only from the enforcer's own output.
        auth = AUTHORIZED_SKIP_MARKER + " the intent-margin classifier judged this turn conversational."

        def _att(event, text, kind="hook_additional_context"):
            return {"type": "attachment", "attachment": {"type": kind, "hookEvent": event, "content": [text]}}
        ruling_ok = (
            bool(_SKIPPING.search("NO SKILL: hook-cleared — conversational turn"))
            and bool(_SKIPPING.search("intro\nSKIPPING: none - trivial"))
            and bool(_SKIPPING.search("skipping: none"))                   # old form, any case
            and not _SKIPPING.search("No skill applies here, so I answer directly.")
            and not _SKIPPING.search("NO SKILL applies")                  # no colon -> not a ruling
            and bool(_SKIPPING.search("No skill: trivial"))               # any case, with colon
            and bool(_SKIPPING.search("`NO SKILL: nothing fits`"))         # backtick-wrapped
            and bool(_USING.search("**USING: ak-git**"))
            and _declared("**USING: b (re-rule: a)**") == (["b"], ["a"])   # a bold re-rule retracts
            and _continued_names("USING: ak-cook for the build, then ak-git (continuing the work)") == ["ak-cook", "ak-git"]
            and _continued_names("Using rg (continuing the search)") == []            # prose, no colon
            and _continued_names("USING: <name> (continuing)") == []                 # the quoted placeholder
            and _continued_names("USING: ak-debug (new task, not continuing ak-cook)") == []   # negated
            and _continued_names("USING: ak-cook — fit (not a continuation of earlier work)") == []
            and _continued_names("USING: ak-cook (continuing — no new skill needed)") == ["ak-cook"]
            and _continued_names("USING session-handoff (continuing)") == ["session-handoff"]   # bare, capitals
            and _continued_names("USING: study, then run the tests (continuing)") == ["study"]
            and not _SEARCH.search("**Search results**")                    # a bold heading is prose
            and _enforcer_output(_att("UserPromptSubmit", auth)) == [auth]
            and _enforcer_output(_att("UserPromptSubmit", "CONSULT-ROUTE · x")) == ["CONSULT-ROUTE · x"]
            and not _enforcer_output(_att("PostToolUse", auth))           # a file-echo hook quoting it
            and not _enforcer_output(_att("UserPromptSubmit", "memory: " + auth))  # another hook quoting it
            and not _enforcer_output(_att("UserPromptSubmit", auth, kind="edited_text_file"))
            and not _enforcer_output(_att("UserPromptSubmit", auth, kind="nested_memory"))
            and not _enforcer_output({"type": "user", "isMeta": True, "message": {"content": auth}})
            and not _enforcer_output({"type": "assistant", "message": {"content": auth}}))
        ok = verdict_ok and harvest_ok and revert_ok and selfref_ok and rerule_ok and ruling_ok
        print("audit --selftest",
              "OK: false-SKIPPING verdict + H1 harvest filter + SELFREF parity + re-rule counting"
              " + both skip-ruling forms + enforcer-output-only authorization" if ok
              else f"FAIL verdict={verdict_ok}(fs={fs} ls={ls} az={az}) "
                   f"harvest={harvest_ok} revert={revert_ok} selfref={selfref_ok} rerule={rerule_ok} "
                   f"ruling={ruling_ok}")
        raise SystemExit(0 if ok else 1)
    since = parse_since(args.since)
    r = audit(since, args.meta_keyword)

    if args.harvest is not None:
        corpus = _harvest_corpus(r["turns"], r["meta_sessions"], r["subagent_stop"])
        sink = args.harvest or DEFAULT_HARVEST_SINK
        d = os.path.dirname(sink)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(sink, "w", encoding="utf-8") as fh:
            fh.write("# H1 rationalization harvest — false-skip SKIPPING clauses (scrubbed, "
                     "local-only, gitignored). Do NOT commit or share. See ADR-0021.\n")
            fh.write(f"# window: {'since '+args.since if since else 'LIFETIME'}  "
                     f"distinct: {len(corpus)}  total: {sum(corpus.values())}\n")
            fh.writelines(f"{c}\t{clause}\n" for clause, c in corpus.most_common())
        print(f"harvested {sum(corpus.values())} false-skip rationalizations "
              f"({len(corpus)} distinct) -> {sink}")
        print("  scrubbed + gitignored; feeds H2 doctrine authoring (ADR-0021). "
              "NOT a usefulness metric — dodge-rate only.")
        raise SystemExit(0)

    st, sl, us = r["skill_tool"], r["slash"], r["using"]
    tot_counter = sum(st.values()) + sum(sl.values())
    win = f"since {args.since}" if since else "LIFETIME (all transcripts)"
    print(f"=== skill-usage audit — {win} ===")
    print("COUNTER signals (Skill tool + /slash — what ledger/usage-tracker see):")
    print(f"  Skill-tool: {sum(st.values())}   /slash: {sum(sl.values())}   combined: {tot_counter}")
    print("INLINE signal (the operator's metric — invisible to both counters):")
    print(f"  USING <skill> declarations: {sum(us.values())}  (distinct {len(us)})")
    print(f"  SEARCH declarations: {r['n_search']}   skip rulings: {r['n_skip']} "
          f"(NO SKILL: {r['n_skip_new']}, old SKIPPING {r['n_skip'] - r['n_skip_new']})")
    print(f"  re-rules: {sum(r['rerules'].values())}  (a USING switched away from under doctrine "
          "rule 3 — excluded from USING above)")
    print(f"  -> total skill-aware actions (USING + counters): {sum(us.values()) + tot_counter}")

    fs, ls, az = r["false_skip"], r["lawful_skip"], r["authorized_skip"]
    skip_turns = fs + ls + az
    print("\nFALSE-SKIPPING (doctrine's hardest rule — 'no search, no skip'):")
    if skip_turns:
        print(f"  {fs}/{skip_turns}  {100*fs/skip_turns:.0f}%  ruled a skip with NO search_skills "
              f"call in the same turn   (lawful, search-backed skips: {ls}; "
              f"hook-authorized skips: {az})")
    else:
        print("  no skip-ruling turns in window")
    ct, cr, cn, cs = r["continuations"]
    if ct:
        ot, orr, on, os_ = r["continuations_organic"]
        print(f"  continuations (`USING: <x> (continuing …)`, rule 3): {ct} — re-read in the turn {cr}; "
              f"no earlier use this session {cn}; last used > {STALE_TURNS} work turns ago {cs}  "
              f"[organic, self/meta excluded: {ot} — {orr} / {on} / {os_}]")
        if args.continuations:
            for (sid_, ep, name, reread, gap), meta in r["continuation_units"]:
                when = dt.datetime.fromtimestamp(ep).strftime("%Y-%m-%d %H:%M:%S") if ep else "?"
                print(f"    {str(sid_)[:8]} {when} {name} re-read={'yes' if reread else 'no'} "
                      f"work-turns-since-last-use={gap if gap is not None else 'never'}"
                      f"{' [self/meta]' if meta else ''}")
    efs, els, eaz = r["enforcer_verdicts"]
    if efs + els + eaz:
        print(f"  enforcer-run turns only: {efs}/{efs + els + eaz}  {100*efs/(efs + els + eaz):.0f}% false "
              f"(lawful {els}; hook-authorized {eaz}) — turns where the enforcer injected")
    print("  [turn = user-prompt boundary; self/meta NOT excluded here — see organic note above]")

    meta = r["meta_sessions"]
    organic_using = sum(c for sid, cc in r["sess_using"].items() if sid not in meta for c in cc.values())
    organic_skill = sum(c for sid, cc in r["sess_skill"].items() if sid not in meta for c in cc.values())
    if r["subagent_stop"]:
        n_disp = len(r["dispatch_sessions"])
        n_sub = sum(1 for t in r["turns"] if t.get("sub"))
        print(f"\nNOISE-SCOPED (H3: drop self/meta + {n_disp} dispatched sessions "
              f"+ subagent turns; {len(meta)} sessions flagged, {n_sub} subagent skip-turns seen):")
        print(f"  organic Skill-tool: {organic_skill}   organic USING declarations: {organic_using}")
        print("  (excluded = dogfood/verification/teammate/subagent traffic, not organic usage; "
              "SKILL_SUBAGENT_STOP=0 to revert)")
    else:
        print(f"\nNOISE-SCOPED (drop self/meta sessions: {len(meta)} flagged):")
        print(f"  organic Skill-tool: {organic_skill}   organic USING declarations: {organic_using}")
        print("  (self/meta = work ON the audited project: dogfood/verification, not organic usage)")

    top = sorted(set(st) | set(us), key=lambda n: -(st.get(n, 0) + us.get(n, 0)))[:15]
    print("\ntop skills (Skill-tool + USING, combined):")
    for n in top:
        print(f"  {st.get(n,0)+us.get(n,0):>4}  (tool {st.get(n,0)}, using {us.get(n,0)})  {n}")
    if not since:
        print("\nnote: pass --since <ship time> to scope to the post-change window.")


if __name__ == "__main__":
    main()
