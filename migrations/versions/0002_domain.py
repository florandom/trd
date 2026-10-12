"""Domain/database foundation; no execution, provider or authentication endpoints.

Revision ID: 0002_domain
Revises: 0001_foundation
"""

from pathlib import Path

from alembic import op

revision = "0002_domain"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None

# Frozen dependency order, independent of future ORM changes.
DROP_ORDER = (
    "position_events",
    "compact_trade_memory",
    "positions",
    "lifecycle_events",
    "orders",
    "execution_events",
    "execution_commands",
    "risk_reservations",
    "risk_approvals",
    "risk_events",
    "risk_rule_heads",
    "ai_usage",
    "signal_versions",
    "agent_runs",
    "agent_fallbacks",
    "telegram_message_versions",
    "signals",
    "agent_configs",
    "telegram_messages",
    "sessions",
    "risk_rules",
    "prompt_versions",
    "trading_accounts",
    "telegram_sources",
    "system_health",
    "outbox_events",
    "model_registry",
    "jobs",
    "agents",
)
IMMUTABLE = (
    "setting_versions",
    "audit_events",
    "prompt_versions",
    "agent_configs",
    "agent_fallbacks",
    "signal_versions",
    "risk_rules",
    "risk_events",
    "risk_approvals",
    "execution_events",
    "position_events",
    "lifecycle_events",
    "ai_usage",
    "compact_trade_memory",
)
FENCED = (
    "signals",
    "signal_versions",
    "agent_runs",
    "risk_events",
    "risk_approvals",
    "risk_reservations",
    "execution_commands",
    "orders",
    "positions",
)
FUNCTIONS = (
    "protect_domain_identity()",
    "prune_configured_evidence(text,integer)",
    "append_signal_version(text,uuid,integer,integer,jsonb,text)",
    "transition_domain_entity(text,text,uuid,integer,text,text,uuid)",
    "finish_domain_job(text,uuid,text,integer,boolean)",
    "claim_domain_job(text,text,integer)",
    "enqueue_domain_job(text,text,jsonb)",
    "prune_raw_evidence(text,integer,integer,integer)",
    "signal_evidence_protected(text,uuid)",
    "revise_system_setting(text,text,integer,jsonb,uuid)",
    "require_initial_lifecycle()",
    "protect_domain_record()",
    "domain_evidence_fence()",
)


