"""Cross-platform tasks. Subprocesses receive role-scoped environments."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from infra.scripts.environment import (  # noqa: E402
    OS_FIELDS,
    prepare_environment,
    read_environment,
    runtime_environment,
)
from infra.scripts.provision_database import provision  # noqa: E402


def operator_environment(values: dict[str, str], fields: set[str]) -> dict[str, str]:
    result = {key: value for key, value in os.environ.items() if key in OS_FIELDS}
    result.update({key: values[key] for key in fields if key in values})
    result["PYTHONUNBUFFERED"] = "1"
    return result


def executable(name: str) -> str:
    result = shutil.which(name)
    if result is None:
        raise ValueError(f"Required tool missing: {name}")
    return result


def platform_command(command: list[str]) -> list[str]:
    # Windows package-manager launchers are batch files. These are fixed task arguments,
    # never message/dashboard inputs; use the platform's native command interpreter.
    if os.name == "nt" and Path(command[0]).suffix.lower() in {".cmd", ".bat"}:
        return [
            os.environ.get("COMSPEC", "cmd.exe"),
            "/d",
            "/s",
            "/c",
            subprocess.list2cmdline(command),
        ]
    return command


def run(command: list[str], env: dict[str, str] | None = None) -> None:
    subprocess.run(platform_command(command), cwd=ROOT, env=env, check=True)


def migrate(values: dict[str, str]) -> None:
    run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        operator_environment(values, {"MIGRATION_DATABASE_URL"}),
    )


def bootstrap(values: dict[str, str]) -> None:
    run(
        [sys.executable, "-m", "backend.application.bootstrap"],
        operator_environment(
            values,
            {
                "MIGRATION_DATABASE_URL",
                "ADMIN_BOOTSTRAP_EMAIL",
                "ADMIN_BOOTSTRAP_PASSWORD",
                "ENVIRONMENT_ID",
            },
        ),
    )


def initialize(values: dict[str, str]) -> None:
    provision(values)
    migrate(values)
    bootstrap(values)


def stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=8)
    except (ProcessLookupError, subprocess.TimeoutExpired, OSError):
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"], check=False, capture_output=True
            )
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.wait()


def service_command(service: str, values: dict[str, str], *, reload: bool = False) -> list[str]:
    if service in {"api", "risk"}:
        port = int(
            values.get(
                "API_PORT" if service == "api" else "BRIDGE_PORT",
                "8000" if service == "api" else "8001",
            )
        )
        if not 1024 <= port <= 65535:
            raise ValueError("Application port must be between 1024 and 65535.")
        module = "apps.api.main:app" if service == "api" else "apps.worker.bridge:app"
        command = [
            sys.executable,
            "-m",
            "uvicorn",
            module,
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--loop",
            "asyncio",
            "--no-access-log",
        ]
        if reload:
            command.extend(
                [
                    "--reload",
                    "--reload-dir",
                    "backend",
                    "--reload-dir",
                    "apps/api" if service == "api" else "apps/worker",
                ]
            )
        return command
    if service == "collector":
        return [sys.executable, "-m", "apps.telegram.main"]
    return [sys.executable, "-m", "apps.worker.main", "--service", service]


def dev(values: dict[str, str]) -> None:
    if values.get("APP_ENV") != "development":
        raise ValueError("The development supervisor is not a production service manager.")
    children: list[subprocess.Popen] = []
    previous_handlers = {}
    stop_requested = False

    def request_stop(_number: int, _frame: object) -> None:
        # A supervisor receiving SIGTERM must still tear down every child group.
        nonlocal stop_requested
        if stop_requested:
            return
        stop_requested = True
        raise KeyboardInterrupt

    for name in ("SIGTERM", "SIGBREAK"):
        number = getattr(signal, name, None)
        if number is not None:
            previous_handlers[number] = signal.signal(number, request_stop)
    try:
        initialize(values)
        for service in ("api", "risk", "ai", "collector", "maintenance"):
            options = (
                {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
                if os.name == "nt"
                else {"start_new_session": True}
            )
            children.append(
                subprocess.Popen(
                    service_command(service, values, reload=service == "api"),
                    cwd=ROOT,
                    env=runtime_environment(service, values),
                    **options,
                )
            )
        frontend = operator_environment(values, {"API_INTERNAL_URL"})
        frontend["NEXT_TELEMETRY_DISABLED"] = "1"
        command = [
            executable("pnpm"),
            "--filter",
            "@trd/dashboard",
            "dev",
            "--port",
            str(int(values.get("DASHBOARD_PORT", "3000"))),
        ]
        options = (
            {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
            if os.name == "nt"
            else {"start_new_session": True}
        )
        children.append(
            subprocess.Popen(platform_command(command), cwd=ROOT, env=frontend, **options)
        )
        print(
            "Paper foundation started. Trading and external integrations are disabled.", flush=True
        )
        while all(child.poll() is None for child in children):
            time.sleep(0.5)
        raise RuntimeError("A development service exited; stopped the remaining processes.")
    finally:
        for child in reversed(children):
            stop_process(child)
        for number, handler in previous_handlers.items():
            signal.signal(number, handler)


def generate_api() -> None:
    from backend.api.factory import create_app
    from backend.domain.config import ApiSettings

    settings = ApiSettings(
        app_env="test",
        environment_id="schema-generation",
        database_url="postgresql+psycopg://trd_api:non-secret-schema-fixture@127.0.0.1:5432/schema",
        _env_file=None,
    )
    schema = create_app(settings, lambda _settings: False).openapi()
    destination = ROOT / "packages" / "shared-types" / "openapi.json"
    destination.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    run(
        [
            executable("pnpm"),
            "exec",
            "openapi-typescript",
            str(destination),
            "-o",
            "packages/shared-types/src/generated.ts",
        ]
    )


def check() -> None:
    run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "backend",
            "apps/api",
            "apps/worker",
            "apps/telegram",
            "apps/simulator",
            "migrations",
            "infra/scripts",
            "tests",
        ]
    )
    run([sys.executable, "-m", "pytest", "-m", "not integration"])
    for command in ("typecheck", "lint", "test", "build"):
        run([executable("pnpm"), "--filter", "@trd/dashboard", command])


def main() -> int:
    parser = argparse.ArgumentParser(description="Explicit platform foundation tasks")
    parser.add_argument(
        "task",
        choices=[
            "init-env",
            "provision-db",
            "migrate",
            "bootstrap",
            "initialize",
            "api",
            "bridge",
            "worker",
            "collector",
            "maintenance",
            "dev",
            "check",
            "test",
            "generate-api",
            "retention",
        ],
    )
    parser.add_argument(
        "--from-process",
        action="store_true",
        help="Read explicit one-shot container environment rather than local operator file",
    )
    args = parser.parse_args()
    try:
        if args.task == "init-env":
            path = prepare_environment()
            print(f"Private local environment prepared: {path.name}. Credentials were not printed.")
            return 0
        if args.task == "check":
            check()
            return 0
        if args.task == "test":
            run([sys.executable, "-m", "pytest"])
            return 0
        if args.task == "generate-api":
            generate_api()
            return 0
        values = dict(os.environ) if args.from_process else read_environment()
        if args.task == "provision-db":
            provision(values)
        elif args.task == "migrate":
            migrate(values)
        elif args.task == "bootstrap":
            bootstrap(values)
        elif args.task == "initialize":
            initialize(values)
        elif args.task == "dev":
            dev(values)
        elif args.task == "retention":
            run(
                [sys.executable, "-m", "backend.application.retention"],
                runtime_environment("maintenance", values),
            )
        else:
            service = {"bridge": "risk", "worker": "ai"}.get(args.task, args.task)
            run(service_command(service, values), runtime_environment(service, values))
        return 0
    except KeyboardInterrupt:
        return 130
    except subprocess.CalledProcessError as exc:
        print(
            f"Task failed (exit {exc.returncode}); review the safe service diagnostics.",
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        # Third-party ValueError messages can also contain credentials/URLs.
        print(
            f"Task failed: {type(exc).__name__}. Check the documented configuration.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
