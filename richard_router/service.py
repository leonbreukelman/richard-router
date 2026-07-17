from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import random
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from richard_router.config import HealthCheckConfig, RouterConfig, Upstream, VirtualModel
from richard_router.errors import classify_exception, classify_status
from richard_router.metrics import MetricsCollector
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
        metrics: MetricsCollector | None = None,
    ):
        self.config = config
        self.client_factory = client_factory or default_client_factory
        self.clock = clock or time.monotonic
        self.decision_logger = decision_logger
        self.metrics = metrics
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

    def _circuit_allows_traffic(self, upstream: Upstream) -> bool:
        """Check if the upstream's circuit breaker allows traffic, without side effects."""
        cfg = self.config.failover.circuit_breaker
        if not cfg.enabled:
            return True
        state = self._circuit_breaker_state(upstream)
        if state.opened_at is None:
            return True
        if self.clock() - state.opened_at < cfg.cooldown_seconds:
            return False
        return state.half_open_probes < cfg.half_open_max_probes

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
                {
                    "id": model.name,
                    "object": "model",
                    "owned_by": model.owned_by,
                    "context_length": model.context_length,
                }
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
        configured = self.config.failover.retry_on_status
        if configured is None:
            return classify_status(status_code) == "retryable"
        return classify_status(status_code, set(configured)) == "retryable"

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

    # ------------------------------------------------------------------
    # Shared failover helpers — extracted from chat_completion / open_stream
    # ------------------------------------------------------------------

    def _record_success(
        self,
        upstream: Upstream,
        *,
        virtual_model_name: str,
        status_code: int,
        upstream_name: str,
    ) -> None:
        """Reset circuit breaker and record success metric for an upstream."""
        self._record_upstream_success(upstream)
        if self.metrics:
            self.metrics.record_attempt(
                virtual_model_name, upstream_name, "success", status_code=status_code
            )

    def _record_http_failure(
        self,
        upstream: Upstream,
        response: httpx.Response,
        attempts: list[Attempt],
        *,
        virtual_model_name: str,
        error_message: str | None = None,
    ) -> bool:
        """Record an HTTP-error attempt, update metrics/circuit breaker.

        Returns ``True`` if the failover loop should continue to the next
        upstream (retryable error), ``False`` if the error is terminal
        (non-retryable, returned to the caller).
        """
        attempts.append(Attempt(upstream.name, "http_error", response.status_code))
        if self.metrics:
            self.metrics.record_attempt(
                virtual_model_name,
                upstream.name,
                "http_error",
                status_code=response.status_code,
                error_message=error_message,
            )
        if self._retryable_status(response.status_code):
            self._record_retryable_failure(upstream)
            return True
        self._record_upstream_success(upstream)
        return False

    def _record_transport_failure(
        self,
        upstream: Upstream,
        exc: Exception,
        attempts: list[Attempt],
        *,
        virtual_model_name: str,
    ) -> bool:
        """Record a transport-level failure (timeout, connection error).

        Returns ``True`` if the failover loop should continue, ``False`` if
        the error is terminal.
        """
        retryable = self._retryable_exception(exc)
        if retryable:
            self._record_retryable_failure(upstream)

        if isinstance(exc, httpx.TimeoutException):
            attempts.append(
                Attempt(upstream.name, "timeout", error_type="TimeoutException")
            )
            if self.metrics:
                self.metrics.record_attempt(
                    virtual_model_name, upstream.name, "timeout", error_type="TimeoutException"
                )
            return retryable and self.config.failover.retry_on_timeout

        if isinstance(exc, httpx.TransportError):
            attempts.append(
                Attempt(
                    upstream.name,
                    "connection_error",
                    error_type=type(exc).__name__,
                )
            )
            if self.metrics:
                self.metrics.record_attempt(
                    virtual_model_name,
                    upstream.name,
                    "connection_error",
                    error_type=type(exc).__name__,
                )
            return retryable and self.config.failover.retry_on_connection_error

        # Non-httpx exception — record and treat as terminal.
        attempts.append(
            Attempt(upstream.name, "error", error_type=type(exc).__name__)
        )
        return False

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

    @staticmethod
    def _select_upstreams_by_tier(
        upstreams: tuple[Upstream, ...],
    ) -> list[tuple[int, list[Upstream]]]:
        """Group upstreams by priority tier, sorted ascending.

        Returns [(1, [up_a, up_b]), (2, [up_c]), ...] where lower priority
        values are tried first.
        """
        tiers: dict[int, list[Upstream]] = {}
        for upstream in upstreams:
            tiers.setdefault(upstream.priority, []).append(upstream)
        return sorted(tiers.items())

    @staticmethod
    def _pick_weighted_upstream(active: list[Upstream]) -> Upstream:
        """Pick an upstream from a list using weighted random selection.

        An upstream with ``weight=70`` is 7× more likely to be picked than
        one with ``weight=10``.  When all weights are equal the selection is
        uniform random.
        """
        total = sum(u.weight for u in active)
        target = random.random() * total
        cumulative = 0.0
        for upstream in active:
            cumulative += upstream.weight
            if target <= cumulative:
                return upstream
        return active[-1]

    async def _failover_loop(
        self,
        virtual: VirtualModel,
        try_upstream: Callable[[Upstream, list[Attempt]], Any],
        *,
        stream: bool,
    ) -> Any:
        """Shared failover iteration loop with priority tiers and weighted selection.

        ``try_upstream`` is an async callable that takes ``(upstream, attempts)``
        and returns either:
        - A ``RouterResult`` or ``RouterStream`` (terminal success/error) → returned immediately.
        - ``_CONTINUE`` (internal sentinel) → loop retries or re-picks from the tier.
        - Raises ``httpx.TimeoutException`` or ``httpx.TransportError`` → recorded and
        continuation decided by failover config.

        Upstreams are first grouped by priority tier (lower = higher priority).
        Within a tier, upstreams are selected by weight.  Only upstreams whose
        circuit breaker allows traffic are in the active pool.  When a tier
        is exhausted the loop falls through to the next lower priority tier.
        """
        attempts: list[Attempt] = []
        tiers = self._select_upstreams_by_tier(virtual.upstreams)

        for _priority, tier in tiers:
            # Detect uniform weights — fall back to list-order iteration
            # for backward compatibility with existing deterministic tests.
            weights = {u.weight for u in tier}
            uniform = len(weights) == 1

            if uniform:
                for upstream in tier:
                    if not self._circuit_allows_traffic(upstream):
                        attempts.append(Attempt(upstream.name, "circuit_open"))
                        continue
                    inner_result = await self._failover_upstream(
                        upstream, try_upstream, attempts, virtual, stream=stream
                    )
                    if inner_result is not None:
                        return inner_result
            else:
                # Non-uniform weights: pick by weight and drop an upstream from
                # the candidate pool once it has exhausted its retries, so the
                # loop does not re-pick a failing upstream indefinitely.
                remaining: list[Upstream] = list(tier)
                while remaining:
                    active = [u for u in remaining if self._circuit_allows_traffic(u)]
                    if not active:
                        break
                    upstream = self._pick_weighted_upstream(active)
                    inner_result = await self._failover_upstream(
                        upstream, try_upstream, attempts, virtual, stream=stream
                    )
                    if inner_result is not None:
                        return inner_result
                    # Upstream exhausted its retries (or its circuit opened) —
                    # remove it so the loop moves to the next candidate.
                    remaining = [u for u in remaining if u is not upstream]
        return self._all_failed(attempts, virtual.name, stream=stream)

    async def _failover_upstream(
        self,
        upstream: Upstream,
        try_upstream: Callable[[Upstream, list[Attempt]], Any],
        attempts: list[Attempt],
        virtual: VirtualModel,
        *,
        stream: bool,
    ) -> Any | None:
        """Try an upstream with ``max_attempts_per_upstream`` retries.

        Returns ``None`` when all retries are exhausted (caller should try
        the next upstream or tier), or a ``RouterResult`` / ``RouterStream``
        when the outcome is terminal (success or non-retryable error).
        """
        for _ in range(self.config.failover.max_attempts_per_upstream):
            circuit_attempt = self._circuit_open_attempt(upstream)
            if circuit_attempt is not None:
                attempts.append(circuit_attempt)
                return None
            try:
                result = await try_upstream(upstream, attempts)
            except httpx.TimeoutException as exc:
                should_continue = self._record_transport_failure(
                    upstream, exc, attempts, virtual_model_name=virtual.name
                )
                if not should_continue:
                    return self._all_failed(attempts, virtual.name, stream=stream)
                continue
            except httpx.TransportError as exc:
                should_continue = self._record_transport_failure(
                    upstream, exc, attempts, virtual_model_name=virtual.name
                )
                if not should_continue:
                    return self._all_failed(attempts, virtual.name, stream=stream)
                continue

            if result is _CONTINUE:
                continue
            return result
        return None

    # ------------------------------------------------------------------
    # Public API — thin callers over shared failover logic
    # ------------------------------------------------------------------

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

        async def try_upstream(upstream: Upstream, attempts: list[Attempt]) -> Any:
            client = self._client_for(upstream)
            response = await client.post(
                upstream.chat_completions_url,
                json=self._rewrite_body(body, upstream),
                headers=self._upstream_headers(upstream),
            )
            content = response.content
            if 200 <= response.status_code < 300:
                self._record_success(
                    upstream,
                    virtual_model_name=virtual.name,
                    status_code=response.status_code,
                    upstream_name=upstream.name,
                )
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

            # HTTP error — extract error message then record
            is_json = "application/json" in response.headers.get("content-type", "")
            error_data = response.json().get("error", {})
            error_message = error_data.get("message", response.text)
            if not is_json:
                error_message = response.text

            should_continue = self._record_http_failure(
                upstream,
                response,
                attempts,
                virtual_model_name=virtual.name,
                error_message=error_message,
            )
            if not should_continue:
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
            return _CONTINUE

        return await self._failover_loop(virtual, try_upstream, stream=False)

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

        async def try_upstream(upstream: Upstream, attempts: list[Attempt]) -> Any:
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
                    self._record_success(
                        upstream,
                        virtual_model_name=virtual.name,
                        status_code=response.status_code,
                        upstream_name=upstream.name,
                    )
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

                should_continue = self._record_http_failure(
                    upstream,
                    response,
                    attempts,
                    virtual_model_name=virtual.name,
                )
                if not should_continue:
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
                return _CONTINUE
            except httpx.TimeoutException as exc:
                if stream_entered:
                    await stream_cm.__aexit__(type(exc), exc, exc.__traceback__)
                raise
            except httpx.TransportError as exc:
                if stream_entered:
                    await stream_cm.__aexit__(type(exc), exc, exc.__traceback__)
                raise

        return await self._failover_loop(virtual, try_upstream, stream=True)

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


