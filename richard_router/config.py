from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

DEFAULT_RETRY_STATUS = (408, 409, 429, 500, 502, 503, 504)
DEFAULT_READ_TIMEOUT_SECONDS = 60.0
DEFAULT_CONNECT_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class Upstream:
    name: str
    base_url: str
    model: str
    api_key_env: str = ""
    timeout_seconds: float = DEFAULT_READ_TIMEOUT_SECONDS
    headers: dict[str, str] = field(default_factory=dict)
    connect_timeout_seconds: float = DEFAULT_CONNECT_TIMEOUT_SECONDS
    write_timeout_seconds: float = DEFAULT_READ_TIMEOUT_SECONDS
    pool_timeout_seconds: float = DEFAULT_READ_TIMEOUT_SECONDS
    priority: int = 1
    weight: int = 100

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
    context_length: int = 128000


@dataclass(frozen=True)
class CircuitBreakerConfig:
    enabled: bool = True
    failure_threshold: int = 5
    cooldown_seconds: float = 30.0
    half_open_max_probes: int = 1


@dataclass(frozen=True)
class FailoverConfig:
    retry_on_status: tuple[int, ...] = DEFAULT_RETRY_STATUS
    retry_on_timeout: bool = True
    retry_on_connection_error: bool = True
    max_attempts_per_upstream: int = 1
    circuit_breaker: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)


@dataclass(frozen=True)
class ObservabilityConfig:
    expose_upstream_header: bool = False
    decision_log_enabled: bool = True
    metrics_window: int = 100
    degraded_threshold: int = 3
    down_threshold: int = 5
    degraded_error_pct: float = 20.0


@dataclass(frozen=True)
class RouterConfig:
    virtual_models: dict[str, VirtualModel]
    failover: FailoverConfig = field(default_factory=FailoverConfig)
    observability: ObservabilityConfig = field(default_factory=ObservabilityConfig)
    inbound_api_key_env: str = ""

    @property
    def inbound_api_key(self) -> str:
        return os.getenv(self.inbound_api_key_env, "").strip() if self.inbound_api_key_env else ""


class ProviderConfigModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    base_url: str = ""
    api_key_env: str = ""
    headers: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: float | None = None
    connect_timeout_seconds: float | None = None
    write_timeout_seconds: float | None = None
    pool_timeout_seconds: float | None = None


class UpstreamConfigModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    provider: str | None = None
    base_url: str | None = None
    api_key_env: str | None = None
    model: str | None = None
    headers: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: float | None = None
    connect_timeout_seconds: float | None = None
    write_timeout_seconds: float | None = None
    pool_timeout_seconds: float | None = None
    priority: int = 1
    weight: int = 100


class VirtualModelConfigModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    owned_by: str = "richard-router"
    context_length: int = 128000
    upstreams: list[UpstreamConfigModel] = Field(default_factory=list)


class CircuitBreakerConfigModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    failure_threshold: int = 5
    cooldown_seconds: float = 30.0
    half_open_max_probes: int = 1


class FailoverConfigModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    retry_on_status: list[int] = Field(default_factory=lambda: list(DEFAULT_RETRY_STATUS))
    retry_on_timeout: bool = True
    retry_on_connection_error: bool = True
    max_attempts_per_upstream: int = 1
    circuit_breaker: CircuitBreakerConfigModel = Field(default_factory=CircuitBreakerConfigModel)


class ObservabilityConfigModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    expose_upstream_header: bool = False
    decision_log_enabled: bool = True
    metrics_window: int = 100
    degraded_threshold: int = 3
    down_threshold: int = 5
    degraded_error_pct: float = 20.0


class AuthConfigModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    api_key_env: str = ""


class RouterConfigModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    providers: dict[str, ProviderConfigModel] = Field(default_factory=dict)
    virtual_models: dict[str, VirtualModelConfigModel] = Field(default_factory=dict)
    failover: FailoverConfigModel = Field(default_factory=FailoverConfigModel)
    observability: ObservabilityConfigModel = Field(default_factory=ObservabilityConfigModel)
    auth: AuthConfigModel = Field(default_factory=AuthConfigModel)


ConfigInput = RouterConfig | RouterConfigModel | Mapping[str, Any]


def _as_headers(raw: Any) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        return {}
    return {str(k): str(v) for k, v in raw.items() if v is not None}


def _env_has_value(env: Mapping[str, str], name: str) -> bool:
    return bool(str(env.get(name, "")).strip())


def _validate_circuit_breaker_values(
    circuit_breaker: CircuitBreakerConfigModel | CircuitBreakerConfig,
) -> list[str]:
    problems: list[str] = []
    if circuit_breaker.failure_threshold < 1:
        problems.append("failover.circuit_breaker.failure_threshold must be at least 1")
    if circuit_breaker.cooldown_seconds < 0:
        problems.append("failover.circuit_breaker.cooldown_seconds must be non-negative")
    if circuit_breaker.half_open_max_probes < 1:
        problems.append("failover.circuit_breaker.half_open_max_probes must be at least 1")
    return problems


