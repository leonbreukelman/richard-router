from __future__ import annotations

from fastapi.testclient import TestClient

from richard_router.config import (
    FailoverConfig,
    ObservabilityConfig,
    RouterConfig,
    Upstream,
    VirtualModel,
)
from richard_router.main import create_app


def _make_config() -> RouterConfig:
    return RouterConfig(
        virtual_models={
            "coding": VirtualModel(
                name="coding",
                upstreams=(
                    Upstream(
                        name="nvidia",
                        base_url="https://nvidia.test/v1",
                        model="nvidia-real-model",
                        api_key_env="TEST_NVIDIA_KEY",
                    ),
                    Upstream(
                        name="openrouter",
                        base_url="https://openrouter.test/v1",
                        model="openrouter-real-model",
                        api_key_env="TEST_OPENROUTER_KEY",
                    ),
                ),
            ),
        },
        failover=FailoverConfig(),
        observability=ObservabilityConfig(expose_upstream_header=True),
    )


class TestPoolEndpoint:
    def test_pool_endpoint_returns_empty_when_no_requests(self):
        app = create_app(_make_config())
        client = TestClient(app)
        resp = client.get("/v1/pool")
        assert resp.status_code == 200
        data = resp.json()
        assert "virtual_models" in data
        # Even with no requests, the config knows about the virtual model
        assert data["virtual_models"] == {}

    def test_pool_endpoint_returns_metrics_after_recording(self):
        cfg = _make_config()
        app = create_app(cfg)
        client = TestClient(app)

        # Hit the pool endpoint directly using the metrics collector from the app
        router = app.state.richard_router
        router.metrics.record_attempt("coding", "nvidia", "success", 200)
        router.metrics.record_attempt("coding", "nvidia", "success", 200)
        router.metrics.record_attempt("coding", "openrouter", "http_error", 503)

        resp = client.get("/v1/pool")
        assert resp.status_code == 200
        data = resp.json()
        vms = data["virtual_models"]
        assert "coding" in vms
        upstreams = {u["name"]: u for u in vms["coding"]}
        assert upstreams["nvidia"]["total_requests"] == 2
        assert upstreams["nvidia"]["success_count"] == 2
        assert upstreams["nvidia"]["status"] == "healthy"
        assert upstreams["openrouter"]["total_requests"] == 1
        assert upstreams["openrouter"]["error_count"] == 1
        assert upstreams["openrouter"]["errors_by_code"] == {"503": 1}

    def test_pool_endpoint_auth(self):
        cfg = RouterConfig(
            virtual_models={
                "coding": VirtualModel(
                    name="coding",
                    upstreams=(
                        Upstream(
                            name="test",
                            base_url="https://example.test/v1",
                            model="test-model",
                        ),
                    ),
                ),
            },
            inbound_api_key_env="TEST_POOL_AUTH_KEY",
        )
        import os

        os.environ["TEST_POOL_AUTH_KEY"] = "supersecret"
        app = create_app(cfg)
        client = TestClient(app)

        # No auth → 401
        resp = client.get("/v1/pool")
        assert resp.status_code == 401

        # Correct Bearer auth → 200
        resp = client.get("/v1/pool", headers={"Authorization": "Bearer supersecret"})
        assert resp.status_code == 200

        # Correct x-api-key auth → 200
        resp = client.get("/v1/pool", headers={"x-api-key": "supersecret"})
        assert resp.status_code == 200

        # Wrong auth → 401
        resp = client.get("/v1/pool", headers={"Authorization": "Bearer wrong"})
        assert resp.status_code == 401

        del os.environ["TEST_POOL_AUTH_KEY"]


class TestStatusCLI:
    def test_cli_status_requires_running_server(self):
        """The status subcommand is just routing; actual server test is in pool endpoint tests."""
        import argparse

        from richard_router.main import _status_cli

        args = argparse.Namespace(
            url="http://127.0.0.1:1",
            vm=None,
            json=False,
            api_key_env="",
            timeout=2,
        )
        rc = _status_cli(args)
        assert rc == 1  # connection refused

    def test_cli_status_json_flag_with_no_server(self):
        import argparse

        from richard_router.main import _status_cli

        args = argparse.Namespace(
            url="http://127.0.0.1:1",
            vm=None,
            json=True,
            api_key_env="",
            timeout=2,
        )
        rc = _status_cli(args)
        assert rc == 1
