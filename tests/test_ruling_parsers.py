"""The skip ruling is `NO SKILL: <why>` since v0.52.0 (ADR-0062); `SKIPPING: none` before it.
Both readers of agent replies — the usage audit and the label extractor — must:
  • read both forms as the same ruling (months of transcripts use the old one);
  • not read prose that opens "No skill…" as a ruling (colon required; any case);
  • take a hook authorization (`SKILL-CHECK:` + a locked signature) only from the enforcer's own
    UserPromptSubmit output — never from the agent's text, a file echo, a memory or instructions
    attachment, or another hook quoting the line: a copied line must not let an agent authorize itself.
The audit is driven end to end over a fixture transcript store.
"""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "skill-usage-audit" / "scripts"))
sys.path.insert(0, str(ROOT / "scripts"))
import audit_skill_usage as A  # noqa: E402

AUTH = A.AUTHORIZED_SKIP_MARKER + " the intent-margin classifier judged this turn conversational/non-task."


def _rec(typ, content, **kw):
    return {"type": typ, "timestamp": "2026-09-26T09:00:00Z", "sessionId": "s1",
            "message": {"role": typ if typ != "attachment" else "user", "content": content}, **kw}


def _user(text):
    return _rec("user", text)


def _say(text):
    return _rec("assistant", [{"type": "text", "text": text}])


def _hook(text, event="UserPromptSubmit", kind="hook_additional_context"):
    return {"type": "attachment", "timestamp": "2026-09-26T09:00:00Z", "sessionId": "s1",
            "attachment": {"type": kind, "hookEvent": event, "content": [text]}}


