"""Paper protocol acceptance against real PostgreSQL, with separate runtime roles."""

from base64 import b64decode
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Event
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text, update

from backend.ai.providers import MockProvider
from backend.api.factory import create_bridge_app
from backend.domain.bridge import (
    Envelope,
    PaperCommand,
    PaperEvent,
    PaperEvents,
    PaperPosition,
    json_bytes,
    strict_json,
)
from backend.domain.config import BridgeSettings
from backend.infrastructure.bridge_models import (
    BridgeBaseline,
    BridgeEnrollment,
    BridgeRequest,
    PaperCommandRecord,
)
from backend.infrastructure.domain_models import (
    ExecutionCommand,
    Order,
    Position,
    PositionEvent,
    RiskApproval,
    RiskReservation,
    Signal,
    TelegramSource,
    TradingAccount,
)
from backend.trading.gateway import _AccountTransaction
from backend.trading.simulator import PaperSimulator
from infra.scripts.paper_scenarios import LocalPaperScenario

pytestmark = pytest.mark.integration


@pytest.fixture
def paper(isolated_database, tmp_path):
    scenario = LocalPaperScenario(isolated_database.urls, tmp_path)
    with TestClient(
        create_bridge_app(scenario.settings, lambda _: True, engine=scenario.engines["trd_risk"])
    ) as client:
        scenario.client = client
        yield scenario
    scenario.close()


def exchange(paper, sequence, path, value, *, body=None, envelope=None):
    body = json_bytes(value) if body is None else body
    now = int(datetime.now(UTC).timestamp())
    p = paper.profile
    envelope = envelope or Envelope(
        "test", p.bridge_id, p.instance_id, p.key_id, sequence, now, now + 10
    )
    response = paper.client.post(
        path, content=body, headers=envelope.headers(paper.request_key, body, path)
    )
    if response.status_code == 503:
        # Surface the transaction failure in isolated tests; HTTP intentionally redacts it.
        paper.client.app.state.paper_gateway.handle(
            envelope.headers(paper.request_key, body, path), path, body
        )
    if "x-trd-signature" in response.headers:
        Envelope.verify(
            response.headers,
            paper.response_key,
            response.content,
            path,
            now=int(datetime.now(UTC).timestamp()),
            direction="RESPONSE",
            status=response.status_code,
            expected=envelope,
        )
    return response


def delivered(paper):
    paper.emit_signal()
    assert exchange(paper, 1, "/bridge/v1/snapshot", paper.snapshot()).status_code == 200
    response = exchange(paper, 2, "/bridge/v1/poll", {})
    assert response.status_code == 200, response.text
    result = strict_json(response.content)
    assert result["status"] == "DELIVERED", result
    payload = b64decode(result["command"])
    return PaperCommand.model_validate(strict_json(payload)), result["command_hash"], response


def test_reserve_revalidate_delivery_and_ack_not_fill(paper):
    command, digest, _ = delivered(paper)
    with paper.operator.connect() as c:
        assert c.scalar(select(RiskApproval.risk_amount)) == command.max_risk
        assert c.scalar(select(RiskReservation.status)) == "HELD"
        assert c.scalar(select(ExecutionCommand.state)) == "DELIVERED"
        assert c.scalar(select(Order.filled_volume)) == 0
    event = PaperEvent(
        event_id=uuid4(),
        command_id=command.command_id,
        command_hash=digest,
        kind="RECEIVED",
        observed_at=datetime.now(UTC),
    )
    response = exchange(paper, 3, "/bridge/v1/events", PaperEvents(events=(event,)))
    with paper.operator.connect() as c:
        details = (
            c.execute(text("SELECT details FROM audit_events WHERE action='PAPER_BRIDGE_FAULT'"))
            .scalars()
            .all()
        )
    assert response.status_code == 200, details
    with paper.operator.connect() as c:
        assert c.scalar(select(ExecutionCommand.state)) == "ACKNOWLEDGED"
        assert c.scalar(select(Order.filled_volume)) == 0
        assert c.scalar(select(RiskReservation.status)) == "HELD"


