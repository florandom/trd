"""Scoped runtime settings. Trading authority remains disabled."""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path
from typing import Literal
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ServiceName = Literal["api", "collector", "ai", "risk", "maintenance", "simulator"]


class RuntimeConfigError(ValueError):
    """A safe configuration error that never contains supplied secret values."""


class ServiceSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        hide_input_in_errors=True,
    )

    service_name: ServiceName = "api"
    app_env: Literal["development", "test", "production"] = "development"
    environment_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    database_url: SecretStr
    trading_mode: Literal["paper", "demo", "live"] = "paper"
    enable_automation: bool = False
    enable_live_trading: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    timezone: str = "Europe/Rome"
    data_dir: Path = Path("var/data")
    log_dir: Path = Path("var/log")
    log_max_bytes: int = Field(default=10_485_760, ge=1024, le=104_857_600)
    log_backup_count: int = Field(default=10, ge=1, le=30)
    heartbeat_interval_seconds: int = Field(default=10, ge=1, le=60)
    redis_enabled: bool = False
    redis_url: SecretStr | None = None

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("TIMEZONE must be an installed IANA timezone") from exc
        return value

    @model_validator(mode="after")
    def validate_service(self) -> ServiceSettings:
        if self.trading_mode != "paper" or self.enable_automation or self.enable_live_trading:
            raise ValueError("Phase 1 supports paper foundation only; automation must be disabled")
        try:
            parsed = urlsplit(self.database_url.get_secret_value())
            if (
                parsed.scheme != "postgresql+psycopg"
                or not parsed.hostname
                or not parsed.path.strip("/")
            ):
                raise ValueError
            if not parsed.username or not parsed.password or not parsed.port:
                raise ValueError
            expected_role = f"trd_{self.service_name}"
            if unquote(parsed.username) != expected_role:
                raise ValueError
            password = unquote(parsed.password)
        except ValueError:
            raise ValueError(
                "DATABASE_URL must use psycopg, explicit port, credentials and the service role"
            ) from None
        if self.app_env == "production":
            if len(password) < 20 or password.lower() in {"changeme", "password", "postgres"}:
                raise ValueError("Production database credentials must be provisioned securely")
            if self.log_level == "DEBUG":
                raise ValueError("Production DEBUG logging is disabled in Phase 1")
            if not self.data_dir.is_absolute() or not self.log_dir.is_absolute():
                raise ValueError("Production DATA_DIR and LOG_DIR must be explicit absolute paths")
        if self.redis_enabled and (self.redis_url is None or not self.redis_url.get_secret_value()):
            raise ValueError("REDIS_URL is required when REDIS_ENABLED is true")
        return self

    def logging_secrets(self) -> tuple[str, ...]:
        """Provide known values to the redactor without serializing settings."""
        values = []
        for name in type(self).model_fields:
            value = getattr(self, name)
            if isinstance(value, SecretStr) and value.get_secret_value():
                values.append(value.get_secret_value())
        password = urlsplit(self.database_url.get_secret_value()).password
        if password:
            values.extend((password, unquote(password)))
        return tuple(values)


