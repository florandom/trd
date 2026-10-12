"""Confirmed local operator requests and durable paper position projections."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.infrastructure.bridge_models import MONEY, BridgeRecord, fk


class PaperPositionState(BridgeRecord):
    __tablename__ = "paper_position_state"
    __table_args__ = (
        ForeignKeyConstraint(
            ["environment_id", "account_id", "position_id"],
            ["positions.environment_id", "positions.account_id", "positions.id"],
        ),
        Index("uq_paper_position_state", "environment_id", "position_id", unique=True),
        CheckConstraint(
            "revision >= 1 AND stop_loss > 0 AND take_profit > 0 "
            "AND stop_loss <> 'NaN'::numeric AND take_profit <> 'NaN'::numeric"
        ),
    )
    position_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    account_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    stop_loss: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    take_profit: Mapped[Decimal] = mapped_column(MONEY, nullable=False)


class PaperOperation(BridgeRecord):
    __tablename__ = "paper_operations"
    __table_args__ = (
        fk("account_id", "trading_accounts"),
        ForeignKeyConstraint(
            ["environment_id", "account_id", "position_id"],
            ["positions.environment_id", "positions.account_id", "positions.id"],
        ),
        ForeignKeyConstraint(
            ["environment_id", "account_id", "command_id"],
            [
                "execution_commands.environment_id",
                "execution_commands.account_id",
                "execution_commands.id",
            ],
        ),
        Index("uq_paper_operation_command", "environment_id", "command_id", unique=True),
        Index(
            "uq_paper_pending_position",
            "environment_id",
            "position_id",
            unique=True,
            postgresql_where=text("state IN ('PENDING','DISPATCHED','UNKNOWN')"),
        ),
        Index(
            "uq_paper_pending_resume",
            "environment_id",
            "account_id",
            unique=True,
            postgresql_where=text("action='RESUME' AND state='PENDING'"),
        ),
        CheckConstraint(
            "action IN ('CLOSE','MODIFY_STOPS','RESUME') "
            "AND state IN ('PENDING','DISPATCHED','UNKNOWN','COMPLETED','REJECTED')"
        ),
        CheckConstraint("expected_revision >= 1 AND safety_epoch >= 1"),
        CheckConstraint("(action='RESUME') = (position_id IS NULL)"),
    )
    account_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    position_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    command_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    actor_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    expected_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    safety_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default="PENDING")
    reason: Mapped[str | None] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)


class PaperOperationResult(BridgeRecord):
    __tablename__ = "paper_operation_results"
    __table_args__ = (
        fk("account_id", "trading_accounts"),
        fk("request_id", "paper_operations"),
        Index("uq_paper_operation_result", "environment_id", "request_id", unique=True),
        Index(
            "uq_paper_operation_identity",
            "environment_id",
            "account_id",
            "operation_id",
            unique=True,
        ),
    )
    account_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    request_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    operation_id: Mapped[str] = mapped_column(String(32), nullable=False)
    outcome: Mapped[dict] = mapped_column(JSONB, nullable=False)


for model in (PaperPositionState, PaperOperation, PaperOperationResult):
    model.__table__.append_constraint(
        CheckConstraint(
            "environment_id ~ '^[a-z][a-z0-9_-]{0,63}$'",
            name=f"ck_{model.__tablename__}_environment",
        )
    )
