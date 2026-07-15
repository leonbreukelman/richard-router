# Extract Shared Failover Logic — Spec

**Date**: 2026-07-15  
**Branch**: `refactor/extract-failover-logic`  
**Base**: `052bd6f` (main)

## Problem

`chat_completion()` (lines 256–378) and `open_stream()` (lines 403–531) in `service.py` shared ~80% identical logic:

- Virtual model lookup → 404 decision if missing
- Upstream iteration loop with `max_attempts_per_upstream` retries
- Circuit breaker check before each attempt (skip if open)
- Success recording: circuit breaker reset + metrics + decision log
- HTTP error recording: attempt append + metrics + circuit breaker
- Transport error handling: timeout and connection error recording + metrics
- "All failed" final fallback

This meant every bug fix or feature addition (latency tracking, retry budgets) had to be applied in two places, doubling maintenance surface.

## Solution

Extracted four shared helper methods onto `RichardRouter`:

| Helper | Inputs | Returns | Replaces |
|--------|--------|---------|----------|
| `_record_success()` | upstream, virtual model name, status code, upstream name | None | Inline success recording in both paths |
| `_record_http_failure()` | upstream, response, attempts list, virtual model name, error_message | `bool` (should_continue?) | Inline HTTP error handling in both paths |
| `_record_transport_failure()` | upstream, exception, attempts list, virtual model name | `bool` (should_continue?) | Separate timeout/connection error handlers in both paths |
| `_failover_loop()` | virtual model, try_upstream callback, stream flag | `RouterResult \| RouterStream` | Shared iteration/circuit-breaker/error skeleton |

...plus a `_ContinueSentinel` / `_CONTINUE` sentinel for the callback to signal "continue to next upstream."

`chat_completion` and `open_stream` are now thin callers that:
1. Look up the virtual model (shared 404 path)
2. Define a `try_upstream(upstream, attempts)` callback with the divergent parts (client.post vs client.stream, response body vs stream iterator)
3. Call `_failover_loop(virtual, try_upstream, stream=...)`

## Verification

| Gate | Result |
|------|--------|
| `ruff check .` | All checks passed |
| `pytest -v` (80 original tests) | 80 passed |
| `pytest -v` (8 new refactor tests) | 8 passed |
| Total | **88 passed, 0 failed** |

### New Tests (tests/test_failover_refactor.py)

| Test | What it proves |
|------|---------------|
| `test_record_http_failure_appends_attempt_and_records_metrics` | `_record_http_failure` creates attempt + updates metrics on retryable error |
| `test_record_http_failure_non_retryable_returns_false` | Non-retryable status returns `False` (terminal) |
| `test_record_transport_failure_timeout_appends_and_records` | `_record_transport_failure` records timeout correctly |
| `test_record_transport_failure_non_retryable_returns_false` | Fatal exception (non-httpx) returns `False` |
| `test_record_transport_failure_connection_error` | `ConnectError` recorded as connection_error, returns True |
| `test_record_success_resets_circuit_breaker_and_metrics` | `_record_success` updates metrics |
| `test_failover_loop_returns_success_from_first_healthy_upstream` | Loop calls callback once on first success |
| `test_failover_loop_skips_circuit_open_upstream` | Circuit-open upstream skipped, fallback tried |

## Behavioral Preservation (Zero-Delta Contract)

Every existing test passes without modification, proving:

- Failover order: primary → fallback → 503
- Circuit breaker: opens after N failures, half-open probe after cooldown, closed on success
- Streaming: SSE model rewriting, [DONE] passthrough, stream iterator lifecycle
- Decision logs: metadata-only, redacted, no bodies leaked
- Error handling: 400/422 don't fail over, 503/429/timeout/connection errors do
- Client pooling: httpx clients cached by (name, base_url, model) tuple
- Mock transport tests: all pass with identical assertions

## Risk

- **Non-zero**: The refactoring moves the exception-catching boundary. In the old code, `TimeoutException`/`TransportError` were caught inside the `chat_completion` method body. In the new code, they're caught in `_failover_loop`, and the `open_stream` callback re-raises them after cleaning up the stream context manager. This is analyzed and tested but should be the focus of review.
- **Low**: The `_CONTINUE` sentinel pattern is unusual. A type error in the callback (returning something that's not `_CONTINUE`, `RouterResult`, or `RouterStream`) would propagate through `_failover_loop` as a `TypeError`. The existing tests cover all normal paths.

## Scope

**In scope**: Extract shared failover logic. Reduce code duplication. Add unit tests for new helpers.

**Out of scope**: Behavioral changes to failover, circuit breaker, metrics, logging, or streaming. Config or API changes.
