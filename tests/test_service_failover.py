from __future__ import annotations

import json

import httpx
import pytest

from richard_router.service import RichardRouter
from tests.conftest import make_test_config


def _client_factory(handler):
    transport = httpx.MockTransport(handler)

    def factory(_upstream):
        return httpx.AsyncClient(transport=transport)

    return factory


@pytest.mark.asyncio
async def test_primary_success_rewrites_model_back_to_virtual(monkeypatch):
    monkeypatch.setenv("TEST_NVIDIA_KEY", "nvidia-secret")
    seen = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        assert request.headers["authorization"] == "Bearer nvidia-secret"
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "model": body["model"],
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                        "index": 0,
                    }
                ],
            },
        )

    router = RichardRouter(make_test_config(), _client_factory(handler))
    result = await router.chat_completion({"model": "coding", "messages": []})
    payload = json.loads(result.content)
    assert result.status_code == 200
    assert result.headers["x-richard-router-upstream"] == "nvidia"
    assert seen[0]["model"] == "nvidia-real-model"
    assert payload["model"] == "coding"


@pytest.mark.asyncio
async def test_retryable_primary_status_fails_over_to_openrouter(monkeypatch):
    monkeypatch.setenv("TEST_OPENROUTER_KEY", "openrouter-secret")
    called_models = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        called_models.append(body["model"])
        if body["model"] == "nvidia-real-model":
            return httpx.Response(503, json={"error": {"message": "overloaded"}})
        assert request.headers["authorization"] == "Bearer openrouter-secret"
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-fallback",
                "object": "chat.completion",
                "model": body["model"],
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "fallback ok"},
                        "finish_reason": "stop",
                        "index": 0,
                    }
                ],
            },
        )

    router = RichardRouter(make_test_config(), _client_factory(handler))
    result = await router.chat_completion({"model": "coding", "messages": []})
    payload = json.loads(result.content)
    assert result.status_code == 200
    assert result.headers["x-richard-router-upstream"] == "openrouter"
    assert called_models == ["nvidia-real-model", "openrouter-real-model"]
    assert payload["model"] == "coding"


@pytest.mark.asyncio
async def test_bad_request_does_not_fail_over():
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400, json={"error": {"message": "bad request"}})

    router = RichardRouter(make_test_config(), _client_factory(handler))
    result = await router.chat_completion({"model": "coding", "messages": []})
    assert result.status_code == 400
    assert result.headers["x-richard-router-upstream"] == "nvidia"
    assert calls == 1


@pytest.mark.asyncio
async def test_tool_schema_passes_through_unchanged():
    tool = {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
        },
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["tools"] == [tool]
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-tools",
                "object": "chat.completion",
                "model": body["model"],
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "tools ok"},
                        "finish_reason": "stop",
                        "index": 0,
                    }
                ],
            },
        )

    router = RichardRouter(make_test_config(), _client_factory(handler))
    result = await router.chat_completion({"model": "coding", "messages": [], "tools": [tool]})
    assert result.status_code == 200


@pytest.mark.asyncio
async def test_timeout_fails_over_to_openrouter():
    called_models = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        called_models.append(body["model"])
        if body["model"] == "nvidia-real-model":
            raise httpx.ReadTimeout("slow primary")
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-timeout-fallback",
                "object": "chat.completion",
                "model": body["model"],
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "timeout fallback ok"},
                        "finish_reason": "stop",
                        "index": 0,
                    }
                ],
            },
        )

    router = RichardRouter(make_test_config(), _client_factory(handler))
    result = await router.chat_completion({"model": "coding", "messages": []})
    payload = json.loads(result.content)
    assert result.status_code == 200
    assert result.headers["x-richard-router-upstream"] == "openrouter"
    assert called_models == ["nvidia-real-model", "openrouter-real-model"]
    assert payload["model"] == "coding"


@pytest.mark.asyncio
async def test_both_upstreams_retryable_fail_returns_503():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": {"message": "unavailable"}})

    router = RichardRouter(make_test_config(), _client_factory(handler))
    result = await router.chat_completion({"model": "coding", "messages": []})
    payload = json.loads(result.content)
    assert result.status_code == 503
    assert payload["error"]["message"] == "all upstreams failed"
    assert [attempt["upstream"] for attempt in payload["error"]["attempts"]] == [
        "nvidia",
        "openrouter",
    ]


@pytest.mark.asyncio
async def test_422_does_not_fail_over():
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(422, json={"error": {"message": "invalid schema"}})

    router = RichardRouter(make_test_config(), _client_factory(handler))
    result = await router.chat_completion({"model": "coding", "messages": []})
    assert result.status_code == 422
    assert result.headers["x-richard-router-upstream"] == "nvidia"
    assert calls == 1


@pytest.mark.asyncio
async def test_streaming_rewrites_model_to_virtual_name():
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "nvidia-real-model"
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=(
                b'data: {"id":"chunk-1","model":"nvidia-real-model",'
                b'"choices":[{"delta":{"content":"ok"}}]}\n\n'
                b"data: [DONE]\n\n"
            ),
        )

    router = RichardRouter(make_test_config(), _client_factory(handler))
    routed = await router.open_stream({"model": "coding", "messages": [], "stream": True})
    chunks = []
    async for chunk in routed.iterator:
        chunks.append(chunk)
    payload = b"".join(chunks)
    assert b'"model":"coding"' in payload
    assert b"nvidia-real-model" not in payload
    assert b"data: [DONE]" in payload


@pytest.mark.asyncio
async def test_timeout_policy_disabled_reports_truthful_single_failure():
    """retry_on_timeout=false: primary times out → 503 names the upstream
    and the policy, does NOT claim all upstreams failed."""
    import dataclasses

    config = make_test_config()
    config = dataclasses.replace(
        config, failover=dataclasses.replace(config.failover, retry_on_timeout=False)
    )
    call_count = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        raise httpx.ReadTimeout("slow primary")

    router = RichardRouter(config, _client_factory(handler))
    result = await router.chat_completion({"model": "coding", "messages": []})
    payload = json.loads(result.content)
    assert result.status_code == 503
    assert "all upstreams failed" not in payload["error"]["message"]
    assert "nvidia" in payload["error"]["message"]
    assert "timeout_failover_disabled" in payload["error"]["message"]
    assert call_count == 1
    assert [attempt["upstream"] for attempt in payload["error"]["attempts"]] == ["nvidia"]


@pytest.mark.asyncio
async def test_connection_error_policy_disabled_reports_truthful_single_failure():
    """retry_on_connection_error=false: primary connection fails → 503 names
    the upstream and the policy, does NOT claim all upstreams failed."""
    import dataclasses

    config = make_test_config()
    config = dataclasses.replace(
        config,
        failover=dataclasses.replace(config.failover, retry_on_connection_error=False),
    )
    call_count = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        raise httpx.ConnectError("connect failed to primary")

    router = RichardRouter(config, _client_factory(handler))
    result = await router.chat_completion({"model": "coding", "messages": []})
    payload = json.loads(result.content)
    assert result.status_code == 503
    assert "all upstreams failed" not in payload["error"]["message"]
    assert "nvidia" in payload["error"]["message"]
    assert "connection_failover_disabled" in payload["error"]["message"]
    assert call_count == 1
    assert [attempt["upstream"] for attempt in payload["error"]["attempts"]] == ["nvidia"]


@pytest.mark.asyncio
async def test_unknown_virtual_model_returns_404():
    router = RichardRouter(make_test_config(), _client_factory(lambda request: httpx.Response(500)))
    result = await router.chat_completion({"model": "missing", "messages": []})
    assert result.status_code == 404
