# Flywheel LLM providers

`scripts/flywheel_llm.py` talks to any OpenAI-compatible `/v1/chat/completions` endpoint.
Four env vars configure it (set them in `~/.claude/settings.json` `env`, the same durable
home as `SKILL_TRIGGERS`):

| Var | Default | Purpose |
|---|---|---|
| `FLYWHEEL_LLM_ENDPOINT` | `http://localhost:4310/v1/chat/completions` | full chat-completions URL |
| `FLYWHEEL_LLM_MODEL` | `gemma-4-e4b-it-qat-optiq` | model id sent in the request body |
| `FLYWHEEL_LLM_API_KEY` | unset | sent as `Authorization: Bearer <key>` when set |
| `FLYWHEEL_LLM_SCHEMA_MODE` | `json_schema` | `json_schema` \| `json_object` \| `off` |

No key, no network call happens unless a generator script (`llm_triggers.py`,
`llm_eval_gen.py`) or `flywheel_llm.ping()` is invoked — `--selftest` stays network-free.

## 1. LM-Studio (default, local)

LM-Studio grammar-constrains output to a strict JSON schema, so leave `SCHEMA_MODE` at its
default.

```
FLYWHEEL_LLM_ENDPOINT=http://localhost:4310/v1/chat/completions
FLYWHEEL_LLM_MODEL=gemma-4-e4b-it-qat-optiq
# FLYWHEEL_LLM_API_KEY unset
# FLYWHEEL_LLM_SCHEMA_MODE unset (defaults to json_schema)
```

Load the model with **thinking OFF** — reasoning tokens are incompatible with
`response_format` (empties the content) and exhaust the token budget on this task's prompt.

## 2. Ollama (local)

Ollama's `/v1` compat layer only honors `json_object`, not strict `json_schema`.

```
FLYWHEEL_LLM_ENDPOINT=http://localhost:11434/v1/chat/completions
FLYWHEEL_LLM_MODEL=<your-ollama-model>
FLYWHEEL_LLM_SCHEMA_MODE=json_object
# FLYWHEEL_LLM_API_KEY unset
```

## 3. OpenAI-compatible gateway (hosted)

Covers OpenAI, OpenRouter, Together, Groq, Anthropic-via-compat-proxy, self-hosted vLLM,
or any other gateway that speaks the OpenAI chat-completions shape.

```
FLYWHEEL_LLM_ENDPOINT=<gateway-base>/v1/chat/completions
FLYWHEEL_LLM_MODEL=<model-id-the-gateway-expects>
FLYWHEEL_LLM_API_KEY=<key>
# FLYWHEEL_LLM_SCHEMA_MODE: try json_schema first; fall back to json_object or off if the
# gateway rejects strict response_format
```

Generation is a paid call on a gateway (unlike the two local setups) — mind the per-run
skill count when running the `skill-concierge:flywheel` skill's generate mode.

## Preflight

`flywheel_llm.ping()` does a cheap `GET <base>/models` (base = endpoint minus
`/chat/completions`) and returns `(ok, detail)`. `scripts/doctor.py`'s flywheel check and the
`skill-concierge:flywheel` skill both call it before generating.
