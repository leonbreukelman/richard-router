from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from richard_router.config import ObservabilityConfig, RouterConfig, Upstream, VirtualModel
from richard_router.service import RichardRouter, RouterStream
from tests.conftest import make_test_config


def _client_factory(handler):
    transport = httpx.MockTransport(handler)

    def factory(_upstream):
        return httpx.AsyncClient(transport=transport)

    return factory


def _serialized(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


@pytest.mark.asyncio
async def test_decision_log_emits_metadata_without_request_or_response_bodies():
    records: list[dict[str, Any]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["messages"][0]["content"] == "user secret body"
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "model": body["model"],
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "assistant secret body"},
                        "finish_reason": "stop",
                        "index": 0,
                    }
                ],
            },
        )

    router = RichardRouter(
        make_test_config(),
        _client_factory(handler),
        decision_logger=records.append,
    )

    result = await router.chat_completion(
        {
            "model": "coding",
            "messages": [{"role": "user", "content": "user secret body"}],
        }
    )

    assert result.status_code == 200
    assert records == [
        {
            "event": "chat_completion.route",
            "stream": False,
            "virtual_model": "coding",
            "outcome": "success",
            "selected_upstream": "nvidia",
            "status_code": 200,
            "attempts": [],
        }
    ]
    serialized = _serialized(records)
    assert "messages" not in serialized
    assert "content" not in serialized
    assert "user secret body" not in serialized
    assert "assistant secret body" not in serialized


@pytest.mark.asyncio
async def test_decision_log_records_failover_attempts_and_final_upstream():
    records: list[dict[str, Any]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["model"] == "nvidia-real-model":
            return httpx.Response(503, json={"error": {"message": "primary body"}})
        return httpx.Response(200, json={"model": body["model"], "choices": []})

    router = RichardRouter(
        make_test_config(),
        _client_factory(handler),
        decision_logger=records.append,
    )

    result = await router.chat_completion({"model": "coding", "messages": []})

    assert result.status_code == 200
    assert records == [
        {
            "event": "chat_completion.route",
            "stream": False,
            "virtual_model": "coding",
            "outcome": "success",
            "selected_upstream": "openrouter",
            "status_code": 200,
            "attempts": [
                {
                    "upstream": "nvidia",
                    "outcome": "http_error",
                    "status_code": 503,
                    "error_type": None,
                }
            ],
        }
    ]
    assert "primary body" not in _serialized(records)


@pytest.mark.asyncio
async def test_decision_log_passes_metadata_through_redaction():
    records: list[dict[str, Any]] = []
    secret_like = "sk-" + "abcdefghijklmnop"
    config = RouterConfig(
        virtual_models={
            "coding": VirtualModel(
                name="coding",
                upstreams=(
                    Upstream(
                        name=f"upstream-{secret_like}",
                        base_url="https://primary.test/v1",
                        model="real-model",
                    ),
                ),
            )
        },
        observability=ObservabilityConfig(decision_log_enabled=True),
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": {"message": "nope"}})

    router = RichardRouter(config, _client_factory(handler), decision_logger=records.append)

    result = await router.chat_completion({"model": "coding", "messages": []})

    assert result.status_code == 503
    serialized = _serialized(records)
    assert secret_like not in serialized
    assert "[REDACTED]" in serialized


@pytest.mark.asyncio
async def test_decision_log_can_be_disabled():
    records: list[dict[str, Any]] = []
    config = make_test_config()
    config = RouterConfig(
        virtual_models=config.virtual_models,
        failover=config.failover,
        observability=ObservabilityConfig(
            expose_upstream_header=True,
            decision_log_enabled=False,
        ),
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"model": "nvidia-real-model", "choices": []})

    router = RichardRouter(config, _client_factory(handler), decision_logger=records.append)

    result = await router.chat_completion({"model": "coding", "messages": []})

    assert result.status_code == 200
    assert records == []


@pytest.mark.asyncio
async def test_decision_logger_failure_does_not_break_successful_route():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"model": "nvidia-real-model", "choices": []})

    def broken_logger(record: dict[str, Any]) -> None:
        raise RuntimeError("logger unavailable")

    router = RichardRouter(
        make_test_config(),
        _client_factory(handler),
        decision_logger=broken_logger,
    )

    result = await router.chat_completion({"model": "coding", "messages": []})

    assert result.status_code == 200


