from __future__ import annotations

from pathlib import Path

import pytest

from paperfetch.core.environment import (
    ENVIRONMENTS,
    LOCAL_PRODUCTION_ROOT,
    environment_spec,
    infer_environment,
    parse_environment,
)
from paperfetch.core.settings import get_settings, reset_settings


pytestmark = [pytest.mark.unit, pytest.mark.contract]


def test_infer_environment_from_interpreter():
    assert (
        infer_environment("/srv/checkout/paperfetch/.venv/bin/python") == "development"
    )
    assert (
        infer_environment(
            str(LOCAL_PRODUCTION_ROOT / "current" / "venv" / "bin" / "python")
        )
        == "production"
    )
    assert infer_environment("/opt/paperfetch/current/venv/bin/python") == "production"
    assert (
        infer_environment("/opt/paperfetch/releases/abc/venv/bin/python")
        == "production"
    )


def test_parse_environment_rejects_unknown():
    with pytest.raises(ValueError, match="SPC_ENVIRONMENT"):
        parse_environment("server-wsl")


def test_production_and_development_have_isolated_roots_and_secrets():
    development = environment_spec("development")
    production = environment_spec("production")
    assert development.secrets_file == Path.home() / ".config" / "spc" / "secrets.env"
    assert production.secrets_file == Path("/opt/paperfetch/config/secrets.env")
    assert development.state_root != production.state_root
    assert development.log_mode == "development"
    assert production.log_mode == "production"
    assert set(ENVIRONMENTS) == {"development", "production"}


def test_local_production_uses_user_release_and_shared_secret_file():
    executable = (
        LOCAL_PRODUCTION_ROOT / "releases" / ("a" * 40) / "venv" / "bin" / "python"
    )
    production = environment_spec("production", executable=str(executable))

    assert production.python_prefix == f"{LOCAL_PRODUCTION_ROOT}/"
    assert production.package_prefix == f"{LOCAL_PRODUCTION_ROOT}/"
    assert production.secrets_file == Path.home() / ".config" / "spc" / "secrets.env"
    assert production.state_root == LOCAL_PRODUCTION_ROOT / "state"
    assert production.data_root == LOCAL_PRODUCTION_ROOT / "data"
    assert production.cache_root == LOCAL_PRODUCTION_ROOT / "cache"
    assert production.log_root == LOCAL_PRODUCTION_ROOT / "logs"
    assert production.install_modes == ("installed",)


def test_load_settings_materializes_inferred_environment(monkeypatch):
    monkeypatch.delenv("SPC_ENVIRONMENT", raising=False)
    reset_settings()
    settings = get_settings()
    assert settings.text("SPC_ENVIRONMENT") in ENVIRONMENTS
    assert settings.text("SPC_ENVIRONMENT") == infer_environment()


def test_schema_config_exposes_environment(capsys):
    from paperfetch.cli.root import main

    assert main(["schema", "config"]) == 0
    import json

    payload = json.loads(capsys.readouterr().out)
    environment = payload["data"]["environment"]
    assert environment["choices"] == ["development", "production"]
    assert environment["current"] in ENVIRONMENTS
    assert environment["matches_runtime"] is True
    names = {item["name"] for item in payload["data"]["fields"]}
    assert "SPC_ENVIRONMENT" in names
