"""Explicit administrator/default creation with migration credentials, never runtime startup."""

import json
import os
import sys
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from argon2 import PasswordHasher, Type
from pydantic import BaseModel, ConfigDict, SecretStr, field_validator
from sqlalchemy import insert, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from backend.application.domain_bootstrap import seed_domain_defaults
from backend.infrastructure.database import ENVIRONMENT_PATTERN, SCHEMA_REVISION, Database
from backend.infrastructure.models import AuditEvent, SettingVersion, SystemSetting, User

DEFAULT_SETTINGS: dict[str, Any] = {
    "automation_enabled": False,
    "live_trading_enabled": False,
    "trading_mode": "paper",
    "raw_log_retention_days": 7,
    "ai_response_retention_days": 7,
    "telegram_retention_days": 7,
}
PASSWORD_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=1, type=Type.ID)


class BootstrapSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    migration_database_url: SecretStr
    environment_id: str = "local"
    admin_bootstrap_email: str
    admin_bootstrap_password: SecretStr

    @field_validator("migration_database_url")
    @classmethod
    def dedicated_migration_credential(cls, value: SecretStr) -> SecretStr:
        try:
            url = make_url(value.get_secret_value())
        except Exception as error:
            raise ValueError("migration database URL is required") from error
        if url.drivername != "postgresql+psycopg" or url.username != "trd_migrator":
            raise ValueError("bootstrap requires the dedicated PostgreSQL migration role")
        return value

    @field_validator("environment_id")
    @classmethod
    def valid_environment(cls, value: str) -> str:
        if not ENVIRONMENT_PATTERN.fullmatch(value):
            raise ValueError("invalid environment identity")
        return value

    @field_validator("admin_bootstrap_email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if (
            len(normalized) > 320
            or normalized.count("@") != 1
            or any(c.isspace() for c in normalized)
        ):
            raise ValueError("invalid administrator email")
        local, domain = normalized.split("@")
        if not local or not domain or "." not in domain:
            raise ValueError("invalid administrator email")
        return normalized

    @field_validator("admin_bootstrap_password")
    @classmethod
    def strong_password(cls, value: SecretStr) -> SecretStr:
        password = value.get_secret_value()
        if len(password) < 16 or len(password.encode("utf-8")) > 1024 or "\x00" in password:
            raise ValueError(
                "password requires at least 16 characters and at most 1024 UTF-8 bytes"
            )
        return value

    @classmethod
    def from_environment(cls) -> "BootstrapSettings":
        return cls(
            migration_database_url=SecretStr(os.environ.get("MIGRATION_DATABASE_URL", "")),
            environment_id=os.environ.get("ENVIRONMENT_ID", "local"),
            admin_bootstrap_email=os.environ.get("ADMIN_BOOTSTRAP_EMAIL", ""),
            admin_bootstrap_password=SecretStr(os.environ.get("ADMIN_BOOTSTRAP_PASSWORD", "")),
        )


class BootstrapError(RuntimeError):
    pass


@dataclass(frozen=True)
class BootstrapResult:
    admin_created: bool
    created_settings: tuple[str, ...]


def bootstrap(settings: BootstrapSettings) -> BootstrapResult:
    database = Database(settings.migration_database_url.get_secret_value())
    try:
        if database.schema_status() != "current":
            raise BootstrapError(f"database schema must be {SCHEMA_REVISION}; run migrations first")
        with database.engine.begin() as connection:
            connection.execute(text("SET LOCAL ROLE trd_owner"))
            # Serialize concurrent bootstrap attempts; one shared administrator,
            # while environment-specific defaults retain separate primary keys.
            connection.execute(text("SELECT pg_advisory_xact_lock(734159203)"))
            existing = connection.execute(
                select(User.id, User.role).where(User.email == settings.admin_bootstrap_email)
            ).first()
            admin_created = existing is None
            if existing is not None and existing.role != "ADMIN":
                raise BootstrapError(
                    "existing bootstrap identity is not an administrator; no role was changed"
                )
            admin_id = existing.id if existing is not None else uuid4()
            if admin_created:
                password_hash = PASSWORD_HASHER.hash(
                    settings.admin_bootstrap_password.get_secret_value()
                )
                connection.execute(
                    insert(User).values(
                        id=admin_id,
                        email=settings.admin_bootstrap_email,
                        password_hash=password_hash,
                        role="ADMIN",
                        active=True,
                    )
                )
                connection.execute(
                    insert(AuditEvent).values(
                        id=uuid4(),
                        environment_id=settings.environment_id,
                        action="BOOTSTRAP_ADMIN_CREATED",
                        actor_id=admin_id,
                        actor_service="bootstrap",
                        target=f"user:{admin_id}",
                        details={},
                    )
                )
            created: list[str] = []
            for key, value in DEFAULT_SETTINGS.items():
                current = connection.scalar(
                    select(SystemSetting.current_version).where(
                        SystemSetting.environment_id == settings.environment_id,
                        SystemSetting.key == key,
                    )
                )
                if current is not None:
                    continue
                # Retain prior/orphan versions rather than overwriting history.
                prior = connection.scalar(
                    select(SettingVersion.version)
                    .where(
                        SettingVersion.environment_id == settings.environment_id,
                        SettingVersion.key == key,
                    )
                    .order_by(SettingVersion.version.desc())
                    .limit(1)
                )
                if prior is not None:
                    raise BootstrapError(
                        "setting history exists without a current version; "
                        "reconcile before bootstrap"
                    )
                connection.execute(
                    insert(SettingVersion).values(
                        environment_id=settings.environment_id,
                        key=key,
                        version=1,
                        value=value,
                        created_by=admin_id,
                    )
                )
                connection.execute(
                    insert(SystemSetting).values(
                        environment_id=settings.environment_id, key=key, current_version=1
                    )
                )
                created.append(key)
            if created:
                connection.execute(
                    insert(AuditEvent).values(
                        id=uuid4(),
                        environment_id=settings.environment_id,
                        action="BOOTSTRAP_DEFAULTS_CREATED",
                        actor_id=admin_id,
                        actor_service="bootstrap",
                        target="system_settings",
                        details={"keys": created},
                    )
                )
            seed_domain_defaults(connection, settings.environment_id, admin_id)
        return BootstrapResult(admin_created=admin_created, created_settings=tuple(created))
    except SQLAlchemyError as error:
        raise BootstrapError("database bootstrap failed; transaction rolled back") from error
    finally:
        database.close()


def main() -> int:
    try:
        result = bootstrap(BootstrapSettings.from_environment())
    except BootstrapError as error:
        print(
            json.dumps(
                {"status": "failed", "error_type": type(error).__name__, "message": str(error)}
            ),
            file=sys.stderr,
        )
        return 1
    except Exception as error:
        # Pydantic/SQL exceptions may include sensitive inputs. CLI output names
        # failure class only; the failure remains explicit and exits nonzero.
        print(json.dumps({"status": "failed", "error_type": type(error).__name__}), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": "ok",
                "admin_created": result.admin_created,
                "created_settings": result.created_settings,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
