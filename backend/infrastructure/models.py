"""Migration-owned persistence. Importing this module registers the entire schema."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('ADMIN', 'VIEWER')", name="ck_users_role"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )


class SettingVersion(Base):
    __tablename__ = "setting_versions"
    __table_args__ = (CheckConstraint("version >= 1", name="ck_setting_versions_positive"),)

    environment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    key: Mapped[str] = mapped_column(String(96), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )


class SystemSetting(Base):
    __tablename__ = "system_settings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["environment_id", "key", "current_version"],
            ["setting_versions.environment_id", "setting_versions.key", "setting_versions.version"],
            name="fk_system_settings_current_version",
        ),
    )

    environment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    key: Mapped[str] = mapped_column(String(96), primary_key=True)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    environment_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(96), nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    actor_service: Mapped[str] = mapped_column(String(32), nullable=False)
    target: Mapped[str] = mapped_column(String(160), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )


class Heartbeat(Base):
    __tablename__ = "heartbeats"
    __table_args__ = (
        CheckConstraint(
            "service_name IN ('api', 'collector', 'ai', 'risk', 'maintenance')",
            name="ck_heartbeats_service",
        ),
        CheckConstraint(
            "status IN ('STARTING', 'HEALTHY', 'DEGRADED', 'STOPPED')", name="ck_heartbeats_status"
        ),
    )

    environment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    service_name: Mapped[str] = mapped_column(String(32), primary_key=True)
    instance_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )


from backend.infrastructure import domain_models as domain_models  # noqa: E402
