"""Disposable PostgreSQL for local paper acceptance; never reads operator .env."""

import os
import secrets
import subprocess
import time
from contextlib import contextmanager
from uuid import uuid4

import psycopg

from infra.scripts.environment import ROLE_URLS, postgres_dsn
from infra.scripts.provision_database import provision

POSTGRES_IMAGE = (
    "postgres:17.11-bookworm@sha256:"
    "639ab7ceb90e13123085b741fb31ef493fba25463002f6da665352e7b534b652"
)


@contextmanager
def disposable_database():
    name = "trd-paper-test-" + uuid4().hex[:12]
    password = secrets.token_urlsafe(32)
    admin = "paper_test_admin"
    env = dict(os.environ, POSTGRES_USER=admin, POSTGRES_PASSWORD=password)
    started = False
    try:
        subprocess.run(
            [
                "docker",
                "run",
                "--detach",
                "--name",
                name,
                "--publish",
                "127.0.0.1::5432",
                "--env",
                "POSTGRES_USER",
                "--env",
                "POSTGRES_PASSWORD",
                "--tmpfs",
                "/var/lib/postgresql/data:rw,size=512m",
                POSTGRES_IMAGE,
            ],
            env=env,
            check=True,
            capture_output=True,
        )
        started = True
        port = (
            subprocess.check_output(["docker", "port", name, "5432/tcp"], text=True)
            .strip()
            .rsplit(":", 1)[1]
        )
        admin_url = f"postgresql+psycopg://{admin}:{password}@127.0.0.1:{port}/postgres"
        for _ in range(100):
            try:
                with psycopg.connect(postgres_dsn(admin_url), connect_timeout=1):
                    break
            except psycopg.OperationalError:
                time.sleep(0.2)
        else:
            raise RuntimeError("Local paper database did not start")
        values = {
            "POSTGRES_DB": "paper_acceptance",
            "DATABASE_ADMIN_URL": admin_url,
            "TEST_ADMIN_DATABASE_URL": admin_url,
        }
        roles = {
            "MIGRATION_DATABASE_URL": "trd_migrator",
            **{field: role for field, role in ROLE_URLS.values()},
        }
        values.update(
            {
                field: f"postgresql+psycopg://{role}:{secrets.token_urlsafe(32)}@127.0.0.1:{port}/paper_acceptance"
                for field, role in roles.items()
            }
        )
        provision(values)
        yield values
    finally:
        if started:
            subprocess.run(["docker", "rm", "--force", name], check=True, capture_output=True)
