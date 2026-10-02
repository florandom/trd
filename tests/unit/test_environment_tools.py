"""Operator secrets and process boundaries, using disposable fixture credentials only."""

from __future__ import annotations

import base64
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote, unquote, urlsplit

import pytest
import yaml
from dotenv import dotenv_values

from infra.scripts import container, environment, provision_database, task

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def operator_root(tmp_path, monkeypatch):
    # Never read the real operator .env or inherit credentials from this test runner.
    template = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    (tmp_path / ".env.example").write_text(template, encoding="utf-8")
    monkeypatch.setattr(environment, "ROOT", tmp_path)
    monkeypatch.setattr(task, "ROOT", tmp_path)
    monkeypatch.setattr(os, "environ", {"PATH": "/fixture/tools", "SystemRoot": "C:\\Windows"})
    return tmp_path


def prepared_values(operator_root):
    target = environment.prepare_environment()
    return target, {key: value or "" for key, value in dotenv_values(target).items()}


def test_setup_uses_independent_256_bit_secrets_and_never_prints(
    operator_root, monkeypatch, capsys
):
    calls = []
    original_hex = environment.secrets.token_hex
    original_urlsafe = environment.secrets.token_urlsafe

    def token_hex(nbytes):
        calls.append(nbytes)
        return original_hex(nbytes)

    def token_urlsafe(nbytes):
        calls.append(nbytes)
        return original_urlsafe(nbytes)

    monkeypatch.setattr(environment.secrets, "token_hex", token_hex)
    monkeypatch.setattr(environment.secrets, "token_urlsafe", token_urlsafe)
    target, values = prepared_values(operator_root)
    assert calls and set(calls) == {32}
    assert environment.PLACEHOLDER not in values.values()
    urls = [values["DATABASE_ADMIN_URL"], values["MIGRATION_DATABASE_URL"]]
    urls.extend(values[field] for field, _role in environment.ROLE_URLS.values())
    passwords = [unquote(urlsplit(url).password or "") for url in urls]
    assert len(set(passwords)) == len(passwords)
    assert passwords[0] == values["POSTGRES_PASSWORD"]
    for password in passwords + [values["ADMIN_BOOTSTRAP_PASSWORD"]]:
        assert len(base64.urlsafe_b64decode(password + "=" * (-len(password) % 4))) == 32
    for field in (
        "ENCRYPTION_KEY",
        "TELEGRAM_SESSION_ENCRYPTION_KEY",
        "MT5_BRIDGE_SHARED_SECRET",
        "MT5_COMMAND_SIGNING_KEY",
    ):
        assert re.fullmatch(r"[a-f0-9]{64}", values[field])
    assert capsys.readouterr() == ("", "")
    if os.name != "nt":
        assert target.stat().st_mode & 0o777 == 0o600


def test_repeat_setup_preserves_credentials_and_comments_without_generating(
    operator_root, monkeypatch
):
    target, _values = prepared_values(operator_root)
    existing = target.read_bytes()

    def unexpected_generation(*_args):
        pytest.fail("Idempotent setup attempted to rotate an existing credential")

    monkeypatch.setattr(environment.secrets, "token_hex", unexpected_generation)
    monkeypatch.setattr(environment.secrets, "token_urlsafe", unexpected_generation)
    assert environment.prepare_environment() == target
    assert target.read_bytes() == existing
    assert b"# This operator file is never passed wholesale" in existing
    assert not target.with_name(".env.new").exists()


def test_failed_atomic_replace_preserves_the_existing_private_file(operator_root, monkeypatch):
    target, _values = prepared_values(operator_root)
    original = target.read_bytes()

    def fail_replace(*_args):
        raise OSError("Fixture replacement failure")

    monkeypatch.setattr(environment.os, "replace", fail_replace)
    with pytest.raises(OSError):
        environment.prepare_environment()
    assert target.read_bytes() == original
    assert not target.with_name(".env.new").exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("APP_ENV", "production"),
        ("TRADING_MODE", "demo"),
        ("TRADING_MODE", "live"),
        ("ENABLE_LIVE_TRADING", "true"),
        ("ENABLE_AUTOMATION", "true"),
    ],
)
def test_setup_rejects_any_execution_authorization_before_writing(operator_root, field, value):
    template = operator_root / ".env.example"
    source = template.read_text(encoding="utf-8")
    source = re.sub(rf"^{field}=.*$", f"{field}={value}", source, flags=re.MULTILINE)
    template.write_text(source, encoding="utf-8")
    with pytest.raises(ValueError):
        environment.prepare_environment()
    assert not (operator_root / ".env").exists()