def upgrade() -> None:
    for name in ("schema", "contracts"):
        sql = Path(__file__).with_name(f"0002_domain_{name}.sql").read_text(encoding="utf-8")
        op.execute(sql)
    for table in IMMUTABLE:
        op.execute(
            f"CREATE TRIGGER protect_{table} BEFORE UPDATE OR DELETE ON public.{table} "
            "FOR EACH ROW EXECUTE FUNCTION public.protect_domain_record('')"
        )
    for table, raw in (("telegram_message_versions", "raw_body"), ("agent_runs", "raw_response")):
        op.execute(
            f"CREATE TRIGGER protect_{table} BEFORE UPDATE OR DELETE ON public.{table} "
            f"FOR EACH ROW EXECUTE FUNCTION public.protect_domain_record('{raw}')"
        )
    for table in FENCED:
        op.execute(
            f"CREATE TRIGGER fence_{table} BEFORE INSERT OR UPDATE ON public.{table} "
            "FOR EACH ROW EXECUTE FUNCTION public.domain_evidence_fence()"
        )
    mutable_fields = {
        "signals": "state,revision",
        "execution_commands": "state,revision",
        "orders": "state,revision,filled_volume,broker_ticket",
        "positions": "status,volume,closed_at",
        "trading_accounts": "status,safety_epoch",
        "risk_reservations": "status",
        "model_registry": "enabled",
        "agents": "current_version",
        "risk_rule_heads": "current_version",
        "jobs": "state,attempts,generation,available_at,lease_owner,lease_until",
        "outbox_events": "delivered_at",
    }
    for table, fields in mutable_fields.items():
        op.execute(
            f"CREATE TRIGGER identity_{table} BEFORE UPDATE ON public.{table} "
            f"FOR EACH ROW EXECUTE FUNCTION public.protect_domain_identity('{fields}')"
        )
    for table, state in (
        ("signals", "RECEIVED"),
        ("orders", "PROPOSED"),
        ("execution_commands", "CREATED"),
    ):
        op.execute(
            f"CREATE TRIGGER initial_{table} BEFORE INSERT ON public.{table} "
            f"FOR EACH ROW EXECUTE FUNCTION public.require_initial_lifecycle('{state}')"
        )
    op.execute(
        "CREATE VIEW public.api_signals AS SELECT environment_id,id,trace_id,state,"
        "revision,expires_at,created_at FROM public.signals"
    )
    op.execute(
        "CREATE VIEW public.api_orders AS SELECT environment_id,id,account_id,command_id,"
        "broker_ticket,symbol,side,volume::text,filled_volume::text,state,revision,created_at "
        "FROM public.orders"
    )
    op.execute(
        "CREATE VIEW public.api_positions AS SELECT environment_id,id,account_id,order_id,"
        "broker_identifier,symbol,volume::text,entry_price::text,status,opened_at,closed_at "
        "FROM public.positions"
    )
    op.execute(
        "CREATE VIEW public.api_agents AS SELECT a.environment_id,a.id,a.name,"
        "a.current_version,c.enabled,c.primary_model_id,c.prompt_version FROM public.agents a "
        "LEFT JOIN public.agent_configs c ON (c.environment_id,c.agent_id,c.version) = "
        "(a.environment_id,a.id,a.current_version)"
    )
    op.execute(
        "CREATE VIEW public.api_models AS SELECT id,provider,model_name,enabled,"
        "schema_version,max_output_tokens,pricing_version,currency,"
        "input_price_per_million::text,output_price_per_million::text FROM public.model_registry"
    )
    op.execute(
        "GRANT SELECT ON public.api_signals,public.api_orders,public.api_positions,"
        "public.api_agents,public.api_models TO trd_api"
    )
    op.execute(
        "GRANT SELECT ON public.telegram_sources,public.telegram_messages,"
        "public.telegram_message_versions TO trd_collector"
    )
    op.execute(
        "GRANT INSERT ON public.telegram_messages,public.telegram_message_versions TO trd_collector"
    )
    op.execute(
        "GRANT SELECT ON public.telegram_sources,public.telegram_messages,"
        "public.telegram_message_versions,public.signals,public.signal_versions,public.agents,"
        "public.agent_configs,public.agent_fallbacks,public.prompt_versions,"
        "public.model_registry,public.agent_runs,public.ai_usage TO trd_ai"
    )
    op.execute("GRANT INSERT ON public.signals,public.agent_runs,public.ai_usage TO trd_ai")
    risk_read = (
        "trading_accounts",
        "signals",
        "signal_versions",
        "risk_rules",
        "risk_rule_heads",
        "risk_events",
        "risk_approvals",
        "risk_reservations",
        "execution_commands",
        "execution_events",
        "orders",
        "positions",
        "position_events",
        "compact_trade_memory",
    )
    op.execute("GRANT SELECT ON " + ",".join(f"public.{t}" for t in risk_read) + " TO trd_risk")
    risk_write = (
        "risk_events",
        "risk_approvals",
        "risk_reservations",
        "execution_commands",
        "execution_events",
        "orders",
        "positions",
        "position_events",
        "compact_trade_memory",
    )
    op.execute("GRANT INSERT ON " + ",".join(f"public.{t}" for t in risk_write) + " TO trd_risk")
    op.execute("GRANT UPDATE(status,safety_epoch) ON public.trading_accounts TO trd_risk")
    op.execute("GRANT UPDATE(status) ON public.risk_reservations TO trd_risk")
    op.execute("GRANT UPDATE(filled_volume,broker_ticket) ON public.orders TO trd_risk")
    op.execute("GRANT UPDATE(volume,status,closed_at) ON public.positions TO trd_risk")
    for function in FUNCTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION public.{function} FROM PUBLIC")
    op.execute(
        "GRANT EXECUTE ON FUNCTION public.revise_system_setting(text,text,integer,jsonb,uuid) "
        "TO trd_api"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION public.transition_domain_entity"
        "(text,text,uuid,integer,text,text,uuid) TO trd_ai,trd_risk"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION public.append_signal_version"
        "(text,uuid,integer,integer,jsonb,text) TO trd_ai"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION public.prune_configured_evidence(text,integer) "
        "TO trd_maintenance"
    )
    for function in (
        "finish_domain_job(text,uuid,text,integer,boolean)",
        "claim_domain_job(text,text,integer)",
        "enqueue_domain_job(text,text,jsonb)",
    ):
        op.execute(
            f"GRANT EXECUTE ON FUNCTION public.{function} "
            "TO trd_collector,trd_ai,trd_risk,trd_maintenance"
        )


def downgrade() -> None:
    for view in ("api_models", "api_agents", "api_positions", "api_orders", "api_signals"):
        op.execute(f"DROP VIEW public.{view}")
    # Remove the sole cyclic reference before dropping tables in dependency order.
    op.execute("ALTER TABLE public.agents DROP CONSTRAINT fk_agents_current_config")
    for table in ("setting_versions", "audit_events"):
        op.execute(f"DROP TRIGGER protect_{table} ON public.{table}")
    for table in DROP_ORDER:
        op.drop_table(table)
    for function in FUNCTIONS:
        op.execute(f"DROP FUNCTION public.{function}")
