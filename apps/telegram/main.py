from backend.application.runtime import run_service
from backend.domain.config import load_settings
from backend.infrastructure.database import database_probe, record_heartbeat
from backend.infrastructure.logging import configure_logging


def main() -> None:
    settings = load_settings("collector")
    configure_logging(settings)
    run_service(settings, database_probe, record_heartbeat)


if __name__ == "__main__":
    main()
