import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.api.factory import create_app
from backend.infrastructure.access import AccessRejected, AccessVerifier
from tests.access_fixtures import AUDIENCE, ORIGIN, assertion, headers, jwks, keypair, settings


@pytest.fixture(scope="module")
def key():
    return keypair()


def verifier(key, responder=None):
    return AccessVerifier(
        settings(),
        transport=httpx.MockTransport(
            responder or (lambda request: httpx.Response(200, json=jwks(key)))
        ),
    )


def test_signed_identity_requires_exact_issuer_audience_and_mfa(key):
    value = verifier(key).verify(assertion(key))
    assert value.email == "admin@example.test" and len(value.subject_hash) == 64
    assert "fixture-admin" not in repr(value)


@pytest.mark.parametrize(
    "change",
    [
        {"iss": "https://other.cloudflareaccess.com"},
        {"aud": ["b" * 64]},
        {"aud": [AUDIENCE, "b" * 64]},
        {"aud": None},
        {"exp": 1},
        {"exp": True},
        {"iat": 9999999999},
        {"nbf": 9999999999},
        {"email": None},
        {"email": "service-token"},
        {"sub": ""},
        {"amr": []},
        {"amr": "mfa"},
        {"amr": ["pwd"]},
        {"amr": ["mfa", 1]},
    ],
)
def test_untrusted_or_incomplete_identity_is_rejected(key, change):
    with pytest.raises(AccessRejected):
        verifier(key).verify(assertion(key, overrides=change))


def test_custom_mfa_claim_can_be_mapped_explicitly(key):
    import base64
    import json

    token = assertion(key)
    claims = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
    claims.pop("amr")
    claims["custom"] = {"amr": ["mfa"]}
    assert verifier(key).verify(assertion(key, payload=json.dumps(claims))).email


@pytest.mark.parametrize(
    "header",
    [
        {"alg": "none", "kid": "fixture-key"},
        {"alg": "HS256", "kid": "fixture-key"},
        {"alg": "RS256", "kid": "fixture-key", "jku": "https://attacker.test/keys"},
        {"alg": "RS256", "kid": "fixture-key", "crit": ["b64"]},
    ],
)
def test_algorithm_and_remote_key_injection_are_rejected(key, header):
    with pytest.raises(AccessRejected):
        verifier(key).verify(assertion(key, header=header))


def test_signature_duplicate_claims_and_oversized_tokens_fail_closed(key):
    for token in (
        assertion(keypair()),
        assertion(key, payload='{"iss":"one","iss":"two"}'),
        "x" * 16385,
        None,
        "a.b.c",
    ):
        with pytest.raises(AccessRejected):
            verifier(key).verify(token)


def test_jwks_is_fixed_bounded_cached_and_never_redirected(key):
    calls = []

    def respond(request):
        calls.append(request)
        assert str(request.url) == "https://fixture-team.cloudflareaccess.com/cdn-cgi/access/certs"
        return httpx.Response(200, json=jwks(key))

    check = verifier(key, respond)
    check.verify(assertion(key))
    check.verify(assertion(key))
    assert len(calls) == 1
    for response in (
        httpx.Response(302, headers={"location": "https://attacker.test/keys"}),
        httpx.Response(200, content=b"x" * 131073),
        httpx.Response(503),
    ):
        with pytest.raises(AccessRejected):
            verifier(key, lambda _request, reply=response: reply).verify(assertion(key))


def test_expired_jwks_fail_closed_and_rotation_is_refreshed(key):
    check = verifier(key)
    check.verify(assertion(key))
    replacement = keypair()
    check.refreshed_at -= 301
    check.transport = httpx.MockTransport(
        lambda _request: httpx.Response(200, json=jwks(replacement))
    )
    assert check.verify(assertion(replacement)).email
    check.refreshed_at -= 301
    check.transport = httpx.MockTransport(lambda _request: httpx.Response(503))
    with pytest.raises(AccessRejected):
        check.verify(assertion(replacement))


def test_malformed_jwks_cannot_leave_a_partially_valid_cache(key):
    document = jwks(key)
    document["keys"].append({"kid": "bad"})
    check = verifier(key, lambda _request: httpx.Response(200, json=document))
    for _ in range(2):
        with pytest.raises(AccessRejected):
            check.verify(assertion(key))
    assert check.keys == {}


def test_remote_gate_precedes_database_and_environment_access(key):
    calls = []
    app = create_app(
        settings(), lambda _settings: calls.append(True) or True, access_verifier=verifier(key)
    )
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get("/health/live").status_code == 200
        for supplied in (
            {},
            {"Cf-Access-Authenticated-User-Email": "admin@example.test"},
            {**headers(assertion(key)), "X-TRD-Proxy-Key": "wrong"},
        ):
            response = client.get("/health/ready", headers=supplied)
            assert response.status_code == 401
            assert response.headers["cache-control"] == "no-store"
        assert calls == []
        mismatch = {**headers(assertion(key)), "X-TRD-Environment": "production-other"}
        assert client.get("/health/ready", headers=mismatch).status_code == 409
        assert calls == []
        assert client.get("/health/ready", headers=headers(assertion(key))).status_code == 200
        assert client.get("/auth/me", headers=headers(assertion(key))).status_code == 401


@pytest.mark.parametrize(
    "change",
    [
        {"auth_mfa_required": False},
        {"auth_cookie_secure": False},
        {"app_url": "http://dashboard.example.test"},
        {"dashboard_proxy_secret": None},
        {"cloudflare_access_audience": "*"},
        {"cloudflare_access_issuer": "https://attacker.test"},
        {"cloudflare_access_issuer": "https://fixture-team.cloudflareaccess.com/path"},
        {"remote_access_mode": "local"},
        {"app_env": "development"},
    ],
)
def test_remote_configuration_cannot_relax_authority(change):
    with pytest.raises(ValidationError):
        settings(**change)
