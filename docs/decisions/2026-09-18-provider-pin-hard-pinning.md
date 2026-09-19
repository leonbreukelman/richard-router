# ADR: provider_pin — hard provider pinning that honors guardrails

Date: 2026-09-18
Status: accepted
Decision by: Leon (operator) + Hermes Agent

## Context

Cost-sensitive routing wanted each virtual model pinned to a specific host
provider (e.g. relace, deepseek) chosen by a cost-vs-usage analysis. Two pin
mechanisms exist on OpenAI-compatible gateways:

- The **colon-route form** (`model:deepseek/deepseek-v4-flash-0731:relace` in
  the `model` field) is a **soft routing hint**. When the pinned provider is
  blocked or unreachable, the gateway silently falls back to another allowed
  provider instead of erroring. On OpenRouter this bypasses operator intent:
  a model intended for DeepInfra was actually served by Relace, and a
  guardrail-blocked provider produced no error at all.
- The **`provider: {only: [...]}` request-body field** is a **hard pin**. It
  honors the account guardrail exactly: a pinned provider outside the
  `allowed_providers` allowlist is rejected with a guardrail 404, and an
  allowed provider is served as pinned. Verified live 2026-09-18:
  `provider.only: deepinfra` → 404 blocked; `provider.only: relace` → 200.

richard-router only rewrote the `model` string, so it could express only the
soft colon-route form and could not emit the hard `provider.only` pin.

## Decision

Add a per-upstream `provider_pin: [<provider-id>, ...]` config field that
injects `{"provider": {"only": [...]}}` into the request body forwarded to the
upstream. Behavior:

- When set, the forwarded body carries `provider: {only: [<pins...>]}`.
- When omitted/empty, the body is unchanged (no `provider` field is added), so
  existing configs are a zero-delta.
- Provider IDs are passed through verbatim; the upstream (e.g. OpenRouter)
  resolves them. This is what makes the pin **honor account guardrails** rather
  than silently falling back.

The soft colon-route form remains supported but is documented as a weaker hint;
guide users to `provider_pin` when they want a guaranteed provider.

## Consequences

- A virtual model can now hard-pin to an allowed provider, delivering the
  "cheapest cost-effective provider" routing goal without relying on a silent
  fallback that can change behaviour if the pinned host becomes unavailable.
- Guardrail-blocked pins fail loudly (404) at the upstream instead of
  silently serving from an unintended host.
- Backward compatible: default `provider_pin = ()` reproduces prior behaviour.
- Providers outside the guardrail allowlist still fail; `provider_pin` does not
  and must not bypass guardrails.

## Evidence

- `tests/test_provider_pin.py` — normalization, validation, body injection,
  end-to-end forwarded-body check (188 tests total, green).
- Live OpenRouter probes (2026-09-18): colon-route pinned provider silently
  fell back to relace; `provider: {only:[...]}` correctly returned guardrail
  404 for blocked providers and 200 for allowed ones.