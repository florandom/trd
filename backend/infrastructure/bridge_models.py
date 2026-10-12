"""Durable paper protocol evidence, scoped to the enrolled account."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKeyConstraint,
    Integer,
    LargeBinary,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.infrastructure.models import Base

MONEY = Numeric(28, 10)


def fk(column, table):
    return ForeignKeyConstraint(
        ["environment_id", column], [f"{table}.environment_id", f"{table}.id"]
    )


class BridgeRecord(Base):
    __abstract__ = True
    environment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )


class BridgeEnrollment(Base):
    __tablename__ = "bridge_enrollments"
    __table_args__ = (
        fk("account_id", "trading_accounts"),
        UniqueConstraint("environment_id", "bridge_id", "instance_id"),
        CheckConstraint("generation >= 1 AND highwater >= 0"),
        CheckConstraint(
            "profile_hash ~ '^[a-f0-9]{64}$' AND request_key_hash ~ '^[a-f0-9]{64}$' "
            "AND response_key_hash ~ '^[a-f0-9]{64}$'"
        ),
    )
    environment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    bridge_id: Mapped[str] = mapped_column(String(64), nullable=False)
    instance_id: Mapped[str] = mapped_column(String(64), nullable=False)
    key_id: Mapped[str] = mapped_column(String(64), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    highwater: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    fault_latched: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    journal_id: Mapped[str | None] = mapped_column(String(64))


class BridgeSnapshot(BridgeRecord):
    __tablename__ = "bridge_snapshots"
    __table_args__ = (
        fk("account_id", "trading_accounts"),
        UniqueConstraint("environment_id", "account_id", "id"),
        CheckConstraint("payload_hash ~ '^[a-f0-9]{64}$'"),
    )
    account_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)


class BridgeBaseline(Base):
    __tablename__ = "bridge_daily_baselines"
    __table_args__ = (
        fk("account_id", "trading_accounts"),
        ForeignKeyConstraint(
            ["environment_id", "account_id", "snapshot_id"],
            [
                "bridge_snapshots.environment_id",
                "bridge_snapshots.account_id",
                "bridge_snapshots.id",
            ],
        ),
        CheckConstraint(
            "opening_equity > 0 AND opening_equity <> 'NaN'::numeric "
            "AND net_cash_flow <> 'NaN'::numeric"
        ),
    )
    environment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    snapshot_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    opening_equity: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    net_cash_flow: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    loss_latched: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")


class BridgeRequest(Base):
    __tablename__ = "bridge_requests"
    __table_args__ = (
        ForeignKeyConstraint(
            ["environment_id", "account_id"],
            ["bridge_enrollments.environment_id", "bridge_enrollments.account_id"],
        ),
        CheckConstraint(
            "sequence >= 1 AND request_hash ~ '^[a-f0-9]{64}$' AND status BETWEEN 200 AND 499"
        ),
    )
    environment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    sequence: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[int] = mapped_column(Integer, nullable=False)
    response: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    response_headers: Mapped[dict] = mapped_column(JSONB, nullable=False)


class PaperCommandRecord(BridgeRecord):
    __tablename__ = "paper_command_records"
    __table_args__ = (
        ForeignKeyConstraint(
            ["environment_id", "account_id", "command_id"],
            [
                "execution_commands.environment_id",
                "execution_commands.account_id",
                "execution_commands.id",
            ],
        ),
        fk("signal_id", "signals"),
        UniqueConstraint("environment_id", "command_id"),
        UniqueConstraint("environment_id", "signal_id"),
        UniqueConstraint("environment_id", "message_id"),
        fk("message_id", "telegram_messages"),
        CheckConstraint(
            "remaining_risk >= 0 AND remaining_notional >= 0 AND remaining_margin >= 0 "
            "AND remaining_risk <> 'NaN'::numeric AND remaining_notional <> 'NaN'::numeric "
            "AND remaining_margin <> 'NaN'::numeric"
        ),
    )
    account_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    command_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    signal_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    message_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    proposal: Mapped[dict] = mapped_column(JSONB, nullable=False)
    admission: Mapped[dict] = mapped_column(JSONB, nullable=False)
    remaining_risk: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    remaining_notional: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    remaining_margin: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    send_intent: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")


class BridgeDecision(BridgeRecord):
    __tablename__ = "bridge_decisions"
    __table_args__ = (
        fk("account_id", "trading_accounts"),
        fk("risk_event_id", "risk_events"),
        UniqueConstraint("environment_id", "account_id", "evaluation_hash"),
        CheckConstraint("evaluation_hash ~ '^[a-f0-9]{64}$'"),
    )
    account_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    evaluation_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    risk_event_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)


for _table in (
    BridgeEnrollment.__table__,
    BridgeSnapshot.__table__,
    BridgeBaseline.__table__,
    BridgeRequest.__table__,
    PaperCommandRecord.__table__,
    BridgeDecision.__table__,
):
    _table.append_constraint(
        CheckConstraint(
            "environment_id ~ '^[a-z][a-z0-9_-]{0,63}$'",
            name=f"ck_{_table.name}_environment",
        )
    )
