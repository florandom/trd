"""Domain acceptance uses real PostgreSQL transactions, permissions and contention."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, delete, insert, select, text, update
from sqlalchemy.exc import DBAPIError

from backend.application.bootstrap import bootstrap
from backend.domain.contracts import AgentConfiguration, LifecycleChange, Proposal, RiskPolicy
from backend.infrastructure.domain_models import (
    Agent,
    AgentConfig,
    AgentRun,
    AIUsage,
    ExecutionCommand,
    Job,
    LifecycleEvent,
    ModelRegistry,
    Order,
    OutboxEvent,
    Position,
    RiskApproval,
    RiskEvent,
    RiskReservation,
    RiskRule,
    RiskRuleHead,
    Signal,
    SignalVersion,
    TelegramMessage,
    TelegramMessageVersion,
    TelegramSource,
    TradingAccount,
)
from backend.infrastructure.models import AuditEvent, Base, SettingVersion, User
from backend.infrastructure.repositories import (
    AgentConfigRepository,
    DomainTransaction,
    IdentityConflict,
    MessageReceipt,
    ModelRegistryRepository,
    RiskConfigRepository,
    VersionConflict,
)
from tests.integration.support import IsolatedDatabase

pytestmark = pytest.mark.integration
NOW = datetime.now(UTC)
OLD = NOW - timedelta(days=9)


@pytest.fixture
def seeded(isolated_database: IsolatedDatabase):
    bootstrap(isolated_database.settings())
    source_id = uuid4()
    with isolated_database.migration_engine.begin() as connection:
        connection.execute(
            insert(TelegramSource).values(
                environment_id="test",
                id=source_id,
                collector_identity="fixture",
                peer_id="-1001",
                name="Fixture source",
            )
        )
    return isolated_database, source_id


def engine_for(db, role):
    return create_engine(db.urls[f"trd_{role}"])


def raw_message(db, source_id, key="1", environment="test"):
    identifier = uuid4()
    digest = sha256(b"fixture message").hexdigest()
    with db.migration_engine.begin() as connection:
        connection.execute(
            insert(TelegramMessage).values(
                environment_id=environment,
                id=identifier,
                source_id=source_id,
                message_id=key,
            )
        )
        connection.execute(
            insert(TelegramMessageVersion).values(
                environment_id=environment,
                message_id=identifier,
                version=1,
                raw_body="fixture message",
                body_hash=digest,
                observed_at=OLD,
                created_at=OLD,
            )
        )
    return MessageReceipt(identifier, 1, digest, True)


def proposal(**changes):
    return Proposal(
        **(
            dict(
                symbol="EURUSD",
                side="BUY",
                entry="1.1",
                stop_loss="1.09",
                take_profit="1.12",
                expires_at=NOW + timedelta(hours=2),
            )
            | changes
        )
    )


def create_signal(db, message, key="open"):
    engine = engine_for(db, "ai")
    try:
        with DomainTransaction(engine, "test") as uow:
            return uow.signals.create(message, proposal(), intent_key=key, trace_id=uuid4())
    finally:
        engine.dispose()


def transition(
    db, kind, identifier, after, revision, evidence="OBSERVATION", role="risk", event_id=None
):
    engine = engine_for(db, role)
    try:
        with DomainTransaction(engine, "test") as uow:
            return uow.lifecycle.transition(
                kind,
                identifier,
                LifecycleChange(
                    event_id=event_id or uuid4(),
                    expected_revision=revision,
                    after=after,
                    evidence=evidence,
                ),
            )
    finally:
        engine.dispose()


def ignored_signal(db, source_id, key="1"):
    signal_id = create_signal(db, raw_message(db, source_id, key))
    transition(db, "signal", signal_id, "CLASSIFIED", 1, role="ai")
    transition(db, "signal", signal_id, "IGNORED", 2, role="ai")
    return signal_id


def trading_chain(db, signal_id, *, open_position=False, login="18446744073709551615"):
    account, event, approval, reservation, command, order = [uuid4() for _ in range(6)]
    with db.migration_engine.begin() as connection:
        connection.execute(
            insert(TradingAccount).values(
                environment_id="test",
                id=account,
                broker_server="fixture",
                login=login,
                mode="paper",
                currency="USD",
            )
        )
        connection.execute(
            insert(RiskEvent).values(
                environment_id="test",
                id=event,
                signal_id=signal_id,
                signal_version=1,
                rule_key="baseline",
                rule_version=1,
                result="APPROVED",
                reason_codes=["FIXTURE"],
                calculation={"risk_amount": "12.3456789012"},
            )
        )
        connection.execute(
            insert(RiskApproval).values(
                environment_id="test",
                id=approval,
                account_id=account,
                risk_event_id=event,
                risk_amount=Decimal("12.3456789012"),
                safety_epoch=1,
                expires_at=NOW + timedelta(hours=1),
            )
        )
        connection.execute(
            insert(RiskReservation).values(
                environment_id="test",
                id=reservation,
                account_id=account,
                approval_id=approval,
                risk_amount=Decimal("12.3456789012"),
            )
        )
        connection.execute(
            insert(ExecutionCommand).values(
                environment_id="test",
                id=command,
                account_id=account,
                reservation_id=reservation,
                trace_id=uuid4(),
                payload=b"fixture",
                payload_hash=sha256(b"fixture").hexdigest(),
                expires_at=NOW + timedelta(hours=1),
            )
        )
        connection.execute(
            insert(Order).values(
                environment_id="test",
                id=order,
                account_id=account,
                command_id=command,
                broker_ticket=login,
                symbol="EURUSD",
                side="BUY",
                volume=Decimal("0.1234567890"),
            )
        )
        if open_position:
            connection.execute(
                insert(Position).values(
                    environment_id="test",
                    id=uuid4(),
                    account_id=account,
                    order_id=order,
                    broker_identifier=login,
                    symbol="EURUSD",
                    volume=Decimal("0.1234567890"),
                    entry_price=Decimal("1.1234567890"),
                    status="OPEN",
                    opened_at=OLD,
                )
            )
    return dict(
        account=account,
        event=event,
        approval=approval,
        reservation=reservation,
        command=command,
        order=order,
    )


def test_frozen_migration_matches_metadata_and_upgrade_preserves_foundation(seeded):
    db, _ = seeded
    with db.migration_engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        assert compare_metadata(context, Base.metadata) == []
        original_hash = connection.scalar(select(User.password_hash))
    db.downgrade("0001_foundation")
    db.migrate("head")
    bootstrap(db.settings("another-password-never-reset"))
    with db.migration_engine.connect() as connection:
        assert connection.scalar(select(User.password_hash)) == original_hash
        assert connection.scalar(select(text("count(*)")).select_from(Agent)) == 6


def test_disabled_defaults_and_operator_versioning_are_atomic_and_not_reset(seeded):
    db, _ = seeded
    with db.migration_engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE trd_owner"))
        assert all(not row.enabled for row in connection.execute(select(AgentConfig.enabled)))
        assert connection.execute(select(ModelRegistry.id)).scalars().all() == ["mock-v1"]
        actor = connection.scalar(select(User.id))
        agent = connection.scalar(select(Agent.id).limit(1))
        assert (
            AgentConfigRepository(connection, "test").publish(
                agent,
                AgentConfiguration(
                    primary_model_id="mock-v1", prompt_version=1, timeout_seconds=15
                ),
                expected_version=1,
                actor_id=actor,
            )
            == 2
        )
        assert (
            RiskConfigRepository(connection, "test").publish(
                RiskPolicy(max_open_positions=1),
                ceiling=RiskPolicy(),
                expected_version=1,
                actor_id=actor,
            )
            == 2
        )
    bootstrap(db.settings())
    with db.migration_engine.connect() as connection:
        assert connection.scalar(select(Agent.current_version).where(Agent.id == agent)) == 2
        assert connection.scalar(select(RiskRuleHead.current_version)) == 2
        assert len(connection.execute(select(RiskRule.version)).all()) == 2
    with pytest.raises(ValueError), db.migration_engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE trd_owner"))
        RiskConfigRepository(connection, "test").publish(
            RiskPolicy(max_open_positions=3),
            ceiling=RiskPolicy(),
            expected_version=2,
            actor_id=actor,
        )


def test_concurrent_settings_edits_detect_conflict_and_preserve_audit(seeded):
    db, _ = seeded
    with db.migration_engine.connect() as connection:
        actor = connection.scalar(select(User.id))
    engine = engine_for(db, "api")

    def revise(value):
        try:
            with DomainTransaction(engine, "test") as uow:
                return uow.settings.revise(
                    "telegram_retention_days", value, expected_version=1, actor_id=actor
                )
        except VersionConflict:
            return "conflict"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(revise, [8, 9]))
        assert sorted(results, key=str) == [2, "conflict"]
        with db.migration_engine.connect() as connection:
            versions = (
                connection.execute(
                    select(SettingVersion.version).where(
                        SettingVersion.key == "telegram_retention_days",
                    )
                )
                .scalars()
                .all()
            )
            assert sorted(versions) == [1, 2]
            audits = (
                connection.execute(
                    select(AuditEvent.details).where(
                        AuditEvent.action == "SETTING_REVISED",
                    )
                )
                .scalars()
                .all()
            )
            assert audits == [{"previous_version": 1, "version": 2}]
        for key, value in (
            ("automation_enabled", True),
            ("trading_mode", "live"),
            ("telegram_retention_days", 7.5),
            ("internal_secret", "sensitive"),
        ):
            with pytest.raises(IdentityConflict), DomainTransaction(engine, "test") as uow:
                uow.settings.revise(key, value, expected_version=2, actor_id=actor)
    finally:
        engine.dispose()


def test_viewer_cannot_revise_settings_even_via_direct_database_function(seeded):
    db, _ = seeded
    actor = uuid4()
    with db.migration_engine.begin() as connection:
        connection.execute(
            insert(User).values(
                id=actor, email="viewer@example.test", password_hash="unused", role="VIEWER"
            )
        )
    engine = engine_for(db, "api")
    try:
        with pytest.raises(PermissionError), DomainTransaction(engine, "test") as uow:
            uow.settings.revise("telegram_retention_days", 8, expected_version=1, actor_id=actor)
    finally:
        engine.dispose()


def test_message_duplicate_edit_and_stale_delivery_are_durable(seeded):
    db, source = seeded
    engine = engine_for(db, "collector")

    def record(body="original", observed_at=OLD):
        with DomainTransaction(engine, "test") as uow:
            return uow.messages.record(
                source_id=source, message_id="9", body=body, observed_at=observed_at
            )

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            receipts = list(pool.map(lambda _: record(), range(2)))
        assert len({r.message_id for r in receipts}) == 1
        assert sum(r.created for r in receipts) == 1
        edited = record("edited", OLD + timedelta(minutes=1))
        assert edited.version == 2
        assert record("late original", OLD).body_hash == edited.body_hash
        with pytest.raises(IdentityConflict):
            record("conflicting edit", OLD + timedelta(minutes=1))
        with db.migration_engine.connect() as connection:
            assert len(connection.execute(select(TelegramMessageVersion.version)).all()) == 2
    finally:
        engine.dispose()


def test_signal_intent_is_deduplicated_under_concurrency(seeded):
    db, source = seeded
    message = raw_message(db, source)
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(lambda _: create_signal(db, message), range(2)))
    assert ids[0] == ids[1]
    with db.migration_engine.connect() as connection:
        assert len(connection.execute(select(Signal.id)).all()) == 1
        assert len(connection.execute(select(SignalVersion.version)).all()) == 1


def test_lifecycle_events_are_idempotent_and_rollback_with_outbox(seeded):
    db, source = seeded
    signal_id = create_signal(db, raw_message(db, source))
    event = uuid4()
    engine = engine_for(db, "ai")
    change = LifecycleChange(event_id=event, expected_revision=1, after="CLASSIFIED")
    try:
        with pytest.raises(RuntimeError), DomainTransaction(engine, "test") as uow:
            assert uow.lifecycle.transition("signal", signal_id, change) == 2
            raise RuntimeError("crash before commit")
        with db.migration_engine.connect() as connection:
            assert connection.scalar(select(Signal.state)) == "RECEIVED"
            assert connection.execute(select(OutboxEvent.id)).first() is None
        for _ in range(2):
            with DomainTransaction(engine, "test") as uow:
                assert uow.lifecycle.transition("signal", signal_id, change) == 2
        with db.migration_engine.connect() as connection:
            assert len(connection.execute(select(LifecycleEvent.id)).all()) == 1
            assert len(connection.execute(select(OutboxEvent.id)).all()) == 1
        with pytest.raises(IdentityConflict):
            transition(db, "signal", signal_id, "PARSED", 1, role="ai", event_id=event)
    finally:
        engine.dispose()


def test_ai_cannot_approve_and_submitted_results_require_broker_evidence(seeded):
    db, source = seeded
    identifier = create_signal(db, raw_message(db, source))
    revision = 1
    for after in ("CLASSIFIED", "PARSED", "DECIDED", "RISK_CHECK"):
        revision = transition(db, "signal", identifier, after, revision, role="ai")
    with pytest.raises(PermissionError):
        transition(db, "signal", identifier, "APPROVED", revision, role="ai")
    revision = transition(db, "signal", identifier, "APPROVED", revision)
    revision = transition(db, "signal", identifier, "EXECUTION_REQUESTED", revision)
    with pytest.raises(IdentityConflict):
        transition(db, "signal", identifier, "EXECUTED", revision)
    transition(db, "signal", identifier, "EXECUTED", revision, evidence="BROKER_FILL")


def test_uncertain_order_cannot_be_resent_or_expired(seeded):
    db, source = seeded
    chain = trading_chain(db, create_signal(db, raw_message(db, source)))
    revision = 1
    for state in ("VALIDATED", "REQUESTED", "SENT", "OUTCOME_UNKNOWN"):
        revision = transition(db, "order", chain["order"], state, revision)
    for state in ("SENT", "EXPIRED", "FAILED"):
        with pytest.raises(IdentityConflict):
            transition(db, "order", chain["order"], state, revision)
    revision = transition(db, "order", chain["order"], "RECONCILING", revision)
    with pytest.raises(IdentityConflict):
        transition(db, "order", chain["order"], "FILLED", revision)
    transition(db, "order", chain["order"], "FILLED", revision, evidence="RECONCILED_FILL")


def test_message_edit_invalidates_unsent_commands_and_preserves_submitted_outcomes(seeded):
    db, source = seeded
    signal_id = create_signal(db, raw_message(db, source))
    trading_chain(db, signal_id)
    engine = engine_for(db, "ai")
    try:
        with DomainTransaction(engine, "test") as uow:
            assert (
                uow.signals.append_version(
                    signal_id, 1, proposal(entry="1.101"), expected_version=1
                )
                == 2
            )
        with db.migration_engine.connect() as connection:
            assert connection.scalar(select(ExecutionCommand.state)) == "INVALIDATED"
            assert connection.scalar(select(RiskReservation.status)) == "RELEASED"
            assert connection.scalar(select(Signal.state)) == "RECEIVED"
            assert connection.scalar(select(Signal.revision)) == 2
            assert (
                connection.scalar(
                    select(LifecycleEvent.after).where(
                        LifecycleEvent.kind == "command",
                    )
                )
                == "INVALIDATED"
            )
        # A submitted command is preserved even if the source changes again.
        other = create_signal(db, raw_message(db, source, "2"))
        other_chain = trading_chain(db, other, login="2")
        transition(db, "command", other_chain["command"], "READY", 1)
        transition(db, "command", other_chain["command"], "DELIVERED", 2)
        transition(db, "command", other_chain["command"], "OUTCOME_UNKNOWN", 3)
        with DomainTransaction(engine, "test") as uow:
            uow.signals.append_version(other, 1, proposal(entry="1.101"), expected_version=1)
        with db.migration_engine.connect() as connection:
            assert (
                connection.scalar(
                    select(ExecutionCommand.state).where(
                        ExecutionCommand.id == other_chain["command"],
                    )
                )
                == "OUTCOME_UNKNOWN"
            )
            assert (
                connection.scalar(
                    select(RiskReservation.status).where(
                        RiskReservation.id == other_chain["reservation"],
                    )
                )
                == "HELD"
            )
    finally:
        engine.dispose()


def test_environment_and_account_foreign_keys_and_exact_money(seeded):
    db, source = seeded
    message = raw_message(db, source)
    signal_id = create_signal(db, message)
    chain = trading_chain(db, signal_id)
    with db.migration_engine.connect() as connection:
        assert connection.scalar(select(RiskApproval.risk_amount)) == Decimal("12.3456789012")
        assert connection.scalar(select(Order.broker_ticket)) == "18446744073709551615"
    with pytest.raises(DBAPIError) as error, db.migration_engine.begin() as connection:
        connection.execute(
            insert(TelegramMessage).values(
                environment_id="other",
                id=uuid4(),
                source_id=source,
                message_id="1",
            )
        )
    assert error.value.orig.sqlstate == "23503"
    with pytest.raises(DBAPIError) as error, db.migration_engine.begin() as connection:
        # Remove the fixture order within the transaction so the account FK,
        # rather than the command's one-order uniqueness, is the rejecting constraint.
        connection.execute(delete(Order).where(Order.id == chain["order"]))
        connection.execute(
            insert(Order).values(
                environment_id="test",
                id=uuid4(),
                account_id=uuid4(),
                command_id=chain["command"],
                symbol="EURUSD",
                side="BUY",
                volume=Decimal("0.1"),
            )
        )
    assert error.value.orig.sqlstate == "23503"
    with pytest.raises(DBAPIError) as error, db.migration_engine.begin() as connection:
        connection.execute(
            insert(AIUsage).values(
                environment_id="test",
                id=uuid4(),
                run_id=uuid4(),
                input_tokens=1,
                output_tokens=1,
                estimated_cost_usd=Decimal("NaN"),
                pricing_version="mock-zero-v1",
            )
        )
    assert error.value.orig.sqlstate == "23514"


def test_raw_retention_is_bounded_resumable_and_protects_open_evidence(seeded):
    db, source = seeded
    ignored_signal(db, source, "1")
    protected = ignored_signal(db, source, "2")
    chain = trading_chain(db, protected, open_position=True)
    # Retain open-position evidence even after command/reservation lifecycle is settled.
    for state, rev, evidence in (
        ("READY", 1, "OBSERVATION"),
        ("DELIVERED", 2, "OBSERVATION"),
        ("COMPLETED", 3, "BROKER_FILL"),
    ):
        transition(db, "command", chain["command"], state, rev, evidence)
    with db.migration_engine.begin() as connection:
        connection.execute(update(RiskReservation).values(status="CONSUMED"))
        agent = connection.scalar(select(Agent.id).limit(1))
        for signal, status in ((None, "SUCCEEDED"), (protected, "SUCCEEDED"), (None, "UNKNOWN")):
            connection.execute(
                insert(AgentRun).values(
                    environment_id="test",
                    id=uuid4(),
                    agent_id=agent,
                    config_version=1,
                    signal_id=signal,
                    trace_id=uuid4(),
                    model_id="mock-v1",
                    attempt=1,
                    status=status,
                    result={"decision": "WAIT"},
                    raw_response="private raw response",
                    created_at=OLD,
                )
            )
    engine = engine_for(db, "maintenance")
    try:
        with DomainTransaction(engine, "test") as uow:
            assert uow.retention.prune(limit=1) == {"telegram_count": 1, "ai_count": 1}
        with DomainTransaction(engine, "test") as uow:
            assert uow.retention.prune(limit=1) == {"telegram_count": 0, "ai_count": 0}
        with db.migration_engine.connect() as connection:
            messages = connection.execute(select(TelegramMessageVersion.raw_body)).scalars().all()
            assert messages.count(None) == 1 and len(messages) == 2
            assert connection.scalar(select(SignalVersion.proposal_hash).limit(1)) is not None
            assert len(connection.execute(select(AgentRun.id)).all()) == 3
            assert (
                len(
                    connection.execute(
                        select(AgentRun.raw_response).where(
                            AgentRun.raw_response.is_not(None),
                        )
                    ).all()
                )
                == 2
            )
    finally:
        engine.dispose()


def test_retention_rollback_and_expired_message_cannot_be_reintroduced(seeded):
    db, source = seeded
    message = raw_message(db, source)
    engine = engine_for(db, "maintenance")
    try:
        with pytest.raises(RuntimeError), DomainTransaction(engine, "test") as uow:
            uow.retention.prune()
            raise RuntimeError("cleanup interrupted")
        with db.migration_engine.connect() as connection:
            assert connection.scalar(select(TelegramMessageVersion.raw_body)) is not None
        with DomainTransaction(engine, "test") as uow:
            uow.retention.prune()
    finally:
        engine.dispose()
    with pytest.raises(IdentityConflict):
        create_signal(db, message)


def test_job_deduplication_concurrent_claims_and_stale_generation_fencing(seeded):
    db, _ = seeded
    engine = engine_for(db, "ai")
    try:
        with DomainTransaction(engine, "test") as uow:
            first = uow.jobs.enqueue("first", {"signal": "fixture"})
            assert first == uow.jobs.enqueue("first", {"signal": "fixture"})
            uow.jobs.enqueue("second", {})
        with pytest.raises(IdentityConflict), DomainTransaction(engine, "test") as uow:
            uow.jobs.enqueue("first", {"signal": "conflicting"})

        def claim(worker):
            with DomainTransaction(engine, "test") as uow:
                return uow.jobs.claim(worker)

        with ThreadPoolExecutor(max_workers=2) as pool:
            leases = list(pool.map(claim, ["worker1", "worker2"]))
        assert len({lease.job_id for lease in leases}) == 2
        with db.migration_engine.begin() as connection:
            connection.execute(
                update(Job).where(Job.id == leases[0].job_id).values(lease_until=OLD)
            )
        replacement = claim("worker3")
        assert replacement.job_id == leases[0].job_id and replacement.generation == 2
        with pytest.raises(VersionConflict), DomainTransaction(engine, "test") as uow:
            uow.jobs.finish(leases[0], worker_id="worker1", success=True)
        with DomainTransaction(engine, "test") as uow:
            uow.jobs.finish(replacement, worker_id="worker3", success=True)
    finally:
        engine.dispose()


@pytest.mark.parametrize("role", ["api", "collector", "ai", "maintenance"])
def test_lower_privilege_roles_cannot_forge_execution_or_erase_evidence(seeded, role):
    db, _ = seeded
    engine = engine_for(db, role)
    try:
        for sql in (
            "UPDATE execution_commands SET state='COMPLETED'",
            "DELETE FROM risk_approvals",
            "UPDATE risk_reservations SET status='RELEASED'",
            "UPDATE prompt_versions SET body='untrusted'",
            "DELETE FROM jobs",
            "UPDATE telegram_message_versions SET raw_body=NULL",
        ):
            with pytest.raises(DBAPIError) as error, engine.begin() as connection:
                connection.execute(text(sql))
            assert error.value.orig.sqlstate == "42501"
    finally:
        engine.dispose()


def test_append_only_versions_and_audit_cannot_be_rewritten_even_by_owner(seeded):
    db, _ = seeded
    for sql in (
        "UPDATE setting_versions SET value='true'::jsonb",
        "UPDATE prompt_versions SET body='changed'",
        "DELETE FROM audit_events",
        "UPDATE model_registry SET input_price_per_million=100",
    ):
        with pytest.raises(DBAPIError) as error, db.migration_engine.begin() as connection:
            connection.execute(text("SET LOCAL ROLE trd_owner"))
            connection.execute(text(sql))
        assert error.value.orig.sqlstate == "42501"


def test_registry_availability_is_audited_and_preserved_by_bootstrap(seeded):
    db, _ = seeded
    with db.migration_engine.begin() as connection:
        actor = connection.scalar(select(User.id))
        connection.execute(text("SET LOCAL ROLE trd_owner"))
        ModelRegistryRepository(connection, "test").set_enabled(
            "mock-v1", enabled=False, actor_id=actor
        )
    bootstrap(db.settings())
    with db.migration_engine.connect() as connection:
        assert connection.scalar(select(ModelRegistry.enabled)) is False
        assert (
            connection.scalar(
                select(AuditEvent.action).where(
                    AuditEvent.action == "MODEL_AVAILABILITY_REVISED",
                )
            )
            is not None
        )


def test_retention_uses_the_current_versioned_policy(seeded):
    db, source = seeded
    raw_message(db, source)
    with db.migration_engine.connect() as connection:
        actor = connection.scalar(select(User.id))
    engine = engine_for(db, "api")
    try:
        with DomainTransaction(engine, "test") as uow:
            uow.settings.revise("telegram_retention_days", 14, expected_version=1, actor_id=actor)
    finally:
        engine.dispose()
    engine = engine_for(db, "maintenance")
    try:
        with DomainTransaction(engine, "test") as uow:
            assert uow.retention.prune()["telegram_count"] == 0
    finally:
        engine.dispose()


def test_risk_cannot_rewrite_policy_and_signed_command_payload_is_immutable(seeded):
    db, source = seeded
    chain = trading_chain(db, create_signal(db, raw_message(db, source)))
    engine = engine_for(db, "risk")
    try:
        with pytest.raises(DBAPIError) as error, engine.begin() as connection:
            connection.execute(
                insert(RiskRule).values(
                    environment_id="test",
                    key="unsafe",
                    version=1,
                    policy={},
                    fingerprint="0" * 64,
                )
            )
        assert error.value.orig.sqlstate == "42501"
    finally:
        engine.dispose()
    with pytest.raises(DBAPIError) as error, db.migration_engine.begin() as connection:
        connection.execute(
            update(ExecutionCommand)
            .where(ExecutionCommand.id == chain["command"])
            .values(
                payload=b"changed payload",
            )
        )
    assert error.value.orig.sqlstate == "42501"
