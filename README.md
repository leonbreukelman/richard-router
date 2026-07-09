# richard-router

`richard-router` is a small OpenAI-compatible model router for Hermes Agent.
Hermes sees one custom provider and one virtual model (`coding`). The router
maps that virtual model to fixed upstream model endpoints and fails over when
the primary provider is unavailable.

Default example:

```text
Hermes -> richard-router model "coding"
       -> NVIDIA z-ai/glm-5.2 primary
       -> OpenRouter z-ai/glm-5.2 fallback
```

Hermes does not need to know about NVIDIA, OpenRouter, or real model IDs.

## What it exposes

```text
GET  /health
GET  /v1/models
POST /v1/chat/completions
```

`GET /v1/models` returns only your configured virtual models, for example:

```json
{"object":"list","data":[{"id":"coding","object":"model","owned_by":"richard-router"}]}
```

## Quick start

```bash
git clone https://github.com/leonbreukelman/richard-router.git
cd richard-router
cp .env.example .env
cp config/router.example.yaml config/router.yaml
# edit .env and add NVIDIA_API_KEY + OPENROUTER_API_KEY
uv sync
uv run dotenv -f .env run -- uvicorn richard_router.main:app --host 127.0.0.1 --port 4000
```

Smoke check:

```bash
curl http://127.0.0.1:4000/v1/models
```

## Hermes profile setup

Create a disposable Hermes profile so this does not affect your main profile:

```bash
hermes profile create routertest --clone
hermes -p routertest config edit
```

Add:

```yaml
custom_providers:
  - name: richard-router
    base_url: http://127.0.0.1:4000/v1
    api_mode: chat_completions
    discover_models: false
    models:
      coding:
        context_length: 128000

model:
  provider: custom:richard-router
  default: coding
```

Test:

```bash
hermes -p routertest chat -Q -q 'Reply exactly: ROUTER-OK'
```

## Failover policy

By default the router retries the next upstream on:

- timeout
- connection error
- HTTP 408, 409, 429, 500, 502, 503, 504

It does not fail over on normal caller/configuration errors like:

- 400 bad request
- 401 bad API key
- 403 forbidden
- malformed request/tool schema

That keeps real configuration problems visible instead of hiding them behind a
fallback.

The circuit breaker is enabled by default. Retryable upstream failures open a
provider/model circuit after five consecutive failures, skip it for 30 seconds,
then allow one half-open probe. A successful probe closes the circuit again.
Caller/configuration errors such as 400/401/403/422 do not open the breaker.

## Streaming

Streaming requests are passed through. Failover can happen before the upstream
stream is accepted. Once an upstream starts returning a stream, the router does
not switch mid-answer because that would corrupt the response. The router rewrites
SSE `model` fields back to the virtual model name before forwarding chunks.

## Diagnostics

By default, `richard-router` does not return the real upstream provider/model to
the client. For local smoke tests only, set:

```yaml
observability:
  expose_upstream_header: true
```

That adds `x-richard-router-upstream` to responses so you can prove which
upstream handled a request. Leave it false for normal Hermes use.

## Development

```bash
uv sync --all-groups
uv run pytest -v
uv run ruff check .
```

Run a bounded live smoke using your local environment keys:

```bash
uv run dotenv -f ~/.hermes/.env run -- python scripts/live_smoke.py --config config/router.example.yaml
```

The live smoke sends tiny prompts and prints only provider/model/upstream status,
not secrets.
