"""The Docker embed-shim image is retired (ADR-0070); the build files are archived
outside the repo, not carried here as dead weight.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_no_dockerfile_or_dockerignore_in_repo():
    assert not (ROOT / "Dockerfile").exists()
    assert not (ROOT / ".dockerignore").exists()


def test_embed_server_docstring_does_not_point_at_a_missing_dockerfile():
    text = (ROOT / "scripts" / "embed_server.py").read_text()
    assert "Dockerfile" not in text
