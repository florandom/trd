"""Explicit local roles: plaintext passwords never enter DDL or task output."""

from __future__ import annotations

from urllib.parse import unquote, urlsplit

import psycopg
from psycopg import sql

from infra.scripts.environment import ROLE_URLS, postgres_dsn


def provision(values: dict[str, str]) -> None:
    database = values["POSTGRES_DB"]
    roles = {"MIGRATION_DATABASE_URL": "trd_migrator"}
    roles.update({field: role for field, role in ROLE_URLS.values()})
    admin_url = postgres_dsn(values["DATABASE_ADMIN_URL"])
    admin = urlsplit(admin_url)
    role_connections = {}
    # Validate the entire requested role set before any CREATE/GRANT. Password
    # verifiers are still sensitive, even though plaintext does not enter SQL.
    for field, role in roles.items():
        parsed = urlsplit(postgres_dsn(values[field]))
        if (
            unquote(parsed.username or "") != role
            or not parsed.password
            or unquote(parsed.path.lstrip("/")) != database
            or parsed.hostname != admin.hostname
            or (parsed.port or 5432) != (admin.port or 5432)
        ):
            raise ValueError("Role URL must target the provisioned DB with its expected login.")
        role_connections[role] = parsed
    try:
        conn = psycopg.connect(admin_url, autocommit=True)
    except psycopg.errors.InvalidCatalogName:
        # Only the explicitly configured app database may be created; no schema setup by hand.
        parsed = urlsplit(admin_url)
        if unquote(parsed.path.lstrip("/")) != database:
            raise ValueError("Admin URL must name the configured database or postgres.") from None
        admin_url = parsed._replace(path="/postgres").geturl()
        conn = psycopg.connect(admin_url, autocommit=True)
    with conn:
        actual = conn.execute("SELECT current_database()").fetchone()[0]
        if actual not in {database, "postgres"}:
            raise ValueError("Admin URL database differs from the explicit target/maintenance DB.")
        if int(conn.execute("SHOW server_version_num").fetchone()[0]) // 10000 != 17:
            raise ValueError("This foundation requires the tested PostgreSQL 17 major.")
        if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname='trd_owner'").fetchone():
            conn.execute("CREATE ROLE trd_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE")
        owner_flags = conn.execute(
            "SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, "
            "rolreplication, rolbypassrls FROM pg_roles WHERE rolname='trd_owner'"
        ).fetchone()
        if owner_flags != (False, False, False, False, False, False):
            raise ValueError("Existing schema owner has unsafe privileges.")
        if conn.execute(
            "SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member "
            "WHERE r.rolname='trd_owner'"
        ).fetchone():
            raise ValueError("Schema owner must have no inherited role memberships.")
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname=%s", (database,)).fetchone():
            conn.execute(
                sql.SQL("CREATE DATABASE {} OWNER trd_owner").format(sql.Identifier(database))
            )
        for role in roles.values():
            parsed = role_connections[role]
            existing = conn.execute(
                "SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, "
                "rolreplication, rolbypassrls FROM pg_roles WHERE rolname=%s",
                (role,),
            ).fetchone()
            if existing:
                if existing != (True, False, False, False, False, False):
                    raise ValueError("Existing runtime/migration role has unsafe privileges.")
            else:
                encoding = conn.info.encoding
                verifier = conn.pgconn.encrypt_password(
                    unquote(parsed.password).encode(encoding),
                    role.encode(encoding),
                    algorithm=b"scram-sha-256",
                ).decode(encoding)
                conn.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}"
                    ).format(sql.Identifier(role), sql.Literal(verifier))
                )
            memberships = {
                row[0]
                for row in conn.execute(
                    "SELECT parent.rolname FROM pg_auth_members m "
                    "JOIN pg_roles child ON child.oid=m.member "
                    "JOIN pg_roles parent ON parent.oid=m.roleid WHERE child.rolname=%s",
                    (role,),
                )
            }
            allowed_memberships = {"trd_owner"} if role == "trd_migrator" else set()
            if not memberships <= allowed_memberships:
                raise ValueError("Existing service role has unexpected role memberships.")
            conn.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(database), sql.Identifier(role)
                )
            )
            if role == "trd_migrator":
                conn.execute("GRANT trd_owner TO trd_migrator")
            elif conn.execute("SELECT pg_has_role(%s, 'trd_owner', 'MEMBER')", (role,)).fetchone()[
                0
            ]:
                raise ValueError("A runtime role must not be a member of the schema owner.")
    target_url = urlsplit(admin_url)._replace(path=f"/{database}").geturl()
    with psycopg.connect(target_url, autocommit=True) as target:
        target.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        target.execute("GRANT USAGE, CREATE ON SCHEMA public TO trd_owner")
        for role in roles.values():
            target.execute(
                sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(role))
            )
