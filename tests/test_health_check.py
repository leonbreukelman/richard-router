from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from richard_router.config import (
    FailoverConfig,
    HealthCheckConfig,
    ObservabilityConfig,
    RouterConfig,
    Upstream,
    VirtualModel,
)
from richard_router.main import create_app
from richard_router.metrics import MetricsCollector, UpstreamMetrics
from richard_router.service import HealthCheckTask, RichardRouter

# ── helpers ──────────────────────────────────────────────────────────────────


def _make_config(
    health_enabled: bool = False,
    **hc_overrides: object,
) -> RouterConfig:
    """Build a RouterConfig with optional health-check overrides."""
    hc_defaults = dict(
        enabled=health_enabled,
        interval_seconds=60.0,
        probe_max_tokens=1,
        probe_timeout_seconds=10.0,
        probe_statuses=("degraded", "down"),
    )
    hc_defaults.update(hc_overrides)
    return RouterConfig(
        virtual_models={
            "coding": VirtualModel(
                name="coding",
                upstreams=(
                    Upstream(
                        name="nvidia",
                        base_url="https://nvidia.test/v1",
                        model="nvidia/model",
                        api_key_env="TEST_NVIDIA_KEY",
                    ),
                    Upstream(
                        name="openrouter",
                        base_url="https://openrouter.test/v1",
                        model="openrouter/model",
                        api_key_env="TEST_OPENROUTER_KEY",
                    ),
                ),
            ),
        },
        failover=FailoverConfig(),
        observability=ObservabilityConfig(expose_upstream_header=True),
        health_check=HealthCheckConfig(**hc_defaults),  # type: ignore[arg-type]
    )


def _error_metrics() -> UpstreamMetrics:
    """Return a metrics object with recorded failures."""
    m = UpstreamMetrics()
    m.record("http_error", 503, "TimeoutException", "upstream busy")
    m.record("http_error", 503, "TimeoutException", "upstream busy")
    m.record("http_error", 503, "TimeoutException", "upstream busy")
    assert m.consecutive_failures == 3
    assert m.last_error_message == "upstream busy"
    assert m.errors_by_code == {503: 3}
    assert m.errors_by_type == {"TimeoutException": 3}
    return m


# ── Task 1: Error-clearing fix ──────────────────────────────────────────────


class TestErrorClearing:
    def test_success_clears_error_state(self):
        """A success after failures clears last_error_message and error dicts."""
        m = _error_metrics()

        m.record("success", 200, None)

        assert m.last_error_message is None
        assert m.errors_by_code == {}
        assert m.errors_by_type == {}
        assert m.consecutive_failures == 0

    def test_success_does_not_clear_unrelated_state(self):
        """Success preserves total_requests and increments success_count."""
        m = _error_metrics()
        before_total = m.total_requests

        m.record("success", 200, None)

        assert m.total_requests == before_total + 1
        assert m.success_count == 1

    def test_non_2xx_outcome_does_not_clear_errors(self):
        """A non-retryable error (e.g. 400) does NOT clear error state."""
        m = _error_metrics()
        m.record("http_error", 400, None, error_message="bad request")

        assert m.last_error_message == "bad request"
        assert 400 in m.errors_by_code

    def test_consecutive_successes_keep_state_clean(self):
        """Multiple successes keep error state clear."""
        m = _error_metrics()
        m.record("success", 200, None)
        m.record("success", 200, None)

        assert m.last_error_message is None
        assert m.errors_by_code == {}
        assert m.errors_by_type == {}


# ── Task 2: Health check config validation ──────────────────────────────────


class TestHealthCheckConfigValidation:
    def test_health_check_defaults(self):
        """Default health_check config has safe values."""
        cfg = _make_config()
        hc = cfg.health_check
        assert hc.enabled is False
        assert hc.interval_seconds == 60.0
        assert hc.probe_max_tokens == 1
        assert hc.probe_timeout_seconds == 10.0
        assert hc.probe_statuses == ("degraded", "down")

    def test_health_check_explicit_enable(self):
        """Setting enabled=true works."""
        cfg = _make_config(health_enabled=True)
        assert cfg.health_check.enabled is True


