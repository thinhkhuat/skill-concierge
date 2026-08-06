"""Tests for server's indexing logic. The pure-logic tests run offline; the
end-to-end test (marked `integration`) actually embeds + indexes via the
default service-free tier and is skipped unless run explicitly."""

import json
import os
import time
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


def test_disk_signature_is_content_not_mtime(tmp_path, monkeypatch):
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
    os.utime(f, (1, 1))                                   # mtime-only touch, content UNCHANGED
    assert server._staleness_warning() is None            # ROOT-CAUSE FIX: mtime move must NOT false-flag stale
    f.write_text("---\nname: sk\ndescription: d\n---\nCHANGED")   # a real content change
    assert server._staleness_warning() is not None        # real drift IS still detected


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


def test_body_section_re_and_server_label_re_stay_aligned():
    # `skills_discovery._BODY_SECTION_RE` and `server._LABEL_RE` are hand-mirrored
    # (skills_discovery.py:60-69). Every label server._LABEL_RE recognizes must also
    # open a body decision-section; the ONLY body-side extra is "when to use" (which
    # only ever appears as a markdown header, never in a one-line description). If a
    # future edit desyncs them, this fails.
    shared = ["triggers", "trigger", "examples", "example",
              "use when", "also use", "use this skill"]
    for label in shared:
        assert server._LABEL_RE.match(f"{label}: x"), f"server._LABEL_RE lost {label!r}"
        assert sd._BODY_SECTION_RE.match(f"{label}: x"), f"_BODY_SECTION_RE lost {label!r}"
    # "when to use" is the one body-only label — present body-side, absent server-side.
    assert sd._BODY_SECTION_RE.match("when to use: x")
    assert not server._LABEL_RE.match("when to use: x")


def test_manifest_records_backend_and_dim(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "META_PATH", tmp_path / "meta.json")
    monkeypatch.setattr(sd, "SKILL_DIRS", [tmp_path / "empty"])
    monkeypatch.setattr(sd, "PLUGIN_GLOB", str(tmp_path / "none" / "**" / "SKILL.md"))
    server._write_manifest(7)
    m = json.loads((tmp_path / "meta.json").read_text())
    assert m["indexed"] == 7
    assert m["dim"] == 384                                # from SKILL_VECTOR_SIZE
    assert m["backend"] == "fastembed"


# --- engine-build drift (long-lived server vs replaced venv) --------------
# A server keeps executing the engine it imported at start. When the venv engine is
# replaced under it, that server and every fresh process parse the same SKILL.md files
# with different parsers, so they derive different disk signatures from an UNCHANGED
# disk — and each reindex hands a false "disk changed" to the other side, forever.
# Recording the writer's build lets a reader tell "disk moved" from "different builds".

def test_manifest_records_engine_build(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "META_PATH", tmp_path / "meta.json")
    monkeypatch.setattr(sd, "SKILL_DIRS", [tmp_path / "empty"])
    monkeypatch.setattr(sd, "PLUGIN_GLOB", str(tmp_path / "none" / "**" / "SKILL.md"))
    server._write_manifest(1)
    m = json.loads((tmp_path / "meta.json").read_text())
    assert m["engine"] == server._ENGINE_BUILD
    assert m["engine"] != "unknown"                       # real id, not the fail-open value


def test_engine_drift_only_on_real_mismatch(monkeypatch):
    monkeypatch.setattr(server, "_ENGINE_BUILD", "aaaaaaaaaaaa")
    assert server._engine_drift({"engine": "bbbbbbbbbbbb"}) == "bbbbbbbbbbbb"
    assert server._engine_drift({"engine": "aaaaaaaaaaaa"}) is None
    # A manifest written before this field existed says nothing about the build. Guessing
    # drift there would reintroduce the very false alarm this exists to remove.
    assert server._engine_drift({}) is None
    # A sentinel on EITHER side identifies no build, so neither may be accused of drift —
    # doing so would demand a restart that fixes nothing.
    assert server._engine_drift({"engine": "unknown"}) is None
    monkeypatch.setattr(server, "_ENGINE_BUILD", "unknown")
    assert server._engine_drift({"engine": "bbbbbbbbbbbb"}) is None


