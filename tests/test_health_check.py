from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from richard_router.config import (
    FailoverConfig,
    HealthCheckConfig,
    ObservabilityConfig,
    RouterConfig,
    Upstream,
    VirtualModel,
)
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


# ── Task 4: Lifecycle wiring ────────────────────────────────────────────────


class TestHealthCheckLifecycle:
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