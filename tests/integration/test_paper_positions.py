"""Confirmed position management against PostgreSQL with authentic local sessions."""

from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError

from backend.api.factory import create_bridge_app
from backend.domain.bridge import json_bytes, strict_json
from backend.infrastructure.bridge_models import BridgeBaseline, BridgeEnrollment
from backend.infrastructure.domain_models import (
    ExecutionCommand,
    Position,
    PositionEvent,
    TradingAccount,
)
from backend.infrastructure.position_models import PaperOperation, PaperPositionState
from backend.trading.simulator import PaperSimulator, SimulatedCrash
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


def executor(paper, directory):
    def transport(request):
        response = paper.client.post(
            request.url.path, content=request.content, headers=dict(request.headers)
        )
        return httpx.Response(
            response.status_code, content=response.content, headers=dict(response.headers)
        )

    return PaperSimulator(
        paper.profile,
        paper.request_key,
        paper.response_key,
        directory,
        "http://127.0.0.1:12345",
        transport=httpx.MockTransport(transport),
    )


def open_position(paper, sim):
    paper.emit_signal()
    assert sim.cycle(paper.snapshot()) == "DELIVERED"
    with paper.operator.connect() as c:
        return c.scalar(select(Position.id))


def test_authenticated_stop_change_full_close_and_history(paper, tmp_path):
    sim = executor(paper, tmp_path / "executor")
    try:
        position = open_position(paper, sim)
        paper.operator_request("MODIFY_STOPS", position, stop_loss="1.09700", take_profit="1.11000")
        assert sim.cycle(paper.snapshot()) == "DELIVERED"
        assert sim.broker.positions()[0].stop_loss == Decimal("1.09700")
        paper.operator_request("CLOSE", position)
        assert sim.cycle(paper.snapshot()) == "DELIVERED"
        assert not sim.broker.positions()
        assert sim.cycle(paper.snapshot()) == "NO_COMMAND"
        close_event = next(
            strict_json(r[0])
            for r in sim.db.execute("SELECT payload FROM events")
            if strict_json(r[0])["kind"] == "POSITION_CLOSED"
        )
        close_event["event_id"] = str(uuid4())
        assert sim.request("/bridge/v1/events", {"events": [close_event]})["accepted"] == [
            close_event["event_id"]
        ]
        rows = paper.admin_client.get("/ops/positions").json()["rows"]
        assert rows[0]["status"] == "CLOSED"
        assert rows[0]["volume"] == "0.0000000000"
        assert Decimal(rows[0]["realized_pnl"]) == sim.broker.realized_pnl(paper.profile) < 0
        assert rows[0]["revision"] == 3
        with paper.operator.connect() as c:
            assert c.scalar(select(BridgeBaseline.opening_equity)) == Decimal("10000")
            assert c.scalars(select(PaperOperation.state)).all() == ["COMPLETED", "COMPLETED"]
            assert len(c.scalars(select(PositionEvent.id)).all()) == 2
    finally:
        sim.close()


@pytest.mark.parametrize("action", ["CLOSE", "MODIFY_STOPS"])
@pytest.mark.parametrize("crash", ["after_intent", "after_fill"])
def test_management_restart_and_unknown_retention(paper, tmp_path, action, crash):
    directory = tmp_path / "executor"
    sim = executor(paper, directory)
    position = open_position(paper, sim)
    levels = {"stop_loss": "1.09700", "take_profit": "1.11000"} if action == "MODIFY_STOPS" else {}
    paper.operator_request(action, position, **levels)
    try:
        with pytest.raises(SimulatedCrash):
            sim.cycle(paper.snapshot(), crash=crash)
    finally:
        sim.close()
    resumed = executor(paper, directory)
    try:
        assert resumed.cycle(paper.snapshot()) in {"NO_COMMAND", "RECONCILING"}
        assert resumed.broker.db.execute("SELECT count(*) FROM position_operations").fetchone()[
            0
        ] == (crash == "after_fill")
        with paper.operator.connect() as c:
            assert c.scalar(select(PaperOperation.state)) == (
                "COMPLETED" if crash == "after_fill" else "UNKNOWN"
            )
            if crash == "after_intent":
                assert c.scalar(select(Position.volume)) > 0
                assert c.scalar(select(Position.status)) == "OUTCOME_UNKNOWN"
                assert c.scalar(select(TradingAccount.status)) == "RECONCILING"
        if crash == "after_intent":
            with pytest.raises(RuntimeError, match="local operator request failed"):
                paper.operator_request("RESUME")
            assert resumed.cycle(paper.snapshot()) == "RECONCILING"
    finally:
        resumed.close()


