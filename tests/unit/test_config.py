from decimal import Decimal

import pytest
from pydantic import ValidationError

from backend.domain.config import (
    AiSettings,
    ApiSettings,
    BridgeSettings,
    CollectorSettings,
    RuntimeConfigError,
    ServiceSettings,
    load_settings,
)


def config(identity="api", **overrides):
    values = {
        "app_env": "test",
        "environment_id": "paper-test",
        "service_name": identity,
        "database_url": f"postgresql+psycopg://trd_{identity}:unshared-test-password@localhost:5432/trd",
    }
    values.update(overrides)
    return values


@pytest.mark.parametrize(
    "override",
    [
        {"trading_mode": "demo"},
        {"trading_mode": "live"},
        {"enable_live_trading": True},
        {"enable_automation": True},
    ],
)
def test_foundation_cannot_authorize_execution(override):
    with pytest.raises(ValidationError):
        ServiceSettings(**config(**override))


@pytest.mark.parametrize(
    "override",
    [
        {"app_env": "production"},
        {"app_env": "staging"},
        {"paper_request_key": "11" * 32, "paper_response_key": "11" * 32},
        {"paper_request_key": "invalid"},
        {"paper_profile_path": None},
    ],
)
def test_paper_gate_requires_local_profile_and_separate_keys(tmp_path, override):
    profile = tmp_path / "profile.json"
    profile.write_text("{}")
    values = config(
        "risk",
        paper_bridge_enabled=True,
        paper_profile_path=profile,
        paper_request_key="11" * 32,
        paper_response_key="22" * 32,
    )
    values.update(override)
    with pytest.raises(ValidationError):
        BridgeSettings(**values)


def test_paper_gate_defaults_off_and_keys_are_not_api_configuration():
    assert BridgeSettings(**config("risk")).paper_bridge_enabled is False
    assert not hasattr(ApiSettings(**config()), "paper_request_key")


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://postgres:unshared-test-password@localhost:5432/trd",
        "postgresql+psycopg://trd_risk:unshared-test-password@localhost:5432/trd",
        "postgresql://trd_api:unshared-test-password@localhost:5432/trd",
        "sqlite:///trd.db",
    ],
)
def test_runtime_cannot_use_privileged_or_other_role(url):
    with pytest.raises(ValidationError):
        ApiSettings(**config(database_url=url))


def test_invalid_secret_never_appears_in_safe_startup_error(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+psycopg://postgres:leak-canary-value@localhost:5432/trd"
    )
    monkeypatch.setenv("ENVIRONMENT_ID", "paper-test")
    monkeypatch.delenv("ENV_FILE", raising=False)
    with pytest.raises(RuntimeConfigError) as captured:
        load_settings("api")
    assert "leak-canary-value" not in str(captured.value)


def test_service_settings_ignore_foreign_secrets(monkeypatch):
    monkeypatch.setenv("MT5_COMMAND_SIGNING_KEY", "must-never-be-on-api-settings")
    settings = ApiSettings(**config())
    assert "must-never-be-on-api-settings" not in settings.model_dump_json()
    assert not hasattr(settings, "mt5_command_signing_key")


def test_explicit_scoped_file_and_no_automatic_root_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("ENVIRONMENT_ID", raising=False)
    monkeypatch.delenv("ENV_FILE", raising=False)
    contents = "DATABASE_URL=postgresql+psycopg://trd_api:unshared-test-password@localhost:5432/trd\nENVIRONMENT_ID=paper-test\n"
    (tmp_path / ".env").write_text(contents)
    with pytest.raises(RuntimeConfigError):
        load_settings("api")
    scoped = tmp_path / ".env.api"
    scoped.write_text(contents)
    monkeypatch.setenv("ENV_FILE", str(scoped))
    assert load_settings("api").environment_id == "paper-test"
    monkeypatch.setenv("ENV_FILE", str(tmp_path / ".env"))
    with pytest.raises(RuntimeConfigError):
        load_settings("api")


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-0.1", "0", "1.01", 0.01, True])
def test_risk_bound_rejects_nonfinite_out_of_range_or_inexact_input(value):
    with pytest.raises(ValidationError):
        BridgeSettings(**config("risk", hard_max_risk_per_trade=value))


def test_exact_risk_input_and_boolean_env(monkeypatch):
    monkeypatch.setenv("HARD_REQUIRE_STOP_LOSS", "true")
    settings = BridgeSettings(**config("risk", hard_max_risk_per_trade="0.01"))
    assert settings.hard_max_risk_per_trade == Decimal("0.01")
    assert settings.hard_require_stop_loss is True
    monkeypatch.setenv("HARD_REQUIRE_STOP_LOSS", "false")
    with pytest.raises(ValidationError):
        BridgeSettings(**config("risk"))


def test_production_rejects_unsafe_origin_cookie_debug_and_missing_bounds(tmp_path):
    production = config(
        app_env="production", data_dir=tmp_path, log_dir=tmp_path, app_url="https://localhost"
    )
    for change in (
        {"auth_cookie_secure": False},
        {"app_url": "https://public.example"},
        {"log_level": "DEBUG"},
    ):
        with pytest.raises(ValidationError):
            ApiSettings(**{**production, **change})
    with pytest.raises(ValidationError):
        BridgeSettings(**config("risk", app_env="production", data_dir=tmp_path, log_dir=tmp_path))


def test_session_policy_cannot_exceed_hard_lifetimes():
    with pytest.raises(ValidationError):
        ApiSettings(**config(auth_session_ttl_seconds=28_801))
    with pytest.raises(ValidationError):
        ApiSettings(**config(auth_session_ttl_seconds=600, auth_idle_ttl_seconds=1800))


def test_unimplemented_integrations_cannot_be_enabled():
    with pytest.raises(ValidationError):
        CollectorSettings(**config("collector", telegram_enabled=True))
    with pytest.raises(ValidationError):
        AiSettings(**config("ai", ai_provider_mode="openai"))
    assert AiSettings(**config("ai", enable_critic_agent=True)).enable_critic_agent
