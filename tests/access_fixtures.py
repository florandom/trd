"""Ephemeral synthetic Access assertions. No real credentials or session material."""

import base64
import json
from time import time

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from backend.domain.config import ApiSettings

ISSUER = "https://fixture-team.cloudflareaccess.com"
AUDIENCE = "a" * 64
PROXY_SECRET = "p" * 43
ORIGIN = "https://dashboard.example.test"


def settings(**overrides):
    values = {
        "app_env": "test",
        "environment_id": "test",
        "app_url": ORIGIN,
        "database_url": "postgresql+psycopg://trd_api:test-fixture-password@localhost:5432/test",
        "remote_access_mode": "cloudflare",
        "auth_mfa_required": True,
        "cloudflare_access_issuer": ISSUER,
        "cloudflare_access_audience": AUDIENCE,
        "dashboard_proxy_secret": PROXY_SECRET,
    }
    return ApiSettings(**{**values, **overrides})


def encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def keypair():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def jwks(key, kid="fixture-key"):
    numbers = key.public_key().public_numbers()
    return {
        "keys": [
            {
                "kid": kid,
                "alg": "RS256",
                "kty": "RSA",
                "use": "sig",
                "n": encode(numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8)),
                "e": encode(numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8)),
            }
        ]
    }


def assertion(key, *, overrides=None, header=None, payload=None):
    now = int(time())
    claims = {
        "iss": ISSUER,
        "aud": [AUDIENCE],
        "sub": "fixture-admin",
        "iat": now,
        "exp": now + 3600,
        "email": "admin@example.test",
        "amr": ["pwd", "mfa"],
    }
    claims.update(overrides or {})
    head = encode(
        json.dumps(header or {"alg": "RS256", "typ": "JWT", "kid": "fixture-key"}).encode()
    )
    body = encode((payload or json.dumps(claims)).encode())
    signature = key.sign((head + "." + body).encode(), padding.PKCS1v15(), hashes.SHA256())
    return head + "." + body + "." + encode(signature)


def headers(token):
    return {
        "X-TRD-User-Assertion": token,
        "X-TRD-Proxy-Key": PROXY_SECRET,
        "X-TRD-Environment": "test",
    }
