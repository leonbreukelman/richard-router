# Decision: Half-open circuit requires a 2xx to close

Date: 2026-07-18
Status: accepted

## Context

The circuit-breaker state machine in `richard_router/service.py` previously
treated any non-retryable HTTP response (e.g. 400/401/403/422) from an
in-flight half-open probe as sufficient evidence to close the breaker, via
`_record_upstream_success`. This was codified by
`tests/test_circuit_breaker.py::test_half_open_non_retryable_response_closes_breaker`.

A 4xx proves only that the upstream answered — not that the prior 5xx
condition recovered. A malformed caller request, or a synthetic health
probe rejected with 400, would therefore restore full traffic to an
upstream that still fails valid requests. Issue
`leonbreukelman/richard-router#33` flagged this as an availability risk;
the recommendation was accepted for resolution.

## Decision

A half-open circuit closes **only** on a 2xx response from the probe. Any
non-2xx probe outcome leaves the breaker open:

- **Closed** state: unchanged. 4xx responses are non-retryable, do not
  increment retryable-failure counters, do not open the breaker. Success
  counters may be cleared as before.
- **Open** state (within cooldown): unchanged. All traffic to that
  upstream is skipped.
- **Half-open** state (post-cooldown, a single probe permitted):
  - 2xx → breaker closes, state fully resets.
  - Retryable failure (e.g. 503, or timeout/connection error per policy)
    → breaker re-arms; `opened_at` is set to now, cooldown restarts.
  - Non-retryable non-2xx (e.g. 400/401/403/422) → breaker stays open;
    `opened_at` is set to now (re-arm cooldown), `half_open_probes`
    resets to 0 so the next request after cooldown is again a probe.
    `consecutive_failures` is **not** incremented (the response was not
    a retryable failure).

The same rule applies to both real request traffic and the background
`HealthCheckTask` probe.

## Rationale

The half-open state exists to prove recovery. A 4xx does not prove
recovery of the condition that opened the breaker; it only proves the
socket is up and the upstream returned a well-formed error. Closing on
4xx creates a poisoning vector where any caller (or the health prober
itself) can force premature reintroduction of a still-broken upstream.

Keeping closed-state 4xx behavior unchanged avoids conflating this fix
with the general HTTP retry classification (see PR #34 /
`retry_on_status` policy).

## Alternatives considered

- **Status quo: 4xx closes half-open.** Rejected — this is the exact
  availability bug the decision addresses.
- **4xx increments `consecutive_failures` during half-open.** Rejected —
  4xx is not a retryable failure; conflating the two would leak into
  closed-state failure-counting semantics and risk opening the breaker
  on ordinary caller errors.
- **4xx during half-open transitions to closed with a probation counter.**
  Rejected as over-engineering; a re-armed cooldown provides the same
  guard with the existing state machine.

## Consequences

- Recovery from a genuine 5xx incident now requires that the first probe
  after cooldown be a real, well-formed request that the upstream can
  serve successfully. If probes keep returning 4xx (e.g. malformed
  probe body), the breaker will oscillate: cooldown → probe → re-arm →
  cooldown. This is intentional and observable via metrics.
- Health-check probes must send a body the upstream will accept. The
  existing `probe_max_tokens=1` chat-completion body is expected to
  return 2xx from healthy providers.
- Pool metrics and breaker state remain consistent: a 4xx probe records
  an `http_error` attempt and leaves `opened_at` set, so `/v1/pool`
  will not report the upstream as healthy while the breaker is open.

## Evidence

- Implementation: `richard_router/service.py` —
  `_record_non_retryable_response` and its call sites in
  `_record_http_failure` and `HealthCheckTask._probe_upstream`.
- Regression tests: `tests/test_circuit_breaker.py` (updated
  `test_half_open_non_retryable_response_keeps_breaker_open`, new
  `test_mixed_503_then_400_probe_keeps_breaker_open_then_recovers_on_2xx`)
  and `tests/test_health_check.py`
  (`test_probe_400_against_open_breaker_keeps_it_open`).
- README: `README.md` circuit-breaker section updated to state
  "A successful 2xx probe closes the circuit."
- Gates: `uv run ruff check .`, `uv run pytest -v`.

## Supersession

- Supersedes: none
- Superseded by: none