def test_risk_increasing_stop_rejected_and_close_allowed_while_paused(paper, tmp_path):
    sim = executor(paper, tmp_path / "executor")
    try:
        position = open_position(paper, sim)
        paper.operator_request("MODIFY_STOPS", position, stop_loss="1.09000", take_profit="1.11000")
        assert sim.cycle(paper.snapshot()) == "POSITION_RISK_INCREASE"
        assert sim.broker.db.execute("SELECT count(*) FROM position_operations").fetchone()[0] == 0
        with paper.operator.begin() as c:
            c.execute(update(TradingAccount).values(status="PAUSED"))
        paper.operator_request("CLOSE", position)
        assert sim.cycle(paper.snapshot()) == "DELIVERED"
        assert not sim.broker.positions()
        assert sim.cycle(paper.snapshot()) == "PAUSED"
        paper.operator_request("RESUME")
        assert sim.cycle(paper.snapshot()) == "RESUMED"
        with paper.operator.connect() as c:
            assert c.scalar(select(TradingAccount.status)) == "READY"
            assert c.scalar(select(TradingAccount.safety_epoch)) == 2
    finally:
        sim.close()


def test_resume_never_clears_daily_loss_or_baseline(paper, tmp_path):
    sim = executor(paper, tmp_path / "executor")
    try:
        assert sim.cycle(paper.snapshot(equity="9800")) == "PAUSED"
        paper.operator_request("RESUME")
        assert sim.cycle(paper.snapshot()) == "DAILY_LOSS_STILL_BLOCKED"
        with paper.operator.connect() as c:
            assert c.scalar(select(BridgeBaseline.loss_latched)) is True
            assert c.scalar(select(BridgeBaseline.opening_equity)) == Decimal("10000")
    finally:
        sim.close()


def test_fault_resume_requires_explicit_confirmed_flat_reconciliation(paper, tmp_path):
    sim = executor(paper, tmp_path / "executor")
    try:
        sim.cycle(paper.snapshot())
        with paper.operator.begin() as c:
            c.execute(update(BridgeEnrollment).values(fault_latched=True))
            c.execute(update(TradingAccount).values(status="RECONCILING"))
        assert sim.cycle(paper.snapshot()) == "RECONCILING"
        paper.operator_request("RESUME")
        assert sim.cycle(paper.snapshot()) == "RESUMED"
        with paper.operator.connect() as c:
            assert c.scalar(select(BridgeEnrollment.fault_latched)) is False
    finally:
        sim.close()


def test_confirmation_cannot_be_reused_and_viewer_cannot_request(paper, tmp_path):
    sim = executor(paper, tmp_path / "executor")
    try:
        position = open_position(paper, sim)
        paper.operator_request("CLOSE", position)
        change = {
            "kind": "paper_position",
            "target": str(position),
            "expected_version": 1,
            "value": {"action": "CLOSE", "stop_loss": None, "take_profit": None},
        }
        headers = {
            "Origin": "http://localhost:3000",
            "X-CSRF-Token": paper.admin_client.get("/auth/me").json()["csrf_token"],
        }
        confirm = paper.admin_client.post("/config/confirm", json=change, headers=headers).json()
        assert (
            paper.admin_client.post(
                "/config/apply",
                json={
                    "change": confirm["change"],
                    "confirmation_token": confirm["confirmation_token"],
                },
                headers=headers,
            ).status_code
            == 409
        )
        with paper.operator.begin() as c:
            c.execute(
                text(
                    "UPDATE public.users SET role='VIEWER' "
                    "WHERE email='paper-operator@example.test'"
                )
            )
        assert (
            paper.admin_client.post("/config/confirm", json=change, headers=headers).status_code
            == 403
        )
    finally:
        sim.close()


