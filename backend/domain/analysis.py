"""Offline advisory analysis. No broker economics, execution authority or network calls."""

import re
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from backend.domain.contracts import Checksum, Contract, NonnegativeDecimal, Proposal

ROUTE_VERSION = "structured-fx-v1"
SYMBOLS = frozenset({"EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD"})
STAGES = ("SIGNAL_CLASSIFIER", "SIGNAL_PARSER", "MARKET_ANALYST", "DECISION_AGENT")


class Reason(StrEnum):
    NO_SIGNAL = "NO_SIGNAL"
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    UNSUPPORTED_SYMBOL = "UNSUPPORTED_SYMBOL"
    INVALID_PRICES = "INVALID_PRICES"
    REVIEW_ONLY = "REVIEW_ONLY"
    STALE_MESSAGE = "STALE_MESSAGE"
    FUTURE_MESSAGE = "FUTURE_MESSAGE"
    EVIDENCE_UNAVAILABLE = "EVIDENCE_UNAVAILABLE"
    AGENT_DISABLED = "AGENT_DISABLED"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    PROMPT_UNAVAILABLE = "PROMPT_UNAVAILABLE"
    CONFIG_CHANGED = "CONFIG_CHANGED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    PROVIDER_DISABLED = "PROVIDER_DISABLED"
    PROVIDER_REFUSAL = "PROVIDER_REFUSAL"
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    PROVIDER_RATE_LIMIT = "PROVIDER_RATE_LIMIT"
    PROVIDER_QUOTA = "PROVIDER_QUOTA"
    PROVIDER_INCOMPLETE = "PROVIDER_INCOMPLETE"
    INVALID_OUTPUT = "INVALID_OUTPUT"
    UNKNOWN_USAGE = "UNKNOWN_USAGE"
    MOCK_ONLY = "MOCK_ONLY"
    NO_MARKET_CONTEXT = "NO_MARKET_CONTEXT"
    RISK_NOT_IMPLEMENTED = "RISK_NOT_IMPLEMENTED"
    RISK_GATEWAY_UNAVAILABLE = "RISK_GATEWAY_UNAVAILABLE"


class AnalysisJob(Contract):
    type: Literal["telegram_message"]
    schema_version: Literal[1]
    message_id: UUID
    message_version: int = Field(strict=True, ge=1)
    source_id: UUID
    source_version: int = Field(strict=True, ge=1)
    review_only: bool = Field(strict=True)


class ParseResult(Contract):
    classification: Literal["NOISE", "STRUCTURED", "AMBIGUOUS", "REVIEW"]
    outcome: Literal["IGNORED", "ESCALATED", "EXPIRED", "WAITING", "REJECTED_AI"]
    reason_codes: tuple[Reason, ...] = Field(min_length=1, max_length=12)
    proposal: Proposal | None = None


# One full message, one exact symbol and one TP. No inference, suffix matching,
# price ranges, locale-dependent numbers, tool text or extra instructions.
_PRICE = r"([0-9]{1,12}(?:\.[0-9]{1,10})?)"
_GRAMMAR = re.compile(
    rf"(BUY|SELL)[ \t\r\n]+([A-Z]{{6}})[ \t\r\n]+ENTRY[ \t\r\n]+{_PRICE}"
    rf"[ \t\r\n]+SL[ \t\r\n]+{_PRICE}[ \t\r\n]+TP[ \t\r\n]+{_PRICE}",
    re.ASCII,
)
_CANDIDATE = re.compile(r"\b(BUY|SELL|SL|TP|ENTRY|LONG|SHORT|ACQUISTO|VENDITA|STOP)\b", re.I)


