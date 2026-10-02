# Threat model — Phase 0

Status: proposed design, 2 October 2026. Controls described here must be implemented and tested in later phases; this document is not a completed security audit. [Architecture](ARCHITECTURE.md) contains data-flow and trust-boundary diagrams; [environment matrix](ENVIRONMENT.md) defines service-specific secret access.

## Assets and trust assumptions

Protect broker account funds/positions, command authenticity, hard risk policy, admin authority, Telegram sessions, provider keys, personal signal data, audit/financial accuracy and recovery evidence. The highest-impact attack is an unauthorized or duplicated broker order. The most frequent operational hazard is a stale/uncertain view treated as safe.

Untrusted inputs: Telegram text/media/URLs/edits, source identity until enrolled, AI output/refusals/usage metadata, browser requests, Internet traffic, and unauthenticated or malformed EA traffic. Authenticated EA telemetry is still bounded/schema-validated. Treat the broker as execution authority with potential delay, partial fills, gaps and outages.

Trusted components: reviewed deployed code, runtime OS/service identities, database administrator/migrations, hard-config provisioning, risk signer and enrolled EA host. Compromise of the VPS admin or execution key can defeat local controls; one machine is not an isolation guarantee. Separating identities, credentials and DB privileges reduces the reach of lesser compromise. RDP and human MT5 trades are high-trust operator actions that can change account state outside the pipeline.

## Threat/control/test matrix

| Threat | Proposed mitigation and residual risk | Required verification |
| --- | --- | --- |
| Stolen dashboard credentials | Argon2id, bounded login attempts/shared throttles, expiring/revocable opaque sessions, external Access MFA, optional local TOTP; ADMIN/VIEWER backend RBAC | Brute-force, fixation, stolen/expired/revoked session, Viewer mutation and MFA tests |
| Malicious admin config | Typed bounds, immutable hard env, no secret/live mutation endpoint, confirmation/version concurrency, append-only audit; administrator can still pause or choose poor policy within bounds | Boundary/stale version/confirmation replay tests; invalid startup config |
| Leaked broker credentials | Broker password stays in MT5; restricted Windows user/data ACLs, no browser/backend field; broker account compromise remains external risk | Secret/log inspection; account tuple mismatch/demo-real rejection |
| Telegram session theft | AES-GCM encrypted session at rest with separate key, restricted collector identity/DB grants, no committed session or log serialization; collector memory/host compromise remains risk | Ciphertext tamper, key mismatch/rotation, revoked session, reconnect/backfill |
| API key leakage | Service-specific env, redacted structured logs/DTOs/audit, no NEXT_PUBLIC credential, minimal provider inputs, dependency scan and egress allowlist | Bundle/health/error/audit leak checks and secret scan |
| Prompt injection | Telegram is data, fixed versioned system prompts, structured schemas, no tools or fetching, no policy/secret/command credentials; output is advisory | Adversarial messages requesting policy override, secret access, URL/tool calls and fabricated fills |
| Malicious source/hallucinated signal | Enrolled source/instrument/profile, strict parser/proposal schema, timestamp/dedup, confidence/required critic, deterministic risk authority and EA rechecks | Wrong symbol/side/SL/TP, malformed JSON, out-of-range values, unapproved route |
| Duplicate/edit/reply race | Telegram identity/message-version constraints, execution fingerprints, invalidated unsent approvals, explicit target lineage; similar independent text is not blindly treated as same message | Duplicate event, content edit before/after approval/fill, cancellation race |
| Replayed/tampered command | HTTPS, exact-byte HMAC, fixed routes, signed expiry/environment/account/generation, durable sequences/replay claims, local command hash/journal | Published HMAC vectors plus Python/MQL fixtures; tamper/reorder/rollback/key rotation |
| Forged/replayed EA event | Direction-specific key, allowlisted bridge/account, unique event ID + payload hash, broker deal dedup, server commit before ACK; compromised EA can forge telemetry | Same-ID-different-content fault, repeated fill accounting, unauthorized account events |
| Duplicate broker execution after lost ACK/crash | Immutable command, flushed SEND_INTENT, one active EA, retained reservations and OUTCOME_UNKNOWN; broker lacks established idempotency key | Kill/restart around send, lost ACK/fill, delayed history, dual EA; no blind resubmit |
| Manual trade/account ownership conflict | Risk observes all-account exposure; dedicated automation account; lifetime position identity; mixed netting ownership stops automation | Manual position/SL modification, foreign magic, netting/FIFO/hedging fixtures |
| Network/MT5/provider outage or stale heartbeat | Bounded retries, snapshot freshness/reconciliation, no exposure on required dependency failure, broker-held protective stops | Timeout, missing heartbeat, partial snapshot, Redis/DB loss, provider failures |
| Daily-loss overshoot/risk races | Decimal account-currency math, supported profiles, equity/cash-flow baseline, atomic account risk+slot reservations, drawdown latch | Concurrent proposals, deposits/swap/fees/unrealized loss, threshold boundaries |
| Spread/slippage/gap/broker failure | Approved price/deviation band, EA preflight, conservative buffers, attached SL/TP requirement; gaps can exceed expected loss | Stale/change quote, rejected stops, freeze constraints, partial fills; demo broker evidence |
| AI spending exhaustion | Atomic worst-case token/cost reservations, bounded attempts/fallback, unknown-cost retained reservation; no analysis-policy bypass | Parallel budget contention, missing usage, timeout, pricing missing, required critic exhausted |
| SQL injection | SQLAlchemy bound expressions/parameters; no interpolated user SQL; restricted roles | Injection payloads, grants review, database constraints |
| XSS | Escaped untrusted messages, no unsafe HTML/raw markdown embeds, CSP/security headers, no arbitrary links/media fetched | Script/HTML/URL payload render tests, browser CSP behavior |
| CSRF/session abuse | SameSite/HttpOnly/Secure cookies, CSRF token and exact Origin on mutations/login/logout, rotation/revocation; no GET mutations | Missing/wrong token/origin, cross-origin requests, fixation and logout |
| SSRF/command injection | Fixed provider/Telegram/bridge origins, no signal URL fetch/tools, no dashboard shell/script fields, pathlib/platform configuration only | Loopback/metadata URL inputs, shell characters, unsafe paths/action enums |
| Dependency compromise | Exact locks/image digests, reviewed install scripts/native binary provenance, security tooling/SBOM, stable checksum-pinned service wrapper | Audit/secret scan, Linux/Windows builds, documented vulnerability triage |
| Secret commit/insecure logs | Ignore rules, secret scanner, redaction-safe exception mapping, no .env/session/MT5 profiles in artifacts | Fresh clone/bundle/log scan; injected secret canaries |
| Container/host escape | Non-root application containers, restricted volumes/capabilities, no Docker socket to app, patched host, least-privilege Windows services | Compose permissions review; service ACL/firewall checks; residual same-host admin trust |
| RDP brute-force/session termination | No public3389, explicit Tunnel/Access policies+MFA, NLA, limited trading user, updates, session timeout audit and recovery console | External port scan, Access denial, RDP disconnect/sign-out/lock/reboot tests |
| Disk full/retention destroys evidence | Rotated logs, disk alerts, protected journal/outbox/replay/open-position evidence, bounded resumable cleanup | Low disk, interrupted cleanup, open/unknown-trade retention test |
| Database loss/restore rollback | Encrypted off-host backups, restore drills, execution paused on restore, broker reconciliation and controlled bridge re-enrollment | Clean restore/replay counter rollback, open trade/reservation rebuild; RPO/RTO proof |
| Audit tampering | Runtime append-only permissions, immutable versions, optional hash chain and off-host export; DBA can still rewrite local database | UPDATE/DELETE denied for runtime, export/restore integrity tests |
| Notification spam/outage | Incident keys/cooldowns/severity, outbox retries, sanitized messages; health is not dependent on successful alert delivery | Repeated failure/recovery, deduplication and secret-redaction fixtures |

