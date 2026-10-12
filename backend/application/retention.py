"""One bounded, resumable cleanup batch using the maintenance credential only."""

import json
import sys

from backend.domain.config import load_settings
from backend.infrastructure.database import Database
from backend.infrastructure.repositories import DomainTransaction


def main() -> int:
    database = None
    try:
        settings = load_settings("maintenance")
        database = Database(settings.database_url.get_secret_value(), "maintenance")
        if database.schema_status() != "current":
            raise RuntimeError("current migration is required")
        with DomainTransaction(database.engine, settings.environment_id) as uow:
            counts = uow.retention.prune(limit=100)
            counts.update(uow.retention.prune_auth(limit=100))
        print(json.dumps({"status": "ok", **counts}))
        return 0
    except Exception as error:
        print(json.dumps({"status": "failed", "error_type": type(error).__name__}), file=sys.stderr)
        return 1
    finally:
        if database is not None:
            database.close()


if __name__ == "__main__":
    raise SystemExit(main())
