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

Transport retries (when enabled):

- timeout
- connection error

### `failover.retry_on_status` — three states

| Config | Meaning |
|--------|---------|
| **Field omitted** | Default status set (408, 409, 429, 500, 502, 503, 504) **plus** blanket 5xx (e.g. 599 still fails over). |
| **Explicit list** | **Only** listed statuses are retryable. No blanket 5xx inheritance. |
| **Explicit `[]`** | No HTTP statuses are retryable (timeouts/connection errors still follow their flags). |

**Compatibility note:** Existing configs that set an explicit list no longer treat
unlisted 5xx (505, 599, …) as retryable. To keep historical “any 5xx fails over”
behavior, **omit** `retry_on_status` entirely. Copying `config/router.example.yaml`
as-is uses the explicit list (strict-list semantics).

It does not fail over on normal caller/configuration errors like:

- 400 bad request
- 401 bad API key
- 403 forbidden
- malformed request/tool schema

That keeps real configuration problems visible instead of hiding them behind a
fallback.

The circuit breaker is enabled by default. Retryable upstream failures open a
provider/model circuit after five consecutive failures, skip it for 30 seconds,
then allow one half-open probe. Only a successful 2xx probe closes the
circuit; a non-2xx probe (retryable failure or non-retryable 4xx) leaves the
breaker open and re-arms the cooldown, so the next request continues to skip
the primary. Caller/configuration errors such as 400/401/403/422 do not open
the breaker while it is closed. See
`docs/decisions/2026-07-18-half-open-requires-2xx.md`.

## Load balancing

Upstreams can be grouped into **priority tiers** and distributed by **weight**
within each tier. This replaces the simple list-order fallback with a true
load-balanced pool.

### Priority tiers

Each upstream has a `priority` field (integer, default `1`, lower = higher
priority). Upstreams are grouped by priority into tiers, and tiers are tried in
ascending order. Only after every upstream in tier 1 has been exhausted does
the router try tier 2.

```yaml
upstreams:
  # Tier 1 — tried first
  - name: primary
    ...
    priority: 1

  # Tier 2 — only tried if all tier-1 upstreams are down
  - name: backup
    ...
    priority: 2
```

### Weighted distribution

Within a tier, traffic is distributed by `weight` (integer, default `100`,
minimum `1`). A weight of 70 gets 70% of requests, a weight of 30 gets 30%.

```yaml
upstreams:
  - name: nvidia-glm
    priority: 1
    weight: 70    # 70% of requests

  - name: openrouter-glm
    priority: 1
    weight: 30    # 30% of requests
```

If all upstreams in a tier have the same weight (including the default of 100),
the router falls back to deterministic list-order iteration — the same behavior
as the original router. You only get load balancing when you set different
weights.

### Putting it together

```yaml
upstreams:
  # Tier 1 — load-balanced pool (70/30 split)
  - name: nvidia-glm
    provider: nvidia
    model: z-ai/glm-5.2
    priority: 1
    weight: 70

  - name: openrouter-glm
    provider: openrouter
    model: z-ai/glm-5.2
    priority: 1
    weight: 30

  # Tier 2 — fallback, only used if both tier-1 upstreams are down
  - name: deepseek-backup
    provider: deepseek
    model: deepseek-chat
    priority: 2
    weight: 100
```

When a circuit breaker opens for an upstream, it is removed from the active
pool until the circuit closes.  The remaining upstreams in the same tier
continue to share traffic proportionally.  When every upstream in a tier is
unavailable, the router falls through to the next priority tier.

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

The router emits server-side decision logs for chat-completion routing by
default. Records include metadata only: virtual model, selected upstream,
status/outcome, stream flag, and failed-attempt summaries. Request and response
message bodies are never logged, and every record passes through redaction before
emission. Set `observability.decision_log_enabled: false` to silence these logs.
For streaming requests, a logged `success` means an upstream was selected and
returned 2xx headers; it does not prove the whole stream body completed.

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

## Config guardrails

- **Validate before starting:** `uv run python -m richard_router.main validate --config config/router.yaml` parses and validates the config and prints any problems. Run this after editing the config to catch errors before they surface as a server 500.
- **YAML tabs are rejected at commit time:** a pre-commit hook (`scripts/git-hooks/pre-commit`) blocks tabs in any staged `.yaml`/`.yml` file, because YAML forbids tab indentation and a single tab causes a parse failure at startup. Install it once after cloning:

  ```bash
  ln -sf ../../scripts/git-hooks/pre-commit .git/hooks/pre-commit
  ```

- **Malformed config fails safe at runtime:** if the config cannot be parsed or validated, the server still starts and answers every route with a `503` containing the specific error (e.g. the line/column of a tab) instead of crashing with an unhelpful traceback. Fix the config and restart.
