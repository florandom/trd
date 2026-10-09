"""Telegram acceptance against real PostgreSQL permissions, leases and atomic history."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, insert, select, text, update
from sqlalchemy.exc import DBAPIError

from backend.domain.telegram import TelegramObservation
from backend.infrastructure.domain_models import (
    CollectorLease,
    CollectorSourceState,
    ExecutionCommand,
    Job,
    OutboxEvent,
    Signal,
    TelegramMessage,
    TelegramMessageVersion,
    TelegramSource,
)
from backend.infrastructure.models import AuditEvent
from backend.infrastructure.repositories import IdentityConflict, VersionConflict
from backend.infrastructure.telegram_repository import TelegramStore
from tests.integration.test_dashboard import auth_headers, login
from tests.integration.test_dashboard import dashboard as dashboard
from tests.integration.test_domain_persistence import create_signal, raw_message, trading_chain

pytestmark = pytest.mark.integration


@pytest.fixture
def collection(isolated_database):
    db = isolated_database
    source_id = uuid4()
    with db.migration_engine.begin() as connection:
        connection.execute(
            insert(TelegramSource).values(
                environment_id="test",
                id=source_id,
                name="Fixture source",
                collector_identity="primary",
                peer_id="-1001234",
                reference="@fixture_source",
                access_hash="9",
                peer_kind="CHANNEL",
                enabled=True,
                resolution_state="RESOLVED",
            )
        )
    engine = create_engine(db.urls["trd_collector"])
    store = TelegramStore(engine, "test")
    ownership = store.acquire("1234", "fixture-owner")
    source = store.sources("primary")[0]
    yield db, store, ownership, source
    engine.dispose()


def event(body="first", key=1, offset=0, old=False, kind="NEW"):
    now = datetime.now(UTC) - timedelta(seconds=10)
    published = now - timedelta(days=2) if old else now
    return TelegramObservation(
        message_id=key,
        kind=kind,
        body=body,
        published_at=published,
        observed_at=published + timedelta(seconds=offset),
    )


def test_lease_contention_and_expiry_fence(collection):
    db, store, owner, source = collection
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(lambda name: store.acquire("1234", name), ["other1", "other2"])) == [
            None,
            None,
        ]
    assert store.acquire("1234", owner.owner).generation == owner.generation
    with db.migration_engine.begin() as connection:
        connection.execute(
            update(CollectorLease).values(lease_until=datetime.now(UTC) - timedelta(seconds=1))
        )
    next_owner = store.acquire("1234", "new-owner")
    assert next_owner.generation == owner.generation + 1
    with pytest.raises(VersionConflict):
        store.ingest(owner, source, event())
    with db.migration_engine.connect() as connection:
        assert connection.scalar(select(text("count(*)")).select_from(TelegramMessageVersion)) == 0


def test_duplicate_edit_delete_reply_are_atomic_and_no_resurrection(collection):
    db, store, owner, source = collection
    original = event().model_copy(update={"reply_message_id": 7})
    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = list(pool.map(lambda _: store.ingest(owner, source, original), range(2)))
    assert sum(r["created"] for r in receipts) == 1
    first = receipts[0]["id"]
    edited = original.model_copy(
        update={
            "kind": "EDIT",
            "body": "edited",
            "observed_at": original.observed_at + timedelta(seconds=1),
        }
    )
    assert store.ingest(owner, source, edited)["version"] == 2
    assert store.ingest(owner, source, original)["version"] == 2
    tombstone = original.model_copy(
        update={"kind": "DELETE", "body": "", "observed_at": datetime.now(UTC)}
    )
    assert store.ingest(owner, source, tombstone)["version"] == 3
    assert store.ingest(owner, source, edited)["created"] is False
    assert store.sources("primary")[0]["cursor_published_at"] == original.published_at
    with db.migration_engine.connect() as connection:
        assert connection.scalar(select(TelegramMessage.reply_message_id)) == "7"
        versions = (
            connection.execute(
                select(TelegramMessageVersion).order_by(TelegramMessageVersion.version)
            )
            .mappings()
            .all()
        )
        assert len(versions) == 3 and versions[-1]["raw_body"] is None
        assert connection.scalar(select(text("count(*)")).select_from(OutboxEvent)) == 3
        assert connection.scalar(select(text("count(*)")).select_from(Job)) == 3
        assert all(
            r.payload["message_id"] == first for r in connection.execute(select(Job.payload))
        )
        assert not connection.scalar(select(text("count(*)")).select_from(ExecutionCommand))


def test_cursor_overlap_and_atomic_conflict_rollback(collection):
    db, store, owner, source = collection
    original = event()
    store.ingest(owner, source, original)
    newest = original.model_copy(update={"message_id": 50})
    store.ingest(owner, source, newest, advance_cursor=False)
    with db.migration_engine.connect() as connection:
        assert connection.scalar(select(CollectorSourceState.last_message_id)) == 1
    store.ingest(owner, source, newest)
    with db.migration_engine.connect() as connection:
        assert connection.scalar(select(CollectorSourceState.last_message_id)) == 50
    with pytest.raises(IdentityConflict):
        store.ingest(owner, source, newest.model_copy(update={"body": "conflicting timestamp"}))
    with db.migration_engine.connect() as connection:
        assert connection.scalar(select(text("count(*)")).select_from(TelegramMessageVersion)) == 2
        assert connection.scalar(select(text("count(*)")).select_from(AuditEvent)) == 2


def test_old_messages_do_not_create_fresh_analysis_jobs(collection):
    db, store, owner, source = collection
    store.ingest(owner, source, event(old=True))
    with db.migration_engine.connect() as connection:
        assert connection.scalar(select(text("count(*)")).select_from(Job)) == 0
        assert connection.scalar(select(OutboxEvent.topic)) == "telegram.message.expired"


def test_source_disable_or_version_change_rejects_inflight_observation(collection):
    db, store, owner, source = collection
    with db.migration_engine.begin() as connection:
        connection.execute(update(TelegramSource).values(enabled=False, version=2))
    with pytest.raises(VersionConflict):
        store.ingest(owner, source, event())
    with pytest.raises(VersionConflict):
        store.observe(owner, source, status="ACTIVE")
    with db.migration_engine.connect() as connection:
        assert connection.scalar(select(text("count(*)")).select_from(TelegramMessageVersion)) == 0


def test_flood_wait_persists_across_owner_and_process_restart(collection):
    _db, store, owner, _source = collection
    store.backoff(owner, 300)
    store.release(owner)
    assert store.acquire("1234", "next-owner") is None


def test_collector_cannot_bypass_fence_and_other_roles_cannot_claim(collection):
    db, store, _owner, source = collection
    with pytest.raises(DBAPIError), store.engine.begin() as connection:
        connection.execute(
            insert(TelegramMessage).values(
                environment_id="test", id=uuid4(), source_id=source["id"], message_id="99"
            )
        )
    for role in ("api", "ai", "risk", "maintenance"):
        engine = create_engine(db.urls["trd_" + role])
        try:
            with pytest.raises(PermissionError):
                TelegramStore(engine, "test").acquire("1234", "bad-owner")
        finally:
            engine.dispose()


def test_source_management_confirmed_and_audited_without_credentials(dashboard):
    client, db = dashboard
    login(client)
    headers = auth_headers(client)
    identifier = str(uuid4())
    change = {
        "kind": "source",
        "target": identifier,
        "expected_version": 0,
        "value": {
            "name": "Fonte del cliente",
            "reference": "https://t.me/Client_Source",
            "enabled": True,
        },
    }
    confirmed = client.post("/config/confirm", json=change, headers=headers)
    assert confirmed.status_code == 200
    confirmation = confirmed.json()
    assert confirmation["change"]["value"]["reference"] == "@client_source"
    body = {
        "change": confirmation["change"],
        "confirmation_token": confirmation["confirmation_token"],
    }
    applied = client.post("/config/apply", json=body, headers=headers)
    assert applied.status_code == 200
    rows = client.get("/ops/sources").json()["rows"]
    assert len(rows) == 1 and rows[0]["status"] == "PENDING" and rows[0]["version"] == 1
    assert not {"access_hash", "collector_identity"} & rows[0].keys()
    assert client.post("/config/apply", json=body, headers=headers).status_code == 422
    change = confirmation["change"] | {
        "expected_version": 1,
        "value": confirmation["change"]["value"] | {"enabled": False},
    }
    review = client.post("/config/confirm", json=change, headers=headers).json()
    assert (
        client.post(
            "/config/apply",
            json={"change": review["change"], "confirmation_token": review["confirmation_token"]},
            headers=headers,
        ).status_code
        == 200
    )
    with db.migration_engine.connect() as connection:
        assert connection.scalar(select(TelegramSource.version)) == 2
        assert (
            len(
                connection.execute(
                    select(AuditEvent.id).where(AuditEvent.action == "SOURCE_CONFIG_REVISED")
                ).all()
            )
            == 2
        )


def test_revisions_invalidate_unsent_proposals_and_commands_keep_reservations(collection):
    db, store, owner, source = collection
    from backend.application.bootstrap import bootstrap

    bootstrap(db.settings())
    message = raw_message(db, source["id"])
    signal_id = create_signal(db, message)
    command_id = trading_chain(db, signal_id)["command"]
    # Foundation fixture is already at REQUESTED; the collector must not rewrite the order.
    latest = event(body="changed", kind="EDIT")
    result = store.ingest(owner, source, latest)
    assert result["version"] == 2
    with db.migration_engine.connect() as connection:
        assert connection.scalar(select(Signal.state)) == "EXPIRED"
        assert (
            connection.scalar(
                select(ExecutionCommand.state).where(ExecutionCommand.id == command_id)
            )
            == "INVALIDATED"
        )
