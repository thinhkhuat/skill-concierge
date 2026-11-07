---
title: "A test suite pinned the embedder backend but not its model, so it failed only in the operator's shell"
author: Thinh
date: 2026-11-07
branch: main
id: l-74ae7f02
scope: repo
status: active
src: agent
touches:
  - vendor/skill-search/VENDORED.md
  - vendor/skill-search/skill_search/server.py
  - vendor/skill-search/tests/conftest.py
  - vendor/skill-search/tests/test_indexing.py
  - tests/conftest.py
---

## Decided
The vendored engine's test suite pins `SKILL_EMBED_BACKEND=fastembed` in
`tests/conftest.py` but left `SKILL_EMBED_MODEL` to whatever the shell carried.
A shell that sourced `~/.config/harness-env.sh` exports
`SKILL_EMBED_MODEL=embeddinggemma-2:270m` machine-wide, so `server.py` resolved
fastembed + an ollama-only model id and died with "Model embeddinggemma-2:270m is
not supported in TextEmbedding". Three tests failed — 2 in `test_query_embed.py`
plus the end-to-end indexing test — for every CLI run, while CI (no harness-env)
stayed green.

Fix: after pinning the backend, `conftest.py` now pops `SKILL_EMBED_MODEL`,
`SKILL_OLLAMA_URL` and `SKILL_EMBED_TOKEN` when the backend is fastembed.

## Tried and ruled out
- **Reading the three failures as a regression from the provenance change I was
  making.** Ruled out by running the same tests under
  `env -u SKILL_EMBED_MODEL -u SKILL_OLLAMA_URL -u SKILL_EMBED_TOKEN`: all 7
  passed untouched. The leak was pre-existing and mine was a separate break.
- **`os.environ.setdefault("SKILL_EMBED_MODEL", ...)`.** Would not have helped —
  the ambient variable is already set, so setdefault is a no-op. Only removal
  works.
- **Fixing it in `server.py` by ignoring the model when fastembed is chosen.** That
  would silently discard a deliberate operator override, and it is the test
  harness's job to be hermetic.

## Watch out
- **A suite that is green in CI can be red in the operator's own shell.** Any
  test-visible env var that `harness-env.sh` exports is a candidate. When a test
  fails locally but passed before, check `env | grep SKILL_` before reading the
  failure as a code regression.
- **`conftest.py` runs before `server` is imported, on purpose.** The env pinning
  only works because nothing imports the engine earlier; a test module that
  imports `skill_search` at collection time ahead of conftest would capture the
  ambient values again.
- The signature change itself (a stored-point tuple growing from 2 to 3 elements)
  broke 3 call sites in `tests/test_indexing.py`. That one IS obvious from the
  diff and needs no note.

In the code:
- `vendor/skill-search/tests/conftest.py` — the backend/model pinning block
- `SKILL_EMBED_BACKEND`, `SKILL_EMBED_MODEL`, `SKILL_OLLAMA_URL`, `SKILL_EMBED_TOKEN`
- reproduction: run pytest from a shell that has sourced `~/.config/harness-env.sh`
- verification: `env -u SKILL_EMBED_MODEL -u SKILL_OLLAMA_URL -u SKILL_EMBED_TOKEN pytest tests/test_query_embed.py`
  -> 7 passed without the conftest fix; full suite 326 passed with it
