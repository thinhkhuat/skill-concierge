"""Per-turn "did this human turn need a specialized skill?" extract from real Claude Code
transcripts — a candidate labelled corpus for calibrating a needs-a-skill gate with zero
hand-written prompts.

READ-ONLY over ~/.claude/projects/**/*.jsonl and the invocation ledger (live + archive).
Writes only ~/.claude/skill-concierge/jev-calibration/real-turn-labels.jsonl (mode 600, one row
per genuine human turn). The rows are VERBATIM private prompts: the output never lives in this
repo, which is public. `--stats` reads that file back and prints the summary tables as JSON.
Feeds scripts/calibrate_jev_gate.py.

Reuses skills/skill-usage-audit/scripts/audit_skill_usage.py (imported, not copied): ruling
regexes (_USING/_SKIPPING/_RERULE via _declared), norm(), the enforcer's authorized-skip
signatures (_AUTHORIZED_SIGNATURES), the search slugs, the subagent path rule, the dispatch
markers and the meta keywords. The harness-message head regex is the enforcer's own
_HARNESS_MSG_RE, loaded through calibrate_jev_gate.load_enforcer (ledger pointed at a temp dir).

Run:  ~/.claude/skills/.venv/bin/python3 scripts/extract_turn_labels.py [--stats]
"""
import collections
import datetime as dt
import glob
import json
import os
import re
import sys
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "skills", "skill-usage-audit", "scripts"))
sys.path.insert(0, HERE)
import audit_skill_usage as A  # noqa: E402
import calibrate_jev_gate as CAL  # noqa: E402

PROJECTS = A.PROJECTS
LEDGERS = [os.path.expanduser("~/.claude/skill-concierge/logs/skill-invocation-ledger.archive-260706.jsonl"),
           os.path.expanduser("~/.claude/skill-concierge/logs/skill-invocation-ledger.log")]
OUT = str(CAL.CAL_DIR / "real-turn-labels.jsonl")
TZ = ZoneInfo("Asia/Saigon")

HARNESS_MSG_RE = CAL.load_enforcer()._HARNESS_MSG_RE   # ADR-0054 lane, single source
# Further non-human heads seen in this store (survey 2026-09-26).
COMMAND_RE = re.compile(r"^\s*(?:/|<command-name>|<command-message>|<local-command-stdout>|<local-command-stderr>"
                        r"|<bash-input>|<bash-stdout>|<bash-stderr>|Caveat: The messages below were generated)")
QUEUED_RE = re.compile(r"^\s*Meanwhile, ")          # queued monitor/heartbeat messages
SCHEDULED_RE = re.compile(r"^\s*\[Scheduled Task:")
CHANNEL_RE = re.compile(r"^\s*\[(?:TG|Telegram|Zalo|Slack|Discord)[^\]]*\]")
ORCH_RE = re.compile(r"^\s*(?:<conversation_history>|Team: \"[^\"]*\"\s*\n+## Team Governance|## Team Governance)")
# sdk-entrypoint-only programmatic heads (orchestrators, prompt drafters, evaluators)
SDK_HEAD_RE = re.compile(r"^\s*(?:Draft the user is typing:|Recent conversation:|## New Messages|Reply with OK\."
                         r"|User: |\[Assistant Rules\]|\[your Bash|\[Relevant skills for|# Session kickoff"
                         r"|Bambooed architect mode|say a one-word greeting)")
DISPATCH_MARKERS = A._DISPATCH_MARKERS + ("## Team Governance",)
SDK_REPLAY_MIN_SESSIONS = 3   # same sdk prompt verbatim in >=3 sessions = replayed fixture

LEG_BY_SIG = {"full-catalogue retrieval ran": "getaway", "intent-margin classifier": "intent",
              "self-referential recap lane": "selfref", "harness-message lane": "harness",
              "Jev needs-a-skill gate": "jev"}
