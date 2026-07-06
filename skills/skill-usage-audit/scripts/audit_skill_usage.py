#!/usr/bin/env python3
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
from collections import Counter, defaultdict

PROJECTS = os.path.join(os.path.expanduser("~"), ".claude", "projects")

# Default self/meta markers: prompts about auditing/tuning the gate itself are NOT organic
# usage. Override/extend with --meta-keyword. Kept conservative on purpose.
DEFAULT_META = ["skill-concierge", "enforcer", "gate floor", "getaway_floor",
                "max_short_words", "dogfood", "threshold", "impact analysis",
                "skill-usage-audit", "verify-as-claimed"]

_USING = re.compile(r'(?im)^\s*USING:?\s+([a-z0-9][a-z0-9:_\-]*)')
_SEARCH = re.compile(r'(?im)^\s*SEARCH:?\s+')
_SKIPPING = re.compile(r'(?im)^\s*SKIPPING:?\s+')
_CMD = re.compile(r"<command-name>\s*(/?[^<]+?)\s*</command-name>")
# The semantic-search tool, normalized — a SKIPPING is only lawful if one of these fired
# in the same turn (an actual search_skills call, not a bare `SEARCH:` line which is itself
# the 'ritual SEARCH' failure mode).
_SEARCH_SLUGS = {"skill-search", "skill-concierge-skill-search"}
# Cross-file contract with hooks/scripts/enforcer.py (Phase 1) — keep in sync. The enforcer
# injects this literal marker on its two silent verdict legs (getaway skip, intent skip) to
# pre-authorize a `SKIPPING: none`; a turn carrying it is a lawful hook-authorized skip, not
# a false skip.
AUTHORIZED_SKIP_MARKER = "SKILL-CHECK:"

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
# GETAWAY_SKIP_MSG / INTENT_SKIP_MSG / SELFREF_SKIP_MSG in hooks/scripts/enforcer.py.
_AUTHORIZED_SIGNATURES = ("full-catalogue retrieval ran", "intent-margin classifier",
                          "self-referential recap lane")


def _is_authorized_skip_line(line):
    """True iff `line` is the enforcer's OWN SKILL-CHECK authorization line — anchored on its
    three message signatures (_AUTHORIZED_SIGNATURES), NOT the bare marker. The marker literal
    also appears in the skill-first.md doctrine and in any prose/tool-result that discusses the
    feature; matching those would over-count authorized_skip and mask false-skips. Fails SAFE:
    if the enforcer wording drifts from these signatures we under-count authorized (over-flag
    false), never the reverse. Single source of truth for count-side (saw_marker) AND harvest-side
    (H1 exclusion) so the two legs can never drift. Keep _AUTHORIZED_SIGNATURES in sync with
    GETAWAY_SKIP_MSG / INTENT_SKIP_MSG / SELFREF_SKIP_MSG in hooks/scripts/enforcer.py."""
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
    if not t:
        return None
    try:
        return dt.datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp()
    except Exception:
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
            return dt.datetime.strptime(s, fmt).timestamp()
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


