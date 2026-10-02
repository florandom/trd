"""Development Compose entrypoint; never load an operator .env into services."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "service", choices=["initialize", "api", "risk", "ai", "collector", "maintenance"]
    )
    service = parser.parse_args().service
    if os.environ.get("APP_ENV") != "development":
        raise SystemExit("This Compose entrypoint is for development only.")
    # Host development and containers share credentials, but not network addresses.
    # This fixed address cannot be supplied by signal, dashboard or AI input.
    fields = (
        ["DATABASE_URL"]
        if service != "initialize"
        else [
            "DATABASE_ADMIN_URL",
            "MIGRATION_DATABASE_URL",
            "API_DATABASE_URL",
            "COLLECTOR_DATABASE_URL",
            "AI_DATABASE_URL",
            "RISK_DATABASE_URL",
            "MAINTENANCE_DATABASE_URL",
        ]
    )
    for field in fields:
        value = os.environ.get(field)
        if not value:
            raise SystemExit(f"Required scoped variable missing: {field}")
        os.environ[field] = (
            make_url(value).set(host="postgres", port=5432).render_as_string(hide_password=False)
        )
    if service == "initialize":
        args = [sys.executable, "infra/scripts/task.py", "initialize", "--from-process"]
    elif service in {"api", "risk"}:
        module = "apps.api.main:app" if service == "api" else "apps.worker.bridge:app"
        args = [
            sys.executable,
            "-m",
            "uvicorn",
            module,
            "--host",
            "0.0.0.0",
            "--port",
            "8000" if service == "api" else "8001",
            "--loop",
            "asyncio",
            "--no-access-log",
        ]
    elif service == "collector":
        args = [sys.executable, "-m", "apps.telegram.main"]
    else:
        args = [sys.executable, "-m", "apps.worker.main", "--service", service]
    os.execv(sys.executable, args)


if __name__ == "__main__":
    main()
