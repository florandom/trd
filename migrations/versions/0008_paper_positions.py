"""Confirmed local paper position operations and result history."""

from pathlib import Path

from alembic import op
from sqlalchemy import text

revision = "0008_paper_positions"
down_revision = "0007_paper_bridge"
branch_labels = None
depends_on = None
TABLES = ("paper_position_state", "paper_operations", "paper_operation_results")


def sql(name):
    op.execute(Path(__file__).with_name(name).read_text())


def upgrade():
    sql("0008_paper_positions_schema.sql")
    op.execute("ALTER TABLE public.execution_commands ALTER COLUMN reservation_id DROP NOT NULL")
    for table, mutable in (
        ("paper_position_state", "revision,stop_loss,take_profit"),
        ("paper_operations", "command_id,state,reason"),
        ("paper_operation_results", None),
    ):
        op.execute(
            f"CREATE TRIGGER fence_{table} BEFORE INSERT OR UPDATE ON public.{table} "
            "FOR EACH ROW EXECUTE FUNCTION public.domain_evidence_fence()"
        )
        function = (
            f"protect_domain_identity('{mutable}')" if mutable else "protect_domain_record('')"
        )
        operation = "UPDATE" if mutable else "UPDATE OR DELETE"
        op.execute(
            f"CREATE TRIGGER identity_{table} BEFORE {operation} ON public.{table} "
            f"FOR EACH ROW EXECUTE FUNCTION public.{function}"
        )
        op.execute(f"GRANT SELECT ON public.{table} TO trd_risk")
        if table != "paper_operations":
            op.execute(f"GRANT INSERT ON public.{table} TO trd_risk")
        if mutable:
            op.execute(f"GRANT UPDATE({mutable}) ON public.{table} TO trd_risk")
    sql("0008_paper_positions_contracts.sql")
    sql("0008_paper_positions_dashboard.sql")
    sql("0008_paper_positions_lifecycle.sql")
    # Existing paper positions retain their original protections and revision one.
    op.execute("""INSERT INTO public.paper_position_state
    (environment_id,id,account_id,position_id,stop_loss,take_profit)
    SELECT p.environment_id,gen_random_uuid(),p.account_id,p.id,
    (convert_from(c.payload,'UTF8')::jsonb->>'stop_loss')::numeric,
    (convert_from(c.payload,'UTF8')::jsonb->>'take_profit')::numeric
    FROM public.positions p JOIN public.orders o
    ON (o.environment_id,o.id)=(p.environment_id,p.order_id)
    JOIN public.execution_commands c ON (c.environment_id,c.id)=(o.environment_id,o.command_id)
    JOIN public.bridge_enrollments b
    ON (b.environment_id,b.account_id)=(p.environment_id,p.account_id)""")


def downgrade():
    if op.get_bind().scalar(text("SELECT EXISTS(SELECT 1 FROM public.paper_operations)")):
        raise RuntimeError(
            "Position operation evidence exists; downgrade requires a fresh database"
        )
    for view in ("api_paper_operations", "api_paper_accounts"):
        op.execute(f"DROP VIEW public.{view}")
    op.execute("DROP VIEW public.api_positions")
    op.execute(
        "CREATE VIEW public.api_positions AS SELECT environment_id,id,account_id,order_id,"
        "broker_identifier,symbol,volume::text AS volume,entry_price::text AS entry_price,"
        "status,opened_at,closed_at FROM public.positions"
    )
    op.execute("GRANT SELECT ON public.api_positions TO trd_api")
    sql("0008_previous_dashboard.sql")
    sql("0008_previous_lifecycle.sql")
    # Restore the original enrollment fence before dropping its referenced requests.
    old = Path(__file__).with_name("0007_paper_bridge_contracts.sql").read_text()
    start = old.index("CREATE OR REPLACE FUNCTION public.paper_enrollment_guard()")
    end = old.index("CREATE OR REPLACE FUNCTION public.paper_baseline_guard()", start)
    op.execute(old[start:end])
    audit_end = old.index("CREATE OR REPLACE FUNCTION public.apply_dashboard_change")
    op.execute(old[:audit_end].replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1))
    op.execute("DROP TRIGGER paper_operation_guard ON public.paper_operations")
    op.execute("DROP FUNCTION public.paper_operation_guard()")
    op.execute("DROP TRIGGER paper_command_guard ON public.execution_commands")
    op.execute("DROP FUNCTION public.paper_command_guard()")
    for table in reversed(TABLES):
        op.drop_table(table)
    op.execute("ALTER TABLE public.execution_commands ALTER COLUMN reservation_id SET NOT NULL")
