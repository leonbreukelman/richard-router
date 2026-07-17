# Background Health Check & Error Clearing — Spec + Handoff

Date: 2026-07-17
Track: F
Status: landed
Thread: bg-health-check
Supersedes: none
Repo: leonbreukelman/richard-router (local: `/home/richard/richard-router`)
Branch: `feat/bg-health-check` from base `6bdbff4`
Mode: github-pr
Driver: Hermes Agent · Certifier: self-certified (Claude Code Opus not available) · Method: docs/method/METHOD.md

## The one rule

Done = a `github-pr` merged to `main` that adds a configurable background health-check task to the router which periodically probes degraded/down pool members, records the probe outcome through the existing metrics pipeline, and clears stale error state on success — verified by `uv run pytest -v` and `uv run ruff check .` both green on CI.

## Verification evidence (landed)

- PR #23: https://github.com/leonbreukelman/richard-router/pull/23
- Merge commit: `fe6467b0973f4ae8dc40bfd99e3b87b758d2e23a`
- Merge method: squash
- Branch: `feat/bg-health-check` → pushed → merged → deleted
- CI check `uv / ruff / pytest`: success
- Local gates: `uv run ruff check .` — clean; `uv run pytest -v` — 125 passed (106 existing + 19 new)
- Changed files: 7 — `config/router.example.yaml`, `docs/specs/2026-07-17-background-health-check.md`, `richard_router/config.py`, `richard_router/main.py`, `richard_router/metrics.py`, `richard_router/service.py`, `tests/test_health_check.py`
- Protected paths untouched: `config/router.yaml` not modified

## Goal

The router proactively detects when previously degraded/offline pool members have recovered and reflects that recovery in the `/v1/pool` metrics and the `richard-router status` CLI output — including clearing stale `last_error_message` and `errors_by_code` so the dashboard shows a clean state once health returns.

## Scope lock

Build only this:
1. **Config layer** — new `health_check` config section with `enabled`, `interval_seconds`, `probe_max_tokens`, `probe_timeout_seconds`, `probe_statuses` fields, all with backward-compatible defaults.
2. **Error-clearing fix** — `UpstreamMetrics.record()` clears `last_error_message` on success and optionally clears `errors_by_code`/`errors_by_type` (design decision D3 below).
3. **Background task** — an `asyncio` task started in the FastAPI lifespan that periodically probes degraded/down upstreams using the router's own httpx client + metrics pipeline.
4. **Tests** — unit tests for error clearing, health-check task logic, config validation, and circuit-breaker interaction.
5. **Config docs** — update `config/router.example.yaml` with the new `health_check` section.

Do not build:
- A new CLI subcommand for manual probing (separate concern, not requested).
- An admin reset endpoint (the background task supersedes this need).
- Persistent/daemon health-check state across restarts.
- WebSocket or push notification of health transitions.
- Changes to the `richard-router status` table columns or formatting.
- A Prometheus `/metrics` endpoint.
- Alerting or threshold configuration.

## Grounding

Read these paths at base `6bdbff4` before editing; re-read them in your own turn and confirm conflicts. Repo wins on conflict — stop and flag, do not invent.

- `richard_router/metrics.py` — `UpstreamMetrics.record()` (lines 32-59), `classify()` (lines 68-80), `MetricsCollector.record_attempt()` (lines 129-148), `snapshot()` (lines 150-173). Establishes the metrics data model and the error fields that need clearing.
- `richard_router/service.py` — `RichardRouter.__init__` (lines 77-91), `_client_for()` (lines 97-103), `_circuit_open_attempt()` (lines 113-125), `_circuit_allows_traffic()` (lines 127-137), `_record_upstream_success()` (lines 139-145), `_record_retryable_failure()` (lines 147-160), `_upstream_headers()` (lines 185-193), `_rewrite_body()` (lines 196-199), `chat_completion()` (lines 528-604). Establishes client reuse, circuit breaker state, and the request path the probe must follow.
- `richard_router/main.py` — `create_app()` (lines 62-147), lifespan context manager (lines 80-86). Establishes where the background task starts and stops.
- `richard_router/config.py` — `ObservabilityConfig` (lines 66-72), `FailoverConfig` (lines 56-62), `CircuitBreakerConfig` (lines 48-53), `RouterConfigModel` (lines 160-167), `_build_router_config()` (lines 393-429), `_validate_normalized_config()` (lines 234-259), `validate_config()` (lines 262-307). Establishes the config-field pattern and validation pipeline.
- `config/router.yaml` — production config (protected, do not modify; read for grounding only).
- `config/router.example.yaml` — template config to be updated with `health_check` section.
- `tests/conftest.py` — `make_test_config()` fixture; establishes test config pattern.

