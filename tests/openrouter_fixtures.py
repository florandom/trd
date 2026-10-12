"""Synthetic paid-model contract fixtures. No actual account, key or source evidence."""

import json
from datetime import UTC, datetime, timedelta
from time import monotonic

from backend.ai.providers import ProviderRequest
from backend.domain.contracts import ModelDefinition, Proposal

KEY = "synthetic-openrouter-account-key"


def model(**changes):
    fields = dict(
        id="or-fixture-provider-v1",
        provider="openrouter",
        model_name="fixture/model-v1",
        enabled=True,
        schema_version=1,
        max_output_tokens=128,
        input_token_limit=4096,
        input_price_per_million="1",
        output_price_per_million="2",
        pricing_version="test-v1",
        provider_slug="fixture",
        provider_label="Fixture",
        accepted_environment_id="test",
        accepted_until=datetime.now(UTC) + timedelta(hours=1),
    )
    fields.update(changes)
    return ModelDefinition(**fields)


def request(profile=None, **changes):
    fields = dict(
        stage="MARKET_ANALYST",
        model=profile or model(),
        prompt="Synthetic advisory only",
        proposal=Proposal(
            symbol="EURUSD",
            side="BUY",
            entry="1.1",
            stop_loss="1.09",
            take_profit="1.12",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        ),
        max_output_tokens=64,
        deadline=monotonic() + 10,
    )
    fields.update(changes)
    return ProviderRequest(**fields)


def response(**changes):
    fields = dict(
        id="gen-synthetic-fixture",
        model="fixture/model-v1",
        provider="Fixture",
        usage={
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
            "cost": "0.0000200000",
        },
        choices=[
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "schema_version": 1,
                            "action": "WAIT",
                            "reason_codes": ["NO_MARKET_CONTEXT"],
                        }
                    ),
                },
            }
        ],
    )
    fields.update(changes)
    return fields


def catalog(profile):
    return {
        "data": {
            "id": profile.model_name,
            "endpoints": [
                {
                    "tag": profile.provider_slug,
                    "provider_name": profile.provider_label,
                    "status": 0,
                    "context_length": profile.input_token_limit,
                    "max_completion_tokens": profile.max_output_tokens,
                    "pricing": {"prompt": "0.000001", "completion": "0.000002", "request": "0"},
                    "supported_parameters": ["max_tokens", "response_format", "structured_outputs"],
                }
            ],
        }
    }
