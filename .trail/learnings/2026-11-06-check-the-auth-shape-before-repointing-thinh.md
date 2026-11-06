---
title: Check the auth shape before repointing an embedder at a protected endpoint
author: Thinh
date: 2026-11-06
branch: main
id: l-54acb8ec
scope: repo
status: active
src: agent
touches:
  - vendor/skill-search/skill_search/server.py
  - scripts/engine_env.py
---

## Decided
Repointing the concierge's embedder at the new HTTPS rtx endpoint is a config-only change only if the URL needs no auth. It does need auth, so the choice is between the plaintext tailnet address (config only) and teaching the embedder to send a bearer header (code change). Recommended the tailnet address first: one reversible line, existing vector dimensions untouched because the model stays the same.

## Tried and ruled out
- Reading the embedder's endpoint from the docs or from history. Rejected: the running owner process carried the real values, and reading the live process exposed that the URL variable was never set at all — it was falling back to a code default.
- Assuming the model name and the URL can change together. Rejected: changing the model changes dimensions and invalidates every stored vector, forcing a full reindex. Changing only the URL keeps them valid.
- Copying the endpoint's auth header from the request that works. There isn't one — the embedder sends none, which is the whole blocker.

## Watch out
An endpoint that answers `curl` is not an endpoint your code can call. `curl` with a header proves the service; it says nothing about whether the caller sends that header.

Read the caller, not the endpoint, before declaring a switch trivial.

In the code:
- rtx-wsl/rtx: endpoint at https://rtx.thinhkhuat.com, bearer-gated, 401 without it
- skill-concierge vendor/skill-search/skill_search/server.py — embed batch posts to /api/embed with no Authorization header
- the skill-search MCP server block in the repo's .mcp.json sets the model and backend, never the URL
- scripts/engine_env.py forwards the URL key on reindex paths, so no code change is needed for the URL alone
