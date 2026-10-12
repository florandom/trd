"""Account transactions for the opt-in local simulator. Real trading remains off."""

from __future__ import annotations

from base64 import b64encode
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import insert, select, text, update

from backend.domain.bridge import (
    Envelope,
    PaperCommand,
    PaperEvents,
    PaperProfile,
    PaperSnapshot,
    Poll,
    ProtocolError,
    json_bytes,
    strict_json,
)
from backend.domain.config import BridgeSettings
from backend.domain.contracts import LifecycleChange, RiskPolicy, fingerprint
from backend.domain.risk import RiskEngine, ceil
from backend.domain.risk_contracts import (
    AccountState,
    AdvisoryEvidence,
    DailyBaseline,
    EffectiveRiskConfig,
    MarketState,
    PositionExposure,
    ReservationExposure,
    RiskProposal,
    ServiceHealth,
    SourceLimits,
)
from backend.infrastructure.bridge_models import (
    BridgeBaseline,
    BridgeDecision,
    BridgeEnrollment,
    BridgeRequest,
    BridgeSnapshot,
    PaperCommandRecord,
)
from backend.infrastructure.database import create_database_engine
from backend.infrastructure.domain_models import (
    Agent,
    AgentConfig,
    AgentRun,
    AnalysisRecord,
    ExecutionCommand,
    ExecutionEvent,
    Order,
    Position,
    PositionEvent,
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
from backend.infrastructure.position_models import PaperPositionState
from backend.infrastructure.repositories import LifecycleRepository
from backend.trading.position_gateway import PositionManagement


class PaperGateway:
    def __init__(self, settings: BridgeSettings, engine=None):
        if not settings.paper_bridge_enabled:
            raise ValueError("paper bridge disabled")
        self.settings = settings
        self.profile = PaperProfile.model_validate(
            strict_json(settings.paper_profile_path.read_bytes())
        )
        if self.profile.account.environment_id != settings.environment_id:
            raise ValueError("paper environment mismatch")
        self.request_key = bytes.fromhex(settings.paper_request_key.get_secret_value())
        self.response_key = bytes.fromhex(settings.paper_response_key.get_secret_value())
        self.engine = engine or create_database_engine(settings.database_url.get_secret_value())
        self.risk = RiskEngine()
        self.hard = RiskPolicy(
            **{name: getattr(settings, "hard_" + name) for name in RiskPolicy.model_fields}
        )
        self.profile.policy.within(self.hard)

    def handle(self, headers, path: str, body: bytes):
        # Caller may also be a test adapter: authenticate here, not only in HTTP middleware.
        now = datetime.now(UTC)
        envelope = Envelope.verify(headers, self.request_key, body, path, now=int(now.timestamp()))
        p = self.profile
        if (envelope.environment, envelope.bridge, envelope.instance, envelope.key) != (
            p.account.environment_id,
            p.bridge_id,
            p.instance_id,
            p.key_id,
        ) or not envelope.issued <= int(now.timestamp()) < envelope.expires:
            raise ProtocolError("AUTHENTICATION_FAILED")
        with self.engine.begin() as connection, localcontext() as context:
            context.prec = 80
            work = _AccountTransaction(self, connection)
            work.lock()
            # Lock contention must not prolong a signed request or stale telemetry.
            if not envelope.issued <= int(work.now.timestamp()) < envelope.expires:
                raise ProtocolError("AUTHENTICATION_FAILED")
            if work.enrollment["journal_id"] is None:
                work.change(BridgeEnrollment, journal_id=envelope.journal)
            elif work.enrollment["journal_id"] != envelope.journal:
                raise ProtocolError("EXECUTOR_OWNER_MISMATCH")
            request_hash = sha256(envelope.message(body, path)).hexdigest()
            cached = work.one(BridgeRequest, BridgeRequest.sequence == envelope.sequence)
            if cached:
                if cached["request_hash"] != request_hash:
                    work.fault("REPLAY_CONFLICT")
                    return work.reply(envelope, path, 409, {"detail": "REPLAY_CONFLICT"})
                return cached["status"], cached["response"], cached["response_headers"]
            if envelope.sequence <= work.enrollment["highwater"]:
                return work.reply(envelope, path, 409, {"detail": "REPLAY_REJECTED"})
            try:
                with connection.begin_nested():
                    value = strict_json(body)
                    if path.endswith("/snapshot"):
                        result = work.snapshot(PaperSnapshot.model_validate(value))
                    elif path.endswith("/events"):
                        result = work.events(PaperEvents.model_validate(value))
                    else:
                        Poll.model_validate(value)
                        result = work.poll()
                status = 200
            except (ValueError, ArithmeticError) as error:
                # A signed contradictory portfolio/event must not erase held exposure.
                reason = str(error) if isinstance(error, ProtocolError) else "INVALID_CONTRACT"
                work.fault(reason)
                status, result = 409, {"detail": "AUTHENTICATED_EVIDENCE_CONFLICT"}
            status, reply, headers = work.reply(envelope, path, status, result)
            work.add(
                BridgeRequest,
                account_id=p.account_id,
                sequence=envelope.sequence,
                request_hash=request_hash,
                status=status,
                response=reply,
                response_headers=headers,
            )
            work.change(BridgeEnrollment, highwater=envelope.sequence)
            return status, reply, headers


class _AccountTransaction:
    def __init__(self, gateway, connection):
        self.gateway, self.c = gateway, connection
        self.p = gateway.profile
        self.env = self.p.account.environment_id
        self.now = connection.scalar(text("SELECT clock_timestamp()"))
        self.lifecycle = LifecycleRepository(connection, self.env)
        self.management = PositionManagement(self)

    def rows(self, model, *conditions, order=None, limit=None):
        query = select(model).where(model.environment_id == self.env, *conditions)
        if hasattr(model, "account_id"):
            query = query.where(model.account_id == self.p.account_id)
        if order is not None:
            query = query.order_by(order)
        if limit is not None:
            query = query.limit(limit)
        return [dict(r) for r in self.c.execute(query).mappings()]

    def one(self, model, *conditions, **kwargs):
        rows = self.rows(model, *conditions, limit=1, **kwargs)
        return rows[0] if rows else None

    def add(self, model, **values):
        self.c.execute(insert(model).values(environment_id=self.env, **values))

    def change(self, model, *conditions, **values):
        query = update(model).where(model.environment_id == self.env, *conditions)
        if hasattr(model, "account_id"):
            query = query.where(model.account_id == self.p.account_id)
        self.c.execute(query.values(**values))

    def lock(self):
        if self.c.scalar(text("SELECT session_user")) != "trd_risk":
            raise PermissionError("risk database identity required")
        # Same ordering as edits, source disabling and retention: evidence fence first.
        self.c.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended('trd-evidence:'||:env,0))"),
            {"env": self.env},
        )
        self.account = dict(
            self.c.execute(
                select(TradingAccount)
                .where(
                    TradingAccount.environment_id == self.env,
                    TradingAccount.id == self.p.account_id,
                )
                .with_for_update()
            )
            .mappings()
            .one()
        )
        self.enrollment = dict(
            self.c.execute(
                select(BridgeEnrollment)
                .where(
                    BridgeEnrollment.environment_id == self.env,
                    BridgeEnrollment.account_id == self.p.account_id,
                )
                .with_for_update()
            )
            .mappings()
            .one()
        )
        g, b, p = self.gateway, self.enrollment, self.p
        if (
            self.account["broker_server"] != p.account.broker_server
            or self.account["login"] != p.account.login
            or self.account["mode"] != "paper"
            or (b["bridge_id"], b["instance_id"], b["key_id"], b["generation"], b["profile_hash"])
            != (p.bridge_id, p.instance_id, p.key_id, p.generation, p.digest)
            or b["request_key_hash"] != sha256(g.request_key).hexdigest()
            or b["response_key_hash"] != sha256(g.response_key).hexdigest()
        ):
            raise ProtocolError("ENROLLMENT_MISMATCH")
        self.now = self.c.scalar(text("SELECT clock_timestamp()"))

    def reply(self, request, path, status, result):
        issued = int(datetime.now(UTC).timestamp())
        response = Envelope(
            request.environment,
            request.bridge,
            request.instance,
            request.key,
            request.sequence,
            issued,
            issued + 10,
            request.journal,
        )
        body = json_bytes(result)
        headers = response.headers(
            self.gateway.response_key, body, path, direction="RESPONSE", status=status
        )
        headers.update({"cache-control": "no-store", "x-content-type-options": "nosniff"})
        return status, body, headers

    def transition(self, kind, row, after, evidence="OBSERVATION"):
        row["revision"] = self.lifecycle.transition(
            kind,
            row["id"],
            LifecycleChange(
                event_id=uuid4(), expected_revision=row["revision"], after=after, evidence=evidence
            ),
        )
        row["state"] = after

    def account_status(self, status):
        self.change(TradingAccount, TradingAccount.id == self.p.account_id, status=status)
        self.account["status"] = status

    def audit(self, action, details):
        self.lifecycle.call(
            "SELECT public.record_paper_audit(:environment,:account,:action,:details)",
            {"account": self.p.account_id, "action": action, "details": details},
            "details",
        )

    def fault(self, code):
        # Protocol conflicts latch permanently; operator inspection is required.
        self.change(BridgeEnrollment, fault_latched=True)
        self.enrollment["fault_latched"] = True
        self.account_status("RECONCILING")
        for command in self.rows(ExecutionCommand):
            if command["state"] in {"CREATED", "READY"}:
                self.revoke(command)
            elif command["state"] in {"DELIVERED", "ACKNOWLEDGED"}:
                self.uncertain(command)
        self.audit("PAPER_BRIDGE_FAULT", {"reason": code})

    def policy(self):
        head = self.one(RiskRuleHead, RiskRuleHead.key == "baseline")
        rule = self.one(
            RiskRule, RiskRule.key == "baseline", RiskRule.version == head["current_version"]
        )
        current = RiskPolicy.model_validate(rule["policy"])
        effective = RiskPolicy(
            **{
                name: min(getattr(current, name), getattr(self.p.policy, name))
                for name in RiskPolicy.model_fields
            }
        )
        return head["current_version"], effective

    def latest_snapshot(self):
        row = self.one(BridgeSnapshot, order=BridgeSnapshot.observed_at.desc())
        return PaperSnapshot.model_validate(row["payload"]) if row else None

    def snapshot(self, snapshot):
        if (
            snapshot.account != self.p.account
            or snapshot.currency != self.account["currency"]
            # This sandbox has no deposits/withdrawals ledger. A caller-supplied
            # adjustment must never disguise loss; real cash flows need evidence.
            or snapshot.net_cash_flow != 0
            or not -2 <= (self.now - snapshot.observed_at).total_seconds() < 15
        ):
            raise ProtocolError("SNAPSHOT_MISMATCH")
        expected = {
            i.symbol: i.model_dump(exclude={"snapshot_id", "observed_at"})
            for i in self.p.instruments
        }
        actual = {
            i.symbol: i.model_dump(exclude={"snapshot_id", "observed_at"})
            for i in snapshot.instruments
        }
        if expected != actual or {q.symbol for q in snapshot.quotes} != set(expected):
            raise ProtocolError("METADATA_MISMATCH")
        prior = self.one(BridgeSnapshot, BridgeSnapshot.id == snapshot.snapshot_id)
        if prior:
            if prior["payload_hash"] != fingerprint(snapshot):
                raise ProtocolError("SNAPSHOT_CONFLICT")
            return {"snapshot_id": str(snapshot.snapshot_id), "status": self.account["status"]}
        latest = self.latest_snapshot()
        if latest and snapshot.observed_at <= latest.observed_at:
            raise ProtocolError("STALE_SNAPSHOT")
        self.add(
            BridgeSnapshot,
            id=snapshot.snapshot_id,
            account_id=self.p.account_id,
            payload_hash=fingerprint(snapshot),
            payload=snapshot.model_dump(mode="json"),
            observed_at=snapshot.observed_at,
        )
        baseline = self.one(BridgeBaseline, BridgeBaseline.day == self.now.date())
        if baseline:
            if (
                baseline["opening_equity"] != snapshot.opening_equity
                or baseline["currency"] != snapshot.currency
            ):
                raise ProtocolError("BASELINE_CONFLICT")
            if snapshot.history_complete:
                self.change(
                    BridgeBaseline,
                    BridgeBaseline.day == self.now.date(),
                    net_cash_flow=snapshot.net_cash_flow,
                )
        elif snapshot.history_complete:
            self.add(
                BridgeBaseline,
                account_id=self.p.account_id,
                day=self.now.date(),
                snapshot_id=snapshot.snapshot_id,
                currency=snapshot.currency,
                opening_equity=snapshot.opening_equity,
                net_cash_flow=snapshot.net_cash_flow,
            )
        self.verify_portfolio(snapshot)
        _, policy = self.policy()
        baseline = self.one(BridgeBaseline, BridgeBaseline.day == self.now.date())
        if (
            baseline
            and max(
                Decimal(0), baseline["opening_equity"] + baseline["net_cash_flow"] - snapshot.equity
            )
            >= baseline["opening_equity"] * policy.max_daily_loss
        ):
            self.change(BridgeBaseline, BridgeBaseline.day == self.now.date(), loss_latched=True)
            self.account_status("PAUSED")
            self.audit("PAPER_DAILY_LOSS_LATCHED", {"day": str(self.now.date())})
        elif (
            self.account["status"] == "RECONCILING"
            and not self.enrollment["fault_latched"]
            and snapshot.portfolio_complete
            and snapshot.history_complete
            and baseline
            and not baseline["loss_latched"]
            and not self.rows(
                ExecutionCommand,
                ExecutionCommand.state.in_(
                    ("DELIVERED", "ACKNOWLEDGED", "OUTCOME_UNKNOWN", "RECONCILING")
                ),
            )
        ):
            self.account_status("READY")
        return {"snapshot_id": str(snapshot.snapshot_id), "status": self.account["status"]}

    def verify_portfolio(self, snapshot):
        positions = self.rows(Position, Position.status != "CLOSED")
        observed = {p.broker_identifier: p for p in snapshot.positions}
        for position in positions:
            item = observed.get(position["broker_identifier"])
            order = self.one(Order, Order.id == position["order_id"])
            command = PaperCommand.model_validate(
                strict_json(
                    self.one(ExecutionCommand, ExecutionCommand.id == order["command_id"])[
                        "payload"
                    ]
                )
            )
            protection = self.one(
                PaperPositionState, PaperPositionState.position_id == position["id"]
            )
            if (
                item is None
                or item.command_id != command.command_id
                or item.symbol != position["symbol"]
                or item.volume != position["volume"]
                or item.entry_price != position["entry_price"]
                or item.side != command.side
                or item.stop_loss != (protection["stop_loss"] if protection else command.stop_loss)
                or item.take_profit
                != (protection["take_profit"] if protection else command.take_profit)
            ):
                raise ProtocolError("PORTFOLIO_CONFLICT")
        if any(
            p.command_id is not None
            and p.broker_identifier not in {r["broker_identifier"] for r in positions}
            for p in snapshot.positions
        ):
            raise ProtocolError("UNRECORDED_FILL")

    def advisory(self, signal, version):
        analysis = self.one(AnalysisRecord, AnalysisRecord.signal_id == signal["id"])
        message = self.one(TelegramMessage, TelegramMessage.id == signal["message_id"])
        source = self.one(TelegramSource, TelegramSource.id == message["source_id"])
        msg = self.one(
            TelegramMessageVersion,
            TelegramMessageVersion.message_id == message["id"],
            order=TelegramMessageVersion.version.desc(),
        )
        if not analysis or source["id"] not in self.p.source_ids:
            return None
        agents = self.rows(Agent)
        critic = next((a for a in agents if a["name"] == "CRITIC"), None)
        critic_config = (
            self.one(
                AgentConfig,
                AgentConfig.agent_id == critic["id"],
                AgentConfig.version == critic["current_version"],
            )
            if critic
            else None
        )
        required = {"SIGNAL_CLASSIFIER", "SIGNAL_PARSER", "MARKET_ANALYST", "DECISION_AGENT"}
        if critic_config and critic_config["enabled"]:
            required.add("CRITIC")
        complete = []
        current = (
            analysis["outcome"] == "WAITING" and analysis["source_version"] == source["version"]
        )
        for name in required:
            agent = next((a for a in agents if a["name"] == name), None)
            if not agent:
                current = False
                continue
            config = self.one(
                AgentConfig,
                AgentConfig.agent_id == agent["id"],
                AgentConfig.version == agent["current_version"],
            )
            if (
                not config["enabled"]
                or config["prompt_version"] != 2
                or analysis["config_versions"].get(name) != agent["current_version"]
            ):
                current = False
                continue
            if name in {"SIGNAL_CLASSIFIER", "SIGNAL_PARSER"}:
                complete.append(name)
                continue
            run = self.one(
                AgentRun,
                AgentRun.agent_id == agent["id"],
                AgentRun.trace_id == analysis["trace_id"],
                order=AgentRun.created_at.desc(),
            )
            if (
                run
                and run["config_version"] == agent["current_version"]
                and run["status"] == "SUCCEEDED"
                and (run["result"] or {}).get("advisory", {}).get("action") == "PROPOSE"
            ):
                complete.append(name)
        review = (
            msg["version"] != 1
            or version["message_version"] != msg["version"]
            or msg["event_kind"] != "NEW"
            or message["reply_message_id"] is not None
        )
        proposal = RiskProposal.model_validate(
            {
                **version["proposal"],
                "account": self.p.account,
                "signal_id": signal["id"],
                "signal_version": version["version"],
                "message_id": message["id"],
                "message_version": version["message_version"],
                "source_id": source["id"],
                "source_version": source["version"],
                "published_at": msg["published_at"] or msg["observed_at"],
                "review_only": review,
            }
        )
        evidence = AdvisoryEvidence(
            receipt_id=analysis["id"],
            signal_id=signal["id"],
            signal_version=version["version"],
            message_version=version["message_version"],
            source_version=analysis["source_version"],
            outcome="PROPOSE" if required.issubset(complete) else "WAIT",
            completed_stages=tuple(sorted(complete)),
            config_current=current,
            confidence=Decimal(0),
        )
        return proposal, evidence, source, "CRITIC" in required

    def inputs(self, proposal, evidence, source, critic, snapshot):
        baseline = self.one(BridgeBaseline, BridgeBaseline.day == self.now.date())
        reservations = []
        ledger = self.rows(PaperCommandRecord)
        for record in ledger:
            row = self.one(ExecutionCommand, ExecutionCommand.id == record["command_id"])
            hold = self.one(RiskReservation, RiskReservation.id == row["reservation_id"])
            command = PaperCommand.model_validate(strict_json(row["payload"]))
            if hold["status"] in {"HELD", "OUTCOME_UNKNOWN"} and record["remaining_risk"] > 0:
                reservations.append(
                    ReservationExposure(
                        reservation_id=hold["id"],
                        slot_id=command.command_id,
                        signal_id=command.signal_id,
                        source_id=command.source_id,
                        symbol=command.symbol,
                        risk_amount=record["remaining_risk"],
                        notional_amount=record["remaining_notional"],
                        margin_amount=record["remaining_margin"],
                        state="UNKNOWN"
                        if row["state"] in {"OUTCOME_UNKNOWN", "RECONCILING"}
                        else "HELD"
                        if row["state"] in {"CREATED", "READY"}
                        else "SUBMITTED",
                        volume=command.volume,
                    )
                )
        positions = []
        for observed in snapshot.positions:
            record = next((r for r in ledger if r["command_id"] == observed.command_id), None)
            command = (
                PaperCommand.model_validate(
                    strict_json(
                        self.one(ExecutionCommand, ExecutionCommand.id == record["command_id"])[
                            "payload"
                        ]
                    )
                )
                if record
                else None
            )
            positions.append(
                PositionExposure(
                    position_id=observed.broker_identifier,
                    slot_id=observed.command_id
                    or uuid5(
                        NAMESPACE_URL,
                        f"{self.env}/{self.p.account_id}/{observed.broker_identifier}",
                    ),
                    symbol=observed.symbol,
                    side=observed.side,
                    volume=observed.volume,
                    stop_loss=observed.stop_loss,
                    take_profit=observed.take_profit,
                    source_id=command.source_id if command else None,
                    signal_id=command.signal_id if command else None,
                    managed=command is not None,
                    ownership_verified=command is not None,
                )
            )
        account = AccountState(
            snapshot_id=snapshot.snapshot_id,
            account=snapshot.account,
            observed_at=snapshot.observed_at,
            currency=snapshot.currency,
            equity=snapshot.equity,
            free_margin=snapshot.free_margin,
            broker_leverage=snapshot.broker_leverage,
            position_mode=snapshot.position_mode,
            safety_epoch=self.account["safety_epoch"],
            status=self.account["status"],
            reconciliation_complete=self.account["status"] == "READY",
            portfolio_complete=snapshot.portfolio_complete,
            trading_permitted=not self.enrollment["fault_latched"],
            positions=tuple(positions),
            reservations=tuple(reservations),
            consumed_signal_ids=tuple(r["signal_id"] for r in ledger),
            consumed_message_ids=tuple(r["message_id"] for r in ledger),
            health=(
                ServiceHealth(service="database", observed_at=self.now, healthy=True),
                ServiceHealth(service="risk", observed_at=self.now, healthy=True),
                ServiceHealth(
                    service="executor",
                    observed_at=snapshot.observed_at,
                    healthy=snapshot.history_complete,
                ),
            ),
            daily_baseline=DailyBaseline(
                snapshot_id=baseline["snapshot_id"],
                account=snapshot.account,
                currency=baseline["currency"],
                day=baseline["day"],
                opening_equity=baseline["opening_equity"],
                net_cash_flow=baseline["net_cash_flow"],
                history_complete=snapshot.history_complete,
                loss_latched=baseline["loss_latched"],
            )
            if baseline
            else None,
        )
        market = MarketState(
            snapshot_id=snapshot.snapshot_id,
            account=snapshot.account,
            quotes=snapshot.quotes,
            instruments=snapshot.instruments,
        )
        policy_version, policy = self.policy()
        config = EffectiveRiskConfig(
            now=self.now,
            policy_version=policy_version,
            hard_limits=self.gateway.hard,
            policy=policy,
            source=SourceLimits(
                source_id=source["id"],
                version=source["version"],
                enabled=source["enabled"],
                allowed_symbols=tuple(m.symbol for m in self.p.mappings),
                max_risk_per_trade=policy.max_risk_per_trade,
            ),
            account_allowlist=(self.p.account,),
            automation_enabled=True,
            expected_safety_epoch=self.account["safety_epoch"],
            allowed_instruments=self.p.mappings,
            calendar=self.p.calendar,
            account_max_age_seconds=15,
            quote_max_age_seconds=5,
            metadata_max_age_seconds=60,
            health_max_age_seconds=15,
            signal_max_age_seconds=900,
            max_spread_points=self.p.max_spread_points,
            max_deviation_points=self.p.max_deviation_points,
            conversion_buffer=Decimal("0.001"),
            max_symbol_exposure=policy.max_effective_leverage,
            advisory=evidence,
            critic_required=critic,
            minimum_confidence=Decimal(0),
        )
        return account, market, config

    def record_evaluation(self, proposal, result, phase):
        # Clock-only changes don't create an unlimited stream of identical decisions.
        key = sha256(
            json_bytes(
                {
                    "phase": phase,
                    "proposal": result.proposal_hash,
                    "account_snapshot": str(result.account_snapshot_id),
                    "policy": result.policy_version,
                    "source": result.source_version,
                    "epoch": result.safety_epoch,
                    "status": result.status,
                    "reasons": list(result.reason_codes),
                }
            )
        ).hexdigest()
        previous = self.one(BridgeDecision, BridgeDecision.evaluation_hash == key)
        if previous:
            return previous["risk_event_id"]
        event = uuid4()
        self.add(
            RiskEvent,
            id=event,
            signal_id=proposal.signal_id,
            signal_version=proposal.signal_version,
            rule_key="baseline",
            rule_version=result.policy_version,
            result={"PASS": "APPROVED", "REJECT": "REJECTED", "ERROR": "ERROR"}[result.status],
            reason_codes=list(result.reason_codes),
            calculation=result.model_dump(mode="json"),
        )
        self.add(
            BridgeDecision,
            id=uuid4(),
            account_id=self.p.account_id,
            evaluation_hash=key,
            risk_event_id=event,
        )
        if result.latch_daily_loss:
            self.change(BridgeBaseline, BridgeBaseline.day == self.now.date(), loss_latched=True)
            self.account_status("PAUSED")
        return event

    def admit(self, snapshot):
        for signal in self.rows(
            Signal, Signal.state == "WAITING", order=Signal.created_at, limit=32
        ):
            if self.one(PaperCommandRecord, PaperCommandRecord.message_id == signal["message_id"]):
                continue
            version = self.one(
                SignalVersion,
                SignalVersion.signal_id == signal["id"],
                order=SignalVersion.version.desc(),
            )
            advisory = self.advisory(signal, version)
            if advisory is None:
                continue
            proposal, evidence, source, critic = advisory
            if evidence.outcome != "PROPOSE":
                continue
            account, market, config = self.inputs(*advisory, snapshot)
            result = self.gateway.risk.evaluate(proposal, account, market, config)
            event = self.record_evaluation(proposal, result, "ADMISSION")
            if result.status != "PASS":
                continue
            for state in ("DECIDED", "RISK_CHECK", "APPROVED"):
                self.transition("signal", signal, state)
            approval, reservation, command_id = uuid4(), uuid4(), uuid4()
            calculations = result.calculations
            expires = min(proposal.expires_at, self.now + timedelta(seconds=30))
            command = PaperCommand(
                command_id=command_id,
                trace_id=signal["trace_id"],
                approval_id=approval,
                reservation_id=reservation,
                account_id=self.p.account_id,
                account=self.p.account,
                bridge_id=self.p.bridge_id,
                instance_id=self.p.instance_id,
                generation=self.p.generation,
                profile_hash=self.p.digest,
                safety_epoch=account.safety_epoch,
                policy_version=config.policy_version,
                signal_id=signal["id"],
                signal_version=version["version"],
                source_id=source["id"],
                source_version=source["version"],
                symbol=next(
                    m.broker_symbol for m in self.p.mappings if m.symbol == proposal.symbol
                ),
                side=proposal.side,
                volume=result.volume,
                stop_loss=proposal.stop_loss,
                take_profit=proposal.take_profit,
                price_band_low=calculations.price_band_low,
                price_band_high=calculations.price_band_high,
                max_spread_points=config.max_spread_points,
                max_deviation_points=config.max_deviation_points,
                max_risk=calculations.estimated_trade_risk,
                expires_at=expires,
            )
            payload = json_bytes(command)
            self.add(
                RiskApproval,
                id=approval,
                account_id=self.p.account_id,
                risk_event_id=event,
                risk_amount=command.max_risk,
                safety_epoch=account.safety_epoch,
                expires_at=expires,
            )
            self.add(
                RiskReservation,
                id=reservation,
                account_id=self.p.account_id,
                approval_id=approval,
                risk_amount=command.max_risk,
            )
            self.add(
                ExecutionCommand,
                id=command_id,
                account_id=self.p.account_id,
                reservation_id=reservation,
                trace_id=signal["trace_id"],
                payload=payload,
                payload_hash=sha256(payload).hexdigest(),
                expires_at=expires,
            )
            self.add(
                PaperCommandRecord,
                id=uuid4(),
                account_id=self.p.account_id,
                command_id=command_id,
                signal_id=signal["id"],
                message_id=signal["message_id"],
                proposal=proposal.model_dump(mode="json"),
                admission=result.model_dump(mode="json"),
                remaining_risk=command.max_risk,
                remaining_notional=calculations.estimated_trade_notional,
                remaining_margin=calculations.required_margin,
            )
            self.add(
                Order,
                id=uuid4(),
                account_id=self.p.account_id,
                command_id=command_id,
                symbol=command.symbol,
                side=command.side,
                volume=command.volume,
            )
            row = self.one(ExecutionCommand, ExecutionCommand.id == command_id)
            self.transition("command", row, "READY")
            order = self.one(Order, Order.command_id == command_id)
            self.transition("order", order, "VALIDATED")
            self.audit(
                "PAPER_COMMAND_RESERVED",
                {
                    "command_id": str(command_id),
                    "signal_id": str(signal["id"]),
                    "risk": str(command.max_risk),
                },
            )
            return

    def revoke(self, row):
        operation = self.management.operation(row["id"])
        if operation:
            self.transition(
                "command", row, "EXPIRED" if row["expires_at"] <= self.now else "INVALIDATED"
            )
            self.management.reject(operation, "POSITION_COMMAND_INVALIDATED")
            return
        self.transition(
            "command", row, "EXPIRED" if row["expires_at"] <= self.now else "INVALIDATED"
        )
        self.change(RiskReservation, RiskReservation.id == row["reservation_id"], status="RELEASED")
        order = self.one(Order, Order.command_id == row["id"])
        if order["state"] in {"PROPOSED", "VALIDATED"}:
            self.transition("order", order, "EXPIRED")
        record = self.one(PaperCommandRecord, PaperCommandRecord.command_id == row["id"])
        signal = self.one(Signal, Signal.id == record["signal_id"])
        if signal["state"] == "APPROVED":
            self.transition("signal", signal, "EXPIRED")

    def poll(self):
        snapshot = self.latest_snapshot()
        if snapshot is None:
            return {"status": "WAITING_FOR_SNAPSHOT", "command": None}
        self.verify_portfolio(snapshot)
        # Lost replies remain reserved. Timeout is uncertainty, not permission to retry a send.
        for row in self.rows(
            ExecutionCommand, ExecutionCommand.state.in_(("DELIVERED", "ACKNOWLEDGED"))
        ):
            if row["expires_at"] <= self.now:
                self.uncertain(row)
        management = self.management.poll(snapshot)
        if management is not None:
            return management
        if self.account["status"] != "READY" or self.enrollment["fault_latched"]:
            return {"status": self.account["status"], "command": None}
        if not self.rows(ExecutionCommand, ExecutionCommand.state == "READY"):
            self.admit(snapshot)
        row = self.one(
            ExecutionCommand, ExecutionCommand.state == "READY", order=ExecutionCommand.created_at
        )
        if not row:
            return {"status": "NO_COMMAND", "command": None}
        command = PaperCommand.model_validate(strict_json(row["payload"]))
        record = self.one(PaperCommandRecord, PaperCommandRecord.command_id == row["id"])
        signal = self.one(Signal, Signal.id == record["signal_id"])
        version = self.one(
            SignalVersion,
            SignalVersion.signal_id == signal["id"],
            order=SignalVersion.version.desc(),
        )
        advisory = self.advisory(signal, version)
        if (
            advisory is None
            or row["expires_at"] <= self.now
            or command.safety_epoch != self.account["safety_epoch"]
            or command.policy_version != self.policy()[0]
            or command.source_version != advisory[2]["version"]
            or command.signal_version != version["version"]
        ):
            self.revoke(row)
            return {"status": "INVALIDATED", "command": None}
        proposal = RiskProposal.model_validate(record["proposal"]).model_copy(
            update={"requested_volume": command.volume}
        )
        inputs = self.inputs(*advisory, snapshot)
        result = self.gateway.risk.revalidate(
            proposal, *inputs, reservation_id=row["reservation_id"]
        )
        self.record_evaluation(proposal, result, "DISPATCH")
        if result.status != "PASS":
            # A loss latch can already invalidate the row in its DB trigger.
            row = self.one(ExecutionCommand, ExecutionCommand.id == row["id"])
            if row["state"] == "READY":
                self.revoke(row)
            return {"status": "REVALIDATION_FAILED", "command": None}
        self.transition("command", row, "DELIVERED")
        self.transition("signal", signal, "EXECUTION_REQUESTED")
        order = self.one(Order, Order.command_id == row["id"])
        self.transition("order", order, "REQUESTED")
        return {
            "status": "DELIVERED",
            "command": b64encode(row["payload"]).decode("ascii"),
            "command_hash": row["payload_hash"],
            "safety_epoch": self.account["safety_epoch"],
        }

    def uncertain(self, row):
        operation = self.management.operation(row["id"])
        if operation:
            self.management.uncertain(row, operation)
            return
        if row["state"] in {"DELIVERED", "ACKNOWLEDGED"}:
            self.transition("command", row, "OUTCOME_UNKNOWN")
        if row["state"] == "OUTCOME_UNKNOWN":
            self.transition("command", row, "RECONCILING")
        order = self.one(Order, Order.command_id == row["id"])
        if order["state"] in {"REQUESTED", "SENT", "ACCEPTED", "PARTIALLY_FILLED"}:
            self.transition("order", order, "OUTCOME_UNKNOWN")
        if order["state"] == "OUTCOME_UNKNOWN":
            self.transition("order", order, "RECONCILING")
        self.change(
            RiskReservation, RiskReservation.id == row["reservation_id"], status="OUTCOME_UNKNOWN"
        )
        record = self.one(PaperCommandRecord, PaperCommandRecord.command_id == row["id"])
        signal = self.one(Signal, Signal.id == record["signal_id"])
        if signal["state"] == "EXECUTION_REQUESTED":
            self.transition("signal", signal, "RECONCILING")
        self.account_status("RECONCILING")

    def events(self, batch):
        accepted = []
        for event in batch.events:
            row = self.one(ExecutionCommand, ExecutionCommand.id == event.command_id)
            if (
                row is None
                or row["payload_hash"] != event.command_hash
                or event.observed_at > self.now + timedelta(seconds=2)
            ):
                raise ProtocolError("EVENT_MISMATCH")
            existing = self.one(ExecutionEvent, ExecutionEvent.event_key == str(event.event_id))
            if existing:
                if existing["payload_hash"] != fingerprint(event):
                    raise ProtocolError("EVENT_CONFLICT")
                accepted.append(str(event.event_id))
                continue
            if row["state"] in {"CREATED", "READY", "EXPIRED", "INVALIDATED", "REJECTED"}:
                raise ProtocolError("EVENT_NOT_DELIVERED")
            self.add(
                ExecutionEvent,
                id=event.event_id,
                account_id=self.p.account_id,
                command_id=row["id"],
                event_key=str(event.event_id),
                event_type=event.kind,
                payload_hash=fingerprint(event),
                summary=event.model_dump(mode="json"),
                observed_at=event.observed_at,
            )
            operation = self.management.operation(row["id"])
            if operation:
                self.management.event(row, operation, event)
                accepted.append(str(event.event_id))
                continue
            order = self.one(Order, Order.command_id == row["id"])
            record = self.one(PaperCommandRecord, PaperCommandRecord.command_id == row["id"])
            if event.kind in {"FILL", "RECONCILED_FILL"}:
                self.fill(row, order, record, event)
            elif row["state"] != "COMPLETED":
                if event.kind == "UNKNOWN":
                    self.uncertain(row)
                elif event.kind == "RECEIVED" and row["state"] == "DELIVERED":
                    self.transition("command", row, "ACKNOWLEDGED")
                elif event.kind in {"SEND_INTENT", "ACCEPTED"}:
                    self.change(
                        PaperCommandRecord, PaperCommandRecord.id == record["id"], send_intent=True
                    )
                    if order["state"] == "REQUESTED":
                        self.transition("order", order, "SENT")
                    if event.kind == "ACCEPTED" and order["state"] == "SENT":
                        self.transition("order", order, "ACCEPTED", "BROKER_ACCEPTANCE")
                elif event.kind == "REJECTED":
                    if (
                        order["filled_volume"]
                        or record["send_intent"]
                        or row["state"] == "RECONCILING"
                    ):
                        raise ProtocolError("REJECTION_AFTER_SEND")
                    if order["state"] == "REQUESTED":
                        self.transition("order", order, "SENT")
                    self.transition("order", order, "REJECTED", "BROKER_REJECTION")
                    self.transition("command", row, "REJECTED", "BROKER_REJECTION")
                    self.change(
                        RiskReservation,
                        RiskReservation.id == row["reservation_id"],
                        status="RELEASED",
                    )
                    signal = self.one(Signal, Signal.id == record["signal_id"])
                    self.transition("signal", signal, "RECONCILING")
                    self.transition("signal", signal, "FAILED", "BROKER_REJECTION")
            accepted.append(str(event.event_id))
        return {"accepted": accepted, "status": self.account["status"]}

    def fill(self, row, order, record, event):
        command = PaperCommand.model_validate(strict_json(row["payload"]))
        # Economic duplicate identity is independent of the transport event UUID.
        economic = {
            "command": str(row["id"]),
            "ticket": event.broker_ticket,
            "position": event.position_identifier,
            "volume": str(event.volume),
            "price": str(event.price),
        }
        previous = self.one(PositionEvent, PositionEvent.broker_deal_id == event.broker_deal_id)
        if previous:
            if previous["summary"] != economic:
                raise ProtocolError("DEAL_CONFLICT")
            return
        if (
            row["state"] == "COMPLETED"
            or order["filled_volume"] + event.volume > command.volume
            or not command.price_band_low <= event.price <= command.price_band_high
            or order["broker_ticket"] not in {None, event.broker_ticket}
        ):
            raise ProtocolError("FILL_ECONOMICS_CONFLICT")
        instrument = next(i for i in self.p.instruments if i.symbol == command.symbol)
        if event.volume % instrument.volume_step or event.price % instrument.tick_size:
            raise ProtocolError("FILL_PRECISION")
        position = self.one(Position, Position.order_id == order["id"])
        if position and position["broker_identifier"] != event.position_identifier:
            raise ProtocolError("POSITION_IDENTITY_CONFLICT")
        if position is None:
            position_id = uuid4()
            self.add(
                Position,
                id=position_id,
                account_id=self.p.account_id,
                order_id=order["id"],
                broker_identifier=event.position_identifier,
                symbol=command.symbol,
                volume=event.volume,
                entry_price=event.price,
                status="OPEN",
                opened_at=event.observed_at,
            )
            self.add(
                PaperPositionState,
                id=uuid4(),
                account_id=self.p.account_id,
                position_id=position_id,
                stop_loss=command.stop_loss,
                take_profit=command.take_profit,
            )
        else:
            position_id = position["id"]
            prior_fills = self.rows(
                PositionEvent,
                PositionEvent.position_id == position_id,
                PositionEvent.event_type == "PAPER_FILL",
            )
            entry_value = sum(
                (
                    Decimal(e["summary"]["volume"]) * Decimal(e["summary"]["price"])
                    for e in prior_fills
                ),
                Decimal(0),
            )
            average = (entry_value + event.price * event.volume) / (
                position["volume"] + event.volume
            )
            self.change(
                Position,
                Position.id == position_id,
                volume=position["volume"] + event.volume,
                entry_price=ceil(average),
            )
        self.add(
            PositionEvent,
            id=uuid4(),
            account_id=self.p.account_id,
            position_id=position_id,
            broker_deal_id=event.broker_deal_id,
            event_type="PAPER_FILL",
            realized_pnl=Decimal(0),
            summary=economic,
            observed_at=event.observed_at,
        )
        filled = order["filled_volume"] + event.volume
        self.change(
            Order, Order.id == order["id"], filled_volume=filled, broker_ticket=event.broker_ticket
        )
        ratio = (command.volume - filled) / command.volume
        original = record["admission"]["calculations"]
        self.change(
            PaperCommandRecord,
            PaperCommandRecord.id == record["id"],
            remaining_risk=ceil(command.max_risk * ratio),
            remaining_notional=ceil(Decimal(original["estimated_trade_notional"]) * ratio),
            remaining_margin=ceil(Decimal(original["required_margin"]) * ratio),
            send_intent=True,
        )
        if order["state"] == "REQUESTED":
            self.transition("order", order, "SENT")
        full = filled == command.volume
        evidence = "RECONCILED_FILL" if event.kind == "RECONCILED_FILL" else "BROKER_FILL"
        if order["state"] != "PARTIALLY_FILLED" or full:
            self.transition(
                "order",
                order,
                "FILLED" if full else "PARTIALLY_FILLED",
                evidence if full else "BROKER_PARTIAL_FILL",
            )
        if full:
            self.change(
                RiskReservation, RiskReservation.id == row["reservation_id"], status="CONSUMED"
            )
            self.transition("command", row, "COMPLETED", evidence)
            signal = self.one(Signal, Signal.id == record["signal_id"])
            self.transition("signal", signal, "EXECUTED", evidence)
        self.audit(
            "PAPER_BROKER_FILL",
            {"command_id": str(row["id"]), "deal_id": event.broker_deal_id, "full": full},
        )
