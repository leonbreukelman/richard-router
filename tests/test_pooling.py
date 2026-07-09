from __future__ import annotations

import json
from collections import Counter

import httpx
import pytest
from fastapi.testclient import TestClient

from richard_router.config import Upstream
from richard_router.main import create_app
from richard_router.service import RichardRouter, RouterStream, default_client_factory
from tests.conftest import make_test_config


class TrackingAsyncClient(httpx.AsyncClient):
    def __init__(self, upstream_name: str, closed: list[str], **kwargs):
        self.upstream_name = upstream_name
        self.closed = closed
        super().__init__(**kwargs)

    async def aclose(self) -> None:
        self.closed.append(self.upstream_name)
        await super().aclose()


@pytest.mark.asyncio
async def test_default_client_factory_uses_split_timeouts():
    upstream = Upstream(
        name="primary",
        base_url="https://primary.test/v1",
        model="real-model",
        timeout_seconds=42.0,
        connect_timeout_seconds=3.0,
        write_timeout_seconds=4.0,
        pool_timeout_seconds=5.0,
    )

    client = default_client_factory(upstream)

    try:
        assert client.timeout.connect == 3.0
        assert client.timeout.read == 42.0
        assert client.timeout.write == 4.0
        assert client.timeout.pool == 5.0
    finally:
        await client.aclose()

    default_upstream = Upstream(
        name="default",
        base_url="https://default.test/v1",
        model="real-model",
    )
    default_client = default_client_factory(default_upstream)
    try:
        assert default_client.timeout.connect == 5.0
    finally:
        await default_client.aclose()


@pytest.mark.asyncio
async def test_client_factory_invoked_once_per_upstream_across_requests():
    factory_calls: Counter[str] = Counter()
    closed: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["model"] == "nvidia-real-model":
            return httpx.Response(503, json={"error": {"message": "overloaded"}})
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

    def factory(upstream: Upstream) -> httpx.AsyncClient:
        factory_calls[upstream.name] += 1
        return TrackingAsyncClient(
            upstream.name,
            closed,
            transport=httpx.MockTransport(handler),
        )

    router = RichardRouter(make_test_config(), factory)
    first = await router.chat_completion({"model": "coding", "messages": []})
    second = await router.chat_completion({"model": "coding", "messages": []})
    await router.aclose()

    assert first.status_code == 200
    assert second.status_code == 200
    assert factory_calls == {"nvidia": 1, "openrouter": 1}
    assert sorted(closed) == ["nvidia", "openrouter"]


@pytest.mark.asyncio
async def test_streaming_reuses_pooled_clients_until_router_close():
    factory_calls: Counter[str] = Counter()
    closed: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["model"] == "nvidia-real-model":
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

    def factory(upstream: Upstream) -> httpx.AsyncClient:
        factory_calls[upstream.name] += 1
        return TrackingAsyncClient(
            upstream.name,
            closed,
            transport=httpx.MockTransport(handler),
        )

    router = RichardRouter(make_test_config(), factory)
    for _ in range(2):
        routed = await router.open_stream({"model": "coding", "messages": [], "stream": True})
        assert isinstance(routed, RouterStream)
        chunks = []
        async for chunk in routed.iterator:
            chunks.append(chunk)
        assert b'"model":"coding"' in b"".join(chunks)

    assert factory_calls == {"nvidia": 1, "openrouter": 1}
    assert closed == []

    await router.aclose()
    assert sorted(closed) == ["nvidia", "openrouter"]


def test_lifespan_closes_pooled_clients():
    factory_calls: Counter[str] = Counter()
    closed: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-primary",
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

    def factory(upstream: Upstream) -> httpx.AsyncClient:
        factory_calls[upstream.name] += 1
        return TrackingAsyncClient(
            upstream.name,
            closed,
            transport=httpx.MockTransport(handler),
        )

    app = create_app(make_test_config(), client_factory=factory)
    with TestClient(app) as client:
        response = client.post("/v1/chat/completions", json={"model": "coding", "messages": []})
        assert response.status_code == 200

    assert factory_calls == {"nvidia": 1}
    assert closed == ["nvidia"]
