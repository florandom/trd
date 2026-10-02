# Environment and configuration matrix

Status: Phase 0 proposal, 2 October 2026. No `.env`, real credentials or production configuration has been created. The `.env.example` and validators are Phase 1 work. This matrix specifies their contract, rather than implying they already exist.

## Observed local environment

| Item | Observation | Implication |
| --- | --- | --- |
| Workspace | Empty at initial inspection; no AGENTS.md in inspected ancestor chain | No existing architecture or application to preserve |
| Git | 2.35.1 installed; initially no repository | Initialized for the requested Phase 0 documentation milestone; no application scaffold |
| OS | macOS 26.6.2, Apple silicon/arm64 | Linux containers and native macOS development must both be supported |
| Node | 24.20.0 in normal shell | Meets Astryx CLI >=22.13 and Next >=20.9 requirements |
| Escalated shell | Resolved Node 20.10/npm 10.4 during package installation | Pin explicit Node24 runtime/toolchain; do not infer identical privileged-shell PATH |
| npm / pnpm | 11.19.0 / 11.25.0 in normal shell | Pin project package manager; do not upgrade global tools during research |
| Python | Default python3 3.9.13 | Cannot run chosen Python3.13 backend; install/use pinned toolchain in Phase 1 or containers |
| Docker | Not found in PATH or standard `/Applications/Docker.app` binary location | User specification says Docker available; actual local boot remains unverified until runtime is located/installed |
| Network | Sandbox registry DNS failed; approved external package metadata/install succeeded | Research succeeded; do not attribute failures to package incompatibility |
| Windows/MT5 | No target host or broker runtime accessible | Native deployment, EA compile, demo, certificate and reboot tests not run |

The disposable Astryx/Next compatibility spike is outside the repository. See [Astryx evidence](research/ASTRYX.md) and [Phase 0 validation](PHASE_0_VALIDATION.md). No application runtime was installed into this workspace.

## Authority and units

Effective policy is the intersection of immutable hard server safety bounds, reviewed server policy, versioned database/dashboard config and the agent proposal. A later layer can tighten an earlier bound. Dashboard and AI cannot modify hard safety, service secrets, account enrollment or live authorization.

Use decimal strings for fractions, prices, money and volume: `0.01` means 1%, not 0.01%. Reject NaN/Infinity, negative inappropriate values and ambiguous percent notation. All times stored in aware UTC. `TIMEZONE` is display-only; UTC defines the risk policy day and cash-flow-adjusted baseline. DSNs and credentials are secrets even if they contain a local hostname.

The numeric defaults below are conservative test/bootstrap bounds, not a recommended real trading strategy. A fresh system has no permitted broker account/instrument and cannot trade until reviewed configuration is provisioned. Paper/demo configuration does not imply permission for real trading.

## Variable matrix

“Required” is evaluated for the service/mode that consumes the variable. Optional provider keys are required only when their adapter is enabled. Secrets are never emitted to browser, audit diff, health payload or logs. Dashboard sees only redacted presence/availability.

