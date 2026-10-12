"""Pinned Chat Completions adapter. One request, one provider, exact cost data, no tools."""

import json
import re
from decimal import Decimal, DecimalException
from time import monotonic

import httpx
from pydantic import SecretStr

from backend.ai.providers import (
    MockProvider,
    ProviderRequest,
    ProviderResponse,
    _unique_object,
)
from backend.domain.analysis import AgentResult, ProviderUsage, Reason
from backend.domain.contracts import ModelDefinition

BASE_URL = "https://openrouter.ai/api/v1"


def exact_json(value) -> str:
    """JSON numeric prices without converting Decimal money to a binary float."""
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Non-finite provider price")
        return str(value)
    if isinstance(value, dict):
        return "{" + ",".join(json.dumps(k) + ":" + exact_json(v) for k, v in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ",".join(exact_json(item) for item in value) + "]"
    return json.dumps(value, ensure_ascii=True, allow_nan=False)


def strict_document(body: bytes | str):
    def reject_constant(_value):
        raise ValueError("Non-finite provider value")

    return json.loads(
        body, parse_float=Decimal, parse_constant=reject_constant, object_pairs_hook=_unique_object
    )


def usage_from(value) -> ProviderUsage | None:
    try:
        if not isinstance(value, dict) or value.get("cost") is None:
            return None
        inputs, outputs = value["prompt_tokens"], value["completion_tokens"]
        if type(value.get("total_tokens")) is not int or value["total_tokens"] != inputs + outputs:
            return None
        cost = value["cost"]
        if isinstance(cost, bool) or not isinstance(cost, (Decimal, int, str)):
            return None
        cost = Decimal(str(cost))
        if not cost.is_finite() or cost < 0:
            return None
        usage = ProviderUsage(
            input_tokens=inputs,
            output_tokens=outputs,
            cached_tokens=(value.get("prompt_tokens_details") or {}).get("cached_tokens", 0),
            reasoning_tokens=(value.get("completion_tokens_details") or {}).get(
                "reasoning_tokens", 0
            ),
            cost_usd=cost.quantize(Decimal("0.0000000001"), rounding="ROUND_CEILING"),
        )
        if usage.cost_usd > Decimal("999999999999999999.9999999999"):
            return None
        return usage
    except (ValueError, TypeError, KeyError, AttributeError, DecimalException):
        return None


class OpenRouterProvider:
    def __init__(
        self,
        api_key: SecretStr,
        models: dict[str, ModelDefinition],
        *,
        transport: httpx.BaseTransport | None = None,
    ):
        self.api_key, self.models, self.transport = api_key, models, transport

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        if request.model.provider == "mock":
            return MockProvider().generate(request)
        model = self.models.get(request.model.id)
        if model != request.model or model.provider != "openrouter":
            return ProviderResponse(None, None, Reason.PROVIDER_DISABLED)
        # Expiry is checked for each request, not only at process startup.
        if model.accepted_until is not None:
            from datetime import UTC, datetime

            if model.accepted_until <= datetime.now(UTC):
                return ProviderResponse(None, None, Reason.MODEL_UNAVAILABLE)
        remaining = request.deadline - monotonic()
        if remaining <= 0:
            return ProviderResponse(None, None, Reason.PROVIDER_TIMEOUT)
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["schema_version", "action", "reason_codes"],
            "properties": {
                "schema_version": {"type": "integer", "enum": [1]},
                "action": {"type": "string", "enum": ["PROPOSE", "WAIT", "REJECT", "ESCALATE"]},
                "reason_codes": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [reason.value for reason in Reason],
                    },
                },
            },
        }
        payload = {
            "model": model.model_name,
            "stream": False,
            "max_tokens": request.max_output_tokens,
            "messages": [
                {"role": "system", "content": request.prompt},
                {"role": "user", "content": request.input_json()},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "advisory_v1",
                    "strict": True,
                    "schema": schema,
                },
            },
            "provider": {
                "only": [model.provider_slug],
                "order": [model.provider_slug],
                "allow_fallbacks": False,
                "require_parameters": True,
                "data_collection": "deny",
                "zdr": True,
                "max_price": {
                    "prompt": model.input_price_per_million,
                    "completion": model.output_price_per_million,
                    "request": 0,
                },
            },
        }
        try:
            with httpx.Client(
                transport=self.transport,
                follow_redirects=False,
                trust_env=False,
                timeout=httpx.Timeout(remaining, connect=min(remaining, 3), read=min(remaining, 5)),
            ) as client:
                with client.stream(
                    "POST",
                    BASE_URL + "/chat/completions",
                    content=exact_json(payload),
                    headers={
                        "Authorization": "Bearer " + self.api_key.get_secret_value(),
                        "Content-Type": "application/json",
                    },
                ) as response:
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        if monotonic() >= request.deadline:
                            return ProviderResponse(None, None, Reason.PROVIDER_TIMEOUT)
                        body.extend(chunk)
                        if len(body) > 262_144:
                            return ProviderResponse(None, None, Reason.INVALID_OUTPUT)
                    status = response.status_code
                    try:
                        delay = min(120, max(0, int(response.headers.get("retry-after", "0"))))
                    except ValueError:
                        delay = 120
            document = strict_document(body)
            if not isinstance(document, dict):
                return ProviderResponse(None, None, Reason.INVALID_OUTPUT)
            usage = usage_from(document.get("usage"))
            if status != 200:
                reason = (
                    Reason.PROVIDER_QUOTA
                    if status == 402
                    else Reason.PROVIDER_RATE_LIMIT
                    if status == 429
                    else Reason.PROVIDER_DISABLED
                    if status in {401, 403}
                    else Reason.PROVIDER_UNAVAILABLE
                )
                return ProviderResponse(None, usage, reason, delay)
            generation, provider = document.get("id"), document.get("provider")
            if (
                document.get("model") != model.model_name
                or provider != model.provider_label
                or not isinstance(generation, str)
                or not re.fullmatch(r"gen-[A-Za-z0-9_-]{1,128}", generation)
            ):
                return ProviderResponse(None, None, Reason.INVALID_OUTPUT)
            choices = document.get("choices")
            if not isinstance(choices, list) or len(choices) != 1:
                return ProviderResponse(
                    None,
                    usage,
                    Reason.INVALID_OUTPUT,
                    generation_id=generation,
                    provider_name=provider,
                )
            choice = choices[0]
            message = choice.get("message", {})
            metadata = {"generation_id": generation, "provider_name": provider}
            if message.get("refusal"):
                return ProviderResponse(None, usage, Reason.PROVIDER_REFUSAL, **metadata)
            if choice.get("finish_reason") != "stop":
                return ProviderResponse(None, usage, Reason.PROVIDER_INCOMPLETE, **metadata)
            if (
                message.get("role") != "assistant"
                or message.get("tool_calls")
                or message.get("function_call")
            ):
                return ProviderResponse(None, usage, Reason.INVALID_OUTPUT, **metadata)
            content = message.get("content")
            if not isinstance(content, str) or len(content.encode()) > 16_384:
                return ProviderResponse(None, usage, Reason.INVALID_OUTPUT, **metadata)
            try:
                result = AgentResult.model_validate(strict_document(content))
            except (ValueError, TypeError):
                return ProviderResponse(None, usage, Reason.INVALID_OUTPUT, **metadata)
            if monotonic() >= request.deadline:
                return ProviderResponse(None, usage, Reason.PROVIDER_TIMEOUT, **metadata)
            return ProviderResponse(result, usage, **metadata)
        except httpx.TimeoutException:
            return ProviderResponse(None, None, Reason.PROVIDER_TIMEOUT)
        except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError):
            return ProviderResponse(None, None, Reason.PROVIDER_UNAVAILABLE)
