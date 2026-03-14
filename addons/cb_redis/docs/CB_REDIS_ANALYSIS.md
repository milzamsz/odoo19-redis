# CB Redis Analysis

## Summary

`cb_redis` is a single Odoo 19 addon that combines two Redis-backed capabilities:

- HTTP session storage through a monkey-patched `http.Application.session_store`
- Background job dispatch through Redis Streams, `cb.async.task`, and an external worker

The addon already has a solid skeleton, but it is only partially hardened. The local Odoo 19 EE environment also has deployment drift: the addon is not mounted into `/mnt/addons/custom`, and the `redis` Python package is currently missing from `odoo19-ee`.

This document captures the current architecture, compares the addon with the local reference modules, and defines the implementation backlog for the next hardening pass.

## Hardening Status

The following items are now implemented in the workspace copy of `cb_redis`:

- broker gating in `.delayable()`, `action_dispatch()`, and worker startup
- `requested_by_user_id` on `cb.async.task`
- `date_next_attempt` plus worker-side retry re-dispatch
- non-stored `cb.async.channel.stream_key`
- tighter async-task ACLs for non-admin users
- Odoo tests for the hardening flow

The remaining environment gap confirmed during validation is operational, not code-level:

- the standalone worker now boots correctly, but the local `odoo19-ee` container still cannot resolve or reach a Redis service at host `redis`

## Current Architecture

### Session Store

- `redis_session_store.py` patches `http.Application.session_store` at import time.
- Redis connection settings are read from `ir.config_parameter` through raw SQL.
- The store falls back to `FilesystemSessionStore` when Redis is disabled or unavailable during initialization.
- Live config reload is signaled through `notify_config_changed()` plus a timed recheck.

### Async Broker

- `models/async_channel.py` defines configurable queues backed by Redis Streams.
- `models/async_task.py` stores task payload, lifecycle state, retry metadata, and logs.
- `models/delayable.py` injects `.delayable()` on `base` so recordsets can queue public methods.
- `async_broker.py` wraps `XADD`, `XREADGROUP`, `XACK`, and `XAUTOCLAIM`.
- `worker.py` runs as a standalone consumer that opens an Odoo environment and executes queued tasks.

### Admin Surface

- Settings fields live on `res.config.settings`.
- Admin menu entries expose `Async Tasks` and `Channels`.
- Seed data creates these channel codes:
  - `jobs`
  - `jobs:high`
  - `jobs:io`
  - `jobs:cpu`
  - `jobs:report`

## Local Environment Findings

- Workspace root: `C:\Projects\Odoo\odoo-dev\redis`
- Live Odoo 19 EE container: `odoo19-ee`
- Live Postgres container: `odoo19-db`
- Main EE database: `odoo19_ee`
- Mounted custom addons path in container: `/mnt/addons/custom`
- Host custom addons path: `C:\Projects\Odoo\odoo-instance\v19\ee\addons\custom`
- Current gap: `cb_redis` is not present in `/mnt/addons/custom`
- Current gap: `python3 -m pip install redis` has not been run inside `odoo19-ee`
- Current gap: this workspace is not a Git repository

## Comparison to Local References

### `smile_redis_session_store`

What it does well:

- Very small and easy to reason about
- Direct session-store replacement
- Clear minimum Redis dependency

Where `cb_redis` is stronger:

- Odoo settings UI instead of config-file-only toggles
- Filesystem fallback when Redis is disabled
- Live reload support after settings changes
- Unified addon that also handles async work

Where `cb_redis` still needs hardening:

- Dependency and deployment instructions must be explicit and accurate
- Current docs drift from the implemented API
- Current worker behavior is more powerful but also riskier

### `open_redis_ormcache`

What it contributes:

- A separate pattern for monkey-patching Odoo internals with Redis-backed behavior
- Good reference for defensive Redis initialization and fallback logging

Why it is out of scope for this phase:

- It targets ORM cache, not sessions or async jobs
- Merging it now would expand the addon boundary and validation surface
- The current request is to harden `cb_redis`, not to introduce Redis ORM cache