## Fail-closed behavior

- Any unknown account mode, instrument valuation, conversion, protective stop, policy version, required AI result or current exposure blocks new risk.
- DB outage blocks fresh command issuance, delivery and replay/event acknowledgement. The EA does not replay a cached unsent command on reconnect or proceed after a locally detected contact/readiness failure. A failure immediately after issuing an authenticated short-lived approval has an unavoidable in-flight race; reconcile the broker outcome rather than claiming instantaneous revocation. Redis outage affects only optional acceleration.
- Heartbeat freshness requires complete account/position/market state; a connected process alone cannot authorize an order.
- Unknown broker result retains risk and slot reservations and stops account execution until reconciliation. Manual override creates an audited resolution, not permission to blindly resend.
- Raw data cleanup preserves compact decision/risk/fill evidence and the anchors/journal/replay state required for open, pending or uncertain orders.
- Disabling automation prevents new exposure. Explicitly confirmed managed close/cancel remains possible under a separate deterministic reduction policy with account/ownership checks. Loss of contact cannot promise remote liquidation.
- No real-money enablement by seed, model output, browser switch, simulator identity or configuration fallback.

## Production hardening gates

Phase 9: dependency/secret scans, RBAC/session/CSRF/replay/DTO leak tests, CSP/XSS/API validation, database grants, redaction review, egress and container review. Phase 10: service identities/ACLs, backup restore, firewall/Access/RDP, native/WSL supervision and pre-login reboot tests. Phase 11: demo broker fills/stops/close/partial capability, uncertain-outcome recovery and manually changed exposure. No production security claim before evidence is recorded.

A fully unattended GUI reboot policy and off-host backup destination are deployment decisions, not Phase 1 blockers. Optional Autologon increases credential exposure and must be explicitly accepted if selected. Never solicit secret values in chat. See [Windows evidence](research/WINDOWS.md) and [MT5 evidence](research/MT5.md).