class _ContinueSentinel:
    """Sentinel returned by ``try_upstream`` callbacks to signal 'continue to next upstream'."""

    def __repr__(self) -> str:
        return "<_CONTINUE>"


_CONTINUE = _ContinueSentinel()


class HealthCheckTask:
    """Background asyncio task that periodically probes degraded/down pool members.

    On each tick, the task examines the current metrics snapshot, identifies
    upstreams whose ``classify()`` status is in ``probe_statuses``, and sends
    a minimal chat-completion probe directly to the upstream's API using the
    router's own httpx client.  Probe outcomes are recorded through the
    metrics pipeline so ``/v1/pool`` and ``richard-router status`` reflect
    the recovery — including clearing stale error state on success.
    """

    def __init__(
        self,
        router: RichardRouter,
        config: HealthCheckConfig,
        metrics: MetricsCollector,
    ) -> None:
        self._router = router
        self._config = config
        self._metrics = metrics
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run(), name="richard-router-health-check")
        logger.info(
            "health check task started (interval=%ss)", self._config.interval_seconds
        )

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None
        logger.info("health check task stopped")

    async def _run(self) -> None:
        """Main loop: tick, sleep interval, repeat until stopped."""
        while not self._stop_event.is_set():
            try:
                await self._tick()
            except Exception:
                logger.warning("richard_router.health_check_tick_failed", exc_info=True)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self._config.interval_seconds
                )

    async def _tick(self) -> None:
        """Probe all upstreams whose status is in ``probe_statuses``."""
        snapshot = self._metrics.snapshot()
        probe_statuses = set(self._config.probe_statuses)
        cfg = self._router.config

        for vm_name in sorted(snapshot.virtual_models):
            entries = snapshot.virtual_models[vm_name]
            virtual = cfg.virtual_models.get(vm_name)
            if virtual is None:
                continue
            for entry in sorted(entries, key=lambda e: e["name"]):
                if entry["status"] not in probe_statuses:
                    continue
                upstream_name = entry["name"]
                upstream = next(
                    (u for u in virtual.upstreams if u.name == upstream_name), None
                )
                if upstream is None:
                    continue
                await self._probe_upstream(upstream, virtual.name)

    async def _probe_upstream(self, upstream: Upstream, vm_name: str) -> None:
        """Send a minimal probe to one upstream and record the outcome."""
        client = self._router._client_for(upstream)
        probe_body = {
            "model": upstream.model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": self._config.probe_max_tokens,
            "stream": False,
        }
        probe_timeout = httpx.Timeout(
            connect=upstream.connect_timeout_seconds,
            read=self._config.probe_timeout_seconds,
            write=self._config.probe_timeout_seconds,
            pool=self._config.probe_timeout_seconds,
        )
        try:
            response = await client.post(
                upstream.chat_completions_url,
                json=probe_body,
                headers=self._router._upstream_headers(upstream),
                timeout=probe_timeout,
            )
        except httpx.TimeoutException:
            if self._router.config.failover.retry_on_timeout:
                self._router._record_retryable_failure(upstream)
            if self._metrics:
                self._metrics.record_attempt(
                    vm_name, upstream.name, "timeout", error_type="TimeoutException"
                )
            logger.debug("health check probe timeout: %s", upstream.name)
            return
        except httpx.TransportError as exc:
            if self._router.config.failover.retry_on_connection_error:
                self._router._record_retryable_failure(upstream)
            if self._metrics:
                self._metrics.record_attempt(
                    vm_name, upstream.name, "connection_error", error_type=type(exc).__name__
                )
            logger.debug("health check probe transport error: %s", upstream.name)
            return

        if 200 <= response.status_code < 300:
            self._router._record_upstream_success(upstream)
            if self._metrics:
                self._metrics.record_attempt(
                    vm_name, upstream.name, "success", status_code=response.status_code
                )
            logger.debug("health check probe recovered: %s", upstream.name)
            return

        _cfg_status = self._router.config.failover.retry_on_status
        if _cfg_status is None:
            _is_retryable = classify_status(response.status_code) == "retryable"
        else:
            _is_retryable = classify_status(response.status_code, set(_cfg_status)) == "retryable"
        if _is_retryable:
            self._router._record_retryable_failure(upstream)
        else:
            self._router._record_upstream_success(upstream)

        is_json = "application/json" in response.headers.get("content-type", "")
        error_message = response.text
        if is_json:
            with contextlib.suppress(Exception):
                error_message = response.json().get("error", {}).get("message", response.text)

        if self._metrics:
            self._metrics.record_attempt(
                vm_name,
                upstream.name,
                "http_error",
                status_code=response.status_code,
                error_message=error_message,
            )
        logger.debug(
            "health check probe http error: %s status=%s", upstream.name, response.status_code
        )
