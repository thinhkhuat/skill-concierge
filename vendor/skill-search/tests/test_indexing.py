"""Tests for server's indexing logic. The pure-logic tests run offline; the
end-to-end test (marked `integration`) actually embeds + indexes via the
default service-free tier and is skipped unless run explicitly."""

import json
import uuid

import pytest

from skill_search import skills_discovery as sd
from skill_search import server   # conftest pins embedded/offline config before this import


# --- pure helpers (offline) ----------------------------------------------

def test_point_id_is_valid_uuid_stable_and_unique():
    a, b = server._point_id("foo"), server._point_id("foo")
    assert a == b                      # stable -> reindex upserts, not dupes
    uuid.UUID(a)                       # valid UUID (Qdrant rejects raw md5 hex)
    assert server._point_id("bar") != a


def test_content_hash_deterministic():
    assert server._content_hash("x") == server._content_hash("x")
    assert server._content_hash("x") != server._content_hash("y")


def test_disk_signature_counts_and_staleness_round_trip(tmp_path, monkeypatch):
    d = tmp_path / "p" / "sk"
    d.mkdir(parents=True)
    f = d / "SKILL.md"
    f.write_text("---\nname: sk\ndescription: d\n---\nb")
    monkeypatch.setattr(sd, "SKILL_DIRS", [tmp_path / "p"])
    monkeypatch.setattr(sd, "PLUGIN_GLOB", str(tmp_path / "none" / "**" / "SKILL.md"))
    monkeypatch.setattr(server, "META_PATH", tmp_path / "meta.json")

    assert server._disk_signature()["count"] == 1
    assert server._staleness_warning() is not None        # no manifest yet
    server._write_manifest(1)
    assert server._staleness_warning() is None            # fresh
    import os
    os.utime(f, (1, 1))                                   # touch -> drift
    assert server._staleness_warning() is not None


def test_trigger_phrases_body_on_adds_and_dedupes(monkeypatch):
    monkeypatch.setattr(server, "SKILL_BODY_TRIGGERS", True)
    s = {
        "name": "x",
        "description": "does alpha things when the user needs alpha",
        "body_triggers": [
            "does alpha things when the user needs alpha",   # dup of description
            "a totally new body-derived trigger phrase",
        ],
    }
    phrases = server._trigger_phrases(s)
    assert "a totally new body-derived trigger phrase" in phrases
    assert phrases.count("does alpha things when the user needs alpha") == 1


def test_trigger_phrases_body_off_is_description_only(monkeypatch):
    monkeypatch.setattr(server, "SKILL_BODY_TRIGGERS", False)
    s = {
        "name": "x",
        "description": "does alpha things when the user needs alpha",
        "body_triggers": ["a totally new body-derived trigger phrase"],
    }
    assert server._trigger_phrases(s) == server._split_phrases(s["description"])


def test_trigger_phrases_combined_cap_respects_trig_max(monkeypatch):
    monkeypatch.setattr(server, "SKILL_BODY_TRIGGERS", True)
    desc = ". ".join(f"description phrase number {i}" for i in range(20))
    s = {"name": "x", "description": desc,
         "body_triggers": ["a totally new body-derived trigger phrase"]}
    assert len(server._trigger_phrases(s)) <= server._TRIG_MAX


def test_manifest_records_backend_and_dim(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "META_PATH", tmp_path / "meta.json")
    monkeypatch.setattr(sd, "SKILL_DIRS", [tmp_path / "empty"])
    monkeypatch.setattr(sd, "PLUGIN_GLOB", str(tmp_path / "none" / "**" / "SKILL.md"))
    server._write_manifest(7)
    m = json.loads((tmp_path / "meta.json").read_text())
    assert m["indexed"] == 7
    assert m["dim"] == 384                                # from SKILL_VECTOR_SIZE
    assert m["backend"] == "fastembed"


# --- end-to-end (loads the embedder; opt-in) -----------------------------

@pytest.mark.integration
def test_end_to_end_build_search_incremental():
    stats = server.build_index(force=True)
    assert stats["indexed"] > 0 and stats["embedded"] == stats["indexed"]

    hits = json.loads(server.search_skills("debug a failing test"))["results"]
    assert len(hits) > 0
    assert all("name" in h and "score" in h for h in hits)

    again = server.build_index()                         # nothing changed
    assert again["embedded"] == 0 and again["skipped"] == stats["indexed"]
