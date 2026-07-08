from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_RETRY_STATUS = (408, 409, 429, 500, 502, 503, 504)


@dataclass(frozen=True)
class Upstream:
    name: str
    base_url: str
    model: str
    api_key_env: str = ""
    timeout_seconds: float = 60.0
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def chat_completions_url(self) -> str:
        return self.base_url.rstrip("/") + "/chat/completions"

    @property
    def api_key(self) -> str:
        return os.getenv(self.api_key_env, "").strip() if self.api_key_env else ""


@dataclass(frozen=True)
class VirtualModel:
    name: str
    upstreams: tuple[Upstream, ...]
    owned_by: str = "richard-router"


@dataclass(frozen=True)
class FailoverConfig:
    retry_on_status: tuple[int, ...] = DEFAULT_RETRY_STATUS
    retry_on_timeout: bool = True
    retry_on_connection_error: bool = True
    max_attempts_per_upstream: int = 1


@dataclass(frozen=True)
class ObservabilityConfig:
    expose_upstream_header: bool = False


@dataclass(frozen=True)
class RouterConfig:
    virtual_models: dict[str, VirtualModel]
    failover: FailoverConfig = field(default_factory=FailoverConfig)
    observability: ObservabilityConfig = field(default_factory=ObservabilityConfig)
    inbound_api_key_env: str = ""

    @property
    def inbound_api_key(self) -> str:
        return os.getenv(self.inbound_api_key_env, "").strip() if self.inbound_api_key_env else ""


def _as_headers(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items() if v is not None}


def _load_upstream(raw: dict[str, Any]) -> Upstream:
    missing = [key for key in ("name", "base_url", "model") if not raw.get(key)]
    if missing:
        raise ValueError(f"upstream missing required fields: {', '.join(missing)}")
    return Upstream(
        name=str(raw["name"]),
        base_url=str(raw["base_url"]),
        model=str(raw["model"]),
        api_key_env=str(raw.get("api_key_env") or ""),
        timeout_seconds=float(raw.get("timeout_seconds") or 60.0),
        headers=_as_headers(raw.get("headers")),
    )


def load_config(path: str | Path | None = None) -> RouterConfig:
    config_path = Path(
        path
        or os.getenv("ROUTER_CONFIG")
        or os.getenv("RICHARD_ROUTER_CONFIG")
        or "config/router.yaml"
    )
    if not config_path.exists() and str(config_path) == "config/router.yaml":
        example = Path("config/router.example.yaml")
        if example.exists():
            config_path = example
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"config root must be a mapping: {config_path}")

    failover_raw = raw.get("failover") or {}
    if not isinstance(failover_raw, dict):
        raise ValueError("failover must be a mapping")
    retry_status = failover_raw.get("retry_on_status", DEFAULT_RETRY_STATUS)
    failover = FailoverConfig(
        retry_on_status=tuple(int(x) for x in retry_status),
        retry_on_timeout=bool(failover_raw.get("retry_on_timeout", True)),
        retry_on_connection_error=bool(failover_raw.get("retry_on_connection_error", True)),
        max_attempts_per_upstream=max(
            1,
            int(failover_raw.get("max_attempts_per_upstream", 1)),
        ),
    )

    vm_raw = raw.get("virtual_models") or {}
    if not isinstance(vm_raw, dict) or not vm_raw:
        raise ValueError("virtual_models must be a non-empty mapping")

    virtual_models: dict[str, VirtualModel] = {}
    for model_name, model_cfg in vm_raw.items():
        if not isinstance(model_cfg, dict):
            raise ValueError(f"virtual_models.{model_name} must be a mapping")
        upstreams_raw = model_cfg.get("upstreams") or []
        if not isinstance(upstreams_raw, list) or not upstreams_raw:
            raise ValueError(f"virtual_models.{model_name}.upstreams must be a non-empty list")
        upstreams = tuple(_load_upstream(item) for item in upstreams_raw if isinstance(item, dict))
        if not upstreams:
            raise ValueError(f"virtual_models.{model_name}.upstreams has no valid entries")
        virtual_models[str(model_name)] = VirtualModel(
            name=str(model_name),
            upstreams=upstreams,
            owned_by=str(model_cfg.get("owned_by") or "richard-router"),
        )

    auth_raw = raw.get("auth") or {}
    if auth_raw is None:
        auth_raw = {}
    if not isinstance(auth_raw, dict):
        raise ValueError("auth must be a mapping")

    observability_raw = raw.get("observability") or {}
    if not isinstance(observability_raw, dict):
        raise ValueError("observability must be a mapping")
    observability = ObservabilityConfig(
        expose_upstream_header=bool(observability_raw.get("expose_upstream_header", False))
    )

    return RouterConfig(
        virtual_models=virtual_models,
        failover=failover,
        observability=observability,
        inbound_api_key_env=str(auth_raw.get("api_key_env") or ""),
    )