@pytest.mark.parametrize(
    "placeholder_line",
    [
        'ENCRYPTION_KEY="__GENERATE__"',
        "ENCRYPTION_KEY=__GENERATE__ # local key",
        "ENCRYPTION_KEY = __GENERATE__",
    ],
)
def test_setup_cannot_report_success_with_unresolved_supported_dotenv_syntax(
    operator_root, placeholder_line
):
    template = operator_root / ".env.example"
    source = template.read_text(encoding="utf-8").replace(
        "ENCRYPTION_KEY=__GENERATE__", placeholder_line, 1
    )
    template.write_text(source, encoding="utf-8")
    try:
        target = environment.prepare_environment()
    except ValueError:
        assert not (operator_root / ".env").exists()
    else:
        assert environment.PLACEHOLDER not in dotenv_values(target).values()


def test_existing_private_values_are_preserved_and_admin_password_is_url_escaped(operator_root):
    target = operator_root / ".env"
    source = (operator_root / ".env.example").read_text(encoding="utf-8")
    source = source.replace("POSTGRES_PASSWORD=__GENERATE__", 'POSTGRES_PASSWORD="test:/@?#&pass"')
    source = source.replace("ENCRYPTION_KEY=__GENERATE__", "ENCRYPTION_KEY=existing-fixture-key")
    target.write_text(source, encoding="utf-8")
    environment.prepare_environment()
    values = dotenv_values(target)
    assert values["ENCRYPTION_KEY"] == "existing-fixture-key"
    parsed = urlsplit(values["DATABASE_ADMIN_URL"])
    assert unquote(parsed.password) == "test:/@?#&pass"
    assert parsed.hostname == "127.0.0.1"


def test_read_environment_only_accepts_declared_operator_overrides(operator_root, monkeypatch):
    target, _values = prepared_values(operator_root)
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    monkeypatch.setenv("UNDECLARED_SECRET", "ambient-canary")
    values = environment.read_environment(target)
    assert values["LOG_LEVEL"] == "WARNING"
    assert "UNDECLARED_SECRET" not in values


def test_unprepared_operator_file_is_rejected_without_secret_output(operator_root, capsys):
    target = operator_root / ".env"
    target.write_text((operator_root / ".env.example").read_text(encoding="utf-8"))
    with pytest.raises(ValueError):
        environment.read_environment(target)
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("service", list(environment.ROLE_URLS))
def test_runtime_projection_retains_only_its_owned_secrets(operator_root, monkeypatch, service):
    _target, values = prepared_values(operator_root)
    values.update(
        OPENAI_API_KEY="provider-canary",
        TELEGRAM_API_HASH="collector-canary",
        ALERT_TELEGRAM_BOT_TOKEN="notification-canary",
    )
    monkeypatch.setenv("ENV_FILE", "/fixture/all-secrets.env")
    monkeypatch.setenv("DATABASE_URL", "foreign-ambient-canary")
    monkeypatch.setenv("UNDECLARED_SECRET", "ambient-canary")
    projected = environment.runtime_environment(service, values)
    assert projected["PATH"] == "/fixture/tools"
    assert projected["SystemRoot"] == "C:\\Windows"
    assert projected["SERVICE_IDENTITY"] == service
    assert projected["DATA_DIR"] == str(operator_root / "data" / service)
    assert projected["LOG_DIR"] == str(operator_root / "logs" / service)
    assert unquote(urlsplit(projected["DATABASE_URL"]).username) == f"trd_{service}"
    assert (
        not {
            "ENV_FILE",
            "UNDECLARED_SECRET",
            "POSTGRES_PASSWORD",
            "DATABASE_ADMIN_URL",
            "MIGRATION_DATABASE_URL",
            "ADMIN_BOOTSTRAP_PASSWORD",
            *[field for field, _role in environment.ROLE_URLS.values()],
        }
        & projected.keys()
    )
    secrets_by_owner = {
        "api": {"ENCRYPTION_KEY"},
        "collector": {"TELEGRAM_API_HASH", "TELEGRAM_SESSION_ENCRYPTION_KEY"},
        "ai": {"OPENAI_API_KEY"},
        "risk": {"MT5_BRIDGE_SHARED_SECRET", "MT5_COMMAND_SIGNING_KEY"},
        "maintenance": {"ALERT_TELEGRAM_BOT_TOKEN"},
    }
    for owner, fields in secrets_by_owner.items():
        assert (fields <= projected.keys()) if owner == service else not fields & projected.keys()
    assert ("HARD_MAX_RISK_PER_TRADE" in projected) == (service == "risk")


