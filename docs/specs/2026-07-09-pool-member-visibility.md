# Pool Member Visibility — Analysis & Plan

**Issue**: https://github.com/leonbreukelman/richard-router/issues/1  
**Created**: 2026-07-09  
**Status**: Analysis complete, plan drafted

---

## 1. Problem Summary

Currently, `richard-router` logs GET/POST statuses and errors to console but provides **no structured visibility** into:
- Which virtual models are configured
- Pool members (upstreams) per virtual model
- Per-member health status (active/inactive/error rates)
- Error codes by status class (4xx, 5xx) per member
- Active member per pool (which upstream handled the last successful request)

The issue requests a dashboard/solution showing per model/provider: total requests, error counts by status code, error rate trends, and pool member-level breakdown.

---

## 2. Current Architecture Analysis

### Key Components

| File | Role |
|------|------|
| `richard_router/config.py` | Config models: `VirtualModel`, `Upstream`, `RouterConfig` |
| `richard_router/service.py` | `RichardRouter` class: failover logic, request routing, `Attempt` tracking |
| `richard_router/main.py` | FastAPI app: `/health`, `/v1/models`, `/v1/chat/completions` |
| `richard_router/errors.py` | Status/exception classification |

### Current Metrics Collection (Minimal)

In `service.py`, `RichardRouter.chat_completion()` and `open_stream()`:
- Collect `Attempt` objects per upstream tried
- `Attempt` tracks: `upstream` (name), `outcome` (success/http_error/timeout/connection_error), `status_code`, `error_type`
- On total failure, returns 503 with attempts array in error body
- No persistence, no aggregation, no time-windowed metrics

### Existing Endpoints
- `GET /health` → `{ "ok": true, "virtual_models": ["coding"] }`
- `GET /v1/models` → OpenAI-compatible model list (virtual models only)
- `POST /v1/chat/completions` → chat completion with failover

---

## 3. Solution Design

### 3.1 New Endpoint: `GET /v1/pools`

Returns structured pool topology + live metrics per virtual model:

```json
{
  "virtual_models": [
    {
      "name": "coding",
      "owned_by": "richard-router",
      "active_upstream": "nvidia-glm-5.2",
      "upstreams": [
        {
          "name": "nvidia-glm-5.2",
          "base_url": "https://integrate.api.nvidia.com/v1",
          "model": "z-ai/glm-5.2",
          "is_active": true,
          "metrics": {
            "total_requests": 142,
            "successful_requests": 138,
            "failed_requests": 4,
            "errors_by_status": {
              "4xx": 1,
              "5xx": 3
            },
            "errors_by_type": {
              "http_error": 3,
              "timeout": 1,
              "connection_error": 0
            },
            "last_success_ts": "2026-07-09T14:22:10Z",
            "last_failure_ts": "2026-07-09T14:15:30Z"
          }
        },
        {
          "name": "openrouter-glm-5.2",
          "base_url": "https://openrouter.ai/api/v1",
          "model": "z-ai/glm-5.2",
          "is_active": false,
          "metrics": { ... }
        }
      ]
    }
  ]
}
```

### 3.2 Metrics Storage

- **In-memory only** (per process), reset on restart — matches router's stateless design
- Thread-safe via `asyncio.Lock` or `threading.Lock` since FastAPI runs in single-threaded async loop
- Data structure: `dict[virtual_model_name, dict[upstream_name, UpstreamMetrics]]`
- `UpstreamMetrics` dataclass with atomic counters + timestamps

### 3.3 Integration Points

| Location | Change |
|----------|--------|
| `service.py` | Add `MetricsCollector` class; hook into `chat_completion`/`open_stream` after each attempt |
| `main.py` | Add `/v1/pools` endpoint; wire `MetricsCollector` into `RichardRouter` |
| `config.py` | No changes needed (config already has all topology info) |

### 3.4 CLI Command (Optional Stretch)

```bash
richard-router pools  # pretty-prints pool status to console
```

---

## 4. Implementation Plan

### Phase 1: Core Metrics Infrastructure

1. **Add `MetricsCollector` class** (`richard_router/metrics.py` — new file)
   - `record_attempt(virtual_model: str, upstream: str, attempt: Attempt)`
   - `get_snapshot() -> dict` (for `/v1/pools`)
   - Thread-safe counters with `asyncio.Lock`
   - Rolling window optional (start simple: lifetime since startup)

2. **Wire into `RichardRouter`**
   - Accept optional `metrics: MetricsCollector | None` in `__init__`
   - Call `metrics.record_attempt()` after each upstream attempt in both `chat_completion` and `open_stream`

3. **Expose via `main.py`**
   - Create `MetricsCollector` in `create_app()`
   - Pass to `RichardRouter`
   - Add `GET /v1/pools` endpoint returning snapshot

### Phase 2: Enrichment & Polish

4. **Add derived fields** to snapshot:
   - `active_upstream` (last successful upstream per virtual model)
   - `is_active` per upstream
   - Error rate % calculations

5. **Add CLI subcommand** `richard-router pools`
   - Reuse snapshot logic, pretty-print with `rich` or plain text

6. **Tests**
   - Unit test `MetricsCollector` counters
   - Integration test: make requests → verify `/v1/pools` reflects attempts
   - Test failover scenario increments both upstreams' counters correctly

### Phase 3: Optional Enhancements (Post-MVP)

- Rolling time windows (last 5m, 1h, 24h)
- Prometheus `/metrics` endpoint
- WebSocket for live updates
- Health threshold alerts (e.g., "upstream error rate > 50%")

---

## 5. Scope Lock

| In Scope | Out of Scope |
|----------|--------------|
| `/v1/pools` endpoint with topology + lifetime metrics | Persistent storage / database |
| In-memory metrics collection | Rolling windows, Prometheus, WS |
| CLI `pools` subcommand | Alerting / threshold config |
| Unit + integration tests | Historical trend analysis |

---

## 6. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Metrics add latency to hot path | Use lock-free counters (`threading.Atomic` / `asyncio` primitives); record after response |
| Memory growth unbounded | Fixed-size counters per upstream; no request logs stored |
| Breaks stateless design | Metrics are ephemeral, per-process — no durability contract |
| CLI needs Rich dep | Optional; fall back to JSON/stdio if `rich` not installed |

---

## 7. Next Actions

1. **Create spec file** → this document
2. **Implement Phase 1** (new file `metrics.py`, wire into `service.py` + `main.py`)
3. **Run gates**: `uv run ruff check .` && `uv run pytest -v`
4. **Create PR** per `github-pr` lifecycle mode
5. **Verify** `/v1/pools` returns expected structure against live config

---

## 8. File Changes Summary (Planned)

| File | Change Type |
|------|-------------|
| `richard_router/metrics.py` | **NEW** — `MetricsCollector`, `UpstreamMetrics` |
| `richard_router/service.py` | **MODIFY** — accept `metrics`, record attempts |
| `richard_router/main.py` | **MODIFY** — create collector, add `/v1/pools`, optional CLI |
| `tests/test_metrics.py` | **NEW** — unit tests for collector |
| `tests/test_pools_endpoint.py` | **NEW** — integration test for `/v1/pools` |