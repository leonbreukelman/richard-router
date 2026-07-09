# ADR: Provider registry config contract for router-core uplift

Date: 2026-07-08
Status: accepted for Track F Phase 1 implementation
Scope: Phase 1 config contract, with later Track F decisions noted but not implemented here

## Context

`richard-router` currently defines every upstream inline under each virtual model. That works for the first `coding` model, but it makes adding another failover-backed virtual model repetitive and easy to misconfigure. The Track F uplift needs declared providers, startup validation, and a validate CLI without breaking Leon's existing inline-upstream config.

The current project is live on GitHub and now uses `github-pr` mode, so config-contract changes must be additive and test-proven before merge.

## Decision

Add an optional top-level `providers:` map. Each provider declares reusable connection metadata:

- `base_url`
- `api_key_env`
- optional `headers`
- optional timeout settings

Virtual model upstream entries may use either form:

1. Provider reference form:
   - `provider: <provider-name>`
   - `model: <real-upstream-model-id>`
   - optional per-entry `name` / timeout overrides where supported by implementation
2. Existing inline form:
   - `name`
   - `base_url`
   - `api_key_env`
   - `model`
   - optional `headers`
   - optional `timeout_seconds`

Both forms normalize to the same internal `VirtualModel(upstreams=(Upstream, ...))` shape consumed by the router. Inline upstreams remain valid for this uplift.

Validation will be implemented with Pydantic v2 surface models and a pure `validate_config(cfg) -> list[str]` function. The `richard-router validate --config <path>` CLI exits non-zero and prints one problem per line when provider references are dangling, upstream lists are empty, or referenced `*_API_KEY` env vars are unset. Errors may name env-var names but must never print secret values.

## Consequences

- Adding a new virtual model becomes mostly provider references plus real model IDs.
- Existing live inline configs do not require migration.
- Missing credentials and typoed provider references fail closed before serving.
- `config/router.example.yaml` should move to provider-reference form while keeping one commented inline example as a compatibility proof.

## Adjacent Track F decisions noted for later phases

Circuit breaker behavior is part of Track F but not the config-registry surface itself. The handoff records the intended Phase 3 default as:

- `failover.circuit_breaker.enabled: true`
- `failure_threshold: 5`
- `cooldown_seconds: 30`
- `half_open_max_probes: 1`

Breaker retryability must reuse `richard_router.errors.classify_status` and `classify_exception`; it must not create a parallel taxonomy. Caller/config 4xx failures must not open the breaker.

Decision logging is Phase 4 work. The handoff records the intended boundary as server-side metadata only: records pass through `redact()` before emitting and never include request/response message bodies.

These adjacent decisions are recorded here so future phases do not re-litigate the handoff, but this ADR's implemented contract is the additive provider registry and validation behavior.

## Deferred

These stay out of this ADR and Track F implementation:

- Heterogeneous per-provider request parameter mapping.
- Prometheus `/metrics` and OpenTelemetry.
- Token-to-cost/spend accounting.
- `/v1/models` capability enrichment.
- `/ready` split and Anthropic `/v1/messages` shim.
- Mid-stream failover.
