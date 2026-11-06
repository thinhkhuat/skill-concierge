# Journal — 2026-11-07 — An HTTPS embedding endpoint on rtx, and what blocks the concierge from using it

Session arc: gate LibreChat's Windows embeddings plumbing so an external endpoint survives, then stand up a working HTTPS embedding endpoint, then survey the concierge cutover. The third part is preparation only; nothing in the concierge changed.

## The problem the gate solved

LibreChat runs on rtx-wsl (WSL2 Ubuntu) with `rag_api` embedding through a Windows-side Ollama reached over a NAT route. Two Windows scripts keep that route alive:

- `ollama-serve.ps1` starts Ollama at logon, clearing a user-level `CUDA_VISIBLE_DEVICES` that would otherwise force CPU-only.
- `wsl-keepalive.ps1` starts that task, writes the current WSL-facing IP into `.win-ollama.env`, and force-recreates `rag_api` when the IP changes.

Both assumed the local Ollama was always the embedder. Any change pointing `rag_api` elsewhere would be reverted at the next logon or WSL restart, with no error.

The fix gates both on a single question. The first version asked *"is the provider called `ollama`?"* and shipped. The validator broke it: a config that keeps `EMBEDDINGS_PROVIDER=ollama` and only repoints `OLLAMA_BASE_URL` reads as ours, so the keepalive still clobbers it. The question was wrong — a name is not proof of ownership.

The shipped version asks *"does our file still own the URL?"* — compares the merged compose config's `OLLAMA_BASE_URL` against the one in `.win-ollama.env`, and answers `local` only when they match and the provider is empty or `ollama`. Only `external` makes the scripts stand down. Unanswerable (docker down, file moved, WSL not booted) preserves the old behaviour deliberately, so a transient failure never disables the fallback.

Verified in four cases plus a positive control. The one that matters: provider `ollama` with the URL injected into `environment:` → predicate says `external`, Ollama pid unchanged, `rag_api` untouched.

## The endpoint

Thinh wanted the embeddings to reach his gateway. The gateway rejects plain-http and bare-IP base URLs, so rtx needed a real HTTPS domain. He wrote the Caddy block himself:

```
rtx.thinhkhuat.com {
    @unauthed not header Authorization "Bearer $FLYWHEEL_API_KEY"
    respond @unauthed 401
    reverse_proxy http://192.168.2.126:11434
}
```

Measured after it went live:

| Check | Result |
|---|---|
| `https://rtx.thinhkhuat.com/api/version` without auth | `401` |
| Same with the key | `200`, Ollama `0.40.15` |
| `POST /v1/embeddings`, `embeddinggemma-2:270m`, dims 768 | `200`, 768 dims, model echoed |
| `POST /api/embed` native | `200`, 768 dims |

DNS resolves through `tnmk.tplinkdns.com` to `42.113.68.92`, Cloudflare-fronted. The VPS reaches rtx over Tailscale (`srv` = `100.88.2.126`); containers reach it too, bridge and host network alike.

The gateway, however, still cannot serve embeddings: its `rtx` provider entry has no credentials attached. `No credentials for provider: openai-compatible-chat-bd89920f-…` on the embeddings route, `No active credentials` on chat. That is a dashboard field, not a network or code problem.

## The concierge survey

Asked to prepare for replacing the concierge's local Ollama with this endpoint. Surveyed, did not change.

Read from the live owner process rather than the docs, which is the only way to know what is actually running:

```
SKILL_EMBED_BACKEND=ollama
SKILL_EMBED_MODEL=embeddinggemma-2:270m
SKILL_QDRANT_URL=http://localhost:6333
SKILL_OLLAMA_URL   (unset → http://localhost:11434)
```

So the concierge embeds through this Mac's own Ollama — same model, same 768 dims, same everything except the host.

The seam is two lines in `vendor/skill-search/skill_search/server.py`:

```python
EMBED_MODEL = os.environ.get("SKILL_EMBED_MODEL") or _DEFAULT_MODEL.get(EMBED_BACKEND, "embeddinggemma")
OLLAMA_URL  = os.environ.get("SKILL_OLLAMA_URL", "http://localhost:11434")
```

Config lives in `.mcp.json` under `skill-search.env`, which sets the first three keys but not `SKILL_OLLAMA_URL`. `scripts/engine_env.py` already forwards it through `ENGINE_ENV_KEYS`, so reindex paths pick it up without a code change.

Because the model stays the same, dimensions stay 768 and the existing Qdrant vectors stay valid. Only the URL changes, which means no reindex and no purge — provided the model name is not touched.

### The blocker

`_ollama_embed_batch` posts to `f"{OLLAMA_URL}/api/embed"` with no `Authorization` header. That exact unauthenticated call to the Caddy endpoint returns `401`. So `SKILL_OLLAMA_URL=https://rtx.thinhkhuat.com` fails as things stand.

Two paths:

1. **Point at Tailscale** (`http://100.88.2.126:11434`) — one config line, answers `200` without auth, plaintext on the tailnet. Reversible, no release.
2. **Send a bearer header from the embedder** — keeps HTTPS and the 401 gate, but touches vendored code and needs the version-bump and install dance.

Recommended 1 first. It solves the stated problem with one line; take 2 only if the concierge must run off-tailnet.

## What I did not do
- Did not change any concierge file, config or Qdrant collection.
- Did not touch the gateway, its credential store, or the VPS Caddy config — Thinh owns those.
- Did not switch LibreChat's `rag_api` to the new endpoint. It still embeds through the Windows Ollama, and the gate correctly reports `local`.
- Could not reproduce the `200` Thinh once pasted from `api.thinhkhuat.com/v1/embeddings` with an empty model. Four variants all returned `400`. Left unresolved rather than explained away.

## What a reader should take away

Ask what evidence would catch the wrong answer. Here one question did — *what makes this endpoint mine to overwrite?* — and the provider name never answered it. The first gate passed every test I wrote for it, because I wrote tests for the design I had chosen. The independent validator, given the code and no stake in it, found the hole in one pass.

A related note: the trigger for the whole change was a request to make infrastructure ready for a switch that had not happened yet. Preparing for a future state without breaking the present one is its own discipline — the gate preserves current behaviour on every uncertain path, so the preparation cannot itself become an outage.
