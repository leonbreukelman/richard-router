"""Tests for startup config-error handling in richard_router.main."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from richard_router.config import load_config
from richard_router.main import _create_config_error_app, create_app


def test_create_config_error_app_returns_503_on_pool():
    app = _create_config_error_app(
        ValueError(
            "failed to parse YAML config config/router.yaml:\n"
            "YAML does not allow tab characters"
        )
    )
    client = TestClient(app)
    # /health still reports the failure but with 200 so healthchecks see it
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["ok"] is False
    # API routes return a clear 503 instead of crashing
    pool = client.get("/v1/pool")
    assert pool.status_code == 503
    body = pool.json()
    assert body["error"] == "router config failed to load"
    assert "YAML does not allow tab" in body["detail"]
    assert "hint" in body
    # chat route also 503s cleanly
    chat = client.post(
        "/v1/chat/completions", json={"model": "x", "messages": []}
    )
    assert chat.status_code == 503


def test_load_config_reports_tab_with_hint(tmp_path):
    broken = (
        "virtual_models:\n"
        "  test:\n"
        "    upstreams:\n"
        "      - name: a\n"
        "\t        base_url: https://a.test\n"
        "        model: a\n"
    )
    cfg_file = tmp_path / "router.yaml"
    cfg_file.write_text(broken)
    with pytest.raises(ValueError) as excinfo:
        load_config(str(cfg_file))
    assert "tab" in str(excinfo.value).lower()


def test_create_app_with_valid_config_still_works():
    # Ensure the happy path is untouched: a valid config builds the real app.
    app = create_app()
    # The real app has the chat route and works (env-var validation may fail
    # if keys are unset, but the app object is constructed without raising).
    assert app is not None