def test_stale_position_revision_invalidates_request(paper, tmp_path):
    sim = executor(paper, tmp_path / "executor")
    try:
        position = open_position(paper, sim)
        paper.operator_request("CLOSE", position)
        with paper.operator.begin() as c:
            c.execute(update(PaperPositionState).values(revision=2))
        assert sim.cycle(paper.snapshot()) == "POSITION_STATE_CHANGED"
        assert sim.broker.positions()
    finally:
        sim.close()


@pytest.mark.parametrize(
    "role", ["trd_api", "trd_ai", "trd_collector", "trd_maintenance", "trd_risk"]
)
def test_runtime_cannot_forge_operator_request(paper, role):
    with paper.engines[role].begin() as c:
        with pytest.raises(DBAPIError):
            c.execute(
                text(
                    "INSERT INTO public.paper_operations(environment_id,id,account_id,actor_id,"
                    "action,expected_revision,safety_epoch,value,expires_at) "
                    "VALUES('test',:id,:account,:actor,'RESUME',1,1,'{}',"
                    "clock_timestamp()+interval '1 minute')"
                ),
                {"id": uuid4(), "account": paper.account_id, "actor": uuid4()},
            )


def test_conflicting_close_retains_exposure_then_correct_evidence_and_explicit_resume(
    paper, tmp_path
):
    from base64 import b64decode

    from backend.domain.bridge import ProtocolError

    sim = executor(paper, tmp_path / "executor")
    try:
        position = open_position(paper, sim)
        paper.operator_request("CLOSE", position)
        snapshot = paper.snapshot(positions=sim.broker.positions())
        sim.request("/bridge/v1/snapshot", snapshot)
        reply = sim.request("/bridge/v1/poll", {})
        sim.accept(
            b64decode(reply["command"]), reply["command_hash"], snapshot, reply["safety_epoch"]
        )
        close = next(
            r
            for r in sim.db.execute("SELECT * FROM events WHERE acknowledged=0").fetchall()
            if strict_json(r["payload"])["kind"] == "POSITION_CLOSED"
        )
        tampered = strict_json(close["payload"])
        tampered["volume"] = "0.01"
        sim.db.execute(
            "UPDATE events SET payload=? WHERE event_id=?",
            (json_bytes(tampered), close["event_id"]),
        )
        with pytest.raises(ProtocolError):
            sim.flush_events()
        with paper.operator.connect() as c:
            assert c.scalar(select(Position.volume)) > 0
            assert c.scalar(select(Position.status)) == "OUTCOME_UNKNOWN"
            assert c.scalar(select(BridgeEnrollment.fault_latched)) is True
            assert not c.scalars(
                select(PositionEvent.id).where(PositionEvent.event_type == "PAPER_CLOSE")
            ).all()
        sim.db.execute(
            "UPDATE events SET payload=? WHERE event_id=?", (close["payload"], close["event_id"])
        )
        sim.flush_events()
        assert sim.cycle(paper.snapshot()) == "RECONCILING"
        paper.operator_request("RESUME")
        assert sim.cycle(paper.snapshot()) == "RESUMED"
        with paper.operator.connect() as c:
            assert c.scalar(select(Position.status)) == "CLOSED"
            assert (
                len(
                    c.scalars(
                        select(PositionEvent.id).where(PositionEvent.event_type == "PAPER_CLOSE")
                    ).all()
                )
                == 1
            )
    finally:
        sim.close()


def test_runtime_cannot_create_unreserved_open_command(paper, tmp_path):
    from datetime import UTC, datetime, timedelta
    from hashlib import sha256

    from sqlalchemy import insert

    from tests.unit.test_paper_simulator import fixture

    _, _, command = fixture()
    payload = json_bytes(command)
    with paper.engines["trd_risk"].begin() as c:
        with pytest.raises(DBAPIError):
            c.execute(
                insert(ExecutionCommand).values(
                    environment_id=paper.env,
                    id=command.command_id,
                    account_id=paper.account_id,
                    reservation_id=None,
                    trace_id=command.trace_id,
                    payload=payload,
                    payload_hash=sha256(payload).hexdigest(),
                    expires_at=datetime.now(UTC) + timedelta(seconds=30),
                )
            )