def test_full_simulated_pipeline_and_duplicate_cycle(paper, tmp_path):
    def transport(request):
        response = paper.client.request(
            request.method, request.url.path, content=request.content, headers=dict(request.headers)
        )
        return httpx.Response(
            response.status_code, content=response.content, headers=response.headers
        )

    paper.emit_signal()
    sim = PaperSimulator(
        paper.profile,
        paper.request_key,
        paper.response_key,
        tmp_path / "executor",
        "http://127.0.0.1:12345",
        transport=httpx.MockTransport(transport),
    )
    try:
        assert sim.cycle(paper.snapshot()) == "DELIVERED"
        assert sim.cycle(paper.snapshot()) == "NO_COMMAND"
        assert sim.broker.db.execute("SELECT count(*) FROM broker_orders").fetchone()[0] == 1
        with paper.operator.connect() as c:
            assert c.scalar(select(ExecutionCommand.state)) == "COMPLETED"
            assert c.scalar(select(Signal.state)) == "EXECUTED"
            assert c.scalar(select(Order.state)) == "FILLED"
            assert c.scalar(select(RiskReservation.status)) == "CONSUMED"
            assert c.scalar(select(Position.volume)) > Decimal(0)
    finally:
        sim.close()


def test_exact_retry_reuses_original_response_and_no_second_approval(paper):
    paper.emit_signal()
    exchange(paper, 1, "/bridge/v1/snapshot", paper.snapshot())
    now = int(datetime.now(UTC).timestamp())
    envelope = Envelope(
        "test",
        paper.profile.bridge_id,
        paper.profile.instance_id,
        paper.profile.key_id,
        2,
        now,
        now + 10,
    )
    first = exchange(paper, 2, "/bridge/v1/poll", {}, envelope=envelope)
    second = exchange(paper, 2, "/bridge/v1/poll", {}, envelope=envelope)
    assert (
        first.content == second.content
        and first.headers["x-trd-signature"] == second.headers["x-trd-signature"]
    )
    assert exchange(paper, 3, "/bridge/v1/poll", {}).json()["command"] is None
    with paper.operator.connect() as c:
        assert len(c.scalars(select(RiskApproval.id)).all()) == 1
        assert c.scalar(select(RiskReservation.status)) == "HELD"


def test_signed_replay_conflict_latches_and_keeps_delivered_risk(paper):
    _, _, _ = delivered(paper)
    conflict = exchange(paper, 2, "/bridge/v1/poll", {}, body=b"{ }")
    assert conflict.status_code == 409
    with paper.operator.connect() as c:
        assert c.scalar(select(BridgeEnrollment.fault_latched))
        assert c.scalar(select(ExecutionCommand.state)) == "RECONCILING"
        assert c.scalar(select(RiskReservation.status)) == "OUTCOME_UNKNOWN"


def test_partial_fills_and_independent_deal_deduplication(paper):
    command, digest, _ = delivered(paper)
    first_volume = Decimal("0.01")
    event = PaperEvent(
        event_id=uuid4(),
        command_id=command.command_id,
        command_hash=digest,
        kind="FILL",
        observed_at=datetime.now(UTC),
        broker_ticket="9007199254740993",
        broker_deal_id="9007199254740994",
        position_identifier="9007199254740995",
        volume=first_volume,
        price="1.10000",
    )
    assert exchange(paper, 3, "/bridge/v1/events", PaperEvents(events=(event,))).status_code == 200
    duplicate = event.model_copy(update={"event_id": uuid4()})
    assert (
        exchange(paper, 4, "/bridge/v1/events", PaperEvents(events=(duplicate,))).status_code == 200
    )
    with paper.operator.connect() as c:
        assert c.scalar(select(Order.filled_volume)) == first_volume
        assert c.scalar(select(Order.state)) == "PARTIALLY_FILLED"
        assert c.scalar(select(RiskReservation.status)) == "HELD"
        assert 0 < c.scalar(select(PaperCommandRecord.remaining_risk)) < command.max_risk
    final = event.model_copy(
        update={
            "event_id": uuid4(),
            "broker_deal_id": "9007199254740996",
            "volume": command.volume - first_volume,
        }
    )
    assert exchange(paper, 5, "/bridge/v1/events", PaperEvents(events=(final,))).status_code == 200
    ack = PaperEvent(
        event_id=uuid4(),
        command_id=command.command_id,
        command_hash=digest,
        kind="RECEIVED",
        observed_at=datetime.now(UTC),
    )
    assert exchange(paper, 6, "/bridge/v1/events", PaperEvents(events=(ack,))).status_code == 200
    with paper.operator.connect() as c:
        assert c.scalar(select(Order.filled_volume)) == command.volume
        assert c.scalar(select(ExecutionCommand.state)) == "COMPLETED"
        assert c.scalar(select(Position.volume)) == command.volume
        assert c.scalar(select(PaperCommandRecord.remaining_risk)) == 0