@pytest.mark.asyncio
async def test_decision_log_exception_attempt_is_type_only_metadata():
    records: list[dict[str, Any]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["model"] == "nvidia-real-model":
            raise httpx.ConnectError("connect failed to primary.test")
        return httpx.Response(503, json={"error": {"message": "fallback body"}})

    router = RichardRouter(
        make_test_config(),
        _client_factory(handler),
        decision_logger=records.append,
    )

    result = await router.chat_completion({"model": "coding", "messages": []})

    assert result.status_code == 503
    assert records == [
        {
            "event": "chat_completion.route",
            "stream": False,
            "virtual_model": "coding",
            "outcome": "all_failed",
            "selected_upstream": None,
            "status_code": 503,
            "attempts": [
                {
                    "upstream": "nvidia",
                    "outcome": "connection_error",
                    "status_code": None,
                    "error_type": "ConnectError",
                },
                {
                    "upstream": "openrouter",
                    "outcome": "http_error",
                    "status_code": 503,
                    "error_type": None,
                },
            ],
        }
    ]
    serialized = _serialized(records)
    assert "connect failed" not in serialized
    assert "primary.test" not in serialized
    assert "fallback body" not in serialized


@pytest.mark.asyncio
async def test_streaming_decision_log_is_metadata_only():
    records: list[dict[str, Any]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["messages"][0]["content"] == "stream user secret"
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=(
                b'data: {"model":"nvidia-real-model",'
                b'"choices":[{"delta":{"content":"stream assistant secret"}}]}\n\n'
                b"data: [DONE]\n\n"
            ),
        )

    router = RichardRouter(
        make_test_config(),
        _client_factory(handler),
        decision_logger=records.append,
    )

    routed = await router.open_stream(
        {
            "model": "coding",
            "messages": [{"role": "user", "content": "stream user secret"}],
            "stream": True,
        }
    )

    assert isinstance(routed, RouterStream)
    assert records == [
        {
            "event": "chat_completion.route",
            "stream": True,
            "virtual_model": "coding",
            "outcome": "success",
            "selected_upstream": "nvidia",
            "status_code": 200,
            "attempts": [],
        }
    ]
    serialized = _serialized(records)
    assert "stream user secret" not in serialized
    assert "stream assistant secret" not in serialized


@pytest.mark.asyncio
async def test_decision_log_timeout_policy_disabled_outcome():
    """retry_on_timeout=false: decision log records
    timeout_failover_disabled, not all_failed, with only the primary in attempts."""
    import dataclasses

    records: list[dict[str, Any]] = []
    config = make_test_config()
    config = dataclasses.replace(
        config, failover=dataclasses.replace(config.failover, retry_on_timeout=False)
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow primary")

    router = RichardRouter(
        config,
        _client_factory(handler),
        decision_logger=records.append,
    )
    result = await router.chat_completion({"model": "coding", "messages": []})
    assert result.status_code == 503
    assert records == [
        {
            "event": "chat_completion.route",
            "stream": False,
            "virtual_model": "coding",
            "outcome": "timeout_failover_disabled",
            "selected_upstream": None,
            "status_code": 503,
            "attempts": [
                {
                    "upstream": "nvidia",
                    "outcome": "timeout",
                    "status_code": None,
                    "error_type": "TimeoutException",
                }
            ],
        }
    ]
    serialized = _serialized(records)
    assert "all_failed" not in serialized


@pytest.mark.asyncio
async def test_decision_log_connection_error_policy_disabled_outcome():
    """retry_on_connection_error=false: decision log records
    connection_failover_disabled, not all_failed, with only the primary in attempts."""
    import dataclasses

    records: list[dict[str, Any]] = []
    config = make_test_config()
    config = dataclasses.replace(
        config,
        failover=dataclasses.replace(config.failover, retry_on_connection_error=False),
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connect failed to primary")

    router = RichardRouter(
        config,
        _client_factory(handler),
        decision_logger=records.append,
    )
    result = await router.chat_completion({"model": "coding", "messages": []})
    assert result.status_code == 503
    assert records == [
        {
            "event": "chat_completion.route",
            "stream": False,
            "virtual_model": "coding",
            "outcome": "connection_failover_disabled",
            "selected_upstream": None,
            "status_code": 503,
            "attempts": [
                {
                    "upstream": "nvidia",
                    "outcome": "connection_error",
                    "status_code": None,
                    "error_type": "ConnectError",
                }
            ],
        }
    ]
    serialized = _serialized(records)
    assert "all_failed" not in serialized