def _audit(tmp_path, monkeypatch, records):
    d = tmp_path / "projects" / "p"
    d.mkdir(parents=True)
    (d / "s1.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))
    monkeypatch.setattr(A, "PROJECTS", str(tmp_path / "projects"))
    return A.audit(since=None, meta_keywords=[], subagent_stop=True)


def test_audit_reads_both_forms_and_ignores_prose(tmp_path, monkeypatch):
    r = _audit(tmp_path, monkeypatch, [
        _user("turn one"), _say("NO SKILL: searched nothing, just chatting"),
        _user("turn two"), _say("SKIPPING: none - trivial"),
        _user("turn three"), _say("No skill applies here, so here is the answer."),
    ])
    assert r["n_skip"] == 2
    assert (r["false_skip"], r["lawful_skip"], r["authorized_skip"]) == (2, 0, 0)


def test_audit_takes_authorization_only_from_hook_records(tmp_path, monkeypatch):
    r = _audit(tmp_path, monkeypatch, [
        _user("turn one"), _hook(AUTH), _say("NO SKILL: hook-cleared — conversational turn"),
        _user("turn two"), _say(AUTH + "\nNO SKILL: hook-cleared — I copied the line myself"),
    ])
    assert (r["false_skip"], r["authorized_skip"]) == (1, 1)


def test_audit_ignores_authorization_lines_other_records_quote(tmp_path, monkeypatch):
    """Reading or editing a file that quotes the line, a memory hook recalling it, the standing
    order or an isMeta record carrying it: none is the enforcer's verdict on this turn."""
    quoted = [
        _hook(AUTH, kind="edited_text_file"),
        _hook(AUTH, kind="nested_memory"),
        _hook(AUTH, event="PostToolUse"),
        _hook("[memory] recalled: " + AUTH),
        _hook(AUTH, event="SessionStart"),
        {**_user(AUTH), "isMeta": True},
    ]
    recs = []
    for i, q in enumerate(quoted):
        recs += [_user(f"turn {i}"), q, _say("NO SKILL: hook-cleared — quoted line")]
    r = _audit(tmp_path, monkeypatch, recs)
    assert (r["false_skip"], r["authorized_skip"]) == (len(quoted), 0)
    assert r["enforcer_verdicts"] == (0, 0, 0)


def test_audit_reads_markdown_wrapped_and_any_case_rulings(tmp_path, monkeypatch):
    r = _audit(tmp_path, monkeypatch, [
        _user("turn one"), _say("`NO SKILL: nothing fits`"),
        _user("turn two"), _say("**No skill: trivial**"),
        _user("turn three"), _say("No skill applies here."),
    ])
    assert r["n_skip"] == 2


def _extractor():
    """Import the extractor without leaking the env defaults its import sets (it loads the enforcer
    with long timeouts) into the rest of the test session."""
    saved = dict(os.environ)
    try:
        import extract_turn_labels as X
    finally:
        os.environ.clear()
        os.environ.update(saved)
    return X


def test_extractor_reads_both_forms_as_one_ruling():
    X = _extractor()
    assert X.ruling_of("NO SKILL: hook-cleared — conversational turn") == ("SKIPPING", "hook-cleared — conversational turn")
    assert X.ruling_of("SKIPPING: none") == ("SKIPPING", "none")
    assert X.ruling_of("skipping none") == ("SKIPPING", "none")
    assert X.ruling_of("USING: ak-git") == ("USING", "ak-git")
    assert X.ruling_of("SEARCH: postgres schema migration") == ("SEARCH", "postgres schema migration")
    assert X.ruling_of("No skill applies here.") is None
    assert X.ruling_of("NO SKILL applies") is None
    assert X.ruling_of("No skill: trivial") == ("SKIPPING", "trivial")
    assert X.ruling_of("`NO SKILL: nothing fits`") == ("SKIPPING", "nothing fits`")


def test_audit_scopes_a_verdict_to_turns_the_enforcer_ran(tmp_path, monkeypatch):
    """Stop-hook feedback and subagent prompts get no offer; their skips measure other hooks."""
    r = _audit(tmp_path, monkeypatch, [
        _user("turn one"), _hook("SKILL-FIRST · reply line 1 = USING: <skill> | …"), _say("NO SKILL: nothing fits"),
        _user("Stop hook feedback: finish the task"), _say("NO SKILL: continuing"),
    ])
    assert (r["false_skip"], r["lawful_skip"], r["authorized_skip"]) == (2, 0, 0)
    assert r["enforcer_verdicts"] == (1, 0, 0)


def test_a_consult_route_turn_is_an_enforcer_run_turn(tmp_path, monkeypatch):
    r = _audit(tmp_path, monkeypatch, [
        _user("which skills fit this"), _hook("CONSULT-ROUTE · this turn asks for a deliberated skill curation.\nreply line 1 = USING: skill-concierge:consult"),
        _say("NO SKILL: answering directly"),
    ])
    assert r["enforcer_verdicts"] == (1, 0, 0)


def test_an_authorization_that_arrives_after_the_ruling_does_not_count(tmp_path, monkeypatch):
    """A queued notification can bring a SKILL-CHECK: line after the agent already ruled."""
    r = _audit(tmp_path, monkeypatch, [
        _user("turn one"), _say("NO SKILL: nothing fits"), _hook(AUTH),
    ])
    assert (r["false_skip"], r["authorized_skip"]) == (1, 0)
    assert r["enforcer_verdicts"] == (0, 0, 0)


def test_the_audit_counts_each_skip_form_and_reads_bold_rulings(tmp_path, monkeypatch):
    r = _audit(tmp_path, monkeypatch, [
        _user("turn one"), _say("**SKIPPING:** none"),
        _user("turn two"), _say("NO SKILL: nothing fits"),
        _user("turn three"), _say("**Search results** follow."),
        _user("turn four"), _say("**USING: new-skill (re-rule: old-skill)**"),
    ])
    assert (r["n_skip"], r["n_skip_new"], r["n_search"]) == (2, 1, 0)
    assert r["rerules"]["old-skill"] == 1


def test_a_continuing_ruling_names_the_skill():
    """Rule 3's continuation form `USING: <name> (continuing)` counts as that skill."""
    assert A._declared("USING: study (continuing)") == (["study"], [])


def _tool(tool, **inp):
    return _rec("assistant", [{"type": "tool_use", "name": tool, "input": inp}])


def test_a_search_after_the_ruling_does_not_back_it(tmp_path, monkeypatch):
    """Rule 4: the search that backs a skip is shown before the ruling, in the same reply."""
    r = _audit(tmp_path, monkeypatch, [
        _user("turn one"), _say("NO SKILL: nothing fits"),
        _tool("mcp__plugin_skill-concierge_skill-search__search_skills", query="later"),
        _user("turn two"), _tool("mcp__plugin_skill-concierge_skill-search__search_skills", query="q"),
        _say("NO SKILL: the hits do not fit"),
    ])
    assert (r["false_skip"], r["lawful_skip"]) == (1, 1)


def test_the_harvest_keeps_the_ruling_that_was_judged(tmp_path, monkeypatch):
    import audit_skill_usage as A2
    captured = []
    real = A2._skip_verdicts
    monkeypatch.setattr(A2, "_skip_verdicts", lambda turns: captured.append(list(turns)) or real(turns))
    _audit(tmp_path, monkeypatch, [_user("turn one"), _say("NO SKILL: first reason"),
                                    _say("NO SKILL: hook-cleared — a later reply in the same turn")])
    assert captured[0][0]["skip_text"] == "NO SKILL: first reason"


def test_the_june_enforcer_head_still_marks_an_enforcer_run_turn(tmp_path, monkeypatch):
    """The 2026-06-25/26 offer opened "SKILL-FIRST (standing order)" with no USING in it."""
    r = _audit(tmp_path, monkeypatch, [
        _user("turn one"), _hook("SKILL-FIRST (standing order) — rule on the preview below"),
        _say("NO SKILL: nothing fits"),
    ])
    assert r["enforcer_verdicts"] == (1, 0, 0)


def test_prose_is_not_a_ruling_even_when_it_looks_like_one():
    assert A._declared("Using `rg` to find it") == ([], [])
    assert not A._SKIPPING.search("**Skipping the tests** for now")
    assert not A._USING.search("**Using the tool**")
    m = A._SKIPPING.search("intro\n\n`NO SKILL: x`")
    assert m and m.group("new") and "\n" not in m.group(0)


def test_continuations_are_counted_with_their_re_read(tmp_path, monkeypatch):
    r = _audit(tmp_path, monkeypatch, [
        _user("turn one"), _tool("Skill", skill="study"), _say("USING: study"),
        _user("turn two"), _say("USING: study (continuing)"),
        _tool("mcp__plugin_skill-concierge_skill-search__get_skill", name="study"),
        _user("turn three"), _say("USING: study (continuing)"),
        _user("turn four"), _say("USING: ak-cook (continuing)"),
    ])
    assert r["continuations"] == (3, 1, 1, 0)   # total, re-read in the turn, no earlier use, stale


def _audit_files(tmp_path, monkeypatch, files, since=None):
    for rel, records in files.items():
        f = tmp_path / "projects" / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))
    monkeypatch.setattr(A, "PROJECTS", str(tmp_path / "projects"))
    return A.audit(since=since, meta_keywords=[], subagent_stop=True)


