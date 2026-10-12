import assert from 'node:assert/strict';
import {test} from 'node:test';
import {deployment} from '../src/lib/deployment';
import {proxy} from '../src/lib/backend-proxy';

const env = {
  VERCEL: '1', VERCEL_ENV: 'preview', DASHBOARD_ACCESS_MODE: 'cloudflare',
  DASHBOARD_DEPLOYMENT_ENV: 'staging', DASHBOARD_ENVIRONMENT_ID: 'staging-paper',
  DASHBOARD_PUBLIC_URL: 'https://dashboard-staging.example.test',
  API_INTERNAL_URL: 'https://api-staging.example.test',
  DASHBOARD_PROXY_SECRET: 'p'.repeat(43), CF_ACCESS_CLIENT_ID: 'fixture-client-id.access',
  CF_ACCESS_CLIENT_SECRET: 'c'.repeat(64),
};
const publicUrl = env.DASHBOARD_PUBLIC_URL;

test('Vercel previews cannot select production or fall back to unprotected local access', () => {
  assert.ok(deployment(env).remote);
  for (const change of [
    {DASHBOARD_ACCESS_MODE: 'local'}, {DASHBOARD_DEPLOYMENT_ENV: 'production'},
    {DASHBOARD_ENVIRONMENT_ID: 'production-paper'}, {API_INTERNAL_URL: 'http://api:8000'},
    {API_INTERNAL_URL: 'https://user:password@api.example.test'},
    {CF_ACCESS_CLIENT_SECRET: ''}, {DASHBOARD_PUBLIC_URL: 'https://localhost'},
  ]) assert.throws(() => deployment({...env, ...change}));
});

test('direct preview URL, forged forwarding headers and missing user assertion never reach backend', async () => {
  let called = false;
  const fetcher: typeof fetch = async () => {called = true; throw new Error('unreachable');};
  for (const request of [
    new Request(publicUrl + '/api/backend/auth/csrf'),
    new Request('https://direct.vercel.app/api/backend/auth/csrf', {headers: {'cf-access-jwt-assertion': 'a.b.c'}}),
    new Request(publicUrl + '/api/backend/auth/csrf', {headers: {'X-TRD-User-Assertion': 'a.b.c'}}),
  ]) assert.equal((await proxy(request, 'auth/csrf', fetcher, env)).status, 401);
  assert.equal(called, false);
});

test('server credentials and original human assertion travel upstream only with an environment fence', async () => {
  const request = new Request(publicUrl + '/api/backend/auth/me?target=https://attacker.test', {
    headers: {'cf-access-jwt-assertion': 'a.b.c', 'x-trd-proxy-key': 'forged',
      cookie: `foreign=private; trd_session=${'s'.repeat(43)}`},
  });
  const fetcher: typeof fetch = async (url, init) => {
    assert.equal(String(url), env.API_INTERNAL_URL + '/auth/me?');
    const headers = new Headers(init?.headers);
    assert.equal(headers.get('x-trd-user-assertion'), 'a.b.c');
    assert.equal(headers.get('x-trd-proxy-key'), env.DASHBOARD_PROXY_SECRET);
    assert.equal(headers.get('cf-access-client-secret'), env.CF_ACCESS_CLIENT_SECRET);
    assert.equal(headers.get('x-trd-environment'), env.DASHBOARD_ENVIRONMENT_ID);
    assert.equal(headers.get('cookie'), `trd_session=${'s'.repeat(43)}`);
    assert.equal(init?.redirect, 'error');
    assert.equal(init?.cache, 'no-store');
    return Response.json({role: 'VIEWER'}, {headers: {'X-TRD-Environment': 'staging-paper'}});
  };
  const result = await proxy(request, 'auth/me', fetcher, env);
  assert.equal(result.status, 200);
  assert.equal(result.headers.get('cf-access-client-secret'), null);
  assert.equal(result.headers.get('x-trd-user-assertion'), null);
  assert.deepEqual(await result.json(), {role: 'VIEWER'});
});

test('missing/mismatched environment and Access HTML failures are safely rejected', async () => {
  const request = new Request(publicUrl + '/api/backend/auth/me', {headers: {'cf-access-jwt-assertion': 'a.b.c'}});
  for (const response of [
    Response.json({private: 'private-backend-data'}),
    Response.json({private: 'private-backend-data'}, {headers: {'X-TRD-Environment': 'production-paper'}}),
    new Response('<html>Access challenge</html>', {headers: {'X-TRD-Environment': 'staging-paper'}}),
  ]) {
    const result = await proxy(request, 'auth/me', async () => response, env);
    assert.equal(result.status, 503);
    assert.deepEqual(await result.json(), {detail: 'SERVICE_UNAVAILABLE'});
  }
});

test('dashboard cannot proxy broker commands, arbitrary routes or methods', async () => {
  for (const path of ['trading/open', 'bridge/commands', '../auth/me', 'https://attacker.test']) {
    const result = await proxy(new Request(publicUrl), path, async () => {throw new Error('unreachable');}, env);
    assert.equal(result.status, 404);
  }
});
