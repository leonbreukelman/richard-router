# richard-router verification — 2026-07-07

## Scope

Implemented `richard-router` as a standalone OpenAI-compatible router for Hermes Agent.

Hermes-facing contract:
- Provider: `custom:richard-router`
- Base URL: `http://127.0.0.1:4000/v1`
- Virtual model: `coding`

Default upstream policy in `config/router.example.yaml`:
- Primary: NVIDIA `z-ai/glm-5.2`
- Fallback: OpenRouter `z-ai/glm-5.2`

## Local automated verification

Commands run from `/home/leonb/projects/richard-router`:

```bash
uv run ruff check .
uv run pytest -q
```

Result:
- Ruff: pass
- Pytest: `17 passed, 1 warning in 0.17s`

Coverage by fake-upstream tests:
- `/v1/models` exposes virtual model `coding` only.
- Primary success rewrites upstream response model back to `coding`.
- Retryable primary status fails over to fallback.
- Timeout fails over to fallback.
- 400 and 422 do not fail over.
- Both upstreams retryable-fail return aggregate 503.
- Tool schema/request body passes through unchanged except `model` rewrite.
- Streaming SSE chunks rewrite upstream `model` to `coding`.
- Upstream diagnostic header is hidden by default and opt-in for local diagnostics.
- Secret-like strings and auth headers are redacted by helper.

## Live provider verification

Commands used existing local env credentials from `/home/leonb/.hermes/.env`; no key values were printed.

Primary smoke:
```bash
uv run python scripts/live_smoke.py --config config/router.example.yaml --env-file /home/leonb/.hermes/.env
```

Observed result after diagnostic-header hiding patch:
- HTTP status: 200
- Upstream diagnostic header: hidden by default (`"upstream": ""`)
- Response model: `coding`
- Expected text present: true

Forced-fallback smoke with a dead local primary and OpenRouter fallback:
```bash
uv run python scripts/live_smoke.py --config /tmp/richard-router-fallback-live.yaml --env-file /home/leonb/.hermes/.env
```

Observed result after diagnostic-header hiding patch, using a temporary config with `observability.expose_upstream_header: true` only for verification:
- HTTP status: 200
- Upstream: `openrouter-glm-5.2`
- Response model: `coding`
- Expected text present: true

## Hermes profile verification

Created profile:
```bash
hermes profile create routertest --clone --description 'Test profile for richard-router local model router' --no-alias
```

Configured `/home/leonb/.hermes/profiles/routertest/config.yaml` with:
- `custom_providers[0].name: richard-router`
- `custom_providers[0].base_url: http://127.0.0.1:4000/v1`
- `model.provider: custom:richard-router`
- `model.default: coding`

Profile check:
```bash
hermes profile show routertest
```

Observed:
- `Model: coding (custom:richard-router)`

Hermes end-to-end smoke:
```bash
hermes -p routertest chat -Q -q 'Reply exactly: ROUTER-OK'
```

Observed response:
- `ROUTER-OK`

## Opus review

Opus blueprint:
- Saved locally at ignored path `reports/opus/blueprint.json`.
- Result: success.

Opus implementation review:
- Saved locally at ignored path `reports/opus/implementation-review.json`.
- Reviewer ran/checked implementation and reported `ACCEPT_WITH_CHANGES`.
- Reviewer evidence included `uv run ruff check .` and `uv run pytest -q` with 15 tests at that review point.

Valid criticism patched before public push:
1. Streaming SSE chunks leaked real upstream model IDs. Patched `_rewrite_sse_chunk` and added a regression test.
2. Inbound API key comparison used plain equality. Patched to `hmac.compare_digest`.
3. Upstream diagnostic response header exposed provider names by default. Patched to an opt-in observability setting, default false.

Post-patch local verification:
- `uv run ruff check .`: pass
- `uv run pytest -q`: `17 passed, 1 warning`

## Remaining risk

- Streaming can only fail over before a stream is accepted; it cannot safely switch providers mid-answer after bytes are sent.
- Any timeout-based failover can duplicate a prompt upstream if the primary was still processing when the router timed out.
- If the Docker service is exposed beyond loopback, set `RICHARD_ROUTER_API_KEY`; otherwise it is an unauthenticated proxy to paid upstreams.
