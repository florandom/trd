# Windows native foundation — Phase 1

This document prepares the Windows-native fallback. It is not a completed production deployment runbook. Phase 1 provides configuration, database/migration, process and health foundations; Telegram ingestion, AI calls, authenticated dashboard administration, EA execution, TLS/Access configuration and trading are later phases. Paper mode and disabled automation/live flags are mandatory. Windows service startup, virtual-account permissions, MT5 and pre-login reboot recovery have not been tested on the available macOS host.

The preferred conditional WSL2/Docker Engine path and its nested-virtualization/boot constraints remain in [Windows research](research/WINDOWS.md). Docker Desktop is not a Windows Server prerequisite.

## Native prerequisites and fixed boundaries

First target: x64 Windows Server 2022 Desktop Experience, native PostgreSQL 17, Python 3.13, Node 24 LTS, the repository's pinned pnpm version, and uv. Use a 64-bit shell. Install approved runtimes independently, update Windows, and confirm out-of-band recovery access. Keep MT5 native and outside these backend services. Use standard asyncio on Windows; Gunicorn/uvloop are not required.

| Service | Development listener | Runtime database login | Isolated service env file |
| --- | --- | --- | --- |
| Admin API | `127.0.0.1:8000` | `trd_api` | `.env.api` |
| Risk/bridge HTTP-worker | `127.0.0.1:8001` | `trd_risk` | `.env.bridge` |
| Dashboard | `127.0.0.1:3000` | None | `.env.dashboard` |
| AI worker | No listener | `trd_ai` | `.env.ai` |
| Telegram collector | No listener | `trd_collector` | `.env.telegram` |
| Maintenance worker | No listener | `trd_maintenance` | `.env.maintenance` |
| PostgreSQL | `127.0.0.1:5432` | Separate bootstrap/migration identities | Never shared with runtime services |

The role name `risk` and env filename `.env.bridge` refer to the same isolated risk/bridge service. It will own bridge keys, authenticated telemetry, replay verification and execution authority. The normal admin API has no bridge keys and cannot write authoritative telemetry or approvals. The AI worker cannot write approvals/commands. Phase 1 does not yet implement an executable bridge protocol or risk engine.

Redis is optional. This path needs native PostgreSQL and does not depend on an unofficial Windows Redis port. No application listener is publicly reachable by design. A later native Caddy service will supply same-origin routing/local bridge TLS; Cloudflare Tunnel/Access is a separate deployment gate. Until implemented authentication/MFA exists, keep this foundation on loopback.

Ports and the native PostgreSQL service name are configured in [native-layout.json](../infra/windows/native-layout.json). The Windows scripts reject non-loopback binding and duplicate/invalid ports. If changing ports, also update task-runner bind options/environment, dashboard `API_INTERNAL_URL`, and future proxy routes; this JSON does not independently reconfigure the running application or PostgreSQL.

Run the read-only inventory and plan from a Windows checkout:

```powershell
.\infra\windows\Test-NativePrerequisites.ps1 -Json
.\infra\windows\Get-NativeDeploymentPlan.ps1 -Json
```

Use `-PostgresBin 'C:\custom\PostgreSQL\17\bin'` for a custom PostgreSQL installation. `-ReportOnly` returns diagnostics without a nonzero prerequisite exit code; it is not a passing readiness gate. Preflight records installed client versions, service registration and current listeners. It does not validate server credentials/version, migrations, MT5, or reboot recovery, and it never changes services, firewall, RDP, or Autologon.

## Local native boot

Use a clean Windows checkout and native dependency builds. Do not copy macOS Python environments or native Node modules onto Windows.

```powershell
uv sync --frozen
pnpm install --frozen-lockfile
Copy-Item .env.example .env
```

Before generating secrets, restrict the Windows ACL of the local `.env` to the operator, required deployment administrator and SYSTEM. A POSIX-style file mode is not proof of an equivalent Windows ACL. Do not put database or account passwords in command arguments, transcripts, Git, or chat.

