"""Real PostgreSQL 17 validation; fixtures only create/drop random test databases."""

import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url

from backend.application.bootstrap import (
    BootstrapSettings,
)

ROOT = Path(__file__).resolve().parents[2]
ROLE_ENV = {
    "trd_migrator": "MIGRATION_DATABASE_URL",
    "trd_api": "API_DATABASE_URL",
    "trd_collector": "COLLECTOR_DATABASE_URL",
    "trd_ai": "AI_DATABASE_URL",
    "trd_risk": "RISK_DATABASE_URL",
    "trd_maintenance": "MAINTENANCE_DATABASE_URL",
}


@dataclass(repr=False)
class IsolatedDatabase:
    urls: dict[str, str]
    migration_engine: Engine

    def migrate(self, target: str) -> None:
        config = Config(str(ROOT / "alembic.ini"))
        # env.py reads the explicit per-test DSN set by the fixture.
        command.upgrade(config, target)

    def downgrade(self, target: str) -> None:
        command.downgrade(Config(str(ROOT / "alembic.ini")), target)

    def settings(self, password: str = "test-only-password-please-change") -> BootstrapSettings:
        return BootstrapSettings(
            migration_database_url=self.urls["trd_migrator"],
            environment_id="test",
            admin_bootstrap_email="Admin@Example.test",
            admin_bootstrap_password=password,
        )


@pytest.fixture
def isolated_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[IsolatedDatabase]:
    admin_url = os.environ.get("TEST_ADMIN_DATABASE_URL")
    if not admin_url:
        pytest.skip("TEST_ADMIN_DATABASE_URL must explicitly select a PostgreSQL 17 test server")
    missing = [name for name in ROLE_ENV.values() if not os.environ.get(name)]
    if missing:
        pytest.fail("test role URLs must be supplied for all six pre-provisioned roles")
    database_name = f"trd_test_{uuid4().hex}"
    admin_engine = create_engine(admin_url)
    migration_engine = None
    created = False
    try:
        with admin_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            version = int(connection.scalar(text("SHOW server_version_num")))
            assert 170000 <= version < 180000, "integration target must be PostgreSQL 17"
            # The identifier consists solely of a fixed prefix and uuid hex.
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))
            created = True
        urls = {
            role: make_url(os.environ[env])
            .set(database=database_name)
            .render_as_string(hide_password=False)
            for role, env in ROLE_ENV.items()
        }
        for role, url in urls.items():
            assert make_url(url).username == role, "test credential identity mismatch"
        isolated_admin_url = make_url(admin_url).set(database=database_name)
        isolated_admin_engine = create_engine(isolated_admin_url)
        try:
            with isolated_admin_engine.begin() as connection:
                connection.execute(text("GRANT USAGE, CREATE ON SCHEMA public TO trd_owner"))
        finally:
            isolated_admin_engine.dispose()
        monkeypatch.setenv("MIGRATION_DATABASE_URL", urls["trd_migrator"])
        migration_engine = create_engine(urls["trd_migrator"])
        instance = IsolatedDatabase(urls, migration_engine)
        instance.migrate("head")
        yield instance
    finally:
        if migration_engine is not None:
            migration_engine.dispose()
        if created:
            assert database_name.startswith("trd_test_") and len(database_name) == 41
            with admin_engine.connect().execution_options(
                isolation_level="AUTOCOMMIT"
            ) as connection:
                connection.execute(text(f'DROP DATABASE "{database_name}" WITH (FORCE)'))
        admin_engine.dispose()