# ── Task 3: HealthCheckTask tick logic ──────────────────────────────────────


class TestHealthCheckTaskTick:
    @pytest.mark.asyncio
    async def test_tick_skips_healthy_member(self):
        """A healthy upstream is NOT probed."""
        cfg = _make_config(health_enabled=True)
        metrics = MetricsCollector()
        router = RichardRouter(cfg, metrics=metrics)
        task = HealthCheckTask(router, cfg.health_check, metrics)

        with (
            patch.object(router, "_client_for") as mock_client_factory,
        ):
            await task._tick()

        mock_client_factory.assert_not_called()

    @pytest.mark.asyncio
    async def test_tick_probes_degraded_member(self):
        """A degraded upstream IS probed."""
        cfg = _make_config(health_enabled=True)
        metrics = MetricsCollector()
        router = RichardRouter(cfg, metrics=metrics)

        # Record failures to push it to degraded
        for _ in range(3):
            metrics.record_attempt("coding", "nvidia", "http_error", 503, "TimeoutException")
        assert metrics.snapshot().virtual_models["coding"][0]["status"] == "degraded"

        task = HealthCheckTask(router, cfg.health_check, metrics)

        fake_client = AsyncMock()
        fake_client.post = AsyncMock(return_value=httpx.Response(200, json={"id": "ok"}))
        with (
            patch.object(router, "_client_for", return_value=fake_client),
        ):
            await task._tick()

        fake_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_tick_probes_down_member(self):
        """A 'down' upstream is probed."""
        cfg = _make_config(health_enabled=True)
        metrics = MetricsCollector()
        router = RichardRouter(cfg, metrics=metrics)

        for _ in range(5):
            metrics.record_attempt("coding", "nvidia", "http_error", 503, "TimeoutException")
        assert metrics.snapshot().virtual_models["coding"][0]["status"] == "down"

        task = HealthCheckTask(router, cfg.health_check, metrics)

        fake_client = AsyncMock()
        fake_client.post = AsyncMock(return_value=httpx.Response(200, json={"id": "ok"}))
        with patch.object(router, "_client_for", return_value=fake_client):
            await task._tick()

        fake_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_tick_skips_member_not_in_probe_statuses(self):
        """A degraded member is NOT probed when probe_statuses is only ['down']."""
        cfg = _make_config(health_enabled=True, probe_statuses=("down",))
        metrics = MetricsCollector()
        router = RichardRouter(cfg, metrics=metrics)

        for _ in range(3):
            metrics.record_attempt("coding", "nvidia", "http_error", 503, "TimeoutException")
        assert metrics.snapshot().virtual_models["coding"][0]["status"] == "degraded"

        task = HealthCheckTask(router, cfg.health_check, metrics)

        with patch.object(router, "_client_for") as mock_client_factory:
            await task._tick()

        mock_client_factory.assert_not_called()

    @pytest.mark.asyncio
    async def test_probe_success_records_metric_and_resets_circuit(self):
        """A successful probe records a success metric and resets the circuit breaker."""
        cfg = _make_config(health_enabled=True)
        metrics = MetricsCollector()
        router = RichardRouter(cfg, metrics=metrics)

        for _ in range(5):
            metrics.record_attempt("coding", "nvidia", "http_error", 503, "TimeoutException")
            router._record_retryable_failure(
                next(u for u in cfg.virtual_models["coding"].upstreams if u.name == "nvidia")
            )

        task = HealthCheckTask(router, cfg.health_check, metrics)
        nvidia_upstream = next(
            u for u in cfg.virtual_models["coding"].upstreams if u.name == "nvidia"
        )

        # Verify circuit IS open (default threshold is 5)
        breaker = router._circuit_breaker_state(nvidia_upstream)
        assert breaker.opened_at is not None

        fake_client = AsyncMock()
        fake_client.post = AsyncMock(return_value=httpx.Response(200, json={"id": "ok"}))
        with patch.object(router, "_client_for", return_value=fake_client):
            await task._tick()

        # Circuit should be reset
        assert breaker.opened_at is None

        # Metrics should show cleared errors (but still degraded due to rolling window)
        snap = metrics.snapshot()
        nvidia_entry = snap.virtual_models["coding"][0]
        assert nvidia_entry["last_error_message"] is None
        assert nvidia_entry["errors_by_code"] == {}

    @pytest.mark.asyncio
    async def test_probe_failure_records_error(self):
        """A probe that gets 503 records a failure."""
        cfg = _make_config(health_enabled=True)
        metrics = MetricsCollector()
        router = RichardRouter(cfg, metrics=metrics)

        for _ in range(3):
            metrics.record_attempt("coding", "nvidia", "http_error", 503, "TimeoutException")

        task = HealthCheckTask(router, cfg.health_check, metrics)

        fake_client = AsyncMock()
        fake_client.post = AsyncMock(
            return_value=httpx.Response(503, json={"error": {"message": "still down"}})
        )
        with patch.object(router, "_client_for", return_value=fake_client):
            await task._tick()

        snap = metrics.snapshot()
        nvidia_entry = snap.virtual_models["coding"][0]
        assert nvidia_entry["consecutive_failures"] >= 4

    @pytest.mark.asyncio
    async def test_probe_failure_redacts_secrets_but_preserves_error_context(self):
        cfg = _make_config(health_enabled=True)
        metrics = MetricsCollector()
        router = RichardRouter(cfg, metrics=metrics)

        for _ in range(3):
            metrics.record_attempt("coding", "nvidia", "http_error", 503, "TimeoutException")

        secret = "sk-" + "healthchecksecret" * 2
        error_message = f"provider health probe rejected api_key={secret}; service unavailable"
        fake_client = AsyncMock()
        fake_client.post = AsyncMock(
            return_value=httpx.Response(503, json={"error": {"message": error_message}})
        )
        task = HealthCheckTask(router, cfg.health_check, metrics)

        with patch.object(router, "_client_for", return_value=fake_client):
            await task._tick()

        stored_message = metrics.snapshot().virtual_models["coding"][0]["last_error_message"]
        assert secret not in stored_message
        assert "[REDACTED]" in stored_message
        assert "provider health probe rejected" in stored_message
        assert "service unavailable" in stored_message

    @pytest.mark.asyncio
    async def test_probe_400_does_not_record_failure(self):
        """A non-retryable HTTP error (400) does NOT increment consecutive_failures."""
        cfg = _make_config(health_enabled=True)
        metrics = MetricsCollector()
        router = RichardRouter(cfg, metrics=metrics)

        for _ in range(3):
            metrics.record_attempt("coding", "nvidia", "http_error", 503, "TimeoutException")

        task = HealthCheckTask(router, cfg.health_check, metrics)
        nvidia_upstream = next(
            u for u in cfg.virtual_models["coding"].upstreams if u.name == "nvidia"
        )

        fake_client = AsyncMock()
        fake_client.post = AsyncMock(
            return_value=httpx.Response(400, json={"error": {"message": "bad"}})
        )
        with patch.object(router, "_client_for", return_value=fake_client):
            await task._tick()

        # 400 is non-retryable — should NOT increment the breaker's consecutive_failures
        breaker = router._circuit_breaker_state(nvidia_upstream)
        assert breaker.consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_probe_400_against_open_breaker_keeps_it_open(self):
        """A 400 health-check probe against an already-open breaker does not close it.

        Policy (docs/decisions/2026-07-18-half-open-requires-2xx.md): only a
        2xx probe closes a half-open circuit.  A 400 proves the upstream
        answered, not that the prior 5xx condition recovered, so the
        breaker must remain open with cooldown re-armed.
        """
        cfg = _make_config(health_enabled=True)
        metrics = MetricsCollector()

        class FixedClock:
            def __init__(self) -> None:
                self.now = 1_000.0

            def __call__(self) -> float:
                return self.now

        clock = FixedClock()
        router = RichardRouter(cfg, metrics=metrics, clock=clock)

        nvidia_upstream = next(
            u for u in cfg.virtual_models["coding"].upstreams if u.name == "nvidia"
        )

        # Force the breaker into the open state as if a prior 5xx storm opened it.
        breaker = router._circuit_breaker_state(nvidia_upstream)
        breaker.opened_at = clock.now - 1.0
        breaker.consecutive_failures = cfg.failover.circuit_breaker.failure_threshold
        breaker.half_open_probes = 0

        task = HealthCheckTask(router, cfg.health_check, metrics)
        # Force metrics to mark nvidia as needing a probe.
        metrics.record_attempt("coding", "nvidia", "http_error", 503, "TimeoutException")

        fake_client = AsyncMock()
        fake_client.post = AsyncMock(
            return_value=httpx.Response(400, json={"error": {"message": "bad probe"}})
        )
        # Advance the clock so the probe fires as a genuine half-open attempt.
        clock.now += cfg.failover.circuit_breaker.cooldown_seconds + 1.0
        with patch.object(router, "_client_for", return_value=fake_client):
            await task._tick()

        # Breaker must remain open; opened_at re-armed to the current clock.
        assert breaker.opened_at is not None
        assert breaker.opened_at == clock.now
        # half_open_probes reset so the next post-cooldown request is again a probe.
        assert breaker.half_open_probes == 0
        # consecutive_failures untouched by non-retryable 4xx.
        assert breaker.consecutive_failures == cfg.failover.circuit_breaker.failure_threshold

    @pytest.mark.asyncio
    async def test_task_reschedules_after_tick_exception(self):
        """An exception in _tick doesn't crash the task."""
        cfg = _make_config(health_enabled=True)
        metrics = MetricsCollector()
        router = RichardRouter(cfg, metrics=metrics)
        task = HealthCheckTask(router, cfg.health_check, metrics)

        # Force _tick to raise
        with patch.object(task, "_tick", side_effect=RuntimeError("boom")):
            # _run catches the exception and continues
            task.start()
            await asyncio.sleep(0.05)
            # Should still be alive (not cancelled/failed)
            assert task._task is not None and not task._task.done()
            await task.stop()

    @pytest.mark.asyncio
    async def test_probe_timeout_records_timeout_metric(self):
        """A timeout during probe records a timeout metric."""
        cfg = _make_config(health_enabled=True)
        metrics = MetricsCollector()
        router = RichardRouter(cfg, metrics=metrics)

        for _ in range(3):
            metrics.record_attempt("coding", "nvidia", "http_error", 503, "TimeoutException")

        task = HealthCheckTask(router, cfg.health_check, metrics)

        fake_client = AsyncMock()
        fake_client.post = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
        with patch.object(router, "_client_for", return_value=fake_client):
            await task._tick()

        snap = metrics.snapshot()
        nvidia_entry = snap.virtual_models["coding"][0]
        assert "TimeoutException" in nvidia_entry["errors_by_type"]
        assert nvidia_entry["error_count"] >= 4