## Preflight

Base `6bdbff4` checked out. Mode from PROJECT.md: `github-pr`. Gate commands `uv run ruff check .` and `uv run pytest -v` must be green on base. If base is red, file BLOCKED instead of fixing unrelated breakage.

## Component contract

### `metrics.py` — `UpstreamMetrics.record()`

- **Input**: `outcome` str, `status_code` int|None, `error_type` str|None, `error_message` str|None, `window_size` int|None (unchanged signature).
- **Success path change**: when `outcome == "success"` and `200 <= status_code < 300`, in addition to existing behavior (increment `success_count`, reset `consecutive_failures`, set `last_ok`, append True to window), **clear `last_error_message = None`** and **clear `errors_by_code = {}` and `errors_by_type = {}`**.
- **Failure path**: unchanged.
- **Never rendered**: internal `_window` deque (still private).
- **Determinism**: clearing errors on success is deterministic — every success clears, regardless of how many errors preceded it.
- **Fail-closed conditions**: none; this is purely cosmetic state, not safety-critical.

### `config.py` — new `HealthCheckConfig` dataclass + Pydantic model

- **Input and validation**:
  - `enabled: bool = False` (default OFF for backward compat — no probes unless explicitly opted in).
  - `interval_seconds: float = 60.0` (minimum 5.0, validated).
  - `probe_max_tokens: int = 1` (minimum 1, validated).
  - `probe_timeout_seconds: float = 10.0` (minimum 1.0, validated) — separate from upstream `timeout_seconds` to keep probes fast.
  - `probe_statuses: list[str] = ["degraded", "down"]` — only probe members whose current `classify()` status is in this list.
- **Selection/routing**: `HealthCheckConfig` is a sibling of `FailoverConfig` and `ObservabilityConfig` on `RouterConfig`.
- **Output/rendered behavior**: appears in config validation; not rendered in any endpoint.
- **Never exposed**: `HealthCheckConfig` itself is not serialized in `/v1/pool` or `/health`.
- **Determinism**: all fields have deterministic defaults.
- **Fail-closed conditions**: `enabled: false` by default means zero behavior change for existing deployments.

### `service.py` — `HealthCheckTask` (new class) + wiring in `RichardRouter`

- **Input**: `RichardRouter` instance, `HealthCheckConfig`, `MetricsCollector`.
- **Behavior**: on each tick (every `interval_seconds`):
  1. Iterate all virtual models and their upstreams.
  2. Skip upstreams whose `classify()` status is NOT in `probe_statuses`.
  3. For each upstream to probe: build a minimal chat completion request `{"messages": [{"role": "user", "content": "ping"}], "max_tokens": <probe_max_tokens>, "stream": false}`.
  4. Send the request through the router's own `_client_for(upstream)` using the upstream's real URL, headers, and model (same path as real traffic).
  5. On 2xx: call `_record_upstream_success(upstream)` to reset the circuit breaker, and call `metrics.record_attempt(virtual_name, upstream.name, "success", status_code=<code>)` to record the success (which triggers the error-clearing fix in `metrics.py`).
  6. On retryable HTTP error (429/5xx): call `_record_retryable_failure(upstream)` and `metrics.record_attempt(...)` with the error — same as real traffic failure handling.
  7. On non-retryable HTTP error (400/401/403): do NOT record a failure (matching existing 4xx non-retryable behavior). Log at debug level. The member stays in its current state; real traffic will re-evaluate it.
  8. On timeout/transport error: call `_record_retryable_failure(upstream)` and record the error if `failover.retry_on_timeout` / `retry_on_connection_error` are set (matching real-traffic behavior).
- **Output/rendered behavior**: probe outcomes flow through `MetricsCollector` and are visible in `/v1/pool` and `richard-router status` — no separate endpoint.
- **Never rendered**: the probe request/response bodies are never logged (same redaction as real traffic).
- **Determinism**: probe order is deterministic (sorted by virtual model name then upstream name).
- **Fail-closed conditions**: if `health_check.enabled` is false, the task is never started. If the task raises an unhandled exception, it logs the error and reschedules the next tick (does not crash the server).

### `main.py` — lifespan wiring

