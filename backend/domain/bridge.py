"""Paper-only, byte-authenticated bridge protocol. No external transport authority."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from hmac import compare_digest, new
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from backend.domain.contracts import (
    AccountIdentity,
    Checksum,
    Contract,
    NonnegativeDecimal,
    PositiveDecimal,
    RiskPolicy,
    fingerprint,
)
from backend.domain.risk_contracts import (
    Currency,
    FxInstrument,
    Quote,
    SessionCalendar,
    SignedMoney,
    SymbolMapping,
)

PATHS = frozenset({"/bridge/v1/snapshot", "/bridge/v1/poll", "/bridge/v1/events"})
MAX_BODY = 65_536
MAX_SEQUENCE = 2**63 - 1
HEADER_NAMES = (
    "environment",
    "bridge",
    "instance",
    "key",
    "sequence",
    "issued",
    "expires",
    "journal",
)
TOKEN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


class ProtocolError(ValueError):
    """Stable redacted failure; never render a submitted body or credential."""


def strict_json(body: bytes) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ProtocolError("DUPLICATE_FIELD")
            result[key] = value
        return result

    def invalid(_value):
        raise ProtocolError("INVALID_NUMBER")

    if not body or len(body) > MAX_BODY or b"\x00" in body or body.startswith(b"\xef\xbb\xbf"):
        raise ProtocolError("INVALID_BODY")
    try:
        value = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_float=invalid,
            parse_constant=invalid,
        )

        def bounded(item, depth=0):
            if depth > 12:
                raise ProtocolError("INVALID_BODY")
            if isinstance(item, dict):
                if len(item) > 128:
                    raise ProtocolError("INVALID_BODY")
                for key, child in item.items():
                    bounded(key, depth + 1)
                    bounded(child, depth + 1)
            elif isinstance(item, list):
                if len(item) > 1000:
                    raise ProtocolError("INVALID_BODY")
                for child in item:
                    bounded(child, depth + 1)
            elif isinstance(item, str):
                if len(item) > 8192 or any(ord(c) < 32 for c in item):
                    raise ProtocolError("INVALID_BODY")
                item.encode("utf-8")
            elif type(item) is int and abs(item) > MAX_SEQUENCE:
                raise ProtocolError("INVALID_NUMBER")

        bounded(value)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ProtocolError("INVALID_BODY") from exc
    if not isinstance(value, dict):
        raise ProtocolError("INVALID_BODY")
    return value


def json_bytes(value: dict | Contract) -> bytes:
    if isinstance(value, Contract):
        value = value.model_dump(mode="json")
    body = json.dumps(value, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode()
    strict_json(body)
    return body


@dataclass(frozen=True)
class Envelope:
    environment: str
    bridge: str
    instance: str
    key: str
    sequence: int
    issued: int
    expires: int
    journal: str = "protocol-fixture"

    def message(self, body: bytes, path: str, *, direction="REQUEST", status=0) -> bytes:
        if path not in PATHS or direction not in {"REQUEST", "RESPONSE"}:
            raise ProtocolError("INVALID_CONTEXT")
        if any(
            not TOKEN.fullmatch(v)
            for v in (self.environment, self.bridge, self.instance, self.key, self.journal)
        ):
            raise ProtocolError("INVALID_CONTEXT")
        if not 1 <= self.sequence <= MAX_SEQUENCE or not 0 < self.expires - self.issued <= 10:
            raise ProtocolError("INVALID_CONTEXT")
        return (
            f"TRD-BRIDGE-V1\n{direction}\n{self.environment}\n{self.bridge}\n{self.instance}\n"
            f"{self.key}\n{self.journal}\nPOST\n{path}\n{status}\n{self.sequence}\n{self.issued}\n{self.expires}\n"
            f"{sha256(body).hexdigest()}\n"
        ).encode("ascii")

    def headers(self, secret: bytes, body: bytes, path: str, *, direction="REQUEST", status=0):
        values = (
            self.environment,
            self.bridge,
            self.instance,
            self.key,
            self.sequence,
            self.issued,
            self.expires,
            self.journal,
        )
        headers = {f"x-trd-{k}": str(v) for k, v in zip(HEADER_NAMES, values, strict=True)}
        headers["x-trd-signature"] = new(
            secret, self.message(body, path, direction=direction, status=status), "sha256"
        ).hexdigest()
        headers["content-type"] = "application/json"
        return headers

    @classmethod
    def verify(
        cls,
        headers,
        secret: bytes,
        body: bytes,
        path: str,
        *,
        now: int,
        direction="REQUEST",
        status=0,
        expected=None,
    ):
        try:
            values = [headers[f"x-trd-{k}"] for k in HEADER_NAMES]
            if any(not re.fullmatch(r"[1-9][0-9]{0,18}", v) for v in values[4:7]):
                raise ValueError
            envelope = cls(*values[:4], *(int(v) for v in values[4:7]), values[7])
            message = envelope.message(body, path, direction=direction, status=status)
            if not envelope.issued <= now < envelope.expires:
                raise ValueError
            signature = headers["x-trd-signature"]
            if not re.fullmatch(r"[a-f0-9]{64}", signature) or not compare_digest(
                new(secret, message, "sha256").hexdigest(), signature
            ):
                raise ValueError
            if expected is not None and (
                envelope.environment,
                envelope.bridge,
                envelope.instance,
                envelope.key,
                envelope.sequence,
                envelope.journal,
            ) != (
                expected.environment,
                expected.bridge,
                expected.instance,
                expected.key,
                expected.sequence,
                expected.journal,
            ):
                raise ValueError
            return envelope
        except (KeyError, ValueError, TypeError):
            raise ProtocolError("AUTHENTICATION_FAILED") from None


class PaperProfile(Contract):
    """Operator-enrolled immutable local sandbox, never a real broker account."""

    account_id: UUID
    account: AccountIdentity
    bridge_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    instance_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    key_id: str = Field(default="paper-v1", pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    generation: int = Field(default=1, strict=True, ge=1)
    source_ids: tuple[UUID, ...] = Field(min_length=1, max_length=32)
    instruments: tuple[FxInstrument, ...] = Field(min_length=1, max_length=16)
    mappings: tuple[SymbolMapping, ...] = Field(min_length=1, max_length=16)
    calendar: SessionCalendar
    policy: RiskPolicy = RiskPolicy()
    max_spread_points: NonnegativeDecimal = Decimal("30")
    max_deviation_points: NonnegativeDecimal = Decimal("20")

    @model_validator(mode="after")
    def local_only(self):
        if self.account.mode != "paper" or self.account.broker_server != "TRD-PAPER-SIMULATOR":
            raise ValueError("paper enrollment requires the synthetic broker identity")
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("duplicate source")
        if {i.symbol for i in self.instruments} != {m.broker_symbol for m in self.mappings}:
            raise ValueError("approved instrument mappings required")
        if len({i.symbol for i in self.instruments}) != len(self.instruments):
            raise ValueError("duplicate instrument")
        return self

    @property
    def digest(self):
        return fingerprint(self)


class PaperPosition(Contract):
    broker_identifier: str = Field(pattern=r"^[0-9]{1,32}$")
    command_id: UUID | None = None
    symbol: str = Field(min_length=1, max_length=64)
    side: Literal["BUY", "SELL"]
    volume: PositiveDecimal
    entry_price: PositiveDecimal
    stop_loss: PositiveDecimal | None
    take_profit: PositiveDecimal | None


class PaperSnapshot(Contract):
    snapshot_id: UUID
    account: AccountIdentity
    observed_at: datetime
    currency: Currency
    equity: NonnegativeDecimal
    free_margin: NonnegativeDecimal
    broker_leverage: PositiveDecimal
    position_mode: Literal["hedging", "netting"]
    history_complete: bool = Field(strict=True)
    portfolio_complete: bool = Field(strict=True)
    opening_equity: PositiveDecimal
    net_cash_flow: SignedMoney
    positions: tuple[PaperPosition, ...] = Field(max_length=1000)
    quotes: tuple[Quote, ...] = Field(max_length=16)
    instruments: tuple[FxInstrument, ...] = Field(max_length=16)

    @model_validator(mode="after")
    def unique_observations(self):
        for items, key in (
            (self.positions, "broker_identifier"),
            (self.quotes, "symbol"),
            (self.instruments, "symbol"),
        ):
            if len({getattr(i, key) for i in items}) != len(items):
                raise ValueError("duplicate observation")
        if len({p.command_id for p in self.positions if p.command_id is not None}) != len(
            [p for p in self.positions if p.command_id is not None]
        ):
            raise ValueError("ambiguous command ownership")
        return self


class PaperCommand(Contract):
    command_id: UUID
    trace_id: UUID
    approval_id: UUID
    reservation_id: UUID
    account_id: UUID
    account: AccountIdentity
    bridge_id: str
    instance_id: str
    generation: int = Field(strict=True, ge=1)
    profile_hash: Checksum
    safety_epoch: int = Field(strict=True, ge=1)
    policy_version: int = Field(strict=True, ge=1)
    signal_id: UUID
    signal_version: int = Field(strict=True, ge=1)
    source_id: UUID
    source_version: int = Field(strict=True, ge=1)
    symbol: str
    side: Literal["BUY", "SELL"]
    volume: PositiveDecimal
    stop_loss: PositiveDecimal
    take_profit: PositiveDecimal
    price_band_low: PositiveDecimal
    price_band_high: PositiveDecimal
    max_spread_points: NonnegativeDecimal
    max_deviation_points: NonnegativeDecimal
    max_risk: PositiveDecimal
    expires_at: datetime


class PaperEvent(Contract):
    event_id: UUID
    command_id: UUID
    command_hash: Checksum
    kind: Literal[
        "RECEIVED", "SEND_INTENT", "ACCEPTED", "FILL", "RECONCILED_FILL", "UNKNOWN", "REJECTED"
    ]
    observed_at: datetime
    broker_ticket: str | None = Field(default=None, pattern=r"^[0-9]{1,32}$")
    broker_deal_id: str | None = Field(default=None, pattern=r"^[0-9]{1,32}$")
    position_identifier: str | None = Field(default=None, pattern=r"^[0-9]{1,32}$")
    volume: PositiveDecimal | None = None
    price: PositiveDecimal | None = None

    @model_validator(mode="after")
    def economic_evidence(self):
        if self.kind in {"FILL", "RECONCILED_FILL"} and any(
            v is None
            for v in (
                self.broker_ticket,
                self.broker_deal_id,
                self.position_identifier,
                self.volume,
                self.price,
            )
        ):
            raise ValueError("fill requires broker economic evidence")
        if self.kind not in {"FILL", "RECONCILED_FILL"} and any(
            v is not None
            for v in (self.broker_deal_id, self.position_identifier, self.volume, self.price)
        ):
            raise ValueError("transport event cannot report financial evidence")
        return self


class PaperEvents(Contract):
    events: tuple[PaperEvent, ...] = Field(min_length=1, max_length=100)


class Poll(Contract):
    pass
