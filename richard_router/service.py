from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from richard_router.config import RouterConfig, Upstream, VirtualModel
from richard_router.errors import classify_exception, classify_status
from richard_router.redaction import redact

ClientFactory = Callable[[Upstream], httpx.AsyncClient]
Clock = Callable[[], float]
ClientCacheKey = tuple[str, str, str]
DecisionLogger = Callable[[dict[str, Any]], None]

logger = logging.getLogger(__name__)


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


@dataclass
class CircuitBreakerState:
    consecutive_failures: int = 0
    opened_at: float | None = None
    half_open_probes: int = 0


def default_client_factory(upstream: Upstream) -> httpx.AsyncClient:
    timeout = httpx.Timeout(
        connect=upstream.connect_timeout_seconds,
        read=upstream.timeout_seconds,
        write=upstream.write_timeout_seconds,
        pool=upstream.pool_timeout_seconds,
    )
    return httpx.AsyncClient(timeout=timeout)


class RichardRouter:
    def __init__(
        self,
        config: RouterConfig,
        client_factory: ClientFactory | None = None,
        clock: Clock | None = None,
        decision_logger: DecisionLogger | None = None,
    ):
        self.config = config
        self.client_factory = client_factory or default_client_factory
        self.clock = clock or time.monotonic
        self.decision_logger = decision_logger
        self._clients: dict[ClientCacheKey, httpx.AsyncClient] = {}
        self._circuit_breakers: dict[ClientCacheKey, CircuitBreakerState] = {}

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

    def _circuit_breaker_state(self, upstream: Upstream) -> CircuitBreakerState:
        cache_key = self._client_cache_key(upstream)
        state = self._circuit_breakers.get(cache_key)
        if state is None:
            state = CircuitBreakerState()
            self._circuit_breakers[cache_key] = state
        return state

    def _circuit_open_attempt(self, upstream: Upstream) -> Attempt | None:
        cfg = self.config.failover.circuit_breaker
        if not cfg.enabled:
            return None
        state = self._circuit_breaker_state(upstream)
        if state.opened_at is None:
            return None
        if self.clock() - state.opened_at < cfg.cooldown_seconds:
            return Attempt(upstream.name, "circuit_open")
        if state.half_open_probes >= cfg.half_open_max_probes:
            return Attempt(upstream.name, "circuit_open")
        state.half_open_probes += 1
        return None

    def _record_upstream_success(self, upstream: Upstream) -> None:
        if not self.config.failover.circuit_breaker.enabled:
            return
        state = self._circuit_breaker_state(upstream)
        state.consecutive_failures = 0
        state.opened_at = None
        state.half_open_probes = 0

    def _record_retryable_failure(self, upstream: Upstream) -> None:
        cfg = self.config.failover.circuit_breaker
        if not cfg.enabled:
            return
        state = self._circuit_breaker_state(upstream)
        if state.opened_at is not None:
            state.consecutive_failures = cfg.failure_threshold
            state.opened_at = self.clock()
            state.half_open_probes = 0
            return
        state.consecutive_failures += 1
        if state.consecutive_failures >= cfg.failure_threshold:
            state.opened_at = self.clock()
            state.half_open_probes = 0

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

    @staticmethod
    def _retryable_exception(exc: Exception) -> bool:
        return classify_exception(exc) == "retryable"

    def _diagnostic_headers(self, upstream: Upstream) -> dict[str, str]:
        if not self.config.observability.expose_upstream_header:
            return {}
        return {"x-richard-router-upstream": upstream.name}

    def _emit_decision_log(self, record: dict[str, Any]) -> None:
        if not self.config.observability.decision_log_enabled:
            return
        try:
            safe_record = redact(record)
            if self.decision_logger is not None:
                self.decision_logger(safe_record)
                return
            logger.info("richard_router.decision %s", json.dumps(safe_record, sort_keys=True))
        except Exception:
            logger.warning("richard_router.decision_log_failed", exc_info=True)

    def _emit_route_decision(
        self,
        *,
        virtual_model: str,
        stream: bool,
        outcome: str,
        selected_upstream: str | None,
        status_code: int | None,
        attempts: list[Attempt],
    ) -> None:
        self._emit_decision_log(
            {
                "event": "chat_completion.route",
                "stream": stream,
                "virtual_model": virtual_model,
                "outcome": outcome,
                "selected_upstream": selected_upstream,
                "status_code": status_code,
                "attempts": [attempt.safe_dict() for attempt in attempts],
            }
        )

    async def chat_completion(self, body: dict[str, Any]) -> RouterResult:
        virtual_name = str(body.get("model") or "")
        virtual = self._lookup_model(virtual_name)
        if virtual is None:
            self._emit_route_decision(
                virtual_model=virtual_name,
                stream=False,
                outcome="unknown_model",
                selected_upstream=None,
                status_code=404,
                attempts=[],
            )
            return self._error_result(404, f"unknown virtual model: {virtual_name}")

        attempts: list[Attempt] = []
        for upstream in virtual.upstreams:
            for _ in range(self.config.failover.max_attempts_per_upstream):
                circuit_attempt = self._circuit_open_attempt(upstream)
                if circuit_attempt is not None:
                    attempts.append(circuit_attempt)
                    break
                client = self._client_for(upstream)
                try:
                    response = await client.post(
                        upstream.chat_completions_url,
                        json=self._rewrite_body(body, upstream),
                        headers=self._upstream_headers(upstream),
                    )
                    content = response.content
                    if 200 <= response.status_code < 300:
                        self._record_upstream_success(upstream)
                        self._emit_route_decision(
                            virtual_model=virtual.name,
                            stream=False,
                            outcome="success",
                            selected_upstream=upstream.name,
                            status_code=response.status_code,
                            attempts=attempts,
                        )
                        rewritten, media_type = self._rewrite_response_model(content, virtual.name)
                        return RouterResult(
                            status_code=response.status_code,
                            content=rewritten,
                            media_type=media_type,
                            headers=self._diagnostic_headers(upstream),
                        )
                    attempts.append(Attempt(upstream.name, "http_error", response.status_code))
                    if self._retryable_status(response.status_code):
                        self._record_retryable_failure(upstream)
                        continue
                    self._record_upstream_success(upstream)
                    self._emit_route_decision(
                        virtual_model=virtual.name,
                        stream=False,
                        outcome="http_error",
                        selected_upstream=upstream.name,
                        status_code=response.status_code,
                        attempts=attempts,
                    )
                    return RouterResult(
                        status_code=response.status_code,
                        content=content,
                        media_type=self._content_type(response),
                        headers=self._diagnostic_headers(upstream),
                    )
                except httpx.TimeoutException as exc:
                    if self._retryable_exception(exc):
                        self._record_retryable_failure(upstream)
                    attempts.append(
                        Attempt(upstream.name, "timeout", error_type="TimeoutException")
                    )
                    if (
                        not self._retryable_exception(exc)
                        or not self.config.failover.retry_on_timeout
                    ):
                        return self._all_failed(attempts, virtual.name, stream=False)
                except httpx.TransportError as exc:
                    if self._retryable_exception(exc):
                        self._record_retryable_failure(upstream)
                    attempts.append(
                        Attempt(
                            upstream.name,
                            "connection_error",
                            error_type=type(exc).__name__,
                        )
                    )
                    if (
                        not self._retryable_exception(exc)
                        or not self.config.failover.retry_on_connection_error
                    ):
                        return self._all_failed(attempts, virtual.name, stream=False)
        return self._all_failed(attempts, virtual.name, stream=False)

    def _all_failed(
        self, attempts: list[Attempt], virtual_model: str, *, stream: bool
    ) -> RouterResult:
        self._emit_route_decision(
            virtual_model=virtual_model,
            stream=stream,
            outcome="all_failed",
            selected_upstream=None,
            status_code=503,
            attempts=attempts,
        )
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
            self._emit_route_decision(
                virtual_model=virtual_name,
                stream=True,
                outcome="unknown_model",
                selected_upstream=None,
                status_code=404,
                attempts=[],
            )
            return self._error_result(404, f"unknown virtual model: {virtual_name}")

        attempts: list[Attempt] = []
        for upstream in virtual.upstreams:
            for _ in range(self.config.failover.max_attempts_per_upstream):
                circuit_attempt = self._circuit_open_attempt(upstream)
                if circuit_attempt is not None:
                    attempts.append(circuit_attempt)
                    break
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
                        self._record_upstream_success(upstream)
                        self._emit_route_decision(
                            virtual_model=virtual.name,
                            stream=True,
                            outcome="success",
                            selected_upstream=upstream.name,
                            status_code=response.status_code,
                            attempts=attempts,
                        )
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
                        self._record_retryable_failure(upstream)
                        continue
                    self._record_upstream_success(upstream)
                    self._emit_route_decision(
                        virtual_model=virtual.name,
                        stream=True,
                        outcome="http_error",
                        selected_upstream=upstream.name,
                        status_code=response.status_code,
                        attempts=attempts,
                    )
                    return RouterResult(
                        status_code=response.status_code,
                        content=content,
                        media_type=self._content_type(response),
                        headers=self._diagnostic_headers(upstream),
                    )
                except httpx.TimeoutException as exc:
                    if stream_entered:
                        await stream_cm.__aexit__(type(exc), exc, exc.__traceback__)
                    if self._retryable_exception(exc):
                        self._record_retryable_failure(upstream)
                    attempts.append(
                        Attempt(upstream.name, "timeout", error_type="TimeoutException")
                    )
                    if (
                        not self._retryable_exception(exc)
                        or not self.config.failover.retry_on_timeout
                    ):
                        return self._all_failed(attempts, virtual.name, stream=True)
                except httpx.TransportError as exc:
                    if stream_entered:
                        await stream_cm.__aexit__(type(exc), exc, exc.__traceback__)
                    if self._retryable_exception(exc):
                        self._record_retryable_failure(upstream)
                    attempts.append(
                        Attempt(
                            upstream.name,
                            "connection_error",
                            error_type=type(exc).__name__,
                        )
                    )
                    if (
                        not self._retryable_exception(exc)
                        or not self.config.failover.retry_on_connection_error
                    ):
                        return self._all_failed(attempts, virtual.name, stream=True)

        return self._all_failed(attempts, virtual.name, stream=True)

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
