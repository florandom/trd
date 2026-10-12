"""Fenced Telegram collection and confirmed source management.

Revision ID: 0004_telegram
Revises: 0003_dashboard
"""

from pathlib import Path

from alembic import op

revision = "0004_telegram"
down_revision = "0003_dashboard"
branch_labels = None
depends_on = None

FUNCTIONS = (
    "telegram_account_backoff(text,text,text,integer,integer)",
    "telegram_acquire_lease(text,text,text,integer)",
    "telegram_assert_lease(text,text,text,integer)",
    "telegram_release_lease(text,text,text,integer)",
    "telegram_source_observed(text,text,text,integer,uuid,integer,jsonb)",
    "telegram_ingest(text,text,text,integer,uuid,integer,jsonb,integer)",
    "telegram_invalidate_message(text,uuid)",
)


def upgrade():
    op.execute(Path(__file__).with_suffix(".sql").read_text(encoding="utf-8"))


def downgrade():
    op.execute("DROP VIEW public.dashboard_telegram_messages")
    op.execute("DROP VIEW public.dashboard_sources")
    op.execute(
        "CREATE VIEW public.dashboard_sources AS "
        "SELECT environment_id,id,name,enabled FROM public.telegram_sources"
    )
    op.execute("GRANT SELECT ON public.dashboard_sources TO trd_api")
    previous = Path(__file__).with_name("0003_dashboard.sql").read_text(encoding="utf-8")
    function = previous[previous.index("CREATE FUNCTION public.apply_dashboard_change(") :]
    function = function[: function.index("END; $fn$;") + len("END; $fn$;")]
    op.execute(function.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1))
    for function in FUNCTIONS:
        op.execute(f"DROP FUNCTION public.{function}")
    op.execute("DROP TABLE public.telegram_source_state")
    op.execute("DROP TABLE public.telegram_collector_leases")
    op.execute(
        "ALTER TABLE public.telegram_message_versions DROP CONSTRAINT telegram_revision_unique"
    )
    op.execute(
        "ALTER TABLE public.telegram_message_versions DROP CONSTRAINT telegram_event_kind_check"
    )
    for column in ("event_kind", "revision_hash", "published_at", "media_kind"):
        op.drop_column("telegram_message_versions", column)
    op.execute("ALTER TABLE public.telegram_sources DROP CONSTRAINT telegram_reference_unique")
    op.execute("ALTER TABLE public.telegram_sources DROP CONSTRAINT telegram_source_version_check")
    op.execute(
        "ALTER TABLE public.telegram_sources DROP CONSTRAINT telegram_source_resolution_check"
    )
    for column in ("reference", "access_hash", "peer_kind", "version", "resolution_state"):
        op.drop_column("telegram_sources", column)
    op.execute(
        "GRANT INSERT ON public.telegram_messages, "
        "public.telegram_message_versions TO trd_collector"
    )
