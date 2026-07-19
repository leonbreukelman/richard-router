from __future__ import annotations

import threading
import time

import pytest

from richard_router.metrics import MetricsCollector, UpstreamMetrics

# ── UpstreamMetrics unit tests ──────────────────────────────────────────────


class TestUpstreamMetrics:
    def test_success_recording(self):
        m = UpstreamMetrics()
        m.record("success", 200, None)
        assert m.total_requests == 1
        assert m.success_count == 1
        assert m.error_count == 0
        assert m.consecutive_failures == 0
        assert len(m._window) == 1
        assert m._window[0] is True

    def test_error_recording_by_status(self):
        m = UpstreamMetrics()
        m.record("http_error", 503, None)
        m.record("http_error", 429, None)
        assert m.total_requests == 2
        assert m.success_count == 0
        assert m.error_count == 2
        assert m.consecutive_failures == 2
        assert m.errors_by_code == {503: 1, 429: 1}
        assert m._window[0] is False
        assert m._window[1] is False

    def test_error_recording_by_type(self):
        m = UpstreamMetrics()
        m.record("timeout", None, "TimeoutException")
        m.record("connection_error", None, "ConnectError")
        assert m.total_requests == 2
        assert m.error_count == 2
        assert m.errors_by_type == {"TimeoutException": 1, "ConnectError": 1}
        assert len(m._window) == 2

    def test_latest_error_context_follows_event_order(self):
        m = UpstreamMetrics()
        m.record("http_error", 503, None, "older failure")
        m.record("http_error", 429, None, "latest failure")

        assert m.errors_by_code == {503: 1, 429: 1}
        assert m.latest_error_code == 429
        assert m.latest_error_type is None
        assert m.last_error_message == "latest failure"

        m.record("timeout", None, "AlphaError", "latest typed failure")

        assert m.errors_by_code == {503: 1, 429: 1}
        assert m.errors_by_type == {"AlphaError": 1}
        assert m.latest_error_code is None
        assert m.latest_error_type == "AlphaError"
        assert m.last_error_message == "latest typed failure"

    def test_consecutive_failures_resets_on_success(self):
        m = UpstreamMetrics()
        m.record("http_error", 503, None)
        m.record("http_error", 503, None)
        m.record("http_error", 503, None)
        assert m.consecutive_failures == 3
        m.record("success", 200, None)
        assert m.consecutive_failures == 0
        assert m.success_count == 1
        assert m.latest_error_code is None
        assert m.latest_error_type is None

    def test_rolling_window_evicts_old_entries(self):
        m = UpstreamMetrics()
        # Override window to size 3
        m.record("success", 200, None, window_size=3)
        m.record("success", 200, None, window_size=3)
        m.record("success", 200, None, window_size=3)
        assert len(m._window) == 3
        assert m._window.maxlen == 3
        # Adding a 4th evicts the oldest
        m.record("http_error", 503, None, window_size=3)
        assert len(m._window) == 3
        # Window should have 2 True (hits) + 1 False (miss) = 33% error rate
        assert m.error_rate_pct() == pytest.approx(33.3, abs=0.5)

    def test_record_reuses_window_when_size_is_unchanged(self):
        m = UpstreamMetrics()
        m.record("success", 200, None, window_size=3)
        window = m._window
        m.record("http_error", 503, None, window_size=3)
        assert m._window is window
        assert list(m._window) == [True, False]

    def test_classify_healthy(self):
        m = UpstreamMetrics()
        m.record("success", 200, None)
        assert m.classify() == "healthy"

    def test_classify_degraded_by_consecutive(self):
        m = UpstreamMetrics()
        m.record("success", 200, None)
        m.record("http_error", 503, None)
        m.record("http_error", 503, None)
        m.record("http_error", 503, None)  # consecutive=3 → degraded
        assert m.classify() == "degraded"

    def test_classify_down(self):
        m = UpstreamMetrics()
        for _ in range(5):
            m.record("http_error", 503, None)
        assert m.classify() == "down"

    def test_classify_degraded_by_error_rate(self):
        """Even with low consecutive failures, high error_rate in window triggers degraded."""
        m = UpstreamMetrics()
        # 3 successes then 1 failure → 25% error rate > 20% threshold
        m.record("success", 200, None, window_size=10)
        m.record("success", 200, None, window_size=10)
        m.record("success", 200, None, window_size=10)
        m.record("http_error", 503, None, window_size=10)
        assert m.consecutive_failures == 1  # below degraded_threshold
        assert m.classify(degraded_threshold=3, degraded_error_pct=20.0) == "degraded"

    def test_classify_custom_thresholds(self):
        m = UpstreamMetrics()
        for _ in range(3):
            m.record("http_error", 503, None)
        # 3 failures = 100% error_rate in window, so override error_pct to skip
        c = m.classify
        assert c(down_threshold=10, degraded_threshold=5, degraded_error_pct=100.0) == "healthy"
        assert c(down_threshold=10, degraded_threshold=3, degraded_error_pct=100.0) == "degraded"
        assert c(down_threshold=2, degraded_threshold=1, degraded_error_pct=100.0) == "down"

    def test_empty_window_classifies_healthy(self):
        m = UpstreamMetrics()
        assert m.error_rate_pct() == 0.0
        assert m.classify() == "healthy"

    def test_timestamps_set_on_record(self):
        m = UpstreamMetrics()
        m.record("success", 200, None)
        assert m.last_ok > 0
        assert m.last_error is None

        m.record("http_error", 503, None)
        assert m.last_error is not None
        assert m.last_error > 0
        assert m.last_error >= m.last_ok

    def test_non_2xx_success_outcome_classified_as_error(self):
        """An outcome='success' with a non-2xx code should still count as error."""
        m = UpstreamMetrics()
        m.record("success", 500, None)
        assert m.error_count == 1
        assert m.success_count == 0


