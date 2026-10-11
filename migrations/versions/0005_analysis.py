"""Fenced advisory analysis and conservative provider-spend reservations."""

from pathlib import Path

from alembic import op

revision = "0005_analysis"
down_revision = "0004_telegram"
branch_labels = None
depends_on = None

FUNCTIONS = (
    "analysis_complete(text,uuid,text,integer,jsonb)",
    "analysis_settle_attempt(text,uuid,text,jsonb)",
    "analysis_reserve_attempt(text,uuid,text,integer,uuid,integer,text,integer,integer,integer,jsonb)",
    "analysis_assert_job(text,uuid,text,integer)",
)


def upgrade():
    op.execute(Path(__file__).with_suffix(".sql").read_text(encoding="utf-8"))
    previous = Path(__file__).with_name("0004_telegram.sql").read_text(encoding="utf-8")
    function = previous[
        previous.index("CREATE OR REPLACE FUNCTION public.apply_dashboard_change(") :
    ]
    function = function[: function.index("END; $fn$;") + len("END; $fn$;")]
    function = function.replace(
        "IF value->'enabled' IS DISTINCT FROM 'false'::jsonb",
        "PERFORM pg_advisory_xact_lock(hashtextextended('trd-evidence:'||p_environment,0));\n"
        " IF jsonb_typeof(value->'enabled') IS DISTINCT FROM 'boolean'\n"
        " OR ((value->>'enabled')::boolean AND NOT EXISTS(SELECT 1 FROM public.agents\n"
        " WHERE environment_id=p_environment AND id=agent AND name<>'POSITION_REVIEW_AGENT'))\n"
        " OR ((value->>'enabled')::boolean AND (value->>'prompt_version')::integer<>2)",
    )
    function = function.replace(
        "VALUES(p_environment,agent,next_version,false,value->>'primary_model_id',",
        "VALUES(p_environment,agent,next_version,(value->>'enabled')::boolean,"
        "value->>'primary_model_id',",
    )
    op.execute(function)


def downgrade():
    op.execute("DROP VIEW public.dashboard_costs")
    op.execute(
        "CREATE VIEW public.dashboard_costs AS SELECT environment_id,id,run_id,"
        "input_tokens,output_tokens,estimated_cost_usd::text,pricing_version,usage_known,"
        "created_at FROM public.ai_usage"
    )
    op.execute("GRANT SELECT ON public.dashboard_costs TO trd_api")
    op.execute("DROP VIEW public.dashboard_analyses")
    op.execute("DROP VIEW public.dashboard_agent_runs")
    for function in FUNCTIONS:
        op.execute(f"DROP FUNCTION public.{function}")
    op.execute("DROP TABLE public.ai_budget_reservations")
    op.execute("DROP TABLE public.analysis_records")
    previous = Path(__file__).with_name("0004_telegram.sql").read_text(encoding="utf-8")
    function = previous[
        previous.index("CREATE OR REPLACE FUNCTION public.apply_dashboard_change(") :
    ]
    function = function[: function.index("END; $fn$;") + len("END; $fn$;")]
    op.execute(function)
