from __future__ import annotations

import json
from dataclasses import replace

import httpx
import pytest

from richard_router.config import FailoverConfig
from richard_router.service import RichardRouter
from tests.conftest import make_test_config


def _client_factory(handler):
    transport = httpx.MockTransport(handler)

    def factory(_upstream):
        return httpx.AsyncClient(transport=transport)

    return factory


def _config_with_retry_policy(retry_on_status: tuple[int, ...] | None) -> object:
    return replace(
        make_test_config(),
        failover=FailoverConfig(retry_on_status=retry_on_status),
    )


def _ok_json(model: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-ok",
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
async def test_unknown_virtual_model_returns_404():
    router = RichardRouter(make_test_config(), _client_factory(lambda request: httpx.Response(500)))
    result = await router.chat_completion({"model": "missing", "messages": []})
    assert result.status_code == 404


# ── acceptance paths for explicit retry_on_status (#28) ─────────────────────


@pytest.mark.asyncio
async def test_explicit_empty_policy_primary_503_does_not_failover():
    """retry_on_status: [] — 503 is terminal; fallback must not be called."""
    called: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        called.append(model)
        return httpx.Response(503, json={"error": {"message": "overloaded"}})

    router = RichardRouter(
        _config_with_retry_policy(()),
        _client_factory(handler),
    )
    result = await router.chat_completion({"model": "coding", "messages": []})
    assert result.status_code == 503
    assert called == ["nvidia-real-model"]
    assert result.headers.get("x-richard-router-upstream") == "nvidia"


@pytest.mark.asyncio
async def test_explicit_429_fails_over_but_503_does_not():
    """retry_on_status: [429] — 429 fails over; 503 stays on primary."""
    # Case A: primary 429 → fallback
    called_429: list[str] = []

    async def handler_429(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        called_429.append(model)
        if model == "nvidia-real-model":
            return httpx.Response(429, json={"error": {"message": "rate limited"}})
        return _ok_json(model)

    router = RichardRouter(
        _config_with_retry_policy((429,)),
        _client_factory(handler_429),
    )
    result = await router.chat_completion({"model": "coding", "messages": []})
    assert result.status_code == 200
    assert called_429 == ["nvidia-real-model", "openrouter-real-model"]
    assert result.headers["x-richard-router-upstream"] == "openrouter"

    # Case B: primary 503 → no failover
    called_503: list[str] = []

    async def handler_503(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        called_503.append(model)
        return httpx.Response(503, json={"error": {"message": "overloaded"}})

    router503 = RichardRouter(
        _config_with_retry_policy((429,)),
        _client_factory(handler_503),
    )
    result503 = await router503.chat_completion({"model": "coding", "messages": []})
    assert result503.status_code == 503
    assert called_503 == ["nvidia-real-model"]


@pytest.mark.asyncio
async def test_omitted_policy_unlisted_5xx_still_fails_over():
    """retry_on_status omitted (None) — 599 still fails over under default blanket 5xx."""
    called: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        called.append(model)
        if model == "nvidia-real-model":
            return httpx.Response(599, json={"error": {"message": "weird 5xx"}})
        return _ok_json(model)

    router = RichardRouter(
        _config_with_retry_policy(None),
        _client_factory(handler),
    )
    result = await router.chat_completion({"model": "coding", "messages": []})
    assert result.status_code == 200
    assert called == ["nvidia-real-model", "openrouter-real-model"]
    assert result.headers["x-richard-router-upstream"] == "openrouter"


@pytest.mark.asyncio
async def test_streaming_explicit_empty_503_does_not_failover():
    """Streaming path: [] + primary 503 → no fallback open_stream attempt."""
    called: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        called.append(model)
        return httpx.Response(503, json={"error": {"message": "overloaded"}})

    router = RichardRouter(
        _config_with_retry_policy(()),
        _client_factory(handler),
    )
    result = await router.open_stream({"model": "coding", "messages": [], "stream": True})
    assert isinstance(result, object)
    # Terminal RouterResult — must not have called fallback
    assert called == ["nvidia-real-model"]
    assert getattr(result, "status_code", None) == 503


@pytest.mark.asyncio
async def test_streaming_explicit_429_fails_over():
    """Streaming path: [429] + primary 429 → fallback stream used."""
    called: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        called.append(model)
        if model == "nvidia-real-model":
            return httpx.Response(429, json={"error": {"message": "rate limited"}})
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
        _config_with_retry_policy((429,)),
        _client_factory(handler),
    )
    routed = await router.open_stream({"model": "coding", "messages": [], "stream": True})
    chunks = []
    async for chunk in routed.iterator:
        chunks.append(chunk)
    assert called == ["nvidia-real-model", "openrouter-real-model"]
    assert b"data: [DONE]" in b"".join(chunks)
