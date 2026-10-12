from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import httpx
import pytest

from backend.domain.bridge import (
    Envelope,
    PaperCommand,
    PaperProfile,
    PaperSnapshot,
    ProtocolError,
    json_bytes,
    strict_json,
)
from backend.trading.simulator import PaperSimulator, SimulatedCrash
from tests.risk_fixtures import inputs


def fixture():
    proposal, account, market, config = inputs()
    now = datetime.now(UTC)
    identity = account.account.model_copy(update={"broker_server": "TRD-PAPER-SIMULATOR"})
    profile = PaperProfile(
        account_id=uuid4(),
        account=identity,
        bridge_id="local",
        instance_id="executor",
        source_ids=(proposal.source_id,),
        instruments=market.instruments,
        mappings=config.allowed_instruments,
        calendar=config.calendar,
    )
    snapshot = PaperSnapshot(
        snapshot_id=uuid4(),
        account=identity,
        observed_at=now,
        currency="USD",
        equity="10000",
        free_margin="10000",
        broker_leverage="100",
        position_mode="hedging",
        history_complete=True,
        portfolio_complete=True,
        opening_equity="10000",
        net_cash_flow="0",
        positions=(),
        quotes=tuple(q.model_copy(update={"observed_at": now}) for q in market.quotes),
        instruments=tuple(i.model_copy(update={"observed_at": now}) for i in market.instruments),
    )
    command = PaperCommand(
        command_id=uuid4(),
        trace_id=uuid4(),
        approval_id=uuid4(),
        reservation_id=uuid4(),
        account_id=profile.account_id,
        account=identity,
        bridge_id=profile.bridge_id,
        instance_id=profile.instance_id,
        generation=1,
        profile_hash=profile.digest,
        safety_epoch=1,
        policy_version=1,
        signal_id=proposal.signal_id,
        signal_version=1,
        source_id=proposal.source_id,
        source_version=1,
        symbol="EURUSD.paper",
        side="BUY",
        volume="0.08",
        stop_loss="1.09500",
        take_profit="1.11000",
        price_band_low="1.09990",
        price_band_high="1.10010",
        max_spread_points="20",
        max_deviation_points="20",
        max_risk="50",
        expires_at=now + timedelta(seconds=30),
    )
    return profile, snapshot, command


REQUEST_KEY = bytes.fromhex("33" * 32)
RESPONSE_KEY = bytes.fromhex("44" * 32)
ORIGIN = "http://127.0.0.1:12345"


def simulator(directory, profile, transport=None):
    return PaperSimulator(
        profile, REQUEST_KEY, RESPONSE_KEY, directory, ORIGIN, transport=transport
    )


def test_duplicate_delivery_never_calls_non_idempotent_broker_twice(tmp_path):
    profile, snapshot, command = fixture()
    sim = simulator(tmp_path, profile)
    payload = json_bytes(command)
    digest = sha256(payload).hexdigest()
    try:
        assert sim.accept(payload, digest, snapshot, 1) == "FILLED"
        assert sim.accept(payload, digest, snapshot, 1) == "FILLED"
        assert sim.broker.db.execute("SELECT count(*) FROM broker_orders").fetchone()[0] == 1
        changed = json_bytes(command.model_dump(mode="json") | {"volume": "0.09"})
        with pytest.raises(ProtocolError):
            sim.accept(changed, sha256(changed).hexdigest(), snapshot, 1)
    finally:
        sim.close()


def test_preexisting_send_intent_cannot_be_claimed_again(tmp_path):
    profile, snapshot, command = fixture()
    sim = simulator(tmp_path, profile)
    payload = json_bytes(command)
    digest = sha256(payload).hexdigest()
    try:
        assert sim.accept(payload, digest, snapshot, 1) == "FILLED"
        with pytest.raises(ProtocolError, match="SEND_INTENT_ALREADY_CLAIMED"):
            sim.execute_received(command, digest, snapshot, 1)
        assert sim.broker.db.execute("SELECT count(*) FROM broker_orders").fetchone()[0] == 1
    finally:
        sim.close()


