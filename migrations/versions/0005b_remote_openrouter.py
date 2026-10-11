"""Remote identity binding and expiring, budgeted OpenRouter advisory models.

This is preparation before implementation phase 6, not the financial risk gateway.
"""

from pathlib import Path

from alembic import op
from sqlalchemy import inspect, text

revision = "0005b_remote_openrouter"
down_revision = "0005_analysis"
branch_labels = None
depends_on = None


def previous_function(name: str) -> str:
    source = Path(__file__).with_name("0005_analysis.sql").read_text()
    start = source.index("CREATE FUNCTION public." + name + "(")
    return source[start : source.index("END; $fn$;", start) + len("END; $fn$;")].replace(
        "CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1
    )


def phase5_dashboard() -> str:
    source = Path(__file__).with_name("0004_telegram.sql").read_text()
    start = source.index("CREATE OR REPLACE FUNCTION public.apply_dashboard_change(")
    function = source[start : source.index("END; $fn$;", start) + len("END; $fn$;")]
    return function.replace(
        "IF value->'enabled' IS DISTINCT FROM 'false'::jsonb",
        "PERFORM pg_advisory_xact_lock(hashtextextended('trd-evidence:'||p_environment,0));\n"
        " IF jsonb_typeof(value->'enabled') IS DISTINCT FROM 'boolean'\n"
        " OR ((value->>'enabled')::boolean AND NOT EXISTS(SELECT 1 FROM public.agents\n"
        " WHERE environment_id=p_environment AND id=agent AND name<>'POSITION_REVIEW_AGENT'))\n"
        " OR ((value->>'enabled')::boolean AND (value->>'prompt_version')::integer<>2)",
    ).replace(
        "VALUES(p_environment,agent,next_version,false,value->>'primary_model_id',",
        "VALUES(p_environment,agent,next_version,(value->>'enabled')::boolean,value->>'primary_model_id',",
    )


def replace_required(value: str, old: str, new: str) -> str:
    if value.count(old) != 1:
        raise RuntimeError("Unexpected previous migration contract")
    return value.replace(old, new)


def provider_constraint(values: str):
    for check in inspect(op.get_bind()).get_check_constraints("model_registry"):
        if "provider" in check["sqltext"]:
            op.drop_constraint(check["name"], "model_registry", type_="check")
    op.create_check_constraint("ck_model_registry_provider", "model_registry", values)