- **Input**: `create_app()` reads `config.health_check` from the loaded `RouterConfig`.
- **Behavior**: in the `lifespan` async context manager, if `config.health_check.enabled` is true, start the `HealthCheckTask` as an `asyncio.Task`. On shutdown (`finally` block), cancel the task and await cleanup.
- **Output**: server logs a single INFO line on start: `"health check task started (interval=60s)"` and on stop: `"health check task stopped"`.
- **Never exposed**: no endpoint to start/stop the task at runtime.
- **Determinism**: task lifecycle is tied to FastAPI lifespan — starts on app startup, stops on app shutdown.
- **Fail-closed conditions**: if `enabled` is false, no task is created.

## Design decisions

- **D1 — Default OFF (`enabled: false`)**. Rationale: the router currently has no background activity. Existing deployments must opt in explicitly. This ensures zero behavior change for current users and zero probe quota consumption unless the operator chooses it. Tagged operator-deferred: the operator decides when to enable it in production.

- **D2 — Probes go through the router's own httpx client, NOT via the `/v1/chat/completions` endpoint**. Rationale: the router's failover logic deliberately skips circuit-open upstreams, so a probe via the public endpoint would never reach the degraded member. By sending directly to the upstream's URL using `_client_for()`, the probe bypasses the failover skip but still reuses the same client pool, headers, and body-rewriting logic. The probe records metrics directly via `metrics.record_attempt()` so the outcome is visible in `/v1/pool`.

- **D3 — Clear `errors_by_code`, `errors_by_type`, and `last_error_message` on success**. Rationale: the user explicitly requested that once a member is healthy, the error code displayed in the dashboard should be cleared. The current code accumulates error counts in `errors_by_code`/`errors_by_type` and never clears them — on success, only `consecutive_failures` is reset. Clearing all three on success gives a clean dashboard. The chronological `last_error` timestamp is also cleared (set to `None`) for consistency. Alternative considered: clear only `last_error_message` but keep `errors_by_code` for historical reference — rejected because the user said "clear the error code that's displayed" and the status table shows `errors_by_code` in the "Error" column.

- **D4 — Probe uses `max_tokens: 1` to minimize cost**. Rationale: one token is the minimum viable response. The probe only needs a 2xx to confirm health — it doesn't need meaningful content. Cost per probe is negligible (fraction of a cent on most providers, free on free-tier upstreams). `probe_max_tokens` is configurable for providers that have minimum token requirements.

- **D5 — Separate `probe_timeout_seconds` (default 10s) from upstream `timeout_seconds` (default 60s)**. Rationale: a probe that takes 60s to respond isn't healthy. Probes should fail fast so the health-check cycle completes quickly and doesn't accumulate hung connections. 10s is generous for a 1-token response.

- **D6 — Probe does NOT consume a circuit-breaker half-open probe slot**. Rationale: `_circuit_open_attempt()` consumes a half-open probe slot, which is designed for real traffic attempting to close the circuit. The health check uses `_circuit_allows_traffic()` to check state (side-effect-free) but sends the probe directly regardless of circuit state — the whole point is to probe a member that the circuit breaker is currently blocking. After a successful probe, `_record_upstream_success()` resets the circuit breaker, reopening it for real traffic. This means the health check CAN reset a circuit-open breaker — which is the desired behavior (detect recovery → reopen for traffic).

- **D7 — No probe for healthy members**. Rationale: probing healthy members wastes quota and adds noise. `probe_statuses` defaults to `["degraded", "down"]`. An operator could expand this to `["healthy", "degraded", "down"]` to probe all members continuously, but that's an explicit opt-in.

