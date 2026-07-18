from __future__ import annotations

import json
from dataclasses import replace

import httpx
import pytest

from richard_router.config import CircuitBreakerConfig, FailoverConfig
from richard_router.service import RichardRouter, RouterStream
from tests.conftest import make_test_config


class ManualClock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _config_with_breaker(
    *,
    enabled: bool = True,
    failure_threshold: int = 2,
    cooldown_seconds: float = 30.0,
    half_open_max_probes: int = 1,
    retry_on_status: tuple[int, ...] | None = None,
):
    return replace(
        make_test_config(),
        failover=FailoverConfig(
            retry_on_status=retry_on_status,
            circuit_breaker=CircuitBreakerConfig(
                enabled=enabled,
                failure_threshold=failure_threshold,
                cooldown_seconds=cooldown_seconds,
                half_open_max_probes=half_open_max_probes,
            )
        ),
    )


def _json_success(model: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "model": model,
            "choices": [
                {
                    "message": {"role": "assistant", "content": "ok"},
                    "finish_reason": "stop",
                    "index": 0,
                }
            ],
        },
    )


def _client_factory(handler):
    transport = httpx.MockTransport(handler)

    def factory(_upstream):
        return httpx.AsyncClient(transport=transport)

    return factory


@pytest.mark.asyncio
async def test_circuit_breaker_skips_open_primary_until_cooldown():
    clock = ManualClock()
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        calls.append(model)
        if model == "nvidia-real-model":
            return httpx.Response(503, json={"error": {"message": "overloaded"}})
        return _json_success(model)

    router = RichardRouter(
        _config_with_breaker(failure_threshold=2, cooldown_seconds=30.0),
        _client_factory(handler),
        clock=clock,
    )

    first = await router.chat_completion({"model": "coding", "messages": []})
    second = await router.chat_completion({"model": "coding", "messages": []})
    third = await router.chat_completion({"model": "coding", "messages": []})

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 200
    assert third.headers["x-richard-router-upstream"] == "openrouter"
    assert calls == [
        "nvidia-real-model",
        "openrouter-real-model",
        "nvidia-real-model",
        "openrouter-real-model",
        "openrouter-real-model",
    ]


@pytest.mark.asyncio
async def test_circuit_breaker_allows_half_open_probe_and_resets_on_success():
    clock = ManualClock()
    primary_fails = True
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        calls.append(model)
        if model == "nvidia-real-model" and primary_fails:
            return httpx.Response(503, json={"error": {"message": "overloaded"}})
        return _json_success(model)

    router = RichardRouter(
        _config_with_breaker(failure_threshold=1, cooldown_seconds=30.0),
        _client_factory(handler),
        clock=clock,
    )

    opened = await router.chat_completion({"model": "coding", "messages": []})
    skipped = await router.chat_completion({"model": "coding", "messages": []})

    primary_fails = False
    clock.advance(31.0)
    probe = await router.chat_completion({"model": "coding", "messages": []})
    closed_again = await router.chat_completion({"model": "coding", "messages": []})

    assert opened.headers["x-richard-router-upstream"] == "openrouter"
    assert skipped.headers["x-richard-router-upstream"] == "openrouter"
    assert probe.headers["x-richard-router-upstream"] == "nvidia"
    assert closed_again.headers["x-richard-router-upstream"] == "nvidia"
    assert calls == [
        "nvidia-real-model",
        "openrouter-real-model",
        "openrouter-real-model",
        "nvidia-real-model",
        "nvidia-real-model",
    ]


@pytest.mark.asyncio
async def test_caller_error_does_not_open_circuit_breaker():
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400, json={"error": {"message": "bad request"}})

    router = RichardRouter(
        _config_with_breaker(failure_threshold=1),
        _client_factory(handler),
    )

    first = await router.chat_completion({"model": "coding", "messages": []})
    second = await router.chat_completion({"model": "coding", "messages": []})

    assert first.status_code == 400
    assert second.status_code == 400
    assert calls == 2


@pytest.mark.asyncio
async def test_non_retryable_response_resets_consecutive_failures():
    primary_statuses = [503, 400, 503, 503]
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        calls.append(model)
        if model == "nvidia-real-model":
            status = primary_statuses.pop(0)
            return httpx.Response(status, json={"error": {"message": "primary response"}})
        return _json_success(model)

    router = RichardRouter(
        _config_with_breaker(failure_threshold=2),
        _client_factory(handler),
    )

    first = await router.chat_completion({"model": "coding", "messages": []})
    caller_error = await router.chat_completion({"model": "coding", "messages": []})
    second_failure = await router.chat_completion({"model": "coding", "messages": []})
    third_failure = await router.chat_completion({"model": "coding", "messages": []})

    assert first.headers["x-richard-router-upstream"] == "openrouter"
    assert caller_error.status_code == 400
    assert second_failure.headers["x-richard-router-upstream"] == "openrouter"
    assert third_failure.headers["x-richard-router-upstream"] == "openrouter"
    assert calls == [
        "nvidia-real-model",
        "openrouter-real-model",
        "nvidia-real-model",
        "nvidia-real-model",
        "openrouter-real-model",
        "nvidia-real-model",
        "openrouter-real-model",
    ]


