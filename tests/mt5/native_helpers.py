"""Drive the native observer source against terminal primitives supplied by fixtures."""

import json
import subprocess
from pathlib import Path
from uuid import uuid4


class NativeMqlProcess:
    def __init__(
        self,
        binary,
        directory,
        *,
        active=True,
        tester=False,
        login="7",
        server="TRD-NATIVE-FIXTURE",
        symbol="EURUSD.native",
        journal=None,
        history=3600,
        case="",
    ):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.process = subprocess.Popen(
            [
                str(binary),
                str(self.directory),
                "1" if active else "0",
                "1" if tester else "0",
                login,
                server,
                symbol,
                str(journal or uuid4()),
                str(history),
                case,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self.initial = self.read()

    def read(self):
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError("Native fixture process stopped")
        return json.loads(line)

    def command(self, command):
        self.process.stdin.write(command + "\n")
        self.process.stdin.flush()
        return self.read()

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.write("STOP\n")
            self.process.stdin.flush()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            stream.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