assert set(LEG_BY_SIG) == set(A._AUTHORIZED_SIGNATURES), "signature drift vs audit script"

# Line-1 rulings. The skip ruling is `NO SKILL: <why>` since v0.52.0 (ADR-0062) — any case, colon
# required, so prose opening "No skill…" is not a ruling — and the old `SKIPPING` form still
# reads. Both are reported as "SKIPPING", so label rules and older corpus rows stay comparable.
RULING_RE = re.compile(r"^\W*(?:(?i:(USING|SEARCH|SKIPPING))\b:?|(?i:(NO SKILL)):)\s*(.*)$")


def ruling_of(line):
    """-> (kind, rest) for a ruling line, kind in USING / SEARCH / SKIPPING; None otherwise."""
    m = RULING_RE.match(line)
    if not m:
        return None
    return ("SKIPPING" if m.group(2) else m.group(1).upper()), m.group(3)
VN_CHARS = set("ăâđêôơưàáảãạằắẳẵặầấẩẫậèéẻẽẹềếểễệìíỉĩịòóỏõọồốổỗộờớởỡợùúủũụừứửữựỳýỷỹỵ")
SKILL_MD_RE = re.compile(r"([A-Za-z0-9][\w.\-]*)/(?:SKILL\.md\b|references/)")
BASE_DIR_RE = re.compile(r"Base directory for this skill:\s*(\S+)")

# Next-turn correction patterns (label-noise indicator): the user's NEXT prompt (commands
# included) pushes back on the skill ruling. Conservative; the matched pattern is recorded.
CORRECTION_RES = [
    ("come-clean", re.compile(r"/come-clean|\bcome[- ]clean\b", re.I)),
    ("you-skipped", re.compile(r"\byou (?:just )?skipp?ed\b", re.I)),
    ("use-the-skill", re.compile(r"\b(?:use|invoke|load|run|apply) (?:the|a|that|this|your|my) [\w:\-]*\s*skills?\b", re.I)),
    ("why-no-skill", re.compile(r"\bwhy (?:didn'?t|did not|don'?t|no|not) (?:you )?(?:use|invoke|load|pick|search)\b", re.I)),
    ("skip-doctrine", re.compile(r"\bfalse[- ]?skip|\bno search,? no skip|\bskill-first\b|\bSKIPPING\b|(?-i:NO SKILL:)", re.I)),
    ("dodge", re.compile(r"\bdodg(?:e|ed|ing)\b", re.I)),
    ("vn-dung-skill", re.compile(r"(?:dùng|gọi|xài|sử dụng) (?:cái |con )?skill|sao (?:không|ko|k) (?:dùng|gọi)", re.I)),
]


def keys(name):
    """Match keys for a skill name: canonical form + the post-colon base ('ak:cook' -> 'cook')."""
    parts = (name or "").strip().lstrip("/").split()   # a bare "/" leaves nothing to split
    if not parts:
        return set()
    raw = parts[0].lower()
    return {A.norm(raw), raw.split(":")[-1]}


def lang_of(text):
    letters = [c for c in text.lower() if c.isalpha()]
    if not letters:
        return "none"
    vn = sum(1 for c in letters if c in VN_CHARS)
    if vn >= 3 and vn / len(letters) >= 0.04:
        return "vi"
    if vn >= 2:
        return "mixed"
    return "en"


def load_ledger():
    """(sid, q[:120]) -> {'turn': [t...], 'offer': [(t, band, offered, jev)...]}"""
    idx = collections.defaultdict(lambda: {"turn": [], "offer": []})
    n = 0
    for path in LEDGERS:
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8", errors="replace") as fh:
            for ln in fh:
                try:
                    r = json.loads(ln)
                except json.JSONDecodeError:
                    continue
                ev = r.get("ev")
                if ev not in ("turn", "offer") or not r.get("sid"):
                    continue
                key = (r["sid"], r.get("q") or "")
                n += 1
                if ev == "turn":
                    idx[key]["turn"].append(r.get("t", 0))
                else:
                    idx[key]["offer"].append((r.get("t", 0), r.get("band"), r.get("offered") or [], r.get("jev")))
    return idx, n


