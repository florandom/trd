"""External wire acceptance remains entirely offline in the automated suite."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from time import monotonic

import httpx
import pytest
from pydantic import SecretStr

from backend.ai.acceptance import OpenRouterManifest, configured_provider
from backend.ai.acceptance_operator import catalog_profile, probe
from backend.ai.openrouter import OpenRouterProvider, exact_json, strict_document, usage_from
from backend.domain.analysis import Reason
from backend.domain.config import AiSettings
from infra.scripts.openrouter_operator import write_receipt
from tests.openrouter_fixtures import KEY, catalog, model, request, response


def adapter(profile, document=None, *, status=200):
    calls = []

    def respond(call):
        calls.append(call)
        return httpx.Response(
            status, content=exact_json(document or response()), headers={"retry-after": "90"}
        )

    return OpenRouterProvider(
        SecretStr(KEY), {profile.id: profile}, transport=httpx.MockTransport(respond)
    ), calls


def test_pinned_schema_provider_privacy_limits_and_exact_billing():
    profile = model()
    provider, calls = adapter(profile)
    result = provider.generate(request(profile))
    assert result.error is None and result.result.action == "WAIT"
    assert result.usage.cost_usd == Decimal("0.0000200000")
    assert result.generation_id == "gen-synthetic-fixture" and result.provider_name == "Fixture"
    (call,) = calls
    assert str(call.url) == "https://openrouter.ai/api/v1/chat/completions"
    body = strict_document(call.content)
    assert body["model"] == profile.model_name and body["max_tokens"] == 64
    assert body["provider"] == {
        "only": ["fixture"],
        "order": ["fixture"],
        "allow_fallbacks": False,
        "require_parameters": True,
        "data_collection": "deny",
        "zdr": True,
        "max_price": {"prompt": 1, "completion": 2, "request": 0},
    }
    assert body["response_format"]["json_schema"]["strict"] is True
    assert not {"tools", "plugins", "transforms", "reasoning"} & set(body)
    assert KEY not in str(body) and KEY not in repr(provider.api_key)
    assert "untrusted_advisory_proposal" in body["messages"][1]["content"]


@pytest.mark.parametrize(
    "changes",
    [
        {"model": "fixture/other"},
        {"provider": "Other"},
        {"id": "unexpected"},
        {"choices": []},
        {
            "choices": [
                {"message": {"role": "assistant", "tool_calls": [{}]}, "finish_reason": "stop"}
            ]
        },
        {
            "choices": [
                {
                    "message": {"role": "assistant", "content": '{"action":"PROPOSE"}'},
                    "finish_reason": "stop",
                }
            ]
        },
    ],
)
def test_unknown_provenance_tools_or_invalid_schema_never_produce_a_result(changes):
    profile = model()
    provider, calls = adapter(profile, response(**changes))
    result = provider.generate(request(profile))
    assert result.result is None and result.error == Reason.INVALID_OUTPUT and len(calls) == 1


@pytest.mark.parametrize(
    "status,reason",
    [
        (402, Reason.PROVIDER_QUOTA),
        (429, Reason.PROVIDER_RATE_LIMIT),
        (401, Reason.PROVIDER_DISABLED),
        (403, Reason.PROVIDER_DISABLED),
        (503, Reason.PROVIDER_UNAVAILABLE),
        (307, Reason.PROVIDER_UNAVAILABLE),
    ],
)
def test_no_redirect_or_hidden_provider_retry(status, reason):
    profile = model()
    provider, calls = adapter(profile, {"error": "synthetic"}, status=status)
    assert provider.generate(request(profile)).error == reason and len(calls) == 1


@pytest.mark.parametrize(
    "usage",
    [
        None,
        {},
        {"prompt_tokens": True, "completion_tokens": 1, "total_tokens": 2, "cost": "0.1"},
        {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2, "cost": "NaN"},
        {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2, "cost": "1e9999"},
        {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2, "cost": 0.1},
        {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 3, "cost": "0.1"},
        {
            "prompt_tokens": 1,
            "completion_tokens": 1,
            "total_tokens": 2,
            "cost": "0.1",
            "prompt_tokens_details": {"cached_tokens": 2},
        },
    ],
)
def test_invalid_or_missing_billing_is_unknown(usage):
    assert usage_from(usage) is None


def test_decimal_cost_rounds_up_and_never_passes_through_float():
    assert usage_from(
        {"prompt_tokens": 1, "completion_tokens": 0, "total_tokens": 1, "cost": "0.00000000001"}
    ).cost_usd == Decimal("0.0000000001")
    assert exact_json({"price": Decimal("0.8790849199")}) == '{"price":0.8790849199}'
    with pytest.raises(ValueError):
        strict_document('{"cost":1,"cost":2}')


def test_expired_or_mismatched_model_and_deadline_never_touch_network():
    profile = model()
    provider, calls = adapter(profile)
    assert (
        provider.generate(request(profile, deadline=monotonic() - 1)).error
        == Reason.PROVIDER_TIMEOUT
    )
    changed = model(pricing_version="other")
    assert provider.generate(request(changed)).error == Reason.PROVIDER_DISABLED
    expired = model(accepted_until=datetime.now(UTC) - timedelta(seconds=1))
    other, _ = adapter(expired)
    assert other.generate(request(expired)).error == Reason.MODEL_UNAVAILABLE and calls == []


def test_refusal_incomplete_and_timeout_retain_verified_usage():
    profile = model()
    provider, _ = adapter(
        profile,
        response(
            choices=[{"finish_reason": "length", "message": {"role": "assistant", "content": "{}"}}]
        ),
    )
    result = provider.generate(request(profile))
    assert result.result is None and result.error == Reason.PROVIDER_INCOMPLETE and result.usage


def manifest(profile):
    now = datetime.now(UTC)
    return OpenRouterManifest(
        schema_version=1,
        environment_id="test",
        reviewed_at=now,
        expires_at=profile.accepted_until,
        models=(profile,),
    )


def probe_settings(**changes):
    fields = dict(
        app_env="test",
        environment_id="test",
        database_url="postgresql+psycopg://trd_ai:synthetic-password@127.0.0.1:5432/test",
        openrouter_api_key=KEY,
        ai_hard_daily_budget_usd="1",
        ai_hard_monthly_budget_usd="1",
        ai_hard_daily_budget_per_agent_usd="1",
        ai_hard_max_cost_per_request_usd="0.1",
    )
    fields.update(changes)
    return AiSettings(**fields)


def test_acceptance_probes_only_synthetic_input_and_receipt_binds_key_env_expiry(tmp_path):
    profile = model()
    reviewed = manifest(profile)
    calls = []

    def wire(call):
        calls.append(call)
        return httpx.Response(
            200, content=exact_json(catalog(profile) if call.method == "GET" else response())
        )

    receipt = probe(
        reviewed,
        reviewed.model_dump_json().encode(),
        probe_settings(),
        transport=httpx.MockTransport(wire),
    )
    assert len(calls) == 4 and all(call.method == "POST" for call in calls[1:])
    receipt.check("test", KEY)
    for environment, key in (("other", KEY), ("test", "other-key")):
        with pytest.raises(ValueError):
            receipt.check(environment, key)
    path = tmp_path / "acceptance.json"
    write_receipt(path, receipt)
    with pytest.raises(ValueError):
        write_receipt(path, receipt)
    assert KEY not in path.read_text() and not path.with_name(path.name + ".new").exists()
    provider = configured_provider(
        probe_settings(ai_provider_mode="openrouter", openrouter_acceptance_path=path)
    )
    assert profile.id in provider.models


@pytest.mark.parametrize(
    "field,value",
    [
        ("context_length", 4097),
        ("status", -1),
        ("max_completion_tokens", 1),
        ("tag", "other"),
        ("supported_parameters", []),
        ("pricing", {"prompt": "0.000001", "completion": "0.000002", "request": "0.01"}),
        ("pricing", {"prompt": "0.000002", "completion": "0.000002", "request": "0"}),
    ],
)
def test_catalog_mismatch_refuses_external_activation(field, value):
    profile = model()
    document = catalog(profile)
    document["data"]["endpoints"][0][field] = value
    with pytest.raises(ValueError):
        catalog_profile(profile, document)


def test_zero_budgets_expired_manifest_or_bad_probe_never_produce_acceptance():
    profile = model()
    reviewed = manifest(profile)
    calls = []
    transport = httpx.MockTransport(lambda call: calls.append(call) or httpx.Response(503))
    with pytest.raises(ValueError):
        probe(reviewed, b"{}", probe_settings(ai_hard_daily_budget_usd="0"), transport=transport)
    assert calls == []
    with pytest.raises(ValueError):
        probe(reviewed, b"{}", probe_settings(), transport=transport)
    assert len(calls) == 1
    with pytest.raises(ValueError):
        reviewed.model_copy(update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}).check(
            "test"
        )
