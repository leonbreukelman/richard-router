from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from dataclasses import replace
from typing import cast

import httpx
import pytest

from richard_router.config import FailoverConfig
from richard_router.service import RichardRouter, RouterStream
from tests.conftest import make_test_config


def _client_factory(handler):
    transport = httpx.MockTransport(handler)

    def factory(_upstream):
        return httpx.AsyncClient(transport=transport)

    return factory


class ChunkedSSEStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


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


@pytest.mark.parametrize(
    ("content", "content_type"),
    [
        (b"<html>overloaded</html>", "text/html"),
        (b'{"error":', "application/json"),
        (b'["overloaded"]', "application/json"),
    ],
    ids=["html", "malformed-json", "non-object-json"],
)
@pytest.mark.asyncio
async def test_retryable_non_json_primary_error_preserves_failover(content, content_type):
    called_models = []

    async def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        called_models.append(model)
        if model == "nvidia-real-model":
            return httpx.Response(503, content=content, headers={"content-type": content_type})
        return _ok_json(model)

    router = RichardRouter(make_test_config(), _client_factory(handler))
    result = await router.chat_completion({"model": "coding", "messages": []})

    assert result.status_code == 200
    assert result.headers["x-richard-router-upstream"] == "openrouter"
    assert called_models == ["nvidia-real-model", "openrouter-real-model"]


@pytest.mark.asyncio
async def test_streaming_non_json_primary_error_preserves_failover():
    called_models = []

    async def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        called_models.append(model)
        if model == "nvidia-real-model":
            return httpx.Response(
                503,
                content=b"<html>overloaded</html>",
                headers={"content-type": "text/html"},
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=(
                b'data: {"id":"chunk","model":"openrouter-real-model",'
                b'"choices":[{"delta":{"content":"ok"}}]}\n\n'
                b"data: [DONE]\n\n"
            ),
        )

    router = RichardRouter(make_test_config(), _client_factory(handler))
    result = await router.open_stream({"model": "coding", "messages": [], "stream": True})
    assert isinstance(result, RouterStream)
    payload = b"".join([chunk async for chunk in result.iterator])

    assert b'"model":"coding"' in payload
    assert result.headers["x-richard-router-upstream"] == "openrouter"
    assert called_models == ["nvidia-real-model", "openrouter-real-model"]


@pytest.mark.asyncio
async def test_all_non_json_upstream_failures_return_attempt_evidence():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503,
            content=b"temporarily unavailable",
            headers={"content-type": "text/plain"},
        )

    router = RichardRouter(make_test_config(), _client_factory(handler))
    result = await router.chat_completion({"model": "coding", "messages": []})
    payload = json.loads(result.content)

    assert result.status_code == 503
    assert [attempt["upstream"] for attempt in payload["error"]["attempts"]] == [
        "nvidia",
        "openrouter",
    ]
    assert all(
        attempt["outcome"] == "http_error" for attempt in payload["error"]["attempts"]
    )


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
@pytest.mark.parametrize("newline", [b"\n", b"\r\n"])
async def test_streaming_rewrite_is_independent_of_byte_chunk_boundaries(newline):
    upstream_event = (
        b": keep this comment"
        + newline
        + b"event: message"
        + newline
        + 'data: {"id":"chunk-1","model":"nvidia-real-model",'
        '"choices":[{"delta":{"content":"caf\u00e9 \u2603"}}]}'.encode()
        + newline
        + newline
        + b"data: [DONE]"
        + newline
        + newline
    )
    stream = ChunkedSSEStream(
        [upstream_event[index : index + 1] for index in range(len(upstream_event))]
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=stream,
        )

    router = RichardRouter(make_test_config(), _client_factory(handler))
    routed = await router.open_stream({"model": "coding", "messages": [], "stream": True})
    payload = b"".join([chunk async for chunk in routed.iterator])

    assert payload.startswith(b": keep this comment" + newline + b"event: message" + newline)
    assert payload.endswith(newline + b"data: [DONE]" + newline + newline)
    assert payload.count(newline) == upstream_event.count(newline)
    data_line = payload.split(newline)[2]
    rewritten = json.loads(data_line.removeprefix(b"data: "))
    assert rewritten["model"] == "coding"
    assert rewritten["choices"][0]["delta"]["content"] == "caf" + chr(233) + " " + chr(9731)
    assert b"nvidia-real-model" not in payload
    assert stream.closed


@pytest.mark.asyncio
async def test_streaming_rewrites_final_unterminated_data_line_and_closes_stream():
    stream = ChunkedSSEStream(
        [b"da", b'ta: {"model":"nvidia-', b'real-model","choices":[]}']
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=stream,
        )

    router = RichardRouter(make_test_config(), _client_factory(handler))
    routed = await router.open_stream({"model": "coding", "messages": [], "stream": True})
    payload = b"".join([chunk async for chunk in routed.iterator])

    assert json.loads(payload.removeprefix(b"data: "))["model"] == "coding"
    assert b"nvidia-real-model" not in payload
    assert stream.closed


@pytest.mark.asyncio
async def test_streaming_closes_chunked_stream_when_consumer_cancels():
    stream = ChunkedSSEStream(
        [
            b'data: {"model":"nvidia-real-model","choices":[]}\n',
            b"data: [DONE]\n\n",
        ]
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=stream,
        )

    router = RichardRouter(make_test_config(), _client_factory(handler))
    routed = await router.open_stream({"model": "coding", "messages": [], "stream": True})
    assert isinstance(routed, RouterStream)
    iterator = cast(AsyncGenerator[bytes, None], routed.iterator)

    first_chunk = await anext(iterator)
    await iterator.aclose()

    assert b'"model":"coding"' in first_chunk
    assert stream.closed


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
