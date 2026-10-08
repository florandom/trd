"""Synchronous database units of work. Engines may be shared; sessions never are."""

import re
from functools import lru_cache
from typing import Any, Protocol

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError

SCHEMA_REVISION = "0002_domain"
SERVICES = frozenset({"api", "collector", "ai", "risk", "maintenance"})
HEARTBEAT_STATUSES = frozenset({"STARTING", "HEALTHY", "DEGRADED", "STOPPED"})
ENVIRONMENT_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
INSTANCE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class SecretValue(Protocol):
    def get_secret_value(self) -> str: ...


class DatabaseSettings(Protocol):
    database_url: SecretValue
    environment_id: str
    service_name: str


def create_database_engine(database_url: str) -> Engine:
    """Bound connection and statement times; never print a connection URL."""
    return create_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=2,
        pool_timeout=3,
        connect_args={
            "connect_timeout": 3,
            "options": (
                "-c statement_timeout=5000 -c lock_timeout=1000 "
                "-c idle_in_transaction_session_timeout=5000 -c timezone=UTC"
            ),
        },
    )


class Database:
    def __init__(self, database_url: str, identity: str | None = None) -> None:
        if identity is not None and identity not in SERVICES:
            raise ValueError("unsupported database service identity")
        self.engine = create_database_engine(database_url)
        self.identity = identity

    def close(self) -> None:
        self.engine.dispose()

    def ping(self) -> bool:
        try:
            with self.engine.connect() as connection:
                return connection.scalar(text("SELECT 1")) == 1
        except SQLAlchemyError:
            return False

    def schema_status(self) -> str:
        try:
            with self.engine.connect() as connection:
                if connection.scalar(text("SELECT to_regclass('public.alembic_version')")) is None:
                    return "missing"
                revisions = set(
                    connection.scalars(text("SELECT version_num FROM public.alembic_version"))
                )
                return "current" if revisions == {SCHEMA_REVISION} else "mismatch"
        except SQLAlchemyError:
            return "unavailable"

    def write_heartbeat(
        self, *, environment_id: str, service_name: str, instance_id: str, status: str
    ) -> None:
        if not ENVIRONMENT_PATTERN.fullmatch(environment_id):
            raise ValueError("invalid environment identity")
        if service_name not in SERVICES or (
            self.identity is not None and service_name != self.identity
        ):
            raise PermissionError("heartbeat identity does not match the process")
        if not INSTANCE_PATTERN.fullmatch(instance_id) or status not in HEARTBEAT_STATUSES:
            raise ValueError("invalid heartbeat fields")
        with self.engine.begin() as connection:
            # The SECURITY DEFINER function also verifies session_user. Caller input
            # cannot grant authority to write another service's health state.
            connection.execute(
                text(
                    "SELECT public.record_service_heartbeat("
                    ":environment, :service, :instance, :status)"
                ),
                {
                    "environment": environment_id,
                    "service": service_name,
                    "instance": instance_id,
                    "status": status,
                },
            )

    def safe_projection(self, name: str, *, limit: int = 100) -> list[dict[str, Any]]:
        allowed = {"api_users", "api_settings", "api_audit_events", "api_heartbeats"}
        if name not in allowed or not 1 <= limit <= 1000:
            raise ValueError("unsupported projection or row limit")
        with self.engine.connect() as connection:
            # Only a fixed allowlist enters SQL syntax; all external values bind.
            rows = connection.execute(
                text(f"SELECT * FROM public.{name} LIMIT :limit"), {"limit": limit}
            )
            return [dict(row) for row in rows.mappings()]


@lru_cache(maxsize=16)
def _database_for_settings(database_url: str, service_name: str) -> Database:
    return Database(database_url, service_name)


def database_probe(settings: DatabaseSettings) -> bool:
    database = _database_for_settings(
        settings.database_url.get_secret_value(), settings.service_name
    )
    return database.ping() and database.schema_status() == "current"


def record_heartbeat(
    settings: DatabaseSettings, *, service_name: str, instance_id: str, status: str
) -> None:
    if service_name != settings.service_name:
        raise PermissionError("heartbeat identity does not match settings")
    _database_for_settings(
        settings.database_url.get_secret_value(), settings.service_name
    ).write_heartbeat(
        environment_id=settings.environment_id,
        service_name=service_name,
        instance_id=instance_id,
        status=status,
    )