| Category / variable | Default / requirement | Secret | Consumer / authority |
| --- | --- | --- | --- |
| APP_ENV | `development`; enum development/test/production | No | All; deploy config |
| APP_URL | Local origin in development; required HTTPS production origin | No | API/edge; fixed trusted origin |
| LOG_LEVEL | `INFO`; production DEBUG needs reviewed redaction | No | All |
| TIMEZONE | `Europe/Rome` display; internal UTC | No | API/dashboard |
| ENVIRONMENT_ID | Unique paper/demo/live deployment identity; required | No | API/worker/bridge/EA |
| DATABASE_URL | Required per-process least-privilege DSN; no hardcoded password | Yes | Each Python process gets its own role-scoped value |
| MIGRATION_DATABASE_URL | Required only migration/bootstrap job | Yes | Deploy operator; absent from runtime |
| POSTGRES_DB | `trd` | No | Development database provisioning |
| POSTGRES_USER | Local bootstrap owner; never reused as app role | No | Development provisioning |
| POSTGRES_PASSWORD | Generated local value; required DB provisioning | Yes | DB/bootstrap only |
| REDIS_ENABLED | `false` native Windows; optional dev cache | No | API/optional cache adapter |
| REDIS_URL | Required only Redis-enabled mode | Yes | Cache users; never execution authority |
| AUTH_SESSION_TTL_SECONDS | `28800` maximum session age; idle expiry also enforced | No | API; deployment upper bound |
| AUTH_IDLE_TTL_SECONDS | `1800` | No | API |
| AUTH_COOKIE_SECURE | true in production; dev loopback HTTP exception only | No | API; cannot false in production |
| AUTH_ALLOWED_ORIGINS | Exact APP_URL; no wildcard | No | API; CSRF validation |
| AUTH_RATE_LIMIT_BACKEND | `postgres`; optional Redis with DB fallback | No | API |
| ENCRYPTION_KEY | Required random 32-byte key in documented encoding | Yes | API TOTP/secret-at-rest owner only |
| ADMIN_BOOTSTRAP_EMAIL | Required bootstrap; no default public credential | Personal | Bootstrap command only |
| ADMIN_BOOTSTRAP_PASSWORD | Strong supplied/generated password; one-time bootstrap | Yes | Bootstrap only; hash stored, remove env afterwards |
| AUTH_MFA_REQUIRED | false locally; production external MFA via Access initially | No | API/deploy policy |
| CLOUDFLARE_ACCESS_ISSUER | Required if trusting Access assertions | No | API; exact issuer allowlist |
| CLOUDFLARE_ACCESS_AUDIENCE | Required with issuer; verified signature/expiry | No | API; does not replace RBAC |
| TELEGRAM_API_ID | Required when collector enabled | Sensitive | Collector only |
| TELEGRAM_API_HASH | Required when collector enabled | Yes | Collector only |
| TELEGRAM_SESSION_ENCRYPTION_KEY | Independent required 32-byte key | Yes | Collector only |
| TELEGRAM_ENABLED | `false` until session enrollment | No | Collector/server config |
| TELEGRAM_SESSION_PATH | Platform data-dir relative path or explicit configured path | Sensitive | Collector; encrypted StringSession storage, restricted ACL |
| TELEGRAM_BACKFILL_MAX_AGE_SECONDS | Bounded reconnect history window; policy-configured | No | Collector; old messages still fail signal-age policy |
| OPENAI_API_KEY | Empty; enabled adapter requires it | Yes | AI worker only |
| ANTHROPIC_API_KEY | Empty; later optional adapter | Yes | AI worker only |
| GOOGLE_AI_API_KEY | Empty; later optional adapter | Yes | AI worker only |
| MOONSHOT_API_KEY | Empty; later optional adapter | Yes | AI worker only |
| TYPESAFE_API_KEY | Empty; later optional adapter | Yes | AI worker only |
| AI_PROVIDER_MODE | `mock` development/test; mock visibly simulated | No | AI worker; production registry policy rejects accidental mock live path |
| MODEL_REGISTRY_PATH | Reviewed deployment manifest; required for configured models | No | AI/API; no remote user-supplied URL |
| PROMPT_MANIFEST_PATH | Versioned checksum manifest | No | AI worker; no production free-form editing |
| AI_HARD_DAILY_BUDGET_USD | `0.00` fresh bootstrap; explicit provisioning for real calls | No | AI worker; upper cost envelope |
| AI_HARD_MONTHLY_BUDGET_USD | `0.00` fresh bootstrap | No | AI worker |
| AI_HARD_MAX_COST_PER_REQUEST_USD | `0.00` bootstrap; priced token reservation required | No | AI worker |
| AI_HARD_MAX_OUTPUT_TOKENS | `4096`; model capability may tighten | No | AI worker |
| AI_HARD_TIMEOUT_SECONDS | `30`; applies across configured bounded attempts | No | AI worker |
| MT5_BRIDGE_SHARED_SECRET | Independent 32-byte event/request HMAC key; enrolled identity | Yes | Bridge/EA only; not general API or AI |
| MT5_COMMAND_SIGNING_KEY | Independent 32-byte command/response HMAC key | Yes | Risk/bridge executor and EA only |
| MT5_BRIDGE_KEY_ID | Enrolled allowlisted rotation key ID | No | Bridge/EA |
| MT5_BRIDGE_INSTANCE_ID | Provisioned random identity; no ad hoc takeover | No | Bridge/EA enrollment |
| MT5_ALLOWED_ACCOUNT_IDS | Empty; reviewed JSON identity tuples login/server/mode | Sensitive | Hard server execution allowlist, not login numbers alone |
| MT5_BRIDGE_URL | Fixed local HTTPS origin, required for real EA | No | EA; no signal-supplied URLs/redirects |
| MT5_BRIDGE_BIND | Local loopback; separate from dashboard edge | No | Risk/bridge executor |
| MT5_COMMAND_TTL_SECONDS | `10`; must fit measured preflight latency | No | Risk/bridge; server maximum |
| MT5_HEARTBEAT_MAX_AGE_SECONDS | `10`; proposed pending runtime measurements | No | Risk/bridge health |
| MT5_MAX_CLOCK_SKEW_SECONDS | `3`; sync and replay checks | No | Bridge/EA; reject beyond configured bound |
| MANAGED_MAGIC_NUMBER | Per-environment configured integer | No | Risk/EA; ownership hint, not sufficient proof |
| TRADING_MODE | `paper`; enum paper/demo/live | No | Deployment-only; visible browser status |
| HARD_MAX_RISK_PER_TRADE | `0.01` fraction of equity | No | Risk executor; secure maximum |
| HARD_MAX_DAILY_LOSS | `0.03` cash-flow-adjusted equity fraction | No | Risk executor |
| HARD_MAX_TOTAL_OPEN_RISK | `0.03`; includes reservations/all-account exposure | No | Risk executor |
| HARD_MAX_OPEN_POSITIONS | `3`; includes reserved slots | No | Risk executor |
| HARD_MAX_LOTS | `1.00`; broker/instrument minimum/step still applies | No | Risk executor |
| HARD_MAX_EFFECTIVE_LEVERAGE | `10`; verified notional/equity calculation | No | Risk executor |
| HARD_ALLOWED_SYMBOLS | Empty; exact tested symbol/profile allowlist | No | Risk executor; dashboard subset only |
| HARD_REQUIRE_STOP_LOSS | `true` | No | Risk/EA; never relaxed through UI |
| HARD_REQUIRE_TAKE_PROFIT | `true` bootstrap | No | Risk/EA |
| HARD_MAX_SIGNAL_AGE_SECONDS | `120`; dashboard may tighten | No | Risk executor |
| HARD_MAX_SPREAD_POINTS | Profile-specific reviewed manifest; missing rejects | No | Risk/EA; no universal pip assumptions |
| HARD_MAX_SLIPPAGE_POINTS | Profile-specific reviewed manifest; missing rejects | No | Risk/EA |
| ALERT_TELEGRAM_BOT_TOKEN | Empty; required if notification adapter enabled | Yes | Maintenance/notification worker only |
| ALERT_TELEGRAM_CHAT_ID | Required when alerts enabled | Sensitive | Notification worker; fixed recipient |
| ALERT_COOLDOWN_SECONDS | `300`; incident-key dedup and recovery events | No | Notification worker |
| RAW_LOG_RETENTION_DAYS | `7` | No | Logging/maintenance; critical journal excluded |
| AI_RESPONSE_RETENTION_DAYS | `7` | No | Maintenance; compact validated evidence retained |
| TELEGRAM_RETENTION_DAYS | `7` | No | Maintenance; message anchors/hash retained |
| AUDIT_RETENTION_DAYS | `0` meaning no automatic deletion | No | Maintenance; reviewed policy required to change |
| TRADE_RETENTION_DAYS | `0` meaning no automatic deletion | No | Maintenance; open/uncertain positions protected |
| DATA_DIR | Platform-specific configured persistent service data directory | Sensitive | Each service; no hardcoded /tmp |
| LOG_DIR | Platform-specific protected/rotated log directory | Sensitive | Each service |
| LOG_MAX_BYTES / LOG_BACKUP_COUNT | `10485760` / `10` per process proposal | No | Logger; bounded disk use |
| ENABLE_AUTOMATION | `false` initial soft seed; requires confirmed ADMIN activation | No | Bootstrap default; subsequent versioned DB config within envelope |
| ENABLE_LIVE_TRADING | `false`; deployment-only hard gate | No | Risk/bridge; cannot browser-enable |
| ENABLE_CRITIC_AGENT | `false` bootstrap | No | Agent seed; later versioned enablement |
| ENABLE_ADAPTIVE_MEMORY | `false`; even enabled remains advisory | No | Memory/AI worker |
| ENABLE_PENDING_ORDERS | `false`; tested capabilities required | No | Risk/EA deployment policy |
| ENABLE_PARTIAL_CLOSE | `false`; tested account-mode behavior required | No | Risk/EA |