class ApiSettings(ServiceSettings):
    service_name: Literal["api"] = "api"
    app_url: str = "http://localhost:3000"
    auth_cookie_secure: bool = True
    auth_session_ttl_seconds: int = Field(default=28_800, ge=60, le=28_800)
    auth_idle_ttl_seconds: int = Field(default=1800, ge=60, le=1800)
    auth_mfa_required: bool = False
    cloudflare_access_issuer: str | None = None
    cloudflare_access_audience: str | None = None

    @model_validator(mode="after")
    def validate_api(self) -> ApiSettings:
        parsed = urlsplit(self.app_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise ValueError("APP_URL must be a trusted HTTP(S) origin without credentials")
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("APP_URL must be an origin, not a path")
        if self.auth_mfa_required:
            raise ValueError("Local MFA is unavailable; remote deployment remains disabled")
        if self.auth_idle_ttl_seconds > self.auth_session_ttl_seconds:
            raise ValueError("Idle session lifetime must not exceed absolute session lifetime")
        if self.app_env == "production":
            if not self.auth_cookie_secure or parsed.scheme != "https":
                raise ValueError("Production requires HTTPS and secure cookies")
            # No Access assertion verification or local MFA is implemented yet.
            # A remote-looking origin must not imply an authenticated dashboard.
            if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
                raise ValueError("Remote production access requires verified external MFA")
        return self


class CollectorSettings(ServiceSettings):
    service_name: Literal["collector"] = "collector"
    telegram_enabled: bool = False
    telegram_api_id: int | None = Field(default=None, ge=1, le=2_147_483_647)
    telegram_api_hash: SecretStr | None = None
    telegram_session_encryption_key: SecretStr | None = None
    telegram_session_key_id: str = Field(default="local-v1", pattern=r"^[A-Za-z0-9_-]{1,64}$")
    telegram_session_path: Path | None = None
    telegram_collector_identity: str = Field(default="primary", pattern=r"^[A-Za-z0-9_-]{1,64}$")
    telegram_poll_seconds: int = Field(default=30, ge=5, le=300)
    telegram_backfill_max_age_seconds: int = Field(default=86400, ge=60, le=604800)
    telegram_history_batch_size: int = Field(default=100, ge=1, le=100)
    telegram_request_timeout_seconds: int = Field(default=20, ge=1, le=30)
    telegram_signal_max_age_seconds: int = Field(default=900, ge=30, le=3600)

    @field_validator("telegram_api_id", mode="before")
    @classmethod
    def empty_api_id(cls, value):
        return None if value == "" else value

    @model_validator(mode="after")
    def validate_collector(self) -> CollectorSettings:
        if self.telegram_enabled:
            self.require_credentials()
        return self

    def require_credentials(self) -> None:
        import re

        if self.telegram_api_id is None or self.telegram_api_hash is None:
            raise ValueError("Telegram application credentials are required")
        if not re.fullmatch(r"[a-fA-F0-9]{32}", self.telegram_api_hash.get_secret_value()):
            raise ValueError("Telegram API hash must use its hexadecimal encoding")
        if self.telegram_session_encryption_key is None or not re.fullmatch(
            r"[a-fA-F0-9]{64}", self.telegram_session_encryption_key.get_secret_value()
        ):
            raise ValueError("Telegram session encryption requires a 256-bit hexadecimal key")
        if self.app_env == "production" and self.telegram_session_path is not None:
            if not self.telegram_session_path.is_absolute():
                raise ValueError("Production Telegram session path must be absolute")


class AiSettings(ServiceSettings):
    service_name: Literal["ai"] = "ai"
    ai_provider_mode: Literal["mock"] = "mock"
    enable_critic_agent: bool = False
    enable_adaptive_memory: bool = False
    ai_hard_daily_budget_usd: Decimal = Field(default=Decimal("0"), ge=0, allow_inf_nan=False)
    ai_hard_monthly_budget_usd: Decimal = Field(default=Decimal("0"), ge=0, allow_inf_nan=False)
    ai_hard_daily_budget_per_agent_usd: Decimal = Field(
        default=Decimal("0"), ge=0, allow_inf_nan=False
    )
    ai_hard_max_cost_per_request_usd: Decimal = Field(
        default=Decimal("0"), ge=0, allow_inf_nan=False
    )
    ai_hard_max_output_tokens: int = Field(default=4096, ge=1, le=4096)
    ai_hard_timeout_seconds: int = Field(default=30, ge=1, le=120)
    ai_signal_max_age_seconds: int = Field(default=900, ge=30, le=3600)
    ai_job_lease_seconds: int = Field(default=180, ge=10, le=300)

    @field_validator(
        "ai_hard_daily_budget_usd",
        "ai_hard_monthly_budget_usd",
        "ai_hard_daily_budget_per_agent_usd",
        "ai_hard_max_cost_per_request_usd",
        mode="before",
    )
    @classmethod
    def exact_budgets(cls, value):
        if isinstance(value, (float, bool)):
            raise ValueError("cost limits require decimal strings")
        return value

    @model_validator(mode="after")
    def offline_analysis_only(self) -> AiSettings:
        if self.enable_adaptive_memory:
            raise ValueError("Adaptive memory is unavailable")
        if self.ai_job_lease_seconds <= self.ai_hard_timeout_seconds + 5:
            raise ValueError("analysis lease must exceed its total deadline and commit margin")
        return self


class BridgeSettings(ServiceSettings):
    service_name: Literal["risk"] = "risk"
    hard_max_risk_per_trade: Decimal = Field(
        default=Decimal("0.01"), gt=0, le=1, allow_inf_nan=False
    )
    hard_max_daily_loss: Decimal = Field(default=Decimal("0.03"), gt=0, le=1, allow_inf_nan=False)
    hard_max_total_open_risk: Decimal = Field(
        default=Decimal("0.03"), gt=0, le=1, allow_inf_nan=False
    )
    hard_max_open_positions: int = Field(default=3, ge=1, le=100)
    hard_max_lots: Decimal = Field(default=Decimal("1.00"), gt=0, allow_inf_nan=False)
    hard_max_effective_leverage: Decimal = Field(default=Decimal("10"), gt=0, allow_inf_nan=False)
    hard_require_stop_loss: bool = True
    hard_require_take_profit: bool = True
    enable_pending_orders: bool = False
    enable_partial_close: bool = False

    @field_validator(
        "hard_max_risk_per_trade",
        "hard_max_daily_loss",
        "hard_max_total_open_risk",
        "hard_max_lots",
        "hard_max_effective_leverage",
        mode="before",
    )
    @classmethod
    def exact_financial_inputs(cls, value: object) -> object:
        if isinstance(value, (float, bool)):
            raise ValueError("Financial settings must use exact decimal strings")
        return value

    @field_validator("hard_require_stop_loss", "hard_require_take_profit")
    @classmethod
    def required_protective_stops(cls, value: bool) -> bool:
        if not value:
            raise ValueError("Protective stops cannot be disabled")
        return value

    @model_validator(mode="after")
    def disabled_capabilities(self) -> BridgeSettings:
        if self.enable_pending_orders or self.enable_partial_close:
            raise ValueError("Phase 1 has no broker execution capabilities")
        if self.app_env == "production":
            required = {
                "hard_max_risk_per_trade",
                "hard_max_daily_loss",
                "hard_max_total_open_risk",
                "hard_max_open_positions",
                "hard_max_lots",
                "hard_max_effective_leverage",
                "hard_require_stop_loss",
                "hard_require_take_profit",
            }
            if not required.issubset(self.model_fields_set):
                raise ValueError("Production must explicitly provision all hard safety bounds")
        return self


def load_settings(service_name: ServiceName) -> ServiceSettings:
    """Read environment, or an explicitly named scoped file; never root .env."""
    env_file = os.environ.get("ENV_FILE")
    if env_file:
        path = Path(env_file)
        if path.name == ".env" or not path.is_file():
            raise RuntimeConfigError(
                "ENV_FILE must name an existing service-scoped environment file"
            )
    settings_type = {
        "api": ApiSettings,
        "risk": BridgeSettings,
        "collector": CollectorSettings,
        "ai": AiSettings,
    }.get(service_name, ServiceSettings)
    try:
        return settings_type(service_name=service_name, _env_file=env_file)
    except ValidationError as exc:
        fields = sorted(
            {
                ".".join(str(part) for part in error["loc"]) or "configuration"
                for error in exc.errors(include_input=False)
            }
        )
        raise RuntimeConfigError(f"Invalid {service_name} settings: {', '.join(fields)}") from None
