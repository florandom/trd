"""Real PostgreSQL 17 validation; fixtures only create/drop random test databases."""

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from argon2 import PasswordHasher
from sqlalchemy import Engine, create_engine, insert, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from backend.application.bootstrap import (
    DEFAULT_SETTINGS,
    BootstrapError,
    BootstrapSettings,
    bootstrap,
)
from backend.infrastructure.database import SCHEMA_REVISION, Database
from backend.infrastructure.models import AuditEvent, SettingVersion, SystemSetting, User

pytestmark = pytest.mark.integration
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


def test_upgrade_downgrade_upgrade_and_owner(isolated_database: IsolatedDatabase) -> None:
    database = Database(isolated_database.urls["trd_api"], "api")
    try:
        assert database.ping()
        assert database.schema_status() == "current"
        isolated_database.migrate("head")
        isolated_database.downgrade("base")
        assert database.schema_status() == "mismatch"
        isolated_database.migrate("head")
        assert database.schema_status() == "current"
        with isolated_database.migration_engine.connect() as connection:
            ownership = connection.execute(
                text(
                    "SELECT relname, pg_get_userbyid(relowner) FROM pg_class "
                    "WHERE relnamespace = 'public'::regnamespace "
                    "AND relname IN ('users','system_settings','setting_versions',"
                    "'audit_events','heartbeats','alembic_version')"
                )
            ).all()
            assert len(ownership) == 6
            assert all(owner == "trd_owner" for _, owner in ownership)
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == SCHEMA_REVISION
            )
    finally:
        database.close()


def test_bootstrap_is_idempotent_preserves_password_and_versions(
    isolated_database: IsolatedDatabase,
) -> None:
    first = bootstrap(isolated_database.settings())
    assert first.admin_created
    assert set(first.created_settings) == set(DEFAULT_SETTINGS)
    with isolated_database.migration_engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE trd_owner"))
        user = connection.execute(select(User)).mappings().one()
        password_hash = user["password_hash"]
        assert password_hash.startswith("$argon2id$")
        assert PasswordHasher().verify(password_hash, "test-only-password-please-change")
        assert user["email"] == "admin@example.test"
        assert (
            connection.scalar(
                select(AuditEvent.id).where(AuditEvent.action == "BOOTSTRAP_ADMIN_CREATED")
            )
            is not None
        )
        initial = dict(connection.execute(select(SettingVersion.key, SettingVersion.value)).all())
        assert initial["automation_enabled"] is False
        assert initial["live_trading_enabled"] is False
        assert initial["trading_mode"] == "paper"
        connection.execute(
            insert(SettingVersion).values(
                environment_id="test",
                key="raw_log_retention_days",
                version=2,
                value=14,
                created_by=user["id"],
            )
        )
        connection.execute(
            update(SystemSetting)
            .where(
                SystemSetting.environment_id == "test",
                SystemSetting.key == "raw_log_retention_days",
            )
            .values(current_version=2)
        )
    again = bootstrap(isolated_database.settings("different-password-not-a-reset"))
    assert not again.admin_created
    assert again.created_settings == ()
    with isolated_database.migration_engine.connect() as connection:
        assert connection.scalar(select(User.password_hash)) == password_hash
        assert (
            connection.scalar(
                select(SystemSetting.current_version).where(
                    SystemSetting.key == "raw_log_retention_days"
                )
            )
            == 2
        )
        assert len(connection.execute(select(AuditEvent.id)).all()) == 2


def test_concurrent_bootstrap_creates_one_admin_and_default_set(
    isolated_database: IsolatedDatabase,
) -> None:
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(bootstrap, [isolated_database.settings()] * 2))
    assert sum(outcome.admin_created for outcome in outcomes) == 1
    assert sum(len(outcome.created_settings) for outcome in outcomes) == len(DEFAULT_SETTINGS)
    with isolated_database.migration_engine.connect() as connection:
        assert len(connection.execute(select(User.id)).all()) == 1
        assert len(connection.execute(select(SystemSetting.key)).all()) == len(DEFAULT_SETTINGS)
        assert len(connection.execute(select(AuditEvent.id)).all()) == 2


def test_bootstrap_rolls_back_when_prior_history_is_inconsistent(
    isolated_database: IsolatedDatabase,
) -> None:
    with isolated_database.migration_engine.begin() as connection:
        connection.execute(
            insert(SettingVersion).values(
                environment_id="test", key="raw_log_retention_days", version=1, value=30
            )
        )
    with pytest.raises(BootstrapError, match="reconcile before bootstrap"):
        bootstrap(isolated_database.settings())
    with isolated_database.migration_engine.connect() as connection:
        assert connection.execute(select(User.id)).first() is None
        assert connection.execute(select(SystemSetting.key)).first() is None
        assert connection.execute(select(AuditEvent.id)).first() is None


@pytest.mark.parametrize(
    "role", ["trd_api", "trd_collector", "trd_ai", "trd_risk", "trd_maintenance"]
)
def test_heartbeat_function_enforces_database_identity(
    isolated_database: IsolatedDatabase, role: str
) -> None:
    service = role.removeprefix("trd_")
    database = Database(isolated_database.urls[role], service)
    try:
        database.write_heartbeat(
            environment_id="test", service_name=service, instance_id="fixture", status="STARTING"
        )
        database.write_heartbeat(
            environment_id="test", service_name=service, instance_id="fixture", status="HEALTHY"
        )
        # Bypass the Python guard to validate SQL authorization independently.
        wrong_service = "api" if service != "api" else "risk"
        with pytest.raises(DBAPIError) as error, database.engine.begin() as connection:
            connection.execute(
                text(
                    "SELECT public.record_service_heartbeat('test', :service, 'spoofed', 'HEALTHY')"
                ),
                {"service": wrong_service},
            )
        assert error.value.orig.sqlstate == "42501"
        with isolated_database.migration_engine.connect() as connection:
            result = connection.execute(text("SELECT service_name, status FROM heartbeats")).all()
            assert result == [(service, "HEALTHY")]
        with pytest.raises(DBAPIError) as error, database.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO public.heartbeats VALUES ('test','risk','direct','HEALTHY',now())"
                )
            )
        assert error.value.orig.sqlstate == "42501"
    finally:
        database.close()


