"""Explicit local user provisioning using operator credentials, never browser authority."""

import getpass
import os
from uuid import uuid4

from pydantic import SecretStr
from sqlalchemy import insert, select, text

from backend.application.bootstrap import PASSWORD_HASHER, BootstrapSettings
from backend.infrastructure.database import SCHEMA_REVISION, create_database_engine
from backend.infrastructure.models import AuditEvent, User


def create_user(settings: BootstrapSettings, role: str):
    if role not in {"ADMIN", "VIEWER"}:
        raise ValueError("unsupported user role")
    engine = create_database_engine(settings.migration_database_url.get_secret_value())
    identifier = uuid4()
    try:
        with engine.begin() as connection:
            if (
                connection.scalar(text("SELECT version_num FROM public.alembic_version"))
                != SCHEMA_REVISION
            ):
                raise ValueError("schema migration required")
            connection.execute(text("SET LOCAL ROLE trd_owner"))
            connection.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended('trd-users',0))")
            )
            if connection.scalar(
                select(User.id).where(User.email == settings.admin_bootstrap_email)
            ):
                raise ValueError("existing users require separate reviewed administration")
            connection.execute(
                insert(User).values(
                    id=identifier,
                    email=settings.admin_bootstrap_email,
                    password_hash=PASSWORD_HASHER.hash(
                        settings.admin_bootstrap_password.get_secret_value()
                    ),
                    role=role,
                )
            )
            connection.execute(
                insert(AuditEvent).values(
                    id=uuid4(),
                    environment_id=settings.environment_id,
                    action="USER_CREATED",
                    actor_service="operator",
                    target=str(identifier),
                    details={"role": role},
                )
            )
        return identifier
    finally:
        engine.dispose()


def main() -> int:
    try:
        email = input("Email del nuovo utente: ")
        role = input("Ruolo (VIEWER per lettore, ADMIN per amministratore): ").strip().upper()
        password = getpass.getpass("Password (almeno 16 caratteri): ")
        if password != getpass.getpass("Ripeti la password: "):
            raise ValueError("passwords differ")
        settings = BootstrapSettings(
            migration_database_url=os.environ.get("MIGRATION_DATABASE_URL", ""),
            environment_id=os.environ.get("ENVIRONMENT_ID", "local"),
            admin_bootstrap_email=email,
            admin_bootstrap_password=SecretStr(password),
        )
        create_user(settings, role)
        print("Utente creato. Credenziali non visualizzate.")
        return 0
    except (EOFError, KeyboardInterrupt):
        return 130
    except Exception as error:
        print(f"Creazione non riuscita ({type(error).__name__}). Verifica i dati e il database.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
