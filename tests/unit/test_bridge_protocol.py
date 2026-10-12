"""Exact-byte signatures, bounded parsing and request/response binding."""

from hashlib import sha256
from hmac import new

import pytest

from backend.domain.bridge import Envelope, ProtocolError, json_bytes, strict_json

KEY = bytes.fromhex("11" * 32)
RESPONSE_KEY = bytes.fromhex("22" * 32)
PATH = "/bridge/v1/poll"
ENVELOPE = Envelope("test", "bridge", "instance", "local-v1", 1, 100, 110)


def test_rfc4231_sha256_vector_and_exact_bytes():
    assert new(bytes.fromhex("0b" * 20), b"Hi There", "sha256").hexdigest() == (
        "b0344c61d8db38535ca8afceaf0bf12b881dc200c9833da726e9376c2e32cff7"
    )
    body = b'{"value":"1.00"}'
    message = ENVELOPE.message(body, PATH)
    assert message.endswith((sha256(body).hexdigest() + "\n").encode())
    headers = ENVELOPE.headers(KEY, body, PATH)
    assert Envelope.verify(headers, KEY, body, PATH, now=100) == ENVELOPE
    with pytest.raises(ProtocolError):
        Envelope.verify(headers, KEY, b'{ "value":"1.00"}', PATH, now=100)


@pytest.mark.parametrize(
    "name,value",
    [
        ("environment", "other"),
        ("bridge", "other"),
        ("instance", "other"),
        ("key", "other"),
        ("sequence", "2"),
        ("issued", "99"),
        ("expires", "109"),
        ("sequence", "01"),
        ("sequence", "0"),
        ("sequence", str(2**63)),
        ("journal", "other-journal"),
    ],
)
def test_all_context_headers_are_authenticated(name, value):
    body = b"{}"
    headers = ENVELOPE.headers(KEY, body, PATH)
    headers["x-trd-" + name] = value
    with pytest.raises(ProtocolError):
        Envelope.verify(headers, KEY, body, PATH, now=100)


@pytest.mark.parametrize("now", [99, 110, 111])
def test_expiry_and_future_never_replay(now):
    headers = ENVELOPE.headers(KEY, b"{}", PATH)
    with pytest.raises(ProtocolError):
        Envelope.verify(headers, KEY, b"{}", PATH, now=now)


def test_separate_response_key_direction_status_path_and_outstanding_sequence():
    body = b"{}"
    headers = ENVELOPE.headers(RESPONSE_KEY, body, PATH, direction="RESPONSE", status=200)
    assert (
        Envelope.verify(
            headers,
            RESPONSE_KEY,
            body,
            PATH,
            now=101,
            direction="RESPONSE",
            status=200,
            expected=ENVELOPE,
        )
        == ENVELOPE
    )
    for key, path, direction, status, expected in (
        (KEY, PATH, "RESPONSE", 200, ENVELOPE),
        (RESPONSE_KEY, PATH, "REQUEST", 200, ENVELOPE),
        (RESPONSE_KEY, PATH, "RESPONSE", 409, ENVELOPE),
        (RESPONSE_KEY, "/bridge/v1/events", "RESPONSE", 200, ENVELOPE),
        (
            RESPONSE_KEY,
            PATH,
            "RESPONSE",
            200,
            Envelope("test", "bridge", "instance", "local-v1", 2, 100, 110),
        ),
    ):
        with pytest.raises(ProtocolError):
            Envelope.verify(
                headers,
                key,
                body,
                path,
                now=101,
                direction=direction,
                status=status,
                expected=expected,
            )


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"[]",
        b"null",
        b"\xef\xbb\xbf{}",
        b'{"v":1,"v":2}',
        b'{"v":NaN}',
        b'{"v":Infinity}',
        b'{"v":1.01}',
        b'{"v":1e2}',
        b'{"v":9223372036854775808}',
        b'{"v":"\\u0000"}',
        b'{"v":"\\ud800"}',
        b"\xff",
        b"{}\x00",
        b'{"v":' + b"[" * 20 + b"0" + b"]" * 20 + b"}",
        b'{"v":"' + b"x" * 8193 + b'"}',
        b" " * 65537,
    ],
)
def test_strict_bounded_json(body):
    with pytest.raises(ProtocolError):
        strict_json(body)


def test_money_remains_decimal_text_in_utf8_bytes():
    assert strict_json(json_bytes({"volume": "0.01", "text": "prova locale"})) == {
        "volume": "0.01",
        "text": "prova locale",
    }
    with pytest.raises(ProtocolError):
        json_bytes({"volume": 0.01})