def test_staleness_warning_blames_engine_not_disk_on_drift(tmp_path, monkeypatch):
    meta = tmp_path / "meta.json"
    # Signature deliberately bogus: on a build mismatch the comparison is meaningless,
    # so the disk must NOT be blamed even though the signatures differ.
    meta.write_text(json.dumps({"signature": {"count": 99, "hash": "nope"},
                                "engine": "bbbbbbbbbbbb"}))
    monkeypatch.setattr(server, "META_PATH", meta)
    monkeypatch.setattr(server, "_ENGINE_BUILD", "aaaaaaaaaaaa")
    monkeypatch.setattr(sd, "SKILL_DIRS", [tmp_path / "empty"])
    monkeypatch.setattr(sd, "PLUGIN_GLOB", str(tmp_path / "none" / "**" / "SKILL.md"))
    warn = server._staleness_warning()
    assert warn is not None
    assert "engine build" in warn                          # names the real cause
    assert "changed on disk" not in warn                   # the old false alarm is gone

    # Same bogus signature, SAME build -> this really is a disk change, and must say so.
    meta.write_text(json.dumps({"signature": {"count": 99, "hash": "nope"},
                                "engine": "aaaaaaaaaaaa"}))
    warn = server._staleness_warning()
    assert "changed on disk" in warn


def test_health_reports_drift_not_false_disk_changed(tmp_path, monkeypatch):
    """The acceptance criterion lives in health(), not just the search-time warning."""
    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps({"indexed": 5, "indexed_at": 1.0,
                                "signature": {"count": 99, "hash": "nope"},
                                "engine": "bbbbbbbbbbbb"}))
    monkeypatch.setattr(server, "META_PATH", meta)
    monkeypatch.setattr(server, "_ENGINE_BUILD", "aaaaaaaaaaaa")
    monkeypatch.setattr(sd, "SKILL_DIRS", [tmp_path / "empty"])
    monkeypatch.setattr(sd, "PLUGIN_GLOB", str(tmp_path / "none" / "**" / "SKILL.md"))
    rep = server._health()
    # UNKNOWABLE across builds — must not be reported as a confirmed match (False).
    assert rep["stale"] is None
    assert rep["engine_build"] == {"running": "aaaaaaaaaaaa", "index_written_by": "bbbbbbbbbbbb"}
    joined = " ".join(str(i) for i in rep["issues"])
    assert "disk changed since last index" not in joined     # the false alarm is gone
    assert "restart" in joined                               # names the real remedy


# --- the running build is a FACT, published unconditionally ---------------
# Reporting `engine_build` only under drift makes it a drift FLAG, so the only way for a
# reader to learn which build a process runs is for something to already be wrong. doctor
# needs the build of a healthy process — it is the yardstick every live server is measured
# against — and it must not have to re-hash the engine itself to get it: a second copy of
# `_engine_build()`'s rule silently stops agreeing the day this one changes.

def test_health_always_reports_running_engine_build(tmp_path, monkeypatch):
    """No drift: `running` is still published, and `index_written_by` is None (not absent)."""
    meta = tmp_path / "meta.json"
    monkeypatch.setattr(server, "META_PATH", meta)
    monkeypatch.setattr(server, "_ENGINE_BUILD", "aaaaaaaaaaaa")
    monkeypatch.setattr(sd, "SKILL_DIRS", [tmp_path / "empty"])
    monkeypatch.setattr(sd, "PLUGIN_GLOB", str(tmp_path / "none" / "**" / "SKILL.md"))
    meta.write_text(json.dumps({"indexed": 5, "indexed_at": 1.0,
                                "signature": server._disk_signature(),
                                "engine": "aaaaaaaaaaaa"}))
    rep = server._health()
    assert rep["engine_build"] == {"running": "aaaaaaaaaaaa", "index_written_by": None}
    assert rep["stale"] is False                  # same build, same disk -> a real answer


def test_health_reports_running_build_even_without_a_manifest(tmp_path, monkeypatch):
    """Which build we run does not depend on an index existing. A fresh machine (no
    manifest) must still answer it, or doctor's yardstick vanishes exactly when the
    post-install checks need it most."""
    monkeypatch.setattr(server, "META_PATH", tmp_path / "absent.json")
    monkeypatch.setattr(server, "_ENGINE_BUILD", "aaaaaaaaaaaa")
    monkeypatch.setattr(sd, "SKILL_DIRS", [tmp_path / "empty"])
    monkeypatch.setattr(sd, "PLUGIN_GLOB", str(tmp_path / "none" / "**" / "SKILL.md"))
    rep = server._health()
    assert rep["engine_build"] == {"running": "aaaaaaaaaaaa", "index_written_by": None}


# --- pid -> build registry (what a LIVE server is actually running) -------
# Timestamps cannot answer this. setup.sh re-copies the engine on EVERY run, so file
# mtime/ctime move even when the bytes are identical, and any check that dates a server
# against them flags every live process after a routine, no-op re-run. The server knows
# its own build; having it say so turns an inference into a lookup.