def _validate_observability_values(
    observability: ObservabilityConfigModel | ObservabilityConfig,
) -> list[str]:
    problems: list[str] = []
    if observability.metrics_window < 1:
        problems.append("observability.metrics_window must be at least 1")
    if observability.degraded_threshold < 1:
        problems.append("observability.degraded_threshold must be at least 1")
    if observability.down_threshold < 1:
        problems.append("observability.down_threshold must be at least 1")
    if observability.down_threshold < observability.degraded_threshold:
        problems.append(
            "observability.down_threshold must be greater than or equal to "
            "degraded_threshold"
        )
    if not 0 <= observability.degraded_error_pct <= 100:
        problems.append("observability.degraded_error_pct must be between 0 and 100")
    return problems


def _format_pydantic_error(error: dict[str, Any]) -> str:
    loc = ".".join(str(part) for part in error.get("loc", ())) or "config"
    return f"{loc}: {error.get('msg', 'invalid value')}"


def _model_from_config_input(cfg: ConfigInput) -> tuple[RouterConfigModel | None, list[str]]:
    if isinstance(cfg, RouterConfigModel):
        return cfg, []
    if isinstance(cfg, RouterConfig):
        return None, []
    if not isinstance(cfg, Mapping):
        return None, ["config root must be a mapping"]
    try:
        return RouterConfigModel.model_validate(dict(cfg)), []
    except ValidationError as exc:
        return None, [_format_pydantic_error(cast(dict[str, Any], error)) for error in exc.errors()]


def _validate_normalized_config(cfg: RouterConfig, env: Mapping[str, str]) -> list[str]:
    problems: list[str] = []
    problems.extend(_validate_circuit_breaker_values(cfg.failover.circuit_breaker))
    problems.extend(_validate_observability_values(cfg.observability))
    if not cfg.virtual_models:
        problems.append("virtual_models must be a non-empty mapping")
    for virtual_name, virtual in cfg.virtual_models.items():
        if not virtual.upstreams:
            problems.append(f"virtual_models.{virtual_name}.upstreams must be a non-empty list")
        for index, upstream in enumerate(virtual.upstreams):
            prefix = f"virtual_models.{virtual_name}.upstreams[{index}]"
            if not upstream.name:
                problems.append(f"{prefix}.name is required")
            if not upstream.base_url:
                problems.append(f"{prefix}.base_url is required")
            if not upstream.model:
                problems.append(f"{prefix}.model is required")
            if upstream.api_key_env and not _env_has_value(env, upstream.api_key_env):
                problems.append(
                    f"{prefix} env var {upstream.api_key_env} is not set"
                )
            if upstream.priority < 1:
                problems.append(f"{prefix}.priority must be at least 1")
            if upstream.weight < 1:
                problems.append(f"{prefix}.weight must be at least 1")
    return problems


def validate_config(cfg: ConfigInput, env: Mapping[str, str] | None = None) -> list[str]:
    """Return config problems without mutating process state or exposing secret values."""
    effective_env = os.environ if env is None else env
    if isinstance(cfg, RouterConfig):
        return _validate_normalized_config(cfg, effective_env)

    model, problems = _model_from_config_input(cfg)
    if model is None:
        return problems

    problems.extend(_validate_circuit_breaker_values(model.failover.circuit_breaker))
    problems.extend(_validate_observability_values(model.observability))
    if not model.virtual_models:
        problems.append("virtual_models must be a non-empty mapping")
    for virtual_name, virtual in model.virtual_models.items():
        if not virtual.upstreams:
            problems.append(f"virtual_models.{virtual_name}.upstreams must be a non-empty list")
            continue
        for index, upstream in enumerate(virtual.upstreams):
            prefix = f"virtual_models.{virtual_name}.upstreams[{index}]"
            if not upstream.model:
                problems.append(f"{prefix}.model is required")
            if upstream.provider:
                provider = model.providers.get(upstream.provider)
                if provider is None:
                    problems.append(f"{prefix}.provider '{upstream.provider}' is not defined")
                    continue
                if not provider.base_url and not upstream.base_url:
                    problems.append(f"providers.{upstream.provider}.base_url is required")
                api_key_env = (
                    upstream.api_key_env
                    if upstream.api_key_env is not None
                    else provider.api_key_env
                )
            else:
                api_key_env = upstream.api_key_env or ""
                for required in ("name", "base_url", "model"):
                    if not getattr(upstream, required):
                        problems.append(f"{prefix}.{required} is required for inline upstreams")
            if api_key_env and not _env_has_value(effective_env, api_key_env):
                problems.append(f"{prefix} env var {api_key_env} is not set")
            if upstream.priority < 1:
                problems.append(f"{prefix}.priority must be at least 1")
            if upstream.weight < 1:
                problems.append(f"{prefix}.weight must be at least 1")
    return problems