def test_unknown_service_identity_is_rejected(operator_root):
    _target, values = prepared_values(operator_root)
    with pytest.raises(ValueError):
        environment.runtime_environment("administrator", values)


def test_bootstrap_and_migrations_receive_no_foreign_runtime_credentials(
    operator_root, monkeypatch
):
    _target, values = prepared_values(operator_root)
    monkeypatch.setenv("ENV_FILE", "/fixture/all-secrets.env")
    monkeypatch.setenv("DATABASE_ADMIN_URL", "ambient-privileged-canary")
    invocations = []
    monkeypatch.setattr(task, "run", lambda command, env=None: invocations.append((command, env)))
    task.migrate(values)
    task.bootstrap(values)
    migration_command, migration_env = invocations[0]
    bootstrap_command, bootstrap_env = invocations[1]
    assert migration_command[-3:] == ["alembic", "upgrade", "head"]
    assert bootstrap_command[-1] == "backend.application.bootstrap"
    assert set(migration_env) - environment.OS_FIELDS == {
        "MIGRATION_DATABASE_URL",
        "PYTHONUNBUFFERED",
    }
    assert set(bootstrap_env) - environment.OS_FIELDS == {
        "MIGRATION_DATABASE_URL",
        "ADMIN_BOOTSTRAP_EMAIL",
        "ADMIN_BOOTSTRAP_PASSWORD",
        "ENVIRONMENT_ID",
        "PYTHONUNBUFFERED",
    }


def test_task_error_message_cannot_echo_a_third_party_secret(operator_root, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["task.py", "provision-db", "--from-process"])

    def fail(_values):
        raise ValueError("malformed DSN contained private-test-canary")

    monkeypatch.setattr(task, "provision", fail)
    assert task.main() == 1
    captured = capsys.readouterr()
    assert "private-test-canary" not in captured.out + captured.err
    assert "ValueError" in captured.err


@pytest.mark.parametrize("port", ["0", "1023", "65536"])
def test_host_service_cannot_bind_a_public_or_invalid_port(operator_root, port):
    with pytest.raises(ValueError):
        task.service_command("api", {"API_PORT": port})
    command = task.service_command("api", {})
    assert command[command.index("--host") + 1] == "127.0.0.1"
    assert "--no-access-log" in command


@pytest.fixture
def development_supervisor(operator_root, monkeypatch):
    """Observe process ownership without spawning services or installing real handlers."""
    _target, values = prepared_values(operator_root)
    state = SimpleNamespace(
        values=values,
        children=[],
        stopped=[],
        events=[],
        launch_failure=None,
        initialization_failure=False,
        trigger_signal=None,
        exit_child=None,
    )
    # Exercise the Windows termination callback on every platform. Signals are mocked.
    monkeypatch.setattr(task.signal, "SIGBREAK", 99, raising=False)
    signal_numbers = (task.signal.SIGTERM, task.signal.SIGBREAK)
    previous = {number: object() for number in signal_numbers}
    active = dict(previous)
    state.previous_handlers = previous
    state.active_handlers = active

    def install_handler(number, handler):
        old = active[number]
        active[number] = handler
        action = "restore" if handler is previous[number] else "install"
        state.events.append((action, number))
        return old

    def initialize(_values):
        state.events.append(("initialize", None))
        if state.initialization_failure:
            raise ValueError("Fixture initialization failed")

    def start_child(_command, *, env, **_options):
        index = len(state.children)
        if index == state.launch_failure:
            raise OSError("Fixture process launch failed")
        name = env.get("SERVICE_IDENTITY", "dashboard")
        child = SimpleNamespace(name=name, index=index)
        child.poll = lambda: 1 if child.index == state.exit_child else None
        state.children.append(child)
        state.events.append(("start", name))
        return child

    def stop_child(child):
        state.stopped.append(child.name)
        state.events.append(("stop", child.name))

    def await_supervisor(_seconds):
        if state.trigger_signal is None:
            pytest.fail("Lifecycle fixture unexpectedly entered an unbounded supervisor wait")
        active[state.trigger_signal](state.trigger_signal, None)
        pytest.fail("Termination callback returned without interrupting the supervisor")

    monkeypatch.setattr(task.signal, "signal", install_handler)
    monkeypatch.setattr(task, "initialize", initialize)
    monkeypatch.setattr(task.subprocess, "Popen", start_child)
    monkeypatch.setattr(task, "stop_process", stop_child)
    monkeypatch.setattr(task, "executable", lambda _name: "/fixture/pnpm")
    monkeypatch.setattr(task.time, "sleep", await_supervisor)
    return state


