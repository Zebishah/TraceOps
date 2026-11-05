# Dashboard caching and invalidation

Dashboard collection pages and command-center counts restore recently fetched data from session memory immediately when revisited. They revalidate in the background, on window focus, and every 15 seconds while visible. The existing refresh buttons explicitly bypass the Redis response cache using `X-OpsPilot-Refresh: 1`. Ordinary HTTP `no-store`/`no-cache` headers continue to prevent browser/proxy caching without disabling Redis.

## Cached reads

Redis caches successful responses for 30 seconds on these authorized GET routes:

- `/organizations/{organization_id}/dashboard/overview`
- `/organizations/{organization_id}/dashboard/resources/{resource}`
- `/organizations/{organization_id}/dashboard/resources/{resource}/{resource_id}`
- `/organizations/{organization_id}/dashboard/incidents/{incident_id}/latest`

Every request resolves the current user and organization membership before reading Redis. Keys include organization, user, role, operation, all filters, pagination, and identifiers. Query values are hashed rather than exposed directly in Redis keys. Cached values are validated against the route's response type; malformed data is discarded.

Auth, membership checks, approval decision/detail APIs, financial execution, workspace execution settings, voice capabilities, health, and evaluation reports are never served from this display cache. Mutations always execute through their existing services and permission checks.

## Redis keys

The existing `REDIS_URL` and `REDIS_KEY_PREFIX` are used; no new secret or migration is required.

- `{prefix}:v2:dashboard:version:*`: global generation.
- `{prefix}:v2:dashboard:version:{organization_id}`: organization generation.
- `{prefix}:v2:dashboard:{global_generation}:{organization_id}:{organization_generation}:{request_hash}`: response, with a 30-second TTL.

Generation keys expire after 24 hours. A missing generation is initialized atomically to a new random token, so eviction/expiry cannot revive an older response. Rotating a generation immediately makes existing snapshots unreachable. Their keys expire naturally; no blocking `KEYS`, wildcard deletes, or database-wide Redis flush is used.

## Invalidation after changes

`DashboardSession`, installed on the shared session factory, tracks ORM inserts, updates, deletes, and bulk statements. It awaits generation rotation after a successful root commit, including explicit `commit()`, `async with session.begin()`, API writes, MCP tools, and background workers using that factory. Savepoints never publish uncommitted data; root rollback clears pending invalidations. A move between organizations invalidates both scopes.

ORM object writes normally rotate just the affected organization's generation. Bulk/text statements that do not load a tenant object conservatively rotate the global generation. A slow reader that started before a commit can fill only its old namespace and cannot repopulate the current one. Cancellation after commit shields the short invalidation operation so it can finish.

Redis operations have a 200ms timeout. Cache failures fall back to PostgreSQL; an invalidation failure does not turn a successful business commit into an error. This is a display optimization, not an atomic PostgreSQL/Redis transaction: missed invalidations or writes performed outside the shared session factory are bounded by the 30-second response TTL. Approval and execution decisions continue to read authoritative state.

## Frontend snapshots

Only dashboard resource pages and command-center display reads opt into immediate restoration. The in-memory store holds at most 100 snapshots for up to 60 seconds, with separate organization, endpoint, filter, and pagination keys. It does not use browser storage and does not persist credentials or data across a full page load.

Identical in-flight reads share a request. Unmounting a tab does not discard that request's result; mutations and manual refresh do invalidate it, preventing older responses from replacing new data. Organization mutations invalidate local snapshots before and after the request and notify other tabs through a metadata-only BroadcastChannel. Pure search, knowledge-answer, and voice-provider requests do not invalidate dashboard data.

An account or membership/role change clears snapshots. Logout and permission failures also clear cached data; denied requests do not trigger an automatic retry loop. A transient background error can retain a snapshot until its age limit; expired or denied data is removed. A changed filter or workspace cannot display the previous view's records while loading.

## Verification

Unit and SQL-session tests cover hits, TTLs, filter/tenant/user/role separation, manual refresh, invalid data, Redis outage, late-reader races, commits, nested transactions, rollbacks, and bulk writes. A local Redis integration test exercises the actual Lua script, key expiry, and namespace rotations using a unique test prefix. Browser checks hold network requests open to test immediate tab return, post-upload refresh, search isolation, background updates, workspace switching, and permission denial.