# ── MetricsCollector unit tests ─────────────────────────────────────────────


class TestMetricsCollector:
    def test_record_creates_new_entry(self):
        c = MetricsCollector()
        c.record_attempt("vm1", "upstream-a", "success", 200)
        snap = c.snapshot()
        assert "vm1" in snap.virtual_models
        assert len(snap.virtual_models["vm1"]) == 1
        assert snap.virtual_models["vm1"][0]["name"] == "upstream-a"
        assert snap.virtual_models["vm1"][0]["total_requests"] == 1
        assert snap.virtual_models["vm1"][0]["success_count"] == 1

    def test_multiple_upstreams_same_vm(self):
        c = MetricsCollector()
        c.record_attempt("vm1", "primary", "success", 200)
        c.record_attempt("vm1", "primary", "success", 200)
        c.record_attempt("vm1", "fallback", "http_error", 503)
        snap = c.snapshot()
        upstreams = snap.virtual_models["vm1"]
        by_name = {u["name"]: u for u in upstreams}
        assert by_name["primary"]["total_requests"] == 2
        assert by_name["primary"]["success_count"] == 2
        assert by_name["fallback"]["total_requests"] == 1
        assert by_name["fallback"]["error_count"] == 1

    def test_multiple_virtual_models(self):
        c = MetricsCollector()
        c.record_attempt("free_ds_nemo", "nvidia", "success", 200)
        c.record_attempt("free_ds_nemo", "openrouter", "success", 200)
        c.record_attempt("gemini", "google", "http_error", 429)
        snap = c.snapshot()
        assert set(snap.virtual_models) == {"free_ds_nemo", "gemini"}
        assert len(snap.virtual_models["free_ds_nemo"]) == 2
        assert len(snap.virtual_models["gemini"]) == 1

    def test_snapshot_includes_health_state(self):
        c = MetricsCollector(down_threshold=3, degraded_threshold=2)
        c.record_attempt("vm1", "bad-upstream", "http_error", 503)
        c.record_attempt("vm1", "bad-upstream", "http_error", 503)
        snap = c.snapshot()
        entry = snap.virtual_models["vm1"][0]
        assert entry["status"] == "degraded"
        assert entry["consecutive_failures"] == 2
        assert entry["error_count"] == 2

    def test_snapshot_includes_error_breakdown(self):
        c = MetricsCollector()
        c.record_attempt("vm1", "upstream-a", "http_error", 429)
        c.record_attempt("vm1", "upstream-a", "http_error", 503)
        c.record_attempt("vm1", "upstream-a", "http_error", 429)
        c.record_attempt("vm1", "upstream-a", "timeout", None, "TimeoutException")
        snap = c.snapshot()
        entry = snap.virtual_models["vm1"][0]
        assert entry["errors_by_code"] == {429: 2, 503: 1}
        assert entry["errors_by_type"] == {"TimeoutException": 1}
        assert entry["latest_error_code"] is None
        assert entry["latest_error_type"] == "TimeoutException"

    def test_empty_collector_snapshot(self):
        c = MetricsCollector()
        snap = c.snapshot()
        assert snap.virtual_models == {}

    def test_100_plus_upstreams(self):
        """Scale test: 20 virtual models × 5 upstreams each."""
        c = MetricsCollector()
        for vm_idx in range(20):
            vm = f"vm-{vm_idx}"
            for up_idx in range(5):
                up = f"upstream-{up_idx}"
                c.record_attempt(vm, up, "success", 200)
                c.record_attempt(vm, up, "http_error", 429)
        snap = c.snapshot()
        assert len(snap.virtual_models) == 20
        for vm in snap.virtual_models.values():
            assert len(vm) == 5
        total_upstreams = sum(len(v) for v in snap.virtual_models.values())
        assert total_upstreams == 100
        # Verify flat-dict internal storage
        assert len(c._upstreams) == 100

    def test_concurrent_recording(self):
        """Thread safety: 10 threads hammering the collector simultaneously."""
        c = MetricsCollector()
        n_threads = 10
        records_per_thread = 500

        def worker(vm: str, up: str):
            for i in range(records_per_thread):
                c.record_attempt(
                    vm,
                    up,
                    "success" if i % 3 != 0 else "http_error",
                    200 if i % 3 != 0 else 503,
                )

        threads = [
            threading.Thread(target=worker, args=(f"vm-{t}", f"upstream-{t}"))
            for t in range(n_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        snap = c.snapshot()
        assert len(snap.virtual_models) == n_threads
        total = 0
        for vm_list in snap.virtual_models.values():
            for entry in vm_list:
                total += entry["total_requests"]
        assert total == n_threads * records_per_thread

    def test_concurrent_snapshot_during_recording(self):
        """Readers and writers share one lock, so snapshots stay consistent."""
        c = MetricsCollector(window_size=25)
        errors: list[BaseException] = []
        stop = threading.Event()
        start = threading.Barrier(5)
        seen_lock = threading.Lock()
        snapshots_seen = 0

        def writer():
            try:
                start.wait()
                for i in range(2_000):
                    c.record_attempt(
                        "vm1",
                        "upstream-a",
                        "success" if i % 2 == 0 else "http_error",
                        200 if i % 2 == 0 else 503,
                    )
                    if i % 50 == 0:
                        time.sleep(0)
            except BaseException as exc:  # pragma: no cover - assertion reports below
                errors.append(exc)
            finally:
                stop.set()

        def reader():
            nonlocal snapshots_seen
            try:
                start.wait()
                while not stop.is_set():
                    snap = c.snapshot()
                    with seen_lock:
                        snapshots_seen += 1
                    for entries in snap.virtual_models.values():
                        for entry in entries:
                            assert entry["total_requests"] == (
                                entry["success_count"] + entry["error_count"]
                            )
            except BaseException as exc:  # pragma: no cover - assertion reports below
                errors.append(exc)
                stop.set()

        threads = [threading.Thread(target=reader) for _ in range(4)] + [
            threading.Thread(target=writer)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert snapshots_seen > 0
        entry = c.snapshot().virtual_models["vm1"][0]
        assert entry["total_requests"] == 2_000
        assert entry["success_count"] == 1_000
        assert entry["error_count"] == 1_000

    def test_isolated_upstreams(self):
        """Upstream metrics are isolated per (vm, upstream) key."""
        c = MetricsCollector()
        c.record_attempt("vm1", "shared", "success", 200)
        c.record_attempt("vm2", "shared", "http_error", 503)
        snap = c.snapshot()
        vm1_entry = snap.virtual_models["vm1"][0]
        vm2_entry = snap.virtual_models["vm2"][0]
        assert vm1_entry["total_requests"] == 1
        assert vm1_entry["success_count"] == 1
        assert vm2_entry["total_requests"] == 1
        assert vm2_entry["error_count"] == 1
        assert vm1_entry["name"] == "shared"
        assert vm2_entry["name"] == "shared"

    def test_custom_thresholds_propagate_to_classification(self):
        c = MetricsCollector(down_threshold=2, degraded_threshold=1, degraded_error_pct=50.0)
        c.record_attempt("vm1", "up", "http_error", 503)
        c.record_attempt("vm1", "up", "http_error", 503)
        snap = c.snapshot()
        assert snap.virtual_models["vm1"][0]["status"] == "down"

    def test_to_dict_serialization(self):
        c = MetricsCollector()
        c.record_attempt("vm1", "up", "success", 200)
        snap = c.snapshot()
        d = snap.to_dict()
        assert "virtual_models" in d
        assert "vm1" in d["virtual_models"]
