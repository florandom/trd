import hashlib
import hmac
import json
import subprocess

import pytest

from backend.domain.bridge import Envelope


def core(binary, **request):
    source = "JSON " + request["hex"] if request["op"] == "json" else json.dumps(request)
    result = subprocess.run(
        [str(binary)], input=source + "\n", text=True, capture_output=True, check=True, timeout=5
    )
    return json.loads(result.stdout)["answer"]


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"abc",
        bytes(range(256)),
        b"a" * 55,
        b"a" * 56,
        b"a" * 64,
        b"a" * 1000,
        "Euro € 中文".encode(),
    ],
)
def test_shared_mql_sha_exact_binary(mql_binary, data):
    assert core(mql_binary, op="sha", hex=data.hex()) == hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize(
    "key,data",
    [
        (b"\x0b" * 20, b"Hi There"),
        (b"Jefe", b"what do ya want for nothing?"),
        (b"\xaa" * 20, b"\xdd" * 50),
        (b"\xaa" * 131, b"Test Using Larger Than Block-Size Key - Hash Key First"),
        (bytes(range(32)), "€, UTF-8".encode()),
    ],
)
def test_shared_mql_rfc_and_python_hmac(mql_binary, key, data):
    assert (
        core(mql_binary, op="hmac", key=key.hex(), hex=data.hex())
        == hmac.new(key, data, "sha256").hexdigest()
    )


def test_shared_mql_protocol_frame_matches_python_with_journal(mql_binary):
    e = Envelope(
        "test", "bridge", "instance", "key", 9223372036854775807, 1791800000, 1791800010, "journal"
    )
    body = b'{"a":"bytes change the signature"}'
    answer = core(
        mql_binary,
        op="frame",
        environment=e.environment,
        bridge=e.bridge,
        instance=e.instance,
        key=e.key,
        journal=e.journal,
        sequence=str(e.sequence),
        issued=str(e.issued),
        expires=str(e.expires),
        path="/bridge/v1/poll",
        hex=body.hex(),
    )
    assert bytes.fromhex(answer) == e.message(body, "/bridge/v1/poll")


@pytest.mark.parametrize(
    "body",
    [
        b'{"a":1,"a":2}',
        b'{"a":1,"\\u0061":2}',
        b'{"n":1.5}',
        b'{"n":NaN}',
        b'{"n":9223372036854775808}',
        b'{"a":"\\n"}',
        b'{"a":"\x00"}',
        b"\xef\xbb\xbf{}",
        b"{}junk",
        b"[]",
        b'{"a":01}',
        b'{"a":true,}',
        b'{"a":[' + b"[" * 13 + b"]" * 13 + b"]}",
        b'{"a":"' + b"x" * 8193 + b'"}',
    ],
)
def test_shared_mql_strict_json_rejects_ambiguous_input(mql_binary, body):
    assert core(mql_binary, op="json", hex=body.hex()) == "INVALID"


@pytest.mark.parametrize("body", [b"{}", b'{"a":{"b":[true,null,12,"a\\"b"]}}', b'{"\\u0061":"x"}'])
def test_shared_mql_json_nested_and_escaped_keys(mql_binary, body):
    assert core(mql_binary, op="json", hex=body.hex()) == "VALID"


@pytest.mark.parametrize(
    "value,expected",
    [
        ("0", "0"),
        ("0.08", "8000"),
        ("1.0950000000", "109500"),
        ("0.000001", "INVALID"),
        ("-1", "INVALID"),
        ("1e2", "INVALID"),
        ("NaN", "INVALID"),
        ("1000001", "INVALID"),
        ("01", "INVALID"),
        ("1.", "INVALID"),
    ],
)
def test_shared_mql_exact_decimal_limits(mql_binary, value, expected):
    assert core(mql_binary, op="decimal", value=value) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        ("YWJj", "616263"),
        ("YQ==", "61"),
        ("YWI=", "6162"),
        ("YR==", ""),
        ("Y=Q=", ""),
        ("YQ", ""),
        ("====", ""),
    ],
)
def test_shared_mql_canonical_base64(mql_binary, value, expected):
    assert core(mql_binary, op="base64", value=value) == expected
