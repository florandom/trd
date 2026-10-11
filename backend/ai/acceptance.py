"""Operator-owned, expiring OpenRouter acceptance. Never activated by a browser or key alone."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import Field

from backend.ai.openrouter import OpenRouterProvider
from backend.ai.providers import MockProvider
from backend.domain.config import AiSettings
from backend.domain.contracts import Contract, ModelDefinition


class OpenRouterManifest(Contract):
    schema_version: Literal[1]
    environment_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    reviewed_at: datetime
    expires_at: datetime
    models: tuple[ModelDefinition, ...] = Field(min_length=1, max_length=8)

    def check(self, environment: str) -> None:
        now = datetime.now(UTC)
        if (
            self.environment_id != environment
            or any(date.utcoffset() is None for date in (self.reviewed_at, self.expires_at))
            or not self.reviewed_at <= now < self.expires_at
            or self.expires_at - self.reviewed_at > timedelta(days=7)
            or len({model.id for model in self.models}) != len(self.models)
            or any(model.provider != "openrouter" or not model.enabled for model in self.models)
        ):
            raise ValueError("Invalid or expired OpenRouter manifest")


class OpenRouterAcceptance(Contract):
    schema_version: Literal[1]
    contract_version: Literal["openrouter-advisory-v1"]
    environment_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    credential_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    accepted_at: datetime
    expires_at: datetime
    models: tuple[ModelDefinition, ...] = Field(min_length=1, max_length=8)
    checks: Literal["catalog-schema-routing-usage-cost-synthetic-wait"]

    def check(self, environment: str, key: str | None = None) -> None:
        now = datetime.now(UTC)
        if (
            self.environment_id != environment
            or any(date.utcoffset() is None for date in (self.accepted_at, self.expires_at))
            or not self.accepted_at <= now < self.expires_at
            or self.expires_at - self.accepted_at > timedelta(days=7)
            or len({model.id for model in self.models}) != len(self.models)
            or any(
                model.provider != "openrouter"
                or not model.enabled
                or model.accepted_environment_id != environment
                or model.accepted_until != self.expires_at
                for model in self.models
            )
            or (
                key is not None
                and sha256(("openrouter:" + key).encode()).hexdigest() != self.credential_sha256
            )
        ):
            raise ValueError("OpenRouter acceptance unavailable for this environment or credential")


def read_document(path: Path, contract):
    if path.stat().st_size > 131_072:
        raise ValueError("Oversized operator manifest")
    from backend.ai.openrouter import strict_document

    return contract.model_validate(strict_document(path.read_bytes()))


def configured_provider(settings: AiSettings):
    if settings.ai_provider_mode == "mock":
        return MockProvider()
    receipt = read_document(settings.openrouter_acceptance_path, OpenRouterAcceptance)
    receipt.check(settings.environment_id, settings.openrouter_api_key.get_secret_value())
    if any(model.input_token_limit > settings.ai_hard_max_input_tokens for model in receipt.models):
        raise ValueError("Accepted model exceeds the deployed input ceiling")
    return OpenRouterProvider(
        settings.openrouter_api_key, {model.id: model for model in receipt.models}
    )
