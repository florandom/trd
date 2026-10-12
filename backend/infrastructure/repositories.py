"""Scoped repositories share their caller's transaction; they never commit internally.

Security-sensitive runtime writes call role-authenticated PostgreSQL functions.
Dashboard configuration uses confirmed session-bound functions. Prompt and registry
manifest administration remains operator-owned.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, bindparam, insert, select, text, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError

from backend.domain.contracts import (
    AgentConfiguration,
    LifecycleChange,
    ModelDefinition,
    Proposal,
    RiskPolicy,
    fingerprint,
)
from backend.domain.lifecycle import STATES, Evidence
from backend.infrastructure.database import ENVIRONMENT_PATTERN
from backend.infrastructure.domain_models import (
    Agent,
    AgentConfig,
    AgentFallback,
    ModelRegistry,
    PromptVersion,
    RiskRule,
    RiskRuleHead,
    Signal,
    SignalVersion,
    TelegramMessage,
    TelegramMessageVersion,
)
from backend.infrastructure.models import AuditEvent, User


class VersionConflict(RuntimeError):
    pass


class IdentityConflict(ValueError):
    pass


class RepositoryError(RuntimeError):
    pass


class ScopedRepository:
    def __init__(self, connection: Connection, environment_id: str) -> None:
        if not ENVIRONMENT_PATTERN.fullmatch(environment_id):
            raise ValueError("invalid environment identity")
        if not connection.in_transaction():
            raise ValueError("repositories require an explicit transaction")
        self.connection = connection
        self.environment_id = environment_id

    def call(self, sql: str, parameters: dict[str, Any], *json_fields: str):
        statement = text(sql)
        if json_fields:
            statement = statement.bindparams(*(bindparam(f, type_=JSONB) for f in json_fields))
        try:
            return self.connection.execute(
                statement, {"environment": self.environment_id, **parameters}
            )
        except DBAPIError as error:
            code = getattr(error.orig, "sqlstate", None)
            if code == "40001":
                raise VersionConflict("version or lease ownership changed") from None
            if code == "42501":
                raise PermissionError("database authority rejected this operation") from None
            if code == "22023":
                raise IdentityConflict("invalid request, evidence or identity conflict") from None
            raise RepositoryError("database operation failed; transaction must roll back") from None

    def require_admin(self, actor_id: UUID) -> None:
        if not self.connection.scalar(
            select(User.id).where(
                User.id == actor_id,
                User.active.is_(True),
                User.role == "ADMIN",
            )
        ):
            raise PermissionError("active administrator required")


class SettingsRepository(ScopedRepository):
    def revise(self, key: str, value: object, *, expected_version: int, actor_id: UUID) -> int:
        if isinstance(expected_version, bool) or expected_version < 1:
            raise ValueError("invalid expected version")
        return self.call(
            "SELECT public.revise_system_setting(:environment,:key,:expected,:value,:actor)",
            {"key": key, "expected": expected_version, "value": value, "actor": actor_id},
            "value",
        ).scalar_one()


class LifecycleRepository(ScopedRepository):
    def transition(self, kind: str, entity_id: UUID, change: LifecycleChange) -> int:
        if kind not in STATES:
            raise ValueError("unsupported lifecycle")
        STATES[kind](change.after)
        Evidence(change.evidence)
        return self.call(
            "SELECT public.transition_domain_entity(:environment,:kind,:entity,:expected,"
            ":after,:evidence,:event)",
            {
                "kind": kind,
                "entity": entity_id,
                "expected": change.expected_revision,
                "after": change.after,
                "evidence": change.evidence,
                "event": change.event_id,
            },
        ).scalar_one()


@dataclass(frozen=True)
class MessageReceipt:
    message_id: UUID
    version: int
    body_hash: str
    created: bool


class MessageRepository(ScopedRepository):
    def record(
        self, *, source_id: UUID, message_id: str, body: str, observed_at: datetime
    ) -> MessageReceipt:
        if not re.fullmatch(r"[0-9]{1,32}", message_id):
            raise ValueError("invalid Telegram message identity")
        if "\x00" in body or len(body.encode("utf-8")) > 65_536:
            raise ValueError("message exceeds the raw storage boundary")
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("message timestamp requires a timezone")
        observed_at = observed_at.astimezone(UTC)
        digest = sha256(body.encode("utf-8")).hexdigest()
        self.connection.execute(
            text(
                "SELECT pg_advisory_xact_lock(hashtextextended('trd-evidence:' || :environment,0))"
            ),
            {"environment": self.environment_id},
        )
        self.connection.execute(
            pg_insert(TelegramMessage)
            .values(
                environment_id=self.environment_id,
                id=uuid4(),
                source_id=source_id,
                message_id=message_id,
            )
            .on_conflict_do_nothing(index_elements=["environment_id", "source_id", "message_id"])
        )
        anchor = self.connection.scalar(
            select(TelegramMessage.id).where(
                TelegramMessage.environment_id == self.environment_id,
                TelegramMessage.source_id == source_id,
                TelegramMessage.message_id == message_id,
            )
        )
        latest = (
            self.connection.execute(
                select(TelegramMessageVersion)
                .where(
                    TelegramMessageVersion.environment_id == self.environment_id,
                    TelegramMessageVersion.message_id == anchor,
                )
                .order_by(TelegramMessageVersion.version.desc())
                .limit(1)
            )
            .mappings()
            .first()
        )
        if latest is not None:
            if latest["body_hash"] == digest or observed_at < latest["observed_at"]:
                return MessageReceipt(anchor, latest["version"], latest["body_hash"], False)
            if observed_at == latest["observed_at"]:
                raise IdentityConflict("same message timestamp has conflicting content")
        version = 1 if latest is None else latest["version"] + 1
        self.connection.execute(
            insert(TelegramMessageVersion).values(
                environment_id=self.environment_id,
                message_id=anchor,
                version=version,
                raw_body=body,
                body_hash=digest,
                observed_at=observed_at,
            )
        )
        return MessageReceipt(anchor, version, digest, True)


class SignalRepository(ScopedRepository):
    def create(
        self, message: MessageReceipt, proposal: Proposal, *, intent_key: str, trace_id: UUID
    ) -> UUID:
        if not 1 <= len(intent_key) <= 96:
            raise ValueError("invalid signal intent")
        digest = fingerprint(proposal)
        self.connection.execute(
            text(
                "SELECT pg_advisory_xact_lock(hashtextextended('trd-evidence:' || :environment,0))"
            ),
            {"environment": self.environment_id},
        )
        existing = self.connection.execute(
            select(Signal.id, SignalVersion.proposal_hash)
            .join(
                SignalVersion,
                (SignalVersion.environment_id == Signal.environment_id)
                & (SignalVersion.signal_id == Signal.id)
                & (SignalVersion.version == 1),
            )
            .where(
                Signal.environment_id == self.environment_id,
                Signal.message_id == message.message_id,
                Signal.intent_key == intent_key,
            )
        ).first()
        if existing:
            if existing.proposal_hash != digest:
                raise IdentityConflict("signal intent already has a different proposal")
            return existing.id
        identifier = uuid4()
        self.connection.execute(
            insert(Signal).values(
                environment_id=self.environment_id,
                id=identifier,
                message_id=message.message_id,
                intent_key=intent_key,
                trace_id=trace_id,
                expires_at=proposal.expires_at,
            )
        )
        self.append_version(identifier, message.version, proposal, expected_version=0)
        return identifier

    def append_version(
        self, signal_id: UUID, message_version: int, proposal: Proposal, *, expected_version: int
    ) -> int:
        return self.call(
            "SELECT public.append_signal_version(:environment,:signal,:expected,:message_version,"
            ":proposal,:hash)",
            {
                "signal": signal_id,
                "expected": expected_version,
                "message_version": message_version,
                "proposal": proposal.model_dump(mode="json"),
                "hash": fingerprint(proposal),
            },
            "proposal",
        ).scalar_one()


class AgentConfigRepository(ScopedRepository):
    def publish(
        self, agent_id: UUID, config: AgentConfiguration, *, expected_version: int, actor_id: UUID
    ) -> int:
        self.require_admin(actor_id)
        if config.enabled:
            raise ValueError("agent execution remains disabled in Phase 2")
        current = self.connection.scalar(
            select(Agent.current_version)
            .where(
                Agent.environment_id == self.environment_id,
                Agent.id == agent_id,
            )
            .with_for_update()
        )
        if current is None or current != expected_version:
            raise VersionConflict("agent configuration version changed")
        models = {
            row["id"]: ModelDefinition.model_validate(dict(row))
            for row in self.connection.execute(select(ModelRegistry)).mappings()
        }
        config.validate_models(models)
        prompt = self.connection.scalar(
            select(PromptVersion.version).where(
                PromptVersion.environment_id == self.environment_id,
                PromptVersion.agent_id == agent_id,
                PromptVersion.version == config.prompt_version,
            )
        )
        if prompt is None:
            raise ValueError("prompt version does not exist")
        version = current + 1
        values = config.model_dump(exclude={"fallback_model_ids"})
        self.connection.execute(
            insert(AgentConfig).values(
                environment_id=self.environment_id,
                agent_id=agent_id,
                version=version,
                created_by=actor_id,
                **values,
            )
        )
        for ordinal, model_id in enumerate(config.fallback_model_ids, 1):
            self.connection.execute(
                insert(AgentFallback).values(
                    environment_id=self.environment_id,
                    agent_id=agent_id,
                    config_version=version,
                    ordinal=ordinal,
                    model_id=model_id,
                )
            )
        self.connection.execute(
            update(Agent)
            .where(
                Agent.environment_id == self.environment_id,
                Agent.id == agent_id,
            )
            .values(current_version=version)
        )
        self.connection.execute(
            insert(AuditEvent).values(
                id=uuid4(),
                environment_id=self.environment_id,
                action="AGENT_CONFIG_REVISED",
                actor_id=actor_id,
                actor_service="operator",
                target=f"agent:{agent_id}",
                details={"previous_version": current, "version": version},
            )
        )
        return version


class RiskConfigRepository(ScopedRepository):
    def publish(
        self,
        policy: RiskPolicy,
        *,
        ceiling: RiskPolicy,
        expected_version: int,
        actor_id: UUID,
        key: str = "baseline",
    ) -> int:
        self.require_admin(actor_id)
        policy.within(ceiling)
        current = self.connection.scalar(
            select(RiskRuleHead.current_version)
            .where(
                RiskRuleHead.environment_id == self.environment_id,
                RiskRuleHead.key == key,
            )
            .with_for_update()
        )
        if current is None or current != expected_version:
            raise VersionConflict("risk configuration version changed")
        version = current + 1
        self.connection.execute(
            insert(RiskRule).values(
                environment_id=self.environment_id,
                key=key,
                version=version,
                policy=policy.model_dump(mode="json"),
                fingerprint=fingerprint(policy),
                created_by=actor_id,
            )
        )
        self.connection.execute(
            update(RiskRuleHead)
            .where(
                RiskRuleHead.environment_id == self.environment_id,
                RiskRuleHead.key == key,
            )
            .values(current_version=version)
        )
        self.connection.execute(
            insert(AuditEvent).values(
                id=uuid4(),
                environment_id=self.environment_id,
                action="RISK_CONFIG_REVISED",
                actor_id=actor_id,
                actor_service="operator",
                target=f"risk_rule:{key}",
                details={"previous_version": current, "version": version},
            )
        )
        return version


class ModelRegistryRepository(ScopedRepository):
    """Operator-reviewed manifests are immutable; availability changes are audited."""

    def register(self, model: ModelDefinition, *, actor_id: UUID) -> None:
        self.require_admin(actor_id)
        existing = (
            self.connection.execute(
                select(ModelRegistry).where(
                    ModelRegistry.id == model.id,
                )
            )
            .mappings()
            .first()
        )
        if existing:
            if ModelDefinition.model_validate(dict(existing)) != model:
                raise IdentityConflict("registry identity already has a different manifest")
            return
        self.connection.execute(insert(ModelRegistry).values(**model.model_dump()))
        self.connection.execute(
            insert(AuditEvent).values(
                id=uuid4(),
                environment_id=self.environment_id,
                action="MODEL_MANIFEST_REGISTERED",
                actor_id=actor_id,
                actor_service="operator",
                target=f"model:{model.id}",
                details={"pricing_version": model.pricing_version},
            )
        )

    def set_enabled(self, model_id: str, *, enabled: bool, actor_id: UUID) -> None:
        self.require_admin(actor_id)
        if type(enabled) is not bool:
            raise ValueError("availability requires a boolean")
        existing = self.connection.scalar(
            select(ModelRegistry.enabled)
            .where(
                ModelRegistry.id == model_id,
            )
            .with_for_update()
        )
        if existing is None:
            raise ValueError("registry entry does not exist")
        if existing == enabled:
            return
        self.connection.execute(
            update(ModelRegistry)
            .where(ModelRegistry.id == model_id)
            .values(
                enabled=enabled,
            )
        )
        self.connection.execute(
            insert(AuditEvent).values(
                id=uuid4(),
                environment_id=self.environment_id,
                action="MODEL_AVAILABILITY_REVISED",
                actor_id=actor_id,
                actor_service="operator",
                target=f"model:{model_id}",
                details={"enabled": enabled},
            )
        )


@dataclass(frozen=True)
class JobLease:
    job_id: UUID
    generation: int
    payload: dict[str, Any]
    lease_until: datetime


class JobRepository(ScopedRepository):
    def enqueue(self, dedupe_key: str, payload: dict[str, Any]) -> UUID:
        return self.call(
            "SELECT public.enqueue_domain_job(:environment,:key,:payload)",
            {"key": dedupe_key, "payload": payload},
            "payload",
        ).scalar_one()

    def claim(self, worker_id: str, *, lease_seconds: int = 30) -> JobLease | None:
        row = (
            self.call(
                "SELECT * FROM public.claim_domain_job(:environment,:worker,:seconds)",
                {"worker": worker_id, "seconds": lease_seconds},
            )
            .mappings()
            .first()
        )
        return JobLease(**row) if row else None

    def finish(self, lease: JobLease, *, worker_id: str, success: bool) -> None:
        self.call(
            "SELECT public.finish_domain_job(:environment,:job,:worker,:generation,:success)",
            {
                "job": lease.job_id,
                "worker": worker_id,
                "generation": lease.generation,
                "success": success,
            },
        )


class RetentionRepository(ScopedRepository):
    def prune_auth(self, *, limit: int = 100) -> dict[str, int]:
        return dict(
            self.call(
                "SELECT * FROM public.prune_dashboard_auth(:environment,:limit)", {"limit": limit}
            )
            .mappings()
            .one()
        )

    def prune(self, *, limit: int = 100) -> dict[str, int]:
        return dict(
            self.call(
                "SELECT * FROM public.prune_configured_evidence(:environment,:limit)",
                {"limit": limit},
            )
            .mappings()
            .one()
        )


class DomainReadRepository(ScopedRepository):
    VIEWS = {
        "signals": "api_signals",
        "orders": "api_orders",
        "positions": "api_positions",
        "agents": "api_agents",
    }

    def list(self, kind: str, *, limit: int = 100) -> list[dict[str, Any]]:
        if kind not in self.VIEWS or isinstance(limit, bool) or not 1 <= limit <= 500:
            raise ValueError("unsupported view or row limit")
        result = self.connection.execute(
            text(
                f"SELECT * FROM public.{self.VIEWS[kind]} WHERE environment_id=:environment "
                "ORDER BY id LIMIT :limit"
            ),
            {"environment": self.environment_id, "limit": limit},
        )
        return [dict(row) for row in result.mappings()]


class DomainTransaction:
    """Commit or roll back all participating repositories, including audit and outbox."""

    def __init__(self, engine: Engine, environment_id: str) -> None:
        self.engine = engine
        self.environment_id = environment_id

    def __enter__(self) -> "DomainTransaction":
        if not ENVIRONMENT_PATTERN.fullmatch(self.environment_id):
            raise ValueError("invalid environment identity")
        self.connection = self.engine.connect()
        self.transaction = self.connection.begin()
        self.settings = SettingsRepository(self.connection, self.environment_id)
        self.lifecycle = LifecycleRepository(self.connection, self.environment_id)
        self.messages = MessageRepository(self.connection, self.environment_id)
        self.signals = SignalRepository(self.connection, self.environment_id)
        self.jobs = JobRepository(self.connection, self.environment_id)
        self.retention = RetentionRepository(self.connection, self.environment_id)
        self.read = DomainReadRepository(self.connection, self.environment_id)
        return self

    def __exit__(self, error_type, error, traceback) -> None:
        try:
            if error_type is None:
                self.transaction.commit()
            else:
                self.transaction.rollback()
        finally:
            self.connection.close()
