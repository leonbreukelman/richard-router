from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from richard_router.config import RouterConfig, Upstream, VirtualModel
from richard_router.errors import classify_exception, classify_status
from richard_router.redaction import redact

ClientFactory = Callable[[Upstream], httpx.AsyncClient]
ClientCacheKey = tuple[str, str, str]


@dataclass
class Attempt:
    upstream: str
    outcome: str
    status_code: int | None = None
    error_type: str | None = None

    def safe_dict(self) -> dict[str, Any]:
        return redact(
            {
                "upstream": self.upstream,
                "outcome": self.outcome,
                "status_code": self.status_code,
                "error_type": self.error_type,
            }
        )


@dataclass
class RouterResult:
    status_code: int
    content: bytes
    media_type: str = "application/json"
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class RouterStream:
    iterator: AsyncIterator[bytes]
    media_type: str = "text/event-stream"
    headers: dict[str, str] = field(default_factory=dict)


def default_client_factory(upstream: Upstream) -> httpx.AsyncClient:
    timeout = httpx.Timeout(
        connect=upstream.connect_timeout_seconds,
        read=upstream.timeout_seconds,
        write=upstream.write_timeout_seconds,
        pool=upstream.pool_timeout_seconds,
    )
    return httpx.AsyncClient(timeout=timeout)


