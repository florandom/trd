"""Account-locked paper bridge, durable authentication and conservative exposure."""

from pathlib import Path

from alembic import op
from sqlalchemy import text

revision = "0007_paper_bridge"
down_revision = "0005b_remote_openrouter"
branch_labels = None
depends_on = None

TABLES = (
    "bridge_enrollments",
    "bridge_snapshots",
    "bridge_daily_baselines",
    "bridge_requests",
    "paper_command_records",
    "bridge_decisions",
)


def upgrade():
    op.execute(Path(__file__).with_name("0007_paper_bridge_schema.sql").read_text())
    mutable = {
        "bridge_enrollments": "highwater,fault_latched,journal_id",
        "bridge_daily_baselines": "net_cash_flow,loss_latched",
        "paper_command_records": "remaining_risk,remaining_notional,remaining_margin,send_intent",
    }
    for table in TABLES:
        op.execute(
            f"CREATE TRIGGER fence_{table} BEFORE INSERT OR UPDATE ON public.{table} "
            "FOR EACH ROW EXECUTE FUNCTION public.domain_evidence_fence()"
        )
        if table in mutable:
            op.execute(
                f"CREATE TRIGGER identity_{table} BEFORE UPDATE ON public.{table} "
                f"FOR EACH ROW EXECUTE FUNCTION public.protect_domain_identity('{mutable[table]}')"
            )
        else:
            op.execute(
                f"CREATE TRIGGER protect_{table} BEFORE UPDATE OR DELETE ON public.{table} "
                "FOR EACH ROW EXECUTE FUNCTION public.protect_domain_record('')"
            )
    op.execute("GRANT SELECT ON " + ",".join("public." + t for t in TABLES) + " TO trd_risk")
    op.execute(
        "GRANT INSERT ON "
        + ",".join("public." + t for t in TABLES if t != "bridge_enrollments")
        + " TO trd_risk"
    )
    for table, fields in mutable.items():
        op.execute(f"GRANT UPDATE({fields}) ON public.{table} TO trd_risk")
    op.execute(
        "GRANT SELECT ON public.telegram_sources,public.telegram_messages,"
        "public.telegram_message_versions,public.analysis_records,public.agents,"
        "public.agent_configs,public.agent_runs,public.model_registry TO trd_risk"
    )
    op.execute("GRANT UPDATE(entry_price) ON public.positions TO trd_risk")
    op.execute("DROP TRIGGER identity_positions ON public.positions")
    op.execute(
        "CREATE TRIGGER identity_positions BEFORE UPDATE ON public.positions "
        "FOR EACH ROW EXECUTE FUNCTION "
        "public.protect_domain_identity('status,volume,closed_at,entry_price')"
    )
    op.execute(Path(__file__).with_name("0007_paper_bridge_contracts.sql").read_text())
    for table, function in (
        ("trading_accounts", "paper_account_guard"),
        ("bridge_enrollments", "paper_enrollment_guard"),
        ("bridge_daily_baselines", "paper_baseline_guard"),
    ):
        op.execute(f"REVOKE ALL ON FUNCTION public.{function}() FROM PUBLIC")
        operation = "INSERT OR UPDATE" if table == "bridge_enrollments" else "UPDATE"
        op.execute(
            f"CREATE TRIGGER {function} BEFORE {operation} ON public.{table} "
            f"FOR EACH ROW EXECUTE FUNCTION public.{function}()"
        )
    op.execute("REVOKE ALL ON FUNCTION public.record_paper_audit(text,uuid,text,jsonb) FROM PUBLIC")
    op.execute(
        "GRANT EXECUTE ON FUNCTION public.record_paper_audit(text,uuid,text,jsonb) TO trd_risk"
    )


def downgrade():
    if any(op.get_bind().scalar(text(f"SELECT EXISTS(SELECT 1 FROM public.{t})")) for t in TABLES):
        raise RuntimeError("Paper evidence exists; downgrade requires a fresh empty database")
    op.execute("DROP FUNCTION public.record_paper_audit(text,uuid,text,jsonb)")
    op.execute("DROP TRIGGER paper_account_guard ON public.trading_accounts")
    op.execute("DROP FUNCTION public.paper_account_guard()")
    for table in reversed(TABLES):
        op.drop_table(table)
    op.execute("DROP FUNCTION public.paper_enrollment_guard()")
    op.execute("DROP FUNCTION public.paper_baseline_guard()")
    op.execute("REVOKE UPDATE(entry_price) ON public.positions FROM trd_risk")
    op.execute("DROP TRIGGER identity_positions ON public.positions")
    op.execute(
        "CREATE TRIGGER identity_positions BEFORE UPDATE ON public.positions "
        "FOR EACH ROW EXECUTE FUNCTION public.protect_domain_identity('status,volume,closed_at')"
    )
    # Restore the previous fixed functions via their preceding migrations.
    for name in ("dashboard", "invalidation"):
        op.execute(Path(__file__).with_name(f"0007_previous_{name}.sql").read_text())
