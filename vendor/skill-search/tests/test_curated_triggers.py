"""Operator-curated trigger layer: triggers-curated.json beside the utterance corpus takes the
FIRST trigger slots, is capped and filtered, and fails open with one stderr line."""
import json
import pytest

from skill_search import server


@pytest.fixture()
def curated(tmp_path, monkeypatch):
    path = tmp_path / "triggers-curated.json"
    monkeypatch.setattr(server, "_CURATED_TRIG_PATH", path)
    monkeypatch.setattr(server, "_CURATED_TRIG_CACHE", None)
    monkeypatch.setattr(server, "SKILL_LLM_TRIGGERS", False)
    monkeypatch.setattr(server, "SKILL_BODY_TRIGGERS", False)

    def write(obj):
        path.write_text(obj if isinstance(obj, str) else json.dumps(obj), encoding="utf-8")
        monkeypatch.setattr(server, "_CURATED_TRIG_CACHE", None)
    return write


DESC = "does alpha things when the user needs alpha"


def test_curated_phrases_come_first_then_llm_then_description(curated, monkeypatch):
    curated({"x": ["fold session lessons into existing skills"]})
    monkeypatch.setattr(server, "SKILL_LLM_TRIGGERS", True)
    monkeypatch.setattr(server, "_llm_utterance_phrases", lambda n: ["an llm made phrase here"])
    out = server._trigger_phrases({"name": "x", "description": DESC})
    assert out[:3] == ["fold session lessons into existing skills", "an llm made phrase here", DESC]


def test_dedupe_is_case_insensitive(curated):
    curated({"x": ["Does Alpha Things When The User Needs Alpha"]})
    out = server._trigger_phrases({"name": "x", "description": DESC})
    assert len(out) == 1 and out[0].startswith("Does Alpha")


def test_cap_keeps_trig_max_all_curated(curated):
    curated({"x": [f"curated phrase number {i}" for i in range(20)]})
    out = server._trigger_phrases({"name": "x", "description": DESC})
    assert len(out) == server._TRIG_MAX
    assert all(p.startswith("curated phrase") for p in out)


def test_short_long_and_non_string_phrases_are_dropped(curated):
    curated({"x": ["too short", "y" * 201, 42, "  a   perfectly   fine   phrase  "]})
    assert server._curated_phrases("x") == ["a perfectly fine phrase"]


def test_absent_file_is_byte_identical_to_description_only(curated):
    assert server._trigger_phrases({"name": "x", "description": DESC}) == server._split_phrases(DESC)


def test_underscore_keys_are_ignored(curated):
    curated({"_note": ["this is documentation not a phrase"], "x": ["a real curated phrase"]})
    assert server._curated_phrases("_note") == []
    assert server._curated_phrases("x") == ["a real curated phrase"]


@pytest.mark.parametrize("bad", ["[]", json.dumps({"x": "not a list"}), "{not json", "[" * 200000])
def test_malformed_file_fails_open_with_one_stderr_line(curated, capsys, bad):
    curated(bad)
    assert server._curated_phrases("x") == []
    assert server._trigger_phrases({"name": "x", "description": DESC}) == server._split_phrases(DESC)
    err = capsys.readouterr().err
    assert err.count("triggers-curated.json unreadable") == 1


def test_curated_path_is_hermetic_under_tests():
    assert ".claude" not in str(server._CURATED_TRIG_PATH)


def test_build_index_rereads_the_curated_file(curated, tmp_path, monkeypatch):
    skill = {"name": "cur-x", "description": DESC, "path": str(tmp_path / "SKILL.md"), "body": "b",
             "scope": "personal"}
    monkeypatch.setattr(server, "discover_skills", lambda: [dict(skill)])
    monkeypatch.setattr(server, "COLLECTION", "curated_reload_test")
    monkeypatch.setattr(server, "embed_batch",
                        lambda texts: [[float(len(t) % 7 + 1)] + [0.0] * 383 for t in texts])
    monkeypatch.setattr(server, "_write_next_skills_sidecar", lambda s: None)
    monkeypatch.setattr(server, "_write_manifest", lambda n: None)

    def trigger_texts():
        pts, _ = server._qdrant.scroll(collection_name="curated_reload_test", limit=100,
                                       with_payload=True)
        return sorted(p.payload.get("content_hash") for p in pts if p.payload.get("kind") == "trigger")

    curated({"cur-x": ["first curated phrasing here"]})
    server.build_index(force=True)
    before = trigger_texts()
    # edit the file WITHOUT the fixture's cache reset, leaving a stale, well-formed cache behind:
    # only build_index's own reset can make the new phrasing reach the index.
    (tmp_path / "triggers-curated.json").write_text(
        json.dumps({"cur-x": ["second curated phrasing here"]}), encoding="utf-8")
    server._CURATED_TRIG_CACHE = {"cur-x": ["first curated phrasing here"]}
    server.build_index()
    after = trigger_texts()
    assert before != after
