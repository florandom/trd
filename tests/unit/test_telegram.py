import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import SecretStr, ValidationError
from telethon import types

from backend.application.telegram import Collector
from backend.domain.config import CollectorSettings
from backend.domain.telegram import SourceConfiguration, TelegramObservation
from backend.infrastructure.repositories import VersionConflict
from backend.infrastructure.telegram_repository import CollectorOwnership
from backend.integrations.telegram.client import Peer, ReadOnlyTelegramClient, observation
from backend.integrations.telegram.session import (
    SessionError,
    StoredSession,
    load_session,
    save_session,
)


def settings(tmp_path, **changes):
    return CollectorSettings(
        app_env="test",
        environment_id="test",
        data_dir=tmp_path,
        database_url="postgresql+psycopg://trd_collector:test-password@localhost:5432/test",
        telegram_api_id=1234,
        telegram_api_hash="a" * 32,
        telegram_session_encryption_key="b" * 64,
        **changes,
    )


def test_session_ciphertext_random_nonce_and_scope_authentication(tmp_path):
    config = settings(tmp_path)
    stored = StoredSession("1234", SecretStr("fixture-secret-session"))
    save_session(config, stored)
    path = tmp_path / "telegram.session.enc"
    first = path.read_bytes()
    assert b"fixture-secret-session" not in first
    assert load_session(config).credential == stored.credential
    with pytest.raises(SessionError):
        save_session(config, stored)
    save_session(config, stored, replace=True)
    assert first != path.read_bytes()
    for changes in (
        {"environment_id": "other"},
        {"telegram_collector_identity": "other"},
        {"telegram_session_key_id": "other"},
        {"telegram_session_encryption_key": SecretStr("c" * 64)},
    ):
        with pytest.raises(SessionError):
            load_session(config.model_copy(update=changes))
    envelope = json.loads(path.read_text())
    envelope["account"] = "4321"
    path.write_text(json.dumps(envelope))
    with pytest.raises(SessionError):
        load_session(config)


def test_session_permissions_tamper_and_atomic_replace(tmp_path, monkeypatch):
    config = settings(tmp_path)
    stored = StoredSession("1234", SecretStr("fixture-session"))
    save_session(config, stored)
    path = tmp_path / "telegram.session.enc"
    original = path.read_bytes()

    def fail(*_args):
        raise OSError("fixture")

    monkeypatch.setattr("backend.integrations.telegram.session.os.replace", fail)
    with pytest.raises(OSError):
        save_session(config, stored, replace=True)
    assert path.read_bytes() == original
    assert len(list(tmp_path.iterdir())) == 1
    import os

    if os.name != "nt":
        path.chmod(0o644)
        with pytest.raises(SessionError):
            load_session(config)


@pytest.mark.parametrize(
    "reference",
    [
        "https://evil.test",
        "https://t.me/+invite",
        "me",
        "1234",
        "@abc",
        "@bad name",
        "-0",
        "@username\x00",
    ],
)
def test_source_references_do_not_authorize_arbitrary_urls_or_private_peers(reference):
    with pytest.raises(ValidationError):
        SourceConfiguration(name="Fonte", reference=reference, enabled=True)


def test_source_reference_is_canonical_and_capabilities_are_strict():
    assert (
        SourceConfiguration(name=" Fonte ", reference=" @Example_Name ", enabled=True).reference
        == "@example_name"
    )
    assert (
        SourceConfiguration(
            name="Fonte", reference="https://t.me/Example_Name/", enabled=True
        ).reference
        == "@example_name"
    )
    with pytest.raises(ValidationError):
        SourceConfiguration(name="Fonte", reference="@example_name", enabled="true")


def test_enabled_collector_requires_real_config(tmp_path):
    with pytest.raises(ValidationError):
        settings(tmp_path, telegram_enabled=True).model_validate(
            settings(tmp_path).model_dump() | {"telegram_api_id": None, "telegram_enabled": True}
        )
    assert settings(tmp_path, telegram_enabled=True).telegram_enabled


def test_message_normalizes_edit_reply_caption_without_downloading():
    now = datetime.now(UTC)
    message = types.Message(
        id=4,
        peer_id=types.PeerChannel(12),
        date=now - timedelta(minutes=1),
        message="Untrusted https://example.test",
        edit_date=now,
        reply_to=types.MessageReplyHeader(reply_to_msg_id=2),
    )
    event = observation(message)
    assert event.kind == "EDIT" and event.reply_message_id == 2
    assert event.body == message.message
    assert (
        event.payload()["revision_hash"]
        != event.model_copy(update={"body": "changed"}).payload()["revision_hash"]
    )
    with pytest.raises(ValidationError):
        event.model_validate(event.model_dump() | {"body": "\x00"})
    with pytest.raises(ValidationError):
        event.model_validate(event.model_dump() | {"observed_at": datetime.now()})


