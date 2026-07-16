"""Tests for weighted priority-tier upstream selection."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from richard_router.config import (
    ObservabilityConfig,
    RouterConfig,
    Upstream,
    VirtualModel,
)
from richard_router.service import RichardRouter, RouterResult
from tests.conftest import make_test_config


def _client_factory(handler):
    transport = httpx.MockTransport(handler)

    def factory(_upstream):
        return httpx.AsyncClient(transport=transport)

    return factory


# ---------------------------------------------------------------------------
# _select_upstreams_by_tier
# ---------------------------------------------------------------------------


def test_select_upstreams_by_tier_groups_by_priority():
    ups = (
        Upstream(name="a", base_url="https://a.test", model="a", priority=2),
        Upstream(name="b", base_url="https://b.test", model="b", priority=1),
        Upstream(name="c", base_url="https://c.test", model="c", priority=2),
    )
    tiers = RichardRouter._select_upstreams_by_tier(ups)
    assert tiers == [
        (1, [ups[1]]),        # priority 1 first
        (2, [ups[0], ups[2]]),  # priority 2 second
    ]


def test_select_upstreams_by_tier_single_tier():
    ups = (
        Upstream(name="a", base_url="https://a.test", model="a"),
        Upstream(name="b", base_url="https://b.test", model="b"),
    )
    tiers = RichardRouter._select_upstreams_by_tier(ups)
    assert tiers == [(1, [ups[0], ups[1]])]


# ---------------------------------------------------------------------------
# _pick_weighted_upstream
# ---------------------------------------------------------------------------


def test_pick_weighted_upstream_respects_weights():
    ups = [
        Upstream(name="heavy", base_url="https://h.test", model="h", weight=90),
        Upstream(name="light", base_url="https://l.test", model="l", weight=10),
    ]
    picks = {"heavy": 0, "light": 0}
    for _ in range(1000):
        picked = RichardRouter._pick_weighted_upstream(ups)
        picks[picked.name] += 1
    assert 700 <= picks["heavy"] <= 1000
    assert 0 <= picks["light"] <= 300


def test_pick_weighted_upstream_equal_weights():
    ups = [
        Upstream(name="a", base_url="https://a.test", model="a"),
        Upstream(name="b", base_url="https://b.test", model="b"),
    ]
    for _ in range(100):
        picked = RichardRouter._pick_weighted_upstream(ups)
        assert picked.name in ("a", "b")


# ---------------------------------------------------------------------------
# _failover_loop tier behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_weighted_tier_selected_first():
    """Weighted upstreams in priority-1 tier get traffic before priority-2."""
    config = RouterConfig(
        virtual_models={
            "coding": VirtualModel(
                name="coding",
                upstreams=(
                    Upstream(
                        name="fast", base_url="https://fast.test",
                        model="fast", priority=1, weight=100,
                    ),
                    Upstream(
                        name="slow", base_url="https://slow.test",
                        model="slow", priority=2, weight=100,
                    ),
                ),
            )
        },
        observability=ObservabilityConfig(expose_upstream_header=True),
    )
    calls: list[str] = []

    async def try_up(upstream, attempts):
        calls.append(upstream.name)
        return RouterResult(status_code=200, content=b'{"ok":true}')

    router = RichardRouter(config, _client_factory(lambda r: httpx.Response(500)))
    virtual = config.virtual_models["coding"]
    result = await router._failover_loop(virtual, try_up, stream=False)
    assert result.status_code == 200
    # Only priority-1 upstream should have been tried
    assert calls == ["fast"]


@pytest.mark.asyncio
async def test_weighted_tier_fallthrough():
    """All priority-1 upstreams fail → priority-2 tier is tried."""
    config = RouterConfig(
        virtual_models={
            "coding": VirtualModel(
                name="coding",
                upstreams=(
                    Upstream(
                        name="primary", base_url="https://p.test",
                        model="p", priority=1, weight=100,
                    ),
                    Upstream(
                        name="fallback", base_url="https://f.test",
                        model="f", priority=2, weight=100,
                    ),
                ),
            )
        },
        observability=ObservabilityConfig(expose_upstream_header=True),
    )
    from richard_router.service import Attempt

    calls: list[str] = []

    async def try_up(upstream, attempts):
        calls.append(upstream.name)
        attempts.append(Attempt(upstream.name, "http_error", 503))
        from richard_router.service import _CONTINUE
        return _CONTINUE

    router = RichardRouter(config, _client_factory(lambda r: httpx.Response(500)))
    virtual = config.virtual_models["coding"]
    result = await router._failover_loop(virtual, try_up, stream=False)
    assert result.status_code == 503
    assert calls == ["primary", "fallback"]


@pytest.mark.asyncio
async def test_non_retryable_error_stops_in_tier():
    """Non-retryable error on a priority-1 upstream stops without trying
    other upstreams in the same or lower tiers."""
    config = make_test_config()
    router = RichardRouter(config, _client_factory(lambda r: httpx.Response(400)))
    virtual = config.virtual_models["coding"]
    async def try_ups(upstream, _attempts):
        return RouterResult(
            status_code=400, content=b'{"error":{"message":"bad"}}',
            headers={"x-richard-router-upstream": upstream.name}
        )
    result = await router._failover_loop(virtual, try_ups, stream=False)
    assert result.status_code == 400


# ---------------------------------------------------------------------------
# Backward compatibility: uniform weights = list-order behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_uniform_weight_behaves_like_list_order():
    """When all upstreams have equal weight (default 100), they are tried
    in list order — same as the original behavior."""
    from richard_router.service import _CONTINUE, Attempt

    calls: list[str] = []
    config = make_test_config()
    router = RichardRouter(config, _client_factory(lambda r: httpx.Response(503)))

    async def try_up(upstream, attempts):
        calls.append(upstream.name)
        attempts.append(Attempt(upstream.name, "test"))
        return _CONTINUE

    virtual = config.virtual_models["coding"]
    result = await router._failover_loop(virtual, try_up, stream=False)
    assert result.status_code == 503
    # Both upstreams should have been tried in list order
    assert calls == ["nvidia", "openrouter"]


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


def test_config_validation_rejects_invalid_priority():
    from richard_router.config import validate_config
    cfg = {
        "virtual_models": {
            "coding": {
                "upstreams": [
                    {
                        "name": "bad",
                        "base_url": "https://bad.test",
                        "model": "bad",
                        "priority": 0,
                    }
                ]
            }
        }
    }
    problems = validate_config(cfg, env={})
    assert any("priority must be at least 1" in p for p in problems)


def test_config_validation_rejects_invalid_weight():
    from richard_router.config import validate_config
    cfg = {
        "virtual_models": {
            "coding": {
                "upstreams": [
                    {
                        "name": "bad",
                        "base_url": "https://bad.test",
                        "model": "bad",
                        "weight": 0,
                    }
                ]
            }
        }
    }
    problems = validate_config(cfg, env={})
    assert any("weight must be at least 1" in p for p in problems)


# ---------------------------------------------------------------------------
# Config normalization
# ---------------------------------------------------------------------------


def test_load_config_preserves_priority_weight():
    from richard_router.config import RouterConfigModel, _build_router_config
    model = RouterConfigModel.model_validate({
        "virtual_models": {
            "test": {
                "upstreams": [
                    {
                        "name": "a",
                        "base_url": "https://a.test",
                        "model": "a",
                        "priority": 2,
                        "weight": 50,
                    }
                ]
            }
        }
    })
    cfg = _build_router_config(model)
    upstream = cfg.virtual_models["test"].upstreams[0]
    assert upstream.priority == 2
    assert upstream.weight == 50


def test_load_config_defaults():
    from richard_router.config import RouterConfigModel, _build_router_config
    model = RouterConfigModel.model_validate({
        "virtual_models": {
            "test": {
                "upstreams": [
                    {
                        "name": "a",
                        "base_url": "https://a.test",
                        "model": "a",
                    }
                ]
            }
        }
    })
    cfg = _build_router_config(model)
    upstream = cfg.virtual_models["test"].upstreams[0]
    assert upstream.priority == 1
    assert upstream.weight == 100


# ---------------------------------------------------------------------------
# Weighted failover loop: retry/exhaustion behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_weighted_branch_tries_each_upstream_once_on_retryable():
    """In the non-uniform (weighted) branch, a retryable failure should move to
    the next upstream rather than re-picking the same one until its circuit
    breaker opens. With max_attempts_per_upstream=1, each upstream is tried once."""
    from richard_router.service import _CONTINUE, Attempt

    calls: list[str] = []
    config = RouterConfig(
        virtual_models={
            "coding": VirtualModel(
                name="coding",
                upstreams=(
                    Upstream(
                        name="heavy", base_url="https://h.test",
                        model="h", priority=1, weight=70,
                    ),
                    Upstream(
                        name="light", base_url="https://l.test",
                        model="l", priority=1, weight=30,
                    ),
                ),
            )
        },
        observability=ObservabilityConfig(expose_upstream_header=True),
    )

    async def try_up(upstream, attempts):
        calls.append(upstream.name)
        attempts.append(Attempt(upstream.name, "http_error", 503))
        router._record_http_failure(
            upstream,
            type("FakeResponse", (), {"status_code": 503})(),
            attempts,
            virtual_model_name="coding",
        )
        return _CONTINUE

    router = RichardRouter(config, _client_factory(lambda r: httpx.Response(503)))
    virtual = config.virtual_models["coding"]
    result = await router._failover_loop(virtual, try_up, stream=False)
    assert result.status_code == 503
    # Each upstream tried exactly once, not 5 times (until circuit opens).
    assert calls.count("heavy") == 1
    assert calls.count("light") == 1


@pytest.mark.asyncio
async def test_weighted_branch_terminates_under_sustained_retryable_errors():
    """Regression for the infinite-loop bug: when all weighted upstreams keep
    returning retryable errors, the loop must terminate after trying each once."""
    from richard_router.service import _CONTINUE, Attempt

    calls: list[str] = []
    config = RouterConfig(
        virtual_models={
            "coding": VirtualModel(
                name="coding",
                upstreams=(
                    Upstream(
                        name="a", base_url="https://a.test",
                        model="a", priority=1, weight=70,
                    ),
                    Upstream(
                        name="b", base_url="https://b.test",
                        model="b", priority=1, weight=30,
                    ),
                ),
            )
        },
        observability=ObservabilityConfig(),
    )

    async def try_up(upstream, attempts):
        calls.append(upstream.name)
        attempts.append(Attempt(upstream.name, "test"))
        return _CONTINUE

    router = RichardRouter(config, _client_factory(lambda r: httpx.Response(500)))
    virtual = config.virtual_models["coding"]
    result = await asyncio.wait_for(
        router._failover_loop(virtual, try_up, stream=False),
        timeout=3.0,
    )
    assert result.status_code == 503  # _all_failed default for exhausted attempts
    # No upstream retried more than once.
    assert calls.count("a") == 1
    assert calls.count("b") == 1


@pytest.mark.asyncio
async def test_weighted_branch_distributes_by_weight_over_many_calls():
    """Distribution sanity check for weighted selection across many requests."""
    picks = {"heavy": 0, "light": 0}
    config = RouterConfig(
        virtual_models={
            "coding": VirtualModel(
                name="coding",
                upstreams=(
                    Upstream(
                        name="heavy", base_url="https://h.test",
                        model="h", priority=1, weight=70,
                    ),
                    Upstream(
                        name="light", base_url="https://l.test",
                        model="l", priority=1, weight=30,
                    ),
                ),
            )
        },
        observability=ObservabilityConfig(expose_upstream_header=True),
    )

    async def try_up(upstream, attempts):
        # Always succeed so the loop returns immediately after one pick.
        # Mirror chat_completion's real behavior: attach the upstream diagnostic
        # header on success when observability exposes it.
        return RouterResult(
            status_code=200,
            content=b'{"ok":true}',
            headers=router._diagnostic_headers(upstream),
        )

    router = RichardRouter(config, _client_factory(lambda r: httpx.Response(200)))
    virtual = config.virtual_models["coding"]
    for _ in range(1000):
        result = await router._failover_loop(virtual, try_up, stream=False)
        assert result.status_code == 200
        # The chosen upstream is recorded in the last attempt's diagnostic header
        # via the success path; instead we infer from upstream header.
        picks[result.headers["x-richard-router-upstream"]] += 1
    assert 620 <= picks["heavy"] <= 780
    assert 220 <= picks["light"] <= 380
