"""Guard deployment trust boundaries without depending on local secrets or Docker."""

import re
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from backend.api.factory import create_app
from backend.domain.config import ApiSettings

ROOT = Path(__file__).resolve().parents[2]
ROLE_URLS = {
    "api": "API_DATABASE_URL",
    "bridge": "RISK_DATABASE_URL",
    "worker": "AI_DATABASE_URL",
    "telegram": "COLLECTOR_DATABASE_URL",
    "maintenance": "MAINTENANCE_DATABASE_URL",
}
APPLICATION_SERVICES = {*ROLE_URLS, "dashboard"}
PRIVILEGED_VARIABLES = {
    "DATABASE_ADMIN_URL",
    "MIGRATION_DATABASE_URL",
    "ADMIN_BOOTSTRAP_EMAIL",
    "ADMIN_BOOTSTRAP_PASSWORD",
}
PROVIDER_PREFIXES = ("OPENAI_", "ANTHROPIC_", "GOOGLE_AI_", "MOONSHOT_", "TYPESAFE_")
REFERENCES = re.compile(r"\$\{([A-Z][A-Z0-9_]*)")


class UniqueKeyLoader(yaml.SafeLoader):
    """Reject duplicate explicit keys while preserving intentional YAML merges."""

    def construct_mapping(self, node, deep=False):
        seen = set()
        for key_node, _value in node.value:
            if key_node.tag == "tag:yaml.org,2002:merge":
                continue
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise ValueError(f"Duplicate Compose key: {key}")
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def load_compose(filename="docker-compose.yml"):
    result = yaml.load((ROOT / filename).read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
    assert isinstance(result, dict) and isinstance(result.get("services"), dict)
    return result["services"]


def environment(service):
    values = service.get("environment", {})
    # Mapping syntax makes inherited shell variables and credentials reviewable.
    assert isinstance(values, dict), "Use explicit environment mappings, not host inheritance"
    return values


def referenced_variables(name, value):
    return {name, *REFERENCES.findall(str(value))}


def default_value(value):
    expression = re.fullmatch(r"\$\{[A-Z][A-Z0-9_]*:-([^}]+)\}", str(value))
    return (expression[1] if expression else str(value)).lower()


def dependencies(services, name, seen=None):
    seen = set() if seen is None else seen
    if name in seen:
        return set()
    seen.add(name)
    direct = set(services[name].get("depends_on", {}))
    return direct | {
        descendant
        for dependency in direct
        for descendant in dependencies(services, dependency, seen)
    }


def assert_restricted_tmpfs(mounts):
    assert isinstance(mounts, list) and mounts, "Application tmpfs mounts must be explicit"
    specifications = {}
    for mount in mounts:
        assert isinstance(mount, str), "Keep each tmpfs path and its options in one string"
        path, separator, options = mount.partition(":")
        assert path.startswith("/"), f"Relative tmpfs mount: {path}"
        assert separator and options, "A tmpfs mount must carry its security options"
        assert path not in specifications, "Duplicate tmpfs paths can override security options"
        specifications[path] = set(options.split(","))

    assert "/tmp" in specifications
    for options in specifications.values():
        assert {"rw", "noexec", "nosuid"} <= options
        assert not ({"exec", "suid"} & options)
        sizes = [option.removeprefix("size=") for option in options if option.startswith("size=")]
        assert len(sizes) == 1, "Writable tmpfs must have one explicit memory bound"
        quantity = re.fullmatch(r"([1-9][0-9]*)([kmg]?)", sizes[0].lower())
        assert quantity, "tmpfs size must be a positive byte count or integer unit"
        multipliers = {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3}
        byte_count = int(quantity[1]) * multipliers[quantity[2]]
        # A small writable scratch mount must not consume unbounded host memory.
        assert byte_count <= 64 * 1024**2


def credential_owner(variable):
    if variable in PRIVILEGED_VARIABLES:
        return {"initialize"}
    if variable in ROLE_URLS.values():
        return {"initialize", next(name for name, url in ROLE_URLS.items() if url == variable)}
    if variable == "POSTGRES_PASSWORD":
        return {"postgres"}
    if variable.startswith(PROVIDER_PREFIXES):
        return {"worker"}
    if variable.startswith("MT5_"):
        return {"bridge"}
    if variable.startswith("TELEGRAM_API_") or variable == "TELEGRAM_SESSION_ENCRYPTION_KEY":
        return {"telegram"}
    if variable in {"AUTH_SECRET", "SESSION_SECRET", "ENCRYPTION_KEY"}:
        return {"api"}
    if re.search(r"(?:_PASSWORD|_SECRET|_TOKEN|_KEY)$", variable):
        pytest.fail(f"Credential {variable} needs an explicit service ownership contract")
    return None


def test_every_application_runtime_uses_only_its_own_required_database_role():
    services = load_compose()
    built_runtimes = {
        name for name, service in services.items() if "build" in service and name != "initialize"
    }
    assert built_runtimes == APPLICATION_SERVICES, "New runtimes need a reviewed role boundary"
    for name, role_variable in ROLE_URLS.items():
        values = environment(services[name])
        assert REFERENCES.findall(str(values["DATABASE_URL"])) == [role_variable]
        assert str(values["DATABASE_URL"]).startswith(f"${{{role_variable}:?")
        assert not (set(values) & {*ROLE_URLS.values(), *PRIVILEGED_VARIABLES})
    assert not any("DATABASE" in name for name in environment(services["dashboard"]))


def test_credentials_are_not_shared_outside_their_service_boundary():
    for name, service in load_compose().items():
        assert "env_file" not in service, "Root dotenv files must not be injected into containers"
        for field, value in environment(service).items():
            for variable in referenced_variables(field, value):
                allowed = credential_owner(variable)
                if allowed is not None:
                    assert name in allowed, f"{variable} crossed the {name} boundary"


def test_paper_and_disabled_execution_are_the_compose_defaults():
    services = load_compose()
    for name in ROLE_URLS:
        values = environment(services[name])
        assert default_value(values["TRADING_MODE"]) == "paper"
        assert default_value(values["ENABLE_AUTOMATION"]) == "false"
        assert default_value(values["ENABLE_LIVE_TRADING"]) == "false"


def test_application_containers_are_read_only_unprivileged_and_nonroot():
    services = load_compose()
    # Official database/cache entrypoints initialize their own persistent stores.
    # These checks target our application images, including the one-shot initializer.
    for name in APPLICATION_SERVICES | {"initialize"}:
        service = services[name]
        assert service.get("read_only") is True
        assert "ALL" in service.get("cap_drop", [])
        assert "no-new-privileges:true" in service.get("security_opt", [])
        assert not service.get("privileged", False)
        assert service.get("network_mode") != "host"
        assert service.get("pid") != "host"
        assert "env_file" not in service
        if "user" in service:
            assert str(service["user"]).split(":")[0] not in {"root", "0"}

        dockerfile = ROOT / service["build"]["dockerfile"]
        contents = dockerfile.read_text(encoding="utf-8")
        final_stage = re.split(r"(?im)^FROM\s+", contents)[-1]
        users = re.findall(r"(?im)^USER\s+(\S+)", final_stage)
        assert users, f"{dockerfile.name} must declare its runtime user explicitly"
        assert users[-1].split(":")[0].lower() not in {"root", "0"}
        assert not users[-1].startswith("$"), "Runtime user must not be an unchecked build argument"


def test_sensitive_credentials_are_not_image_build_arguments_or_environment():
    paths = {
        ROOT / service["build"]["dockerfile"]
        for service in load_compose().values()
        if "build" in service
    }
    for path in paths:
        for instruction in re.findall(r"(?im)^(?:ARG|ENV)\s+(.+)$", path.read_text()):
            # Handles both ENV KEY=value and the older ENV KEY value syntax.
            variables = set(re.findall(r"(?:^|\s)([A-Z][A-Z0-9_]*)=", instruction))
            if not variables:
                variables.add(instruction.split()[0])
            for variable in variables:
                assert credential_owner(variable) is None, (
                    "Secrets must be supplied only at runtime"
                )


def test_tmpfs_options_remain_one_absolute_restricted_mount_with_a_memory_limit():
    services = load_compose()
    for name in APPLICATION_SERVICES | {"initialize"}:
        assert_restricted_tmpfs(services[name].get("tmpfs"))


def test_unquoted_flow_tmpfs_options_fail_as_malformed_relative_mounts():
    # Historical startup failure: YAML treats these commas as list delimiters.
    broken = yaml.load("tmpfs: [/tmp:rw,noexec,nosuid,size=32m]", Loader=UniqueKeyLoader)
    with pytest.raises(AssertionError, match="Relative tmpfs mount"):
        assert_restricted_tmpfs(broken["tmpfs"])


def test_published_ports_are_loopback_and_host_networking_is_forbidden():
    for name, service in load_compose().items():
        assert service.get("network_mode") != "host"
        for port in service.get("ports", []):
            if isinstance(port, dict):
                assert port.get("host_ip") in {"127.0.0.1", "::1"}, name
            else:
                assert str(port).startswith(("127.0.0.1:", "[::1]:")), name


def test_redis_is_optional_for_application_startup_and_api_readiness(monkeypatch):
    services = load_compose()
    for name in APPLICATION_SERVICES | {"initialize"}:
        assert "redis" not in dependencies(services, name)
    # Even a host's unusable optional Redis setting must not affect DB-only readiness.
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    settings = ApiSettings(
        app_env="test",
        environment_id="paper-test",
        database_url="postgresql+psycopg://trd_api:isolated-test-password@localhost:5432/trd",
    )
    with TestClient(create_app(settings, lambda _settings: True)) as client:
        assert client.get("/health/ready").status_code == 200


def test_host_development_override_cannot_inject_credentials_or_open_ports():
    # Dev overlay only selects which application services run in containers.
    for service in load_compose("docker-compose.dev.yml").values():
        assert not ({"environment", "env_file", "ports", "user", "privileged"} & set(service))


def test_duplicate_compose_override_keys_fail_before_the_contract_is_checked():
    malformed = (
        "services:\n  api:\n    environment:\n"
        "      DATABASE_URL: first\n      DATABASE_URL: second\n"
    )
    with pytest.raises(ValueError, match="Duplicate Compose key: DATABASE_URL"):
        yaml.load(malformed, Loader=UniqueKeyLoader)
