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

Pure stdlib, read-only. Usage:
  python3 audit_skill_usage.py [--since "YYYY-MM-DD HH:MM:SS"] [--meta-keyword KW ...]
  python3 audit_skill_usage.py --since "2026-06-29 01:06:35"
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
    """Pure verdict over per-turn flags [{'saw_search':bool,'saw_skip':bool}, ...].

    Returns (false_skip, lawful_skip). The doctrine's hardest rule is 'no search, no
    skip': a turn that DECLARED `SKIPPING` with NO `search_skills` call in the SAME turn
    is a false skip; one with a search is lawful. Turns without a SKIPPING are ignored.
    Kept pure so --selftest pins the branching without touching the filesystem."""
    false_skip = lawful_skip = 0
    for t in turns:
        if not t.get("saw_skip"):
            continue
        if t.get("saw_search"):
            lawful_skip += 1
        else:
            false_skip += 1
    return false_skip, lawful_skip


def audit(since=None, meta_keywords=None):
    meta_keywords = [k.lower() for k in (meta_keywords or DEFAULT_META)]
    skill_tool = Counter()
    slash = Counter()
    using = Counter()
    n_search = n_skip = 0
    # per-session prompt text, to flag self/meta sessions
    sess_text = defaultdict(str)
    sess_skill = defaultdict(Counter)
    sess_using = defaultdict(Counter)
    turns = []  # per-turn {saw_search, saw_skip} for the false-SKIPPING verdict

    for fp in glob.glob(os.path.join(PROJECTS, "**", "*.jsonl"), recursive=True):
        try:
            fh = open(fp, encoding="utf-8", errors="replace")
        except Exception:
            continue
        # Turn segmentation: a genuine user prompt (string `content`) opens a turn; a
        # tool_result user record (`content` is a LIST) does not. We accumulate, per turn,
        # whether a SKIPPING was declared and whether a real search_skills call fired in the
        # SAME turn, judging at the boundary so SEARCH-then-SKIPPING order is handled.
        cur = {"saw_search": False, "saw_skip": False, "active": False}
        for line in fh:
            if '"timestamp"' not in line:
                continue
            is_user = ('"type":"user"' in line or '"type": "user"' in line)
            is_list_content = ('"content":[' in line or '"content": [' in line)
            if is_user and not is_list_content:  # genuine user prompt -> new turn
                if cur["active"] and cur["saw_skip"]:
                    turns.append({"saw_search": cur["saw_search"], "saw_skip": True})
                cur = {"saw_search": False, "saw_skip": False, "active": True}
            # Genuine user-prompt lines must always reach sess_text below for meta
            # classification, even when they carry none of these tool/doctrine markers
            # (e.g. "review the skill-concierge gate" has no USING/SEARCH/SKIPPING token).
            has_marker = ('"Skill"' in line or "<command-name>" in line or "search_skills" in line
                          or "USING" in line or "SEARCH" in line or "SKIPPING" in line)
            if not (has_marker or (is_user and not is_list_content)):
                continue
            try:
                rec = json.loads(line.strip())
            except Exception:
                continue
            if since is not None:
                e = ts_epoch(rec)
                if e is None or e < since:
                    continue
            sid = rec.get("sessionId") or fp
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
                                sess_using[sid][n] += 1
                        if _SEARCH.search(txt):
                            n_search += 1
                        if _SKIPPING.search(txt):
                            n_skip += 1
                            cur["saw_skip"] = True
        if cur["active"] and cur["saw_skip"]:  # flush the file's last turn
            turns.append({"saw_search": cur["saw_search"], "saw_skip": True})
        fh.close()

    false_skip, lawful_skip = _skip_verdicts(turns)

    # Exclude builtin slashes (/clear, /compact, /plugin, ...) by catalogue membership so
    # they don't inflate "skill usage" — mirrors the skill-usage-tracker's known-skill filter.
    known = build_catalogue() | set(skill_tool) | set(using)
    slash_skill = Counter({n: c for n, c in slash.items() if n in known})

    meta_sessions = {sid for sid, t in sess_text.items()
                     if any(kw in t for kw in meta_keywords)}
    return {
        "skill_tool": skill_tool, "slash": slash_skill, "using": using,
        "n_search": n_search, "n_skip": n_skip,
        "false_skip": false_skip, "lawful_skip": lawful_skip,
        "sess_skill": sess_skill, "sess_using": sess_using,
        "meta_sessions": meta_sessions,
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
                    help="run the false-SKIPPING verdict self-check and exit")
    args = ap.parse_args()
    if args.selftest:
        t = [{"saw_skip": True, "saw_search": False},   # SKIPPING, no search -> false
             {"saw_skip": True, "saw_search": True},     # SKIPPING after a search -> lawful
             {"saw_skip": False, "saw_search": True}]    # no SKIPPING -> ignored
        fs, ls = _skip_verdicts(t)
        ok = (fs == 1 and ls == 1)
        print("audit --selftest", "OK: false-SKIPPING verdict" if ok else f"FAIL fs={fs} ls={ls}")
        raise SystemExit(0 if ok else 1)
    since = parse_since(args.since)
    r = audit(since, args.meta_keyword)

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

    fs, ls = r["false_skip"], r["lawful_skip"]
    skip_turns = fs + ls
    print(f"\nFALSE-SKIPPING (doctrine's hardest rule — 'no search, no skip'):")
    if skip_turns:
        print(f"  {fs}/{skip_turns}  {100*fs/skip_turns:.0f}%  declared SKIPPING with NO search_skills "
              f"call in the same turn   (lawful, search-backed skips: {ls})")
    else:
        print(f"  no SKIPPING turns in window")
    print(f"  [turn = user-prompt boundary; self/meta NOT excluded here — see organic note above]")

    meta = r["meta_sessions"]
    organic_using = sum(c for sid, cc in r["sess_using"].items() if sid not in meta for c in cc.values())
    organic_skill = sum(c for sid, cc in r["sess_skill"].items() if sid not in meta for c in cc.values())
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
