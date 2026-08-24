"""Shared test setup.

Pins skill-search to an isolated, offline-by-default configuration BEFORE
`server` is imported (importing it constructs the Qdrant client): embedded
Qdrant in a temp dir, a temp manifest, and a fixed vector size so unit tests
never touch the network or download a model. The one integration test that
actually embeds is marked `integration` and can be deselected.
"""

import os
import atexit
import shutil
import tempfile

_TMP = tempfile.mkdtemp(prefix="skillsearch-test-")
atexit.register(lambda: shutil.rmtree(_TMP, ignore_errors=True))

# setdefault so an explicit env (e.g. CI choosing the Ollama tier) still wins.
os.environ.setdefault("SKILL_QDRANT_PATH", os.path.join(_TMP, "qdrant"))
os.environ.setdefault("SKILL_META_PATH", os.path.join(_TMP, "meta.json"))
os.environ.setdefault("SKILL_EMBED_BACKEND", "fastembed")
os.environ.setdefault("SKILL_VECTOR_SIZE", "384")  # avoids an embed probe in unit tests
# Pin the external-catalog config to a NONEXISTENT path (ADR-0031). Without this,
# every test calling discover_skills()/_disk_signature() reads the operator's LIVE
# ~/.claude/skill-concierge/catalog-roots.json and pulls in real external skills —
# non-hermetic, and it breaks the count-exact discovery/indexing tests on any machine
# that has a catalog registered. The 6 catalog tests monkeypatch CATALOG_ROOTS_PATH
# themselves, so this only neutralizes the ambient config for everyone else.
os.environ.setdefault("SKILL_CONCIERGE_CATALOG_ROOTS", os.path.join(_TMP, "no-catalogs.json"))

# Imported ONLY AFTER the env pinning above: skills_discovery reads several
# seams (SKILL_CONCIERGE_CATALOG_ROOTS included) at MODULE IMPORT time, so an
# import placed before the setdefaults would capture the operator's live
# config — exactly the leak this file exists to prevent.
import pytest

from skill_search import skills_discovery


@pytest.fixture(autouse=True)
def _isolate_codex_roots(tmp_path, monkeypatch):
    # ADR-0033 dual-harness: discovery also walks ~/.codex/**. Tests that patch
    # SKILL_DIRS/PLUGIN_GLOB but not the Codex globals would otherwise pull the
    # machine's REAL ~/.codex/plugins/cache/** skills into their fixtures
    # (312 observed on the dev machine). Pin every Codex seam to a temp path so
    # each test opts INTO Codex coverage explicitly.
    monkeypatch.setattr(skills_discovery, "CODEX_PERSONAL_ROOT", tmp_path / "codex-personal")
    monkeypatch.setattr(skills_discovery, "CODEX_PROJECT_ROOT", tmp_path / "codex-project")
    monkeypatch.setattr(skills_discovery, "CODEX_PLUGIN_GLOB",
                        str(tmp_path / "codex-cache" / "none" / "**" / "SKILL.md"))