class RichardRouter:
    def __init__(self, config: RouterConfig, client_factory: ClientFactory | None = None):
        self.config = config
        self.client_factory = client_factory or default_client_factory
        self._clients: dict[ClientCacheKey, httpx.AsyncClient] = {}

    @staticmethod
    def _client_cache_key(upstream: Upstream) -> ClientCacheKey:
        return (upstream.name, upstream.base_url, upstream.model)

    def _client_for(self, upstream: Upstream) -> httpx.AsyncClient:
        cache_key = self._client_cache_key(upstream)
        client = self._clients.get(cache_key)
        if client is None:
            client = self.client_factory(upstream)
            self._clients[cache_key] = client
        return client

    async def aclose(self) -> None:
        clients = list(self._clients.values())
        self._clients.clear()
        for client in clients:
            await client.aclose()

    def models_payload(self) -> dict[str, Any]:
        return {
            "object": "list",
            "data": [
                {"id": model.name, "object": "model", "owned_by": model.owned_by}
                for model in self.config.virtual_models.values()
            ],
        }

    def _lookup_model(self, model_name: str) -> VirtualModel | None:
        return self.config.virtual_models.get(model_name)

    def _upstream_headers(self, upstream: Upstream) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if upstream.api_key:
            headers["Authorization"] = f"Bearer {upstream.api_key}"
        headers.update(upstream.headers)
        return headers

    @staticmethod
    def _rewrite_body(body: dict[str, Any], upstream: Upstream) -> dict[str, Any]:
        rewritten = dict(body)
        rewritten["model"] = upstream.model
        return rewritten

    @staticmethod
    def _rewrite_response_model(content: bytes, virtual_model: str) -> tuple[bytes, str]:
        try:
            payload = json.loads(content.decode("utf-8"))
        except Exception:
            return content, "application/octet-stream"
        if isinstance(payload, dict):
            payload["model"] = virtual_model
        return json.dumps(payload, separators=(",", ":")).encode("utf-8"), "application/json"

    @staticmethod
    def _error_result(status_code: int, message: str) -> RouterResult:
        return RouterResult(
            status_code=status_code,
            content=json.dumps({"error": {"message": message}}).encode("utf-8"),
        )

    @staticmethod
    def _content_type(response: httpx.Response, default: str = "application/json") -> str:
        return response.headers.get("content-type", default).split(";")[0]

    def _retryable_status(self, status_code: int) -> bool:
        retryable_status = set(self.config.failover.retry_on_status)
        return classify_status(status_code, retryable_status) == "retryable"

    def _diagnostic_headers(self, upstream: Upstream) -> dict[str, str]:
        if not self.config.observability.expose_upstream_header:
            return {}
        return {"x-richard-router-upstream": upstream.name}

    async def chat_completion(self, body: dict[str, Any]) -> RouterResult:
        virtual_name = str(body.get("model") or "")
        virtual = self._lookup_model(virtual_name)
        if virtual is None:
            return self._error_result(404, f"unknown virtual model: {virtual_name}")

        attempts: list[Attempt] = []
        for upstream in virtual.upstreams:
            for _ in range(self.config.failover.max_attempts_per_upstream):
                client = self._client_for(upstream)
                try:
                    response = await client.post(
                        upstream.chat_completions_url,
                        json=self._rewrite_body(body, upstream),
                        headers=self._upstream_headers(upstream),
                    )
                    content = response.content
                    if 200 <= response.status_code < 300:
                        rewritten, media_type = self._rewrite_response_model(content, virtual.name)
                        return RouterResult(
                            status_code=response.status_code,
                            content=rewritten,
                            media_type=media_type,
                            headers=self._diagnostic_headers(upstream),
                        )
                    attempts.append(Attempt(upstream.name, "http_error", response.status_code))
                    if self._retryable_status(response.status_code):
                        continue
                    return RouterResult(
                        status_code=response.status_code,
                        content=content,
                        media_type=self._content_type(response),
                        headers=self._diagnostic_headers(upstream),
                    )
                except httpx.TimeoutException as exc:
                    attempts.append(
                        Attempt(upstream.name, "timeout", error_type="TimeoutException")
                    )
                    if (
                        classify_exception(exc) == "fatal"
                        or not self.config.failover.retry_on_timeout
                    ):
                        return self._all_failed(attempts)
                except httpx.TransportError as exc:
                    attempts.append(
                        Attempt(
                            upstream.name,
                            "connection_error",
                            error_type=type(exc).__name__,
                        )
                    )
                    if (
                        classify_exception(exc) == "fatal"
                        or not self.config.failover.retry_on_connection_error
                    ):
                        return self._all_failed(attempts)
        return self._all_failed(attempts)

    def _all_failed(self, attempts: list[Attempt]) -> RouterResult:
        return RouterResult(
            status_code=503,
            content=json.dumps(
                {
                    "error": {
                        "message": "all upstreams failed",
                        "attempts": [attempt.safe_dict() for attempt in attempts],
                    }
                }
            ).encode("utf-8"),
        )

    async def open_stream(self, body: dict[str, Any]) -> RouterStream | RouterResult:
        virtual_name = str(body.get("model") or "")
        virtual = self._lookup_model(virtual_name)
        if virtual is None:
            return self._error_result(404, f"unknown virtual model: {virtual_name}")

        attempts: list[Attempt] = []
        for upstream in virtual.upstreams:
            for _ in range(self.config.failover.max_attempts_per_upstream):
                client = self._client_for(upstream)
                stream_cm = client.stream(
                    "POST",
                    upstream.chat_completions_url,
                    json=self._rewrite_body(body, upstream),
                    headers=self._upstream_headers(upstream),
                )
                stream_entered = False
                try:
                    response = await stream_cm.__aenter__()
                    stream_entered = True
                    if 200 <= response.status_code < 300:
                        media_type = self._content_type(response, "text/event-stream")
                        iterator = self._stream_iterator(response, stream_cm, virtual.name)
                        return RouterStream(
                            iterator=iterator,
                            media_type=media_type,
                            headers=self._diagnostic_headers(upstream),
                        )

                    content = await response.aread()
                    await stream_cm.__aexit__(None, None, None)
                    stream_entered = False
                    attempts.append(Attempt(upstream.name, "http_error", response.status_code))
                    if self._retryable_status(response.status_code):
                        continue
                    return RouterResult(
                        status_code=response.status_code,
                        content=content,
                        media_type=self._content_type(response),
                        headers=self._diagnostic_headers(upstream),
                    )
                except httpx.TimeoutException as exc:
                    if stream_entered:
                        await stream_cm.__aexit__(type(exc), exc, exc.__traceback__)
                    attempts.append(
                        Attempt(upstream.name, "timeout", error_type="TimeoutException")
                    )
                    if (
                        classify_exception(exc) == "fatal"
                        or not self.config.failover.retry_on_timeout
                    ):
                        return self._all_failed(attempts)
                except httpx.TransportError as exc:
                    if stream_entered:
                        await stream_cm.__aexit__(type(exc), exc, exc.__traceback__)
                    attempts.append(
                        Attempt(
                            upstream.name,
                            "connection_error",
                            error_type=type(exc).__name__,
                        )
                    )
                    if (
                        classify_exception(exc) == "fatal"
                        or not self.config.failover.retry_on_connection_error
                    ):
                        return self._all_failed(attempts)

        return self._all_failed(attempts)

    @staticmethod
    def _rewrite_sse_chunk(chunk: bytes, virtual_model: str) -> bytes:
        lines: list[bytes] = []
        for line in chunk.splitlines(keepends=True):
            newline = b"\n" if line.endswith(b"\n") else b""
            core = line[:-1] if newline else line
            if core.endswith(b"\r"):
                core = core[:-1]
                newline = b"\r" + newline
            if not core.startswith(b"data:"):
                lines.append(line)
                continue
            prefix, _, raw_data = core.partition(b":")
            data = raw_data.lstrip()
            if data == b"[DONE]":
                lines.append(line)
                continue
            try:
                payload = json.loads(data.decode("utf-8"))
            except Exception:
                lines.append(line)
                continue
            if isinstance(payload, dict):
                payload["model"] = virtual_model
                rewritten = json.dumps(payload, separators=(",", ":")).encode("utf-8")
                lines.append(prefix + b": " + rewritten + newline)
            else:
                lines.append(line)
        return b"".join(lines)

    @staticmethod
    async def _stream_iterator(
        response: httpx.Response,
        stream_cm: Any,
        virtual_model: str,
    ) -> AsyncIterator[bytes]:
        try:
            async for chunk in response.aiter_bytes():
                yield RichardRouter._rewrite_sse_chunk(chunk, virtual_model)
        finally:
            await stream_cm.__aexit__(None, None, None)
