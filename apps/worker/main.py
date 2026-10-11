import argparse

from backend.application.runtime import run_service
from backend.domain.config import load_settings
from backend.infrastructure.database import database_probe, record_heartbeat
from backend.infrastructure.logging import configure_logging


def main() -> None:
    parser = argparse.ArgumentParser(description="Scoped advisory/maintenance worker")
    parser.add_argument("--service", choices=("ai", "maintenance"), required=True)
    arguments = parser.parse_args()
    settings = load_settings(arguments.service)
    configure_logging(settings)
    if arguments.service == "ai":
        from backend.application.analysis import AnalysisWorker
        from backend.infrastructure.analysis_repository import AnalysisStore
        from backend.infrastructure.database import create_database_engine

        engine = create_database_engine(settings.database_url.get_secret_value())
        worker = AnalysisWorker(settings, AnalysisStore(engine, settings.environment_id))
        try:
            run_service(
                settings, lambda cfg: database_probe(cfg) and worker.process_one(), record_heartbeat
            )
        finally:
            engine.dispose()
    else:
        run_service(settings, database_probe, record_heartbeat)


if __name__ == "__main__":
    main()
