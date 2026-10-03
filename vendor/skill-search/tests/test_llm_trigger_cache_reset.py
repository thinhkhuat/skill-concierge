"""build_index re-reads the utterance corpus (triggers.json llm_triggers) instead of serving the
copy cached at first use, so an in-process reindex after a corpus rewrite embeds the new phrases."""
import json

from skill_search import server

DESC = "does alpha things when the user needs alpha"


def test_build_index_rereads_the_utterance_corpus(tmp_path, monkeypatch):
    corpus = tmp_path / "triggers.json"
    corpus.write_text(json.dumps({"llm-x": {"llm_triggers": {"triggers": ["fresh utterance phrase here"]}}}),
                      encoding="utf-8")
    monkeypatch.setattr(server, "_LLM_TRIG_PATH", str(corpus))
    # a stale, well-formed cache left behind by an earlier build in the same process
    monkeypatch.setattr(server, "_LLM_TRIG_CACHE", {"llm-x": ["stale utterance phrase here"]})
    assert server._llm_utterance_phrases("llm-x") == ["stale utterance phrase here"]

    skill = {"name": "llm-x", "description": DESC, "path": str(tmp_path / "SKILL.md"), "body": "b",
             "scope": "personal"}
    monkeypatch.setattr(server, "discover_skills", lambda: [dict(skill)])
    monkeypatch.setattr(server, "COLLECTION", "llm_cache_reset_test")
    monkeypatch.setattr(server, "embed_batch",
                        lambda texts: [[float(len(t) % 7 + 1)] + [0.0] * 383 for t in texts])
    monkeypatch.setattr(server, "_write_next_skills_sidecar", lambda s: None)
    monkeypatch.setattr(server, "_write_manifest", lambda n: None)
    server.build_index(force=True)

    assert server._llm_utterance_phrases("llm-x") == ["fresh utterance phrase here"]
