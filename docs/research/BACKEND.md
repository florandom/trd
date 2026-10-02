# Backend research and proposed baseline

Research date: **2026-10-02, Europe/Rome**. Scope: Phase 0 documentation only. No application, dependency lock, migration, or service has been created or exercised by this research.

The research recommendations below have been reconciled to the final Phase 0 proposal in [ARCHITECTURE.md](../ARCHITECTURE.md) and [ENVIRONMENT.md](../ENVIRONMENT.md). Those main documents define the proposed product policy; this document supplies supporting evidence and implementation guidance. All decisions still await the user's Architecture Approval Gate, and none imply production acceptance.

## Evidence and confidence

The package versions below were read directly from the public PyPI JSON API on the research date. Release timestamps are UTC. Official library documentation was opened separately to verify architecture constraints. Package metadata, Python classifiers, and wheel availability establish an install candidate; they do **not** establish that the whole application has passed integration tests. Phase 1 must resolve and lock the dependency graph and run the compatibility checks below.

The local shell currently resolves `python3` to Python **3.9.13**. That interpreter is unsuitable for the proposed backend; no existing local Python environment is assumed to be the project environment.

## Proposed runtime and dependency baseline

Use standard, GIL-enabled **CPython 3.13.16**, not an experimental free-threaded build. Python's official page identifies it as the final full maintenance release of the 3.13 series, released September 30, 2026; subsequent 3.13 releases receive security fixes. Schedule a tested Python 3.14 upgrade rather than treating 3.13 as a permanent choice. [Python release](https://www.python.org/downloads/release/python-31316/)