The native PostgreSQL installation has its own administrator/password; the Docker development bootstrap identity is not automatically present. In the protected `.env`, set `POSTGRES_USER` and `POSTGRES_PASSWORD` to the actual native bootstrap administrator, confirm `POSTGRES_HOST=127.0.0.1`, `POSTGRES_PORT=5432`, and `POSTGRES_DB=trd`, and leave runtime/migration DSNs as generation placeholders. Then generate the remaining local secrets:

```powershell
uv run python infra/scripts/task.py init-env
```

Role provisioning creates the configured empty database if it is absent, owned by the non-login `trd_owner` role. It connects through PostgreSQL's `postgres` maintenance database when the configured application database does not yet exist. The protected bootstrap administrator must have permission to create databases and roles; this identity is confined to the operator setup step. Existing databases are preserved, and application schema setup remains entirely through migrations:

```powershell
uv run python infra/scripts/task.py provision-db
uv run python infra/scripts/task.py migrate
uv run python infra/scripts/task.py bootstrap
pnpm dev
```

Use another terminal for checks:

```powershell
uv run python infra/scripts/task.py check
```

The task runner projects the development operator env into separate runtime process environments; no service receives the migration/bootstrap URL. Individual foundation processes can also be started with `api`, `bridge`, `worker`, `collector`, and `maintenance` task commands. Health/readiness reports must continue to show unavailable/unimplemented capabilities honestly; a successful foundation boot does not enable trading.

## Reviewable native service artifacts

Service templates use confirmed module contracts:

| Service ID | Entrypoint |
| --- | --- |
| `trdapi` | Python Uvicorn `apps.api.main:app`, local port 8000, asyncio |
| `trdbridge` | Python Uvicorn `apps.worker.bridge:app`, local port 8001, asyncio |
| `trdai` | `python -m apps.worker.main --service ai` |
| `trdcollector` | `python -m apps.telegram.main` |
| `trdmaintenance` | `python -m apps.worker.main --service maintenance` |
| `trddashboard` | Native Node 24 running Windows-built standalone `server.js` |

Preview only, with no service installation or filesystem writes:

```powershell
.\infra\windows\New-NativeServiceTemplates.ps1 -ProjectRoot 'C:\trd' -Json
```

