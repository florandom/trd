import assert from 'node:assert/strict';
import {test} from 'node:test';
import {getConnectionState, parseReadiness, STATUS_STALE_AFTER_MS} from '../src/lib/readiness';
import {proxyReadiness, readinessEndpoint} from '../src/lib/readiness-proxy';

const now = Date.parse('2026-10-02T12:00:00Z');
const valid = {
  status: 'ready', service: 'api', phase: 1, mode: 'paper',
  automation_enabled: false, checked_at: new Date(now).toISOString(),
} as const;

test('readiness boundary returns only public, paper-disabled fields', () => {
  assert.deepEqual(parseReadiness({...valid, secret: 'must not reach browser', database_url: 'private'}), valid);
});

test('unsupported safety state or malformed response fails closed', () => {
  for (const value of [
    null, {}, {...valid, mode: 'live'}, {...valid, automation_enabled: true},
    {...valid, phase: 2}, {...valid, status: 'healthy'},
    {...valid, checked_at: 'yesterday'}, {...valid, checked_at: '2026-10-02T14:00:00+02:00'},
  ]) assert.equal(parseReadiness(value), null);
});

test('stale/future observations and transport failures never display ready', () => {
  const data = parseReadiness(valid);
  assert.ok(data);
  assert.equal(getConnectionState(data, false, now), 'ready');
  assert.equal(getConnectionState(data, false, now + STATUS_STALE_AFTER_MS + 1), 'stale');
  assert.equal(getConnectionState(data, false, now - 5_001), 'stale');
  assert.equal(getConnectionState(data, true, now), 'offline');
  assert.equal(getConnectionState(null, false, now), 'loading');
});

test('not_ready is a valid observed condition, distinct from unavailable', () => {
  const data = parseReadiness({...valid, status: 'not_ready'});
  assert.ok(data);
  assert.equal(getConnectionState(data, false, now), 'not_ready');
});

test('proxy fixes the upstream path, disables caching, and refuses redirects', async () => {
  const fetcher: typeof fetch = async (url, init) => {
    assert.equal(String(url), 'http://api:8000/health/ready');
    assert.equal(init?.cache, 'no-store');
    assert.equal(init?.redirect, 'error');
    assert.ok(init?.signal);
    return Response.json({...valid, internal_error: 'private'}, {status: 200});
  };
  const response = await proxyReadiness('http://api:8000', fetcher);
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('cache-control'), 'no-store');
  assert.deepEqual(await response.json(), valid);
});

test('proxy preserves safe HTTP 503 not_ready observation', async () => {
  const unavailable = {...valid, status: 'not_ready'};
  const response = await proxyReadiness('http://api:8000', async () => Response.json(unavailable, {status: 503}));
  assert.equal(response.status, 503);
  assert.deepEqual(await response.json(), unavailable);
});

test('upstream errors, safety mismatch, malformed JSON and code mismatch are redacted', async () => {
  const upstream = [
    new Response('database password private', {status: 500}),
    Response.json({...valid, automation_enabled: true}),
    new Response('not json'),
    Response.json(valid, {status: 503}),
    new Response('x'.repeat(8_192)),
  ];
  for (const result of upstream) {
    const response = await proxyReadiness('http://api:8000', async () => result);
    assert.equal(response.status, 503);
    assert.deepEqual(await response.json(), {error: 'status_unavailable'});
  }
  const failure = await proxyReadiness('http://api:8000', async () => {throw new Error('private upstream origin and credentials');});
  assert.deepEqual(await failure.json(), {error: 'status_unavailable'});
});

test('server origin must not contain credentials, paths, query parameters or unsafe protocols', () => {
  for (const origin of ['file:///secret', 'http://user:secret@api:8000', 'http://api:8000/path', 'http://api:8000?secret=value', 'http://api:8000/#fragment']) {
    assert.throws(() => readinessEndpoint(origin));
  }
});