@pytest.mark.asyncio
async def test_half_open_non_retryable_response_closes_breaker():
    clock = ManualClock()
    primary_statuses = [503, 400, 400]
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        calls.append(model)
        if model == "nvidia-real-model":
            status = primary_statuses.pop(0)
            return httpx.Response(status, json={"error": {"message": "primary response"}})
        return _json_success(model)

    router = RichardRouter(
        _config_with_breaker(failure_threshold=1, cooldown_seconds=30.0),
        _client_factory(handler),
        clock=clock,
    )

    opened = await router.chat_completion({"model": "coding", "messages": []})
    skipped = await router.chat_completion({"model": "coding", "messages": []})
    clock.advance(31.0)
    probe = await router.chat_completion({"model": "coding", "messages": []})
    closed_again = await router.chat_completion({"model": "coding", "messages": []})

    assert opened.headers["x-richard-router-upstream"] == "openrouter"
    assert skipped.headers["x-richard-router-upstream"] == "openrouter"
    assert probe.status_code == 400
    assert closed_again.status_code == 400
    assert calls == [
        "nvidia-real-model",
        "openrouter-real-model",
        "openrouter-real-model",
        "nvidia-real-model",
        "nvidia-real-model",
    ]


@pytest.mark.asyncio
async def test_disabled_circuit_breaker_never_skips_retryable_primary():
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        calls.append(model)
        if model == "nvidia-real-model":
            return httpx.Response(503, json={"error": {"message": "overloaded"}})
        return _json_success(model)

    router = RichardRouter(
        _config_with_breaker(enabled=False, failure_threshold=1),
        _client_factory(handler),
    )

    await router.chat_completion({"model": "coding", "messages": []})
    await router.chat_completion({"model": "coding", "messages": []})

    assert calls == [
        "nvidia-real-model",
        "openrouter-real-model",
        "nvidia-real-model",
        "openrouter-real-model",
    ]


@pytest.mark.asyncio
async def test_streaming_uses_open_circuit_breaker():
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        calls.append(model)
        if model == "nvidia-real-model":
            return httpx.Response(503, json={"error": {"message": "overloaded"}})
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=(
                b'data: {"id":"chunk-1","model":"openrouter-real-model",'
                b'"choices":[{"delta":{"content":"ok"}}]}\n\n'
                b"data: [DONE]\n\n"
            ),
        )

    router = RichardRouter(
        _config_with_breaker(failure_threshold=1),
        _client_factory(handler),
    )

    for _ in range(2):
        routed = await router.open_stream({"model": "coding", "messages": [], "stream": True})
        assert isinstance(routed, RouterStream)
        chunks = []
        async for chunk in routed.iterator:
            chunks.append(chunk)
        assert b'"model":"coding"' in b"".join(chunks)

    assert calls == [
        "nvidia-real-model",
        "openrouter-real-model",
        "openrouter-real-model",
    ]


@pytest.mark.asyncio
async def test_breaker_opens_on_429_when_policy_lists_429_only():
    """failure_threshold=1 + [429]: primary 429 opens breaker; next request skips primary."""
    clock = ManualClock()
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        calls.append(model)
        if model == "nvidia-real-model":
            return httpx.Response(429, json={"error": {"message": "rate limited"}})
        return _json_success(model)

    router = RichardRouter(
        _config_with_breaker(
            failure_threshold=1,
            cooldown_seconds=30.0,
            retry_on_status=(429,),
        ),
        _client_factory(handler),
        clock=clock,
    )

    first = await router.chat_completion({"model": "coding", "messages": []})
    second = await router.chat_completion({"model": "coding", "messages": []})

    assert first.status_code == 200
    assert second.status_code == 200
    # First: nvidia 429 → openrouter; second: nvidia skipped (open) → openrouter only
    assert calls == [
        "nvidia-real-model",
        "openrouter-real-model",
        "openrouter-real-model",
    ]
    assert second.headers["x-richard-router-upstream"] == "openrouter"


@pytest.mark.asyncio
async def test_breaker_does_not_open_on_503_when_policy_empty():
    """failure_threshold=1 + []: 503 is non-retryable; breaker stays closed."""
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        calls.append(model)
        return httpx.Response(503, json={"error": {"message": "overloaded"}})

    router = RichardRouter(
        _config_with_breaker(failure_threshold=1, retry_on_status=()),
        _client_factory(handler),
    )

    first = await router.chat_completion({"model": "coding", "messages": []})
    second = await router.chat_completion({"model": "coding", "messages": []})

    assert first.status_code == 503
    assert second.status_code == 503
    # Both hit primary only — no failover, no open-circuit skip of primary
    assert calls == ["nvidia-real-model", "nvidia-real-model"]
