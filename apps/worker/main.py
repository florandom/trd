import argparse

from backend.application.runtime import run_service
from backend.domain.config import load_settings
from backend.infrastructure.database import database_probe, record_heartbeat
from backend.infrastructure.logging import configure_logging


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 1 heartbeat-only worker")
    parser.add_argument("--service", choices=("ai", "maintenance"), required=True)
    arguments = parser.parse_args()
    settings = load_settings(arguments.service)
    configure_logging(settings)
    run_service(settings, database_probe, record_heartbeat)


if __name__ == "__main__":
    main()
