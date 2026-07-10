# Pool & Virtual Model Visibility — Metrics Dashboard

**Issue:** [#1 — Add visibility into error status codes received by the router](https://github.com/leonbreukelman/richard-router/issues/1)
**Status:** Spec / Plan (pre-implementation)
**Mode:** `github-pr`

---

## 1. Problem

The router proxies requests to upstream pool members and logs `Attempt` records internally, but there is **no way to inspect**:

- which virtual models are configured and their pool members;
- the **current status** of each pool member (healthy/slow/failing);
- per-member request counts, success rates, or error breakdowns;
- the **active member** currently serving each virtual model (for multi-upstream pools with failover).

When something goes wrong — a provider is returning 5xx, timing out, or rejecting requests — the operator has no insight except reading raw uvicorn logs or scraping error responses. This makes debugging routing issues, identifying unhealthy members, and tracking error trends over time unnecessarily painful.

## 2. Goals

1. **CLI command** (`richard-router status`) — print a terminal table showing every virtual model, its pool members, their current health status, request counts, and error rates.
2. **Metrics endpoint** (`GET /v1/pool`) — expose the same data as JSON so it can be consumed by external monitoring (Prometheus, health dashboards, cron alerts).
3. **In-memory metrics collector** — lightweight, zero-dependency tracking that lives alongside the router; accumulates counts and status snapshots across requests.
4. **Health state tracking** — per-upstream: last-ok timestamp, last-error timestamp, consecutive failure count, and an aggregate health classification (`healthy`, `degraded`, `down`).

Non-goals:
- Persistent storage (metrics reset on restart; keep it simple for a lightweight router).
- Prometheus-native format (plain JSON is sufficient; can be adapted later).
- Time-series trend analysis (last-N-window tracking replaces full history for now).

## 3. Scaling Properties (designed for)

The solution must handle deployments with:
- **Many virtual models**: 50+ virtual models, each with its own pool.
- **Large pools**: 10+ upstream members per virtual model.
- **High throughput**: thousands of requests per minute across all pools.
- **Concurrent access**: FastAPI serves requests on multiple workers/threads.

Design budget per operation:
- `record_attempt()` — O(1) for existing upstream entries: one flat-dict lookup, counter updates, optional error-breakdown update, and one bounded deque append under a short critical section. The first observation for a new `(virtual_model, upstream)` key allocates its metrics record.
- `snapshot()` — O(N) where N = total upstreams across all pools. It computes and copies snapshot entries while holding the collector lock, then returns an immutable response object for serialization.
- **Memory** — bounded by `num_upstreams × metrics_window` rolling-window entries plus small counters and error-breakdown dicts. Exact byte size is Python-runtime dependent; the important guarantee is no growth with request volume after the window is full.

## 4. Proposed Architecture

### 4.1 MetricsCollector (new module: `richard_router/metrics.py`)

Thread-safe in-memory accumulator injected into `RichardRouter`. Data layout:

```
MetricsCollector
└── _upstreams: dict[tuple[virtual_model, upstream_name], UpstreamMetrics]
    ├── total_requests: int            # lock-protected counter
    ├── success_count: int             # lock-protected counter
    ├── error_count: int               # lock-protected counter
    ├── errors_by_code: dict[int, int] # e.g. {429: 3, 503: 1}
    ├── errors_by_type: dict[str, int] # e.g. {"TimeoutException": 2}
    ├── last_ok: float                 # epoch seconds from time.time()
    ├── last_error: float | None
    ├── consecutive_failures: int
    └── _window: deque[bool]           # maxlen=metrics_window; True=success, False=failure
```

Key structural choices for scale:

- **Flat keyed dict**, not nested `vm_dict[upstream]`. A flat `(vm, upstream)` tuple key means `record_attempt()` does a single hash lookup and avoids nested dict churn. The `snapshot()` method groups by virtual model when building the response — a cheap dict grouping pass.
- **`collections.deque(maxlen=window)`** per upstream for the rolling window. Appending is O(1), old entries evaporate automatically. No manual trimming, no unbounded growth.
- **Integer counters** for totals and error breakdowns — not recomputed from the deque on every call. `record_attempt()` increments counters atomically; the deque is only used to compute `error_rate` (percentage of failures in the window) for health classification.
- **`threading.Lock`** guarding `_upstreams` dict mutations and snapshot reads. Writers hold the lock for one dict access plus field mutations on the `UpstreamMetrics` dataclass. Snapshots also build response entries under the same lock so readers cannot observe torn counters or mutating rolling windows.

Concrete `UpstreamMetrics` dataclass:

```python
@dataclass
class UpstreamMetrics:
    total_requests: int = 0
    success_count: int = 0
    error_count: int = 0
    errors_by_code: dict[int, int] = field(default_factory=lambda: {})
    errors_by_type: dict[str, int] = field(default_factory=lambda: {})
    last_ok: float = 0.0  # epoch seconds from time.time()
    last_error: float | None = None
    consecutive_failures: int = 0
    _window: deque[bool] = field(default_factory=lambda: deque(maxlen=100))

    def record(self, outcome: str, status_code: int | None, error_type: str | None) -> None:
        self.total_requests += 1
        if outcome == "success" and status_code and 200 <= status_code < 300:
            self.success_count += 1
            self.consecutive_failures = 0
            self.last_ok = time.time()
            self._window.append(True)
        else:
            self.error_count += 1
            self.consecutive_failures += 1
            self.last_error = time.time()
            if status_code:
                self.errors_by_code[status_code] = self.errors_by_code.get(status_code, 0) + 1
            if error_type:
                self.errors_by_type[error_type] = self.errors_by_type.get(error_type, 0) + 1
            self._window.append(False)
```

### 4.2 Health Classification

```
            ┌─────────────────────────────────┐
            │  consecutive_failures >=        │
            │  down_threshold?                │─── YES → "down"
            └──────────┬──────────────────────┘
                       │ NO
                       ▼
            ┌─────────────────────────────────┐
            │  consecutive_failures >=        │
            │  degraded_threshold?            │─── YES → "degraded"
            └──────────┬──────────────────────┘
                       │ NO
                       ▼
            ┌─────────────────────────────────┐
            │  error_rate (from deque) >      │
            │  degraded_error_pct?            │─── YES → "degraded"
            └──────────┬──────────────────────┘
                       │ NO
                       ▼
                    "healthy"
```

Where `error_rate = sum(not x for x in window) / len(window)` (or 0 if window is empty).

Configurable thresholds (see §4.5):
- `down_threshold` — consecutive failures before "down" (default 5)
- `degraded_threshold` — consecutive failures before "degraded" (default 3)
- `degraded_error_pct` — error rate in window that also triggers "degraded" (default 20.0)

### 4.3 Integration into RichardRouter

The `RichardRouter` class gets an optional `metrics: MetricsCollector | None` parameter. After each attempt (success or failure), the router calls `metrics.record_attempt(...)`:

```python
# In chat_completion() — after a success
if self.metrics:
    self.metrics.record_attempt(virtual.name, upstream.name, "success", response.status_code)

# In chat_completion() — after a failure attempt
if self.metrics:
    self.metrics.record_attempt(virtual.name, upstream.name, outcome, status_code, error_type)
```

The collector keeps the routing-path critical section small: one locked lookup/update and a bounded deque append per attempt.

### 4.4 CLI: `richard-router status`

Extended CLI with a new subcommand. When many virtual models and pool members are configured, the output groups by virtual model with a blank-line separator between groups for readability:

```
Virtual Model      Pool Member                Status      Requests    Success    Errors    Error Rate    Last Active
─────────────────  ────────────────────────  ─────────  ──────────  ─────────  ────────  ────────────  ───────────────────
free_ds_nemo       nvidia-deepseek-v4-flash   healthy           142        138         4          2.8%  2026-07-09 14:32:01
                   openrouter-nemotronultra   healthy            12         12         0          0.0%  2026-07-09 13:15:22
                   opencode-deepseek-v4       degraded            8          5         3         37.5%  2026-07-09 12:44:10

gemini31flashlite  gemini-3.1-flash-lite      healthy            67         65         2          3.0%  2026-07-09 14:30:55
```

Optional CLI flags for large deployments:
- `--vm NAME` — filter to a single virtual model (useful in scripts)
- `--json` — raw JSON output for piped consumption (same shape as `GET /v1/pool`)
- `--url` — override the router address (default `http://127.0.0.1:4000`)

Implementation: the CLI sends a `GET /v1/pool` request to the running router and formats the response as a table.

### 4.5 API: `GET /v1/pool`

New endpoint appended to the FastAPI app:

```json
GET /v1/pool

{
  "virtual_models": {
    "free_ds_nemo": [
      {
        "name": "nvidia-deepseek-v4-flash",
        "status": "healthy",
        "total_requests": 142,
        "success_count": 138,
        "error_count": 4,
        "error_rate_pct": 2.8,
        "errors_by_code": {"429": 3, "503": 1},
        "errors_by_type": {},
        "last_ok": "2026-07-09T14:32:01Z",
        "last_error": "2026-07-09T12:10:05Z",
        "consecutive_failures": 0
      }
    ]
  }
}
```

Key: the endpoint serializes the metrics snapshot **directly** — no iterating over virtual model configs to build the response shape. `MetricsCollector.snapshot()` returns data already grouped by virtual model. This means the endpoint cost is proportional to total upstreams, not to config complexity.

Auth: same inbound API key check as other endpoints.

### 4.6 Observability config extension

```yaml
observability:
  expose_upstream_header: false
  metrics_window: 100            # rolling window size (per upstream) for error_rate computation
  degraded_threshold: 3          # consecutive failures before "degraded"
  down_threshold: 5              # consecutive failures before "down"
  degraded_error_pct: 20.0       # error_rate within window that also triggers "degraded"
```

All default when not specified. `validate_config()` rejects non-positive windows/thresholds, `down_threshold < degraded_threshold`, and `degraded_error_pct` outside 0–100 so bad observability config is surfaced instead of silently masked.

## 5. Scaling Properties

| Dimension | Behavior |
|---|---|
| **Virtual models** | Flat-keyed dict stores `(vm, upstream)` tuples. 50+ virtual models with any number of upstreams — dict is a single hash layer, not nested. |
| **Upstreams per pool** | 10+ upstreams per virtual model — only one entry per upstream regardless of routing attempts. |
| **Request throughput** | Existing-entry `record_attempt()` is one flat-dict lookup, one bounded deque append, and counter updates under a short lock. No benchmark guarantee is claimed; benchmark before relying on a hard throughput target. |
| **Snapshot cost** | O(N) where N = total upstream entries. Grouping by virtual model is a single pass; JSON serialization cost depends on response size and runtime. |
| **Memory bound** | Each upstream has one fixed-size deque plus counters and two small dicts. Memory is bounded by configured upstream cardinality and `metrics_window`, not by total request count. |
| **Concurrent readers** | Snapshot and writes share the same lock. Readers may briefly wait for writers and vice versa, but snapshots are internally consistent. |

## 6. File Changes Summary

| File | Change |
|---|---|
| `richard_router/metrics.py` | **New** — `MetricsCollector`, `UpstreamMetrics`, health classification, snapshot |
| `richard_router/service.py` | Add `metrics: MetricsCollector | None` to `RichardRouter.__init__`; call `record_attempt()` in `chat_completion` and `open_stream` |
| `richard_router/config.py` | Extend `ObservabilityConfig` with `metrics_window`, `degraded_threshold`, `down_threshold`, `degraded_error_pct`; update `ObservabilityConfigModel` |
| `richard_router/main.py` | Add `GET /v1/pool` route; add `richard-router status` CLI subcommand |
| `tests/test_metrics.py` | **New** — unit tests for `MetricsCollector` |
| `tests/test_pool_endpoint.py` | **New** — integration tests for `GET /v1/pool` |
| `docs/specs/2026-07-09-pool-visibility-metrics.md` | This spec |

No changes to: `errors.py`, `redaction.py`, `__init__.py`, config YAML schema (backward-compatible).

## 7. Design Decisions

**Why in-memory, not SQLite/Prometheus?**
The router is a lightweight stateless proxy. Adding a DB dependency or an external metrics system contradicts its design philosophy. If the operator wants persistent metrics, they can scrape `GET /v1/pool` from a cron job into any external system.

**Why a flat keyed dict, not nested `vm_dict[upstream_dict]`?**
Two reasons. (1) Single-level dict does one hash lookup instead of two dict lookups per `record_attempt()` call — matters at high throughput. (2) A flat store cleanly supports virtual models that share an upstream name (unlikely but valid) and avoids ambiguous key-space questions when upstreams are renamed in a config reload.

**Why `deque(maxlen=window)` instead of trimming manually?**
Python's `collections.deque` with a fixed maxlen is O(1) append and automatic eviction of stale entries. No manual slice, no counter drift, no timer-based expiry, no unbounded growth regardless of request rate. The window slides naturally with each request.

**Why a rolling window, not unbounded counters?**
Unbounded counters drift from reality over the lifetime of a long-running process (a provider may have recovered hours ago but the error counter still inflates). A rolling window (last N requests) gives a truthful picture of *current* health.

**Why inject MetricsCollector rather than make it global?**
Testability. The `client_factory` pattern already proves this works well — inject dependencies so tests can use a mock collector or verify calls.

**Why both CLI and API?**
The CLI is the primary operator affordance (fast, no extra tooling). The API enables automation (health check scripts, Discord alerts, Prometheus scraping via an adapter). They share the same data model.

## 8. Implementation Order

1. **`metrics.py`** — `MetricsCollector`, `UpstreamMetrics`, health classification, `snapshot()` method.
2. **`service.py`** — Wire collector into `RichardRouter`, add `record_attempt()` calls at all exit points in `chat_completion()` and `open_stream()`.
3. **Tests** — `test_metrics.py` covering: success recording, error recording by code/type, health state transitions, rolling window boundaries, concurrent access, empty state, scale test (100+ upstreams).
4. **`config.py`** — Extend `ObservabilityConfig` and `ObservabilityConfigModel` with new fields (backward-compatible defaults).
5. **`main.py`** — `GET /v1/pool` endpoint; `richard-router status` CLI command.
6. **Integration tests** — `test_pool_endpoint.py` using `TestClient`.
7. **Certify** — Claude Code Opus review pass.
8. **PR** — Open PR against `main`, verify CI green, merge.

## 9. Open Questions

- Should `GET /v1/pool` be behind a separate auth or share the same inbound key? — **Decision: same auth** (simpler, consistent with existing endpoints).
- Window size defaults: 100 requests? 1000? — **Default 100** (lightweight, good signal for most routers; operators can raise for higher confidence).
- Should the CLI default to `http://127.0.0.1:4000` for the server URL? — **Yes**, with an override flag `--url`.
- Should `error_rate` in the snapshot be a percentage (0–100) or a ratio (0–1)? — **Percentage** (more intuitive in terminal tables).

---

*Prepared for Issue #1 implementation.*