def upgrade():
    op.execute("ALTER TABLE public.sessions ADD COLUMN external_subject_hash varchar(64)")
    op.execute("ALTER TABLE public.ai_usage ADD COLUMN reported_cost_usd numeric(28,10)")
    op.execute(
        "ALTER TABLE public.model_registry ADD COLUMN input_token_limit integer NOT NULL DEFAULT 0"
    )
    for column, definition in (
        ("provider_slug", "varchar(64)"),
        ("provider_label", "varchar(96)"),
        ("accepted_environment_id", "varchar(64)"),
        ("accepted_until", "timestamptz"),
    ):
        op.execute(f"ALTER TABLE public.model_registry ADD COLUMN {column} {definition}")
    provider_constraint(
        "provider IN ('mock','openrouter','openai','anthropic','google','moonshot','typesafe')"
    )
    op.execute(
        "CREATE OR REPLACE VIEW public.api_models AS SELECT id,provider,model_name,enabled,"
        "schema_version,max_output_tokens,pricing_version,currency,input_price_per_million::text,"
        "output_price_per_million::text,input_token_limit,provider_slug,provider_label,"
        "accepted_environment_id,accepted_until FROM public.model_registry"
    )
    function = phase5_dashboard()
    function = replace_required(
        function,
        "OR (value->>'max_cost_usd')::numeric<>0",
        "OR value->>'max_cost_usd' IS NULL OR value->>'max_cost_usd' !~ "
        "'^[0-9]{1,18}(\\.[0-9]{1,10})?$' "
        "OR ((value->>'max_cost_usd')::numeric<>0 AND NOT EXISTS("
        "SELECT 1 FROM public.model_registry m "
        "WHERE m.provider='openrouter' AND (m.id=value->>'primary_model_id' "
        "OR value->'fallback_model_ids' ? m.id)))",
    )
    function = replace_required(
        function,
        "AND m.provider='mock'",
        "AND (m.provider='mock' OR ("
        "m.provider='openrouter' AND m.accepted_environment_id=p_environment "
        "AND m.input_token_limit BETWEEN 1 AND 1000000 AND m.provider_slug IS NOT NULL "
        "AND EXISTS(SELECT 1 FROM public.agents a WHERE a.environment_id=p_environment "
        "AND a.id=agent AND a.name IN ('MARKET_ANALYST','DECISION_AGENT','CRITIC')) "
        "AND (NOT (value->>'enabled')::boolean OR (m.accepted_until>clock_timestamp() "
        "AND (value->>'max_cost_usd')::numeric>0))))",
    )
    function = replace_required(
        function,
        "(value->>'max_output_tokens')::integer,0,(value->>'required_schema_version')::integer,actor);",
        "(value->>'max_output_tokens')::integer,(value->>'max_cost_usd')::numeric,"
        "(value->>'required_schema_version')::integer,actor);",
    )
    op.execute(function)

    op.execute("DROP TRIGGER identity_ai_budget ON public.ai_budget_reservations")
    op.execute(
        "CREATE TRIGGER identity_ai_budget BEFORE UPDATE ON public.ai_budget_reservations "
        "FOR EACH ROW EXECUTE FUNCTION public.protect_domain_identity("
        "'state,charged_usd,settled_at,reserved_usd')"
    )

    function = previous_function("analysis_reserve_attempt")
    function = replace_required(
        function,
        "OR model.enabled IS DISTINCT FROM true",
        "OR (model.provider='openrouter' AND ("
        "model.accepted_environment_id IS DISTINCT FROM p_environment "
        "OR model.accepted_until IS NULL OR model.accepted_until<=clock_timestamp() "
        "OR p_input IS DISTINCT FROM model.input_token_limit)) "
        "OR model.enabled IS DISTINCT FROM true",
    )
    function = replace_required(
        function,
        "'pricing_version',model.pricing_version,",
        "'provider',model.provider,'model_name',model.model_name,'provider_slug',model.provider_slug,"
        "'pricing_version',model.pricing_version,",
    )
    op.execute(function)

    function = previous_function("analysis_settle_attempt")
    function = replace_required(
        function,
        "cost numeric; known boolean;",
        "cost numeric; estimate numeric; reported numeric; provider text; known boolean;",
    )
    function = replace_required(function, "cost:=ceil(", "estimate:=ceil(")
    function = replace_required(
        function,
        " IF (p_result->>'input_tokens')::integer>",
        " SELECT m.provider INTO provider FROM public.model_registry m WHERE m.id=item.model_id;\n"
        " IF p_result->>'reported_cost_usd' ~ '^[0-9]{1,18}(\\.[0-9]{1,10})?$' THEN\n"
        " reported:=(p_result->>'reported_cost_usd')::numeric; END IF;\n"
        " IF provider='openrouter' AND reported IS NULL THEN known:=false; END IF;\n"
        " cost:=GREATEST(estimate,COALESCE(reported,0));\n"
        " IF (p_result->>'input_tokens')::integer>",
    )
    function = replace_required(
        function,
        "charged_usd=CASE WHEN known THEN cost END,settled_at=clock_timestamp()",
        "charged_usd=CASE WHEN known THEN cost END,reserved_usd=GREATEST(item.reserved_usd,cost),"
        "settled_at=clock_timestamp()",
    )
    function = replace_required(
        function,
        "estimated_cost_usd,pricing_version,usage_known)",
        "estimated_cost_usd,pricing_version,usage_known,reported_cost_usd)",
    )
    function = replace_required(
        function,
        "item.snapshot->>'pricing_version',known);",
        "item.snapshot->>'pricing_version',known,reported);",
    )
    op.execute(function)
    op.execute("DROP VIEW public.dashboard_costs")
    op.execute(
        "CREATE VIEW public.dashboard_costs AS "
        "SELECT u.environment_id,u.id,u.run_id,u.input_tokens,u.output_tokens,"
        "u.estimated_cost_usd::text,u.pricing_version,u.usage_known,u.created_at,"
        "COALESCE(b.state,'SETTLED')::varchar(16) AS budget_state,"
        "b.reserved_usd::text,b.charged_usd::text,u.reported_cost_usd::text "
        "FROM public.ai_usage u LEFT JOIN public.ai_budget_reservations b "
        "ON (b.environment_id,b.id)=(u.environment_id,u.run_id) "
        "UNION ALL SELECT b.environment_id,b.id,b.id,0,0,b.reserved_usd::text,"
        "b.snapshot->>'pricing_version',"
        "false,b.created_at,b.state,b.reserved_usd::text,NULL::text,NULL::text "
        "FROM public.ai_budget_reservations b WHERE NOT EXISTS(SELECT 1 FROM public.ai_usage u "
        "WHERE (u.environment_id,u.run_id)=(b.environment_id,b.id))"
    )
    op.execute("GRANT SELECT ON public.dashboard_costs TO trd_api")


def downgrade():
    if op.get_bind().scalar(
        text("SELECT count(*) FROM public.model_registry WHERE provider='openrouter'")
    ):
        raise RuntimeError(
            "OpenRouter history requires a reviewed migration; it cannot be silently removed"
        )
    op.execute(phase5_dashboard())
    op.execute(previous_function("analysis_reserve_attempt"))
    op.execute(previous_function("analysis_settle_attempt"))
    op.execute("DROP TRIGGER identity_ai_budget ON public.ai_budget_reservations")
    op.execute(
        "CREATE TRIGGER identity_ai_budget BEFORE UPDATE ON public.ai_budget_reservations "
        "FOR EACH ROW EXECUTE FUNCTION public.protect_domain_identity("
        "'state,charged_usd,settled_at')"
    )
    op.execute("DROP VIEW public.dashboard_costs")
    source = Path(__file__).with_name("0005_analysis.sql").read_text()
    start = source.index("CREATE VIEW public.dashboard_costs AS")
    op.execute(source[start : source.index("REVOKE ALL ON FUNCTION", start)])
    op.execute("DROP VIEW public.api_models")
    op.execute(
        "CREATE VIEW public.api_models AS SELECT id,provider,model_name,enabled,"
        "schema_version,max_output_tokens,pricing_version,currency,input_price_per_million::text,"
        "output_price_per_million::text FROM public.model_registry"
    )
    op.execute("GRANT SELECT ON public.api_models TO trd_api")
    for column in (
        "input_token_limit",
        "provider_slug",
        "provider_label",
        "accepted_environment_id",
        "accepted_until",
    ):
        op.execute(f"ALTER TABLE public.model_registry DROP COLUMN {column}")
    op.execute("ALTER TABLE public.sessions DROP COLUMN external_subject_hash")
    op.execute("ALTER TABLE public.ai_usage DROP COLUMN reported_cost_usd")
    provider_constraint("provider IN ('mock','openai','anthropic','google','moonshot','typesafe')")