# ── Task 3b: Decaying backoff (see docs/specs/2026-07-20-decaying-health-check.md) ─


class _FixedClock:
    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


class TestHealthCheckBackoff:
    """Per-upstream exponential backoff for the health-check probe schedule."""

    @pytest.mark.asyncio
    async def test_backoff_advances_on_failure(self):
        """Each consecutive probe failure grows the next_probe_at delay."""
        cfg = _make_config(
            health_enabled=True,
            backoff_base_seconds=60.0,
            backoff_max_seconds=1800.0,
            backoff_multiplier=2.0,
        )
        metrics = MetricsCollector()
        clock = _FixedClock()
        router = RichardRouter(cfg, metrics=metrics, clock=clock)
        nvidia_upstream = next(
            u for u in cfg.virtual_models["coding"].upstreams if u.name == "nvidia"
        )

        for _ in range(3):
            metrics.record_attempt("coding", "nvidia", "http_error", 503, "TimeoutException")

        task = HealthCheckTask(router, cfg.health_check, metrics)
        key = (nvidia_upstream.name, nvidia_upstream.base_url, nvidia_upstream.model)
        fake_client = AsyncMock()
        fake_client.post = AsyncMock(
            return_value=httpx.Response(503, json={"error": {"message": "down"}})
        )

        # First failed probe: probe_failures 0 → 1, delay = 60 * 2**0 = 60.
        with patch.object(router, "_client_for", return_value=fake_client):
            await task._tick()
        assert task._probe_failures[key] == 1
        assert task.get_next_probe_at(nvidia_upstream) == clock.now + 60.0

        # Second failed probe: probe_failures 1 → 2, delay = 60 * 2**1 = 120.
        clock.now += 60.0
        with patch.object(router, "_client_for", return_value=fake_client):
            await task._tick()
        assert task._probe_failures[key] == 2
        assert task.get_next_probe_at(nvidia_upstream) == clock.now + 120.0

    @pytest.mark.asyncio
    async def test_backoff_resets_on_success(self):
        """A successful probe collapses the curve back to the base interval."""
        cfg = _make_config(
            health_enabled=True,
            backoff_base_seconds=60.0,
            backoff_max_seconds=1800.0,
            backoff_multiplier=2.0,
        )
        metrics = MetricsCollector()
        clock = _FixedClock()
        router = RichardRouter(cfg, metrics=metrics, clock=clock)
        nvidia_upstream = next(
            u for u in cfg.virtual_models["coding"].upstreams if u.name == "nvidia"
        )

        for _ in range(3):
            metrics.record_attempt("coding", "nvidia", "http_error", 503, "TimeoutException")

        task = HealthCheckTask(router, cfg.health_check, metrics)
        key = (nvidia_upstream.name, nvidia_upstream.base_url, nvidia_upstream.model)

        fail_client = AsyncMock()
        fail_client.post = AsyncMock(
            return_value=httpx.Response(503, json={"error": {"message": "down"}})
        )
        ok_client = AsyncMock()
        ok_client.post = AsyncMock(return_value=httpx.Response(200, json={"id": "ok"}))

        # Drive two failures to grow the backoff curve.
        with patch.object(router, "_client_for", return_value=fail_client):
            await task._tick()
        clock.now += 60.0
        with patch.object(router, "_client_for", return_value=fail_client):
            await task._tick()
        assert task._probe_failures[key] == 2

        # Success: probe_failures resets to 0; next probe due at now + base.
        clock.now += 120.0
        with patch.object(router, "_client_for", return_value=ok_client):
            await task._tick()
        assert task._probe_failures[key] == 0
        assert task.get_next_probe_at(nvidia_upstream) == clock.now + 60.0

    @pytest.mark.asyncio
    async def test_backoff_caps_at_max(self):
        """Delay never exceeds backoff_max_seconds, no matter how many failures."""
        cfg = _make_config(
            health_enabled=True,
            backoff_base_seconds=10.0,
            backoff_max_seconds=30.0,  # small cap so we can hit it in 2 failures
            backoff_multiplier=2.0,
        )
        metrics = MetricsCollector()
        clock = _FixedClock()
        router = RichardRouter(cfg, metrics=metrics, clock=clock)
        nvidia_upstream = next(
            u for u in cfg.virtual_models["coding"].upstreams if u.name == "nvidia"
        )

        for _ in range(3):
            metrics.record_attempt("coding", "nvidia", "http_error", 503, "TimeoutException")

        task = HealthCheckTask(router, cfg.health_check, metrics)
        fail_client = AsyncMock()
        fail_client.post = AsyncMock(
            return_value=httpx.Response(503, json={"error": {"message": "down"}})
        )

        # Failure 1: delay = 10 * 2**0 = 10 (under cap).
        with patch.object(router, "_client_for", return_value=fail_client):
            await task._tick()
        assert task.get_next_probe_at(nvidia_upstream) == clock.now + 10.0

        # Advance and fail again: delay = 10 * 2**1 = 20 (under cap).
        clock.now += 10.0
        with patch.object(router, "_client_for", return_value=fail_client):
            await task._tick()
        assert task.get_next_probe_at(nvidia_upstream) == clock.now + 20.0

        # Advance and fail a third time: delay would be 10 * 2**2 = 40, capped at 30.
        clock.now += 20.0
        with patch.object(router, "_client_for", return_value=fail_client):
            await task._tick()
        assert task.get_next_probe_at(nvidia_upstream) == clock.now + 30.0

    @pytest.mark.asyncio
    async def test_backoff_does_not_delay_first_degraded_probe(self):
        """A freshly-degraded upstream with no prior probe history probes immediately."""
        cfg = _make_config(
            health_enabled=True,
            backoff_base_seconds=60.0,
            backoff_max_seconds=1800.0,
            backoff_multiplier=2.0,
        )
        metrics = MetricsCollector()
        clock = _FixedClock()
        router = RichardRouter(cfg, metrics=metrics, clock=clock)
        nvidia_upstream = next(
            u for u in cfg.virtual_models["coding"].upstreams if u.name == "nvidia"
        )

        # Three real-traffic failures → degraded. No prior probe history.
        for _ in range(3):
            metrics.record_attempt("coding", "nvidia", "http_error", 503, "TimeoutException")

        task = HealthCheckTask(router, cfg.health_check, metrics)
        # next_probe_at starts empty, so the _tick filter passes immediately.
        assert task.get_next_probe_at(nvidia_upstream) is None

        fake_client = AsyncMock()
        fake_client.post = AsyncMock(return_value=httpx.Response(503, json={"error": {}}))
        with patch.object(router, "_client_for", return_value=fake_client):
            await task._tick()

        # Probe happened; backoff schedule is now set but the first probe was not held.
        assert task.get_next_probe_at(nvidia_upstream) is not None
        assert fake_client.post.call_count == 1

    @pytest.mark.asyncio
    async def test_tick_skips_upstream_with_future_next_probe_at(self):
        """An upstream in its backoff window is NOT probed on subsequent ticks."""
        cfg = _make_config(
            health_enabled=True,
            backoff_base_seconds=60.0,
            backoff_max_seconds=1800.0,
            backoff_multiplier=2.0,
        )
        metrics = MetricsCollector()
        clock = _FixedClock()
        router = RichardRouter(cfg, metrics=metrics, clock=clock)

        for _ in range(3):
            metrics.record_attempt("coding", "nvidia", "http_error", 503, "TimeoutException")

        task = HealthCheckTask(router, cfg.health_check, metrics)
        fake_client = AsyncMock()
        fake_client.post = AsyncMock(
            return_value=httpx.Response(503, json={"error": {"message": "down"}})
        )

        # First probe fails; next_probe_at is now + 60.
        with patch.object(router, "_client_for", return_value=fake_client):
            await task._tick()
        assert fake_client.post.call_count == 1

        # Advance the clock 30s — short of the 60s backoff window. Tick should skip.
        clock.now += 30.0
        with patch.object(router, "_client_for", return_value=fake_client):
            await task._tick()
        assert fake_client.post.call_count == 1  # unchanged

        # Advance past the backoff window. Tick should probe again.
        clock.now += 31.0
        with patch.object(router, "_client_for", return_value=fake_client):
            await task._tick()
        assert fake_client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_snapshot_includes_next_probe_at(self):
        """The /v1/pool snapshot surfaces next_probe_at for monitored upstreams."""
        cfg = _make_config(
            health_enabled=True,
            backoff_base_seconds=60.0,
            backoff_max_seconds=1800.0,
            backoff_multiplier=2.0,
        )
        metrics = MetricsCollector()
        clock = _FixedClock()
        router = RichardRouter(cfg, metrics=metrics, clock=clock)
        # Wire the back-reference the way main.py does.
        task = HealthCheckTask(router, cfg.health_check, metrics)
        metrics.health_check_task = task

        for _ in range(3):
            metrics.record_attempt("coding", "nvidia", "http_error", 503, "TimeoutException")
        # Record one successful real-traffic attempt so openrouter appears in the
        # snapshot; otherwise the snapshot only lists upstreams that have activity.
        metrics.record_attempt("coding", "openrouter", "success", 200)

        fail_client = AsyncMock()
        fail_client.post = AsyncMock(
            return_value=httpx.Response(503, json={"error": {"message": "down"}})
        )
        with patch.object(router, "_client_for", return_value=fail_client):
            await task._tick()

        snap = metrics.snapshot()
        nvidia_entry = next(
            e for e in snap.virtual_models["coding"] if e["name"] == "nvidia"
        )
        assert nvidia_entry["next_probe_at"] is not None
        # openrouter recorded real traffic but was never probed → its next_probe_at
        # should be None (not yet tracked in the backoff table).
        openrouter_entry = next(
            e for e in snap.virtual_models["coding"] if e["name"] == "openrouter"
        )
        assert openrouter_entry.get("next_probe_at") is None