def parse_message(
    body: str | None,
    *,
    published_at: datetime,
    now: datetime,
    max_age_seconds: int = 900,
    review_only: bool = False,
    reply: bool = False,
) -> ParseResult:
    if any(t.tzinfo is None or t.utcoffset() is None for t in (now, published_at)):
        raise ValueError("aware timestamps required")
    if not 30 <= max_age_seconds <= 3600:
        raise ValueError("unsupported freshness window")
    if review_only or reply:
        return ParseResult(
            classification="REVIEW", outcome="ESCALATED", reason_codes=(Reason.REVIEW_ONLY,)
        )
    age = (now - published_at).total_seconds()
    if age < -5:
        return ParseResult(
            classification="AMBIGUOUS", outcome="EXPIRED", reason_codes=(Reason.FUTURE_MESSAGE,)
        )
    if age >= max_age_seconds:
        return ParseResult(
            classification="AMBIGUOUS", outcome="EXPIRED", reason_codes=(Reason.STALE_MESSAGE,)
        )
    if body is None:
        return ParseResult(
            classification="AMBIGUOUS",
            outcome="ESCALATED",
            reason_codes=(Reason.EVIDENCE_UNAVAILABLE,),
        )
    if len(body.encode("utf-8")) > 16_384 or "\x00" in body:
        return ParseResult(
            classification="AMBIGUOUS",
            outcome="ESCALATED",
            reason_codes=(Reason.UNSUPPORTED_FORMAT,),
        )
    match = _GRAMMAR.fullmatch(body.strip(" \t\r\n"))
    if not match:
        candidate = bool(_CANDIDATE.search(body))
        return ParseResult(
            classification="AMBIGUOUS" if candidate else "NOISE",
            outcome="ESCALATED" if candidate else "IGNORED",
            reason_codes=(Reason.UNSUPPORTED_FORMAT if candidate else Reason.NO_SIGNAL,),
        )
    side, symbol, entry, stop, target = match.groups()
    if symbol not in SYMBOLS:
        return ParseResult(
            classification="AMBIGUOUS",
            outcome="ESCALATED",
            reason_codes=(Reason.UNSUPPORTED_SYMBOL,),
        )
    try:
        proposal = Proposal(
            symbol=symbol,
            side=side,
            entry=entry,
            stop_loss=stop,
            take_profit=target,
            expires_at=published_at + timedelta(seconds=max_age_seconds),
        )
    except ValueError:
        return ParseResult(
            classification="AMBIGUOUS", outcome="ESCALATED", reason_codes=(Reason.INVALID_PRICES,)
        )
    return ParseResult(
        classification="STRUCTURED",
        outcome="WAITING",
        proposal=proposal,
        reason_codes=(Reason.RISK_GATEWAY_UNAVAILABLE,),
    )


class AgentResult(Contract):
    schema_version: Literal[1]
    action: Literal["PROPOSE", "WAIT", "REJECT", "ESCALATE"]
    reason_codes: tuple[Reason, ...] = Field(min_length=1, max_length=8)

    @model_validator(mode="before")
    @classmethod
    def exact_schema_version(cls, value):
        if not isinstance(value, dict) or type(value.get("schema_version")) is not int:
            raise ValueError("schema version must be an integer")
        return value


class ProviderUsage(Contract):
    input_tokens: int = Field(strict=True, ge=0, le=1_000_000)
    output_tokens: int = Field(strict=True, ge=0, le=1_000_000)
    cached_tokens: int = Field(default=0, strict=True, ge=0)
    reasoning_tokens: int = Field(default=0, strict=True, ge=0)
    cost_usd: NonnegativeDecimal | None = None

    @model_validator(mode="after")
    def breakdowns_are_subsets(self):
        if self.cached_tokens > self.input_tokens or self.reasoning_tokens > self.output_tokens:
            raise ValueError("invalid usage breakdown")
        return self


class CostLimits(Contract):
    daily_usd: NonnegativeDecimal = Decimal("0")
    monthly_usd: NonnegativeDecimal = Decimal("0")
    request_usd: NonnegativeDecimal = Decimal("0")
    agent_daily_usd: NonnegativeDecimal = Decimal("0")


class AnalysisResult(ParseResult):
    route_version: Literal["structured-fx-v1"] = ROUTE_VERSION
    input_hash: Checksum
    trace_id: UUID
    config_versions: dict[str, int] = Field(default_factory=dict)


def estimated_cost(
    input_tokens: int, output_tokens: int, input_price: Decimal, output_price: Decimal
) -> Decimal:
    if min(input_tokens, output_tokens, input_price, output_price) < 0:
        raise ValueError("negative cost inputs")
    return (
        (input_tokens * input_price + output_tokens * output_price) / Decimal(1_000_000)
    ).quantize(Decimal("0.0000000001"), rounding="ROUND_CEILING")
