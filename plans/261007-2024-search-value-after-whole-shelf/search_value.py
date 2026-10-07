#!/usr/bin/env python3
"""Does the forced search after a Jev whole-shelf ranking find skills the ranking missed?

Reads the transcript store (~/.claude/projects/**/*.jsonl, subagent files skipped), per the
skill-usage-audit rule: the ledger measures gate compliance, not usage. A turn opens at a user prompt.
For every turn whose enforcer output carried the whole-shelf head, it records the offered rows, the
agent's first ruling, each search_skills call and its hit names, and the skills the turn used
(Skill tool / get_skill loads plus final USING lines, re-ruled names dropped). Outcome classes:

  direct_offer      no search; used a skill from the offer
  direct_skip       no search; NO SKILL (doctrine breach under a whole-shelf offer)
  search_offer      searched; used a skill that the offer already listed
  search_new_hit    searched; used a skill NOT in the offer that the search returned   <- search value
  search_new_other  searched; used a skill in neither (found some other way)
  search_none       searched; used no skill
  other             no ruling read / no search and no skill

Read-only. `--since` / `--until` local time; `--list CLASS` prints those turns for hand review.
"""
import argparse
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "skill-usage-audit" / "scripts"))
import audit_skill_usage as au  # noqa: E402

HEAD = "Whole-shelf ranking for this task"
PREVIEW = "Preview for this task"
ROW = re.compile(r"^\s*•\s+([A-Za-z0-9][A-Za-z0-9:_\-]*)")
ANNEX = ("External catalog matches", "Other-harness matches")
EPOCHS = [("0.52.3 doctrine", "2026-09-26 21:20"), ("0.56.0 bench", "2026-10-03 12:57"),
          ("0.59.0 cc/jevd", "2026-10-06 23:21")]


def offer_rows(text):
    """(primary rows, annex rows) of one enforcer offer, names normalized."""
    prim, annex, zone = [], [], None
    for line in text.splitlines():
        if line.startswith((HEAD, PREVIEW)):
            zone = "p"
        elif line.startswith(ANNEX):
            zone = "a"
        elif line.startswith(("Shares are", "To use one", "None fit", "ROUTE:", "CHAIN-HINT")):
            zone = None if not line.startswith("To use one") else zone
        m = ROW.match(line)
        if m and zone:
            (prim if zone == "p" else annex).append(au.norm(m.group(1)))
    return prim, annex


def hit_names(content):
    """Names in a search_skills tool_result."""
    if isinstance(content, list):
        content = " ".join(b.get("text", "") for b in content if isinstance(b, dict))
    if not isinstance(content, str):
        return []
    try:
        outer = json.loads(content)
        inner = json.loads(outer["result"]) if isinstance(outer, dict) and "result" in outer else outer
        return [au.norm(r["name"]) for r in inner.get("results", []) if r.get("name")]
    except (ValueError, TypeError, KeyError, AttributeError):
        return [au.norm(n) for n in re.findall(r'\\?"name\\?":\s*\\?"([^"\\]+)', content)]


def inset(name, names):
    return any(au._same_skill(name, n) for n in names if n)


def new_turn(rec, prompt):
    return {"t": au.ts_epoch(rec), "cwd": rec.get("cwd") or "", "sid": rec.get("sessionId"),
            "prompt": prompt, "work": au._hands_over_work(rec), "offer": None, "kind": None,
            "prim": [], "annex": [], "ruling": None, "searches": [], "pending": {},
            "loads": [], "using": [], "rerules": [], "after_search": False, "continuing": False}


def classify(tu):
    used = [n for n in tu["loads"] + tu["using"] if n and not inset(n, tu["rerules"])]
    used = list(dict.fromkeys(used))
    offered = tu["prim"] + tu["annex"]
    hits = [h for s in tu["searches"] for h in s["hits"]]
    if not tu["searches"]:
        if used:
            if any(inset(u, offered) for u in used):
                return "direct_offer", used
            return ("direct_continuing" if tu["continuing"] else "direct_other"), used
        return ("direct_skip" if tu["ruling"] == "NO SKILL" else "other"), used
    if not used:
        return "search_none", used
    # A turn that used a new search hit counts as search value even if it also used an offered skill.
    if any(inset(u, hits) and not inset(u, offered) for u in used):
        return "search_new_hit", used
    if any(inset(u, offered) for u in used):
        return "search_offer", used
    return "search_new_other", used