def audit(since=None, meta_keywords=None, subagent_stop=None):
    if subagent_stop is None:
        subagent_stop = SKILL_SUBAGENT_STOP
    meta_keywords = [k.lower() for k in (meta_keywords or DEFAULT_META)]
    skill_tool = Counter()
    slash = Counter()
    using = Counter()
    n_search = n_skip = 0
    # per-session prompt text, to flag self/meta sessions
    sess_text = defaultdict(str)
    sess_skill = defaultdict(Counter)
    sess_using = defaultdict(Counter)
    turns = []  # per-turn {saw_search, saw_skip, saw_marker, skip_text, sid, sub}
    dispatch_sessions = set()  # H3: team teammate / dispatched sessions (own sid), excluded when ON

    def _new_turn(active):
        return {"saw_search": False, "saw_skip": False, "saw_marker": False,
                "active": active, "skip_text": "", "sid": None}

    for fp in glob.glob(os.path.join(PROJECTS, "**", "*.jsonl"), recursive=True):
        try:
            fh = open(fp, encoding="utf-8", errors="replace")
        except Exception:
            continue
        # H3: subagent (Task sidechain) transcripts sit under a `subagents/` dir but carry the
        # PARENT's sid — flag them per FILE (not sid) so the parent's organic turns survive.
        is_sub = _SUBAGENT_PATH in fp
        file_dispatch = False   # a team/dispatched scaffolding marker seen in this file
        file_sid = None
        # Turn segmentation: a genuine user prompt (string `content`) opens a turn; a
        # tool_result user record (`content` is a LIST) does not. We accumulate, per turn,
        # whether a SKIPPING was declared and whether a real search_skills call fired in the
        # SAME turn, judging at the boundary so SEARCH-then-SKIPPING order is handled.
        cur = _new_turn(False)
        for line in fh:
            if '"timestamp"' not in line:
                continue
            # H3 dispatch: scan the RAW line (not the 400-char-capped sess_text) so the team
            # scaffolding marker is never truncated; short-circuit once the file is flagged.
            if subagent_stop and not file_dispatch and any(dm in line for dm in _DISPATCH_MARKERS):
                file_dispatch = True
            is_user = ('"type":"user"' in line or '"type": "user"' in line)
            is_list_content = ('"content":[' in line or '"content": [' in line)
            if is_user and not is_list_content:  # genuine user prompt -> new turn
                if cur["active"] and cur["saw_skip"]:
                    turns.append({"saw_search": cur["saw_search"], "saw_skip": True,
                                  "saw_marker": cur["saw_marker"], "skip_text": cur["skip_text"],
                                  "sid": cur["sid"], "sub": is_sub})
                cur = _new_turn(True)
            # Genuine user-prompt lines must always reach sess_text below for meta
            # classification, even when they carry none of these tool/doctrine markers
            # (e.g. "review the skill-concierge gate" has no USING/SEARCH/SKIPPING token).
            has_marker = ('"Skill"' in line or "<command-name>" in line or "search_skills" in line
                          or "USING" in line or "SEARCH" in line or "SKIPPING" in line
                          or AUTHORIZED_SKIP_MARKER in line)
            if not (has_marker or (is_user and not is_list_content)):
                continue
            # Count ONLY the enforcer's own authorization line (see _is_authorized_skip_line):
            # anchored on its three message signatures, not the bare marker — the marker literal
            # also appears in the skill-first.md doctrine and in prose discussing the feature.
            if _is_authorized_skip_line(line):
                cur["saw_marker"] = True
            try:
                rec = json.loads(line.strip())
            except Exception:
                continue
            if since is not None:
                e = ts_epoch(rec)
                if e is None or e < since:
                    continue
            sid = rec.get("sessionId") or fp
            cur["sid"] = file_sid = sid  # file = one session; thread onto the turn for the sid-join
            role = rec.get("type")
            # user /slash (a skill-search slash also credits a same-turn search)
            for m in _CMD.findall(line):
                n = norm(m)
                if n:
                    slash[n] += 1
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
                    elif "search_skills" in nm:  # the MCP retriever call
                        cur["saw_search"] = True
                if blk.get("type") == "text":
                    txt = blk.get("text", "")
                    if role == "user":
                        sess_text[sid] += " " + txt[:400].lower()
                    if role == "assistant":
                        for m in _USING.findall(txt):
                            n = norm(m)
                            # drop obvious non-skill matches from prose ('the','none','a'...)
                            if n and n not in ("the", "none", "a", "an", "it", "this", "that"):
                                using[n] += 1
                                if not (subagent_stop and is_sub):  # H3: organic denominator only
                                    sess_using[sid][n] += 1
                        if _SEARCH.search(txt):
                            n_search += 1
                        m = _SKIPPING.search(txt)
                        if m:
                            n_skip += 1
                            cur["saw_skip"] = True
                            # H1: capture ONLY the SKIPPING clause line WHILE `txt` is valid
                            # (Red-Team F5: `txt` is stale/unbound at flush). Cap to the clause —
                            # not the surrounding task text — for data-safety (F7).
                            ls = txt.rfind("\n", 0, m.start()) + 1
                            le = txt.find("\n", m.start())
                            cur["skip_text"] = txt[ls: le if le != -1 else len(txt)].strip()
        if cur["active"] and cur["saw_skip"]:  # flush the file's last turn
            turns.append({"saw_search": cur["saw_search"], "saw_skip": True,
                          "saw_marker": cur["saw_marker"], "skip_text": cur["skip_text"],
                          "sid": cur["sid"], "sub": is_sub})
        if file_dispatch and file_sid:
            dispatch_sessions.add(file_sid)
        fh.close()

    false_skip, lawful_skip, authorized_skip = _skip_verdicts(turns)

    # Exclude builtin slashes (/clear, /compact, /plugin, ...) by catalogue membership so
    # they don't inflate "skill usage" — mirrors the skill-usage-tracker's known-skill filter.
    known = build_catalogue() | set(skill_tool) | set(using)
    slash_skill = Counter({n: c for n, c in slash.items() if n in known})

    # H3: real-usage denominator drops self/meta (keyword) + dispatched team sessions (dispatch
    # markers, own sid). Subagent turns are already kept out of sess_* above (they share sid).
    meta_sessions = {sid for sid, t in sess_text.items()
                     if any(kw in t for kw in meta_keywords)} | dispatch_sessions
    return {
        "skill_tool": skill_tool, "slash": slash_skill, "using": using,
        "n_search": n_search, "n_skip": n_skip,
        "false_skip": false_skip, "lawful_skip": lawful_skip, "authorized_skip": authorized_skip,
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
        ok = verdict_ok and harvest_ok and revert_ok and selfref_ok
        print("audit --selftest",
              "OK: false-SKIPPING verdict + H1 harvest filter + SELFREF parity" if ok
              else f"FAIL verdict={verdict_ok}(fs={fs} ls={ls} az={az}) "
                   f"harvest={harvest_ok} revert={revert_ok} selfref={selfref_ok}")
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
            for clause, c in corpus.most_common():
                fh.write(f"{c}\t{clause}\n")
        print(f"harvested {sum(corpus.values())} false-skip rationalizations "
              f"({len(corpus)} distinct) -> {sink}")
        print("  scrubbed + gitignored; feeds H2 doctrine authoring (ADR-0021). "
              "NOT a usefulness metric — dodge-rate only.")
        raise SystemExit(0)

    st, sl, us = r["skill_tool"], r["slash"], r["using"]
    tot_counter = sum(st.values()) + sum(sl.values())
    win = f"since {args.since}" if since else "LIFETIME (all transcripts)"
    print(f"=== skill-usage audit — {win} ===")
    print(f"COUNTER signals (Skill tool + /slash — what ledger/usage-tracker see):")
    print(f"  Skill-tool: {sum(st.values())}   /slash: {sum(sl.values())}   combined: {tot_counter}")
    print(f"INLINE signal (the operator's metric — invisible to both counters):")
    print(f"  USING <skill> declarations: {sum(us.values())}  (distinct {len(us)})")
    print(f"  SEARCH declarations: {r['n_search']}   SKIPPING declarations: {r['n_skip']}")
    print(f"  -> total skill-aware actions (USING + counters): {sum(us.values()) + tot_counter}")

    fs, ls, az = r["false_skip"], r["lawful_skip"], r["authorized_skip"]
    skip_turns = fs + ls + az
    print(f"\nFALSE-SKIPPING (doctrine's hardest rule — 'no search, no skip'):")
    if skip_turns:
        print(f"  {fs}/{skip_turns}  {100*fs/skip_turns:.0f}%  declared SKIPPING with NO search_skills "
              f"call in the same turn   (lawful, search-backed skips: {ls}; "
              f"hook-authorized skips: {az})")
    else:
        print(f"  no SKIPPING turns in window")
    print(f"  [turn = user-prompt boundary; self/meta NOT excluded here — see organic note above]")

    meta = r["meta_sessions"]
    organic_using = sum(c for sid, cc in r["sess_using"].items() if sid not in meta for c in cc.values())
    organic_skill = sum(c for sid, cc in r["sess_skill"].items() if sid not in meta for c in cc.values())
    if r["subagent_stop"]:
        n_disp = len(r["dispatch_sessions"])
        n_sub = sum(1 for t in r["turns"] if t.get("sub"))
        print(f"\nNOISE-SCOPED (H3: drop self/meta + {n_disp} dispatched sessions "
              f"+ subagent turns; {len(meta)} sessions flagged, {n_sub} subagent skip-turns seen):")
        print(f"  organic Skill-tool: {organic_skill}   organic USING declarations: {organic_using}")
        print(f"  (excluded = dogfood/verification/teammate/subagent traffic, not organic usage; "
              f"SKILL_SUBAGENT_STOP=0 to revert)")
    else:
        print(f"\nNOISE-SCOPED (drop self/meta sessions: {len(meta)} flagged):")
        print(f"  organic Skill-tool: {organic_skill}   organic USING declarations: {organic_using}")
        print(f"  (self/meta = work ON the audited project: dogfood/verification, not organic usage)")

    top = sorted(set(st) | set(us), key=lambda n: -(st.get(n, 0) + us.get(n, 0)))[:15]
    print(f"\ntop skills (Skill-tool + USING, combined):")
    for n in top:
        print(f"  {st.get(n,0)+us.get(n,0):>4}  (tool {st.get(n,0)}, using {us.get(n,0)})  {n}")
    if not since:
        print("\nnote: pass --since <ship time> to scope to the post-change window.")


if __name__ == "__main__":
    main()
