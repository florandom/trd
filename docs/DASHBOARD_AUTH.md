# Dashboard and authentication contract through Phase 4

Phase 4 retains the Phase 3 authentication boundary and adds `source` confirmation
changes. Source creation uses expected version zero; existing sources use their
current positive version. Target identity is a UUID. The server validates and
canonicalizes source references and restricts edits to name/enabled state. Source
cap, uniqueness, session, role, expiry, replay and concurrency checks run in PostgreSQL.
Only ADMIN may confirm or apply these changes. The authenticated `telegram-messages`
collection exposes the latest event and escaped 240-character preview; credentials,
account sessions and peer access hashes remain unavailable to browser clients.
See [the Telegram contract](TELEGRAM.md) and [Phase 4 evidence](PHASE_4_VALIDATION.md).

## Access and sessions

The Italian dashboard now requires a local ADMIN or VIEWER account. The existing
bootstrap administrator is preserved. Its credentials remain in the private ignored
operator `.env` under `ADMIN_BOOTSTRAP_EMAIL` and `ADMIN_BOOTSTRAP_PASSWORD`; they
are never printed by setup. `pnpm user:create` creates another user interactively
with the migration credential, validates a password of at least 16 characters and
records the role in the audit log. It refuses to overwrite an existing identity.
There is no browser user-provisioning, password-reset or privilege-escalation route.

Passwords use Argon2id with 64 MiB memory, three iterations and one lane. At most
two password verifications run concurrently in each API process; saturation returns
a bounded retry response before allocating another expensive hash. Login
verifies an equivalent dummy hash for unknown users and returns one generic failure
for an unknown, inactive or incorrect account. The API role can look up a single
credential through a dedicated function; neither a view nor a browser response
contains password hashes. Other runtime roles cannot call this function.

Sessions use independently generated 256-bit opaque tokens. PostgreSQL stores only
their SHA-256 hashes. Cookies are host-only, HttpOnly and SameSite=Lax; Secure is
mandatory for production. The local HTTP deployment explicitly sets Secure=false.
An eight-hour absolute lifetime and a 30-minute idle lifetime are the defaults,
with bounded shorter overrides. Revoked, expired or inactive-user sessions fail
closed. Login rotates a pre-existing session; logout revokes its database record.
The dashboard clears its authenticated navigation cache on exit and responds to
session-expiry errors. Human activity refreshes session metadata at most once a
minute; the background readiness poll does not extend the idle lifetime.

A five-minute single-use pre-login challenge protects login. Login, logout and every
configuration mutation require an Origin equal to the configured `APP_URL`, plus
a CSRF token derived from the corresponding opaque cookie. Session and challenge
tokens are independently generated; CSRF tokens are never accepted as cookies.
The API exposes no permissive CORS policy. Authorization uses the database's current
active user/role, not a browser claim. VIEWER has read access only.

Shared PostgreSQL throttle reservations occur before password verification. Each
account permits five attempts per five-minute window, and each observed peer permits
30 login attempts and 60 challenge requests. Retry-After is bounded to 300 seconds.
Concurrent service instances share the same counters. Forwarded IP headers are not
trusted. Behind the current Next proxy, the peer throttle conservatively applies to
the shared proxy hop; per-user forwarded-IP attribution requires a reviewed proxy
trust arrangement before external deployment.

Input validation does not echo submitted values. Next and FastAPI bound mutation
bodies to 16 KiB. The Next transport allows only dashboard routes, forwards only
TRD cookies, Origin and CSRF headers, refuses redirects and disables caching.
Session cookies, credentials, provider keys and database URLs stay out of browser
storage and ordinary service logs.

These choices follow [OWASP session management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)
and [CSRF guidance](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html).
The application continues to reject remote production origins. Local MFA and Access
assertion verification are not implemented; enabling the MFA requirement fails
startup rather than implying protection that does not exist.

## Confirmed changes and authority

ADMIN first requests a two-minute confirmation for an exact normalized change:
kind, target, expected version and value. Its opaque token is stored only as a hash,
bound to environment, session and full JSON payload. The dashboard shows the old
and proposed values, simulation mode, version and expiry. Applying the change
rechecks the current administrator/session, locks the confirmation and configuration,
compares the full payload and expected version, and atomically publishes an immutable
version, head pointer, audit event and consumed confirmation. Replays, substitution,
cross-session use and stale versions fail. A failed transaction consumes nothing.

The confirmed HTTP routes expose these capabilities only:

- Retention periods: integers from 1 to 365 days, preserving evidence protection.
- Risk: tighten the current reviewed policy, with mandatory SL and TP. No expansion,
  hard-bound or trading-mode editor is exposed. Pending commands, held/uncertain
  reservations or open positions reject the change until the risk gateway exists.
  An accepted change pauses enrolled accounts and advances their safety epoch.
- Agents in Phase 3: prepare immutable configurations with enabled=false, compatible enabled
  mock models, at most two unique fallback models, 1–120 second timeout, at most
  4096 output tokens, and zero request cost. Prompt manifests stay operator-owned.

Risk fingerprints preserve the domain contract's canonical representation. Model
manifests and prices remain operator-reviewed and immutable; the registry UI is
read-only. Only the offline mock is seeded. Phase 5 now permits confirmed activation
of the five implemented offline agents with reviewed prompt version 2. Position review
and external models remain unavailable. The API has no financial-record write grants or broker keys. Its
explicit unavailable-trading handler never creates a command or approval.

## Operational pages and lifecycle

Overview, positions, signals/detail, message analysis, sources, agents, model registry, risk, AI costs,
settings, audit and status use stored, redacted projections. Operational lists are
paged in bounded batches. Money is represented by decimal strings; percentage inputs
move the decimal point without floating-point arithmetic. Dates use it-IT and
Europe/Rome. Empty, loading, unavailable and stale states are visible. Worker
heartbeats describe process presence and age, not provider, Telegram or broker
readiness. Account financial metrics remain absent until an account is connected.

Revision `0003_dashboard` adds three authentication/confirmation tables, two expiry
indexes, redacted operational views and narrowly granted definer functions. There
are 37 mapped tables in total. Authentication cleanup is maintenance-only, bounded
per table and resumable; it removes expired challenges, old counters/confirmations
and expired/revoked sessions after a one-day grace period. It never removes active
sessions or configuration/audit history. `pnpm retention:run` runs one batch for both
raw evidence and authentication records; automatic scheduling remains later work. The raw-log retention setting is versioned
preparation; log files currently use size/count rotation rather than age-based pruning.
