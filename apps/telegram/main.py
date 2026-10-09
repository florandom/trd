from backend.application.telegram import run_collector
from backend.domain.config import load_settings
from backend.infrastructure.logging import configure_logging


def main() -> None:
    settings = load_settings("collector")
    configure_logging(settings)
    run_collector(settings)


if __name__ == "__main__":
    main()
