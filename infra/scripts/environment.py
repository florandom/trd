"""Operator environment preparation and least-privilege runtime projection."""

from __future__ import annotations

import json
import os
import re
import secrets
from io import StringIO
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
PLACEHOLDER = "__GENERATE__"
ROLE_URLS = {
    "api": ("API_DATABASE_URL", "trd_api"),
    "collector": ("COLLECTOR_DATABASE_URL", "trd_collector"),
    "ai": ("AI_DATABASE_URL", "trd_ai"),
    "risk": ("RISK_DATABASE_URL", "trd_risk"),
    "maintenance": ("MAINTENANCE_DATABASE_URL", "trd_maintenance"),
}
COMMON = {
    "APP_ENV",
    "APP_URL",
    "ENVIRONMENT_ID",
    "TIMEZONE",
    "LOG_LEVEL",
    "TRADING_MODE",
    "ENABLE_AUTOMATION",
    "ENABLE_LIVE_TRADING",
    "LOG_MAX_BYTES",
    "LOG_BACKUP_COUNT",
}
ROLE_FIELDS = {
    "api": {
        "REMOTE_ACCESS_MODE",
        "DASHBOARD_PROXY_SECRET",
        "AUTH_COOKIE_SECURE",
        "AUTH_SESSION_TTL_SECONDS",
        "AUTH_IDLE_TTL_SECONDS",
        "AUTH_MFA_REQUIRED",
        "AUTH_ALLOWED_ORIGINS",
        "CLOUDFLARE_ACCESS_ISSUER",
        "CLOUDFLARE_ACCESS_AUDIENCE",
        "ENCRYPTION_KEY",
        "REDIS_ENABLED",
        "REDIS_URL",
    },
    "collector": {
        "TELEGRAM_ENABLED",
        "TELEGRAM_API_ID",
        "TELEGRAM_API_HASH",
        "TELEGRAM_SESSION_ENCRYPTION_KEY",
        "TELEGRAM_SESSION_PATH",
        "TELEGRAM_BACKFILL_MAX_AGE_SECONDS",
        "TELEGRAM_SESSION_KEY_ID",
        "TELEGRAM_COLLECTOR_IDENTITY",
        "TELEGRAM_POLL_SECONDS",
        "TELEGRAM_HISTORY_BATCH_SIZE",
        "TELEGRAM_REQUEST_TIMEOUT_SECONDS",
        "TELEGRAM_SIGNAL_MAX_AGE_SECONDS",
    },
    "ai": {
        "OPENROUTER_API_KEY",
        "OPENROUTER_MANIFEST_PATH",
        "OPENROUTER_ACCEPTANCE_PATH",
        "AI_HARD_MAX_INPUT_TOKENS",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_AI_API_KEY",
        "MOONSHOT_API_KEY",
        "TYPESAFE_API_KEY",
        "AI_PROVIDER_MODE",
        "MODEL_REGISTRY_PATH",
        "PROMPT_MANIFEST_PATH",
        "AI_HARD_DAILY_BUDGET_USD",
        "AI_HARD_MONTHLY_BUDGET_USD",
        "AI_HARD_DAILY_BUDGET_PER_AGENT_USD",
        "AI_HARD_MAX_COST_PER_REQUEST_USD",
        "AI_HARD_MAX_OUTPUT_TOKENS",
        "AI_HARD_TIMEOUT_SECONDS",
        "AI_SIGNAL_MAX_AGE_SECONDS",
        "AI_JOB_LEASE_SECONDS",
        "ENABLE_CRITIC_AGENT",
        "ENABLE_ADAPTIVE_MEMORY",
    },
    "risk": {
        "PAPER_BRIDGE_ENABLED",
        "PAPER_PROFILE_PATH",
        "PAPER_REQUEST_KEY",
        "PAPER_RESPONSE_KEY",
        "MT5_BRIDGE_SHARED_SECRET",
        "MT5_COMMAND_SIGNING_KEY",
        "MT5_ALLOWED_ACCOUNT_IDS",
        "MT5_BRIDGE_INSTANCE_ID",
        "MT5_BRIDGE_KEY_ID",
        "MT5_BRIDGE_URL",
        "MT5_COMMAND_TTL_SECONDS",
        "MT5_HEARTBEAT_MAX_AGE_SECONDS",
        "MT5_MAX_CLOCK_SKEW_SECONDS",
        "MANAGED_MAGIC_NUMBER",
        "ENABLE_PENDING_ORDERS",
        "ENABLE_PARTIAL_CLOSE",
    },
    "maintenance": {
        "ALERT_TELEGRAM_BOT_TOKEN",
        "ALERT_TELEGRAM_CHAT_ID",
        "ALERT_COOLDOWN_SECONDS",
        "RAW_LOG_RETENTION_DAYS",
        "AI_RESPONSE_RETENTION_DAYS",
        "TELEGRAM_RETENTION_DAYS",
        "AUDIT_RETENTION_DAYS",
        "TRADE_RETENTION_DAYS",
    },
}
OS_FIELDS = {
    "PATH",
    "SystemRoot",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "PATHEXT",
    "TEMP",
    "TMP",
    "LANG",
    "LC_ALL",
    "HOME",
    "USERPROFILE",
    "LOCALAPPDATA",
    "APPDATA",
    "PNPM_HOME",
    "NUMBER_OF_PROCESSORS",
    "UV_CACHE_DIR",
}


