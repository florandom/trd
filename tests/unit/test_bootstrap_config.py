import pytest
from pydantic import ValidationError

from backend.application.bootstrap import BootstrapSettings


def test_bootstrap_requires_an_operator_supplied_password() -> None:
    with pytest.raises(ValidationError):
        BootstrapSettings(
            migration_database_url="postgresql+psycopg://trd_migrator:unused@localhost/test",
            admin_bootstrap_email="admin@example.test",
            admin_bootstrap_password="",
        )


def test_bootstrap_secrets_are_redacted_and_environment_is_validated() -> None:
    settings = BootstrapSettings(
        migration_database_url="postgresql+psycopg://trd_migrator:connection-secret@localhost/test",
        admin_bootstrap_email="admin@example.test",
        admin_bootstrap_password="operator-password-at-least-16",
    )
    assert "operator-password" not in repr(settings)
    assert "connection-secret" not in repr(settings)
    with pytest.raises(ValidationError):
        BootstrapSettings.model_validate(
            {**settings.model_dump(), "environment_id": "bad identity"}
        )


def test_bootstrap_cannot_use_a_runtime_credential() -> None:
    with pytest.raises(ValidationError):
        BootstrapSettings(
            migration_database_url="postgresql+psycopg://trd_api:unused@localhost/test",
            admin_bootstrap_email="admin@example.test",
            admin_bootstrap_password="operator-password-at-least-16",
        )