def assert_supervisor_cleanup(state):
    assert state.stopped == [child.name for child in reversed(state.children)]
    assert state.active_handlers == state.previous_handlers
    restores = [index for index, event in enumerate(state.events) if event[0] == "restore"]
    assert len(restores) == len(state.previous_handlers)
    stops = [index for index, event in enumerate(state.events) if event[0] == "stop"]
    if stops:
        assert max(stops) < min(restores)


@pytest.mark.parametrize("signal_name", ["SIGTERM", "SIGBREAK"])
def test_supervisor_termination_callback_stops_all_child_groups_and_restores_handlers(
    development_supervisor, signal_name
):
    state = development_supervisor
    state.trigger_signal = getattr(task.signal, signal_name)
    with pytest.raises(KeyboardInterrupt):
        task.dev(state.values)
    assert [child.name for child in state.children] == [
        "api",
        "risk",
        "ai",
        "collector",
        "maintenance",
        "dashboard",
    ]
    assert_supervisor_cleanup(state)


@pytest.mark.parametrize("launch_failure", range(6))
def test_supervisor_startup_failure_stops_every_started_child_and_restores_handlers(
    development_supervisor, launch_failure
):
    state = development_supervisor
    state.launch_failure = launch_failure
    with pytest.raises(OSError, match="launch failed"):
        task.dev(state.values)
    assert len(state.children) == launch_failure
    assert_supervisor_cleanup(state)


def test_supervisor_initialization_failure_restores_handlers_without_starting_children(
    development_supervisor,
):
    state = development_supervisor
    state.initialization_failure = True
    with pytest.raises(ValueError, match="initialization failed"):
        task.dev(state.values)
    assert not state.children
    assert_supervisor_cleanup(state)


def test_unexpected_child_exit_stops_remaining_child_groups_and_restores_handlers(
    development_supervisor,
):
    state = development_supervisor
    state.exit_child = 2
    with pytest.raises(RuntimeError, match="service exited"):
        task.dev(state.values)
    assert len(state.children) == 6
    assert_supervisor_cleanup(state)


def test_container_rejects_production_before_rewriting_or_executing(operator_root, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "untouched-fixture")
    monkeypatch.setattr(sys, "argv", ["container.py", "api"])
    monkeypatch.setattr(os, "execv", lambda *_args: pytest.fail("Unexpected process launch"))
    with pytest.raises(SystemExit):
        container.main()
    assert os.environ["DATABASE_URL"] == "untouched-fixture"


def test_container_preserves_encoded_password_while_readdressing_scoped_dsn(
    operator_root, monkeypatch
):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+psycopg://trd_api:test%3A%2F%40%3Fpass@127.0.0.1:5444/trd"
    )
    monkeypatch.setattr(sys, "argv", ["container.py", "api"])
    calls = []
    monkeypatch.setattr(os, "execv", lambda *args: calls.append(args))
    container.main()
    parsed = urlsplit(os.environ["DATABASE_URL"])
    assert parsed.hostname == "postgres" and parsed.port == 5432
    assert unquote(parsed.username) == "trd_api"
    assert unquote(parsed.password) == "test:/@?pass"
    assert len(calls) == 1 and "apps.api.main:app" in calls[0][1]


class FakeResult:
    def __init__(self, row=None, rows=()):
        self.row = row
        self.rows = rows

    def fetchone(self):
        return self.row

    def __iter__(self):
        return iter(self.rows)


