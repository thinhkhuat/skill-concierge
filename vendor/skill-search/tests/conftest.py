"""Shared test setup.

Pins skill-search to an isolated configuration BEFORE `server` is imported
(importing it constructs the store client): an EPHEMERAL index owner
(`skill_search.index_owner`, started here on free ports with a temp SQLite file and
no model) as the store — never the live 6333; `SKILL_TEST_QDRANT_URL` points the
suite at an already-running store instead — plus a per-run scratch collection
dropped at exit, a temp manifest, and a fixed vector size so unit tests never
download a model. The one integration test that actually embeds is marked
`integration` and can be deselected.
"""

import os
import atexit
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="skillsearch-test-")
atexit.register(lambda: shutil.rmtree(_TMP, ignore_errors=True))
_SRC = Path(__file__).resolve().parents[1]   # vendor/skill-search: test the source, not the venv copy
sys.path.insert(0, str(_SRC))   # in-process imports too: the venv carries an installed skill_search


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class OwnerProc:
    """An index owner subprocess on free ports with its own SQLite file, log and stamp."""

    def __init__(self, db, qport=None, eport=None, env=None):
        self.db = Path(db)
        self.qport, self.eport = qport or free_port(), eport or free_port()
        self.url = f"http://127.0.0.1:{self.qport}"
        self.log = Path(f"{db}.log")
        self.stamp = Path(f"{db}.stamp")
        self.env = dict(os.environ, PYTHONPATH=os.pathsep.join(
                            [str(_SRC)] + [p for p in [os.environ.get("PYTHONPATH")] if p]),
                        SKILL_INDEX_DB=str(db), SKILL_OWNER_QUERY_PORT=str(self.qport),
                        SKILL_OWNER_EMBED_PORT=str(self.eport), SKILL_OWNER_NO_MODEL="1",
                        SKILL_OWNER_LOG=str(self.log), SKILL_OWNER_STAMP=str(self.stamp))
        self.env.update(env or {})
        self.proc = subprocess.Popen([sys.executable, "-m", "skill_search.index_owner"],
                                     env=self.env, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)

    def wait_ready(self, timeout=20.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.proc.poll() is not None:
                raise RuntimeError(f"index owner exited {self.proc.returncode}: {self.read_log()}")
            try:
                with urllib.request.urlopen(self.url + "/", timeout=0.5) as r:
                    if r.status == 200:
                        return self
            except OSError:
                pass
            time.sleep(0.05)
        raise RuntimeError(f"index owner not ready in {timeout}s: {self.read_log()}")

    def read_log(self) -> str:
        try:
            return self.log.read_text(encoding="utf-8")
        except OSError:
            return ""

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()


# Forced, not setdefault: a shell carrying the live SKILL_QDRANT_URL must never
# point the suite (which force-rebuilds its collection) at the live store.
if os.environ.get("SKILL_TEST_QDRANT_URL"):
    os.environ["SKILL_QDRANT_URL"] = os.environ["SKILL_TEST_QDRANT_URL"]
else:
    _OWNER = OwnerProc(os.path.join(_TMP, "index.sqlite")).wait_ready()
    atexit.register(_OWNER.stop)   # registered after rmtree, so it runs first (LIFO)
    os.environ["SKILL_QDRANT_URL"] = _OWNER.url
os.environ["SKILL_COLLECTION"] = f"skillsearch_test_{os.getpid()}"
# setdefault so an explicit env (e.g. CI choosing the Ollama tier) still wins.
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
# Pin the utterance corpus (and so the operator-curated triggers file beside it) to a
# nonexistent temp path: otherwise the operator's live ~/.claude/skill-concierge/ corpus
# leaks into every trigger-phrase test.
os.environ.setdefault("SKILL_TRIGGERS", os.path.join(_TMP, "no-triggers.json"))

# Imported ONLY AFTER the env pinning above: skills_discovery reads several
# seams (SKILL_CONCIERGE_CATALOG_ROOTS included) at MODULE IMPORT time, so an
# import placed before the setdefaults would capture the operator's live
# config — exactly the leak this file exists to prevent.
import pytest

from skill_search import skills_discovery


@pytest.fixture
def owner_factory(tmp_path):
    """Start index owners (not yet waited on) with a temp SQLite file each; all stopped
    at teardown."""
    procs = []

    def make(db=None, **kw):
        p = OwnerProc(db or tmp_path / f"owner{len(procs)}.sqlite", **kw)
        procs.append(p)
        return p
    yield make
    for p in procs:
        p.stop()


@pytest.fixture(scope="session", autouse=True)
def _drop_test_collections():
    yield
    from skill_search import server
    for c in (server.COLLECTION, "curated_reload_test"):
        try:
            server._qdrant.delete_collection(c)
        except Exception:
            pass


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
    # Claude account-synced skills (~/.claude/skills/synced/<bucket>/<name>/SKILL.md).
    monkeypatch.setattr(skills_discovery, "SYNCED_ROOT", tmp_path / "claude-synced", raising=False)
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
