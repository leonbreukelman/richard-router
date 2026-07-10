# Certification — Pool & Virtual Model Visibility

**Date:** 2026-07-09  
**Certifier:** Hermes Agent (self-certification)  
**Spec:** `docs/specs/2026-07-09-pool-visibility-metrics.md`  
**Mode:** `github-pr`  
**Escalation:** None (no Tier-4 Fable escalation needed)

---

## 1. Spec Conformance

| Spec Requirement | Implementation | Status |
|---|---|---|
| `MetricsCollector` with flat keyed dict `dict[tuple[vm, upstream], UpstreamMetrics]` | `metrics.py:120` — `self._upstreams: dict[tuple[str, str], UpstreamMetrics]` | ✅ |
| `UpstreamMetrics` dataclass with counters, error breakdowns, epoch timestamps, deque rolling window | `metrics.py:21-29` — all fields present | ✅ |
| `record_attempt()` — O(1) for existing entries, thread-safe via `threading.Lock` | `metrics.py:127-141` — lock held for dict get + field mutations; new-key allocation only on first observation | ✅ |
| `snapshot()` — O(N), groups by virtual model under the collector lock | `metrics.py:143-165` — dict grouping pass derives entries before releasing lock | ✅ |
| Health classification: down ≥ down_threshold, degraded ≥ degraded_threshold or error_rate > pct, else healthy | `metrics.py:65-77` — decision tree matches spec | ✅ |
| Rolling window: `deque(maxlen=metrics_window)` per upstream | `metrics.py:29` — `deque(maxlen=100)` default, resizable | ✅ |
| Wire into `RichardRouter`: `metrics` param, `record_attempt()` at every exit point | `service.py:15` (import), `service.py:66` (param), `service.py:168-327` (all 8 exit points in chat_completion + open_stream) | ✅ |
| `GET /v1/pool` endpoint with auth | `main.py:65-68` — uses `_check_auth`, returns snapshot | ✅ |
| `richard-router status` CLI subcommand | `main.py:146-215` — table output, --vm, --json, --url, --api-key-env, --timeout | ✅ |
| `ObservabilityConfig` extension: metrics_window, degraded_threshold, down_threshold, degraded_error_pct | `config.py:56-59` — all fields with defaults | ✅ |
| Observability metric validation rejects invalid windows/thresholds | `_validate_observability_values()` and `tests/test_config.py` — invalid values, including `down_threshold < degraded_threshold`, are reported by `validate_config()` | ✅ |
| Backward-compatible: all new config fields have defaults | `config.py:56-59` — defaults match spec | ✅ |

## 2. Test Coverage

| Test File | Tests | Coverage |
|---|---|---|
| `tests/test_metrics.py` | 26 | `UpstreamMetrics` (14): success/error/type recording, consecutive resets, rolling window eviction, unchanged-window reuse, all 4 classification paths, custom thresholds, empty state, timestamps, non-2xx edge case. `MetricsCollector` (12): record creates entry, multiple VMs/upstreams, snapshot health/errors, empty, 100-upstream scale, 10-thread concurrent writers, concurrent snapshot while writing, isolated keys, custom thresholds, serialization |
| `tests/test_pool_endpoint.py` | 6 | Pool endpoint: empty state, post-recording metrics, auth (no auth, correct Bearer, correct x-api-key, wrong auth). CLI: connection failure, JSON flag, multi-VM blank-line table grouping |

**Current follow-up verification: targeted config/metrics/pool suite: 42 tests passing. Full suite: 80 tests passing.**

## 3. Scaling Verification

| Dimension | Test Evidence | Result |
|---|---|---|
| 100+ upstreams | `test_100_plus_upstreams`: 20 VMs × 5 upstreams = 100 entries, snapshot groups correctly | ✅ |
| Concurrent writes | `test_concurrent_recording`: 10 threads × 500 records = 5000 total, all accounted for | ✅ |
| Concurrent snapshots | `test_concurrent_snapshot_during_recording`: snapshots run during writes and maintain internally consistent counters | ✅ |
| Isolated keys | `test_isolated_upstreams`: same upstream name under different VMs maintains separate state | ✅ |
| Memory bound | `UpstreamMetrics._window` is `deque(maxlen=N)`, tested via `test_rolling_window_evicts_old_entries` | ✅ |

## 4. Edge Cases Reviewed

| Edge Case | Handling | Status |
|---|---|---|
| No MetricsCollector (metrics=None) | `main.py:68` — ternary: `router.metrics.snapshot() if router.metrics else {"virtual_models": {}}` | ✅ |
| Empty collector (no requests yet) | `metrics.py:143-165` — returns empty `virtual_models` dict | ✅ |
| Outcome="success" with non-2xx code | `metrics.py:44` — `200 <= status_code < 300` check catches this → counts as error | ✅ |
| Classify thresholds at boundaries | `test_classify_custom_thresholds` — exact boundary values tested | ✅ |
| Error rate window overflow | `test_classify_degraded_by_error_rate` — 25% error rate with 1 consecutive failure triggers degraded | ✅ |
| CLI with unreachable server | `test_cli_status_requires_running_server` — exit code 1, stderr message | ✅ |
| CLI JSON output mode | `test_cli_status_json_flag_with_no_server` — exit code 1 (connection refused) | ✅ |
| CLI auth injection | `_status_cli` reads `api_key_env` from env, adds Bearer header | ✅ |
| Backward compat: no new config fields | `config.py:56-59` — all default; existing configs parse unchanged | ✅ |

## 5. Linting

`uv run ruff check .` — **All checks passed** (0 errors)

## 6. Certification Statement

This implementation conforms to the spec at `docs/specs/2026-07-09-pool-visibility-metrics.md`. All spec requirements are met. The implementation is backward-compatible — existing configs require no changes. The rolling window design ensures bounded memory regardless of request volume. Follow-up hardening tightened the write path so fixed-size windows are not rebuilt on every attempt, changed snapshots to derive entries under the collector lock, fixed CLI VM-group spacing, validates observability metric config values, and removed unbacked benchmark-style claims from the spec. Test coverage includes normal paths, edge cases, concurrent writes/read snapshots, config validation, and scale scenarios.

**Verdict: CERTIFIED** — Ready for PR.
