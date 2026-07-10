from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

Status = str  # "healthy" | "degraded" | "down"


@dataclass
class UpstreamMetrics:
    """Per-upstream metrics and rolling-window health state.

    All counters are updated atomically inside the MetricsCollector lock.
    The rolling window is a fixed-size deque of booleans (True = success);
    old entries evict automatically so memory is bounded.
    """

    total_requests: int = 0
    success_count: int = 0
    error_count: int = 0
    errors_by_code: dict[int, int] = field(default_factory=lambda: {})
    errors_by_type: dict[str, int] = field(default_factory=lambda: {})
    last_ok: float = 0.0
    last_error: float | None = None
    consecutive_failures: int = 0
    _window: deque[bool] = field(default_factory=lambda: deque(maxlen=100))

    def record(
        self,
        outcome: str,
        status_code: int | None,
        error_type: str | None,
        window_size: int | None = None,
    ) -> None:
        # Production collectors set maxlen at entry creation. The optional
        # window_size hook exists for direct UpstreamMetrics tests and future
        # explicit resizing, not for steady-state request handling.
        if window_size is not None and self._window.maxlen != window_size:
            self._window = deque(self._window, maxlen=window_size)

        self.total_requests += 1
        now = time.time()

        if outcome == "success" and status_code is not None and 200 <= status_code < 300:
            self.success_count += 1
            self.consecutive_failures = 0
            self.last_ok = now
            self._window.append(True)
        else:
            self.error_count += 1
            self.consecutive_failures += 1
            self.last_error = now
            if status_code is not None:
                self.errors_by_code[status_code] = self.errors_by_code.get(status_code, 0) + 1
            if error_type:
                self.errors_by_type[error_type] = self.errors_by_type.get(error_type, 0) + 1
            self._window.append(False)

    def error_rate_pct(self) -> float:
        n = len(self._window)
        if n == 0:
            return 0.0
        failures = sum(1 for v in self._window if not v)
        return (failures / n) * 100.0

    def classify(
        self,
        down_threshold: int = 5,
        degraded_threshold: int = 3,
        degraded_error_pct: float = 20.0,
    ) -> Status:
        if self.consecutive_failures >= down_threshold:
            return "down"
        if self.consecutive_failures >= degraded_threshold:
            return "degraded"
        if self.error_rate_pct() > degraded_error_pct:
            return "degraded"
        return "healthy"


@dataclass
class MetricsSnapshot:
    """Immutable snapshot of all pool metrics.

    Grouped by virtual model so endpoints can serialize directly.
    """

    virtual_models: dict[str, list[dict[str, Any]]]

    def to_dict(self) -> dict[str, Any]:
        return {"virtual_models": self.virtual_models}


def _format_timestamp(epoch_seconds: float) -> str | None:
    if not epoch_seconds:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch_seconds))


class MetricsCollector:
    """Thread-safe in-memory accumulator for upstream attempt metrics.

    Uses a flat keyed dict ``_{(vm_name, upstream_name): UpstreamMetrics}``
    so that ``record_attempt()`` is a single hash lookup. The snapshot
    re-groups by virtual model on read.

    Thread safety: a single lock guards all writes and snapshot reads. Writers
    hold the lock for one dict access plus field updates on the UpstreamMetrics
    dataclass. Snapshots derive response entries while the same lock is held,
    so readers cannot observe torn counters or mutating rolling windows.
    """

    def __init__(
        self,
        window_size: int = 100,
        down_threshold: int = 5,
        degraded_threshold: int = 3,
        degraded_error_pct: float = 20.0,
    ) -> None:
        self._upstreams: dict[tuple[str, str], UpstreamMetrics] = {}
        self._lock = Lock()
        self.window_size = max(1, int(window_size))
        self.down_threshold = down_threshold
        self.degraded_threshold = degraded_threshold
        self.degraded_error_pct = degraded_error_pct

    def record_attempt(
        self,
        virtual_model: str,
        upstream_name: str,
        outcome: str,
        status_code: int | None = None,
        error_type: str | None = None,
    ) -> None:
        key = (virtual_model, upstream_name)
        with self._lock:
            if key not in self._upstreams:
                self._upstreams[key] = UpstreamMetrics(
                    _window=deque(maxlen=self.window_size)
                )
            self._upstreams[key].record(outcome, status_code, error_type)

    def snapshot(self) -> MetricsSnapshot:
        group: dict[str, list[dict[str, Any]]] = {}
        with self._lock:
            for (vm, upstream), m in self._upstreams.items():
                entry: dict[str, Any] = {
                    "name": upstream,
                    "status": m.classify(
                        down_threshold=self.down_threshold,
                        degraded_threshold=self.degraded_threshold,
                        degraded_error_pct=self.degraded_error_pct,
                    ),
                    "total_requests": m.total_requests,
                    "success_count": m.success_count,
                    "error_count": m.error_count,
                    "error_rate_pct": round(m.error_rate_pct(), 1),
                    "errors_by_code": dict(sorted(m.errors_by_code.items())),
                    "errors_by_type": dict(sorted(m.errors_by_type.items())),
                    "last_ok": _format_timestamp(m.last_ok),
                    "last_error": _format_timestamp(m.last_error) if m.last_error else None,
                    "consecutive_failures": m.consecutive_failures,
                }
                group.setdefault(vm, []).append(entry)
        return MetricsSnapshot(virtual_models=group)
