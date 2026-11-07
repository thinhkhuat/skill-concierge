---
title: "A test that passes can still be testing nothing: check the stub was reached"
author: Thinh
date: 2026-11-07
branch: main
id: l-13488099
scope: repo
status: active
src: agent
touches:
  - vendor/skill-search/tests/test_embed_token.py
  - vendor/skill-search/tests/conftest.py
  - scripts/engine_env.py
---

## Decided
When a new test exercises an environment-selected code path, assert that the path actually ran before asserting what it did. In `vendor/skill-search/tests/test_embed_token.py` the embedder branch is chosen by `EMBED_BACKEND`, and `vendor/skill-search/tests/conftest.py` pins that to `fastembed` for the whole suite, so the new network-path test silently took the local branch and never touched the stub server. Fix was to pin the backend inside the new test's fixture, not to change the shared one.

## Tried and ruled out
- Reading the assertion failure as a bug in `embed_batch` / `_ollama_embed_batch` in `server.py`. Wrong: the recorded header key was absent because the request was never made.
- Changing the `conftest.py` default so the new test could run. Rejected: every other vendored test depends on that default, and one test's needs do not justify shifting the shared baseline.
- Accepting the passing run without checking which branch executed. Rejected: the first version was green on the paths it reached while proving nothing about the ones it did not.

## Watch out
A green test proves only the path it took. When a branch is selected by configuration, a test can be green and vacuous at the same time.

The tell was not the assertion text; it was that the stub handler recorded no request at all.

In the code:
- `vendor/skill-search/tests/test_embed_token.py` pins `server.EMBED_BACKEND` to `ollama` beside the stub URL
- `vendor/skill-search/tests/conftest.py` keeps its `SKILL_EMBED_BACKEND` default untouched
- four tests: feature off sends no Authorization header, feature on sends on `/api/embed`, feature on sends on the `/api/embeddings` fallback, and `SKILL_EMBED_TOKEN` is in `ENGINE_ENV_KEYS` in `scripts/engine_env.py`