def test_unknown_is_retained_and_only_fill_plus_snapshot_restores_readiness(paper):
    command, digest, _ = delivered(paper)
    unknown = PaperEvent(
        event_id=uuid4(),
        command_id=command.command_id,
        command_hash=digest,
        kind="UNKNOWN",
        observed_at=datetime.now(UTC),
    )
    assert (
        exchange(paper, 3, "/bridge/v1/events", PaperEvents(events=(unknown,))).status_code == 200
    )
    assert exchange(paper, 4, "/bridge/v1/poll", {}).json()["status"] == "RECONCILING"
    with paper.operator.connect() as c:
        assert c.scalar(select(RiskReservation.status)) == "OUTCOME_UNKNOWN"
        assert c.scalar(select(PaperCommandRecord.remaining_risk)) == command.max_risk
    fill = PaperEvent(
        event_id=uuid4(),
        command_id=command.command_id,
        command_hash=digest,
        kind="RECONCILED_FILL",
        observed_at=datetime.now(UTC),
        broker_ticket="1",
        broker_deal_id="1",
        position_identifier="1",
        volume=command.volume,
        price="1.10000",
    )
    assert exchange(paper, 5, "/bridge/v1/events", PaperEvents(events=(fill,))).status_code == 200
    with paper.operator.connect() as c:
        assert c.scalar(select(TradingAccount.status)) == "RECONCILING"
    position = PaperPosition(
        broker_identifier="1",
        command_id=command.command_id,
        symbol=command.symbol,
        side=command.side,
        volume=command.volume,
        entry_price="1.10000",
        stop_loss=command.stop_loss,
        take_profit=command.take_profit,
    )
    assert (
        exchange(paper, 6, "/bridge/v1/snapshot", paper.snapshot(positions=(position,))).json()[
            "status"
        ]
        == "READY"
    )


def stage_ready(paper):
    paper.emit_signal()
    snapshot = paper.snapshot()
    assert exchange(paper, 1, "/bridge/v1/snapshot", snapshot).status_code == 200
    with paper.engines["trd_risk"].begin() as c:
        work = _AccountTransaction(paper.client.app.state.paper_gateway, c)
        work.lock()
        work.admit(snapshot)
    with paper.operator.connect() as c:
        assert c.scalar(select(ExecutionCommand.state)) == "READY"


@pytest.mark.parametrize("change", ["pause", "epoch", "source"])
def test_authority_change_invalidates_unsent_and_releases_only_its_hold(paper, change):
    stage_ready(paper)
    with paper.operator.begin() as c:
        if change in {"pause", "epoch"}:
            values = {"status": "PAUSED"} if change == "pause" else {"safety_epoch": 2}
            c.execute(update(TradingAccount).values(**values))
        else:
            c.execute(update(TelegramSource).values(enabled=False, version=2))
    result = exchange(paper, 2, "/bridge/v1/poll", {})
    assert result.status_code == 200 and result.json()["command"] is None
    with paper.operator.connect() as c:
        assert c.scalar(select(ExecutionCommand.state)) == "INVALIDATED"
        assert c.scalar(select(RiskReservation.status)) == "RELEASED"
        assert c.scalar(select(Order.state)) == "EXPIRED"


@pytest.mark.parametrize("adjustment", ["500", "-500"])
def test_unsupported_cash_flow_cannot_rewrite_daily_loss(paper, adjustment):
    snapshot = paper.snapshot().model_copy(update={"net_cash_flow": Decimal(adjustment)})
    assert exchange(paper, 1, "/bridge/v1/snapshot", snapshot).status_code == 409
    with paper.operator.connect() as c:
        assert c.scalar(select(BridgeEnrollment.fault_latched)) is True
        assert c.scalar(select(RiskApproval.id)) is None


def test_daily_loss_latch_survives_equity_recovery(paper):
    paper.emit_signal()
    assert (
        exchange(paper, 1, "/bridge/v1/snapshot", paper.snapshot(equity="9800")).status_code == 200
    )
    assert exchange(paper, 2, "/bridge/v1/snapshot", paper.snapshot()).status_code == 200
    assert exchange(paper, 3, "/bridge/v1/poll", {}).json()["command"] is None
    with paper.operator.connect() as c:
        assert c.scalar(select(BridgeBaseline.loss_latched))
        assert c.scalar(select(TradingAccount.status)) == "PAUSED"
        assert c.scalar(select(text("count(*)")).select_from(RiskApproval)) == 0


