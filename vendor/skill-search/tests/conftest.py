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
