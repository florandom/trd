"""Durable local executor and a deliberately separate synthetic broker ledger."""

from __future__ import annotations

import os
import sqlite3
from base64 import b64decode
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from backend.domain.bridge import (
    MAX_BODY,
    Envelope,
    PaperCommand,
    PaperEvent,
    PaperEvents,
    PaperPosition,
    PaperPositionCommand,
    PaperProfile,
    ProtocolError,
    json_bytes,
    parse_paper_command,
    strict_json,
)
from backend.domain.position_management import position_preflight, realized_pnl
from backend.domain.risk import ceil


class SimulatedCrash(RuntimeError):
    pass


def durable_database(path: Path):
    connection = sqlite3.connect(path, isolation_level=None)
    if os.name != "nt":
        path.chmod(0o600)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("PRAGMA fullfsync=ON")
    connection.row_factory = sqlite3.Row
    return connection


class PaperBroker:
    """No network/MT5 adapter. submit is intentionally NOT idempotent."""

    def __init__(self, path: Path):
        self.db = durable_database(path)
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS broker_orders(ticket INTEGER PRIMARY KEY AUTOINCREMENT,
            command_id TEXT NOT NULL, command_hash TEXT NOT NULL, payload BLOB NOT NULL);
        CREATE TABLE IF NOT EXISTS deals(ticket INTEGER PRIMARY KEY AUTOINCREMENT,
            order_ticket INTEGER NOT NULL REFERENCES broker_orders(ticket),
            volume TEXT NOT NULL, price TEXT NOT NULL, observed_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS position_operations(ticket INTEGER PRIMARY KEY AUTOINCREMENT,
            command_id TEXT NOT NULL, command_hash TEXT NOT NULL, payload BLOB NOT NULL,
            position_identifier TEXT NOT NULL, outcome BLOB NOT NULL);
        """)

    def submit(self, command, payload_hash, *, volume=None, price=None):
        if isinstance(command, PaperPositionCommand):
            return self.submit_position(command, payload_hash, price)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            ticket = self.db.execute(
                "INSERT INTO broker_orders(command_id,command_hash,payload) VALUES(?,?,?)",
                (str(command.command_id), payload_hash, json_bytes(command)),
            ).lastrowid
            self.db.execute(
                "INSERT INTO deals(order_ticket,volume,price,observed_at) VALUES(?,?,?,?)",
                (
                    ticket,
                    str(volume or command.volume),
                    str(price or command.price_band_high),
                    datetime.now(UTC).isoformat(),
                ),
            )
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        return ticket

    def submit_position(self, command, payload_hash, price):
        # Deliberately separate from executor journal; restart must reconcile this ledger.
        self.db.execute("BEGIN IMMEDIATE")
        try:
            positions = {p.broker_identifier: p for p in self.positions()}
            current = positions.get(command.position_identifier)
            if (
                current is None
                or current.volume != command.volume
                or current.command_id != command.opening_command_id
            ):
                raise ProtocolError("SYNTHETIC_POSITION_CHANGED")
            result = {
                "kind": "POSITION_CLOSED" if command.action == "CLOSE" else "STOPS_CHANGED",
                "position_identifier": command.position_identifier,
                "observed_at": datetime.now(UTC).isoformat(),
            }
            if command.action == "CLOSE":
                result.update(volume=str(command.volume), price=str(price))
            else:
                result.update(
                    stop_loss=str(command.stop_loss), take_profit=str(command.take_profit)
                )
            ticket = self.db.execute(
                "INSERT INTO position_operations(command_id,command_hash,payload,"
                "position_identifier,outcome) VALUES(?,?,?,?,?)",
                (
                    str(command.command_id),
                    payload_hash,
                    json_bytes(command),
                    command.position_identifier,
                    json_bytes(result),
                ),
            ).lastrowid
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        return ticket

    def position_results(self, command_id):
        return self.db.execute(
            "SELECT * FROM position_operations WHERE command_id=? ORDER BY ticket",
            (str(command_id),),
        ).fetchall()

    def realized_pnl(self, profile):
        total = Decimal(0)
        for row in self.db.execute("SELECT * FROM position_operations ORDER BY ticket").fetchall():
            command = PaperPositionCommand.model_validate(strict_json(row["payload"]))
            if command.action == "CLOSE":
                result = strict_json(row["outcome"])
                instrument = next(i for i in profile.instruments if i.symbol == command.symbol)
                total += realized_pnl(command, Decimal(result["price"]), instrument)
        return total

    def deals(self, command_id):
        return self.db.execute(
            "SELECT d.*,b.command_hash,b.command_id FROM deals d JOIN broker_orders b "
            "ON b.ticket=d.order_ticket WHERE b.command_id=? ORDER BY d.ticket",
            (str(command_id),),
        ).fetchall()

    def positions(self):
        positions = []
        for order in self.db.execute("SELECT * FROM broker_orders ORDER BY ticket").fetchall():
            command = PaperCommand.model_validate(strict_json(order["payload"]))
            operations = self.db.execute(
                "SELECT * FROM position_operations WHERE position_identifier=? ORDER BY ticket",
                (str(order["ticket"]),),
            ).fetchall()
            protection = None
            closed = False
            for operation in operations:
                outcome = strict_json(operation["outcome"])
                if outcome["kind"] == "POSITION_CLOSED":
                    closed = True
                else:
                    protection = outcome
            if closed:
                continue
            deals = self.db.execute(
                "SELECT * FROM deals WHERE order_ticket=?", (order["ticket"],)
            ).fetchall()
            volume = sum((Decimal(d["volume"]) for d in deals), Decimal(0))
            with localcontext() as context:
                context.prec = 80
                average = ceil(
                    sum((Decimal(d["volume"]) * Decimal(d["price"]) for d in deals), Decimal(0))
                    / volume
                )
            positions.append(
                PaperPosition(
                    broker_identifier=str(order["ticket"]),
                    command_id=command.command_id,
                    symbol=command.symbol,
                    side=command.side,
                    volume=volume,
                    entry_price=average,
                    stop_loss=protection["stop_loss"] if protection else command.stop_loss,
                    take_profit=protection["take_profit"] if protection else command.take_profit,
                )
            )
        return tuple(positions)

    def close(self):
        self.db.close()


class PaperSimulator:
    def __init__(
        self,
        profile: PaperProfile,
        request_key: bytes,
        response_key: bytes,
        directory: Path,
        origin: str,
        *,
        transport=None,
    ):
        address = urlsplit(origin)
        if (
            address.scheme != "http"
            or address.hostname not in {"127.0.0.1", "::1"}
            or address.port is None
            or address.path
            or address.query
            or address.fragment
            or address.username
            or address.password
        ):
            raise ValueError("paper simulator requires a fixed numeric loopback origin")
        if len(request_key) != 32 or len(response_key) != 32 or request_key == response_key:
            raise ValueError("separate 256-bit local keys required")
        self.profile, self.request_key, self.response_key = profile, request_key, response_key
        self.directory, self.origin = Path(directory), origin
        self.directory.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            self.directory.chmod(0o700)
        self.lock = (self.directory / "executor.lock").open("a+b")
        try:
            if os.name == "nt":
                import msvcrt

                self.lock.seek(0)
                self.lock.write(b"0")
                self.lock.flush()
                self.lock.seek(0)
                msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lock.close()
            raise ProtocolError("EXECUTOR_ALREADY_RUNNING") from None
        try:
            self.db = durable_database(self.directory / "journal.sqlite3")
            self.db.executescript("""
            CREATE TABLE IF NOT EXISTS identity(id INTEGER PRIMARY KEY CHECK(id=1),
                binding TEXT NOT NULL, sequence INTEGER NOT NULL, journal TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS commands(command_id TEXT PRIMARY KEY,
                payload_hash TEXT NOT NULL, payload BLOB NOT NULL,
                state TEXT NOT NULL CHECK(state IN
                    ('RECEIVED','SEND_INTENT','UNKNOWN','FILLED','REJECTED')));
            CREATE TABLE IF NOT EXISTS events(event_id TEXT PRIMARY KEY, payload BLOB NOT NULL,
                acknowledged INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS journal_deals(deal_id TEXT PRIMARY KEY,
                command_id TEXT NOT NULL);
            """)
            binding = sha256(
                json_bytes(
                    {
                        "profile": profile.digest,
                        "request": sha256(request_key).hexdigest(),
                        "response": sha256(response_key).hexdigest(),
                        "origin": origin,
                    }
                )
            ).hexdigest()
            identity = self.db.execute("SELECT * FROM identity").fetchone()
            if identity and identity["binding"] != binding:
                raise ProtocolError("JOURNAL_BINDING_MISMATCH")
            if not identity:
                self.db.execute("INSERT INTO identity VALUES(1,?,0,?)", (binding, str(uuid4())))
            self.journal_id = self.db.execute("SELECT journal FROM identity WHERE id=1").fetchone()[
                0
            ]
            self.broker = PaperBroker(self.directory / "paper-broker.sqlite3")
            self.http = httpx.Client(
                base_url=origin,
                timeout=3,
                follow_redirects=False,
                trust_env=False,
                transport=transport,
            )
        except Exception:
            if hasattr(self, "db"):
                self.db.close()
            self.lock.close()
            raise

    def request(self, path, value):
        # A crash can leave a gap, never reuse a sequence for different bytes.
        self.db.execute("BEGIN IMMEDIATE")
        sequence = self.db.execute(
            "UPDATE identity SET sequence=sequence+1 WHERE id=1 RETURNING sequence"
        ).fetchone()[0]
        self.db.execute("COMMIT")
        now = int(datetime.now(UTC).timestamp())
        p = self.profile
        envelope = Envelope(
            p.account.environment_id,
            p.bridge_id,
            p.instance_id,
            p.key_id,
            sequence,
            now,
            now + 10,
            self.journal_id,
        )
        body = json_bytes(value)
        with self.http.stream(
            "POST", path, content=body, headers=envelope.headers(self.request_key, body, path)
        ) as response:
            chunks, length = [], 0
            for chunk in response.iter_bytes():
                length += len(chunk)
                if length > MAX_BODY:
                    raise ProtocolError("RESPONSE_TOO_LARGE")
                chunks.append(chunk)
            raw = b"".join(chunks)
            names = [
                name for name, _ in response.headers.multi_items() if name.startswith("x-trd-")
            ]
            if len(names) != len(set(names)) or "content-encoding" in response.headers:
                raise ProtocolError("INVALID_RESPONSE")
            Envelope.verify(
                response.headers,
                self.response_key,
                raw,
                path,
                now=int(datetime.now(UTC).timestamp()),
                direction="RESPONSE",
                status=response.status_code,
                expected=envelope,
            )
            result = strict_json(raw)
            if response.status_code != 200:
                raise ProtocolError("BRIDGE_REJECTED_REQUEST")
            return result

    def enqueue(self, command, payload_hash, kind, **economics):
        event = PaperEvent(
            event_id=uuid4(),
            command_id=command.command_id,
            command_hash=payload_hash,
            kind=kind,
            observed_at=datetime.now(UTC),
            **economics,
        )
        self.db.execute(
            "INSERT INTO events(event_id,payload) VALUES(?,?)",
            (str(event.event_id), json_bytes(event)),
        )

    def flush_events(self):
        rows = self.db.execute(
            "SELECT * FROM events WHERE acknowledged=0 ORDER BY rowid LIMIT 100"
        ).fetchall()
        if not rows:
            return
        while sum(len(r["payload"]) + 1 for r in rows) + 32 > MAX_BODY:
            rows.pop()
        batch = PaperEvents(
            events=tuple(PaperEvent.model_validate(strict_json(r["payload"])) for r in rows)
        )
        reply = self.request("/bridge/v1/events", batch)
        expected = {r["event_id"] for r in rows}
        if set(reply.get("accepted", [])) != expected:
            raise ProtocolError("EVENT_ACK_MISMATCH")
        self.db.execute("BEGIN IMMEDIATE")
        self.db.executemany(
            "UPDATE events SET acknowledged=1 WHERE event_id=?", [(i,) for i in expected]
        )
        self.db.execute("COMMIT")

    def preflight(self, command, snapshot, safety_epoch):
        if isinstance(command, PaperPositionCommand):
            with localcontext() as context:
                context.prec = 80
                fills = self.broker.deals(command.opening_command_id)
                entry_value = sum(
                    (Decimal(d["volume"]) * Decimal(d["price"]) for d in fills), Decimal(0)
                )
                if entry_value != command.entry_value:
                    raise ProtocolError("POSITION_ENTRY_EVIDENCE_MISMATCH")
            return position_preflight(command, snapshot, self.profile, safety_epoch)
        p = self.profile
        if (
            command.account != p.account
            or command.account_id != p.account_id
            or command.bridge_id != p.bridge_id
            or command.instance_id != p.instance_id
            or command.generation != p.generation
            or command.profile_hash != p.digest
            or command.safety_epoch != safety_epoch
            or command.expires_at <= datetime.now(UTC)
            or not snapshot.history_complete
            or not snapshot.portfolio_complete
            or snapshot.account != p.account
            or snapshot.currency != "USD"
        ):
            raise ProtocolError("LOCAL_PREFLIGHT_FAILED")
        instrument = next((i for i in snapshot.instruments if i.symbol == command.symbol), None)
        quote = next((q for q in snapshot.quotes if q.symbol == command.symbol), None)
        if instrument is None or quote is None or instrument.quote_currency != snapshot.currency:
            raise ProtocolError("LOCAL_PROFILE_UNSUPPORTED")
        approved = next((i for i in p.instruments if i.symbol == command.symbol), None)
        if approved is None or instrument.model_dump(
            exclude={"snapshot_id", "observed_at"}
        ) != approved.model_dump(exclude={"snapshot_id", "observed_at"}):
            raise ProtocolError("LOCAL_METADATA_MISMATCH")
        executable = quote.ask if command.side == "BUY" else quote.bid
        low, high = command.price_band_low, command.price_band_high
        if (
            not quote.market_open
            or not 0 <= (datetime.now(UTC) - quote.observed_at).total_seconds() < 5
            or not 0 <= (datetime.now(UTC) - snapshot.observed_at).total_seconds() < 15
            or not low <= executable <= high
            or low > high
            or high - low
            > 2 * min(command.max_deviation_points, p.max_deviation_points) * instrument.point
            or (quote.ask - quote.bid) / instrument.point
            > min(command.max_spread_points, p.max_spread_points)
            or command.volume % instrument.volume_step
            or command.volume < instrument.volume_min
            or command.volume > min(instrument.volume_max, p.policy.max_lots)
            or not instrument.attached_stops_supported
            or any(
                price % instrument.tick_size
                for price in (low, high, command.stop_loss, command.take_profit)
            )
        ):
            raise ProtocolError("LOCAL_MARKET_CHECK_FAILED")
        protective = (
            command.stop_loss < min(low, quote.bid) and command.take_profit > high
            if command.side == "BUY"
            else command.take_profit < low and command.stop_loss > max(high, quote.ask)
        )
        distance = (
            min(min(low, quote.bid) - command.stop_loss, command.take_profit - max(high, quote.ask))
            if command.side == "BUY"
            else min(
                command.stop_loss - max(high, quote.ask), min(low, quote.bid) - command.take_profit
            )
        )
        if (
            not protective
            or distance < instrument.stops_level_points * instrument.point
            or (
                instrument.freeze_level_points
                and distance <= instrument.freeze_level_points * instrument.point
            )
        ):
            raise ProtocolError("LOCAL_PROTECTION_FAILED")
        with localcontext() as context:
            context.prec = 80
            worst = high if command.side == "BUY" else low
            risk = ceil(
                (
                    (
                        abs(worst - command.stop_loss)
                        + instrument.slippage_buffer_points * instrument.point
                    )
                    * instrument.contract_size
                    + instrument.commission_per_lot_account
                )
                * command.volume
            )
            if (
                risk > command.max_risk
                or command.max_risk > snapshot.equity * p.policy.max_risk_per_trade
            ):
                raise ProtocolError("LOCAL_RISK_FAILED")
        return executable

    def accept(self, payload: bytes, payload_hash: str, snapshot, safety_epoch, *, crash=None):
        if sha256(payload).hexdigest() != payload_hash:
            raise ProtocolError("COMMAND_HASH_MISMATCH")
        command = parse_paper_command(payload)
        existing = self.db.execute(
            "SELECT * FROM commands WHERE command_id=?", (str(command.command_id),)
        ).fetchone()
        if existing:
            if existing["payload_hash"] != payload_hash:
                raise ProtocolError("COMMAND_IDENTITY_CONFLICT")
            if existing["state"] in {"SEND_INTENT", "UNKNOWN"}:
                self.reconcile(command.command_id)
            return existing["state"]
        # Persist receipt and then intent in separate durable commits before any broker action.
        self.db.execute("BEGIN IMMEDIATE")
        self.db.execute(
            "INSERT INTO commands VALUES(?,?,?,'RECEIVED')",
            (str(command.command_id), payload_hash, payload),
        )
        self.enqueue(command, payload_hash, "RECEIVED")
        self.db.execute("COMMIT")
        return self.execute_received(command, payload_hash, snapshot, safety_epoch, crash=crash)

    def execute_received(self, command, payload_hash, snapshot, safety_epoch, *, crash=None):
        try:
            price = self.preflight(command, snapshot, safety_epoch)
        except ProtocolError:
            self.db.execute("BEGIN IMMEDIATE")
            self.db.execute(
                "UPDATE commands SET state='REJECTED' WHERE command_id=?",
                (str(command.command_id),),
            )
            self.enqueue(command, payload_hash, "REJECTED")
            self.db.execute("COMMIT")
            return "REJECTED"
        self.db.execute("BEGIN IMMEDIATE")
        claimed = self.db.execute(
            "UPDATE commands SET state='SEND_INTENT' WHERE command_id=? AND state='RECEIVED'",
            (str(command.command_id),),
        )
        if claimed.rowcount != 1:
            self.db.execute("ROLLBACK")
            raise ProtocolError("SEND_INTENT_ALREADY_CLAIMED")
        self.enqueue(command, payload_hash, "SEND_INTENT")
        self.db.execute("COMMIT")
        if crash == "after_intent":
            raise SimulatedCrash("AFTER_DURABLE_INTENT")
        self.broker.submit(command, payload_hash, price=price)
        if crash == "after_fill":
            raise SimulatedCrash("AFTER_BROKER_FILL")
        self.reconcile(command.command_id, recovered=False)
        return "FILLED"

    def reconcile(self, command_id, *, recovered=True):
        row = self.db.execute(
            "SELECT * FROM commands WHERE command_id=?", (str(command_id),)
        ).fetchone()
        command = parse_paper_command(row["payload"])
        if isinstance(command, PaperPositionCommand):
            self.reconcile_position(row, command, recovered)
            return
        orders = self.broker.db.execute(
            "SELECT * FROM broker_orders WHERE command_id=?", (str(command_id),)
        ).fetchall()
        deals = self.broker.deals(command_id)
        known = (
            len(orders) == 1
            and orders[0]["command_hash"] == row["payload_hash"]
            and sum((Decimal(d["volume"]) for d in deals), Decimal(0)) == command.volume
        )
        self.db.execute("BEGIN IMMEDIATE")
        try:
            if known:
                for deal in deals:
                    if self.db.execute(
                        "SELECT 1 FROM journal_deals WHERE deal_id=?", (str(deal["ticket"]),)
                    ).fetchone():
                        continue
                    self.enqueue(
                        command,
                        row["payload_hash"],
                        "RECONCILED_FILL" if recovered else "FILL",
                        broker_ticket=str(deal["order_ticket"]),
                        broker_deal_id=str(deal["ticket"]),
                        position_identifier=str(deal["order_ticket"]),
                        volume=deal["volume"],
                        price=deal["price"],
                    )
                    self.db.execute(
                        "INSERT INTO journal_deals VALUES(?,?)",
                        (str(deal["ticket"]), str(command_id)),
                    )
                self.db.execute(
                    "UPDATE commands SET state='FILLED' WHERE command_id=?", (str(command_id),)
                )
            elif row["state"] != "UNKNOWN":
                self.enqueue(command, row["payload_hash"], "UNKNOWN")
                self.db.execute(
                    "UPDATE commands SET state='UNKNOWN' WHERE command_id=?", (str(command_id),)
                )
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def reconcile_position(self, row, command, recovered):
        results = self.broker.position_results(command.command_id)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            if len(results) == 1 and results[0]["command_hash"] == row["payload_hash"]:
                result = results[0]
                value = strict_json(result["outcome"])
                value.pop("observed_at")
                kind = value.pop("kind")
                if recovered:
                    kind = "RECONCILED_CLOSE" if kind == "POSITION_CLOSED" else "RECONCILED_STOPS"
                identity = "operation:" + str(result["ticket"])
                if not self.db.execute(
                    "SELECT 1 FROM journal_deals WHERE deal_id=?", (identity,)
                ).fetchone():
                    if command.action == "CLOSE":
                        value["broker_deal_id"] = str(10**16 + result["ticket"])
                    self.enqueue(
                        command,
                        row["payload_hash"],
                        kind,
                        operation_id=str(result["ticket"]),
                        **value,
                    )
                    self.db.execute(
                        "INSERT INTO journal_deals VALUES(?,?)", (identity, str(command.command_id))
                    )
                self.db.execute(
                    "UPDATE commands SET state='FILLED' WHERE command_id=?",
                    (str(command.command_id),),
                )
            elif row["state"] != "UNKNOWN":
                self.enqueue(command, row["payload_hash"], "UNKNOWN")
                self.db.execute(
                    "UPDATE commands SET state='UNKNOWN' WHERE command_id=?",
                    (str(command.command_id),),
                )
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def recover(self):
        for row in self.db.execute(
            "SELECT command_id FROM commands WHERE state IN ('SEND_INTENT','UNKNOWN')"
        ).fetchall():
            self.reconcile(row["command_id"])

    def cycle(self, snapshot, *, crash=None):
        self.recover()
        self.flush_events()
        with localcontext() as context:
            context.prec = 80
            pnl = self.broker.realized_pnl(self.profile)
            snapshot = snapshot.model_copy(
                update={
                    "positions": self.broker.positions(),
                    "equity": snapshot.equity + pnl,
                    "free_margin": snapshot.free_margin + pnl,
                }
            )
        self.request("/bridge/v1/snapshot", snapshot)
        reply = self.request("/bridge/v1/poll", {})
        if reply.get("command"):
            try:
                payload = b64decode(reply["command"], validate=True)
            except (ValueError, TypeError):
                raise ProtocolError("INVALID_COMMAND_ENCODING") from None
            self.accept(
                payload, reply["command_hash"], snapshot, reply["safety_epoch"], crash=crash
            )
            self.flush_events()
        return reply["status"]

    def close(self):
        self.http.close()
        self.broker.close()
        self.db.close()
        self.lock.close()