def read_environment(path: Path | None = None) -> dict[str, str]:
    source = path or ROOT / ".env"
    if not source.is_file():
        raise ValueError("Local environment missing. Run pnpm setup first.")
    values = {key: value or "" for key, value in dotenv_values(source).items()}
    # Operator overrides are limited to declared template keys, not arbitrary env injection.
    for key in values:
        if key in os.environ:
            values[key] = os.environ[key]
    if PLACEHOLDER in values.values():
        raise ValueError("Environment contains placeholders. Run pnpm setup first.")
    return values


def prepare_environment(path: Path | None = None) -> Path:
    target = path or ROOT / ".env"
    template = (ROOT / ".env.example").read_text(encoding="utf-8")
    source = target.read_text(encoding="utf-8") if target.exists() else template
    values = {key: value or "" for key, value in dotenv_values(stream=StringIO(source)).items()}
    if values.get("APP_ENV") != "development" or values.get("TRADING_MODE") != "paper":
        raise ValueError("Automatic environment generation is development/paper only.")
    if any(
        values.get(field, "false").lower() != "false"
        for field in ("ENABLE_AUTOMATION", "ENABLE_LIVE_TRADING")
    ):
        raise ValueError("Automatic environment generation requires automation and live off.")
    generated: dict[str, str] = {}
    for key, value in values.items():
        if value != PLACEHOLDER or key.endswith("DATABASE_URL") or key == "DATABASE_ADMIN_URL":
            continue
        generated[key] = (
            secrets.token_hex(32)
            if key.endswith("KEY") or "SECRET" in key
            else secrets.token_urlsafe(32)
        )
    values.update(generated)
    host = values.get("POSTGRES_HOST", "127.0.0.1")
    port = values.get("POSTGRES_PORT", "5432")
    database = values.get("POSTGRES_DB", "trd")
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,40}", database):
        raise ValueError("Use a simple lowercase development database name.")
    dsn_roles = {
        "DATABASE_ADMIN_URL": values.get("POSTGRES_USER", "trd_bootstrap"),
        "MIGRATION_DATABASE_URL": "trd_migrator",
        **{field: role for field, role in ROLE_URLS.values()},
    }
    for field, role in dsn_roles.items():
        if values.get(field) != PLACEHOLDER:
            continue
        password = (
            values["POSTGRES_PASSWORD"]
            if field == "DATABASE_ADMIN_URL"
            else secrets.token_urlsafe(32)
        )
        generated[field] = (
            f"postgresql+psycopg://{quote(role, safe='')}:{quote(password, safe='')}"
            f"@{host}:{port}/{database}"
        )
    # Preserve comments/order and all existing values; only declared placeholders change.
    for key, value in generated.items():
        source = re.sub(
            rf"^{re.escape(key)}={PLACEHOLDER}$", f"{key}={value}", source, flags=re.MULTILINE
        )
    # Customized quoting/comments are not silently accepted as generated credentials.
    if PLACEHOLDER in dotenv_values(stream=StringIO(source)).values():
        raise ValueError("Unresolved placeholders; use the exact template assignment format.")
    temporary = target.with_name(target.name + ".new")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as output:
            output.write(source)
        os.replace(temporary, target)
        target.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def runtime_environment(service: str, values: dict[str, str]) -> dict[str, str]:
    if service not in ROLE_URLS:
        raise ValueError("Unknown runtime service identity.")
    fields = COMMON | ROLE_FIELDS[service]
    if service == "risk":
        fields |= {key for key in values if key.startswith("HARD_")}
    result = {key: value for key, value in os.environ.items() if key in OS_FIELDS}
    result.update({key: values[key] for key in fields if key in values})
    result["DATABASE_URL"] = values[ROLE_URLS[service][0]]
    result["SERVICE_IDENTITY"] = service
    state = values.get("RUNTIME_STATE_DIR")
    state_root = Path(state) if state else ROOT
    if state and not state_root.is_absolute():
        raise ValueError("RUNTIME_STATE_DIR must be absolute")
    if values.get("APP_ENV") in {"staging", "production"} and not state:
        raise ValueError("Remote deployments require an independent RUNTIME_STATE_DIR")
    result["DATA_DIR"] = str(state_root / "data" / service)
    result["LOG_DIR"] = str(state_root / "logs" / service)
    result["PYTHONUNBUFFERED"] = "1"
    return result