def test_server_records_its_own_build_for_live_lookup(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "SERVER_RECORDS", tmp_path / "servers")
    monkeypatch.setattr(server, "_ENGINE_BUILD", "aaaaaaaaaaaa")
    before = time.time()
    path = server._record_server_build()
    after = time.time()
    rec = json.loads(path.read_text())
    assert rec["pid"] == os.getpid()
    assert rec["build"] == "aaaaaaaaaaaa"
    assert path.name == f"{os.getpid()}.json"
    # started_at anchors the record to THIS process: a recycled pid must not inherit it.
    # Bracketed by the call, not merely "close to now" — the loose form cannot fail.
    assert before <= rec["started_at"] <= after
    assert not list((tmp_path / "servers").glob("*.tmp")), "left a temp file behind"


def test_cli_paths_write_no_server_record(tmp_path, monkeypatch):
    """Only the long-lived server publishes a record. A CLI run dies immediately, so its
    record would be a lie the moment it lands — a dead pid claiming to run a build."""
    records = tmp_path / "servers"
    monkeypatch.setattr(server, "SERVER_RECORDS", records)
    monkeypatch.setattr(server, "_health", lambda: {"status": "ok"})
    monkeypatch.setattr(server.sys, "argv", ["skill-search", "--health"])
    with pytest.raises(SystemExit):
        server.main()
    assert not records.exists() or not list(records.glob("*.json"))


def test_server_build_record_never_raises(tmp_path, monkeypatch):
    """Best-effort by contract. This runs on the server's startup path, where an
    unwritable cache dir must cost a diagnostic, never the server."""
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory")
    monkeypatch.setattr(server, "SERVER_RECORDS", blocker / "servers")
    assert server._record_server_build() is None


# --- scope-bounded pruning (multi-session shared collection) --------------
# All sessions share one Qdrant collection. A reindex must only delete points in
# scopes it can actually see, or session A silently deletes session B's project
# skills and the two flip-flop the index forever.

def test_prunable_skips_foreign_project_scope():
    existing = {
        "mine":    ("h1", "project:/my/proj/.claude/skills"),
        "theirs":  ("h2", "project:/their/proj/.claude/skills"),
        "personal": ("h3", "personal"),
    }
    desired = {}                       # nothing on disk -> everything "gone"
    visible = {"personal", "plugin", "project:/my/proj/.claude/skills"}

    prunable = server._prunable(existing, desired, visible)
    assert "mine" in prunable          # mine, visible, gone -> delete
    assert "personal" in prunable
    assert "theirs" not in prunable    # NOT mine -> never touch


def test_prunable_keeps_points_still_on_disk():
    existing = {"a": ("h1", "personal")}
    desired = {"a": ("txt", "h1", {})}
    assert server._prunable(existing, desired, {"personal"}) == []


def test_prunable_treats_legacy_scopeless_points_as_prunable():
    """Points written before scope tagging carry no scope. They must remain
    prunable, else they linger forever and never get re-embedded with a scope."""
    existing = {"old": ("h1", None)}
    assert server._prunable(existing, {}, {"personal"}) == ["old"]


def test_scope_change_forces_reembed():
    """A point whose scope changed must count as changed even if its text didn't,
    otherwise the one-time migration to scoped payloads never happens."""
    assert server._point_changed(("h1", "personal"), "h1", "project:/x") is True
    assert server._point_changed(("h1", "personal"), "h1", "personal") is False
    assert server._point_changed(("h1", "personal"), "h2", "personal") is True
    assert server._point_changed(None, "h1", "personal") is True


# --- end-to-end (loads the embedder; opt-in) -----------------------------

@pytest.mark.integration
def test_end_to_end_build_search_incremental():
    """`embedded` counts POINTS, `indexed` counts SKILLS — they are equal only in the
    upstream one-vector-per-skill shape. This deployment layers MAX-pool trigger points
    on top of each base vector (ADR-0012/0016/0026), so embedded legitimately runs many
    times higher: measured 6,092 points for 416 skills. The original `==` therefore failed
    on every real run here while passing with the layers off, which made a green suite
    depend on env rather than on correctness. Assert the invariant that holds either way."""
    stats = server.build_index(force=True)
    assert stats["indexed"] > 0
    assert stats["embedded"] >= stats["indexed"]

    hits = json.loads(server.search_skills("debug a failing test"))["results"]
    assert len(hits) > 0
    assert all("name" in h and "score" in h for h in hits)

    again = server.build_index()                         # nothing changed
    # `embedded == 0` IS the incremental guarantee. `skipped` counts points, not skills,
    # so it cannot equal `indexed` under the trigger layer (measured 6,096 vs 417) — and
    # pinning it to the earlier count would also break on any skill added mid-test.
    assert again["embedded"] == 0
    assert again["skipped"] >= stats["indexed"]
