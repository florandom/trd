"""Authenticated dashboard and confirmed, bounded configuration administration."""

from pathlib import Path

from alembic import op

revision = "0003_dashboard"
down_revision = "0002_domain"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(Path(__file__).with_name("0003_dashboard.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    for function in (
        "prune_dashboard_auth(text,integer)",
        "apply_dashboard_change(text,text,text,jsonb,integer)",
        "dashboard_auth_audit(text,uuid,text)",
        "lookup_login_user(text)",
    ):
        op.execute(f"DROP FUNCTION public.{function}")
    for view in (
        "dashboard_audit",
        "dashboard_agents",
        "dashboard_risk",
        "dashboard_sources",
        "dashboard_costs",
        "dashboard_signal_versions",
    ):
        op.execute(f"DROP VIEW public.{view}")
    op.execute("REVOKE ALL ON public.sessions FROM trd_api")
    for table in ("dashboard_confirmations", "auth_challenges", "auth_attempts"):
        op.drop_table(table)
