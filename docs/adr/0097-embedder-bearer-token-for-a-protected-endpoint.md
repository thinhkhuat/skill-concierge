# 0097 — The embedder can authenticate: a bearer token for a protected endpoint

- Status: accepted
- Date: 2026-11-07
- Deciders: Thinh: "go with #2 now and documentate the change thoroughly" — choosing the
  code change (auth support) over the zero-code alternative of pointing the embedder at an
  unauthenticated tailnet address.
- Relates to: ADR-0026 (the `ENGINE_ENV_KEYS` forwarding class), ADR-0070 (the local index
  owner). Implementation: `vendor/skill-search/skill_search/server.py`
  (`EMBED_TOKEN`, `_embed_headers()`), `scripts/engine_env.py`, `VENDORED.md`,
  `vendor/skill-search/tests/test_embed_token.py`.

## Context

The concierge embeds skills and queries through an Ollama-compatible endpoint named by
`SKILL_OLLAMA_URL`, which defaults to `http://localhost:11434`. The engine had exactly one
way to call it: `POST /api/embed` for batches and `POST /api/embeddings` for single items,
**with no authentication of any kind**.

On 2026-11-07 a new embedding host became available: Ollama running on the GPU box, published
at `https://rtx.thinhkhuat.com` by a Caddy reverse proxy that enforces
`Authorization: Bearer <key>` and answers `401` to anything else. The endpoint serves both
shapes: the Ollama-native `/api/embed` and the OpenAI-compatible `/v1/embeddings`, 768
dimensions, `embeddinggemma-2:270m`.

Measured before the change: an unauthenticated `POST https://rtx.thinhkhuat.com/api/embed`
returns `401`. So `SKILL_OLLAMA_URL=https://rtx.thinhkhuat.com` could not work — the engine
had no way to present a credential. The gateway at `api.thinhkhuat.com` was not an alternative
either: it speaks only the OpenAI shape and does not expose `/api/embed` at all (`401`), so
it cannot serve a client that only knows the Ollama routes.

## Decision

Read an optional token from `SKILL_EMBED_TOKEN` and send it as a bearer header on **both**
Ollama paths, through one `_embed_headers()` helper.

An empty or unset token sends **no** `Authorization` header at all — not an empty one. This
keeps a bare local Ollama byte-identical to its previous behaviour, so the default path
carries no new risk and no configuration.

## Why this shape

- **One helper, both paths.** The batch path is the one that normally runs, but the
  single-item fallback fires whenever the batch call fails. Authenticating only the batch path
  would produce a puzzling partial failure: a reindex that degrades to N sequential
  unauthenticated calls, each 401.
- **A config key, not a code special case.** The endpoint is data; the credential is data. A
  flag that hardcoded "if the URL looks remote, add a header" would encode a guess about
  someone's network.
- **Header-present-only-when-set.** Sending `Authorization: Bearer ` with an empty value would
  be rejected by some proxies and accepted by others, producing an environment-dependent bug.
  Absent is unambiguous.
- **The key joins `ENGINE_ENV_KEYS`.** A reindex that authenticates while the query server does
  not (or the reverse) is the exact failure class ADR-0026 exists to prevent: a background
  reindex rebuilding the index at engine defaults and pruning what the server serves. A
  credential that shapes which endpoint answers is an engine setting by that rule.

## Alternatives rejected

- **Point at the unauthenticated tailnet address instead.** `http://100.88.2.126:11434` works
  today with zero code. Rejected as the *primary* path because it sends embedding text in
  plaintext and only works from a machine on the tailnet; the HTTPS endpoint is the durable
  one. It remains a valid fallback, and this change does not prevent it.
- **Add an OpenAI-compatible backend to the engine.** The gateway and the rtx proxy both speak
  `/v1/embeddings`. Rejected as scope: a new backend is a far larger change than one header,
  and it buys nothing the native route does not already give, since the endpoint serves both
  shapes.
- **Bake the token into `.mcp.json`.** Rejected: that file is tracked in git, so the token
  would be committed. The key is read from the process environment, whose home is
  `~/.config/harness-env.sh`, and `.mcp.json` deliberately carries no secret.

## Consequences

- A protected embedding endpoint is now usable, with no new flag: set `SKILL_OLLAMA_URL`,
  `SKILL_EMBED_MODEL`, and `SKILL_EMBED_TOKEN`.
- The default is unchanged. Existing deployments that embed through a bare local Ollama need
  to do nothing and send no header, verified by test.
- The token is a secret. It must not be written into `.mcp.json`, a plan, a report, or a
  commit; `doctor` and the tests never print it.
- Dimension safety: keeping `embeddinggemma-2:270m` when changing only the URL leaves 768
  dimensions untouched, so an existing collection stays valid and no reindex is forced. Changing
  the *model* would invalidate every stored vector — a different decision, with its own cost.
- This is a direct edit to vendored source, so it is recorded in `VENDORED.md` and must be
  re-applied on re-vendor.

## Verification

- `vendor/skill-search/tests/test_embed_token.py`: no token → no header (the default is
  preserved); token → `Bearer` on the batch path; token → `Bearer` on the single-item fallback;
  the key is present in `ENGINE_ENV_KEYS`.
- Live, against the real endpoint: `embed_batch` returned 2 vectors of 768 dims and
  `_ollama_embed_one` returned 1 vector of 768 dims through `https://rtx.thinhkhuat.com` with
  the token set. The same calls without the header return `401`, so the token is doing the work
  rather than the endpoint being open.
- `tests/test_engine_env.py`: every reindex builder still forwards every engine key.