- **D8 — Task survives exceptions and reschedules**. Rationale: a single probe failure (e.g., one upstream's DNS resolution crashes) must not kill the health-check task for all upstreams. Each probe is wrapped in try/except. If the entire tick somehow raises, the task catches, logs, and continues to the next interval.

## Tasks

Use concrete file/test names. No prose-only descriptions.

1. **`metrics.py`** — Modify `UpstreamMetrics.record()` success branch to clear `last_error_message`, `errors_by_code`, `errors_by_type` on success — proven by `tests/test_health_check.py::test_success_clears_error_state`.
2. **`config.py`** — Add `HealthCheckConfig` frozen dataclass + `HealthCheckConfigModel` Pydantic model. Add `health_check: HealthCheckConfig` field to `RouterConfig`. Add `health_check` to `RouterConfigModel`. Thread through `_build_router_config()`. Add validation in `_validate_normalized_config()` and `validate_config()` — proven by `tests/test_config.py::test_health_check_defaults` and `test_health_check_invalid_values`.
3. **`service.py`** — Add `HealthCheckTask` class with `start()`, `stop()`, `_tick()` methods. The `_tick()` method iterates upstreams, filters by `probe_statuses` via `MetricsCollector.snapshot()`, probes with `_client_for()`, and records outcomes via `_record_upstream_success()` / `_record_retryable_failure()` + `metrics.record_attempt()`. Add `health_check_task: HealthCheckTask | None` to `RichardRouter.__init__` — proven by `tests/test_health_check.py::test_tick_probes_degraded_member` and `test_tick_skips_healthy_member`.
4. **`main.py`** — In `create_app()` lifespan, start/stop `HealthCheckTask` based on `config.health_check.enabled` — proven by `tests/test_health_check.py::test_task_starts_when_enabled` and `test_task_not_started_when_disabled`.
5. **`config/router.example.yaml`** — Add commented `health_check` section with all fields documented.
6. **`tests/test_health_check.py`** — NEW file with tests:
   - `test_success_clears_error_state` — record failures, then success, verify `last_error_message` and `errors_by_code` are cleared.
   - `test_tick_probes_degraded_member` — degraded upstream gets probed, success recorded, circuit breaker reset.
   - `test_tick_skips_healthy_member` — healthy upstream is NOT probed (no extra requests).
   - `test_tick_probes_down_member` — `down` status upstream gets probed.
   - `test_tick_skips_member_not_in_probe_statuses` — if `probe_statuses: ["down"]` only, degraded member is skipped.
   - `test_task_starts_when_enabled` — app lifespan starts the task.
   - `test_task_not_started_when_disabled` — default config, no task.
   - `test_probe_failure_records_error` — probe gets 503, records failure, circuit breaker increments.
   - `test_probe_400_does_not_record_failure` — probe gets 400, does NOT increment failure (non-retryable).
   - `test_task_reschedules_after_exception` — a probe that raises doesn't kill the task.
   - `test_probe_resets_circuit_breaker_on_success` — circuit-open upstream, successful probe reopens circuit.
7. **`tests/test_config.py`** — Add tests:
   - `test_health_check_defaults` — all fields have correct defaults when omitted.
   - `test_health_check_enabled_true` — `enabled: true` parses correctly.
   - `test_health_check_interval_too_low` — `interval_seconds < 5.0` rejected.
   - `test_health_check_probe_statuses_invalid` — unknown status string rejected.

## Acceptance gate

State mode-appropriate evidence:

- **github-pr**: PR URL, merge SHA, GitHub changed-file list, CI check-run conclusion.
- All tests pass: `uv run pytest -v` (including new `tests/test_health_check.py`).
- Lint clean: `uv run ruff check .`.
- `config/router.example.yaml` updated with `health_check` section.
- No changes to `config/router.yaml` (protected path).
- Backward compatibility: existing tests pass unchanged (no defaults changed, no schema break).
- Self-certification evidence: spec conformance table, test coverage table, edge-case review per user's standing requirement (Claude Code Opus not available).

## If you get stuck

Follow METHOD.md escalation ladder. Scope insufficiency is SCOPE-DELTA, not improvisation.

## Report back

Return the evidence ledger per METHOD.md §8, including escalation log and operator value summary.

## Known boundaries and open items

- **Operator-gated**: the operator decides when to enable `health_check.enabled: true` in production `config/router.yaml` and restart the server. The spec ships with it OFF.
- **No cross-restart state**: health-check state is ephemeral. If the router restarts, all metrics reset (existing behavior). The background task starts fresh.
- **Probe cost**: each probe consumes one API call per degraded/down member per interval. At `interval_seconds: 60` with 2 degraded members, that's ~2 calls/minute — negligible for most providers. Free-tier upstreams (OpenRouter `:free`, OpenCode) may have rate limits; the operator should tune `interval_seconds` accordingly.
- **Race condition with real traffic**: a probe and a real request could arrive at the same upstream simultaneously. This is safe — both go through httpx's connection pool, and metrics are recorded under a lock. Worst case: two successes are recorded instead of one, which is harmless.
- **D6 interaction — probe resets circuit breaker**: this is intentional. A successful probe means the upstream is healthy, so the circuit breaker should reopen. However, this means the health check can reopen a circuit before real traffic would have tested it. The trade-off is faster recovery vs. potentially routing real traffic to a flaky upstream that passes a 1-token probe but fails on real requests. The circuit breaker will re-open if real traffic fails again. This is acceptable.
- **Not implemented (future scope)**: configurable probe payload, probe per virtual model (currently probes all virtual models a degraded upstream belongs to), health transition notifications, Prometheus metrics.

## Stop clause

If you cannot produce the mode-appropriate evidence, it is not done. File BLOCKED and stop.
