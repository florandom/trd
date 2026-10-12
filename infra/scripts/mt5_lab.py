"""Compile and run the actual MQL lab source with a test-only C++ platform shim."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx

from backend.domain.bridge import PaperProfile, PaperSnapshot, ProtocolError, json_bytes

ROOT = Path(__file__).resolve().parents[2]


def compile_lab(directory: Path) -> Path:
    compiler = shutil.which("clang++") or shutil.which("g++")
    if compiler is None:
        raise RuntimeError("A local C++ compiler is required for the MQL platform harness")

    def expand(path):
        return re.sub(
            r'^#include "([^"]+)"$',
            lambda match: expand(path.parent / match[1]),
            path.read_text(),
            flags=re.MULTILINE,
        )

    source = expand(ROOT / "apps/mt5/Experts/TrdLocalBridge.mq5")
    # Mechanical syntax compatibility only; no crypto, JSON, execution or lifecycle
    # implementation is replaced. Includes have already been expanded in order.
    source = re.sub(r"^#(?:property|include) .*$", "", source, flags=re.MULTILINE)
    source = re.sub(r"^input ", "", source, flags=re.MULTILINE)
    source = source.replace("char data[],result[];", "std::vector<char> data,result;")
    shim = (ROOT / "tests/mt5/mql_host.hpp").read_text().replace("#pragma once\n", "")
    runner = (ROOT / "tests/mt5/runner.cpp").read_text()
    directory.mkdir(parents=True, exist_ok=True)
    cpp = directory / "mql-lab.cpp"
    cpp.write_text(shim + "\n" + source + "\n" + runner)
    binary = directory / "mql-lab"
    sdk_flags = []
    if sys.platform == "darwin":
        sdk = Path(subprocess.check_output(["xcrun", "--show-sdk-path"], text=True).strip())
        if not (sdk / "usr/include/c++/v1/algorithm").exists():
            candidates = sorted(
                path
                for path in sdk.parent.glob("MacOSX*.sdk")
                if (path / "usr/include/c++/v1/algorithm").exists()
            )
            if not candidates:
                raise RuntimeError("A macOS SDK with C++ headers is required")
            sdk = candidates[-1]
        sdk_flags = ["-isysroot", str(sdk), "-isystem", str(sdk / "usr/include/c++/v1")]
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-O1",
            "-Wall",
            "-Wextra",
            "-Wno-unused-parameter",
            *sdk_flags,
            str(cpp),
            "-o",
            str(binary),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    return binary


def lab_config(
    profile: PaperProfile, snapshot: PaperSnapshot, request_key, response_key, origin, journal
):
    # This build deliberately supports only the reviewed single-instrument lab.
    if (
        not re.fullmatch(r"test|development|test-mt5-[0-9a-f]{8}", profile.account.environment_id)
        or profile.account.login != "1"
        or len(profile.instruments) != 1
        or profile.instruments[0].symbol != "EURUSD.paper"
        or profile.generation != 1
        or len(request_key) != 32
        or len(response_key) != 32
        or request_key == response_key
        or not profile.calendar.is_open(snapshot.observed_at)
        or profile.calendar.timezone != "UTC"
        or {(w.weekday, w.start_minute, w.end_minute) for w in profile.calendar.windows}
        != {(d, 0, 1440) for d in range(7)}
    ):
        raise ProtocolError("UNSUPPORTED_NATIVE_LAB_PROFILE")
    template = snapshot.model_dump(mode="json")

    def refresh(value):
        if isinstance(value, dict):
            return {
                k: "$NOW$" if k == "observed_at" else "$UUID$" if k == "snapshot_id" else refresh(v)
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [refresh(item) for item in value]
        return value

    return {
        "schema": 1,
        "utc_day": snapshot.observed_at.date().isoformat(),
        "origin": origin,
        "environment": profile.account.environment_id,
        "bridge": profile.bridge_id,
        "instance": profile.instance_id,
        "key": profile.key_id,
        "journal": str(journal),
        "account_id": str(profile.account_id),
        "account": profile.account.model_dump(mode="json"),
        "profile_hash": profile.digest,
        "request_key_hex": request_key.hex(),
        "response_key_hex": response_key.hex(),
        "snapshot_template": refresh(template),
    }


class MqlLabProcess:
    """Drive OnInit/OnTimer and relay only the signed loopback transport."""

    def __init__(
        self, binary, directory, config, *, crash="", active=True, tester=False, transport=None
    ):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.chmod(0o700)
        self.config_path = self.directory / "config.json"
        if config is not None:
            self.config_path.write_bytes(json_bytes(config))
            self.config_path.chmod(0o600)
        self.http = httpx.Client(
            timeout=3, trust_env=False, follow_redirects=False, transport=transport
        )
        self.process = subprocess.Popen(
            [
                str(binary),
                "run",
                "config.json",
                str(self.directory),
                crash,
                "1" if active else "0",
                "1" if tester else "0",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        try:
            self.initial = self._reply()
        except BaseException:
            self.close()
            raise

    def _reply(self):
        while True:
            line = self.process.stdout.readline()
            if not line:
                raise ProtocolError("MQL_LAB_PROCESS_STOPPED")
            if line.startswith("RPC\t"):
                _, url, headers, body = line.rstrip("\n").split("\t")
                # The EA validates the origin; the test platform independently enforces it.
                address = httpx.URL(url)
                if address.scheme != "http" or address.host != "127.0.0.1" or address.port is None:
                    raise ProtocolError("MQL_LAB_EXTERNAL_TRANSPORT_FORBIDDEN")
                pairs = [
                    tuple(row.split(": ", 1))
                    for row in bytes.fromhex(headers).decode().split("\r\n")
                    if row
                ]
                try:
                    with self.http.stream(
                        "POST", url, headers=pairs, content=bytes.fromhex(body)
                    ) as response:
                        raw = b""
                        for chunk in response.iter_raw():
                            raw += chunk
                            if len(raw) > 65536:
                                break
                        raw_headers = "".join(
                            f"{name}: {value}\r\n" for name, value in response.headers.multi_items()
                        )
                        reply = (
                            f"{response.status_code}\t{raw_headers.encode().hex()}\t{raw.hex()}\n"
                        )
                except httpx.TransportError:
                    reply = "-1\t\t\n"
                self.process.stdin.write(reply)
                self.process.stdin.flush()
            else:
                return json.loads(line)

    def cycle(self):
        deadline = time.monotonic() + 5
        while True:
            self.process.stdin.write("TICK\n")
            self.process.stdin.flush()
            result = self._reply()
            if result["status"] != "CLOCK_WAIT" or time.monotonic() >= deadline:
                return result
            time.sleep(0.02)

    def close(self):
        if self.process.poll() is None:
            try:
                self.process.stdin.write("STOP\n")
                self.process.stdin.flush()
                self.process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                self.process.kill()
                self.process.wait(timeout=5)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            stream.close()
        self.http.close()