Opaque PostgreSQL sessions require no JWT signing secret. Do not add inert `AUTH_SECRET`/`SESSION_SECRET` variables just to imitate a framework. If later a library introduces signed tokens, add scoped keys and an ADR. Do not expose any `NEXT_PUBLIC_*` credential; the browser obtains only safe public status/config DTOs.

## Database/dashboard configuration

Database settings hold bounded soft risk/source/agent/session policies, allowed symbol subsets, trading calendars, AI soft budgets and behavior-on-exhaustion, retention options and notification preferences. They never hold plaintext provider keys. Changes use schema validation, hard-bound comparison, expected-version concurrency, explicit confirmation and audit. Failed validation makes no partial change.

Environment feature flags define fresh-install seeds or hard deployment permissions, as identified in the matrix. Once a soft setting is bootstrapped, restarting does not reset its database version. Deployment permission still takes precedence over stored settings. No fallback from unavailable database settings to permissive environment defaults.

## Secrets lifecycle

Generate cryptographic keys with OS CSPRNG, not copied placeholders. Validate encoding/length, independent purpose keys and enrolled account mode. Supply only service-specific variables through restricted secret files or Windows ACL-protected service environment; Compose source `.env` may be used by the operator to interpolate narrowly scoped values. Exclude `.env`, Telegram sessions, certificates/private keys, broker profiles and logs from Git. Bootstrap does not print generated secrets into logs or CI output.

Encrypt Telegram StringSession at rest and load into collector memory. Persist independent bounded catch-up/checkpoint metadata; StringSession alone is not a complete missed-update recovery solution. Keep encryption keys separate from ciphertext and backups; document rotation/re-enrollment. Provider URLs are deployment allowlists, not dashboard text fields. Broker passwords stay solely in native MT5 credential handling; the backend receives account telemetry, never the broker login password.

Secure production startup rejects placeholder credentials, insecure cookies, invalid or missing hard limits, mode/account mismatch, zero/invalid keys, unapproved models, and unavailable compatible schema. Services can start into an observable NOT_READY/PAUSED state where external enrollment is missing; they cannot create exposure. Dev/test exceptions require explicit environment/mode isolation, never silent fallback.