## Confirmed Risks and Gaps

### P0: Installability and Operator Drift

- The addon cannot be used in the live EE environment until it is copied to the custom addons mount.
- The `redis` Python package is missing in `odoo19-ee`.
- The current setup guide still documents paths and environment variables that do not match `worker.py`.

### P1: Broker Safety and Behavior Gaps

- `cb_redis.broker_enable` is exposed in Settings but is not enforced in `.delayable()`, `action_dispatch()`, or worker startup.
- `retry_delay` is stored on tasks but not actually honored by the current worker flow.
- Auto-retry currently sets failed tasks back to `pending`, but nothing schedules a delayed re-dispatch.

### P1: Security and Permission Model

- The worker executes tasks in an environment created with `SUPERUSER_ID`.
- The task model ACL currently lets `base.group_user` create and write `cb.async.task` records.
- The UI is admin-only, but server-side task creation and mutation are not yet constrained to the safer model described in the backlog.

### P1: Configuration Drift in Channel Stream Names

- `cb.async.channel.stream_key` is stored even though it depends on mutable config parameter `cb_redis.stream_prefix`.
- Changing the prefix can leave stale persisted stream keys on existing channel records.

### P2: Developer Experience Drift

- Some examples still use channel names like `high` even though the actual seed code is `jobs:high`.
- The chaining example in the current guide does not match the real `.then()` signature.
- `worker.py` documents a `REDIS_URL` override that the current code does not implement.

## Prioritized Hardening Backlog

### 1. Deployment Baseline

- Sync `cb_redis` into `C:\Projects\Odoo\odoo-instance\v19\ee\addons\custom\cb_redis`
- Install `redis` inside `odoo19-ee`
- Add a disposable validation database workflow for `odoo19_ee_cb_redis_test`
- Keep the addon boundary unchanged

### 2. Broker Gating

- Fail fast when async dispatch is requested while `cb_redis.broker_enable` is off
- Fail fast when the worker is started while the broker is disabled
- Make the user-facing error actionable

### 3. Safer Task Execution

- Add `requested_by_user_id` on `cb.async.task`
- Execute the task method as the requesting user unless explicit system behavior is required
- Keep server-side permission checks in place even if a task is created from code

### 4. Real Retry Scheduling

- Add `date_next_attempt`
- Requeue only when `date_next_attempt <= now`
- Honor `retry_delay` in worker or scheduler logic

### 5. Stream Key Correctness

- Make `stream_key` a live non-stored compute field
- Recompute from current prefix plus channel code on every read

### 6. Admin UX and ACL Hardening

- Restrict manual channel management to system administrators
- Restrict manual task mutation from the admin UI
- Preserve business-user access only through explicit application flows that call `.delayable()`

### 7. Documentation and Test Coverage

- Keep channel-code examples aligned with seeded data
- Keep worker setup aligned with the actual local mount path and CLI
- Add acceptance tests for broker gating, retry timing, user-context execution, and prefix changes

## Acceptance Scenarios for the Next Code Phase

1. Redis disabled:
   - Session store falls back to filesystem.
   - Async dispatch is blocked with a clear error.
2. Redis enabled and reachable:
   - Settings connection test succeeds.
   - Session keys appear in Redis with the configured prefix.
3. Broker enabled:
   - `.delayable(channel='jobs:high')` creates a task and publishes to the expected stream.
4. Failed task with retry policy:
   - Task moves to a waiting state with `date_next_attempt`.
   - Worker does not re-run it before the delay expires.
5. Stream prefix changed:
   - Channel stream names reflect the new prefix without stale stored values.
6. Security:
   - Task executes in the requesting user context.
   - Admin-only UI actions remain admin-only.

## Recommended Next Step

Use the backlog in this order:

1. Fix deployment and documentation drift
2. Enforce broker gating
3. Implement user-context execution and retry scheduling
4. Harden `stream_key`, ACLs, and tests