The generator proposes separate passwordless virtual accounts such as `NT SERVICE\trdapi` and `NT SERVICE\trdbridge`. Windows documents virtual service accounts, but their WinSW registration, effective permissions and target-host behavior are still smoke-test requirements. Do not substitute a shared administrator/LocalSystem identity to bypass a setup failure. [Microsoft service accounts](https://learn.microsoft.com/windows/security/identity-protection/access-control/service-accounts)

For later reviewed artifact creation, supply the approved stable WinSW **2.12.0 x64** executable and an independently recorded trusted SHA-256. The verifier checks checksum and release version without executing it. No script downloads a wrapper, and no checksum is inferred from the untrusted artifact and accepted as its own evidence. A missing/mismatched checksum blocks writing:

```powershell
.\infra\windows\Test-WinSWArtifact.ps1 -Path 'C:\approved-tools\WinSW-x64.exe' -ExpectedSha256 $approvedDigest
.\infra\windows\New-NativeServiceTemplates.ps1 -ProjectRoot 'C:\trd' -WinSWPath 'C:\approved-tools\WinSW-x64.exe' -ExpectedSha256 $approvedDigest -OutputDirectory 'C:\review\trd-services-v1' -Write -Json
```

`$approvedDigest` is an operator-supplied non-secret reviewed value; it must be resolved before the second command. `-Write` checks required runtime/env/server artifacts, refuses an existing output directory, and writes only wrapper copies and XML. It never installs or starts a service, creates a Windows account, changes ACLs, modifies firewall/RDP, or enables Autologon. The generated XML contains paths and safety flags, never credential values. [WinSW 2.12.0 release](https://github.com/winsw/winsw/releases/tag/v2.12.0), [version-matched XML contract](https://raw.githubusercontent.com/winsw/winsw/v2.12.0/doc/xmlConfigFile.md)

The XML specifies delayed automatic startup, native PostgreSQL service dependencies, gradual restart backoff, graceful-stop timeout and size-bounded wrapper logs. Seven retained files means a size bound, not seven-day retention; the application log/retention policy is separate. Dependency order does not prove schema readiness. Templates force `TRADING_MODE=paper`, `ENABLE_AUTOMATION=false`, and `ENABLE_LIVE_TRADING=false`. Phase 1 configuration also rejects demo/live/automation independently. [WinSW logging contract](https://raw.githubusercontent.com/winsw/winsw/v2.12.0/doc/loggingAndErrorReporting.md)

Before any future installation, provision restrictive ACLs explicitly:

- Shared release files: each runtime account reads/executes; runtime accounts cannot modify them.
- Each service env file: only its own service identity and the deployment administrator can read it; sibling runtime accounts cannot.
- Each data/log directory: only its owner writes; the collector owns its session storage; risk owns bridge/replay material.
- Bootstrap/migration credentials: available only during the controlled operator deployment step.
- Wrapper configuration/executables: deployment administrator writes; runtime identities cannot replace them.

Each Python scoped file needs its own `DATABASE_URL`, `ENVIRONMENT_ID`, paper/disabled flags, and absolute `DATA_DIR`/`LOG_DIR`. For production configuration, all relevant hard bounds must be explicit in `.env.bridge`, and API HTTPS/secure-cookie checks must pass. Never use the complete operator `.env` as `ENV_FILE`; the application rejects that filename. Put future Telegram/provider/bridge/notification secrets only in their corresponding role file. Scoped production env-file export and ACL enforcement are later deployment work; Phase 1 does not claim to automate them.

Do not set application secrets in machine-wide Windows environment variables: services inherit those variables, and inherited values can override env-file values. Keep the deployment operator environment separate from each service's scoped runtime configuration.

The dashboard file contains only non-secret server configuration, for example `API_INTERNAL_URL=http://127.0.0.1:8000`. It contains no PostgreSQL, Telegram, model-provider, signing or bootstrap secret. Node's `--env-file` reads this separate file; `HOSTNAME`, `PORT` and `NODE_ENV` are supplied explicitly by the wrapper. [Node environment-file CLI](https://nodejs.org/download/release/v24.7.0/docs/api/cli.html)

Build the dashboard on Windows and inspect the standalone output. With the monorepo tracing root, the expected server path is `apps\dashboard\.next\standalone\apps\dashboard\server.js`. Pass `-DashboardServerPath` if the verified artifact layout differs. Copy `.next\static` into the matching standalone application's `.next\static`, and include `public` if one is added. Standalone output does not copy those assets automatically. [Next.js standalone output](https://nextjs.org/docs/app/api-reference/config/next-config-js/output)

## Later production acceptance

Phase 10 must finish service installation, role-file export/ACL verification, database backup/restore, native proxy TLS/certificate trust, authenticated access/MFA, secure RDP, and the selected WSL or native topology. Phase 7/11 must compile and validate the EA on a real Windows/demo account. A mandatory reboot test must observe PostgreSQL, admin API, risk/bridge, collectors/workers, dashboard, proxy and tunnel recovering **before** interactive desktop login.

MT5 is a separate interactive process. The safe default requires a dedicated trading-user login after reboot, then broker/position/command reconciliation before new orders. Disconnecting RDP normally preserves the session; signing out stops its processes. Optional dedicated-user Autologon and desktop locking require a later explicit security decision and real reboot test. No script in this foundation configures that behavior. See [Windows deployment research and evidence gates](research/WINDOWS.md).

Current validation can cover PowerShell parsing and read-only plan/template previews on macOS. It cannot establish Windows prerequisite discovery, service identities, restart behavior, certificate trust, or pre-login/MT5 recovery. Those remain explicit acceptance gates rather than inferred success.


## Phase 4 Telegram preparation

The read-only collector now requires an operator-enrolled encrypted StringSession,
a service-scoped application API ID/hash and independent encryption key. Stop the
collector for enrollment/replacement/rotation. Restrict session directory/file ACLs
to its service account and authorized operators, preserve key/ciphertext separately
in backup, and avoid collecting the same account from independent database copies.
The implementation is exercised on macOS and Linux containers; native Windows
collector enrollment, ACLs and recovery remain target-host acceptance gates. See
[the practical Italian guide](team/GUIDA_PREPARAZIONE.md) and [Telegram contract](TELEGRAM.md).