@pytest.mark.parametrize(
    "role", ["trd_api", "trd_collector", "trd_ai", "trd_risk", "trd_maintenance"]
)
def test_runtime_roles_have_no_owner_or_authority_grants(
    isolated_database: IsolatedDatabase, role: str
) -> None:
    database = Database(isolated_database.urls[role], role.removeprefix("trd_"))
    denied_statements = [
        "SELECT password_hash FROM public.users",
        "INSERT INTO public.users (id,email,password_hash,role) "
        "VALUES ('00000000-0000-0000-0000-000000000001','bad@example.test','bad','ADMIN')",
        "UPDATE public.system_settings SET current_version=100",
        "INSERT INTO public.setting_versions "
        "VALUES ('test','automation_enabled',1,'true',NULL,now())",
        "UPDATE public.audit_events SET action='hidden'",
        "DELETE FROM public.audit_events",
        "UPDATE public.api_users SET role='ADMIN'",
        "UPDATE public.api_heartbeats SET status='HEALTHY'",
        "CREATE TABLE public.unapproved (id integer)",
        "SET ROLE trd_owner",
    ]
    try:
        with database.engine.connect() as connection:
            role_flags = connection.execute(
                text(
                    "SELECT rolsuper,rolcreaterole,rolcreatedb,rolreplication,rolbypassrls "
                    "FROM pg_roles WHERE rolname=session_user"
                )
            ).one()
            assert not any(role_flags)
            assert not connection.scalar(
                text("SELECT pg_has_role(session_user,'trd_owner','MEMBER')")
            )
            assert (
                connection.scalar(text("SELECT version_num FROM public.alembic_version"))
                == SCHEMA_REVISION
            )
        for statement in denied_statements:
            with pytest.raises(DBAPIError) as error, database.engine.begin() as connection:
                connection.execute(text(statement))
            assert error.value.orig.sqlstate == "42501"
    finally:
        database.close()


def test_api_projections_exclude_password_internal_setting_and_raw_audit(
    isolated_database: IsolatedDatabase,
) -> None:
    bootstrap(isolated_database.settings())
    with isolated_database.migration_engine.begin() as connection:
        connection.execute(
            insert(SettingVersion).values(
                environment_id="test",
                key="internal_example",
                version=1,
                value={"secret": "not-visible"},
            )
        )
        connection.execute(
            insert(SystemSetting).values(
                environment_id="test", key="internal_example", current_version=1
            )
        )
    database = Database(isolated_database.urls["trd_api"], "api")
    try:
        users = database.safe_projection("api_users")
        assert len(users) == 1 and "password_hash" not in users[0]
        settings = database.safe_projection("api_settings")
        assert {setting["key"] for setting in settings} == set(DEFAULT_SETTINGS)
        audits = database.safe_projection("api_audit_events")
        assert audits and all("details" not in event for event in audits)
        with pytest.raises(ValueError):
            database.safe_projection("users")
        for role in ("trd_collector", "trd_ai", "trd_risk", "trd_maintenance"):
            other = Database(isolated_database.urls[role], role.removeprefix("trd_"))
            try:
                with pytest.raises(DBAPIError) as error:
                    other.safe_projection("api_users")
                assert error.value.orig.sqlstate == "42501"
            finally:
                other.close()
    finally:
        database.close()


def test_definer_ignores_temporary_table_shadowing(isolated_database: IsolatedDatabase) -> None:
    database = Database(isolated_database.urls["trd_api"], "api")
    try:
        with database.engine.begin() as connection:
            connection.execute(text("CREATE TEMP TABLE heartbeats (marker integer)"))
            connection.execute(
                text("SELECT public.record_service_heartbeat('test','api','safe','HEALTHY')")
            )
            assert connection.scalar(text("SELECT count(*) FROM pg_temp.heartbeats")) == 0
            assert connection.scalar(text("SELECT count(*) FROM public.api_heartbeats")) == 1
        with isolated_database.migration_engine.connect() as connection:
            configuration = connection.scalar(
                text(
                    "SELECT proconfig FROM pg_proc "
                    "WHERE oid = 'public.record_service_heartbeat"
                    "(text,text,text,text)'::regprocedure"
                )
            )
            assert "search_path=pg_catalog, public, pg_temp" in configuration
            assert not connection.scalar(
                text(
                    "SELECT has_function_privilege('public', "
                    "'public.record_service_heartbeat(text,text,text,text)', 'EXECUTE')"
                )
            )
    finally:
        database.close()


def test_future_owner_functions_require_explicit_execute_grants(
    isolated_database: IsolatedDatabase,
) -> None:
    with isolated_database.migration_engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE trd_owner"))
        connection.execute(
            text(
                "CREATE FUNCTION public.future_private_probe() RETURNS integer "
                "LANGUAGE sql AS 'SELECT 1'"
            )
        )
        assert not connection.scalar(
            text(
                "SELECT has_function_privilege('public', "
                "'public.future_private_probe()', 'EXECUTE')"
            )
        )
    database = Database(isolated_database.urls["trd_api"], "api")
    try:
        with pytest.raises(DBAPIError) as error, database.engine.begin() as connection:
            connection.execute(text("SELECT public.future_private_probe()"))
        assert error.value.orig.sqlstate == "42501"
    finally:
        database.close()
