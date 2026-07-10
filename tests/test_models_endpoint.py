from __future__ import annotations

from fastapi.testclient import TestClient

from richard_router.main import create_app
from tests.conftest import make_test_config


def test_models_endpoint_exposes_only_virtual_model():
    client = TestClient(create_app(make_test_config()))
    response = client.get("/v1/models")
    assert response.status_code == 200
    assert response.json() == {
        "object": "list",
        "data": [
            {
                "id": "coding",
                "object": "model",
                "owned_by": "richard-router",
                "context_length": 128000,
            }
        ],
    }


def test_upstream_header_hidden_by_default():
    from richard_router.config import RouterConfig, Upstream, VirtualModel
    from richard_router.service import RichardRouter

    cfg = RouterConfig(
        virtual_models={
            "coding": VirtualModel(
                name="coding",
                upstreams=(
                    Upstream(
                        name="private-upstream", base_url="https://example.test/v1", model="real"
                    ),
                ),
            )
        }
    )
    router = RichardRouter(cfg)
    assert router._diagnostic_headers(next(iter(cfg.virtual_models["coding"].upstreams))) == {}
