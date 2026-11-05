import test from 'node:test';
import assert from 'node:assert/strict';
import { DashboardReadCache, dashboardCacheKey, DASHBOARD_MAX_AGE_MS } from '../lib/product/dashboard-cache.ts';

const org = 'd5d2a37c-5538-4783-8f42-a285d8534b7a';
const other = '24e095e8-63a0-4ea7-a032-63ce65714974';
const path = `organizations/${org}/dashboard/resources/incidents`;
const next = `organizations/${other}/dashboard/resources/incidents`;

test('only read-only dashboard paths qualify, with normalized query keys', () => {
  assert.equal(dashboardCacheKey(`${path}?offset=0&limit=20`), `${path}?limit=20&offset=0`);
  for (const p of ['auth/me', `organizations/${org}/dashboard/evaluations`, `organizations/${org}/dashboard/workspace`, `organizations/${org}/incidents/${other}/approvals/${other}`, `organizations/${org}/voice/capabilities`]) assert.equal(dashboardCacheKey(p), null);
});

test('snapshots expire and in-flight identical reads are deduplicated', async () => {
  let now = 1;
  const cache = new DashboardReadCache(() => now);
  let resolve!: (value: {total: number}) => void;
  let calls = 0;
  const loader = () => { calls++; return new Promise<{total:number}>(done => { resolve = done; }); };
  const first = cache.load(path, loader);
  const second = cache.load(path, loader);
  assert.equal(calls, 1); resolve({total: 4});
  assert.deepEqual(await first, await second);
  assert.deepEqual(cache.get(path)?.data, {total: 4});
  now += DASHBOARD_MAX_AGE_MS;
  assert.equal(cache.get(path), undefined);
});

test('a tab unmount does not cancel the shared request or lose its snapshot', async () => {
  const cache = new DashboardReadCache();
  const consumer = new AbortController();
  let resolve!: (value: number) => void;
  const pending = cache.load(path, () => new Promise<number>(done => resolve = done), consumer.signal);
  consumer.abort(); resolve(4);
  await assert.rejects(pending, {name:'AbortError'});
  assert.equal(cache.get(path)?.data, 4);
});

test('committed mutations cannot be overwritten by a late older read', async () => {
  const cache = new DashboardReadCache();
  await cache.load(next, async () => ({total: 99}));
  let resolve!: (value: {total:number}) => void;
  const old = cache.load(path, () => new Promise<{total:number}>(done => resolve = done));
  cache.invalidate(org);
  await cache.load(path, async () => ({total: 5}));
  resolve({total: 4});
  await assert.rejects(old, {name:'AbortError'});
  assert.deepEqual(cache.get(path)?.data, {total:5});
  assert.deepEqual(cache.get(next)?.data, {total:99});
});

test('manual refresh bypasses Redis, while ordinary background refresh does not', async () => {
  const cache = new DashboardReadCache();
  const seen: boolean[] = [];
  const load = async (_signal: AbortSignal, force: boolean) => { seen.push(force); return 1; };
  await cache.load(path, load);
  cache.refresh(path);
  await cache.load(path, load);
  await cache.load(path, load);
  assert.deepEqual(seen, [false,true,false]);
});

test('identity/permission changes clear data, and denied reads need not trigger refetch loops', async () => {
  const published: string[] = [];
  const cache = new DashboardReadCache(Date.now, scope => published.push(scope));
  cache.setPrincipal('owner'); await cache.load(path, async () => 1);
  cache.setPrincipal('viewer'); assert.equal(cache.get(path), undefined);
  assert.deepEqual(published, ['*']);
  let invalidations = 0;
  cache.subscribe(() => invalidations++);
  await cache.load(path, async () => 2);
  cache.invalidate('*', false, false);
  assert.equal(invalidations, 0); assert.equal(cache.get(path), undefined);
});

test('failed reads are never cached, and the display cache has a bounded size', async () => {
  const cache = new DashboardReadCache();
  await assert.rejects(cache.load(path, async () => { throw Error('unavailable'); }));
  assert.equal(cache.get(path), undefined);
  for (let i=0;i<105;i++) await cache.load(`${path}?offset=${i}`, async () => i);
  assert.equal(cache.get(`${path}?offset=0`), undefined);
  assert.equal(cache.get(`${path}?offset=104`)?.data, 104);
});
