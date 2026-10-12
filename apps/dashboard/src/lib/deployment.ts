// Server transport configuration. Only Route Handlers and the deployment preflight import this.
type Environment = Record<string, string | undefined>;
export type Deployment = {
  remote: boolean;
  backendOrigin: string;
  environmentId?: string;
  publicOrigin?: string;
  proxyKey?: string;
  accessClientId?: string;
  accessClientSecret?: string;
};

export class RemoteAccessRequired extends Error {}

export function origin(value: string | undefined): string {
  if (!value) throw new Error('Deployment configuration unavailable');
  const url = new URL(value);
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password ||
    url.pathname !== '/' || url.search || url.hash)
    throw new Error('Deployment configuration unavailable');
  return url.origin;
}

export function deployment(env: Environment = process.env): Deployment {
  const backendOrigin = origin(env.API_INTERNAL_URL);
  const mode = env.DASHBOARD_ACCESS_MODE ?? 'local';
  if (mode === 'local') {
    if (env.VERCEL === '1') throw new Error('Remote access configuration required');
    return {remote: false, backendOrigin};
  }
  const stage = env.DASHBOARD_DEPLOYMENT_ENV;
  const environmentId = env.DASHBOARD_ENVIRONMENT_ID;
  const publicOrigin = origin(env.DASHBOARD_PUBLIC_URL);
  const backend = new URL(backendOrigin);
  const publicUrl = new URL(publicOrigin);
  const secrets = [env.DASHBOARD_PROXY_SECRET, env.CF_ACCESS_CLIENT_ID, env.CF_ACCESS_CLIENT_SECRET];
  if (mode !== 'cloudflare' || !['staging', 'production'].includes(stage ?? '') ||
    (env.VERCEL_ENV === 'preview' && stage !== 'staging') ||
    !environmentId || environmentId.length > 64 ||
    !new RegExp(`^${stage}-[a-z0-9_-]+$`).test(environmentId) ||
    backend.protocol !== 'https:' || publicUrl.protocol !== 'https:' ||
    [backend, publicUrl].some((url) => !url.hostname.includes('.') ||
      ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname) ||
      (url.port && url.port !== '443')) || backend.hostname === publicUrl.hostname ||
    !/^[A-Za-z0-9_-]{43,128}$/.test(env.DASHBOARD_PROXY_SECRET ?? '') ||
    secrets.some((secret) => !secret || !/^[A-Za-z0-9_.-]{16,256}$/.test(secret)))
    throw new Error('Deployment configuration unavailable');
  return {remote: true, backendOrigin, environmentId, publicOrigin,
    proxyKey: env.DASHBOARD_PROXY_SECRET!,
    accessClientId: env.CF_ACCESS_CLIENT_ID!,
    accessClientSecret: env.CF_ACCESS_CLIENT_SECRET!};
}

export function transportHeaders(request: Request, config: Deployment): Headers {
  const headers = new Headers({'Content-Type': 'application/json'});
  if (!config.remote) return headers;
  const assertion = request.headers.get('cf-access-jwt-assertion');
  if (new URL(request.url).origin !== config.publicOrigin || !assertion ||
    assertion.length > 16_384 || !/^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/.test(assertion))
    throw new RemoteAccessRequired('Remote access required');
  headers.set('X-TRD-User-Assertion', assertion);
  headers.set('X-TRD-Proxy-Key', config.proxyKey!);
  headers.set('X-TRD-Environment', config.environmentId!);
  headers.set('CF-Access-Client-Id', config.accessClientId!);
  headers.set('CF-Access-Client-Secret', config.accessClientSecret!);
  return headers;
}

export function verifyEnvironment(response: Response, config: Deployment): void {
  if (config.remote && response.headers.get('X-TRD-Environment') !== config.environmentId)
    throw new Error('Backend environment unavailable');
}
