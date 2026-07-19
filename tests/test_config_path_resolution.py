from __future__ import annotations

import logging

import pytest
import yaml
from fastapi.testclient import TestClient

from richard_router.config import load_config
from richard_router.main import cli, create_app


def _write_valid_config(path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "virtual_models": {
                    "coding": {
                        "upstreams": [
                            {
                                "name": "primary",
                                "base_url": "https://primary.test/v1",
                                "model": "real-model",
                            }
                        ]
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _clear_config_env(monkeypatch) -> None:
    monkeypatch.delenv("ROUTER_CONFIG", raising=False)
    monkeypatch.delenv("RICHARD_ROUTER_CONFIG", raising=False)


def test_explicit_missing_cli_config_does_not_use_example(tmp_path, monkeypatch):
    _clear_config_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    _write_valid_config(tmp_path / "config" / "router.example.yaml")
    monkeypatch.setattr(
        "uvicorn.run",
        lambda *args, **kwargs: pytest.fail("CLI started with the example config"),
    )

    with pytest.raises(
        FileNotFoundError, match=r"router config file not found: config/router.yaml"
    ):
        cli(["--config", "config/router.yaml"])


@pytest.mark.parametrize("env_name", ["ROUTER_CONFIG", "RICHARD_ROUTER_CONFIG"])
def test_explicit_missing_env_config_does_not_use_example(tmp_path, monkeypatch, env_name):
    _clear_config_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    _write_valid_config(tmp_path / "config" / "router.example.yaml")
    monkeypatch.setenv(env_name, "config/router.yaml")
    monkeypatch.setenv("UNRELATED_SECRET", "must-not-appear")

    with pytest.raises(FileNotFoundError) as exc_info:
        load_config()

    message = str(exc_info.value)
    assert "router config file not found: config/router.yaml" in message
    assert "must-not-appear" not in message


def test_no_argument_example_fallback_is_announced(tmp_path, monkeypatch, caplog):
    _clear_config_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    example_path = tmp_path / "config" / "router.example.yaml"
    _write_valid_config(example_path)
    caplog.set_level(logging.INFO)

    config = load_config()

    assert "coding" in config.virtual_models
    assert any(
        record.levelno == logging.WARNING
        and "config/router.example.yaml" in record.getMessage()
        and "fallback" in record.getMessage().lower()
        for record in caplog.records
    )


def test_startup_diagnostic_names_active_config_path(tmp_path, monkeypatch, caplog):
    _clear_config_env(monkeypatch)
    config_path = tmp_path / "selected-router.yaml"
    _write_valid_config(config_path)
    monkeypatch.setenv("ROUTER_CONFIG", str(config_path))
    caplog.set_level(logging.INFO)

    app = create_app()

    assert TestClient(app).get("/health").json()["ok"] is True
    assert any(
        record.levelno == logging.INFO
        and str(config_path) in record.getMessage()
        and "config" in record.getMessage().lower()
        for record in caplog.records
    )


def test_validation_and_runtime_share_explicit_path_behavior(tmp_path, monkeypatch, capsys):
    _clear_config_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    _write_valid_config(tmp_path / "config" / "router.example.yaml")

    with pytest.raises(SystemExit) as exc_info:
        cli(["validate", "--config", "config/router.yaml"])

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "router config file not found: config/router.yaml" in captured.err
    assert "router.example.yaml" not in captured.err
    assert captured.out == ""