@pytest.mark.parametrize("crash,expected", [("after_intent", "UNKNOWN"), ("after_fill", "FILLED")])
def test_restart_after_intent_or_fill_does_not_blindly_resend(tmp_path, crash, expected):
    profile, snapshot, command = fixture()
    sim = simulator(tmp_path, profile)
    payload = json_bytes(command)
    digest = sha256(payload).hexdigest()
    try:
        with pytest.raises(SimulatedCrash):
            sim.accept(payload, digest, snapshot, 1, crash=crash)
    finally:
        sim.close()
    resumed = simulator(tmp_path, profile)
    try:
        resumed.recover()
        assert resumed.db.execute("SELECT state FROM commands").fetchone()[0] == expected
        assert resumed.broker.db.execute("SELECT count(*) FROM broker_orders").fetchone()[0] == (
            expected == "FILLED"
        )
        resumed.accept(payload, digest, snapshot, 1)
        resumed.recover()
        assert resumed.broker.db.execute("SELECT count(*) FROM broker_orders").fetchone()[0] == (
            expected == "FILLED"
        )
        kinds = [
            strict_json(r[0])["kind"] for r in resumed.db.execute("SELECT payload FROM events")
        ]
        assert kinds == [
            "RECEIVED",
            "SEND_INTENT",
            "UNKNOWN" if expected == "UNKNOWN" else "RECONCILED_FILL",
        ]
    finally:
        resumed.close()


def test_single_owner_and_journal_binding_survive_restart(tmp_path):
    profile, _, _ = fixture()
    sim = simulator(tmp_path, profile)
    try:
        with pytest.raises(ProtocolError, match="EXECUTOR_ALREADY_RUNNING"):
            simulator(tmp_path, profile)
    finally:
        sim.close()
    with pytest.raises(ProtocolError, match="JOURNAL_BINDING_MISMATCH"):
        simulator(tmp_path, profile.model_copy(update={"instance_id": "other"}))


@pytest.mark.parametrize(
    "field,value",
    [
        ("safety_epoch", 2),
        ("generation", 2),
        ("instance_id", "wrong"),
        ("volume", "1"),
        ("volume", "0.001"),
        ("stop_loss", "1.2"),
        ("take_profit", "1.0"),
        ("max_risk", "1"),
        ("max_deviation_points", "0"),
        ("profile_hash", "0" * 64),
    ],
)
def test_executor_rechecks_immutable_economics(tmp_path, field, value):
    profile, snapshot, command = fixture()
    payload = json_bytes(command.model_dump(mode="json") | {field: value})
    sim = simulator(tmp_path, profile)
    try:
        assert sim.accept(payload, sha256(payload).hexdigest(), snapshot, 1) == "REJECTED"
        assert sim.broker.db.execute("SELECT count(*) FROM broker_orders").fetchone()[0] == 0
    finally:
        sim.close()


@pytest.mark.parametrize(
    "origin",
    [
        "https://127.0.0.1:12345",
        "http://localhost:12345",
        "http://example.test:12345",
        "http://127.0.0.1:12345/path",
    ],
)
def test_only_fixed_numeric_loopback(tmp_path, origin):
    profile, _, _ = fixture()
    with pytest.raises(ValueError):
        PaperSimulator(profile, REQUEST_KEY, RESPONSE_KEY, tmp_path, origin)


def test_stale_wrong_sequence_or_unsigned_response_never_reaches_broker(tmp_path):
    profile, _, _ = fixture()

    def handler(request):
        envelope = Envelope.verify(
            request.headers,
            REQUEST_KEY,
            request.content,
            request.url.path,
            now=int(datetime.now(UTC).timestamp()),
        )
        response = Envelope(
            envelope.environment,
            envelope.bridge,
            envelope.instance,
            envelope.key,
            envelope.sequence + 1,
            envelope.issued,
            envelope.expires,
        )
        body = b'{"command":null}'
        return httpx.Response(
            200,
            content=body,
            headers=response.headers(
                RESPONSE_KEY, body, request.url.path, direction="RESPONSE", status=200
            ),
        )

    sim = simulator(tmp_path, profile, httpx.MockTransport(handler))
    try:
        with pytest.raises(ProtocolError):
            sim.request("/bridge/v1/poll", {})
        assert sim.broker.db.execute("SELECT count(*) FROM broker_orders").fetchone()[0] == 0
    finally:
        sim.close()