def test_concurrent_polls_cannot_overbook_account(paper):
    for _ in range(3):
        paper.emit_signal()
    exchange(paper, 1, "/bridge/v1/snapshot", paper.snapshot())
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(
            pool.map(lambda sequence: exchange(paper, sequence, "/bridge/v1/poll", {}), (2, 3))
        )
    assert any(r.status_code == 200 and r.json().get("command") for r in responses)
    for sequence in (4, 5):
        assert exchange(paper, sequence, "/bridge/v1/poll", {}).status_code == 200
    with paper.operator.connect() as c:
        assert len(c.scalars(select(ExecutionCommand.id)).all()) == 2
        assert sum(c.scalars(select(RiskReservation.risk_amount)).all()) <= Decimal("100")


def test_lock_contention_does_not_extend_signature_validity(paper, monkeypatch):
    paper.emit_signal()
    exchange(paper, 1, "/bridge/v1/snapshot", paper.snapshot())
    entered = Event()
    original = _AccountTransaction.lock

    def waiting(work):
        entered.set()
        original(work)

    monkeypatch.setattr(_AccountTransaction, "lock", waiting)
    p = paper.profile
    now = int(datetime.now(UTC).timestamp())
    envelope = Envelope("test", p.bridge_id, p.instance_id, p.key_id, 2, now, now + 2)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with paper.operator.begin() as blocker:
            blocker.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended('trd-evidence:test',0))")
            )
            pending = pool.submit(exchange, paper, 2, "/bridge/v1/poll", {}, envelope=envelope)
            assert entered.wait(2)
            blocker.execute(text("SELECT pg_sleep(2.1)"))
            assert not pending.done()
        assert pending.result(timeout=5).status_code == 401
    with paper.operator.connect() as c:
        assert c.scalar(select(RiskApproval.id)) is None
        assert c.scalar(select(BridgeEnrollment.highwater)) == 1


def test_database_failure_rolls_back_approval_command_and_outbox(paper):
    paper.emit_signal()
    exchange(paper, 1, "/bridge/v1/snapshot", paper.snapshot())
    with paper.operator.begin() as c:
        c.execute(
            text(
                "CREATE FUNCTION public.paper_test_failure() RETURNS trigger LANGUAGE plpgsql "
                "AS $$ BEGIN RAISE EXCEPTION 'injected failure'; END $$"
            )
        )
        c.execute(
            text(
                "CREATE TRIGGER paper_test_failure BEFORE INSERT ON public.orders "
                "FOR EACH ROW EXECUTE FUNCTION public.paper_test_failure()"
            )
        )
    now = int(datetime.now(UTC).timestamp())
    envelope = Envelope(
        "test",
        paper.profile.bridge_id,
        paper.profile.instance_id,
        paper.profile.key_id,
        2,
        now,
        now + 10,
    )
    response = paper.client.post(
        "/bridge/v1/poll",
        content=b"{}",
        headers=envelope.headers(paper.request_key, b"{}", "/bridge/v1/poll"),
    )
    assert response.status_code == 503
    with paper.operator.connect() as c:
        assert c.scalar(select(text("count(*)")).select_from(RiskApproval)) == 0
        assert c.scalar(select(text("count(*)")).select_from(ExecutionCommand)) == 0
        assert c.scalar(select(Signal.state)) == "WAITING"
        assert c.scalar(select(BridgeEnrollment.highwater)) == 1


def test_unauthenticated_tamper_and_disabled_bridge_never_write(paper):
    assert (
        paper.client.post(
            "/bridge/v1/poll", content=b"{}", headers={"content-type": "application/json"}
        ).status_code
        == 401
    )
    settings = BridgeSettings(
        environment_id="test", app_env="test", database_url=paper.urls["trd_risk"]
    )
    with TestClient(create_bridge_app(settings, lambda _: True)) as disabled:
        assert disabled.post("/bridge/v1/poll", json={}).status_code == 404
    with paper.operator.connect() as c:
        assert c.scalar(select(text("count(*)")).select_from(BridgeRequest)) == 0
        assert c.scalar(select(BridgeEnrollment.journal_id)) is None


