"""Bounded provider contracts; no tools, arbitrary URLs or private reasoning storage."""

import json
from dataclasses import dataclass
from time import monotonic
from typing import Protocol

import httpx

from backend.domain.analysis import AgentResult, ProviderUsage, Reason
from backend.domain.contracts import ModelDefinition, Proposal


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


@dataclass(frozen=True, repr=False)
class ProviderRequest:
    stage: str
    model: ModelDefinition
    prompt: str
    proposal: Proposal
    max_output_tokens: int
    deadline: float

    def input_json(self) -> str:
        return json.dumps(
            {"untrusted_advisory_proposal": self.proposal.model_dump(mode="json")},
            ensure_ascii=True,
            separators=(",", ":"),
        )


@dataclass(frozen=True, repr=False)
class ProviderResponse:
    result: AgentResult | None
    usage: ProviderUsage | None
    error: Reason | None = None
    retry_after_seconds: int = 0
    generation_id: str | None = None
    provider_name: str | None = None


class AIProvider(Protocol):
    def generate(self, request: ProviderRequest) -> ProviderResponse: ...


class MockProvider:
    """Repeatable WAIT. It does not pretend to have observed market conditions."""

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        if monotonic() >= request.deadline:
            return ProviderResponse(None, None, Reason.PROVIDER_TIMEOUT)
        if request.model.provider != "mock":
            return ProviderResponse(None, None, Reason.PROVIDER_DISABLED)
        result = AgentResult(
            schema_version=1,
            action="WAIT",
            reason_codes=(Reason.MOCK_ONLY, Reason.NO_MARKET_CONTEXT),
        )
        return ProviderResponse(result, ProviderUsage(input_tokens=0, output_tokens=0))


class OpenAIProvider:
    """Responses wire adapter, restricted to a fake transport until network acceptance.

    There is intentionally no live transport constructor or runtime activation flag.
    This permits offline contract tests without sending source data or using an API key.
    """

    def __init__(self, transport: httpx.MockTransport) -> None:
        if not isinstance(transport, httpx.MockTransport):
            raise ValueError("OpenAI network acceptance is required")
        self.transport = transport

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        remaining = request.deadline - monotonic()
        if remaining <= 0:
            return ProviderResponse(None, None, Reason.PROVIDER_TIMEOUT)
        if request.model.provider != "openai":
            return ProviderResponse(None, None, Reason.PROVIDER_DISABLED)
        # Hand-authored subset, all fields required, no unsupported tuple/minItems schema.
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["schema_version", "action", "reason_codes"],
            "properties": {
                "schema_version": {"type": "integer", "enum": [1]},
                "action": {"type": "string", "enum": ["PROPOSE", "WAIT", "REJECT", "ESCALATE"]},
                "reason_codes": {
                    "type": "array",
                    "items": {"type": "string", "enum": [r.value for r in Reason]},
                },
            },
        }
        payload = {
            "model": request.model.model_name,
            "store": False,
            "max_output_tokens": request.max_output_tokens,
            "instructions": request.prompt,
            "input": [{"role": "user", "content": request.input_json()}],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "advisory_v1",
                    "strict": True,
                    "schema": schema,
                }
            },
        }
        try:
            with httpx.Client(
                transport=self.transport, timeout=remaining, follow_redirects=False, trust_env=False
            ) as client:
                response = client.post("https://api.openai.com/v1/responses", json=payload)
            if monotonic() >= request.deadline:
                return ProviderResponse(None, None, Reason.PROVIDER_TIMEOUT)
            if response.is_redirect:
                return ProviderResponse(None, None, Reason.PROVIDER_UNAVAILABLE)
            if response.status_code == 429:
                try:
                    quota = response.json().get("error", {}).get("code") == "insufficient_quota"
                    delay = min(120, max(0, int(response.headers.get("retry-after", "0"))))
                except (ValueError, TypeError, AttributeError):
                    quota, delay = False, 0
                return ProviderResponse(
                    None,
                    None,
                    Reason.PROVIDER_QUOTA if quota else Reason.PROVIDER_RATE_LIMIT,
                    delay,
                )
            if response.is_error:
                return ProviderResponse(None, None, Reason.PROVIDER_UNAVAILABLE)
            if len(response.content) > 65_536:
                return ProviderResponse(None, None, Reason.INVALID_OUTPUT)
            value = response.json()
            usage = None
            if value.get("usage") is not None:
                try:
                    raw = value["usage"]
                    usage = ProviderUsage(
                        input_tokens=raw["input_tokens"],
                        output_tokens=raw["output_tokens"],
                        cached_tokens=(raw.get("input_tokens_details") or {}).get(
                            "cached_tokens", 0
                        ),
                        reasoning_tokens=(raw.get("output_tokens_details") or {}).get(
                            "reasoning_tokens", 0
                        ),
                    )
                except (ValueError, KeyError, TypeError, AttributeError):
                    return ProviderResponse(None, None, Reason.UNKNOWN_USAGE)
            if value.get("status") != "completed":
                return ProviderResponse(None, usage, Reason.PROVIDER_INCOMPLETE)
            texts = []
            for item in value.get("output", []):
                if item.get("type") == "reasoning":
                    continue  # Never retain private reasoning or its encrypted payload.
                if item.get("type") != "message" or item.get("role") != "assistant":
                    return ProviderResponse(None, usage, Reason.INVALID_OUTPUT)
                for content in item.get("content", []):
                    if content.get("type") == "refusal":
                        return ProviderResponse(None, usage, Reason.PROVIDER_REFUSAL)
                    if content.get("type") != "output_text":
                        return ProviderResponse(None, usage, Reason.INVALID_OUTPUT)
                    texts.append(content["text"])
            if len(texts) != 1:
                return ProviderResponse(None, usage, Reason.INVALID_OUTPUT)
            return ProviderResponse(
                AgentResult.model_validate(json.loads(texts[0], object_pairs_hook=_unique_object)),
                usage,
            )
        except httpx.TimeoutException:
            return ProviderResponse(None, None, Reason.PROVIDER_TIMEOUT)
        except httpx.HTTPError:
            return ProviderResponse(None, None, Reason.PROVIDER_UNAVAILABLE)
        except (ValueError, KeyError, TypeError, AttributeError):
            return ProviderResponse(None, None, Reason.INVALID_OUTPUT)
