import {parseReadiness} from './readiness';
import {type Deployment, verifyEnvironment} from './deployment';

const PROXY_ERROR = {error: 'status_unavailable'} as const;
const MAX_HEALTH_BODY_CHARACTERS = 4_096;

/** Configured server origin only: never derived from a browser URL or parameter. */
export function readinessEndpoint(internalOrigin: string): URL {
  const origin = new URL(internalOrigin);
  if (
    !['http:', 'https:'].includes(origin.protocol) || origin.username || origin.password ||
    origin.search || origin.hash || origin.pathname !== '/'
  ) throw new Error('Invalid API_INTERNAL_URL');
  return new URL('/health/ready', origin);
}

export async function proxyReadiness(
  internalOrigin: string,
  fetcher: typeof fetch = fetch,
  transport?: {headers: Headers; config: Deployment},
): Promise<Response> {
  const headers = {'Cache-Control': 'no-store'};
  try {
    const upstream = await fetcher(readinessEndpoint(internalOrigin), {
      cache: 'no-store',
      redirect: 'error',
      signal: AbortSignal.timeout(2_000),
      headers: transport?.headers ?? {Accept: 'application/json'},
    });
    if (transport) verifyEnvironment(upstream, transport.config);
    if (upstream.status !== 200 && upstream.status !== 503) {
      return Response.json(PROXY_ERROR, {status: 503, headers});
    }
    const body = await upstream.text();
    if (body.length > MAX_HEALTH_BODY_CHARACTERS) {
      return Response.json(PROXY_ERROR, {status: 503, headers});
    }
    const data = parseReadiness(JSON.parse(body));
    if (!data || (data.status === 'ready') !== (upstream.status === 200)) {
      return Response.json(PROXY_ERROR, {status: 503, headers});
    }
    return Response.json(data, {status: upstream.status, headers});
  } catch {
    // No exception text, origin, credentials or internal diagnostics leave the server.
    return Response.json(PROXY_ERROR, {status: 503, headers});
  }
}
