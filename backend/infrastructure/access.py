"""Cloudflare human assertions: fixed issuer, RS256, bounded JWKS and explicit MFA.

Neither forwarded email headers nor the service token grant a dashboard identity.
The existing local password, session, role and CSRF boundary remains mandatory.
"""

import base64
import json
import re
import threading
from dataclasses import dataclass
from hashlib import sha256
from time import monotonic, time

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from backend.domain.config import ApiSettings


class AccessRejected(ValueError):
    """Safe denial, without the assertion, identity, URL or key material."""


def unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise AccessRejected("Invalid access assertion")
        result[key] = value
    return result


def decode64(value: str) -> bytes:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise AccessRejected("Invalid access assertion")
    return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)


@dataclass(frozen=True, repr=False)
class AccessIdentity:
    email: str
    subject_hash: str


class AccessVerifier:
    def __init__(self, settings: ApiSettings, *, transport: httpx.BaseTransport | None = None):
        self.issuer = (settings.cloudflare_access_issuer or "").rstrip("/")
        self.audience = settings.cloudflare_access_audience
        self.transport = transport
        self.keys: dict[str, rsa.RSAPublicKey] = {}
        self.refreshed_at = float("-inf")
        self.lock = threading.Lock()

    def _key(self, kid: str) -> rsa.RSAPublicKey:
        with self.lock:
            now = monotonic()
            expired = now - self.refreshed_at >= 300
            if expired or (kid not in self.keys and now - self.refreshed_at >= 30):
                # A key ID never selects a URL. No redirects, ambient proxy or stale-key fallback.
                self.refreshed_at = now
                self.keys = {}
                with httpx.Client(
                    transport=self.transport, timeout=3, follow_redirects=False, trust_env=False
                ) as client:
                    with client.stream("GET", self.issuer + "/cdn-cgi/access/certs") as response:
                        if response.status_code != 200:
                            raise AccessRejected("Access verification unavailable")
                        body = bytearray()
                        for chunk in response.iter_bytes():
                            body.extend(chunk)
                            if len(body) > 131_072:
                                raise AccessRejected("Access verification unavailable")
                document = json.loads(body, object_pairs_hook=unique_json)
                keys = document.get("keys")
                if not isinstance(keys, list) or not 1 <= len(keys) <= 8:
                    raise AccessRejected("Access verification unavailable")
                refreshed = {}
                for key in keys:
                    if (
                        key.get("kty") != "RSA"
                        or key.get("alg") != "RS256"
                        or key.get("use") != "sig"
                        or not isinstance(key.get("kid"), str)
                        or key["kid"] in refreshed
                    ):
                        raise AccessRejected("Access verification unavailable")
                    numbers = rsa.RSAPublicNumbers(
                        int.from_bytes(decode64(key["e"])), int.from_bytes(decode64(key["n"]))
                    )
                    public = numbers.public_key()
                    if not 2048 <= public.key_size <= 4096:
                        raise AccessRejected("Access verification unavailable")
                    refreshed[key["kid"]] = public
                self.keys = refreshed
            if kid not in self.keys:
                raise AccessRejected("Invalid access assertion")
            return self.keys[kid]

    def verify(self, token: str | None) -> AccessIdentity:
        try:
            if not token or len(token) > 16_384:
                raise AccessRejected("Invalid access assertion")
            header64, payload64, signature64 = token.split(".")
            header = json.loads(decode64(header64), object_pairs_hook=unique_json)
            if (
                not isinstance(header, dict)
                or set(header) - {"alg", "kid", "typ"}
                or header.get("alg") != "RS256"
                or header.get("typ", "JWT") != "JWT"
                or not isinstance(header.get("kid"), str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", header["kid"])
            ):
                raise AccessRejected("Invalid access assertion")
            self._key(header["kid"]).verify(
                decode64(signature64),
                (header64 + "." + payload64).encode("ascii"),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
            claims = json.loads(decode64(payload64), object_pairs_hook=unique_json)
            now = time()
            if not isinstance(claims, dict):
                raise AccessRejected("Invalid access assertion")
            audience = claims.get("aud")
            if isinstance(audience, str):
                audience = [audience]
            if (
                claims.get("iss") != self.issuer
                or not isinstance(audience, list)
                or audience != [self.audience]
                or any(type(claims.get(field)) is not int for field in ("exp", "iat"))
                or claims["exp"] <= now
                or claims["iat"] > now + 5
                or claims["exp"] <= claims["iat"]
                or claims["exp"] - claims["iat"] > 28_800
                or ("nbf" in claims and (type(claims["nbf"]) is not int or claims["nbf"] > now + 5))
                or not isinstance(claims.get("sub"), str)
                or not 1 <= len(claims["sub"]) <= 256
                or not isinstance(claims.get("email"), str)
                or not re.fullmatch(r"[^\s\x00]+@[^\s\x00]+", claims["email"])
                or len(claims["email"]) > 320
            ):
                raise AccessRejected("Invalid access assertion")
            # Supported IdP MFA must be exported as amr, optionally through Access custom claims.
            custom = claims.get("custom", {})
            methods = claims.get("amr", custom.get("amr") if isinstance(custom, dict) else None)
            if (
                not isinstance(methods, list)
                or not all(isinstance(method, str) for method in methods)
                or "mfa" not in methods
            ):
                raise AccessRejected("MFA evidence required")
            return AccessIdentity(
                claims["email"].casefold(),
                sha256((self.issuer + "\0" + claims["sub"]).encode()).hexdigest(),
            )
        except AccessRejected:
            raise
        except (ValueError, TypeError, KeyError, AttributeError, InvalidSignature, httpx.HTTPError):
            raise AccessRejected("Invalid access assertion") from None
