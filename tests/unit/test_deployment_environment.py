"""Private environment creation/export with independent accounts and role projections."""

from pathlib import Path
from urllib.parse import urlsplit

import pytest
from dotenv import dotenv_values

from infra.scripts import environment

ROOT = Path(__file__).resolve().parents[2]


def test_new_remote_environments_generate_independent_private_credentials(tmp_path):
    paths = [
        environment.prepare_deployment(stage, tmp_path / stage)
        for stage in ("staging", "production")
    ]
    values = [dotenv_values(path, interpolate=False) for path in paths]
    assert values[0]["ENVIRONMENT_ID"] == "staging-paper"
    assert values[1]["ENVIRONMENT_ID"] == "production-paper"
    for field in (
        "POSTGRES_PASSWORD",
        "DASHBOARD_PROXY_SECRET",
        "ADMIN_BOOTSTRAP_PASSWORD",
        "TELEGRAM_SESSION_ENCRYPTION_KEY",
        "MIGRATION_DATABASE_URL",
    ):
        assert values[0][field] != values[1][field]
    assert (
        urlsplit(values[0]["API_DATABASE_URL"]).port != urlsplit(values[1]["API_DATABASE_URL"]).port
    )
    assert values[0]["RUNTIME_STATE_DIR"] != values[1]["RUNTIME_STATE_DIR"]
    assert all(
        value["AI_PROVIDER_MODE"] == "mock"
        and value["ENABLE_LIVE_TRADING"] == "false"
        and value["AUTH_MFA_REQUIRED"] == "true"
        for value in values
    )
    for path in paths:
        with pytest.raises(ValueError):
            environment.prepare_deployment("staging", path.parent)


def test_export_scopes_secrets_and_refuses_incomplete_remote_access(tmp_path, monkeypatch):
    path = environment.prepare_deployment("staging", tmp_path / "operator")
    values = dict(dotenv_values(path, interpolate=False))
    output = tmp_path / "scoped"
    with pytest.raises(ValueError):
        environment.export_environments(values, output)
    assert not output.exists()
    values.update(
        CLOUDFLARE_ACCESS_AUDIENCE="a" * 64,
        OPENROUTER_API_KEY="synthetic-ai-canary",
        CF_ACCESS_CLIENT_ID="synthetic-client-id",
        CF_ACCESS_CLIENT_SECRET="synthetic-client-secret",
    )
    monkeypatch.setenv("AMBIENT_UNSCOPED_SECRET", "must-not-travel")
    environment.export_environments(values, output)
    files = {path.name: dict(dotenv_values(path, interpolate=False)) for path in output.iterdir()}
    dashboard = files[".env.dashboard"]
    assert dashboard["DASHBOARD_ENVIRONMENT_ID"] == "staging-paper"
    assert dashboard["DASHBOARD_ACCESS_MODE"] == "cloudflare"
    assert not any(
        "DATABASE" in key or key.startswith(("OPENROUTER", "TELEGRAM", "MT5", "ADMIN_"))
        for key in dashboard
    )
    assert files[".env.ai"]["OPENROUTER_API_KEY"] == "synthetic-ai-canary"
    for name, projected in files.items():
        assert "AMBIENT_UNSCOPED_SECRET" not in projected
        if name != ".env.ai":
            assert "OPENROUTER_API_KEY" not in projected
        if name != ".env.dashboard":
            assert not any(key.startswith("CF_ACCESS_CLIENT") for key in projected)
    assert files[".env.api"]["DASHBOARD_PROXY_SECRET"] == dashboard["DASHBOARD_PROXY_SECRET"]
    assert "DASHBOARD_PROXY_SECRET" not in files[".env.ai"]
    with pytest.raises(ValueError):
        environment.export_environments(values, output)


def test_remote_state_directory_is_required_and_independent_of_development():
    values = {
        "APP_ENV": "staging",
        "ENVIRONMENT_ID": "staging-paper",
        "API_DATABASE_URL": "unused-synthetic-value",
    }
    with pytest.raises(ValueError):
        environment.runtime_environment("api", values)
    values["RUNTIME_STATE_DIR"] = "relative-state"
    with pytest.raises(ValueError):
        environment.runtime_environment("api", values)