# ── Task 4: Lifecycle wiring ────────────────────────────────────────────────


class TestHealthCheckLifecycle:
    def test_enabled_app_can_be_constructed_without_running_event_loop(self):
        """App construction defers starting the task until ASGI lifespan startup."""
        app = create_app(_make_config(health_enabled=True))

        task = app.state.health_check_task
        assert isinstance(task, HealthCheckTask)
        assert task._task is None

    def test_app_lifespan_starts_and_stops_enabled_task(self):
        app = create_app(_make_config(health_enabled=True))
        task = app.state.health_check_task

        with TestClient(app):
            assert task._task is not None
            assert not task._task.done()

        assert task._task is None

    def test_disabled_app_creates_no_health_check_task(self):
        app = create_app(_make_config(health_enabled=False))

        assert app.state.health_check_task is None
        with TestClient(app):
            assert app.state.health_check_task is None

    @pytest.mark.asyncio
    async def test_task_starts_when_enabled(self):
        """Start creates an asyncio task."""
        cfg = _make_config(health_enabled=True)
        metrics = MetricsCollector()
        router = RichardRouter(cfg, metrics=metrics)
        task = HealthCheckTask(router, cfg.health_check, metrics)

        task.start()
        assert task._task is not None
        assert not task._task.done()
        await task.stop()

    @pytest.mark.asyncio
    async def test_task_not_started_when_disabled(self):
        """When disabled, no task is created."""
        cfg = _make_config(health_enabled=False)
        metrics = MetricsCollector()
        router = RichardRouter(cfg, metrics=metrics)
        task = HealthCheckTask(router, cfg.health_check, metrics)

        assert task._task is None

    @pytest.mark.asyncio
    async def test_start_stop_cycle(self):
        """Start then stop cleans up the task."""
        cfg = _make_config(health_enabled=True)
        metrics = MetricsCollector()
        router = RichardRouter(cfg, metrics=metrics)
        task = HealthCheckTask(router, cfg.health_check, metrics)

        task.start()
        assert task._task is not None and not task._task.done()
        await task.stop()
        assert task._task is None

    @pytest.mark.asyncio
    async def test_idempotent_stop(self):
        """Calling stop twice is safe."""
        cfg = _make_config(health_enabled=True)
        metrics = MetricsCollector()
        router = RichardRouter(cfg, metrics=metrics)
        task = HealthCheckTask(router, cfg.health_check, metrics)

        task.start()
        await task.stop()
        await task.stop()  # second call should not raise
        assert task._task is None


# Need asyncio for the exception tests
import asyncio  # noqa: E402 — used in test_task_reschedules_after_tick_exception