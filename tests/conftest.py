from __future__ import annotations

from richard_router.config import (
    FailoverConfig,
    ObservabilityConfig,
    RouterConfig,
    Upstream,
    VirtualModel,
)


def make_test_config(
    *,
    primary_url: str = "https://nvidia.test/v1",
    fallback_url: str = "https://openrouter.test/v1",
) -> RouterConfig:
    return RouterConfig(
        virtual_models={
            "coding": VirtualModel(
                name="coding",
                upstreams=(
                    Upstream(
                        name="nvidia",
                        base_url=primary_url,
                        model="nvidia-real-model",
                        api_key_env="TEST_NVIDIA_KEY",
                    ),
                    Upstream(
                        name="openrouter",
                        base_url=fallback_url,
                        model="openrouter-real-model",
                        api_key_env="TEST_OPENROUTER_KEY",
                    ),
                ),
            )
        },
        failover=FailoverConfig(),
        observability=ObservabilityConfig(expose_upstream_header=True),
    )


def make_legacy_inline_config_dict(
    *,
    primary_url: str = "https://nvidia.test/v1",
    fallback_url: str = "https://openrouter.test/v1",
) -> dict:
    return {
        "virtual_models": {
            "coding": {
                "owned_by": "richard-router",
                "upstreams": [
                    {
                        "name": "nvidia",
                        "base_url": primary_url,
                        "model": "nvidia-real-model",
                        "api_key_env": "TEST_NVIDIA_KEY",
                    },
                    {
                        "name": "openrouter",
                        "base_url": fallback_url,
                        "model": "openrouter-real-model",
                        "api_key_env": "TEST_OPENROUTER_KEY",
                    },
                ],
            }
        },
        "observability": {"expose_upstream_header": True},
    }