def _at(rec, ts):
    return {**rec, "timestamp": ts}


def test_every_continuation_form_is_counted(tmp_path, monkeypatch):
    r = _audit(tmp_path, monkeypatch, [
        _user("turn one"), _tool("Skill", skill="study"), _tool("Skill", skill="ak-git"),
        _user("turn two"), _say("USING: study (continuing the migration)"),
        _user("turn three"), _say("**USING: ak-git (continued)**"),
        _user("turn four"), _say("USING: study, ak-git (continuation of the rebase)"),
    ])
    assert r["continuations"][0] == 4


def test_a_load_in_the_same_turn_is_the_re_read_not_an_earlier_use(tmp_path, monkeypatch):
    r = _audit(tmp_path, monkeypatch, [
        _user("turn one"), _tool("mcp__plugin_skill-concierge_skill-search__get_skill", name="study"),
        _say("USING: study (continuing)"),
    ])
    assert r["continuations"] == (1, 1, 1, 0)


def test_name_forms_of_one_skill_match(tmp_path, monkeypatch):
    r = _audit(tmp_path, monkeypatch, [
        _user("turn one"), _tool("Skill", skill="ak:cook"),
        _user("turn two"), _say("USING: cook (continuing)"),
        _tool("mcp__plugin_skill-concierge_skill-search__get_skill", name="ak:cook"),
    ])
    assert r["continuations"] == (1, 1, 0, 0)


def test_only_skill_search_s_own_get_skill_is_a_re_read(tmp_path, monkeypatch):
    r = _audit(tmp_path, monkeypatch, [
        _user("turn one"), _tool("Skill", skill="study"),
        _user("turn two"), _say("USING: study (continuing)"), _tool("mcp__other-server__get_skill", name="study"),
    ])
    assert r["continuations"] == (1, 0, 0, 0)


def test_a_slash_command_is_an_earlier_use(tmp_path, monkeypatch):
    r = _audit(tmp_path, monkeypatch, [
        _user("<command-name>/study</command-name>"),
        _user("turn two"), _say("USING: study (continuing)"),
    ])
    assert r["continuations"][2] == 0


def test_a_continuation_long_after_the_last_use_is_flagged_stale(tmp_path, monkeypatch):
    recs = [_user("turn 0"), _tool("Skill", skill="study")]
    for i in range(1, A.STALE_TURNS + 2):
        recs.append(_user(f"turn {i}"))
    recs.append(_say("USING: study (continuing)"))
    r = _audit(tmp_path, monkeypatch, recs)
    assert r["continuations"] == (1, 0, 0, 1)


def test_earlier_use_before_the_window_counts_and_subagents_are_excluded(tmp_path, monkeypatch):
    early, late = "2026-09-26T01:00:00Z", "2026-09-26T12:00:00Z"
    main = [_at(_user("turn one"), early), _at(_tool("Skill", skill="study"), early),
            _at(_user("turn two"), late), _at(_say("USING: study (continuing)"), late)]
    sub = [_at(_user("brief"), late), _at(_say("USING: other (continuing)"), late)]
    r = _audit_files(tmp_path, monkeypatch, {"p/s1.jsonl": main, "p/s1/subagents/a.jsonl": sub},
                     since=A.parse_since("2026-09-26 10:00:00"))
    assert r["continuations"] == (1, 0, 0, 0)
