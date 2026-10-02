# Phase 0 validation record

Date: 2 October 2026, Europe/Rome. Scope: research/design/documents and tiny disposable compatibility spikes. Application acceptance has not started.

## Evidence

| Check | Result | Limit |
| --- | --- | --- |
| Request and environment inspection | PASS: complete attached specification read; empty workspace and no applicable ancestor AGENTS.md found | No existing application to exercise |
| Local runtime inventory | PASS: macOS arm64, Node24.20/pnpm11.25, Python3.9.13, Git2.35.1 recorded | Docker not found; Python unsuitable for selected backend |
| Astryx public registry | PASS: core/CLI0.6.4, React>=19, StyleX^0.19, CLI Node>=22.13 | Dated package observation |
| Actual Astryx CLI | PASS: help/search/build/docs/templates and relevant component contracts inspected | No invented dashboard component API; no workspace init/scaffold |
| Next/React compatibility spike | PASS: Next16.3.8, React19.3, Astryx/theme-neutral0.6.4, TS production compile/prerender with default Turbopack | Tiny temporary page; not completed dashboard |
| Authored StyleX spike | PASS:0.19.0 SWC plugin with Webpack, xstyle emitted CSS and prerender markup | Third-party plugin; browser layout/interaction and custom Turbopack untested |
| Python dependency research | PASS: official docs/public registry constraints and representative cross-platform wheels inspected | No full dependency resolve/install/import/runtime test |
| Windows constraints | PASS: official WSL/nested virtualization/Desktop support, services and GUI-session documentation reviewed | No actual VPS/service/reboot test |
| MT5 capabilities | PASS: official WebRequest/crypto/trade-event/history/account behavior researched | No MQL compile/TLS/broker demo; HMAC interop still must be tested |
| Architecture peer review | PASS after revisions: signer/telemetry privileges and fresh risk evaluation clarified | Design review only; grants/code do not exist yet |
| Documentation integrity | PASS:11 Markdown files,43 local file links, balanced fences, whitespace and document-only inventory;4 Mermaid diagram sources reviewed | Diagrams not rendered; does not certify runtime or security controls |
| Git milestone | Git initialized on main for the requested documentation milestone; docs staged/checked and committed at phase close | No application scaffold, remote or deployment |

The temporary compatibility test is explicitly permitted by the user's Phase 0 request. Its installed dependencies/application files are outside this workspace; only its evidence document is retained here. Security/dependency scanning of the future production lockfiles remains Phase 1/9 work. Installing packages with scripts disabled during research is not a production supply-chain guarantee.

## Architecture review resolutions

1. A normal API capable of writing forged equity/positions could undermine percentage caps even without a signing key. Isolate authenticated EA ingress, replay checks, dynamic response signing and authoritative projections in the risk/bridge process/DB role.
2. A fresh snapshot can still invalidate an old approval. Before delivery rerun all applicable risk gates on latest equity/drawdown/portfolio/config, counting the command's existing reservation once.
3. External dashboard access requires Access MFA or implemented equivalent; absence of Access means local/VPN-only initially.
4. WSL systemd/container restart policies do not prove Windows pre-login recovery. Windows must supervise the distro owner and sustained lifetime; prove it on the target host.
5. A submitted broker request is not a fill, and a lost acknowledgement is not rejection. Preserve unknown state/reservations and do not claim exactly-once execution.
6. Published Astryx components compile without custom StyleX tooling; authored overrides need the explicitly tested compiler/bundler path. Document the discrepancy in the linked official example.

## Phase exit

Deliverables: architecture/repo proposal, data-flow and trust diagrams, threat model, full env matrix, ten proposed ADRs, four evidence notes, approval gate and validation record. No application scaffold or production code. Only approval to start Phase 1 remains; later native Windows/broker acceptance prerequisites are openly tracked.
