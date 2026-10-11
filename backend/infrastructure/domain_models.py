"""Domain records. Composite references prevent cross-environment/account associations.

NUMERIC(28,10) covers money, prices and volumes; no binary floating-point accounting.
Broker identifiers remain text. Evidence references use RESTRICT, never cascading deletes.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.infrastructure.models import Base

MONEY = Numeric(28, 10)


def fk(column: str, table: str, remote: str = "id") -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["environment_id", column], [f"{table}.environment_id", f"{table}.{remote}"]
    )


def version_fk(column: str, version: str, table: str, remote: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["environment_id", column, version],
        [f"{table}.environment_id", f"{table}.{remote}", f"{table}.version"],
    )


def choice(column: str, values: str) -> CheckConstraint:
    return CheckConstraint(f"{column} IN ({','.join(repr(v) for v in values.split())})")


class ScopedRecord(Base):
    __abstract__ = True
    environment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )


class SessionRecord(ScopedRecord):
    __tablename__ = "sessions"
    __table_args__ = (
        Index("ix_sessions_expiry", "expires_at"),
        UniqueConstraint("token_hash"),
        CheckConstraint("token_hash ~ '^[a-f0-9]{64}$'"),
        CheckConstraint("expires_at > created_at"),
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    external_subject_hash: Mapped[str | None] = mapped_column(String(64))


class TradingAccount(ScopedRecord):
    __tablename__ = "trading_accounts"
    __table_args__ = (
        UniqueConstraint("environment_id", "broker_server", "login", "mode"),
        choice("mode", "paper demo live"),
        choice("status", "PAUSED RECONCILING READY"),
        CheckConstraint("login ~ '^[0-9]{1,32}$'"),
        CheckConstraint("safety_epoch >= 1"),
    )
    broker_server: Mapped[str] = mapped_column(String(128), nullable=False)
    login: Mapped[str] = mapped_column(String(32), nullable=False)
    mode: Mapped[str] = mapped_column(String(8), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="PAUSED")
    safety_epoch: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")


class TelegramSource(ScopedRecord):
    __tablename__ = "telegram_sources"
    __table_args__ = (
        UniqueConstraint("environment_id", "collector_identity", "peer_id"),
        UniqueConstraint("environment_id", "collector_identity", "reference"),
        CheckConstraint("version >= 1"),
        choice("resolution_state", "PENDING RESOLVED UNAVAILABLE"),
    )
    collector_identity: Mapped[str] = mapped_column(String(64), nullable=False)
    peer_id: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    reference: Mapped[str | None] = mapped_column(String(160))
    access_hash: Mapped[str | None] = mapped_column(String(32))
    peer_kind: Mapped[str | None] = mapped_column(String(8))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    resolution_state: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="PENDING"
    )


class CollectorLease(Base):
    __tablename__ = "telegram_collector_leases"
    __table_args__ = (
        CheckConstraint("account_id ~ '^[1-9][0-9]{0,19}$'"),
        CheckConstraint("generation >= 1"),
    )
    account_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    environment_id: Mapped[str] = mapped_column(String(64), nullable=False)
    owner: Mapped[str] = mapped_column(String(128), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    lease_until: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    retry_after: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class CollectorSourceState(Base):
    __tablename__ = "telegram_source_state"
    __table_args__ = (
        fk("source_id", "telegram_sources"),
        CheckConstraint("last_message_id >= 0 AND delete_cursor >= 0"),
        choice("status", "PENDING ACTIVE BACKFILL GAP UNAVAILABLE FLOOD_WAIT DISABLED"),
    )
    environment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    last_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    delete_cursor: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="PENDING")
    checked_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    gap_since: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(32))


class TelegramMessage(ScopedRecord):
    __tablename__ = "telegram_messages"
    __table_args__ = (
        fk("source_id", "telegram_sources"),
        UniqueConstraint("environment_id", "source_id", "message_id"),
        CheckConstraint("message_id ~ '^[0-9]{1,32}$'"),
    )
    source_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    message_id: Mapped[str] = mapped_column(String(32), nullable=False)
    reply_message_id: Mapped[str | None] = mapped_column(String(32))


class TelegramMessageVersion(Base):
    __tablename__ = "telegram_message_versions"
    __table_args__ = (
        fk("message_id", "telegram_messages"),
        CheckConstraint("version >= 1"),
        CheckConstraint("body_hash ~ '^[a-f0-9]{64}$'"),
        Index("ix_telegram_raw_retention", "environment_id", "created_at"),
        UniqueConstraint("environment_id", "message_id", "revision_hash"),
        choice("event_kind", "NEW EDIT DELETE"),
    )
    environment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    message_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    body_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_body: Mapped[str | None] = mapped_column(Text)
    event_kind: Mapped[str] = mapped_column(String(8), nullable=False, server_default="NEW")
    revision_hash: Mapped[str | None] = mapped_column(String(64))
    published_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    media_kind: Mapped[str] = mapped_column(String(8), nullable=False, server_default="NONE")
    observed_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )


class Signal(ScopedRecord):
    __tablename__ = "signals"
    __table_args__ = (
        fk("message_id", "telegram_messages"),
        UniqueConstraint("environment_id", "id", "message_id"),
        UniqueConstraint("environment_id", "message_id", "intent_key"),
        choice(
            "state",
            "RECEIVED CLASSIFIED PARSED ANALYZING DECIDED WAITING ESCALATED "
            "RISK_CHECK APPROVED EXECUTION_REQUESTED RECONCILING EXECUTED IGNORED "
            "REJECTED_AI REJECTED_RISK EXPIRED FAILED",
        ),
        CheckConstraint("revision >= 1"),
        Index("ix_signals_state", "environment_id", "state"),
    )
    message_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    intent_key: Mapped[str] = mapped_column(String(96), nullable=False)
    trace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, server_default="RECEIVED")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)


class SignalVersion(Base):
    __tablename__ = "signal_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["environment_id", "signal_id", "message_id"],
            ["signals.environment_id", "signals.id", "signals.message_id"],
        ),
        version_fk("message_id", "message_version", "telegram_message_versions", "message_id"),
        CheckConstraint("version >= 1"),
        CheckConstraint("proposal_hash ~ '^[a-f0-9]{64}$'"),
    )
    environment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    signal_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    message_version: Mapped[int] = mapped_column(Integer, nullable=False)
    proposal: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    proposal_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )


class ModelRegistry(Base):
    __tablename__ = "model_registry"
    __table_args__ = (
        UniqueConstraint("provider", "model_name", "pricing_version"),
        CheckConstraint("input_price_per_million >= 0 AND output_price_per_million >= 0"),
        CheckConstraint("schema_version >= 1 AND max_output_tokens > 0"),
        choice("provider", "mock openrouter openai anthropic google moonshot typesafe"),
        CheckConstraint("currency = 'USD'"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    max_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    input_price_per_million: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    output_price_per_million: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    pricing_version: Mapped[str] = mapped_column(String(64), nullable=False)
    input_token_limit: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    provider_slug: Mapped[str | None] = mapped_column(String(64))
    provider_label: Mapped[str | None] = mapped_column(String(96))
    accepted_environment_id: Mapped[str | None] = mapped_column(String(64))
    accepted_until: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="USD")


class Agent(ScopedRecord):
    __tablename__ = "agents"
    __table_args__ = (
        UniqueConstraint("environment_id", "name"),
        ForeignKeyConstraint(
            ["environment_id", "id", "current_version"],
            ["agent_configs.environment_id", "agent_configs.agent_id", "agent_configs.version"],
            name="fk_agents_current_config",
            use_alter=True,
        ),
        choice(
            "name",
            "SIGNAL_CLASSIFIER SIGNAL_PARSER MARKET_ANALYST DECISION_AGENT "
            "CRITIC POSITION_REVIEW_AGENT",
        ),
    )
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    current_version: Mapped[int | None] = mapped_column(Integer)


class PromptVersion(Base):
    __tablename__ = "prompt_versions"
    __table_args__ = (
        fk("agent_id", "agents"),
        CheckConstraint("version >= 1"),
        CheckConstraint("checksum ~ '^[a-f0-9]{64}$'"),
    )
    environment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )


class AgentConfig(Base):
    __tablename__ = "agent_configs"
    __table_args__ = (
        fk("agent_id", "agents"),
        version_fk("agent_id", "prompt_version", "prompt_versions", "agent_id"),
        CheckConstraint("version >= 1 AND timeout_seconds BETWEEN 1 AND 120"),
        CheckConstraint("max_output_tokens > 0 AND max_cost_usd >= 0"),
        CheckConstraint("required_schema_version >= 1"),
    )
    environment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    primary_model_id: Mapped[str] = mapped_column(ForeignKey("model_registry.id"), nullable=False)
    prompt_version: Mapped[int] = mapped_column(Integer, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    max_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    max_cost_usd: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    required_schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )


class AgentFallback(Base):
    __tablename__ = "agent_fallbacks"
    __table_args__ = (
        version_fk("agent_id", "config_version", "agent_configs", "agent_id"),
        UniqueConstraint("environment_id", "agent_id", "config_version", "model_id"),
        CheckConstraint("ordinal BETWEEN 1 AND 2"),
    )
    environment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    config_version: Mapped[int] = mapped_column(Integer, primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_id: Mapped[str] = mapped_column(ForeignKey("model_registry.id"), nullable=False)


class AgentRun(ScopedRecord):
    __tablename__ = "agent_runs"
    __table_args__ = (
        version_fk("agent_id", "config_version", "agent_configs", "agent_id"),
        fk("signal_id", "signals"),
        choice("status", "STARTED SUCCEEDED REFUSED FAILED UNKNOWN"),
        CheckConstraint("attempt BETWEEN 1 AND 3"),
        Index("ix_ai_raw_retention", "environment_id", "created_at"),
    )
    agent_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    config_version: Mapped[int] = mapped_column(Integer, nullable=False)
    signal_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    trace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    model_id: Mapped[str] = mapped_column(ForeignKey("model_registry.id"), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    raw_response: Mapped[str | None] = mapped_column(Text)


class AIUsage(ScopedRecord):
    __tablename__ = "ai_usage"
    __table_args__ = (
        fk("run_id", "agent_runs"),
        UniqueConstraint("environment_id", "run_id"),
        CheckConstraint("input_tokens >= 0 AND output_tokens >= 0 AND estimated_cost_usd >= 0"),
    )
    run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_cost_usd: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    pricing_version: Mapped[str] = mapped_column(String(64), nullable=False)
    reported_cost_usd: Mapped[Decimal | None] = mapped_column(MONEY)
    usage_known: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")


class AnalysisRecord(ScopedRecord):
    __tablename__ = "analysis_records"
    __table_args__ = (
        fk("job_id", "jobs"),
        fk("signal_id", "signals"),
        version_fk("message_id", "message_version", "telegram_message_versions", "message_id"),
        UniqueConstraint("environment_id", "job_id"),
        UniqueConstraint("environment_id", "message_id", "message_version"),
        choice("classification", "NOISE STRUCTURED AMBIGUOUS REVIEW"),
        choice("outcome", "IGNORED ESCALATED EXPIRED WAITING REJECTED_AI"),
        CheckConstraint("input_hash ~ '^[a-f0-9]{64}$'"),
        CheckConstraint("source_version >= 1"),
    )
    job_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    message_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    message_version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_version: Mapped[int] = mapped_column(Integer, nullable=False)
    signal_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    trace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    classification: Mapped[str] = mapped_column(String(16), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    route_version: Mapped[str] = mapped_column(String(64), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    config_versions: Mapped[dict[str, int]] = mapped_column(JSONB, nullable=False)


class AIBudgetReservation(ScopedRecord):
    __tablename__ = "ai_budget_reservations"
    __table_args__ = (
        fk("job_id", "jobs"),
        version_fk("agent_id", "config_version", "agent_configs", "agent_id"),
        UniqueConstraint("environment_id", "job_id", "generation", "agent_id", "attempt"),
        choice("state", "RESERVED SETTLED UNKNOWN"),
        CheckConstraint("attempt BETWEEN 1 AND 3 AND generation >= 1"),
        CheckConstraint("reserved_usd >= 0 AND charged_usd >= 0"),
        CheckConstraint("input_token_ceiling >= 0 AND output_token_ceiling > 0"),
        CheckConstraint("(state = 'SETTLED') = (charged_usd IS NOT NULL)"),
        Index("ix_ai_budget_period", "environment_id", "created_at"),
    )
    job_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    agent_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    config_version: Mapped[int] = mapped_column(Integer, nullable=False)
    model_id: Mapped[str] = mapped_column(ForeignKey("model_registry.id"), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    reserved_usd: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    charged_usd: Mapped[Decimal | None] = mapped_column(MONEY)
    input_token_ceiling: Mapped[int] = mapped_column(Integer, nullable=False)
    output_token_ceiling: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default="RESERVED")
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    settled_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class RiskRule(Base):
    __tablename__ = "risk_rules"
    __table_args__ = (
        CheckConstraint("version >= 1"),
        CheckConstraint("fingerprint ~ '^[a-f0-9]{64}$'"),
    )
    environment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    policy: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )


class RiskEvent(ScopedRecord):
    __tablename__ = "risk_events"
    __table_args__ = (
        version_fk("signal_id", "signal_version", "signal_versions", "signal_id"),
        choice("result", "APPROVED REJECTED ERROR"),
        ForeignKeyConstraint(
            ["environment_id", "rule_key", "rule_version"],
            ["risk_rules.environment_id", "risk_rules.key", "risk_rules.version"],
        ),
    )
    signal_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    signal_version: Mapped[int] = mapped_column(Integer, nullable=False)
    rule_key: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_version: Mapped[int] = mapped_column(Integer, nullable=False)
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    calculation: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class RiskRuleHead(Base):
    __tablename__ = "risk_rule_heads"
    __table_args__ = (
        ForeignKeyConstraint(
            ["environment_id", "key", "current_version"],
            ["risk_rules.environment_id", "risk_rules.key", "risk_rules.version"],
        ),
    )
    environment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False)


class RiskApproval(ScopedRecord):
    __tablename__ = "risk_approvals"
    __table_args__ = (
        fk("account_id", "trading_accounts"),
        fk("risk_event_id", "risk_events"),
        UniqueConstraint("environment_id", "account_id", "id"),
        CheckConstraint("risk_amount > 0 AND safety_epoch >= 1"),
        CheckConstraint("expires_at > created_at"),
    )
    account_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    risk_event_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    risk_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    safety_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)


class RiskReservation(ScopedRecord):
    __tablename__ = "risk_reservations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["environment_id", "account_id", "approval_id"],
            ["risk_approvals.environment_id", "risk_approvals.account_id", "risk_approvals.id"],
        ),
        UniqueConstraint("environment_id", "approval_id"),
        UniqueConstraint("environment_id", "account_id", "id"),
        choice("status", "HELD CONSUMED RELEASED OUTCOME_UNKNOWN"),
        CheckConstraint("risk_amount > 0 AND slots > 0"),
    )
    account_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    approval_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    risk_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    slots: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="HELD")


class ExecutionCommand(ScopedRecord):
    __tablename__ = "execution_commands"
    __table_args__ = (
        ForeignKeyConstraint(
            ["environment_id", "account_id", "reservation_id"],
            [
                "risk_reservations.environment_id",
                "risk_reservations.account_id",
                "risk_reservations.id",
            ],
        ),
        UniqueConstraint("environment_id", "reservation_id"),
        UniqueConstraint("environment_id", "account_id", "id"),
        CheckConstraint("payload_hash ~ '^[a-f0-9]{64}$'"),
        CheckConstraint("revision >= 1"),
        CheckConstraint("expires_at > created_at"),
        choice(
            "state",
            "CREATED READY DELIVERED ACKNOWLEDGED OUTCOME_UNKNOWN RECONCILING "
            "COMPLETED REJECTED EXPIRED INVALIDATED",
        ),
    )
    account_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    reservation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    trace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    payload: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, server_default="CREATED")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)


class ExecutionEvent(ScopedRecord):
    __tablename__ = "execution_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["environment_id", "account_id", "command_id"],
            [
                "execution_commands.environment_id",
                "execution_commands.account_id",
                "execution_commands.id",
            ],
        ),
        UniqueConstraint("environment_id", "account_id", "event_key"),
        CheckConstraint("payload_hash ~ '^[a-f0-9]{64}$'"),
    )
    account_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    command_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    event_key: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)


class Order(ScopedRecord):
    __tablename__ = "orders"
    __table_args__ = (
        ForeignKeyConstraint(
            ["environment_id", "account_id", "command_id"],
            [
                "execution_commands.environment_id",
                "execution_commands.account_id",
                "execution_commands.id",
            ],
        ),
        UniqueConstraint("environment_id", "command_id"),
        UniqueConstraint("environment_id", "account_id", "broker_ticket"),
        UniqueConstraint("environment_id", "account_id", "id"),
        choice("side", "BUY SELL"),
        CheckConstraint("revision >= 1"),
        CheckConstraint("volume > 0 AND filled_volume >= 0 AND filled_volume <= volume"),
        choice(
            "state",
            "PROPOSED VALIDATED REQUESTED SENT ACCEPTED PARTIALLY_FILLED FILLED "
            "OUTCOME_UNKNOWN RECONCILING REJECTED FAILED EXPIRED CANCELED",
        ),
    )
    account_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    command_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    broker_ticket: Mapped[str | None] = mapped_column(String(32))
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    volume: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    filled_volume: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    state: Mapped[str] = mapped_column(String(32), nullable=False, server_default="PROPOSED")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")


class Position(ScopedRecord):
    __tablename__ = "positions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["environment_id", "account_id", "order_id"],
            ["orders.environment_id", "orders.account_id", "orders.id"],
        ),
        UniqueConstraint("environment_id", "account_id", "broker_identifier", "opened_at"),
        UniqueConstraint("environment_id", "account_id", "id"),
        CheckConstraint("volume >= 0 AND entry_price > 0"),
        choice("status", "OPEN CLOSING CLOSED OUTCOME_UNKNOWN"),
        CheckConstraint("(status = 'CLOSED') = (closed_at IS NOT NULL)"),
    )
    account_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    order_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    broker_identifier: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    volume: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    entry_price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class PositionEvent(ScopedRecord):
    __tablename__ = "position_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["environment_id", "account_id", "position_id"],
            ["positions.environment_id", "positions.account_id", "positions.id"],
        ),
        UniqueConstraint("environment_id", "account_id", "broker_deal_id"),
    )
    account_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    position_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    broker_deal_id: Mapped[str] = mapped_column(String(32), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    realized_pnl: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)


class LifecycleEvent(ScopedRecord):
    __tablename__ = "lifecycle_events"
    __table_args__ = (
        fk("signal_id", "signals"),
        fk("order_id", "orders"),
        fk("command_id", "execution_commands"),
        UniqueConstraint("environment_id", "kind", "entity_id", "revision"),
        choice("kind", "signal order command"),
        CheckConstraint("revision >= 2"),
        CheckConstraint(
            "(kind = 'signal' AND signal_id IS NOT NULL AND signal_id = entity_id "
            "AND order_id IS NULL AND command_id IS NULL) OR (kind = 'order' "
            "AND order_id IS NOT NULL AND order_id = entity_id "
            "AND signal_id IS NULL AND command_id IS NULL) OR (kind = 'command' "
            "AND command_id IS NOT NULL AND command_id = entity_id "
            "AND signal_id IS NULL AND order_id IS NULL)"
        ),
    )
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    signal_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    order_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    command_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    before: Mapped[str] = mapped_column(String(32), nullable=False)
    after: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_service: Mapped[str] = mapped_column(String(16), nullable=False)


class SystemHealth(ScopedRecord):
    __tablename__ = "system_health"
    __table_args__ = (choice("status", "HEALTHY DEGRADED UNAVAILABLE UNKNOWN"),)
    component: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)


class Job(ScopedRecord):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("environment_id", "service", "dedupe_key"),
        choice("service", "collector ai risk maintenance"),
        choice("state", "PENDING RUNNING COMPLETED DEAD"),
        CheckConstraint("attempts >= 0 AND max_attempts BETWEEN 1 AND 10 AND generation >= 0"),
        CheckConstraint(
            "(state = 'RUNNING') = (lease_owner IS NOT NULL AND lease_until IS NOT NULL)"
        ),
        Index("ix_jobs_claim", "environment_id", "service", "state", "available_at"),
    )
    service: Mapped[str] = mapped_column(String(16), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="3")
    generation: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    available_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    lease_until: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class OutboxEvent(ScopedRecord):
    __tablename__ = "outbox_events"
    __table_args__ = (UniqueConstraint("environment_id", "event_key"),)
    event_key: Mapped[str] = mapped_column(String(128), nullable=False)
    topic: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    delivered_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class CompactTradeMemory(ScopedRecord):
    __tablename__ = "compact_trade_memory"
    __table_args__ = (fk("signal_id", "signals"), fk("position_id", "positions"))
    signal_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    position_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    context_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    realized_pnl: Mapped[Decimal | None] = mapped_column(MONEY)
    r_multiple: Mapped[Decimal | None] = mapped_column(MONEY)


# Apply the same boundary to every new scoped table. Revision 0002 contains a
# frozen SQL snapshot; it never imports mutable metadata to create its schema.
for _table in Base.metadata.tables.values():
    if _table.name in {
        "users",
        "setting_versions",
        "system_settings",
        "audit_events",
        "heartbeats",
    }:
        continue
    if "environment_id" in _table.c:
        _table.append_constraint(
            CheckConstraint(
                "environment_id ~ '^[a-z][a-z0-9_-]{0,63}$'",
                name=f"ck_{_table.name}_environment",
            )
        )
    for _column in _table.c:
        if isinstance(_column.type, Numeric):
            _table.append_constraint(
                CheckConstraint(
                    f"{_column.name} <> 'NaN'::numeric",
                    name=f"ck_{_table.name}_{_column.name}_finite",
                )
            )
