# Decision: Decision log boundary

Date: 2026-07-09
Status: accepted for Track F Phase 4 implementation

## Context

Track F Phase 4 adds routing decision visibility after provider registry, pooled clients, and the circuit breaker have landed. The earlier provider-registry ADR recorded the Phase 4 boundary: decision logging is server-side metadata only, records pass through `redact()`, and request/response message bodies must never be emitted.

The router must help operators explain routing behavior without leaking the user's prompts, assistant responses, API keys, bearer tokens, cookies, or provider credentials.

## Decision

Emit one server-side route-decision record per chat-completion routing outcome.

Records include only:

- event name;
- virtual model;
- stream flag;
- outcome;
- selected upstream name, when one handled the response;
- HTTP status code, when available;
- failed-attempt summaries already represented by `Attempt.safe_dict()`.

Records exclude request bodies, response bodies, messages, tool schemas, and upstream request headers.

Every record passes through `redact()` before it is emitted. By default records are written through the Python logger. Tests may inject a `decision_logger` callback to assert the exact metadata without depending on log capture.

`observability.decision_log_enabled` controls emission and defaults to `true`. This is server-side logging only; it does not add response headers or alter the OpenAI-compatible response body.

For streaming requests, a `success` decision means the router selected an upstream and received 2xx stream headers. It does not certify that the entire stream body completed successfully.

## Rationale

This gives Leon enough evidence to understand why a request landed on a provider or why all providers failed, while preserving the router abstraction for clients and avoiding prompt/response leakage.

The logger path keeps the implementation dependency-free and deployment-neutral. It lets container/systemd/log collectors handle storage and retention without introducing a new persistence layer in this phase.

## Alternatives considered

- Log full request and response bodies — rejected. It violates the Track F boundary and would leak prompts, tool schemas, and assistant output.
- Add a public `/decision-log` endpoint — rejected for this phase. It expands public API and requires storage, retention, and auth decisions.
- Add Prometheus/OpenTelemetry metrics now — rejected. The earlier ADR explicitly deferred metrics/OTel; this phase is metadata decision logging only.
- Reuse `x-richard-router-upstream` diagnostics — rejected as the primary mechanism. Response headers leak abstraction to clients and are already explicitly local-diagnostics-only.

## Consequences

- Operators get metadata-only route evidence for success, failover, all-failed, streaming, and unknown-model outcomes.
- Server logs can include upstream names even when client-facing diagnostic headers are disabled.
- No request/response payload replay or historical decision API exists in this phase.
- Logging is in-process only; external retention depends on the host logging stack.

## Evidence

- Implementation branch: `phase4-decision-log`
- Verification ledger: `docs/verification/2026-07-08-richard-router-uplift-verification.md`
- Tests: `tests/test_decision_log.py`

## Supersession

- Supersedes: none
- Superseded by: none
