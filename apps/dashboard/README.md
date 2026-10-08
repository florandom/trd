# Dashboard foundation

Phase 1 exposes read-only infrastructure readiness. Paper mode and disabled automation are fixed in the public contract. Authentication, settings, trading data and administrative controls belong to later phases; disabled navigation labels make that scope explicit.

Customer-facing copy, errors, metadata and accessible controls use Italian (`it-IT`). Astryx's built-in navigation, resize and loading labels are translated through its `InternationalizationProvider` with the local overrides in `src/lib/locale.ts`. Observation times use Italian formatting and `Europe/Rome`, including the time-zone abbreviation; the API contract retains UTC timestamps and its existing status identifiers. New dashboard features must follow the Italian-language guidance in `AGENTS.md`.

The Italian update was verified on 4 October 2026 with strict typechecking, lint, all eight existing frontend tests and the production container build. Browser checks covered the 1280px desktop layout, mobile navigation, status refresh, Italian accessible labels, document language and the localized not-found page with its working return link. The running local dashboard was updated to this build.

Astryx 0.6.4's `shell-side-nav` template was scaffolded with the real CLI and adapted after reading its generated `AGENTS.md`, layout guidance and component contracts. The AppShell/SideNav/Layout frame, content padding 6 and section gap 5 remain; the mixed operational table uses a 960px content budget and a 260px resizable sidebar. Below the theme's `md` breakpoint, AppShell swaps navigation to its mobile drawer. The prebuilt neutral theme runs in dark mode. All interior overrides use StyleX and semantic tokens.

Next 16 uses an explicit Webpack build/dev path with the verified community SWC StyleX compiler; its default plugin does not extract CSS through default Turbopack. The Webpack carrier is imported in the root layout. No remote fonts are fetched by Next during builds.

TypeScript 6.0.3 is pinned because the installed typescript-eslint version rejects the TypeScript 7 API. The typecheck command first generates Next's route types with `next typegen --webpack`, so it also works on a clean checkout before a build. Strict typechecking, lint, eight readiness/proxy tests and a production build passed. The built standalone server was also opened in a browser: dark styles, unavailable status, Refresh, and the 390px navigation drawer/anchor behavior were checked. These checks do not establish later trading-service or authentication acceptance.

The monorepo standalone entrypoint is `.next/standalone/apps/dashboard/server.js`. Production packaging must place `.next/static` at `.next/standalone/apps/dashboard/.next/static` (and `public` alongside the server if that directory is added later). Use the packaged server for deployed operation; `next start` prints a standalone-mode warning.

`API_INTERNAL_URL` is a server-only origin (default `http://127.0.0.1:8000`, Compose uses `http://api:8000`). A fixed same-origin `/api/status` route requests `/health/ready`, validates and whitelists the public DTO, and returns a generic error on invalid replies/timeouts. It follows no redirects, sends no user credentials, caches nothing and never returns the configured origin or upstream diagnostics. No `NEXT_PUBLIC_*` secret is used. Ready means API database/migration readiness only; it does not imply worker, Telegram, AI or MT5 availability.

The browser refreshes every 10 seconds, treats observations older than 30 seconds (or too far in the future) as stale, and clearly marks failed requests as unavailable even when an earlier observation exists. Observation time remains visible in the Italian time zone. Tests cover boundary validation, stale/future observations, status-code consistency, error redaction and redirect/cache behavior.

Use root workspace scripts or `pnpm --filter @trd/dashboard <dev|typecheck|lint|test|build|start>`. Containers can override the host binding with their command. External production exposure still requires verified MFA/Access and the later deployment security gate.

## Phase 3 operational dashboard

The existing shell-side-nav frame now wraps authenticated routes. Login uses the
Astryx login template; configuration sections adapt the settings template inside
the existing shell. All copy and accessibility labels remain Italian. Next server
layouts check the opaque cookie with the API. The allowlisted same-origin transport
forwards only TRD cookies, Origin and CSRF headers and never provider/database secrets.

ADMIN can confirm versioned retention, tighter risk and disabled-agent configuration
changes. VIEWER fields are read-only and the API rejects writes. Sessions expire on
idle/absolute limits; activity checks are bounded and readiness polling does not
keep a session alive. Operational data, registry, audit and heartbeat lists use real
database views; unavailable integrations show honest empty/inactive states.

Eleven frontend tests, strict types, lint and a production build pass. Browser
verification covers ADMIN save/audit/logout, VIEWER read-only access, stale notices
and 1280px/390px layouts in a disposable database. See [Phase 3 evidence](../../docs/PHASE_3_VALIDATION.md).
