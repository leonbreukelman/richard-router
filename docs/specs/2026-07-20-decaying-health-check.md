# Decaying Health Check — Backoff for Degraded/Down Pool Members

Date: 2026-07-20
Track: G
Status: planned
Thread: decaying-health-check
Supersedes: docs/specs/2026-07-17-background-health-check.md (refines, does not replace)
Repo: leonbreukelman/richard-router (local: `/home/richard/richard-router`)
Branch: `main` (no PR yet)
Mode: github-pr
Driver: Hermes Agent · Certifier: self-certified · Method: docs/method/METHOD.md

## The one rule

Done = a `github-pr` merged to `main` that replaces the fixed-interval health check with a per-upstream exponential-backoff strategy so that terminally-down hosts are probed less frequently, reducing wasted API calls and avoiding rate-limit self-harm on free-tier upstreams — verified by `uv run pytest -v` and `uv run ruff check .` both green on CI.

## Problem

The current `HealthCheckTask` (landed in PR #23, merged `fe6467b`) probes every degraded/down member **every `interval_seconds`** (default 60s). For a host that is genuinely down (connection refused, persistent 5xx, throttled):

- Each probe is a wasted API call against the failing upstream.
- On free-tier providers (OpenRouter free, OpenAI free trial, etc.) repeated failed probes consume rate-limit budget, potentially **keeping the host down longer** than the underlying condition justifies.
- There is no concept of "this host has been down for 20 minutes — back off". A 10-second blip and a 10-hour outage get identical treatment.

## Scope lock

Build only:

1. **Config layer** — three new fields on `HealthCheckConfig`: `backoff_base_seconds`, `backoff_max_seconds`, `backoff_multiplier`, each with backward-compatible defaults that reproduce current behavior.
2. **Per-upstream backoff state** — `HealthCheckTask` maintains private `_next_probe_at` and `_probe_failures` dicts, keyed by `ClientCacheKey`.
3. **Tick filter** — `_tick()` skips upstreams whose `next_probe_at` is in the future.
4. **Probe outcome wiring** — failed probes advance the backoff curve; successful probes reset it.
5. **`_run()` sleep adapts** — the loop sleep becomes `min(interval_seconds, time-to-next-due)` so a freshly-degraded host doesn't wait for a long-sleeping tick.
6. **Pool snapshot exposure** — `/v1/pool` includes `next_probe_at` (ISO timestamp or null) per upstream so the CLI dashboard can show when the next check is due.
7. **Config validation** — `backoff_base_seconds >= 1.0`, `backoff_max_seconds >= backoff_base_seconds`, `backoff_multiplier >= 1.0`.
8. **Tests** — backoff advances on failure, resets on success, caps at max, degraded host without prior failures probes at base interval, config validation, snapshot includes `next_probe_at`.
9. **Config docs** — update `config/router.example.yaml` with the new fields documented and commented out.

Do not build:
- A kill-switch for backoff (unnecessary — `multiplier=1.0` = fixed interval).
- Probing healthy hosts (unchanged from D7 in prior spec).
- Cross-restart persistence (state is ephemeral, matches existing design).
- Health transition events or webhooks.
- A `/v1/pool` column in the existing CLI table for `next_probe_at` — the field is in the JSON snapshot; CLI formatting changes are a follow-up.
- Separate intervals per status tier (design decision D3 below).

## Design decisions

- **D1 — Backoff state lives in `HealthCheckTask` with an accessor for the snapshot.** Not on `UpstreamMetrics`. Health-check policy (how often to check) is a scheduling concern, not a metrics data-model concern. The task exposes a `get_next_probe_at(vm_name, upstream_name) -> float | None` that `MetricsCollector.snapshot()` can call during the snapshot lock. (Deferred: may switch to injection or callback if the accessor pattern causes threading issues.)

- **D2 — `backoff_base_seconds` defaults to `interval_seconds` (60.0), not a separate value.** Rationale: the operator already configured the base interval in `interval_seconds`. Reusing that value means one less knob. If they want a faster initial recovery check, they lower `interval_seconds`; the backoff grows from that base.

- **D3 — Single exponential curve, not per-status-tier intervals.** Rationale: a host that is `degraded` (partial errors) and a host that is `down` (all errors) are in the same `probe_statuses` set. The backoff grows by outcome (probe success vs. failure), not by static tier. This is simpler and targets the actual problem (failing hosts backing off) without adding config surface for hypothetical tier granularity.

- **D4 — `_probe_failures` counter is separate from `UpstreamMetrics.consecutive_failures`.** They measure different things: `_probe_failures` counts how many *probes* have failed in a row (for backoff), while `consecutive_failures` counts how many real-traffic or probe *attempts* have failed (for classify()). The probe-failure counter resets only on probe success, even if real traffic records a success in between. This prevents a single real-traffic hit from collapsing the backoff curve.

- **D5 — Backoff formula: `delay = min(base * multiplier^probe_failures, backoff_max_seconds)`.** Standard exponential backoff. `probe_failures=0` → base interval. After success: `probe_failures=0`, next probe at `now + base`. After failure: `probe_failures += 1`, next probe at `now + delay`. Capped at `backoff_max_seconds`.

- **D6 — `_run()` loop sleep adapts to the earliest-due probe.** Instead of a fixed sleep for `interval_seconds`, the loop computes `min(interval_seconds, time_to_next_due)` where `time_to_next_due` is the smallest `next_probe_at - now` across all upstreams that are in `probe_statuses`. This ensures a freshly-degraded host gets probed promptly even when another host is deep in backoff. If no probe is due, falls back to `interval_seconds` (so idle loops don't busy-spin).

## Component contract

### `config.py` — `HealthCheckConfig` additions

```python
interval_seconds: float = 60.0       # existing; unchanged
backoff_base_seconds: float = 60.0   # NEW — initial interval for a failing host
backoff_max_seconds: float = 1800.0  # NEW — cap after which we stop growing
backoff_multiplier: float = 2.0      # NEW — exponential growth factor
```

Frozen dataclass + Pydantic model (same pattern as existing fields).

Validation (added to `_validate_health_check_values`):
- `backoff_base_seconds >= 1.0`
- `backoff_max_seconds >= backoff_base_seconds`
- `backoff_multiplier >= 1.0`

### `service.py` — `HealthCheckTask` changes

**New state**:

```python
_next_probe_at: dict[ClientCacheKey, float]  # earliest timestamp the upstream may be probed again
_probe_failures: dict[ClientCacheKey, int]    # consecutive probe failures for backoff calc
```

**`_tick()` filter change**:

```python
# Before: if entry["status"] not in probe_statuses: continue
# After:
if entry["status"] not in probe_statuses:
    continue
cache_key = RichardRouter._client_cache_key(upstream)  # or access via router
if time.monotonic() < self._next_probe_at.get(cache_key, 0):
    continue
```

**`_probe_upstream()` — success path**:

```python
cache_key = self._router._client_cache_key(upstream)
self._probe_failures[cache_key] = 0
self._next_probe_at[cache_key] = self._router.clock() + self._config.backoff_base_seconds
```

**`_probe_upstream()` — failure path (any non-2xx result)**:

```python
cache_key = self._router._client_cache_key(upstream)
failures = self._probe_failures.get(cache_key, 0) + 1
self._probe_failures[cache_key] = failures
delay = min(
    self._config.backoff_base_seconds * (self._config.backoff_multiplier ** (failures - 1)),
    self._config.backoff_max_seconds,
)
self._next_probe_at[cache_key] = self._router.clock() + delay
```

Note: on the first failure (`failures=1`), `multiplier^0 = 1` → delay = `base`.

**`_run()` sleep adaption**:

```python
async def _run(self) -> None:
    config = self._config
    probe_statuses = set(config.probe_statuses)
    while not self._stop_event.is_set():
        try:
            await self._tick()
        except Exception:
            logger.warning("...", exc_info=True)
        # Sleep until the next probe is due, or interval_seconds, whichever is earlier.
        sleep_for = config.interval_seconds
        soonest = self._compute_soonest_probe()
        if soonest is not None:
            sleep_for = min(sleep_for, max(0.0, soonest - self._router.clock()))
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._stop_event.wait(), timeout=sleep_for)
```

**New helper**:

```python
def _compute_soonest_probe(self) -> float | None:
    """Return the earliest next_probe_at timestamp currently in the backoff table,
    or None if nothing is being tracked."""
    if not self._next_probe_at:
        return None
    return min(self._next_probe_at.values())
```

**Accessor for pool snapshot**:

```python
def get_next_probe_at(self, upstream_key: ClientCacheKey) -> float | None:
    return self._next_probe_at.get(upstream_key)
```

### `metrics.py` — `MetricsCollector.snapshot()` changes

The `MetricsSnapshot` entry for each upstream gains:

```python
"next_probe_at": _format_timestamp(task.get_next_probe_at(...)) if task else None,
```

`MetricsCollector` gains an optional `health_check_task: HealthCheckTask | None` parameter. Passed through from `create_app()`.

### `main.py` — wiring

Pass `metrics.health_check_task = hc_task` after construction.

### `config/router.example.yaml`

Add commented-out config block:

```yaml
# health_check:
#   enabled: false
#   interval_seconds: 60
#   # --- Decaying backoff (optional) ---
#   # The probe interval grows exponentially for persistently failing hosts.
#   # Set backoff_multiplier: 1.0 for fixed-interval behaviour.
#   backoff_base_seconds: 60      # Starting interval (same as interval_seconds by default)
#   backoff_max_seconds: 1800     # Cap at 30 minutes
#   backoff_multiplier: 2.0       # Double after each consecutive probe failure
#   probe_max_tokens: 1
#   probe_timeout_seconds: 10
#   probe_statuses: ["degraded", "down"]
```

## Tasks

1. **`config.py`** — Add `backoff_base_seconds`, `backoff_max_seconds`, `backoff_multiplier` to `HealthCheckConfig` + `HealthCheckConfigModel`. Thread through `_build_router_config()`. Add validation.
2. **`service.py`** — Add `_next_probe_at` and `_probe_failures` dicts to `HealthCheckTask`. Modify `_tick()` to filter by `next_probe_at`. Add backoff logic to `_probe_upstream()` success/failure paths. Add `_compute_soonest_probe()`. Adapt `_run()` sleep to soonest-due. Add `get_next_probe_at()` accessor.
3. **`metrics.py`** — Add optional `health_check_task` param to `MetricsCollector`. Include `next_probe_at` in snapshot entries.
4. **`main.py`** — Wire `hc_task` to `metrics.health_check_task`.
5. **`config/router.example.yaml`** — Document new fields commented out.
6. **`tests/test_health_check.py`** — Add tests:
   - `test_backoff_advances_on_failure` — consecutive probe failures increase delay.
   - `test_backoff_resets_on_success` — successful probe resets to base.
   - `test_backoff_caps_at_max` — delay doesn't exceed `backoff_max_seconds`.
   - `test_backoff_does_not_delay_first_degraded_probe` — freshly-degraded upstream with no prior failures probes at base interval.
   - `test_tick_skips_upstream_with_future_next_probe_at` — upstream in backoff is skipped.
   - `test_snapshot_includes_next_probe_at` — `/v1/pool` includes the field.
   - `test_backoff_config_validation` — invalid values rejected.
   - `test_backoff_defaults_match_current_behavior` — `multiplier=1.0` → fixed interval.
   - `test_soonest_probe_adapts_sleep` — `_run()` sleep is reduced when a probe is nearly due.

## Acceptance gate

- PR # + URL on `leonbreukelman/richard-router`.
- Implementation commit SHA and merge commit SHA on `main`.
- Branch lifecycle: pushed → merged → deleted.
- Changed-file list read from GitHub matches scope.
- CI check-run conclusion: `uv / ruff / pytest` green.
- `uv run pytest -v` — all tests pass (new and existing).
- `uv run ruff check .` — clean.
- `config/router.example.yaml` updated.
- No changes to `config/router.yaml` (protected path).
- Backward compatibility: existing tests pass unchanged.
- Self-certification evidence: spec conformance table, test coverage, edge-case review.

## Known boundaries and open items

- **Race with config changes**: backoff state is ephemeral; a restart resets it. If the operator changes `interval_seconds` while the server is running, old backoff state persists until next probe success/failure — acceptable for v1.
- **`_run()` sleep adapts but `stop_event.wait()` is still bounded**: the sleep adapts down to the soonest probe due, but never below 0. A tick may fire slightly before a probe is due. This is harmless — the probe is just skipped by the `next_probe_at` filter.
- **Accessor threading**: `MetricsCollector.snapshot()` holds `_lock`. If `get_next_probe_at()` is called inside the snapshot lock, and `HealthCheckTask` modifies `_next_probe_at` in a concurrent `_tick()`, there's no data race on CPython (GIL protects dict get/set) but the value may be stale by the time the snapshot is serialized. Acceptable — next probe time is advisory, not critical.
- **Not implemented (future scope)**: per-virtual-model probe payload, health transition notifications, per-backoff-curve tuning per upstream.

## References

- Existing 2026-07-17 spec: `docs/specs/2026-07-17-background-health-check.md`
- Existing decision: `docs/decisions/2026-07-18-half-open-requires-2xx.md`
- Existing verification: `docs/verification/2026-07-19-smactorio-issue-25-20260719t1.md`
