# Phase 4 Telegram collection contract

Implemented 9 October 2026. The collector reads only dashboard-authorized sources.
The local installation has no enrolled real account and remains disabled. This
contract describes the adapter and its limits, not real-network acceptance.

## Account and source boundaries

ADMIN creates at most 32 sources per environment through the existing two-minute,
single-use, session/payload/version-bound confirmation workflow. Public `@username`
and `https://t.me/username` references canonicalize to lowercase; explicit negative
peer IDs support joined private groups. Names and enabled state can be revised;
the reference is immutable. VIEWER can consult sources and message previews.
API projections omit peer access hashes, account credentials and session material.

The operator supplies API ID/hash and runs `pnpm telegram:enroll` in an interactive
local terminal. Phone, code and two-step password are entered without echo. A human
account must match the enrolled identity; bots and revoked/mismatched sessions fail.
Enrollment uses only login operations; the collector never joins groups, sends
messages, downloads media, follows text URLs or contacts an arbitrary browser URL.
Private resolution pages at most 500 dialog metadata entries; an inaccessible or
unlisted source is reported unavailable. Telegram membership is managed separately.

## Encrypted session and scoped deployment

Telethon 1.45.0 uses a StringSession in memory with update reception disabled. Its
stored session is an AES-256-GCM envelope with a fresh nonce and authenticated schema,
environment, account, collector identity and key ID. Secret values stay out of logs.
Writes use a private temporary file, fsync and atomic replacement. The reader rejects
symlinks, oversized envelopes, unexpected metadata, invalid authentication and broad
POSIX file permissions. The dedicated collector volume is writable; its container
root filesystem is read-only. The operator key is separate from ciphertext.

Verified sessions persist changes to their Telegram DC/auth state through the same
encrypted atomic writer while the collector retains ownership. Plaintext session
state never becomes a transport cache on disk.

Stop the collector before `--replace-session` or `--rotate-key`. Rotation loads the
old key/key ID through private terminal prompts and writes under the configured new
key. Backup protection and Windows ACLs require operator preparation and target-host
verification. Commands and account requirements are in the [Italian team guide](team/GUIDA_PREPARAZIONE.md).

## Bounded recovery and durable fencing

Defaults: 30-second polling, 24-hour history/revision window, 100 records per history
request, 20-second RPC timeouts, 15-minute preliminary analysis freshness. Each cycle
reads oldest unseen history, a latest-window overlap, then a rotating bounded batch
of recently known message IDs. An old history cursor restarts by date at the window
boundary. Overlap/edit/delete checks cannot advance the sequential history cursor.
Attachments are represented by metadata; text/captions/reply identity are normalized
with UTC-aware dates and strict bounds.

A PostgreSQL lease permits one active owner for the enrolled account across environment
labels in the same database. Generation, expiry, account, environment and source
version fence every observation, cursor and ingestion write. Network calls hold no
database transaction. Ownership is checked before network work; lost ownership stops
further work. Direct runtime INSERT on message anchors/versions is revoked. Independent
databases do not coordinate account ownership and must not collect the same account.

Flood waits persist an account-level retry deadline and survive process restart.
Disconnections use bounded exponential backoff; inaccessible sources do not block
other sources. Revoked/mismatched sessions stop network retries until operator repair
and restart. Heartbeats report degraded when collection is incomplete or failed.
Source success observations older than 120 seconds display as unverified. Operational
pages have explicit refresh and stale-data warnings; a loaded snapshot does not
automatically become fresh. An outage outside the window records a persistent gap;
operator assessment is required. Missed-and-deleted events and old revisions cannot
be guaranteed recoverable. This is bounded reconciliation rather than instant streaming.

## Atomic evidence and later analysis

Message anchors deduplicate source/message identity. Semantic revisions deduplicate
event payloads, reject conflicting same-time edits, preserve immutable history, and
retain deletion tombstones that cannot be resurrected by stale deliveries. Message,
checkpoint, metadata-only audit/outbox and a future analysis handoff commit atomically.
Old initial messages create expired observations without a fresh-opening analysis job.
Revisions/deletions are review-only; associated pending/running jobs are invalidated
before the new handoff. Unsent commands and unexecuted signals are invalidated, while
delivered commands and reservation evidence remain for future reconciliation.

These handoff jobs are stored but no parser, provider request, risk evaluation or broker
execution runs in Phase 4. Source disablement prevents new collection and invalidates
unsent proposals. A message edit never authorizes another opening trade. Later workers
must revalidate source status/version, message freshness and all financial gates.
The dashboard shows the latest event/version with a 240-character escaped preview,
not a full history viewer. Retention preserves identities and necessary financial evidence.

## Verification and references

[Phase 4 evidence](PHASE_4_VALIDATION.md) separates automatic, browser and local-container
checks from the pending real Telegram, Windows and demo-broker gates. Official references:
[Telegram application credentials](https://core.telegram.org/api/obtaining_api_id),
[Telethon session model](https://docs.telethon.dev/en/stable/concepts/sessions.html),
[Telethon client API](https://docs.telethon.dev/en/stable/modules/client.html),
[cryptography AESGCM](https://cryptography.io/en/latest/hazmat/primitives/aead/).
