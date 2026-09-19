from __future__ import annotations

import json

import httpx
import pytest
import yaml

from richard_router.config import RouterConfig, Upstream, VirtualModel, load_config, validate_config
from richard_router.service import RichardRouter
from tests.conftest import make_test_config


def _client_factory(handler):
    transport = httpx.MockTransport(handler)

    def factory(_upstream):
        return httpx.AsyncClient(transport=transport)

    return factory


def _ok_json(model: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-ok",
            "object": "chat.completion",
            "model": model,
            "choices": [
                {
                    "message": {"role": "assistant", "content": "ok"},
                    "finish_reason": "stop",
                    "index": 0,
                }
            ],
        },
    )


def _provider_pin_config_dict(provider_pin: list[str] | None) -> dict:
    return {
        "providers": {
            "openrouter": {
                "base_url": "https://openrouter.ai/api/v1",
                "api_key_env": "TEST_OPENROUTER_KEY",
            }
        },
        "virtual_models": {
            "coding": {
                "owned_by": "richard-router",
                "context_length": 65536,
                "upstreams": [
                    {
                        "name": "primary",
                        "provider": "openrouter",
                        "model": "deepseek/deepseek-v4-flash-0731",
                        "provider_pin": provider_pin,
                    }
                ],
            }
        },
    }


def _write(tmp_path, data: dict) -> str:
    path = tmp_path / "router.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return str(path)


@pytest.fixture(autouse=True)
def _api_keys(monkeypatch):
    monkeypatch.setenv("TEST_NVIDIA_KEY", "nvidia-secret")
    monkeypatch.setenv("TEST_OPENROUTER_KEY", "openrouter-secret")


def test_provider_pin_normalized_to_tuple(tmp_path):
    cfg = load_config(_write(tmp_path, _provider_pin_config_dict(["relace", "deepseek"])))
    upstream = list(cfg.virtual_models["coding"].upstreams)[0]
    assert upstream.provider_pin == ("relace", "deepseek")


def test_provider_pin_omitted_defaults_empty(tmp_path):
    cfg = load_config(_write(tmp_path, _provider_pin_config_dict(None)))
    upstream = list(cfg.virtual_models["coding"].upstreams)[0]
    assert upstream.provider_pin == ()


def test_provider_pin_empty_list_defaults_empty(tmp_path):
    cfg = load_config(_write(tmp_path, _provider_pin_config_dict([])))
    upstream = list(cfg.virtual_models["coding"].upstreams)[0]
    assert upstream.provider_pin == ()


def test_provider_pin_blank_entries_rejected():
    problems = validate_config(_provider_pin_config_dict(["relace", "  "]))
    assert any("provider_pin entries must be non-empty" in p for p in problems)


def test_rewrite_body_injects_provider_only():
    upstream = Upstream(
        name="primary",
        base_url="https://openrouter.ai/api/v1",
        model="deepseek/deepseek-v4-flash-0731",
        provider_pin=("relace",),
    )
    body = {"model": "whatever", "messages": [{"role": "user", "content": "hi"}]}
    rewritten = RichardRouter._rewrite_body(body, upstream)
    assert rewritten["model"] == "deepseek/deepseek-v4-flash-0731"
    assert rewritten["provider"] == {"only": ["relace"]}
    # original body unmutated
    assert body["model"] == "whatever"


def test_rewrite_body_no_pin_leaves_provider_untouched():
    upstream = Upstream(
        name="primary",
        base_url="https://openrouter.ai/api/v1",
        model="deepseek/deepseek-v4-flash-0731",
    )
    body = {"model": "x", "messages": []}
    rewritten = RichardRouter._rewrite_body(body, upstream)
    assert "provider" not in rewritten


@pytest.mark.asyncio
async def test_forwarded_body_carries_provider_pin():
    """End-to-end: the body sent upstream includes provider: {only:[pin]}."""
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return _ok_json("deepseek/deepseek-v4-flash-0731")

    base = make_test_config()
    cfg = RouterConfig(
        virtual_models={
            "coding": VirtualModel(
                name="coding",
                upstreams=(
                    Upstream(
                        name="openrouter",
                        base_url="https://openrouter.test/v1",
                        model="deepseek/deepseek-v4-flash-0731",
                        provider_pin=("relace",),
                        api_key_env="TEST_OPENROUTER_KEY",
                    ),
                ),
            )
        },
        failover=base.failover,
        observability=base.observability,
    )

    router = RichardRouter(cfg, _client_factory(handler))
    result = await router.chat_completion({"model": "coding", "messages": []})
    assert result.status_code == 200
    assert captured["body"]["provider"] == {"only": ["relace"]}
    assert captured["body"]["model"] == "deepseek/deepseek-v4-flash-0731"