def prepare_deployment(stage: str, destination: Path) -> Path:
    if stage not in {"staging", "production"} or destination.exists():
        raise ValueError("Choose staging or production and a new private directory")
    destination.mkdir(mode=0o700, parents=True)
    target = destination / "operator.env"
    source = (ROOT / (".env." + stage + ".example")).read_text(encoding="utf-8")
    source = source.replace("APP_ENV=" + stage, "APP_ENV=development", 1)
    source = source.replace(
        "RUNTIME_STATE_DIR=REPLACE_WITH_ABSOLUTE_PRIVATE_STATE_DIRECTORY",
        "RUNTIME_STATE_DIR=" + json.dumps(str(destination.resolve() / "state"), ensure_ascii=False),
    )
    with os.fdopen(
        os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w", encoding="utf-8"
    ) as output:
        output.write(source)
    prepare_environment(target)
    source = target.read_text(encoding="utf-8").replace(
        "APP_ENV=development", "APP_ENV=" + stage, 1
    )
    target.write_text(source, encoding="utf-8")
    return target


def dashboard_environment(values: dict[str, str]) -> dict[str, str]:
    fields = {
        "API_INTERNAL_URL",
        "DASHBOARD_PROXY_SECRET",
        "CF_ACCESS_CLIENT_ID",
        "CF_ACCESS_CLIENT_SECRET",
    }
    result = {key: value for key, value in os.environ.items() if key in OS_FIELDS}
    result.update({key: values[key] for key in fields if key in values})
    result.update(
        DASHBOARD_ACCESS_MODE=values.get("REMOTE_ACCESS_MODE", "local"),
        DASHBOARD_ENVIRONMENT_ID=values["ENVIRONMENT_ID"],
        DASHBOARD_DEPLOYMENT_ENV=values.get("APP_ENV", "development"),
        DASHBOARD_PUBLIC_URL=values.get("APP_URL", "http://localhost:3000"),
        NEXT_TELEMETRY_DISABLED="1",
    )
    return result


def export_environments(values: dict[str, str], destination: Path) -> None:
    """Generate a new, private directory. Never print credentials or overwrite files."""
    from backend.domain.config import AiSettings, ApiSettings, BridgeSettings, CollectorSettings

    projections = {role: runtime_environment(role, values) for role in ROLE_URLS}
    projections["dashboard"] = dashboard_environment(values)
    classes = {
        "api": ApiSettings,
        "ai": AiSettings,
        "risk": BridgeSettings,
        "collector": CollectorSettings,
    }
    for role, contract in classes.items():
        contract.model_validate({key.lower(): value for key, value in projections[role].items()})
    if destination.exists():
        raise ValueError("Export directory already exists; choose a new private review directory")
    destination.mkdir(mode=0o700, parents=True)
    for role, projection in projections.items():
        filename = {"collector": "telegram", "risk": "bridge"}.get(role, role)
        path = destination / (".env." + filename)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as output:
            for key, value in sorted(projection.items()):
                if key not in OS_FIELDS:
                    # Quoted dotenv values preserve paths, dollar signs and backslashes.
                    if any(char in value for char in ("\n", "\r", "\0")):
                        raise ValueError("Multiline environment values are unsupported")
                    output.write(key + "=" + json.dumps(value, ensure_ascii=False) + "\n")


def postgres_dsn(url: str) -> str:
    parsed = urlsplit(url.replace("postgresql+psycopg://", "postgresql://", 1))
    if parsed.scheme != "postgresql":
        raise ValueError("Expected a PostgreSQL URL.")
    return urlunsplit(parsed)
