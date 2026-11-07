"""Embedder provenance tests (ADR-0098).

The defect these exist for: the engine's only embedder guard was a DIMENSION check, so
swapping to a different embedder that also produced N floats left every stored vector
built by the old embedder while queries embedded on the new one. Retrieval kept working
and health stayed green — health probes the query backend, not stored provenance — so the
only symptom was a quiet loss of ranking precision.

Each test here fails against the unpatched engine.
"""

import pytest

from skill_search import server


# --- the token -------------------------------------------------------------

def test_identity_is_stable_for_the_same_embedder():
    a = server.embedder_identity("ollama", "embeddinggemma-2:270m", "http://h:11434", 768)
    b = server.embedder_identity("ollama", "embeddinggemma-2:270m", "http://h:11434", 768)
    assert a == b
    assert len(a) == 12


@pytest.mark.parametrize("field_change", [
    ("fastembed", "embeddinggemma-2:270m", "http://h:11434", 768),   # backend
    ("ollama", "other-model", "http://h:11434", 768),                # model
    ("ollama", "embeddinggemma-2:270m", "http://other:11434", 768),  # endpoint
    ("ollama", "embeddinggemma-2:270m", "http://h:11434", 1024),     # dimension
])
def test_identity_changes_for_every_field(field_change):
    base = server.embedder_identity("ollama", "embeddinggemma-2:270m", "http://h:11434", 768)
    assert server.embedder_identity(*field_change) != base


def test_identity_normalizes_cosmetic_endpoint_difference():
    """The same host written two ways is the same embedder. Without normalisation a
    trailing slash would trigger a full re-embed of 47k points for nothing."""
    a = server.embedder_identity("ollama", "m", "http://h:11434/", 768)
    b = server.embedder_identity("ollama", "m", "HTTP://H:11434", 768)
    assert a == b


# --- the changed-detection arm (the whole fix) -----------------------------

def test_point_unchanged_when_text_scope_and_provenance_all_match():
    stored = ("hash", "personal", "aaaaaaaaaaaa")
    assert server._point_changed(stored, "hash", "personal", "aaaaaaaaaaaa") is False


def test_point_changed_when_only_the_embedder_differs():
    """The exact 2026-11-07 case: same text, same scope, different embedder."""
    stored = ("hash", "personal", "aaaaaaaaaaaa")
    assert server._point_changed(stored, "hash", "personal", "bbbbbbbbbbbb") is True


def test_legacy_point_without_a_stamp_is_changed_once():
    """Points written before this field existed carry None, so the first reindex after
    the upgrade migrates the whole index exactly once."""
    stored = ("hash", "personal", None)
    assert server._point_changed(stored, "hash", "personal", "aaaaaaaaaaaa") is True


def test_point_changed_keeps_its_existing_arms():
    """The text and scope arms must not regress while adding the third."""
    assert server._point_changed(("other", "personal", "a"), "hash", "personal", "a") is True
    assert server._point_changed(("hash", "other-scope", "a"), "hash", "personal", "a") is True
    assert server._point_changed(None, "hash", "personal", "a") is True


# --- the manifest ----------------------------------------------------------

def test_manifest_records_endpoint_and_provenance(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "META_PATH", tmp_path / "meta.json")
    server._write_manifest(3)
    import json
    meta = json.loads((tmp_path / "meta.json").read_text())
    assert meta["endpoint"] == server.EMBED_ENDPOINT
    assert meta["provenance"] == server.current_embed_identity()


# --- health reports it -----------------------------------------------------

def test_health_reports_provenance_counts():
    """Health must ANSWER the provenance question, not just reachability. Against a fresh
    test collection every point is stamped by this process, so nothing is stale; the keys
    existing at all is what proves the check ran."""
    report = server._health()
    prov = report.get("embedder_provenance")
    assert prov is not None, "health stopped reporting embedder_provenance"
    assert prov.get("current") == server.current_embed_identity()
    if "error" not in prov:
        assert prov["stale_points"] == 0
        assert prov["ok"] is True