def turns(since, until):
    files = [f for f in glob.glob(os.path.join(au.PROJECTS, "**", "*.jsonl"), recursive=True)
             if au._SUBAGENT_PATH not in f]
    for fp in sorted(files):
        if since and os.path.getmtime(fp) < since:
            continue
        cur = None
        for line in au._read_lines(fp):
            if HEAD not in line and cur is None:
                if '"type":"user"' not in line and '"type": "user"' not in line and "queued_command" not in line:
                    continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            msg = rec.get("message") if isinstance(rec.get("message"), dict) else {}
            prompt = au._prompt_text(rec) if rec.get("type") == "user" else None
            if prompt is not None and not rec.get("isMeta") and not rec.get("isCompactSummary"):
                if cur and cur["kind"]:
                    yield cur
                cur = new_turn(rec, prompt)
                continue
            att = rec.get("attachment") if rec.get("type") == "attachment" else None
            if isinstance(att, dict) and att.get("type") == "queued_command" and isinstance(att.get("prompt"), str):
                # A prompt typed while the agent works arrives as an attachment: it opens its own turn.
                if cur and cur["kind"]:
                    yield cur
                cur = new_turn(rec, att["prompt"])
                cur["work"] = att.get("commandMode") == "prompt" and (att.get("origin") or {}).get("kind") == "human"
                continue
            if cur is None:
                continue
            for out in au._enforcer_output(rec):
                if HEAD in out or PREVIEW in out:
                    cur["kind"] = "whole" if HEAD in out else "preview"
                    cur["offer"] = out
                    cur["prim"], cur["annex"] = offer_rows(out)
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text" and rec.get("type") == "assistant":
                    txt = b.get("text", "")
                    if cur["ruling"] is None:
                        s = txt.lstrip(" *`>")
                        cur["continuing"] = bool(re.match(r"(?i)USING:?\s*\S+\s*\(continu", s))
                        cur["ruling"] = next((k for k in ("USING", "SEARCH", "NO SKILL", "SKIPPING")
                                              if s.upper().startswith(k)), None)
                    used, rr = au._declared(txt)
                    cur["using"] += used
                    cur["rerules"] += rr
                elif b.get("type") == "tool_use":
                    nm = b.get("name") or ""
                    if ("skill-search" in nm or "skill_search" in nm) and nm.endswith("search_skills"):
                        cur["pending"][b.get("id")] = {"q": (b.get("input") or {}).get("query", ""), "hits": []}
                        cur["searches"].append(cur["pending"][b.get("id")])
                    else:
                        n = au._loaded_skill(b)
                        if n:
                            cur["loads"].append(n)
                elif b.get("type") == "tool_result" and b.get("tool_use_id") in cur["pending"]:
                    cur["pending"][b["tool_use_id"]]["hits"] = hit_names(b.get("content"))
        if cur and cur["kind"]:
            yield cur


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=EPOCHS[0][1])
    ap.add_argument("--until")
    ap.add_argument("--list", action="append", default=[])
    ap.add_argument("--json", help="write every scored turn here")
    a = ap.parse_args()
    since, until = au.parse_since(a.since), a.until and au.parse_since(a.until)
    rows = []
    for tu in turns(since, until):
        if tu["t"] is None or tu["t"] < since or (until and tu["t"] >= until):
            continue
        cls, used = classify(tu)
        meta = "skill-concierge" in tu["cwd"]
        rows.append({**{k: tu[k] for k in ("t", "cwd", "sid", "kind", "ruling", "prim", "annex", "work")},
                     "prompt": tu["prompt"][:300], "cls": cls, "used": used,
                     "searches": [{"q": s["q"], "hits": s["hits"][:8]} for s in tu["searches"]], "meta": meta})
    # A resumed or forked session copies earlier records into a second file: one turn, two rows.
    # Keep the copy that recorded the most (tool blocks are sometimes missing from the copy).
    best = {}
    for r in rows:
        k = (r["prompt"][:200], int(r["t"]))
        if k not in best or len(r["searches"]) + len(r["used"]) > len(best[k]["searches"]) + len(best[k]["used"]):
            best[k] = r
    rows = sorted(best.values(), key=lambda r: r["t"])
    if a.json:
        Path(a.json).write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    order = ["direct_offer", "direct_continuing", "direct_other", "direct_skip", "search_offer", "search_new_hit",
             "search_new_other", "search_none", "other"]
    epochs = [(n, au.parse_since(s)) for n, s in EPOCHS]

    def table(title, sel):
        print(f"\n{title}")
        hdr = f"  {'class':18}" + "".join(f"{n:>17}" for n, _ in epochs)
        print(hdr)
        groups = []
        for i, (n, s) in enumerate(epochs):
            e = epochs[i + 1][1] if i + 1 < len(epochs) else float("inf")
            groups.append([r for r in sel if s <= r["t"] < e])
        for c in order + ["TOTAL"]:
            cells = []
            for g in groups:
                k = len(g) if c == "TOTAL" else sum(r["cls"] == c for r in g)
                cells.append(f"{k:>6} ({100*k/max(len(g),1):4.1f}%)" if c != "TOTAL" else f"{k:>17}")
            print(f"  {c:18}" + "".join(f"{x:>17}" for x in cells))

    for kind in ("whole", "preview"):
        sel = [r for r in rows if r["kind"] == kind]
        table(f"== {kind} offers, all sessions, all prompts ==", sel)
        table(f"== {kind} offers, organic (not skill-concierge cwd), work prompts only ==",
              [r for r in sel if not r["meta"] and r["work"]])
    org = [r for r in rows if r["kind"] == "whole" and not r["meta"] and r["work"]]
    searched = [r for r in org if r["searches"]]
    print(f"\norganic whole-shelf work turns: {len(org)}; searched: {len(searched)}; "
          f"search calls: {sum(len(r['searches']) for r in searched)}")
    pos = Counter()
    for r in org:
        for u in r["used"]:
            for i, p in enumerate(r["prim"]):
                if au._same_skill(u, p):
                    pos[i + 1] += 1
                    break
    print("rank in offer of a used offered skill:", dict(sorted(pos.items())))
    for c in a.list:
        print(f"\n-- {c} (organic work turns) --")
        for r in org if c != "*" else rows:
            if r["cls"] == c or c == "*":
                ts = __import__("datetime").datetime.fromtimestamp(r["t"]).strftime("%m-%d %H:%M")
                print(f"{ts} {r['sid'][:8]} {Path(r['cwd']).name:18} used={r['used']} offer={r['prim'][:5]}")
                print(f"    prompt: {r['prompt'][:160]!r}")
                for s in r["searches"]:
                    print(f"    search: {s['q'][:80]!r} -> {s['hits'][:6]}")


if __name__ == "__main__":
    main()
