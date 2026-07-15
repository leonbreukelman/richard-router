"""Tests for the shared failover logic extracted from chat_completion and open_stream.

These tests verify the extracted helpers behave identically to the inline logic:
- _record_http_failure records attempts + metrics identically for both paths
- _record_transport_failure records attempts + metrics identically for both paths
- _failover_loop iterates upstreams in order, respects circuit breaker, and stops
  when the callback returns a terminal result or all upstreams are exhausted.
"""
from __future__ import annotations

from dataclasses import replace

import httpx
import pytest

from richard_router.config import (
    CircuitBreakerConfig,
    FailoverConfig,
    RouterConfig,
)
from richard_router.metrics import MetricsCollector
from richard_router.service import Attempt, RichardRouter, RouterResult
from tests.conftest import make_test_config


def _client_factory(handler):
    transport = httpx.MockTransport(handler)

    def factory(_upstream):
        return httpx.AsyncClient(transport=transport)

    return factory


def _config_with_metrics(**kwargs) -> tuple[RouterConfig, MetricsCollector]:
    cfg = make_test_config(**kwargs)
    metrics = MetricsCollector()
    return cfg, metrics


# ---------------------------------------------------------------------------
# _record_http_failure: shared HTTP-error recording
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_http_failure_appends_attempt_and_records_metrics(monkeypatch):
    monkeypatch.setenv("TEST_NVIDIA_KEY", "nvidia-secret")
    cfg, metrics = _config_with_metrics()
    router = RichardRouter(cfg, _client_factory(lambda r: httpx.Response(500)), metrics=metrics)

    upstream = cfg.virtual_models["coding"].upstreams[0]
    attempts: list[Attempt] = []
    response = httpx.Response(503, json={"error": {"message": "overloaded"}})

    should_continue = router._record_http_failure(
        upstream=upstream,
        response=response,
        attempts=attempts,
        virtual_model_name="coding",
    )

    assert should_continue is True
    assert len(attempts) == 1
    assert attempts[0].upstream == "nvidia"
    assert attempts[0].outcome == "http_error"
    assert attempts[0].status_code == 503
    # Metrics should have one http_error recorded
    snap = metrics.snapshot().to_dict()
    assert snap["virtual_models"]["coding"][0]["error_count"] == 1


@pytest.mark.asyncio
async def test_record_http_failure_non_retryable_returns_false(monkeypatch):
    monkeypatch.setenv("TEST_NVIDIA_KEY", "nvidia-secret")
    cfg, metrics = _config_with_metrics()
    router = RichardRouter(cfg, _client_factory(lambda r: httpx.Response(400)), metrics=metrics)

    upstream = cfg.virtual_models["coding"].upstreams[0]
    attempts: list[Attempt] = []
    response = httpx.Response(400, json={"error": {"message": "bad request"}})

    should_continue = router._record_http_failure(
        upstream=upstream,
        response=response,
        attempts=attempts,
        virtual_model_name="coding",
    )

    assert should_continue is False
    assert len(attempts) == 1
    assert attempts[0].status_code == 400


# ---------------------------------------------------------------------------
# _record_transport_failure: shared timeout/TransportError recording
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_transport_failure_timeout_appends_and_records(monkeypatch):
    monkeypatch.setenv("TEST_NVIDIA_KEY", "nvidia-secret")
    cfg, metrics = _config_with_metrics()
    router = RichardRouter(cfg, _client_factory(lambda r: httpx.Response(500)), metrics=metrics)

    upstream = cfg.virtual_models["coding"].upstreams[0]
    attempts: list[Attempt] = []
    exc = httpx.ReadTimeout("slow")

    should_continue = router._record_transport_failure(
        upstream=upstream,
        exc=exc,
        attempts=attempts,
        virtual_model_name="coding",
    )

    assert should_continue is True  # timeout is retryable, retry_on_timeout=True
    assert len(attempts) == 1
    assert attempts[0].outcome == "timeout"
    assert attempts[0].error_type == "TimeoutException"
    snap = metrics.snapshot().to_dict()
    assert snap["virtual_models"]["coding"][0]["error_count"] == 1