def prompt_text(rec):
    c = (rec.get("message") or {}).get("content")
    if isinstance(c, str):
        return c, False
    if isinstance(c, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
            return None, False  # tool_result: not a turn boundary
        txt = "\n".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
        return txt, any(isinstance(b, dict) and b.get("type") == "image" for b in c)
    return None, False


def classify_prompt(rec, txt):
    """None for a genuine human prompt, else the exclusion kind."""
    kind = (rec.get("origin") or {}).get("kind")
    if kind and kind != "human":
        return "origin:" + kind
    if rec.get("isCompactSummary"):
        return "compact_summary"
    if not txt.strip():
        return "empty"
    for name, rx in (("harness_msg", HARNESS_MSG_RE), ("command", COMMAND_RE), ("queued_msg", QUEUED_RE),
                     ("orchestrator_payload", ORCH_RE), ("scheduled_task", SCHEDULED_RE),
                     ("channel_relay", CHANNEL_RE)):
        if rx.match(txt):
            return name
    if (rec.get("entrypoint") or "").startswith("sdk") and SDK_HEAD_RE.match(txt):
        return "sdk_programmatic"
    return None


def first_line(text):
    for ln in text.splitlines():
        if ln.strip():
            return ln.strip()
    return ""


def names_in(rest):
    """Skill names on a USING line: 'a, b + c then d — why' -> ['a','b','c','d'] (raw lowercase)."""
    rest = re.split(r"\s[—–-]\s|\s\(|:\s|\.\s", rest, maxsplit=1)[0]
    out = []
    for tok in re.split(r"[,+&]|\s+then\s+|\s+and\s+|\s+→\s+|\s+->\s+", rest):
        tok = tok.strip().strip("`*_'\".").lstrip("/").lower()
        tok = tok.split()[0] if tok.split() else ""
        n = A.norm(tok)
        if n and n not in A._NOT_A_SKILL and re.match(r"^[a-z0-9][a-z0-9_:\-]*$", tok):
            out.append(tok)
    return out


def new_turn(rec, txt, has_img, excl, fp):
    return {"rec": rec, "txt": txt, "has_img": has_img, "excl": excl, "file": fp,
            "texts": [], "skill_calls": [], "search_calls": 0, "search_queries": [],
            "consult_calls": 0, "get_skill": [], "skill_md": [], "body_injected": [], "slash": [],
            "n_tools": 0, "legs": set(), "mandate_seen": False, "interrupted": False, "n_assistant": 0}


def loaded_keys(tn):
    ks = set()
    for n in tn["skill_calls"] + tn["get_skill"] + tn["skill_md"] + tn["body_injected"] + tn["slash"]:
        ks |= keys(n)
    return ks


def scan_file(fp, meta_kw):
    turns, cur, sess_text = [], None, []
    dispatched = first_prompt_seen = False
    with open(fp, encoding="utf-8", errors="replace") as fh:
        for ln in fh:
            is_att = '"type":"attachment"' in ln and (A.AUTHORIZED_SKIP_MARKER in ln or "SKILL-FIRST" in ln)
            if not ('"type":"user"' in ln or '"type":"assistant"' in ln or is_att):
                continue
            try:
                rec = json.loads(ln)
            except json.JSONDecodeError:
                continue
            typ = rec.get("type")
            if typ == "user":
                txt, has_img = prompt_text(rec)
                if rec.get("isMeta"):
                    # skill-body injections (Skill tool or slash) arrive as isMeta user records
                    if cur is not None and txt:
                        for d in BASE_DIR_RE.findall(txt):
                            cur["body_injected"].append(os.path.basename(d.rstrip("/")))
                        if A.AUTHORIZED_SKIP_MARKER in txt and cur["n_assistant"] == 0:
                            cur["legs"] |= {leg for s, leg in LEG_BY_SIG.items() if s in txt}
                    continue
                if txt is None:
                    continue  # tool_result
                if txt.lstrip().startswith("[Request interrupted by user") and cur is not None:
                    cur["interrupted"] = True
                if not first_prompt_seen:
                    first_prompt_seen = True
                    dispatched = any(m in txt for m in DISPATCH_MARKERS)
                excl = classify_prompt(rec, txt)
                if cur is not None:
                    turns.append(cur)
                cur = new_turn(rec, txt, has_img, excl, fp)
                if excl == "command":
                    cur["slash"] = [A.norm(m) for m in A._CMD.findall(txt)] or (
                        [txt.strip().split()[0].lstrip("/")] if txt.strip().startswith("/") else [])
                if excl is None:
                    sess_text.append(txt[:400].lower())
                continue
            if cur is None:
                continue
            if typ == "attachment":
                own = A._enforcer_output(rec)   # the enforcer's own output only, as the audit reads it
                if not own or cur["n_assistant"]:
                    continue
                body = "\n".join(own)
                if A.AUTHORIZED_SKIP_MARKER in body:
                    cur["legs"] |= {leg for s, leg in LEG_BY_SIG.items() if s in body}
                if "SKILL-FIRST" in body:
                    cur["mandate_seen"] = True
                continue
            if rec.get("isSidechain"):
                continue
            cur["n_assistant"] += 1
            for b in (rec.get("message") or {}).get("content") or []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text" and b.get("text", "").strip():
                    cur["texts"].append(b["text"])
                elif b.get("type") == "tool_use":
                    cur["n_tools"] += 1
                    nm = b.get("name") or ""
                    inp = b.get("input") or {}
                    if nm == "Skill":
                        s = str(inp.get("skill") or "").strip().lower()
                        if s:
                            cur["skill_calls"].append(s)
                            if A.norm(s) in A._SEARCH_SLUGS:
                                cur["search_calls"] += 1
                    elif "search_skills" in nm:
                        cur["search_calls"] += 1
                        cur["search_queries"].append(str(inp.get("query") or inp.get("queries") or "")[:120])
                    elif "consult_candidates" in nm:
                        cur["consult_calls"] += 1
                    elif nm.endswith("get_skill"):
                        s = str(inp.get("name") or inp.get("skill") or "").strip().lower()
                        if s:
                            cur["get_skill"].append(s)
                    elif nm in ("Read", "Bash"):
                        s = str(inp.get("file_path") or inp.get("command") or "")
                        cur["skill_md"] += [m.lower() for m in SKILL_MD_RE.findall(s)]
    if cur is not None:
        turns.append(cur)
    meta = any(kw in t for t in sess_text for kw in meta_kw)
    return turns, dispatched, meta


def rule_turn(tn, loaded_before):
    """Ruling fields + candidate label for one genuine human turn. Every branch names its rule."""
    texts = tn["texts"]
    l1 = first_line(texts[0]) if texts else ""
    m = ruling_of(l1)
    ruling = m[0] if m else ("NONE" if texts else "NO_REPLY")
    ruling_names = names_in(m[1]) if (m and ruling == "USING") else []
    final, final_names = ruling, ruling_names
    if ruling == "SEARCH":   # final = first USING/SKIPPING line after the SEARCH line, anywhere in the turn
        final, final_names, seen = "SEARCH_ONLY", [], False
        for tx in texts:
            for ln in tx.splitlines():
                mm = ruling_of(ln.strip())
                if not mm:
                    continue
                k = mm[0]
                if k == "SEARCH":
                    seen = True
                elif seen:
                    final, final_names = k, (names_in(mm[1]) if k == "USING" else [])
                    break
            if final != "SEARCH_ONLY":
                break
    rerule = [A.norm(x) for tx in texts for x in A._RERULE.findall(tx)]
    now = loaded_keys(tn)
    calls = [c for c in tn["skill_calls"] if A.norm(c) not in A._SEARCH_SLUGS]
    leg = sorted(tn["legs"])[0] if tn["legs"] else None
    search = tn["search_calls"] > 0
    plow = tn["txt"].lower()
    named = sorted({n for n in final_names + calls + tn["get_skill"]
                    if any(len(k) >= 4 and k in plow for k in keys(n))})

    if final == "USING" and final_names:
        if any(keys(n) & now for n in final_names):
            label, rule = "NEEDS_SKILL", "using+executed_this_turn"
        elif any(keys(n) & loaded_before for n in final_names):
            label, rule = "NEEDS_SKILL", "using+loaded_earlier_in_session"
        else:
            label, rule = "UNLABELLABLE", "using_not_executed"
    elif final == "USING":
        label, rule = "UNLABELLABLE", "using_unparseable_name"
    elif calls or tn["get_skill"]:
        label, rule = "NEEDS_SKILL_WEAK", "skill_call_without_using_ruling"
    elif leg:   # hook pre-authorized a skip and no skill was used: the label would echo the hook
        label, rule = "UNLABELLABLE", "authorized_skip_circular:" + leg
    elif final == "SKIPPING":
        if search:
            label, rule = "NO_SKILL", "searched_then_skipped"
        elif tn["n_tools"] == 0 and len(tn["txt"].split()) <= 15:
            label, rule = "NO_SKILL", "skip_nosearch_conversational"
        else:
            label, rule = "UNLABELLABLE", "false_skip_no_search"
    elif final == "SEARCH_ONLY" and search and not now:
        # a real search ran, nothing was loaded, no formal final line: a behavioural skip
        label, rule = "NO_SKILL_WEAK", "search_call_then_no_skill_used(no_final_line)"
    elif final == "SEARCH_ONLY":
        label, rule = "UNLABELLABLE", "search_line_no_final_ruling" + ("+search_call" if search else "+no_search_call")
    elif ruling == "NO_REPLY":
        label, rule = "UNLABELLABLE", "no_assistant_text"
    else:
        label, rule = "UNLABELLABLE", "no_ruling_line"
    return {"ruling_line": l1[:200], "ruling": ruling, "ruling_names": ruling_names,
            "final_ruling": final, "final_names": final_names, "rerule_from": rerule,
            "hook_skillcheck_leg": leg, "hook_legs_all": sorted(tn["legs"]),
            "hook_mandate_seen": tn["mandate_seen"], "skill_named_in_prompt": named,
            "label": label, "label_rule": rule}


def extract():
    ledger, n_ledger = load_ledger()
    meta_kw = [k.lower() for k in A.DEFAULT_META]
    files = sorted(f for f in glob.glob(os.path.join(PROJECTS, "**", "*.jsonl"), recursive=True)
                   if A._SUBAGENT_PATH not in f)
    rows, by_uuid = {}, {}
    excl = collections.Counter()
    dup = 0
    for fp in files:
        turns, dispatched, meta = scan_file(fp, meta_kw)
        loaded = set()
        recent = []   # skill names loaded earlier in the session, newest last (context the live hook can see)

        def note(tn):
            for n in tn["skill_calls"] + tn["get_skill"] + tn["skill_md"] + tn["body_injected"] + tn["slash"]:
                n = A.norm(n)
                if n and n not in A._SEARCH_SLUGS:
                    if n in recent:
                        recent.remove(n)
                    recent.append(n)
        for i, tn in enumerate(turns):
            rec = tn["rec"]
            sid = rec.get("sessionId")
            if tn["excl"] is None and dispatched:
                tn["excl"] = "dispatched_session"
            if tn["excl"] is not None:
                excl[tn["excl"]] += 1
                loaded |= loaded_keys(tn)
                note(tn)
                continue
            prev = next((turns[j]["texts"][-1] for j in range(i - 1, -1, -1) if turns[j]["texts"]), "")
            ctx_skills = recent[-3:]
            nxt = next((turns[j]["txt"] for j in range(i + 1, len(turns)) if turns[j]["excl"] in (None, "command")), None)
            r = rule_turn(tn, loaded)
            loaded |= loaded_keys(tn)
            note(tn)
            uid = rec.get("uuid")
            if uid in by_uuid:   # prompt record copied into a resumed/forked file: keep the richer copy
                dup += 1
                if len(tn["texts"]) <= by_uuid[uid]:
                    continue
            ts = rec.get("timestamp") or ""
            try:
                tloc = dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(TZ)
            except ValueError:
                tloc = None
            band = top = jev = offered = None
            lg = ledger.get((sid, tn["txt"].strip()[:120]))
            if lg and lg["offer"] and tloc:
                o = min(lg["offer"], key=lambda x: abs(x[0] - tloc.timestamp()))
                if abs(o[0] - tloc.timestamp()) < 600:
                    band, top, jev, offered = o[1], o[2][:3], o[3], o[2]
            corr = next((name for name, rx in CORRECTION_RES if nxt and rx.search(nxt[:2000])), None)
            ep = rec.get("entrypoint") or ""
            rows[uid] = {
                "sid": sid, "project": os.path.basename(os.path.dirname(fp)), "uuid": uid,
                "ts_utc": ts, "ts_local": tloc.isoformat() if tloc else None,
                "month": tloc.strftime("%Y-%m") if tloc else None,
                "entrypoint": ep or None, "entry_class": "sdk" if ep.startswith("sdk") else "interactive",
                "cc_version": rec.get("version"), "origin_kind": (rec.get("origin") or {}).get("kind"),
                "meta_session": meta, "has_image": tn["has_img"],
                "prompt": tn["txt"][:4000], "prompt_chars": len(tn["txt"]),
                "prev_assistant": prev[-1500:], "session_skills": ctx_skills,
                "prompt_words": len(tn["txt"].split()), "lang": lang_of(tn["txt"]),
                **r,
                "search_call": tn["search_calls"] > 0, "n_search_calls": tn["search_calls"],
                "search_queries": tn["search_queries"][:3], "consult_call": tn["consult_calls"] > 0,
                "skill_call": any(A.norm(c) not in A._SEARCH_SLUGS for c in tn["skill_calls"]),
                "skill_calls": tn["skill_calls"][:8], "get_skill": tn["get_skill"][:8],
                "skill_md_reads": sorted(set(tn["skill_md"]))[:8], "skill_bodies_injected": tn["body_injected"][:8],
                "n_tool_calls": tn["n_tools"], "n_assistant_records": tn["n_assistant"],
                "interrupted": tn["interrupted"],
                "ledger_turn_row": bool(lg and lg["turn"]), "ledger_offer_band": band,
                "ledger_offer_top3": top, "ledger_offered": offered, "ledger_jev": jev,
                "next_prompt_correction": corr, "next_prompt_head": (nxt or "")[:160] if corr else None,
            }
            by_uuid[uid] = len(tn["texts"])
    # sdk fixture replays: the same sdk prompt verbatim in >= N distinct sessions
    sess_by_prompt = collections.defaultdict(set)
    for r in rows.values():
        if r["entry_class"] == "sdk":
            sess_by_prompt[r["prompt"][:500]].add(r["sid"])
    out = []
    for r in rows.values():
        if r["entry_class"] == "sdk" and len(sess_by_prompt[r["prompt"][:500]]) >= SDK_REPLAY_MIN_SESSIONS:
            excl["sdk_fixture_replay"] += 1
            continue
        out.append(r)
    out.sort(key=lambda r: r["ts_utc"] or "")
    os.makedirs(os.path.dirname(OUT), mode=0o700, exist_ok=True)
    fd = os.open(OUT, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        for r in out:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(json.dumps({"files_scanned": len(files), "rows_written": len(out), "dup_prompt_records": dup,
                      "excluded_by_kind": dict(excl.most_common()), "ledger_rows_indexed": n_ledger}, indent=1))


def stats():
    R = [json.loads(ln) for ln in open(OUT, encoding="utf-8")]
    C = collections.Counter
    lab = lambda r: r["label"]  # noqa: E731

    def tab(key, rows=R):
        t = collections.defaultdict(C)
        for r in rows:
            t[key(r)][lab(r)] += 1
        return {str(k): dict(v) | {"total": sum(v.values())} for k, v in sorted(t.items(), key=lambda kv: str(kv[0]))}
    inter = [r for r in R if r["entry_class"] == "interactive"]
    res = {
        "total": len(R), "interactive": len(inter),
        "labels": dict(C(map(lab, R))), "labels_interactive": dict(C(map(lab, inter))),
        "rules": {f"{a}|{b}": n for (a, b), n in C((r["label"], r["label_rule"]) for r in R).most_common()},
        "by_month": tab(lambda r: r["month"]), "by_lang": tab(lambda r: r["lang"]),
        "by_entry_class": tab(lambda r: r["entry_class"]), "by_meta_session": tab(lambda r: r["meta_session"]),
        "hook_leg_x_label": tab(lambda r: r["hook_skillcheck_leg"]),
        "ledger_band_x_label": tab(lambda r: r["ledger_offer_band"]),
        "ledger_band_x_leg": dict(C(f"{r['ledger_offer_band']}|{r['hook_skillcheck_leg']}" for r in R
                                    if r["ledger_offer_band"] in ("intent_skip", "getaway", "jev_skip", "selfref_skip")
                                    or r["hook_skillcheck_leg"])),
        "ledger_match": {"turn_row": sum(r["ledger_turn_row"] for r in R),
                         "offer_band": sum(r["ledger_offer_band"] is not None for r in R),
                         "rows_since_ledger_start": sum(1 for r in R if (r["ts_utc"] or "") >= "2026-06-26")},
        "correction_x_label": tab(lambda r: r["next_prompt_correction"]),
        "skipping_without_search": {
            "all_final_skipping": sum(r["final_ruling"] == "SKIPPING" for r in R),
            "no_search_no_leg": sum(r["final_ruling"] == "SKIPPING" and not r["search_call"] and not r["hook_skillcheck_leg"] for r in R),
            "no_search_with_leg": sum(r["final_ruling"] == "SKIPPING" and not r["search_call"] and bool(r["hook_skillcheck_leg"]) for r in R),
            "with_search": sum(r["final_ruling"] == "SKIPPING" and r["search_call"] for r in R)},
        "skill_named_in_prompt_x_label": tab(lambda r: bool(r["skill_named_in_prompt"])),
        "interrupted_x_label": tab(lambda r: r["interrupted"]),
        "rerule_turns": sum(bool(r["rerule_from"]) for r in R),
        "clean_core": {  # the strictest usable subset: interactive, non-meta, non-circular, no correction
            lbl: sum(1 for r in inter if r["label"] == lbl and not r["meta_session"] and not r["next_prompt_correction"]
                     and not r["interrupted"]) for lbl in ("NEEDS_SKILL", "NO_SKILL", "NEEDS_SKILL_WEAK", "NO_SKILL_WEAK")},
    }
    print(json.dumps(res, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    args = sys.argv[1:]
    if args not in ([], ["--stats"]):
        # Anything else prints usage and stops: a bare run rewrites the private corpus.
        ok = args in (["-h"], ["--help"])
        print(__doc__.strip().splitlines()[-1].strip() + "\n(no argument: extract; --stats: summary)",
              file=sys.stdout if ok else sys.stderr)
        sys.exit(0 if ok else 2)
    stats() if args else extract()