class ProvisionConnection:
    """Catalog model: tests never connect to PostgreSQL or execute SQL."""

    def __init__(
        self,
        *,
        owner_flags=None,
        owner_membership=False,
        service_memberships=None,
        existing_services=True,
    ):
        self.owner_flags = owner_flags or (False, False, False, False, False, False)
        self.owner_membership = owner_membership
        self.service_memberships = service_memberships or {}
        self.existing_services = existing_services
        self.statements = []
        self.password_hash_calls = []
        self.info = SimpleNamespace(encoding="utf-8")
        self.pgconn = SimpleNamespace(encrypt_password=self.encrypt_password)

    def encrypt_password(self, password, role, *, algorithm):
        self.password_hash_calls.append((password, role, algorithm))
        return b"SCRAM-SHA-256$4096:fixture-salt$fixture-stored-key:fixture-server-key"

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, query, params=None):
        self.statements.append(query)
        if query == "SELECT current_database()":
            return FakeResult(("trd",))
        if query == "SHOW server_version_num":
            return FakeResult(("170011",))
        if isinstance(query, str) and query.startswith("SELECT 1 FROM pg_roles"):
            return FakeResult((1,))
        if isinstance(query, str) and query.startswith("SELECT rolcanlogin"):
            if params is not None and not self.existing_services:
                return FakeResult()
            return FakeResult(
                self.owner_flags if params is None else (True, False, False, False, False, False)
            )
        if isinstance(query, str) and query.startswith("SELECT 1 FROM pg_auth_members"):
            return FakeResult((1,) if self.owner_membership else None)
        if isinstance(query, str) and query.startswith("SELECT 1 FROM pg_database"):
            return FakeResult((1,))
        if isinstance(query, str) and query.startswith("SELECT parent.rolname"):
            return FakeResult(
                rows=[(role,) for role in self.service_memberships.get(params[0], [])]
            )
        if isinstance(query, str) and query.startswith("SELECT pg_has_role"):
            return FakeResult((False,))
        return FakeResult()


@pytest.mark.parametrize("privilege_index", range(6))
def test_provisioning_rejects_any_privileged_or_login_enabled_owner(
    operator_root, monkeypatch, privilege_index
):
    _target, values = prepared_values(operator_root)
    flags = [False] * 6
    flags[privilege_index] = True
    conn = ProvisionConnection(owner_flags=tuple(flags))
    monkeypatch.setattr(provision_database.psycopg, "connect", lambda *_args, **_kwargs: conn)
    with pytest.raises(ValueError, match="owner"):
        provision_database.provision(values)


def test_provisioning_rejects_owner_role_membership(operator_root, monkeypatch):
    _target, values = prepared_values(operator_root)
    conn = ProvisionConnection(owner_membership=True)
    monkeypatch.setattr(provision_database.psycopg, "connect", lambda *_args, **_kwargs: conn)
    with pytest.raises(ValueError, match="owner"):
        provision_database.provision(values)


@pytest.mark.parametrize(
    "inherited_role", ["trd_owner", "trd_migrator", "pg_read_all_data", "pg_write_all_data"]
)
def test_provisioning_rejects_runtime_inherited_privileges(
    operator_root, monkeypatch, inherited_role
):
    _target, values = prepared_values(operator_root)
    conn = ProvisionConnection(service_memberships={"trd_api": [inherited_role]})
    monkeypatch.setattr(provision_database.psycopg, "connect", lambda *_args, **_kwargs: conn)
    with pytest.raises(ValueError, match="memberships"):
        provision_database.provision(values)


@pytest.mark.parametrize("bad_url", ["other-host:5432", "127.0.0.1:5444"])
def test_provisioning_rejects_role_dsn_for_a_different_server(operator_root, monkeypatch, bad_url):
    _target, values = prepared_values(operator_root)
    values["API_DATABASE_URL"] = values["API_DATABASE_URL"].replace("127.0.0.1:5432", bad_url)
    conn = ProvisionConnection()
    monkeypatch.setattr(provision_database.psycopg, "connect", lambda *_args, **_kwargs: conn)
    with pytest.raises(ValueError, match="expected login"):
        provision_database.provision(values)


def test_provisioning_accepts_only_the_expected_migrator_membership(operator_root, monkeypatch):
    _target, values = prepared_values(operator_root)
    conn = ProvisionConnection(service_memberships={"trd_migrator": ["trd_owner"]})
    monkeypatch.setattr(provision_database.psycopg, "connect", lambda *_args, **_kwargs: conn)
    provision_database.provision(values)
    conn.service_memberships["trd_migrator"].append("pg_read_all_data")
    with pytest.raises(ValueError, match="memberships"):
        provision_database.provision(values)