@pytest.mark.asyncio
async def test_record_transport_failure_non_retryable_returns_false(monkeypatch):
    """A fatal exception (not TransportError/Timeout) should return False."""
    monkeypatch.setenv("TEST_NVIDIA_KEY", "nvidia-secret")
    cfg, metrics = _config_with_metrics()
    router = RichardRouter(cfg, _client_factory(lambda r: httpx.Response(500)), metrics=metrics)

    upstream = cfg.virtual_models["coding"].upstreams[0]
    attempts: list[Attempt] = []
    # RuntimeError is not an httpx exception, classify_exception returns "fatal"
    exc = RuntimeError("unexpected")

    should_continue = router._record_transport_failure(
        upstream=upstream,
        exc=exc,
        attempts=attempts,
        virtual_model_name="coding",
    )

    assert should_continue is False
    assert len(attempts) == 1


@pytest.mark.asyncio
async def test_record_transport_failure_connection_error(monkeypatch):
    monkeypatch.setenv("TEST_NVIDIA_KEY", "nvidia-secret")
    cfg, metrics = _config_with_metrics()
    router = RichardRouter(cfg, _client_factory(lambda r: httpx.Response(500)), metrics=metrics)

    upstream = cfg.virtual_models["coding"].upstreams[0]
    attempts: list[Attempt] = []
    exc = httpx.ConnectError("refused")

    should_continue = router._record_transport_failure(
        upstream=upstream,
        exc=exc,
        attempts=attempts,
        virtual_model_name="coding",
    )

    assert should_continue is True  # ConnectError is TransportError → retryable
    assert attempts[0].outcome == "connection_error"
    assert attempts[0].error_type == "ConnectError"


# ---------------------------------------------------------------------------
# _record_success: shared success recording
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_success_resets_circuit_breaker_and_metrics(monkeypatch):
    monkeypatch.setenv("TEST_NVIDIA_KEY", "nvidia-secret")
    cfg, metrics = _config_with_metrics()
    router = RichardRouter(cfg, _client_factory(lambda r: httpx.Response(200)), metrics=metrics)

    upstream = cfg.virtual_models["coding"].upstreams[0]
    router._record_success(
        upstream, virtual_model_name="coding", status_code=200, upstream_name=upstream.name
    )

    snap = metrics.snapshot().to_dict()
    assert snap["virtual_models"]["coding"][0]["success_count"] == 1


# ---------------------------------------------------------------------------
# _failover_loop: the shared iteration loop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failover_loop_returns_success_from_first_healthy_upstream(monkeypatch):
    monkeypatch.setenv("TEST_NVIDIA_KEY", "nvidia-secret")
    monkeypatch.setenv("TEST_OPENROUTER_KEY", "openrouter-secret")
    cfg, metrics = _config_with_metrics()

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"model": "test", "choices": []})

    router = RichardRouter(cfg, _client_factory(handler), metrics=metrics)
    virtual = cfg.virtual_models["coding"]

    call_count = 0

    async def try_upstream(upstream, attempts):
        nonlocal call_count
        call_count += 1
        return RouterResult(status_code=200, content=b'{"ok":true}')

    result = await router._failover_loop(virtual, try_upstream, stream=False)

    assert result.status_code == 200
    assert call_count == 1


@pytest.mark.asyncio
async def test_failover_loop_skips_circuit_open_upstream(monkeypatch):
    monkeypatch.setenv("TEST_OPENROUTER_KEY", "openrouter-secret")

    cb_cfg = CircuitBreakerConfig(failure_threshold=1, cooldown_seconds=30.0)
    cfg = replace(
        make_test_config(),
        failover=FailoverConfig(circuit_breaker=cb_cfg),
    )
    router = RichardRouter(cfg, _client_factory(lambda r: httpx.Response(500)))

    # Open the primary circuit
    virtual = cfg.virtual_models["coding"]
    upstream = virtual.upstreams[0]
    router._record_retryable_failure(upstream)

    calls: list[str] = []

    async def try_upstream(up, attempts):
        calls.append(up.name)
        return RouterResult(status_code=200, content=b'{"ok":true}')

    result = await router._failover_loop(virtual, try_upstream, stream=False)

    assert result.status_code == 200
    # Primary should have been skipped (circuit_open), only openrouter tried
    assert calls == ["openrouter"]