def _resolve_config_path(path: str | Path | None = None) -> Path:
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
    return config_path


def read_config_data(path: str | Path | None = None) -> dict[str, Any]:
    config_path = _resolve_config_path(path)
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        hint = str(exc).strip()
        if "\t" in hint:
            hint = (
                "YAML does not allow tab characters for indentation — "
                "replace tabs with spaces. " + hint
            )
        raise ValueError(f"failed to parse YAML config {config_path}:\n{hint}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"config root must be a mapping: {config_path}")
    return raw


def _coalesce_float(*values: float | None, default: float) -> float:
    for value in values:
        if value is not None:
            return float(value)
    return default


def _normalize_upstream(
    providers: Mapping[str, ProviderConfigModel], upstream: UpstreamConfigModel
) -> Upstream:
    provider = providers[upstream.provider] if upstream.provider else None
    provider_headers = _as_headers(provider.headers if provider else None)
    upstream_headers = _as_headers(upstream.headers)
    headers = {**provider_headers, **upstream_headers}
    model = str(upstream.model or "")
    provider_name = str(upstream.provider or "")
    name = upstream.name or (f"{provider_name}:{model}" if provider_name else "")
    return Upstream(
        name=str(name),
        base_url=str(upstream.base_url or (provider.base_url if provider else "")),
        model=model,
        api_key_env=str(
            upstream.api_key_env
            if upstream.api_key_env is not None
            else (provider.api_key_env if provider else "")
        ),
        timeout_seconds=_coalesce_float(
            upstream.timeout_seconds,
            provider.timeout_seconds if provider else None,
            default=DEFAULT_READ_TIMEOUT_SECONDS,
        ),
        headers=headers,
        connect_timeout_seconds=_coalesce_float(
            upstream.connect_timeout_seconds,
            provider.connect_timeout_seconds if provider else None,
            default=DEFAULT_CONNECT_TIMEOUT_SECONDS,
        ),
        write_timeout_seconds=_coalesce_float(
            upstream.write_timeout_seconds,
            provider.write_timeout_seconds if provider else None,
            default=DEFAULT_READ_TIMEOUT_SECONDS,
        ),
        pool_timeout_seconds=_coalesce_float(
            upstream.pool_timeout_seconds,
            provider.pool_timeout_seconds if provider else None,
            default=DEFAULT_READ_TIMEOUT_SECONDS,
        ),
        priority=max(1, int(upstream.priority)),
        weight=max(1, int(upstream.weight)),
    )


def _build_router_config(model: RouterConfigModel) -> RouterConfig:
    retry_status = model.failover.retry_on_status or list(DEFAULT_RETRY_STATUS)
    circuit_breaker = CircuitBreakerConfig(
        enabled=bool(model.failover.circuit_breaker.enabled),
        failure_threshold=max(1, int(model.failover.circuit_breaker.failure_threshold)),
        cooldown_seconds=max(0.0, float(model.failover.circuit_breaker.cooldown_seconds)),
        half_open_max_probes=max(1, int(model.failover.circuit_breaker.half_open_max_probes)),
    )
    failover = FailoverConfig(
        retry_on_status=tuple(int(x) for x in retry_status),
        retry_on_timeout=bool(model.failover.retry_on_timeout),
        retry_on_connection_error=bool(model.failover.retry_on_connection_error),
        max_attempts_per_upstream=max(1, int(model.failover.max_attempts_per_upstream)),
        circuit_breaker=circuit_breaker,
    )
    virtual_models: dict[str, VirtualModel] = {}
    for model_name, model_cfg in model.virtual_models.items():
        upstreams = tuple(
            _normalize_upstream(model.providers, upstream) for upstream in model_cfg.upstreams
        )
        virtual_models[str(model_name)] = VirtualModel(
            name=str(model_name), upstreams=upstreams, owned_by=str(model_cfg.owned_by),
            context_length=model_cfg.context_length,
        )
    return RouterConfig(
        virtual_models=virtual_models,
        failover=failover,
        observability=ObservabilityConfig(
            expose_upstream_header=bool(model.observability.expose_upstream_header),
            decision_log_enabled=bool(model.observability.decision_log_enabled),
            metrics_window=int(model.observability.metrics_window),
            degraded_threshold=int(model.observability.degraded_threshold),
            down_threshold=int(model.observability.down_threshold),
            degraded_error_pct=float(model.observability.degraded_error_pct),
        ),
        inbound_api_key_env=str(model.auth.api_key_env or ""),
    )


def load_config(
    path: str | Path | None = None, *, env: Mapping[str, str] | None = None
) -> RouterConfig:
    raw = read_config_data(path)
    problems = validate_config(raw, env=env)
    if problems:
        details = "\n".join(f"- {problem}" for problem in problems)
        raise ValueError(f"invalid router config:\n{details}")
    model = RouterConfigModel.model_validate(raw)
    return _build_router_config(model)
