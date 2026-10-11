"""Strict, immutable contracts; JSON represents money and broker identities as strings."""

from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator


def exact_decimal(value: object) -> object:
    if not isinstance(value, (str, Decimal)):
        raise ValueError("financial values require decimal strings or Decimal")
    return value


ExactDecimal = Annotated[Decimal, BeforeValidator(exact_decimal)]
PositiveDecimal = Annotated[
    ExactDecimal, Field(gt=0, allow_inf_nan=False, max_digits=28, decimal_places=10)
]
NonnegativeDecimal = Annotated[
    ExactDecimal, Field(ge=0, allow_inf_nan=False, max_digits=28, decimal_places=10)
]
Fraction = Annotated[ExactDecimal, Field(gt=0, le=1, allow_inf_nan=False, decimal_places=10)]
Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]
Checksum = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class Contract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def aware_timestamps(cls, value: object) -> object:
        if isinstance(value, datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("timestamps must include a timezone")
            return value.astimezone(UTC)
        return value


class AccountIdentity(Contract):
    environment_id: Identifier
    broker_server: str = Field(min_length=1, max_length=128)
    login: str = Field(pattern=r"^[0-9]{1,32}$")
    mode: Literal["paper", "demo", "live"]


class Proposal(Contract):
    symbol: str = Field(min_length=1, max_length=64)
    side: Literal["BUY", "SELL"]
    entry: PositiveDecimal
    stop_loss: PositiveDecimal
    take_profit: PositiveDecimal
    expires_at: datetime

    @model_validator(mode="after")
    def protective_prices(self) -> "Proposal":
        prices = (self.stop_loss, self.entry, self.take_profit)
        if self.side == "SELL":
            prices = tuple(reversed(prices))
        if not prices[0] < prices[1] < prices[2]:
            raise ValueError("protective prices must match the proposed side")
        return self


class RiskPolicy(Contract):
    max_risk_per_trade: Fraction = Decimal("0.005")
    max_daily_loss: Fraction = Decimal("0.02")
    max_total_open_risk: Fraction = Decimal("0.02")
    max_open_positions: int = Field(default=2, strict=True, ge=1, le=100)
    max_lots: PositiveDecimal = Decimal("0.50")
    max_effective_leverage: PositiveDecimal = Decimal("5")
    require_stop_loss: Literal[True] = True
    require_take_profit: Literal[True] = True

    @field_validator("require_stop_loss", "require_take_profit", mode="before")
    @classmethod
    def mandatory_protection(cls, value: object) -> object:
        if value is not True:
            raise ValueError("protective stops are mandatory")
        return value

    def within(self, ceiling: "RiskPolicy") -> None:
        for field in (
            "max_risk_per_trade",
            "max_daily_loss",
            "max_total_open_risk",
            "max_open_positions",
            "max_lots",
            "max_effective_leverage",
        ):
            if getattr(self, field) > getattr(ceiling, field):
                raise ValueError("configuration exceeds the server safety envelope")


class ModelDefinition(Contract):
    id: Identifier
    provider: Literal["mock", "openrouter", "openai", "anthropic", "google", "moonshot", "typesafe"]
    model_name: str = Field(min_length=1, max_length=128)
    enabled: bool = Field(strict=True)
    schema_version: int = Field(strict=True, ge=1)
    max_output_tokens: int = Field(strict=True, ge=1, le=100_000)
    input_price_per_million: NonnegativeDecimal
    output_price_per_million: NonnegativeDecimal
    pricing_version: str = Field(min_length=1, max_length=64)
    currency: Literal["USD"] = "USD"
    input_token_limit: int = Field(default=0, strict=True, ge=0, le=1_000_000)
    provider_slug: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9_/-]{0,63}$")
    provider_label: str | None = Field(default=None, min_length=1, max_length=96)
    accepted_environment_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    accepted_until: datetime | None = None

    @model_validator(mode="after")
    def bounded_external_profile(self):
        if self.accepted_until is not None and self.accepted_until.utcoffset() is None:
            raise ValueError("acceptance expiry must be timezone aware")
        if self.provider == "openrouter":
            import re

            if (
                not re.fullmatch(r"[a-z0-9_.-]+/[a-z0-9_.-]+", self.model_name)
                or not self.provider_slug
                or not self.provider_label
                or self.input_token_limit <= 0
                or self.input_price_per_million <= 0
                or self.output_price_per_million <= 0
            ):
                raise ValueError("OpenRouter requires a paid model and reviewed routing profile")
        return self


class AgentConfiguration(Contract):
    enabled: bool = Field(default=False, strict=True)
    primary_model_id: Identifier
    fallback_model_ids: tuple[Identifier, ...] = ()
    prompt_version: int = Field(strict=True, ge=1)
    timeout_seconds: int = Field(default=30, strict=True, ge=1, le=120)
    max_output_tokens: int = Field(default=1024, strict=True, ge=1, le=100_000)
    max_cost_usd: NonnegativeDecimal = Decimal("0")
    required_schema_version: int = Field(default=1, strict=True, ge=1)

    @model_validator(mode="after")
    def bounded_fallbacks(self) -> "AgentConfiguration":
        ids = (self.primary_model_id, *self.fallback_model_ids)
        if len(ids) > 3 or len(set(ids)) != len(ids):
            raise ValueError("fallbacks must be unique and limited to three total attempts")
        return self

    def validate_models(self, models: dict[str, ModelDefinition]) -> None:
        for identifier in (self.primary_model_id, *self.fallback_model_ids):
            model = models.get(identifier)
            if (
                model is None
                or not model.enabled
                or model.schema_version != self.required_schema_version
                or self.max_output_tokens > model.max_output_tokens
            ):
                raise ValueError("model is unavailable or incompatible with this agent")


class LifecycleChange(Contract):
    event_id: UUID
    expected_revision: int = Field(strict=True, ge=1)
    after: str
    evidence: str = "OBSERVATION"


def fingerprint(value: Contract) -> str:
    return sha256(value.model_dump_json().encode("utf-8")).hexdigest()
