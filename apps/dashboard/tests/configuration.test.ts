import {test} from 'node:test';
import assert from 'node:assert/strict';
import {shiftDecimal} from '../src/lib/configuration';
import {
  allowedRoute,
  backendOrigin,
  boundedBody,
} from '../src/lib/backend-proxy';

test('risk percentages preserve exact decimal digits', () => {
  assert.equal(shiftDecimal('0.005', 2), '0.5');
  assert.equal(shiftDecimal('0.123456789', -2), '0.00123456789');
  assert.equal(shiftDecimal('12.5', -2), '0.125');
  assert.equal(shiftDecimal('0005.00', 0), '5');
  for (const input of ['NaN', 'Infinity', '1e5', '-2', '1,2', ''])
    assert.throws(() => shiftDecimal(input, -2));
});

test('dashboard proxy only accepts known paths and configured origins', () => {
  assert.equal(allowedRoute('auth/me', 'GET'), true);
  assert.equal(allowedRoute('config/apply', 'POST'), true);
  for (const route of [
    '../bridge/commands',
    'trading/enable',
    'ops/users',
    'health/ready',
    'auth/me/extra',
    'https://evil.test',
  ])
    assert.equal(allowedRoute(route, 'GET'), false);
  assert.equal(allowedRoute('ops/settings', 'POST'), false);
  assert.equal(backendOrigin('http://127.0.0.1:8000'), 'http://127.0.0.1:8000');
  for (const origin of [
    'file:///private',
    'http://user:password@localhost',
    'https://example.test/path',
  ])
    assert.throws(() => backendOrigin(origin));
});

test('streamed requests are bounded before forwarding', async () => {
  assert.equal(
    await boundedBody(
      new Request('http://localhost', {method: 'POST', body: '{}'})
    ),
    '{}'
  );
  await assert.rejects(
    boundedBody(
      new Request('http://localhost', {
        method: 'POST',
        body: 'x'.repeat(16_385),
      })
    )
  );
});
