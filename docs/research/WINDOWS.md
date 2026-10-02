# Windows production research

Research date: 2 October 2026. Phase 0 design evidence only. No Windows host, VPS provider, MT5 installation, broker demo account, or Cloudflare account was available for runtime validation. The plans below are documented deployment candidates, not tested production deployments.

## Recommendation

Support two deployment modes with the same application package and protocol. Prefer Mode A only after the target VPS passes its capability and recovery checks. Mode B is a complete native Windows fallback and must remain independent of Docker Desktop, WSL, and nested virtualization. Use Windows Server 2022 or 2025 with Desktop Experience for the native MT5/human browser requirement. Server Core is unsuitable for that interactive desktop requirement even when its WSL installation is supported.

Keep durable jobs, settings, sessions, audit, risk reservations, and execution state in PostgreSQL in both modes. Redis can improve caching or notifications but must not be the only durable execution queue, session store, replay store, or safety lock. This permits native Windows deployment without an unofficial Redis port. PostgreSQL explicitly documents `SKIP LOCKED` for competing consumers of queue-like tables; delivery still requires leases, retries, unique identifiers, and idempotent handlers. [PostgreSQL SELECT](https://www.postgresql.org/docs/current/sql-select.html)

## Mode A: WSL2, Ubuntu, Docker Engine, Compose

Microsoft documents the simple WSL2 installation path for Windows Server 2022 and 2025. Earlier Server versions require separate checks; WSL being available does not prove WSL2 is usable. [Windows Server WSL installation](https://learn.microsoft.com/en-us/windows/wsl/install-on-server)

A VPS is already a virtual machine. WSL2 therefore requires the hosting provider to expose nested virtualization. The example Hyper-V setting belongs to the parent hypervisor, which the VPS customer usually cannot control. Written provider confirmation plus a successful WSL2 runtime check is required; a guest-side feature installation alone cannot enable missing host capabilities. [WSL FAQ](https://learn.microsoft.com/en-us/windows/wsl/faq#can-i-run-wsl-2-in-a-virtual-machine), [Nested virtualization](https://learn.microsoft.com/en-us/windows-server/virtualization/hyper-v/nested-virtualization)

Docker Desktop is explicitly unsupported on Windows Server. Install Docker Engine and the Compose plugin directly inside Ubuntu using the Docker repository installation path. This is an architectural choice based on the documented Ubuntu engine installation, not a claim that Docker has certified this exact VPS/WSL combination. Select an Ubuntu release listed as supported at implementation time and pin package/image versions. [Docker Desktop Windows FAQ](https://docs.docker.com/desktop/troubleshoot-and-support/faqs/windowsfaqs/), [Docker Engine on Ubuntu](https://docs.docker.com/engine/install/ubuntu/)

Planned services:

| Windows host | Ubuntu/Compose |
| --- | --- |
| MT5 with EA in a dedicated interactive user session | PostgreSQL with a persistent data volume |
| RDP and human browser | Optional Redis |
| Caddy reverse proxy/local HTTPS bridge as an auto-start service | Admin API, orchestration worker, Telegram collector, dashboard |
| Cloudflared as an auto-start service | Separate risk/bridge HTTP-worker service; maintenance/notifications |
| Windows boot/supervision task for WSL | Systemd-managed Docker Engine |

The risk/bridge service is an independent entrypoint of the shared Python monolith, with its own container identity, environment and database role. It owns request/event authentication keys, response/command signing, replay verification, deterministic dispatch revalidation, and authoritative account/market/portfolio projections. Caddy routes the local EA HTTPS origin only to this service. The normal admin API receives no bridge keys or authority to write those projections; it reads redacted state and submits authenticated administrative intents.

### Startup must be supervised from Windows

Enabling systemd in WSL allows normal Linux service configuration, but Microsoft states that systemd services do not keep the WSL instance alive. Container restart policies and `systemctl enable docker` are therefore insufficient evidence of unattended recovery. [WSL systemd](https://learn.microsoft.com/en-us/windows/wsl/systemd/)

The proposed launcher runs as a dedicated Windows account that owns the imported Ubuntu distribution. WSL distributions are installed per Windows user, so launching as SYSTEM cannot be assumed to access a distribution registered for an administrator. [WSL environment setup](https://learn.microsoft.com/en-us/windows/wsl/setup/environment)

Register a Windows at-startup task that can run before desktop login under that account. It starts the named distribution, checks Docker, brings up the approved Compose release, and maintains a persistent foreground supervisor inside WSL. Configure unlimited task duration, restart on failure, one instance, and a health watchdog with bounded recovery. Use absolute executable/distribution names. Task credentials are supplied through Windows credential handling, never a committed script or service XML. This launcher is a design inference that must be tested on the actual Windows build and account; Task Scheduler's ability to run without login does not itself validate WSL startup. [Task Scheduler principals](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/new-scheduledtaskprincipal)

Health checks must prove database readiness, schema compatibility, worker heartbeats, and recovery reconciliation. Process liveness alone is insufficient. Do not replay stale trade commands merely because containers restarted.

### Networking

Default WSL2 NAT supports Windows applications reaching Linux services through Windows localhost forwarding. Use this for the host proxy and EA bridge. Do not hardcode the WSL virtual IP: it can change. Do not assume the Windows 11 mirrored-networking feature applies to the selected Windows Server build. Keep public firewall access closed for API, dashboard origin, Redis, and PostgreSQL. Verify localhost forwarding from service accounts before desktop login and after reboot; if the intended loopback bindings fail, choose Mode B rather than opening broad listeners as a shortcut. [WSL networking](https://learn.microsoft.com/en-us/windows/wsl/networking)

Store PostgreSQL data and container volumes on the Linux filesystem inside the WSL virtual disk. Plan backups and restores outside that single virtual disk; a Compose volume is not a backup. A VPS/disk failure remains a single-host availability limit.

## Mode B: native Windows services

Mode B requires no virtualization and no container runtime:

| Component | Planned native deployment | Recovery and security |
| --- | --- | --- |
| PostgreSQL | EDB installer linked by PostgreSQL; native Windows service | Auto-start; local binding; restricted database role; separate migration credential |
| Admin FastAPI API | Pinned Python virtual environment; Uvicorn with standard asyncio loop | WinSW automatic service; local binding; no bridge keys or authoritative telemetry writes |
| Risk/bridge HTTP-worker | Separate entrypoint of the same Python package; Uvicorn/asyncio plus deterministic execution worker | Independent WinSW service identity, env and DB role; bridge keys/replay/signing/authoritative telemetry; local bridge route only |
| Orchestration worker | Same Python package; durable PostgreSQL job leases/outbox | Separate WinSW service; heartbeat; idempotent recovery |
| Telegram collector | Same Python package; Telethon | Separate WinSW service; encrypted session file; reconnect backoff |
| Next.js | Windows-built `output: standalone`; `node server.js` | WinSW service; include public/static assets; local binding |
| Redis | Disabled by default in this mode | PostgreSQL-backed cache/rate-limit/session and durable job implementations remain available |
| Caddy | Native Windows executable | Service; local TLS bridge/proxy; request limits |
| Cloudflared | Native Windows executable | Service; explicit Access policies; protected tunnel credential |
| MT5 | Native desktop terminal | Interactive session; at-logon startup; separate health gating |

PostgreSQL's current Windows installer table lists PostgreSQL 18 tested on Server 2022/2025, and PostgreSQL 17/16 on Server 2019/2022. Use one tested OS/database pairing. PostgreSQL's `pg_ctl register` supports native service registration and automatic startup. [Windows installers](https://www.postgresql.org/download/windows/), [pg_ctl](https://www.postgresql.org/docs/current/app-pg-ctl.html)

Uvicorn's built-in multiprocess manager uses spawn and works on Windows; Unix signal-based worker administration is unsupported there. Use one API worker initially unless measured load justifies more, keep background jobs outside API processes, and choose `asyncio`, since uvloop is not Windows-compatible. Do not require Gunicorn for the native deployment. [Uvicorn deployment](https://www.uvicorn.org/deployment/), [Uvicorn settings](https://www.uvicorn.org/settings/)

Next.js standalone output supplies `server.js`, but `public` and `.next/static` require inclusion in the deployment artifact. A monorepo must set its tracing root correctly. Build Windows artifacts on Windows CI or on the target host so native dependencies are appropriate; copying macOS native modules is not a supported release strategy. [Standalone output](https://nextjs.org/docs/app/api-reference/config/next-config-js/output)

Redis's current installation overview offers Windows through Docker only. Do not rely on an abandoned/unofficial Windows Redis executable. A managed Redis service is an optional future adapter, not a paid prerequisite. Retain PostgreSQL as the execution source of truth. [Redis installation](https://redis.io/docs/latest/install/)

WinSW is a Windows service wrapper; the project currently identifies stable 2.x releases and prerelease 3.x releases. Pin the selected stable executable and checksum, review its release provenance, and use its corresponding documentation. Do not download an unpinned wrapper during every boot. Configure automatic service startup, working directories, restrictive service identities/ACLs, controlled restart, graceful stop, and log rotation; credentials do not belong in service XML. Actual stop behavior and restart behavior require native testing. [WinSW project](https://github.com/winsw/winsw), [WinSW releases](https://github.com/winsw/winsw/releases)

Caddy's own documentation provides Windows service deployment through Windows service control or WinSW, making it suitable as the shared host-level proxy in both modes. [Caddy service deployment](https://caddyserver.com/docs/running)

Services start with backoff when dependencies are temporarily unavailable. Apply migrations as an explicit controlled deployment step, then start compatible services. Never let every worker race to run migrations on boot. Restrict release files to read/execute for runtime accounts and grant write access only to specific data/log directories.

## MT5, interactive login, and reboot behavior

MT5 is a GUI terminal, and its EA depends on that terminal running. Windows services run in Session 0 and cannot directly interact with users; wrapping MT5 as an interactive service is not the recommended design. [Microsoft interactive services](https://learn.microsoft.com/en-us/windows/win32/services/interactive-services)

Use a dedicated non-administrator trading user, a saved MT5 profile with the EA attached, explicit account/EA allowlists, and an at-logon task configured to run in that user's interactive session. MT5 documents profile/config startup arguments. Use the normal per-user data directory; avoid the Program Files portable-mode path that requires disabling UAC. [MT5 startup](https://www.metatrader5.com/en/terminal/help/start_advanced/start), [Task Scheduler logon trigger](https://learn.microsoft.com/en-us/windows/win32/taskschd/starting-an-executable-when-a-user-logs-on)

An RDP disconnect normally preserves session processes; signing out terminates them. Audit the VPS's disconnected-session time limits and reconnect to the same trading user's session. Test lock, disconnect, idle timeout, reconnect, and logout separately. [Microsoft session behavior](https://learn.microsoft.com/en-us/troubleshoot/windows-server/remote/terminal-server-startup-connection-application)

The safest default is: backend services return before interactive login, new execution remains paused while MT5 is absent, the operator logs in after reboot, MT5 starts, and broker/account/position reconciliation must complete before new orders become eligible. Existing broker-held stops should already have been verified; local trailing-stop/EA logic is unavailable while the terminal is stopped. This default does not meet a claim of hands-free trading resumption after every reboot, and documentation must say so.

An optional hands-free profile may use Microsoft Sysinternals Autologon for the dedicated low-privilege trading account, then start MT5 and immediately lock the desktop. Microsoft warns that administrators can retrieve and decrypt the LSA-stored password. Autologon is not configured by default, and should be an explicit deployment security decision; do not put its password in command-line arguments or repository files. A real reboot, policy, and password-rotation test is required. [Sysinternals Autologon](https://learn.microsoft.com/en-us/sysinternals/downloads/autologon)

No choice about Autologon blocks Phase 1 development. It becomes a deployment gate only if unattended MT5 recovery without a human login is required. Manual recovery is the safer documented default.

## Cloudflare Tunnel, Access, and RDP

Cloudflare Tunnel uses outbound connections, so no public inbound application ports are necessary. Cloudflared supports running as a Windows service; use a protected configuration/credential location appropriate to its actual service account rather than assuming the interactive user's profile. Give the connector only the required routes. [Tunnel overview](https://developers.cloudflare.com/tunnel/), [Windows service instructions](https://developers.cloudflare.com/tunnel/features/locally-managed-tunnels/as-a-service/windows/)

Create separate Access applications/policies for the dashboard and RDP, allow only approved identities, require MFA, and retain ADMIN/VIEWER authorization and authenticated application sessions. A published RDP route alone is not private: Cloudflare explicitly recommends adding an Access application. Keep Windows Network Level Authentication enabled and restrict RDP users; deny inbound public 3389 at the Windows firewall and provider firewall after testing the tunnel and out-of-band recovery console. [RDP over Access](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/use-cases/rdp/rdp-cloudflared-authentication/), [Microsoft RDP/NLA](https://learn.microsoft.com/windows-server/remote/remote-desktop-services/remotepc/remote-desktop-allow-access)

If Access identity is used in application logic, validate the JWT signature, issuer, audience, and expiry; do not trust a submitted email/header as identity. Local dashboard access still requires application authentication. [Access JWT validation](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/)

Keep the EA bridge on a separate local HTTPS route with its own machine authentication and HMAC/replay controls. EA operation on the same host should not depend on Internet reachability of a Cloudflare hostname or on interactive Access login. Provision a local certificate chain trusted by Windows/MT5 and validate under the trading account. If a remote bridge is introduced later, use a dedicated Access Service Auth policy/service token in addition to the bridge protocol; its secret is server-side, not a browser credential. [Access service tokens](https://developers.cloudflare.com/cloudflare-one/access-controls/service-credentials/service-tokens/)

## Deployment validation gates

| Gate | Required evidence | Current status |
| --- | --- | --- |
| VPS eligibility | Provider, Windows build/edition, CPU/RAM/disk, Desktop Experience, console/recovery access | Unknown; deployment prerequisite |
| Mode A capability | Provider nesting enabled; WSL2 starts; supported Ubuntu/Docker install; boot owner sees distro | Not run |
| Mode B packaging | Windows CI backend tests, standalone build, installer/service smoke test | Planned |
| Pre-login backend reboot | Reboot and observe DB, admin API, risk/bridge, dashboard, collector, workers, proxy, tunnel before RDP login | Not run; mandatory |
| WSL continuity | Disconnect/sign out, terminate WSL, kill launcher/Docker, recover without interactive login | Not run; required for Mode A |
| MT5 startup | Trading-user logon; correct demo account/profile/EA; heartbeat and reconnect | Not run |
| TLS and exposure | MT5 certificate trust; blocked external ports; Access denial/allowance; local auth | Not run |
| Broker recovery | Reconcile pending/uncertain commands and open positions; no duplicate trade after restart | Not run; demo only |
| Backup recovery | Restore into clean DB/release; keep automation paused until reconciliation | Not run |
| Hands-free GUI recovery | Security decision on optional Autologon; real locked-desktop reboot verification | Optional deployment gate |

The architecture can proceed without the target VPS being known because Mode B is preserved. Neither Windows recovery nor real MT5/demo trading can be honestly marked tested on the available macOS environment.