def test_transport_uses_memory_session_and_no_update_queue(tmp_path):
    from telethon.crypto import AuthKey
    from telethon.sessions import StringSession

    session = StringSession()
    session.set_dc(2, "149.154.167.51", 443)
    session.auth_key = AuthKey(b"a" * 256)
    client = ReadOnlyTelegramClient(
        settings(tmp_path), StoredSession("1234", SecretStr(session.save()))
    )
    assert client.client._no_updates is True and client.client._auto_reconnect is False
    assert client.client._request_retries == 0 and client.client.flood_sleep_threshold == 0
    assert list(tmp_path.iterdir()) == []
    save_session(settings(tmp_path), client.stored)
    client.client.session.set_dc(3, "149.154.175.100", 443)
    client.persist_session()
    stored = load_session(settings(tmp_path))
    assert StringSession(stored.credential.get_secret_value()).dc_id == 3
    assert (
        stored.credential.get_secret_value().encode()
        not in (tmp_path / "telegram.session.enc").read_bytes()
    )


@pytest.mark.parametrize("gap", [False, True])
def test_offline_edit_and_delete_recovery_do_not_skip_sequential_history(tmp_path, gap):
    now = datetime.now(UTC)
    base = TelegramObservation(
        message_id=1, kind="NEW", body="old", published_at=now, observed_at=now
    )
    edited = base.model_copy(
        update={"kind": "EDIT", "body": "edited", "observed_at": now + timedelta(seconds=1)}
    )
    source = {
        "id": "fixture",
        "version": 1,
        "resolution_state": "RESOLVED",
        "peer_id": "-10012",
        "peer_kind": "CHANNEL",
        "access_hash": "5",
        "last_message_id": 42,
        "cursor_published_at": now - timedelta(days=2) if gap else now,
        "delete_cursor": 0,
        "last_success_at": now - timedelta(days=2) if gap else now,
    }
    ownership = CollectorOwnership("1234", "owner", 1)
    recorded = []
    states = []
    offsets = []
    store = SimpleNamespace(
        acquire=lambda *_: ownership,
        ingest=lambda *args, **kwargs: recorded.append(
            (args[2], kwargs.get("advance_cursor", True))
        ),
        observe=lambda *args, **kwargs: states.append(kwargs),
        deletion_candidates=lambda *_: [
            {"message_id": "1", "published_at": now},
            {"message_id": "2", "published_at": now},
        ],
    )

    class Fake:
        async def history(self, _peer, **kwargs):
            offsets.append(kwargs["after"])
            return [base.model_copy(update={"message_id": 9})] if kwargs.get("newest") else [base]

        async def check_ids(self, _peer, _ids):
            return {1: edited, 2: None}

    collector = Collector(settings(tmp_path), store)
    collector.owner = "owner"
    collector.ownership = ownership
    complete = asyncio.run(collector.scan_source(Fake(), source))
    assert [(event.message_id, event.kind, advance) for event, advance in recorded] == [
        (1, "NEW", True),
        (9, "NEW", False),
        (1, "EDIT", False),
        (2, "DELETE", False),
    ]
    assert states[-1]["status"] == ("GAP" if gap else "ACTIVE")
    assert states[-1]["delete_cursor"] == 2 and complete is not gap
    assert offsets == [0 if gap else 42, 0]


def test_mid_cycle_database_failure_reports_degraded_after_a_successful_source(
    tmp_path, monkeypatch
):
    config = settings(tmp_path, telegram_enabled=True)
    save_session(config, StoredSession("1234", SecretStr("fixture-session")))
    states = []
    monkeypatch.setattr(
        "backend.application.telegram.HeartbeatRuntime",
        lambda *_: SimpleNamespace(emit=states.append),
    )
    stop = asyncio.Event()
    ownership = CollectorOwnership("1234", "owner", 1)
    store = SimpleNamespace(
        acquire=lambda *_: ownership,
        sources=lambda *_: [1, 2],
        release=lambda *_: None,
    )

    class Fake:
        async def connect(self):
            pass

        def persist_session(self):
            pass

        async def disconnect(self):
            stop.set()

    collector = Collector(config, store, client_factory=lambda *_: Fake())

    async def scan(_client, source):
        if source == 2:
            raise VersionConflict("database fence lost")
        return True

    monkeypatch.setattr(collector, "scan_source", scan)
    asyncio.run(collector.run(stop))
    assert states == ["STARTING", "DEGRADED", "STOPPED"]


def test_fence_loss_prevents_further_network_requests(tmp_path):
    store = SimpleNamespace(acquire=lambda *_: None)
    collector = Collector(settings(tmp_path), store)
    collector.ownership = CollectorOwnership("1234", "owner", 1)
    called = []

    async def operation():
        called.append(True)

    with pytest.raises(VersionConflict):
        asyncio.run(collector.network(operation))
    assert not called


def test_peer_id_mapping_does_not_use_fuzzy_symbol_or_source_matching():
    assert Peer("-1001234", "CHANNEL", "99").input_peer() == types.InputPeerChannel(1234, 99)
    assert Peer("-1234", "CHAT").input_peer() == types.InputPeerChat(1234)
