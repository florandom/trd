"""Phase 1 foundation and least-privilege health contracts.

Revision ID: 0001_foundation
Revises: none
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_foundation"
down_revision = None
branch_labels = None
depends_on = None

RUNTIME_ROLES = ("trd_api", "trd_collector", "trd_ai", "trd_risk", "trd_maintenance")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("role IN ('ADMIN', 'VIEWER')", name="ck_users_role"),
    )
    op.create_table(
        "setting_versions",
        sa.Column("environment_id", sa.String(64), primary_key=True),
        sa.Column("key", sa.String(96), primary_key=True),
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("version >= 1", name="ck_setting_versions_positive"),
    )
    op.create_table(
        "system_settings",
        sa.Column("environment_id", sa.String(64), primary_key=True),
        sa.Column("key", sa.String(96), primary_key=True),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["environment_id", "key", "current_version"],
            ["setting_versions.environment_id", "setting_versions.key", "setting_versions.version"],
            name="fk_system_settings_current_version",
        ),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("environment_id", sa.String(64), nullable=False),
        sa.Column("action", sa.String(96), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("actor_service", sa.String(32), nullable=False),
        sa.Column("target", sa.String(160), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_audit_events_environment_id", "audit_events", ["environment_id"])
    op.create_table(
        "heartbeats",
        sa.Column("environment_id", sa.String(64), primary_key=True),
        sa.Column("service_name", sa.String(32), primary_key=True),
        sa.Column("instance_id", sa.String(128), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "observed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "service_name IN ('api', 'collector', 'ai', 'risk', 'maintenance')",
            name="ck_heartbeats_service",
        ),
        sa.CheckConstraint(
            "status IN ('STARTING', 'HEALTHY', 'DEGRADED', 'STOPPED')", name="ck_heartbeats_status"
        ),
    )

    # Schema ownership may remain with the installation administrator. The
    # provisioner must revoke PUBLIC CREATE; the table owner cannot always do it.
    op.execute("""
        DO $guard$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM pg_namespace n,
              LATERAL aclexplode(COALESCE(n.nspacl, acldefault('n', n.nspowner))) a
            WHERE n.nspname = 'public' AND a.grantee = 0 AND a.privilege_type = 'CREATE'
          ) THEN
            RAISE EXCEPTION 'provisioner must revoke PUBLIC schema CREATE first';
          END IF;
        END;
        $guard$
    """)
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC")
    op.execute(
        "CREATE VIEW public.api_users AS "
        "SELECT id, email, role, active, created_at FROM public.users"
    )
    op.execute(
        "CREATE VIEW public.api_settings AS "
        "SELECT s.environment_id, s.key, s.current_version, v.value "
        "FROM public.system_settings s JOIN public.setting_versions v "
        "ON (v.environment_id, v.key, v.version) = "
        "(s.environment_id, s.key, s.current_version) "
        "WHERE s.key IN ('automation_enabled', 'live_trading_enabled', 'trading_mode', "
        "'raw_log_retention_days', 'ai_response_retention_days', 'telegram_retention_days')"
    )
    op.execute(
        "CREATE VIEW public.api_audit_events AS "
        "SELECT id, environment_id, action, actor_id, actor_service, target, created_at "
        "FROM public.audit_events"
    )
    op.execute(
        "CREATE VIEW public.api_heartbeats AS "
        "SELECT environment_id, service_name, instance_id, status, observed_at "
        "FROM public.heartbeats"
    )
    op.execute("""
        CREATE FUNCTION public.record_service_heartbeat(
          p_environment text, p_service text, p_instance text, p_status text)
        RETURNS void LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, public, pg_temp
        AS $function$
        DECLARE expected_service text;
        BEGIN
          expected_service := CASE session_user
            WHEN 'trd_api' THEN 'api' WHEN 'trd_collector' THEN 'collector'
            WHEN 'trd_ai' THEN 'ai' WHEN 'trd_risk' THEN 'risk'
            WHEN 'trd_maintenance' THEN 'maintenance' ELSE NULL END;
          IF expected_service IS NULL OR p_service IS DISTINCT FROM expected_service THEN
            RAISE EXCEPTION 'heartbeat identity rejected' USING ERRCODE = '42501';
          END IF;
          IF p_environment !~ '^[a-z][a-z0-9_-]{0,63}$' OR p_instance !~ '^[A-Za-z0-9_-]{1,128}$'
             OR p_status NOT IN ('STARTING', 'HEALTHY', 'DEGRADED', 'STOPPED')
             OR p_environment IS NULL OR p_instance IS NULL OR p_status IS NULL THEN
            RAISE EXCEPTION 'invalid heartbeat fields' USING ERRCODE = '22023';
          END IF;
          INSERT INTO public.heartbeats(
            environment_id, service_name, instance_id, status, observed_at)
          VALUES (p_environment, expected_service, p_instance, p_status, clock_timestamp())
          ON CONFLICT (environment_id, service_name, instance_id) DO UPDATE
          SET status = EXCLUDED.status, observed_at = EXCLUDED.observed_at;
        END;
        $function$
    """)
    op.execute(
        "REVOKE ALL ON FUNCTION public.record_service_heartbeat(text,text,text,text) FROM PUBLIC"
    )
    for role in RUNTIME_ROLES:
        op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {role}")
        op.execute(f"GRANT USAGE ON SCHEMA public TO {role}")
        op.execute(f"GRANT SELECT ON public.alembic_version TO {role}")
        op.execute(
            "GRANT EXECUTE ON FUNCTION "
            f"public.record_service_heartbeat(text,text,text,text) TO {role}"
        )
    op.execute(
        "GRANT SELECT ON public.api_users, public.api_settings, "
        "public.api_audit_events, public.api_heartbeats TO trd_api"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE trd_owner IN SCHEMA public "
        "REVOKE ALL ON TABLES FROM PUBLIC"
    )
    op.execute(
        # Schema defaults only add to global defaults. A schema-scoped REVOKE
        # cannot remove PostgreSQL's implicit PUBLIC EXECUTE for new functions.
        "ALTER DEFAULT PRIVILEGES FOR ROLE trd_owner REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC"
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION public.record_service_heartbeat(text,text,text,text)")
    for view in ("api_heartbeats", "api_audit_events", "api_settings", "api_users"):
        op.execute(f"DROP VIEW public.{view}")
    op.drop_table("heartbeats")
    op.drop_index("ix_audit_events_environment_id", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_table("system_settings")
    op.drop_table("setting_versions")
    op.drop_table("users")
