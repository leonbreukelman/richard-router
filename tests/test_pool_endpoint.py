from __future__ import annotations

import json

import httpx
import pytest
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
        assert upstreams["openrouter"]["latest_error_code"] == 503
        assert upstreams["openrouter"]["latest_error_type"] is None

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

    @pytest.mark.parametrize(
        ("header_name", "header_value"),
        [
            (b"authorization", b"Bearer \xff"),
            (b"x-api-key", b"\xff"),
        ],
    )
    def test_pool_endpoint_rejects_non_ascii_auth_headers(
        self, monkeypatch, header_name, header_value
    ):
        monkeypatch.setenv("TEST_POOL_AUTH_KEY", "supersecret")
        cfg = RouterConfig(virtual_models={}, inbound_api_key_env="TEST_POOL_AUTH_KEY")
        client = TestClient(create_app(cfg))

        response = client.get("/v1/pool", headers=[(header_name, header_value)])

        assert response.status_code == 401

    def test_upstream_error_secrets_are_redacted_from_pool_and_status_cli(
        self, capsys, monkeypatch
    ):
        import argparse
        import urllib.request

        from richard_router.main import _status_cli

        secrets = {
            "api_key": "sk-" + "a" * 20,
            "authorization": "Bearer " + "b" * 20,
            "cookie": "nvapi-" + "c" * 20,
            "client_secret": "sk-" + "d" * 20,
        }
        error_message = "provider rejected credentials; " + "; ".join(
            f"{key}={value}" for key, value in secrets.items()
        )

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": {"message": error_message}})

        transport = httpx.MockTransport(handler)

        def client_factory(_upstream):
            return httpx.AsyncClient(transport=transport)

        app = create_app(_make_config(), client_factory=client_factory)
        with TestClient(app) as client:
            chat_response = client.post(
                "/v1/chat/completions", json={"model": "coding", "messages": []}
            )
            assert chat_response.status_code == 401

            pool_response = client.get("/v1/pool")

        assert pool_response.status_code == 200
        pool_payload = pool_response.json()
        stored_message = pool_payload["virtual_models"]["coding"][0]["last_error_message"]
        assert "provider rejected credentials" in stored_message
        assert "[REDACTED]" in stored_message
        serialized_pool = json.dumps(pool_payload)
        assert all(secret not in serialized_pool for secret in secrets.values())

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def read(self):
                return json.dumps(pool_payload).encode("utf-8")

        monkeypatch.setattr(urllib.request, "urlopen", lambda *args, **kwargs: FakeResponse())
        args = argparse.Namespace(
            url="http://router.test",
            vm=None,
            json=True,
            api_key_env="",
            timeout=2,
        )

        assert _status_cli(args) == 0
        status_output = capsys.readouterr().out
        assert "provider rejected credentials" in status_output
        assert all(secret not in status_output for secret in secrets.values())


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

    def test_cli_status_separates_virtual_model_groups(self, capsys, monkeypatch):
        import argparse
        import urllib.request

        from richard_router.main import _status_cli

        payload = {
            "virtual_models": {
                "vm-one": [
                    {
                        "name": "up-one",
                        "status": "healthy",
                        "total_requests": 2,
                        "success_count": 2,
                        "error_count": 0,
                        "error_rate_pct": 0.0,
                        "last_ok": "2026-07-10T00:00:00Z",
                        "last_error": None,
                    }
                ],
                "vm-two": [
                    {
                        "name": "up-two",
                        "status": "degraded",
                        "total_requests": 3,
                        "success_count": 1,
                        "error_count": 2,
                        "error_rate_pct": 66.7,
                        "last_ok": None,
                        "last_error": "2026-07-10T00:01:00Z",
                    }
                ],
            }
        }

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def read(self):
                return json.dumps(payload).encode("utf-8")

        monkeypatch.setattr(urllib.request, "urlopen", lambda *args, **kwargs: FakeResponse())

        args = argparse.Namespace(
            url="http://router.test",
            vm=None,
            json=False,
            api_key_env="",
            timeout=2,
        )
        assert _status_cli(args) == 0
        output = capsys.readouterr().out
        assert "vm-one" in output
        assert "vm-two" in output
        assert "\n\nvm-two" in output
        assert not output.endswith("\n\n")

    def test_cli_status_uses_latest_timestamps_and_explicit_error_context(
        self, capsys, monkeypatch
    ):
        import argparse
        import urllib.request

        from richard_router.main import _status_cli

        payload = {
            "virtual_models": {
                "coding": [
                    {
                        "name": "error-after-success",
                        "status": "degraded",
                        "total_requests": 3,
                        "success_count": 1,
                        "error_count": 2,
                        "error_rate_pct": 66.7,
                        "errors_by_code": {"429": 1, "503": 1},
                        "errors_by_type": {},
                        "last_ok": "2026-07-10T20:00:00Z",
                        "last_error": "2026-07-10T21:00:00Z",
                        "latest_error_code": 429,
                        "latest_error_type": None,
                        "last_error_message": "latest rate limit",
                    },
                    {
                        "name": "success-after-error",
                        "status": "healthy",
                        "total_requests": 2,
                        "success_count": 1,
                        "error_count": 1,
                        "error_rate_pct": 50.0,
                        "errors_by_code": {},
                        "errors_by_type": {"ZuluError": 1, "AlphaError": 1},
                        "last_ok": "2026-07-10T22:00:00Z",
                        "last_error": "2026-07-10T21:00:00Z",
                        "latest_error_code": None,
                        "latest_error_type": "AlphaError",
                        "last_error_message": "latest typed failure",
                    },
                ]
            }
        }

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def read(self):
                return json.dumps(payload).encode("utf-8")

        monkeypatch.setattr(urllib.request, "urlopen", lambda *args, **kwargs: FakeResponse())
        args = argparse.Namespace(
            url="http://router.test",
            vm=None,
            json=False,
            api_key_env="",
            timeout=2,
        )

        assert _status_cli(args) == 0
        output = capsys.readouterr().out
        error_row = next(line for line in output.splitlines() if "error-after-success" in line)
        success_row = next(line for line in output.splitlines() if "success-after-error" in line)
        assert "2026-07-10 21:00:00" in error_row
        assert "Code:429 latest rate limit" in error_row
        assert "Code:503" not in error_row
        assert "2026-07-10 22:00:00" in success_row
        assert "Type:AlphaError latest typed failure" in success_row
        assert "Type:ZuluError" not in success_row