| Dependency | Verified candidate | Published UTC date | Phase 1 constraint | Evidence |
| --- | --- | --- | --- | --- |
| FastAPI | 0.142.2 | 2026-09-30 | `>=0.142.2,<0.143` | [Registry](https://pypi.org/pypi/fastapi/0.142.2/json) |
| Pydantic | 2.13.5 | 2026-08-28 | `>=2.13.5,<2.14` | [Registry](https://pypi.org/pypi/pydantic/2.13.5/json) |
| Pydantic Core | **2.46.5**, required by Pydantic 2.13.5 | 2026-08-28 | Let Pydantic select its exact dependency; do not independently upgrade it | [Registry](https://pypi.org/pypi/pydantic-core/2.46.5/json) |
| Pydantic Settings | 2.15.0 | 2026-08-07 | `>=2.15.0,<2.16` | [Registry](https://pypi.org/pypi/pydantic-settings/2.15.0/json) |
| SQLAlchemy | **2.0.54** maintenance branch | 2026-09-15 | `>=2.0.54,<2.1` | [Registry](https://pypi.org/pypi/SQLAlchemy/2.0.54/json) |
| Alembic | 1.20.0 | 2026-09-11 | `>=1.20.0,<1.21` | [Registry](https://pypi.org/pypi/alembic/1.20.0/json) |
| Psycopg 3 | 3.3.6 | 2026-09-18 | `psycopg[binary]>=3.3.6,<3.4` | [Registry](https://pypi.org/pypi/psycopg/3.3.6/json) |
| Uvicorn | 0.54.0 | 2026-09-25 | `>=0.54.0,<0.55`; use minimal package initially | [Registry](https://pypi.org/pypi/uvicorn/0.54.0/json) |
| Telethon | 1.45.0 | 2026-09-10 | `>=1.45.0,<1.46`; stable v1 API | [Registry](https://pypi.org/pypi/Telethon/1.45.0/json) |
| Argon2 CFFI | 25.1.0 | 2025-06-03 | `>=25.1.0,<26` | [Registry](https://pypi.org/pypi/argon2-cffi/25.1.0/json) |
| Cryptography | 50.0.2 | 2026-09-30 | `>=50.0.2,<51` | [Registry](https://pypi.org/pypi/cryptography/50.0.2/json) |
| PyOTP | 2.10.0 | 2026-06-14 | `>=2.10.0,<2.11` | [Registry](https://pypi.org/pypi/pyotp/2.10.0/json) |
| HTTPX | 0.28.1 | 2024-12-06 | `>=0.28.1,<0.29` | [Registry](https://pypi.org/pypi/httpx/0.28.1/json) |
| Structlog | 26.1.0 | 2026-06-06 | `>=26.1.0,<27` | [Registry](https://pypi.org/pypi/structlog/26.1.0/json) |
| OpenAI Python SDK, Phase 5 adapter only | 3.23.0 | 2026-10-01 | Reverify in Phase 5; lock an exact tested SDK then | [Registry](https://pypi.org/pypi/openai/3.23.0/json) |

These are resolver inputs, not mutable production installs. Commit one lockfile including transitive dependencies, hashes, platform markers, and the exact runtime once Phase 1 passes. Review updates explicitly. FastAPI 0.142.2 requires Pydantic `>=2.9.0`, and Alembic 1.20.0 requires SQLAlchemy `>=2.0`; the proposed versions satisfy those declared requirements. SQLAlchemy's newest release was 2.1.2 on the research date. Choosing the 2.0 maintenance branch is a conservative architecture decision, not a claim that 2.1 is incompatible.

Pydantic Core 2.46.5 and Psycopg Binary 3.3.6 provide CPython 3.13 wheels for Windows x64, macOS ARM64/x64, and Linux. Argon2 CFFI Bindings 26.1.0 and Cryptography 50.0.2 provide compatible stable-ABI Windows x64/macOS ARM64 wheels; CFFI 2.1.1 and Greenlet 3.5.6 provide CPython 3.13 wheels. Verify the complete locked graph on each target. Telethon's declared Python requirement admits 3.13 but its classifiers do not explicitly certify 3.13. Its `pyaes` 1.6.1 dependency is old and source-only, so a blanket wheels-only installation policy would fail; audit and reproducibly build that dependency or reassess the adapter before production. [Psycopg Binary metadata](https://pypi.org/pypi/psycopg-binary/3.3.6/json), [Argon2 bindings](https://pypi.org/pypi/argon2-cffi-bindings/26.1.0/json), [CFFI](https://pypi.org/pypi/cffi/2.1.1/json), [Greenlet](https://pypi.org/pypi/greenlet/3.5.6/json), [PyAES](https://pypi.org/pypi/pyaes/1.6.1/json)

Choose **PostgreSQL 17**, current verified minor **17.11**, for the initial database. The official support table lists support through November 8, 2029. Keep the latest tested security minor in that major family; pin the development/production image digest and Windows installer version in Phase 1. PostgreSQL 18 is also supported, but no feature here requires that upgrade. Native Windows availability must be checked alongside the selected installer in deployment research. [PostgreSQL version policy](https://www.postgresql.org/support/versioning/)

## Process and persistence boundaries

Build one installable Python package containing domain, application, infrastructure, and API modules. Run separate entrypoints from the same package:

- **Normal administrative API:** dashboard authentication, settings and redacted read models; request administrative changes through typed use cases. It has no bridge keys, bridge verification/signing responsibility, approved-command/risk-reservation writes, or authoritative account/equity/position snapshot writes.
- **Telegram ingestion:** Telethon connection, source allowlist, normalized events, durable ingestion cursors; possesses only Telegram credentials and its database role.
- **Orchestration worker:** parsing, agent routing, AI adapters, usage accounting; possesses provider keys and can write proposals and agent records, but cannot write approved commands or risk reservations and cannot read bridge signing keys.
- **Isolated risk/bridge HTTP-worker:** the sole application writer of risk reservations and approved signed commands. Its separate local HTTP entrypoint owns machine authentication, replay verification, inbound telemetry, authoritative account/position projections, dynamic signed responses and command delivery. It recomputes hard bounds, fresh account/symbol data, portfolio exposure, and command eligibility. Its role is restricted to required risk/execution data and has no AI or Telegram credentials. The normal dashboard edge does not expose this bridge entrypoint.
- **Maintenance worker:** retention and scheduled reconciliation/health jobs with a restricted role. It cannot purge open-position evidence or alter hard safety limits.

A deployment migration role creates schemas/grants and is absent from service runtimes. Database ownership/grants must actually enforce these boundaries; using separate processes with a shared superuser URL would not enforce them. Execution-command signatures remain a second control if proposal/config data is compromised. Only the isolated bridge serves commands authorized by risk; the administrative API does not synthesize command payloads from browser or AI input. Authenticated bridge telemetry is still schema/bounds checked before the isolated role updates authoritative projections.

Use SQLAlchemy 2 typed mappings/repositories and synchronous Psycopg 3 database units of work initially. FastAPI synchronous handlers and bounded worker thread calls can execute complete units of work, creating and closing the session inside the same thread. Never share a SQLAlchemy session across concurrent tasks or threads; never hold a database transaction while awaiting an AI provider or Telegram network operation. Network integrations remain async. [SQLAlchemy Psycopg dialect](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#module-sqlalchemy.dialects.postgresql.psycopg)

This avoids a verified Windows constraint: Psycopg async connections do not support the default Proactor event loop and require a Selector loop. If a later phase adopts async database access, explicitly configure and test that loop in every Windows entrypoint. Uvicorn's optional `uvloop` is excluded on Windows by package markers; do not make it a runtime requirement. [Psycopg async Windows constraint](https://www.psycopg.org/psycopg3/docs/advanced/async.html), [Uvicorn dependency markers](https://pypi.org/pypi/uvicorn/0.54.0/json)

Store UTC aware timestamps in `timestamptz`; use Python `Decimal` and PostgreSQL `numeric` for prices, lots, account values, costs, and risk. Serialize financial values as explicitly typed decimal strings at JSON boundaries and reject NaN/infinity, excessive precision, invalid scales, and unsupported symbols. Instrument metadata drives tick/lot quantization. Keep database enums/state transitions explicit and migration-owned. Review generated Alembic migrations, then test fresh upgrades and representative previous-schema upgrades. Alembic itself warns that autogeneration requires manual review. [Alembic guidance](https://alembic.sqlalchemy.org/en/latest/autogenerate.html)

## Durable jobs and transactional outbox

**Recommendation:** PostgreSQL is the durable job store and outbox. Redis may run in development and be enabled as an expendable cache; sessions, budgets, risk reservations, replay protection, and command delivery remain correct with Redis unavailable. This preserves an uncomplicated Windows-native fallback and avoids adding a broker. Celery explicitly does not support Microsoft Windows. [Celery support statement](https://docs.celeryq.dev/en/stable/getting-started/introduction.html)

The mechanics below are proposed application design, not properties automatically provided by a framework:

1. Commit the business state transition, audit record, and outbox/job insertion in one database transaction. A unique semantic deduplication key identifies the logical action and version.
2. Workers claim due rows using a short `FOR UPDATE SKIP LOCKED` transaction, increment a lease generation, record owner/expiry, and commit before work. PostgreSQL explicitly documents this locking option for queue-like tables. [PostgreSQL SELECT locking](https://www.postgresql.org/docs/17/sql-select.html)
3. Persist attempts, retry-after time, deadline, maximum attempts, last classified error, and trace identifiers. Heartbeat long jobs with bounded leases; only the current owner/generation may commit completion. Late workers cannot overwrite the newer worker's state.
4. Poll indexed ready jobs with bounded idle delay; notification hints are optional. A missed hint never loses work. Apply exponential backoff with jitter and dead-letter visibility, and expire stale signals before any reasoning or execution step.
5. Job processing is **at least once**. Repository constraints and state-machine checks make repeat internal transitions idempotent. Never claim exactly-once external effects from a queue lease or transaction alone.
6. Keep execution command delivery separate from generic retry jobs. Persist a command once; every delivery uses the same signed command ID and expiry. Lost acknowledgement, a crash after submission, or ambiguous broker state becomes **OUTCOME_UNKNOWN / reconciliation required**. Do not automatically issue a fresh command ID or resubmit a broker order because a job lease expired.

For risk admission, lock a per-account risk coordinator row and read the active settings version in the same transaction. Recompute exposure including open positions, pending approved commands, and unresolved commands. Reserve risk, persist the decision/audit, and create the unique approved command atomically. Respect a deterministic lock order and bounded lock timeouts. Immediately before delivery, rerun all applicable deterministic gates under the account lock using current equity, daily loss, portfolio, quotes/metadata, config and health; count the command's own existing reservation exactly once. Fresh snapshots alone are insufficient. Revoke a no-longer-valid immutable request before delivery rather than silently changing its signed economics. Tightening limits must not leave pending commands eligible. Release reservations only on confirmed safe terminal outcomes or broker reconciliation; command expiry alone does not prove that a submitted order did not fill.

Account identity must include broker/server, login/account ID, and the account's verified demo/live mode. The default transport target is the simulator/paper mode. Enabling a demo bridge must validate that identity tuple. `ENABLE_LIVE_TRADING=false` is the immutable deployment default, and a dashboard toggle alone cannot enable live execution.

PostgreSQL unavailable means no new durable ingestion acknowledgement, no new AI budget reservation, no risk admission, and no command authorization. EA-side protection of existing positions must remain independent of database or backend availability.

For future managed PostgreSQL, prefer direct/session connections initially. Pooling modes, connection limits, TLS verification, and Psycopg prepared-statement behavior require testing before a Supabase-like transaction pooler is enabled. No domain logic may depend on a local hostname, Unix socket, or filesystem path. Upstash migration should affect only an optional cache adapter.

## Telegram ingestion and session security

Telethon stable v1 supports persistent sessions, reconnect settings, update handlers, and a catch-up API. Its default SQLite session contains an authorization key; a StringSession exports authorization material and must be treated as an account credential. Anyone possessing it can use that account. Telethon does **not** promise application-level encryption of its default session file. [Session documentation](https://docs.telethon.dev/en/stable/concepts/sessions.html), [Client reconnect/catch-up API](https://docs.telethon.dev/en/stable/modules/client.html)

Proposed V1 storage: encrypt a **StringSession** credential using authenticated encryption and a separate `TELEGRAM_SESSION_ENCRYPTION_KEY`, then load it only into the ingestion process. The encryption key is outside the database and repository. Use a library AEAD construction, fresh nonce, associated data binding the credential to its account/schema version, key ID, atomic persistence, restricted permissions, and encrypted backups. Initial Telegram phone/code/2FA enrollment is an explicit local operator command; never print the resulting session, put it in browser responses, or accept login codes through an ordinary settings screen.

A StringSession is not a complete durable ingestion checkpoint. Persist independent per-source history cursors and reconciliation windows in PostgreSQL. On restart/reconnect, fetch a bounded overlapping history window, upsert message revisions, and enforce signal-age expiry before reprocessing. Verify edit handling across disconnections during Phase 4; neither a reconnect flag nor a message-ID high-water mark proves that offline edits were recovered. A long outage or inaccessible source is visible degraded state with a documented gap, not a claim of complete history.

Run one active ingestion owner per Telegram account with an expiring, fenced database lease. Handle flood waits, source removal, revoked sessions, and bounded connection retries explicitly. On loss of durable database storage, stop advancing cursors and catch up after recovery instead of accumulating an unbounded in-memory backlog.

Use unique keys for `(telegram_account_id, peer_id, message_id)` and revision hashes/edit timestamps. Store normalized new/edit/delete/reply events and retain tombstones longer than raw message bodies. Cross-source duplicate content requires separate candidate deduplication; messages from two channels have different Telegram IDs. An edit creates a signal version and invalidates prior unsubmitted proposals. An edit/cancellation after submission becomes a position-management event subject to deterministic risk controls; it cannot silently rewrite a trade record or generate a second opening command.

## Dashboard authentication

Use backend-owned, revocable opaque sessions rather than browser-stored bearer JWTs. This is a small administrative system with no need for application-level federation in V1. External production access initially requires Cloudflare Access MFA; without Access or a subsequently implemented equivalent MFA gate, access remains local/VPN-only. The Access identity assertion is validated when relied on, and it does not replace application RBAC.

- Hash passwords with **Argon2id** through Argon2 CFFI; benchmark a documented parameter profile on the smallest supported VPS and bound concurrent hashing to prevent memory exhaustion. Never go below the OWASP baseline of 19 MiB, two iterations, one lane without a documented security reassessment. Rehash successful logins when parameters change. [OWASP password storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html), [Argon2 parameter guidance](https://argon2-cffi.readthedocs.io/en/stable/parameters.html)
- Generate a 256-bit random session verifier; store only its SHA-256 hash, user ID, expiry, recent authentication time, and revocation state. Rotate on authentication or privilege change. Use a production `__Host-` cookie with `Secure`, `HttpOnly`, `SameSite=Lax`, `Path=/`, and no `Domain`. Final proposed default policy: 30-minute idle and **8-hour absolute lifetime**, explicit logout/revoke-all, and no persistent remember-me. SameSite=Lax is coupled to the CSRF/Origin controls below. These times are product decisions to validate with usage, not standards requirements. [OWASP session guidance](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)
- Serve dashboard and API through one origin. All browser state-changing endpoints require a session-bound synchronizer CSRF token in a header plus validated Origin, JSON content type, and restrictive CORS. Protect login/enrollment as well as authenticated changes; GET never mutates. Reject cross-site Fetch Metadata where present. Bridge endpoints use their machine authentication separately and do not accept browser cookies. [OWASP CSRF guidance](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)
- **Optional local TOTP contract, for later implementation:** enrollment with encrypted TOTP seeds, one-time hashed recovery codes, login throttling, and an atomic last-accepted counter to reject replay. Do not treat a QR code generation step as completed enrollment: verify a code first. TOTP is not a mandatory local Phase 1 feature or a substitute for an unimplemented external-access MFA gate. Require fresh authentication for sensitive risk/model/security changes. TOTP is susceptible to phishing; future WebAuthn can improve this. [PyOTP security guidance](https://pyauth.github.io/pyotp/)
- Bootstrap an administrator with a local CLI and operator-supplied credential. Do not ship a default password; remove bootstrap secrets from routine service environments. Log authentication outcomes, not credentials, session cookies, CSRF tokens, or TOTP/recovery values. Store rate-limit state in PostgreSQL so the policy survives restarts and Redis failure.

Confirmation dialogs for settings changes are UX controls. Backend authorization, bounds, optimistic settings-version checks, CSRF, fresh authentication, and append-only audit records enforce the change. Emergency actions require ADMIN and single-use, short-lived confirmation bound to the exact targets/state; an authenticated kill switch should not add a fresh MFA challenge. Enabling automation or increasing risk requires fresh authentication. A paused account can still request a confirmed managed close/cancel under a separate deterministic reduction policy with account/ownership checks. API downtime/unknown session state does not permit administrative writes.

## Provider-agnostic AI contracts and routing

Implement `AIProvider`, `AIModel`, `AgentDefinition`, `AgentExecution`, `AgentResult`, `ModelRegistry`, and immutable `PromptVersion` as application contracts, with provider SDKs confined to adapters. Use a deterministic mock provider first and one real OpenAI adapter in Phase 5. Anthropic, Google, Moonshot/Kimi, and TypeSafe/Jev remain optional adapters. Do not assume those providers share an API, identical schema dialects, or identical token accounting.

Each registry entry records allowlisted provider/model ID, supported schemas/modality/reasoning controls, token/context limits, model availability verification time, enabled status, adapter version, price currency/unit, and price verification time. Resolve a dashboard choice to an internal registry ID. Arbitrary model IDs, endpoints, and provider base URLs are forbidden from dashboard input. Validate an acyclic bounded fallback chain whose members satisfy the same mandatory stage/schema requirements.

Each run snapshots config version, prompt checksum/version, input revision hash, schema version, provider/model ID, trace/signal IDs, deadline, latency, usage, cost estimate, outcome, and classified provider error. Record a concise reason/evidence summary, not private chain-of-thought. Validate finite numeric values, enums, symbol mappings, freshness, provenance, and all business rules after schema validation. An AI confidence field is a claim, not calibrated permission to execute.

Routing is deterministic: source allowlist and cheap format/noise checks, then allowlisted classifier, then a deterministic parser for supported formats, then analyst/decision stages when required, then optional critic, then the isolated risk worker. Noisy or ambiguous inputs never obtain a lower mandatory-review policy merely because a cheaper provider was selected. A fallback or disabled optional critic is audited; if a rule requires that critic and its budget/provider is unavailable, reject or escalate.

Telegram bodies and historical memory remain untrusted data fields. No model receives infrastructure/API keys or bridge credentials. No model may invoke tools, fetch arbitrary URLs, rewrite prompts, mutate risk/settings, execute SQL, or write an approved command. Keep external URLs as inert data and escape text in the dashboard.

### OpenAI adapter evidence

Official OpenAI documentation was researched with the **OpenAI Docs** skill. Use the Responses API for the initial adapter, with strict structured output on supported registered models. The API supports only a subset of JSON Schema and provides refusal/incomplete outcomes; even an output that conforms to a schema still needs application validation. Map refusal, incomplete output, unsupported schema, and invalid semantic values to explicit failures. [Structured output guide](https://developers.openai.com/api/docs/guides/structured-outputs)

Set a bounded `max_output_tokens`; its ceiling includes visible output and reasoning tokens. Normalize input/output/cached/reasoning usage details into provider-neutral accounting without counting a breakdown twice. Use a total application deadline, not only individual HTTP-attempt timeouts. No tools are supplied to this adapter. [Responses API reference](https://developers.openai.com/api/reference/python/resources/responses/methods/create)

Set `store=false` for ordinary stateless requests and send only necessary redacted signal/context data. This reduces Responses application-state retention; it does **not** promise zero provider retention. Abuse monitoring, caching, account policies, and other features have their own documented behavior; special retention approval is not assumed. The application's seven-day raw-response cleanup cannot delete all provider-side records. [OpenAI data controls](https://developers.openai.com/api/docs/guides/your-data)

Bound retries and respect valid `Retry-After` delays. When the application owns retry/fallback policy, disable SDK retries or include them in the total attempts/deadline/reservation policy. Do not retry quota/billing failures indefinitely. Official guidance notes that unsuccessful attempts also consume rate limits. [OpenAI rate-limit guidance](https://developers.openai.com/api/docs/guides/rate-limits)

No concrete production model IDs, live account access, pricing, or calibration are approved by Phase 0. In Phase 5 select registered models from current official capabilities/pricing, verify the deployment account's access, and evaluate fixed Telegram fixtures. Phase 1 can seed disabled placeholder configurations and the mock provider without provider secrets.

## AI budget reservation and ambiguous provider outcomes

Create atomic budget buckets for global daily, global monthly policy, and per-agent limits. Before a provider attempt, lock buckets in a deterministic order, subtract committed spend and active reservations, and reserve a conservative maximum charge using a verified price version, a bounded input, and the output/reasoning ceiling. Track Decimal cost and native currency; EUR presentation requires a timestamped exchange-rate estimate and never replaces USD budget accounting.

Input token estimates are not inherently exact. If an adapter cannot establish a defensible maximum charge, a strict maximum-cost mode must refuse that provider/model. Do not assume cached-input discounts when reserving. Enforce the provisioned daily, monthly and per-request server cost envelopes before a new reservation; zero-valued bootstrap envelopes permit only mock calls. Within those hard bounds, a separate monthly soft budget warns or adjusts optional stages according to explicit policy. Provider account spend limits are an additional safeguard, not the sole control.

Settle against reported usage and release only known unused reservation amounts. A timeout after sending a request can still incur provider charges. Retain its conservative reservation as `UNKNOWN_COST` until reconciliation or conservative final charging; do not immediately return the full amount to the budget and spend it on fallback calls. Every retry/fallback attempt needs its own reservation. A crashed worker cannot reclaim a reservation merely because its processing lease expired. Unknown or excessive charges block subsequent admission as required by policy and surface an alert.

Fallbacks may switch to a cheaper compatible registered model, omit an explicitly optional critic, or reject AI-dependent candidates. They never skip mandatory analysis or relax deterministic risk. Test concurrent admissions, provider timeout after submission, usage missing, price version unavailable, cached/reasoning accounting, and crash/restart before settlement.

## Required validation gates and open assumptions

**Phase 1:** create the lock; install/import the locked stack on CPython 3.13 Linux and Windows x64 plus macOS development; test minimal Uvicorn/FastAPI health and Pydantic strict schemas; migrate an empty PostgreSQL 17 database; verify runtime roles cannot write another process's protected tables; validate malformed/missing production settings; and prove secrets are redacted. An import-only pass is insufficient for Windows production acceptance.

**Phase 2 / queue spike:** crash between claim/work/commit, reclaim expired leases, reject late generation writes, exercise duplicate jobs, and prove transactional state-plus-outbox insertion. Test atomic per-account admission and verify replay keys survive raw-data retention cleanup.

**Phase 3:** test login/session rotation/revocation, CSRF and Origin failures, bounded password hashing/rate limits, settings version races, and the external Access MFA gate before exposing a production dashboard. If optional local TOTP is implemented, add replay/concurrency/enrollment tests before enabling it. Auth controls are foundational, not postponed until the final hardening phase.

**Phase 4:** exercise reconnects, flood waits, revoked sessions, bounded history catch-up, duplicate new/edit events, missed offline edits, overlapping-history reconciliation, database outages, and retention while a signal has an open position. Real Telegram enrollment requires operator credentials and a permitted source account; no secrets were requested or stored during this research.

**Phase 5:** mock refusal/invalid JSON/invalid semantics, timeout, provider outage, bounded retries, unavailable model, unknown price, concurrent budgets, and incomplete usage. Verify prompt injection fixtures cannot affect system configuration or execution authorization.

Unresolved deployment validation includes actual Windows Server version, VPS virtualization capability, CPU/RAM sizing for Argon2 and worker concurrency, broker account/symbol semantics, and real provider account access. These do not prevent a paper/simulator Phase 1 foundation. External demo execution, MT5 runtime tests, reboot recovery, and real Telegram connection tests remain later acceptance gates and must never be marked passed from documentation alone.