def test_conflicting_fill_batch_rolls_back_economics_and_retains_full_risk(paper):
    command, digest, _ = delivered(paper)
    valid = PaperEvent(
        event_id=uuid4(),
        command_id=command.command_id,
        command_hash=digest,
        kind="FILL",
        observed_at=datetime.now(UTC),
        broker_ticket="1",
        broker_deal_id="1",
        position_identifier="1",
        volume="0.01",
        price="1.10000",
    )
    invalid = valid.model_copy(
        update={"event_id": uuid4(), "broker_deal_id": "2", "volume": command.volume}
    )
    assert (
        exchange(paper, 3, "/bridge/v1/events", PaperEvents(events=(valid, invalid))).status_code
        == 409
    )
    with paper.operator.connect() as c:
        assert c.scalar(select(text("count(*)")).select_from(PositionEvent)) == 0
        assert c.scalar(select(text("count(*)")).select_from(Position)) == 0
        assert c.scalar(select(Order.filled_volume)) == 0
        assert c.scalar(select(RiskReservation.status)) == "OUTCOME_UNKNOWN"
        assert c.scalar(select(PaperCommandRecord.remaining_risk)) == command.max_risk


def test_expiry_after_delivery_is_uncertainty_and_never_release(paper):
    delivered(paper)
    with paper.engines["trd_risk"].begin() as c:
        work = _AccountTransaction(paper.client.app.state.paper_gateway, c)
        work.lock()
        work.now += timedelta(seconds=31)
        assert work.poll()["status"] == "RECONCILING"
    with paper.operator.connect() as c:
        assert c.scalar(select(ExecutionCommand.state)) == "RECONCILING"
        assert c.scalar(select(RiskReservation.status)) == "OUTCOME_UNKNOWN"


def test_default_wait_provider_cannot_create_approval(paper):
    paper.worker.provider = MockProvider()
    paper.emit_signal()
    exchange(paper, 1, "/bridge/v1/snapshot", paper.snapshot())
    assert exchange(paper, 2, "/bridge/v1/poll", {}).json()["command"] is None
    with paper.operator.connect() as c:
        assert c.scalar(select(text("count(*)")).select_from(RiskApproval)) == 0


def test_stale_quote_and_spread_cannot_create_approval(paper):
    paper.emit_signal()
    snapshot = paper.snapshot()
    snapshot = snapshot.model_copy(
        update={
            "quotes": tuple(
                q.model_copy(update={"observed_at": q.observed_at - timedelta(seconds=5)})
                for q in snapshot.quotes
            )
        }
    )
    exchange(paper, 1, "/bridge/v1/snapshot", snapshot)
    assert exchange(paper, 2, "/bridge/v1/poll", {}).json()["command"] is None
    exchange(paper, 3, "/bridge/v1/snapshot", paper.snapshot(ask="1.10100"))
    assert exchange(paper, 4, "/bridge/v1/poll", {}).json()["command"] is None
    with paper.operator.connect() as c:
        assert c.scalar(select(text("count(*)")).select_from(RiskApproval)) == 0


@pytest.mark.parametrize("role", ["api", "collector", "ai", "risk", "maintenance"])
def test_bridge_role_boundaries_and_no_runtime_enrollment(paper, role):
    with paper.engines[f"trd_{role}"].connect() as c:
        assert not c.scalar(
            text("SELECT has_table_privilege(current_user,'public.bridge_enrollments','INSERT')")
        )
        assert not c.scalar(
            text("SELECT has_table_privilege(current_user,'public.bridge_requests','DELETE')")
        )
        assert c.scalar(
            text("SELECT has_table_privilege(current_user,'public.bridge_snapshots','SELECT')")
        ) == (role == "risk")


def test_fresh_journal_cannot_take_over_enrolled_executor(paper, tmp_path):
    def transport(request):
        response = paper.client.request(
            request.method, request.url.path, content=request.content, headers=dict(request.headers)
        )
        return httpx.Response(
            response.status_code, content=response.content, headers=response.headers
        )

    sims = [
        PaperSimulator(
            paper.profile,
            paper.request_key,
            paper.response_key,
            tmp_path / directory,
            "http://127.0.0.1:12345",
            transport=httpx.MockTransport(transport),
        )
        for directory in ("first", "other")
    ]
    try:
        sims[0].request("/bridge/v1/snapshot", paper.snapshot())
        with pytest.raises(ValueError):
            sims[1].request("/bridge/v1/poll", {})
        assert sims[0].request("/bridge/v1/poll", {})["status"] == "NO_COMMAND"
        with paper.operator.connect() as c:
            assert c.scalar(select(BridgeEnrollment.journal_id)) == sims[0].journal_id
            assert not c.scalar(select(BridgeEnrollment.fault_latched))
    finally:
        for sim in sims:
            sim.close()
