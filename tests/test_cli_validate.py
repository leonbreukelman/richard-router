from __future__ import annotations

import pytest
import yaml

from richard_router.main import cli


def _write_yaml(tmp_path, data: dict) -> str:
    path = tmp_path / "router.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return str(path)


def _config(api_key_env: str = "CLI_VALIDATE_API_KEY") -> dict:
    return {
        "providers": {
            "primary": {
                "base_url": "https://primary.test/v1",
                "api_key_env": api_key_env,
            }
        },
        "virtual_models": {
            "coding": {
                "upstreams": [
                    {
                        "provider": "primary",
                        "model": "real-model",
                    }
                ]
            }
        },
    }


def test_validate_cli_unset_env_var_exits_nonzero(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("CLI_VALIDATE_API_KEY", raising=False)
    config_path = _write_yaml(tmp_path, _config())

    with pytest.raises(SystemExit) as exc:
        cli(["validate", "--config", config_path])

    captured = capsys.readouterr()
    assert exc.value.code == 1
    assert "CLI_VALIDATE_API_KEY" in captured.err
    assert captured.out == ""


def test_validate_cli_dangling_provider_exits_nonzero(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CLI_VALIDATE_API_KEY", "present")
    raw = _config()
    raw["virtual_models"]["coding"]["upstreams"][0]["provider"] = "missing"
    config_path = _write_yaml(tmp_path, raw)

    with pytest.raises(SystemExit) as exc:
        cli(["validate", "--config", config_path])

    captured = capsys.readouterr()
    assert exc.value.code == 1
    assert "provider 'missing' is not defined" in captured.err
    assert captured.out == ""


def test_validate_cli_configured_env_var_exits_zero(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CLI_VALIDATE_API_KEY", "present")
    config_path = _write_yaml(tmp_path, _config())

    with pytest.raises(SystemExit) as exc:
        cli(["validate", "--config", config_path])

    captured = capsys.readouterr()
    assert exc.value.code == 0
    assert captured.out.strip() == "config ok"
    assert captured.err == ""