def test_new_role_ddl_contains_scram_verifiers_and_no_plaintext_passwords(
    operator_root, monkeypatch, capsys
):
    _target, values = prepared_values(operator_root)
    fixture_password = "plain-password-fixture:/?#"
    values["API_DATABASE_URL"] = (
        f"postgresql+psycopg://trd_api:{quote(fixture_password, safe='')}@127.0.0.1:5432/trd"
    )
    conn = ProvisionConnection(existing_services=False)
    monkeypatch.setattr(provision_database.psycopg, "connect", lambda *_args, **_kwargs: conn)
    provision_database.provision(values)
    rendered = "\n".join(str(statement) for statement in conn.statements)
    role_urls = [values["MIGRATION_DATABASE_URL"]]
    role_urls.extend(values[field] for field, _role in environment.ROLE_URLS.values())
    expected_hash_calls = {
        (
            unquote(urlsplit(url).password).encode("utf-8"),
            unquote(urlsplit(url).username).encode("utf-8"),
            b"scram-sha-256",
        )
        for url in role_urls
    }
    assert set(conn.password_hash_calls) == expected_hash_calls
    assert len(conn.password_hash_calls) == len(role_urls)
    assert rendered.count("SCRAM-SHA-256$") == len(role_urls)
    for url in role_urls:
        assert unquote(urlsplit(url).password) not in rendered
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize(
    "final_role_url",
    [
        "sqlite:///fixture.db",
        "postgresql+psycopg://trd_api:fixture-password@127.0.0.1:5432/trd",
        "postgresql+psycopg://trd_maintenance@127.0.0.1:5432/trd",
        "postgresql+psycopg://trd_maintenance:fixture-password@127.0.0.1:5432/other",
        "postgresql+psycopg://trd_maintenance:fixture-password@other-host:5432/trd",
        "postgresql+psycopg://trd_maintenance:fixture-password@127.0.0.1:5444/trd",
        "postgresql+psycopg://trd_maintenance:fixture-password@127.0.0.1:invalid/trd",
    ],
)
def test_invalid_final_role_url_is_rejected_before_any_connection_or_catalog_mutation(
    operator_root, monkeypatch, final_role_url
):
    _target, values = prepared_values(operator_root)
    values["MAINTENANCE_DATABASE_URL"] = final_role_url

    def unexpected_connect(*_args, **_kwargs):
        pytest.fail("Provisioning connected before validating the entire requested role set")

    monkeypatch.setattr(provision_database.psycopg, "connect", unexpected_connect)
    with pytest.raises(ValueError):
        provision_database.provision(values)


def test_compose_runtime_scopes_and_loopback_publishing():
    compose = yaml.safe_load((PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    runtime_database = {
        "api": "API_DATABASE_URL",
        "bridge": "RISK_DATABASE_URL",
        "worker": "AI_DATABASE_URL",
        "telegram": "COLLECTOR_DATABASE_URL",
        "maintenance": "MAINTENANCE_DATABASE_URL",
    }
    for service, field in runtime_database.items():
        configuration = services[service]
        scoped = configuration["environment"]
        assert "env_file" not in configuration
        assert scoped["DATABASE_URL"].startswith("${" + field + ":")
        assert (
            not {
                "DATABASE_ADMIN_URL",
                "MIGRATION_DATABASE_URL",
                "ADMIN_BOOTSTRAP_PASSWORD",
                "OPENAI_API_KEY",
                "TELEGRAM_API_HASH",
                "MT5_COMMAND_SIGNING_KEY",
            }
            & scoped.keys()
        )
        assert configuration["read_only"] is True
        assert configuration["cap_drop"] == ["ALL"]
        assert configuration["depends_on"]["initialize"]["condition"] == (
            "service_completed_successfully"
        )
    assert set(services["dashboard"]["environment"]) == {"API_INTERNAL_URL", "HOSTNAME", "PORT"}
    assert services["initialize"]["restart"] == "no"
    assert services["worker"]["environment"]["AI_PROVIDER_MODE"] == "mock"
    assert services["telegram"]["environment"]["TELEGRAM_ENABLED"] == "false"
    for configuration in services.values():
        assert "env_file" not in configuration
        for published in configuration.get("ports", []):
            assert published.startswith("127.0.0.1:")
    for name in ("postgres", "redis"):
        assert "@sha256:" in services[name]["image"]


def test_host_development_compose_cannot_start_a_duplicate_application_stack():
    compose = yaml.safe_load((PROJECT_ROOT / "docker-compose.dev.yml").read_text(encoding="utf-8"))
    for service in (
        "initialize",
        "api",
        "bridge",
        "worker",
        "telegram",
        "maintenance",
        "dashboard",
    ):
        assert compose["services"][service]["profiles"] == ["containers"]
