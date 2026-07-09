from __future__ import annotations

import copy

import pytest
import yaml

from richard_router.config import load_config, validate_config


def _write_yaml(tmp_path, name: str, data: dict) -> str:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return str(path)


def _provider_reference_config() -> dict:
    return {
        "providers": {
            "test-provider": {
                "base_url": "https://provider.test/v1",
                "api_key_env": "TEST_PROVIDER_API_KEY",
                "timeout_seconds": 30,
                "headers": {"X-Test": "provider"},
            }
        },
        "virtual_models": {
            "coding": {
                "owned_by": "richard-router",
                "upstreams": [
                    {
                        "name": "primary",
                        "provider": "test-provider",
                        "model": "real-model",
                    }
                ],
            }
        },
    }


def _legacy_inline_config() -> dict:
    return {
        "virtual_models": {
            "coding": {
                "owned_by": "richard-router",
                "upstreams": [
                    {
                        "name": "primary",
                        "base_url": "https://provider.test/v1",
                        "api_key_env": "TEST_PROVIDER_API_KEY",
                        "model": "real-model",
                        "timeout_seconds": 30,
                        "headers": {"X-Test": "provider"},
                    }
                ],
            }
        },
    }


def test_provider_reference_and_inline_forms_normalize_identically(tmp_path):
    env = {"TEST_PROVIDER_API_KEY": "present"}
    provider_cfg = load_config(
        _write_yaml(tmp_path, "provider.yaml", _provider_reference_config()), env=env
    )
    inline_cfg = load_config(_write_yaml(tmp_path, "inline.yaml", _legacy_inline_config()), env=env)

    assert provider_cfg.virtual_models["coding"] == inline_cfg.virtual_models["coding"]


def test_validate_config_reports_dangling_provider_reference():
    raw = _provider_reference_config()
    raw["virtual_models"]["coding"]["upstreams"][0]["provider"] = "missing"

    problems = validate_config(raw, env={"TEST_PROVIDER_API_KEY": "present"})

    assert "provider 'missing' is not defined" in "\n".join(problems)


def test_load_config_raises_on_dangling_provider_reference(tmp_path):
    raw = _provider_reference_config()
    raw["virtual_models"]["coding"]["upstreams"][0]["provider"] = "missing"

    with pytest.raises(ValueError, match="provider 'missing' is not defined"):
        load_config(_write_yaml(tmp_path, "dangling.yaml", raw), env={})


def test_validate_config_reports_unset_provider_env_var():
    problems = validate_config(_provider_reference_config(), env={})

    assert "TEST_PROVIDER_API_KEY" in "\n".join(problems)
    assert "present" not in "\n".join(problems)


def test_empty_upstream_list_is_invalid():
    raw = _provider_reference_config()
    raw["virtual_models"]["coding"]["upstreams"] = []

    problems = validate_config(raw, env={})

    assert "virtual_models.coding.upstreams must be a non-empty list" in problems


def test_example_file_provider_form_parses_and_documents_inline_backcompat():
    cfg = load_config(
        "config/router.example.yaml",
        env={"NVIDIA_API_KEY": "present", "OPENROUTER_API_KEY": "present"},
    )
    with open("config/router.example.yaml", encoding="utf-8") as config_file:
        text = config_file.read()

    assert list(cfg.virtual_models) == ["coding"]
    assert cfg.failover.circuit_breaker.enabled is True
    assert cfg.failover.circuit_breaker.failure_threshold == 5
    assert cfg.failover.circuit_breaker.cooldown_seconds == 30.0
    assert cfg.failover.circuit_breaker.half_open_max_probes == 1
    assert cfg.observability.decision_log_enabled is True
    assert "provider: nvidia" in text
    assert "circuit_breaker:" in text
    assert "decision_log_enabled: true" in text
    assert "Legacy inline form remains supported" in text


def test_legacy_inline_fixture_still_parses(tmp_path):
    raw = copy.deepcopy(_legacy_inline_config())
    cfg = load_config(
        _write_yaml(tmp_path, "legacy-inline.yaml", raw),
        env={"TEST_PROVIDER_API_KEY": "present"},
    )

    assert cfg.virtual_models["coding"].upstreams[0].base_url == "https://provider.test/v1"


def test_circuit_breaker_config_validation_reports_invalid_values():
    raw = _provider_reference_config()
    raw["failover"] = {
        "circuit_breaker": {
            "failure_threshold": 0,
            "cooldown_seconds": -1,
            "half_open_max_probes": 0,
        }
    }

    problems = validate_config(raw, env={"TEST_PROVIDER_API_KEY": "present"})

    assert "failover.circuit_breaker.failure_threshold must be at least 1" in problems
    assert "failover.circuit_breaker.cooldown_seconds must be non-negative" in problems
    assert "failover.circuit_breaker.half_open_max_probes must be at least 1" in problems
