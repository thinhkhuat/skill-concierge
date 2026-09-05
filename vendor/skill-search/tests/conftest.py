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
def _isolate_harness_roots(tmp_path, monkeypatch):
    # ADR-0033/0038 multi-harness: discovery also walks ~/.codex/** and ~/.omp/**.
    # Tests that patch SKILL_DIRS/PLUGIN_GLOB but not the Codex/OMP globals would
    # otherwise pull the machine's REAL ~/.codex/plugins/cache/** and
    # ~/.omp/agent/managed-skills/ + ~/.omp/plugins/cache/plugins/** skills into
    # their fixtures (312 codex skills observed on the dev machine, plus the OMP
    # managed-skills auto-learn corpus). Pin every harness seam to a temp path so
    # each test opts INTO harness coverage explicitly.
    monkeypatch.setattr(skills_discovery, "CODEX_PERSONAL_ROOT", tmp_path / "codex-personal")
    monkeypatch.setattr(skills_discovery, "CODEX_PROJECT_ROOT", tmp_path / "codex-project")
    monkeypatch.setattr(skills_discovery, "CODEX_PLUGIN_GLOB",
                        str(tmp_path / "codex-cache" / "none" / "**" / "SKILL.md"))
    monkeypatch.setattr(skills_discovery, "OMP_PERSONAL_ROOT", tmp_path / "omp-personal")
    monkeypatch.setattr(skills_discovery, "OMP_PROJECT_ROOT", tmp_path / "omp-project")
    monkeypatch.setattr(skills_discovery, "OMP_MANAGED_ROOT", tmp_path / "omp-managed")
    monkeypatch.setattr(skills_discovery, "OMP_PLUGIN_GLOB",
                        str(tmp_path / "omp-cache" / "none" / "**" / "SKILL.md"))
    # ADR-0042/0050/0051 harness seams (ZCode/DSH/Cline) read the LIVE machine when
    # unpinned — ~/.zcode/cli/plugins/cache/** is registry-enumerated and bypasses
    # PLUGIN_GLOB entirely, so 12 discovery/indexing tests pulled real ZCode skills
    # into their fixtures (2026-09-05 baseline: 12 failed). Pin every remaining
    # harness seam; tests that want a seam monkeypatch it explicitly.
    monkeypatch.setattr(skills_discovery, "ZCODE_PERSONAL_ROOT", tmp_path / "zcode-personal")
    monkeypatch.setattr(skills_discovery, "ZCODE_PROJECT_ROOT", tmp_path / "zcode-project")
    monkeypatch.setattr(skills_discovery, "ZCODE_AGENTS_PROJECT_ROOT", tmp_path / "agents-project")
    monkeypatch.setattr(skills_discovery, "ZCODE_PLUGIN_CACHE", tmp_path / "zcode-cache")
    monkeypatch.setattr(skills_discovery, "ZCODE_INSTALLED_PLUGINS_JSON",
                        tmp_path / "zcode-cache" / "installed_plugins.json")
    monkeypatch.setattr(skills_discovery, "ZCODE_CONFIG_JSON", tmp_path / "zcode-cache" / "config.json")
    monkeypatch.setattr(skills_discovery, "DSH_PERSONAL_ROOT", tmp_path / "dsh-personal")
    monkeypatch.setattr(skills_discovery, "DSH_PROJECT_ROOT", tmp_path / "dsh-project")
    monkeypatch.setattr(skills_discovery, "CLINE_PERSONAL_ROOT", tmp_path / "cline-personal")
    monkeypatch.setattr(skills_discovery, "CLINE_PROJECT_ROOT", tmp_path / "cline-project")
    # ADR-0052 enablement seams: root-relative plugin enumeration reads the Claude
    # manifests + layer files directly (no PLUGIN_GLOB funnel), so unpinned tests
    # would pull the operator's real installed plugins and project layer files into
    # discovery. Tests that want them monkeypatch these explicitly.
    monkeypatch.setattr(skills_discovery, "INSTALLED_PLUGINS_JSON",
                        tmp_path / "claude-plugins" / "installed_plugins.json")
    monkeypatch.setattr(skills_discovery, "CLAUDE_SETTINGS_JSON",
                        tmp_path / "claude-settings" / "settings.json")
    monkeypatch.setattr(skills_discovery, "CLAUDE_PROJECTS_FILE",
                        tmp_path / "claude-settings" / ".claude.json")
