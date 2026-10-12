"""Scoped explicit OpenRouter acceptance and immutable registry import."""

import argparse
import os
from pathlib import Path

from sqlalchemy import select, text

from backend.ai.acceptance import OpenRouterAcceptance, OpenRouterManifest, read_document
from backend.ai.acceptance_operator import probe
from backend.domain.config import AiSettings
from backend.infrastructure.database import SCHEMA_REVISION, create_database_engine
from backend.infrastructure.models import User
from backend.infrastructure.repositories import ModelRegistryRepository


def write_receipt(path: Path, receipt: OpenRouterAcceptance) -> None:
    if path.exists():
        raise ValueError("Choose a new private receipt path for this review")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".new")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(receipt.model_dump_json(indent=2) + "\n")
        # Never replace another operator's acceptance artifact.
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def import_models(receipt: OpenRouterAcceptance, database_url: str, admin_email: str) -> None:
    receipt.check(os.environ["ENVIRONMENT_ID"])
    engine = create_database_engine(database_url)
    try:
        with engine.begin() as connection:
            if (
                connection.scalar(text("SELECT version_num FROM public.alembic_version"))
                != SCHEMA_REVISION
            ):
                raise ValueError("The acceptance schema is not deployed")
            actor = connection.scalar(
                select(User.id).where(
                    User.email == admin_email.lower().strip(), User.role == "ADMIN", User.active
                )
            )
            if actor is None:
                raise ValueError("An existing active administrator is required")
            registry = ModelRegistryRepository(connection, receipt.environment_id)
            for model in receipt.models:
                registry.register(model, actor_id=actor)
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["accept", "import"])
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--allow-paid-probe", action="store_true")
    parser.add_argument("--admin-email")
    args = parser.parse_args()
    try:
        if args.action == "accept":
            if not args.allow_paid_probe or args.manifest is None or args.receipt.exists():
                raise ValueError(
                    "Explicit paid synthetic probe and a new receipt path are required"
                )
            manifest = read_document(args.manifest, OpenRouterManifest)
            settings = AiSettings(ai_provider_mode="mock", _env_file=None)
            receipt = probe(manifest, args.manifest.read_bytes(), settings)
            write_receipt(args.receipt, receipt)
            print("Collaudo sintetico superato. Ricevuta privata salvata; agenti ancora invariati.")
        else:
            if not args.admin_email:
                raise ValueError("Administrator identity required")
            receipt = read_document(args.receipt, OpenRouterAcceptance)
            import_models(receipt, os.environ["MIGRATION_DATABASE_URL"], args.admin_email)
            print("Modelli approvati importati. Selezione e attivazione richiedono la dashboard.")
        return 0
    except Exception:
        # Catalogs, credentials and DSNs must never become terminal diagnostics.
        print("Operazione non completata. Verificare manifest, limiti e prerequisiti nella guida.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
