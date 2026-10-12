"""Risk-owned handling of confirmed paper position requests; no new exposure."""

from base64 import b64encode
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
from uuid import uuid4

from backend.domain.bridge import (
    PaperCommand,
    PaperPositionCommand,
    ProtocolError,
    json_bytes,
    strict_json,
)
from backend.domain.position_management import position_preflight, realized_pnl
from backend.infrastructure.bridge_models import BridgeBaseline, BridgeEnrollment
from backend.infrastructure.domain_models import (
    ExecutionCommand,
    ExecutionEvent,
    Order,
    Position,
    PositionEvent,
    RiskReservation,
    TradingAccount,
)
from backend.infrastructure.position_models import (
    PaperOperation,
    PaperOperationResult,
    PaperPositionState,
)


class PositionManagement:
    def __init__(self, work):
        self.w = work

    def operation(self, command_id):
        return self.w.one(PaperOperation, PaperOperation.command_id == command_id)

    def reject(self, request, reason):
        self.w.change(
            PaperOperation, PaperOperation.id == request["id"], state="REJECTED", reason=reason
        )
        self.w.audit(
            "PAPER_OPERATION_REJECTED", {"request_id": str(request["id"]), "reason": reason}
        )
        return {"status": reason, "command": None}

    def poll(self, snapshot):
        w = self.w
        request = w.one(
            PaperOperation, PaperOperation.state == "PENDING", order=PaperOperation.created_at
        )
        if request is None:
            return None
        if request["expires_at"] <= w.now or request["safety_epoch"] != w.account["safety_epoch"]:
            return self.reject(request, "STALE_OPERATOR_REQUEST")
        if request["action"] == "RESUME":
            return self.resume(request, snapshot)
        if w.enrollment["fault_latched"]:
            return self.reject(request, "ACCOUNT_FAULT_REQUIRES_RECONCILIATION")
        position = w.one(Position, Position.id == request["position_id"])
        state = w.one(PaperPositionState, PaperPositionState.position_id == request["position_id"])
        order = w.one(Order, Order.id == position["order_id"]) if position else None
        if (
            position is None
            or state is None
            or state["revision"] != request["expected_revision"]
            or position["status"] != "OPEN"
            or order["state"] != "FILLED"
        ):
            return self.reject(request, "POSITION_STATE_CHANGED")
        opening = w.one(ExecutionCommand, ExecutionCommand.id == order["command_id"])
        original = PaperCommand.model_validate(strict_json(opening["payload"]))
        fills = w.rows(
            PositionEvent,
            PositionEvent.position_id == position["id"],
            PositionEvent.event_type == "PAPER_FILL",
        )
        entry_value = sum(
            (Decimal(e["summary"]["volume"]) * Decimal(e["summary"]["price"]) for e in fills),
            Decimal(0),
        )
        if not fills or entry_value <= 0:
            return self.reject(request, "ENTRY_EVIDENCE_MISSING")
        quote = next(q for q in snapshot.quotes if q.symbol == position["symbol"])
        instrument = next(i for i in w.p.instruments if i.symbol == position["symbol"])
        price = quote.bid if original.side == "BUY" else quote.ask
        band = w.p.max_deviation_points * instrument.point
        command = PaperPositionCommand(
            action=request["action"],
            command_id=uuid4(),
            request_id=request["id"],
            trace_id=opening["trace_id"],
            account_id=w.p.account_id,
            account=w.p.account,
            bridge_id=w.p.bridge_id,
            instance_id=w.p.instance_id,
            generation=w.p.generation,
            profile_hash=w.p.digest,
            safety_epoch=w.account["safety_epoch"],
            position_id=position["id"],
            position_revision=state["revision"],
            opening_command_id=opening["id"],
            position_identifier=position["broker_identifier"],
            symbol=position["symbol"],
            side=original.side,
            volume=position["volume"],
            entry_price=position["entry_price"],
            entry_value=entry_value,
            previous_stop_loss=state["stop_loss"],
            previous_take_profit=state["take_profit"],
            stop_loss=request["value"]["stop_loss"] or state["stop_loss"],
            take_profit=request["value"]["take_profit"] or state["take_profit"],
            price_band_low=price - band,
            price_band_high=price + band,
            max_spread_points=w.p.max_spread_points,
            max_deviation_points=w.p.max_deviation_points,
            expires_at=min(request["expires_at"], w.now + timedelta(seconds=30)),
        )
        try:
            position_preflight(command, snapshot, w.p, w.account["safety_epoch"], now=w.now)
        except ProtocolError as error:
            return self.reject(request, str(error))
        payload = json_bytes(command)
        w.add(
            ExecutionCommand,
            id=command.command_id,
            account_id=w.p.account_id,
            reservation_id=None,
            trace_id=opening["trace_id"],
            payload=payload,
            payload_hash=sha256(payload).hexdigest(),
            expires_at=command.expires_at,
        )
        w.change(
            PaperOperation,
            PaperOperation.id == request["id"],
            command_id=command.command_id,
            state="DISPATCHED",
        )
        row = w.one(ExecutionCommand, ExecutionCommand.id == command.command_id)
        w.transition("command", row, "READY")
        w.transition("command", row, "DELIVERED")
        if command.action == "CLOSE":
            w.change(Position, Position.id == position["id"], status="CLOSING")
        return {
            "status": "DELIVERED",
            "command": b64encode(payload).decode("ascii"),
            "command_hash": row["payload_hash"],
            "safety_epoch": w.account["safety_epoch"],
        }

    def resume(self, request, snapshot):
        w = self.w
        baseline = w.one(BridgeBaseline, BridgeBaseline.day == w.now.date())
        _, policy = w.policy()
        if (
            not 0 <= (w.now - snapshot.observed_at).total_seconds() < 15
            or not snapshot.history_complete
            or not snapshot.portfolio_complete
            or baseline is None
        ):
            return self.reject(request, "FRESH_RECONCILIATION_REQUIRED")
        if any(
            not q.market_open or not 0 <= (w.now - q.observed_at).total_seconds() < 5
            for q in snapshot.quotes
        ) or any(
            not 0 <= (w.now - i.observed_at).total_seconds() < 60 for i in snapshot.instruments
        ):
            return self.reject(request, "FRESH_MARKET_REQUIRED")
        if (
            baseline["loss_latched"]
            or max(Decimal(0), baseline["opening_equity"] - snapshot.equity)
            >= baseline["opening_equity"] * policy.max_daily_loss
        ):
            return self.reject(request, "DAILY_LOSS_STILL_BLOCKED")
        if (
            w.rows(
                ExecutionCommand,
                ExecutionCommand.state.notin_(("COMPLETED", "REJECTED", "EXPIRED", "INVALIDATED")),
            )
            or w.rows(RiskReservation, RiskReservation.status.in_(("HELD", "OUTCOME_UNKNOWN")))
            or w.rows(PaperOperation, PaperOperation.state.in_(("DISPATCHED", "UNKNOWN")))
        ):
            return self.reject(request, "UNRESOLVED_EXECUTION")
        if w.enrollment["fault_latched"] and (
            snapshot.positions or w.rows(Position, Position.status != "CLOSED")
        ):
            return self.reject(request, "FAULT_RESET_REQUIRES_FLAT_ACCOUNT")
        risk = Decimal(0)
        notional = Decimal(0)
        for position in snapshot.positions:
            if (
                position.command_id is None
                or position.stop_loss is None
                or position.take_profit is None
            ):
                return self.reject(request, "UNVERIFIED_POSITION")
            i = next(i for i in snapshot.instruments if i.symbol == position.symbol)
            q = next(q for q in snapshot.quotes if q.symbol == position.symbol)
            if (
                i.quote_currency != snapshot.currency
                or not q.market_open
                or not 0 <= (w.now - q.observed_at).total_seconds() < 5
                or not 0 <= (w.now - i.observed_at).total_seconds() < 60
            ):
                return self.reject(request, "FRESH_MARKET_REQUIRED")
            distance = (
                q.bid - position.stop_loss if position.side == "BUY" else position.stop_loss - q.ask
            )
            risk += (
                max(Decimal(0), distance) + i.slippage_buffer_points * i.point
            ) * i.contract_size * position.volume + i.commission_per_lot_account * position.volume
            notional += q.ask * i.contract_size * position.volume
        if (
            snapshot.equity <= 0
            or risk > snapshot.equity * policy.max_total_open_risk
            or notional > snapshot.equity * policy.max_effective_leverage
            or len(snapshot.positions) > policy.max_open_positions
        ):
            return self.reject(request, "PORTFOLIO_LIMIT_STILL_BLOCKED")
        # The DB fence requires this exact unexpired operator request before clearing a fault.
        w.change(BridgeEnrollment, fault_latched=False)
        w.enrollment["fault_latched"] = False
        w.change(
            TradingAccount,
            TradingAccount.id == w.p.account_id,
            status="READY",
            safety_epoch=w.account["safety_epoch"] + 1,
        )
        w.account["status"] = "READY"
        w.account["safety_epoch"] += 1
        w.change(PaperOperation, PaperOperation.id == request["id"], state="COMPLETED")
        w.audit(
            "PAPER_ACCOUNT_RESUMED",
            {"request_id": str(request["id"]), "epoch": w.account["safety_epoch"]},
        )
        return {"status": "RESUMED", "command": None}

    def uncertain(self, row, operation):
        w = self.w
        if row["state"] in {"DELIVERED", "ACKNOWLEDGED"}:
            w.transition("command", row, "OUTCOME_UNKNOWN")
        if row["state"] == "OUTCOME_UNKNOWN":
            w.transition("command", row, "RECONCILING")
        w.change(
            PaperOperation,
            PaperOperation.id == operation["id"],
            state="UNKNOWN",
            reason="OUTCOME_UNKNOWN",
        )
        w.change(Position, Position.id == operation["position_id"], status="OUTCOME_UNKNOWN")
        w.account_status("RECONCILING")

    def event(self, row, operation, event):
        w = self.w
        command = PaperPositionCommand.model_validate(strict_json(row["payload"]))
        if event.kind in {
            "POSITION_CLOSED",
            "RECONCILED_CLOSE",
            "STOPS_CHANGED",
            "RECONCILED_STOPS",
        }:
            closed = event.kind in {"POSITION_CLOSED", "RECONCILED_CLOSE"}
            if (
                closed != (command.action == "CLOSE")
                or event.position_identifier != command.position_identifier
            ):
                raise ProtocolError("POSITION_OUTCOME_MISMATCH")
            outcome = {
                "command_id": str(command.command_id),
                "position": event.position_identifier,
                "action": command.action,
                "operation_id": event.operation_id,
                "volume": str(event.volume) if closed else None,
                "price": str(event.price) if closed else None,
                "deal_id": event.broker_deal_id,
                "stop_loss": str(event.stop_loss) if not closed else None,
                "take_profit": str(event.take_profit) if not closed else None,
            }
            previous = w.one(
                PaperOperationResult, PaperOperationResult.operation_id == event.operation_id
            )
            if previous:
                if previous["outcome"] != outcome:
                    raise ProtocolError("POSITION_OPERATION_CONFLICT")
                return
            state = w.one(PaperPositionState, PaperPositionState.position_id == command.position_id)
            position = w.one(Position, Position.id == command.position_id)
            if (
                row["state"] == "COMPLETED"
                or state["revision"] != command.position_revision
                or position["volume"] != command.volume
                or position["status"] == "CLOSED"
                or event.observed_at < position["opened_at"]
            ):
                raise ProtocolError("POSITION_REVISION_CONFLICT")
            if closed:
                i = next(i for i in w.p.instruments if i.symbol == command.symbol)
                if (
                    event.volume != command.volume
                    or not command.price_band_low <= event.price <= command.price_band_high
                    or event.price % i.tick_size
                    or w.one(PositionEvent, PositionEvent.broker_deal_id == event.broker_deal_id)
                ):
                    raise ProtocolError("CLOSE_ECONOMICS_CONFLICT")
                pnl = realized_pnl(command, event.price, i)
                w.add(
                    PositionEvent,
                    id=uuid4(),
                    account_id=w.p.account_id,
                    position_id=command.position_id,
                    broker_deal_id=event.broker_deal_id,
                    event_type="PAPER_CLOSE",
                    realized_pnl=pnl,
                    summary=outcome,
                    observed_at=event.observed_at,
                )
                w.change(
                    Position,
                    Position.id == command.position_id,
                    status="CLOSED",
                    volume=Decimal(0),
                    closed_at=event.observed_at,
                )
            else:
                if (event.stop_loss, event.take_profit) != (command.stop_loss, command.take_profit):
                    raise ProtocolError("PROTECTION_OUTCOME_CONFLICT")
                w.change(
                    PaperPositionState,
                    PaperPositionState.position_id == command.position_id,
                    stop_loss=command.stop_loss,
                    take_profit=command.take_profit,
                )
                w.change(Position, Position.id == command.position_id, status="OPEN")
            w.change(
                PaperPositionState,
                PaperPositionState.position_id == command.position_id,
                revision=state["revision"] + 1,
            )
            w.add(
                PaperOperationResult,
                id=uuid4(),
                account_id=w.p.account_id,
                request_id=operation["id"],
                operation_id=event.operation_id,
                outcome=outcome,
            )
            w.change(
                PaperOperation, PaperOperation.id == operation["id"], state="COMPLETED", reason=None
            )
            w.transition("command", row, "COMPLETED", "BROKER_POSITION_UPDATE")
            w.audit(
                "PAPER_POSITION_CLOSED" if closed else "PAPER_STOPS_CHANGED",
                {"request_id": str(operation["id"]), "position_id": str(command.position_id)},
            )
        elif row["state"] != "COMPLETED":
            if event.kind == "UNKNOWN":
                self.uncertain(row, operation)
            elif event.kind == "RECEIVED" and row["state"] == "DELIVERED":
                w.transition("command", row, "ACKNOWLEDGED")
            elif event.kind == "REJECTED":
                if row["state"] == "RECONCILING" or w.rows(
                    ExecutionEvent,
                    ExecutionEvent.command_id == row["id"],
                    ExecutionEvent.event_type.in_(("SEND_INTENT", "ACCEPTED")),
                ):
                    raise ProtocolError("REJECTION_AFTER_POSITION_SEND")
                w.transition("command", row, "REJECTED", "BROKER_REJECTION")
                w.change(Position, Position.id == command.position_id, status="OPEN")
                self.reject(operation, "EXECUTOR_PREFLIGHT_REJECTED")
            elif event.kind not in {"SEND_INTENT", "ACCEPTED", "RECEIVED"}:
                raise ProtocolError("UNEXPECTED_POSITION_EVENT")
