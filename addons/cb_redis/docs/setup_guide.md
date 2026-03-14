# CB Redis Setup and Configuration Guide

> Module: `cb_redis` `19.0.2.0.0`
>
> Odoo: `19.0 Enterprise`
>
> Features: Redis session storage and Redis Streams async broker

## Summary

`cb_redis` combines two Redis-backed capabilities:

- Redis session storage for Odoo HTTP sessions
- Redis Streams background job dispatch through `.delayable()` and `worker.py`

This guide reflects the current code in the repository and the local Docker EE environment that was inspected on `2026-03-14`.

For Dokploy-specific deployment guidance with split app and database services, see `cb_redis/docs/USER_MANUAL_DOKPLOY.md`.

## Prerequisites

### Runtime Requirements

- Odoo 19 Enterprise
- Redis 7 or newer with Streams support
- Python package `redis` available inside the Odoo runtime and any worker runtime
- Network connectivity from Odoo and worker containers to Redis

### Local Environment Notes

The local EE environment currently uses:

- Odoo container: `odoo19-ee`
- Postgres container: `odoo19-db`
- Main database: `odoo19_ee`
- Host custom addons path: `C:\Projects\Odoo\odoo-instance\v19\ee\addons\custom`
- Container custom addons path: `/mnt/addons/custom`

Two important local gaps were confirmed:

- `cb_redis` is not yet copied into `/mnt/addons/custom`
- `redis` is not yet installed inside `odoo19-ee`

### Install the Python Dependency

Inside the Odoo container:

```bash
python3 -m pip install redis
```

If you run a separate worker image or container, install `redis` there too.

## Install the Addon

### Local EE Sync

Copy the addon into the mounted custom addons path:

```powershell
robocopy "C:\Projects\Odoo\odoo-dev\redis\cb_redis" "C:\Projects\Odoo\odoo-instance\v19\ee\addons\custom\cb_redis" /E
```

After the copy, the addon should exist in the Odoo container at:

```text
/mnt/addons/custom/cb_redis
```

### Install or Update in Odoo

Restart Odoo if needed, then install `cb_redis` from Apps or through a `--stop-after-init` command.

Example disposable validation flow:

```powershell
python -m compileall "C:\Projects\Odoo\odoo-dev\redis\cb_redis"
docker exec odoo19-db bash -lc "PGPASSWORD=odoo_dev_2024 dropdb -h localhost -U odoo --if-exists odoo19_ee_cb_redis_test"
docker exec odoo19-ee bash -lc "rm -f /var/log/odoo/cb_redis-test.log"
docker exec odoo19-ee bash -lc "odoo server -c /etc/odoo/odoo.conf -d odoo19_ee_cb_redis_test -i base,base_setup,cb_redis --without-demo=all --test-enable --test-tags /cb_redis --stop-after-init --no-http --logfile=/var/log/odoo/cb_redis-test.log --log-level=info --log-handler=:INFO"
docker exec odoo19-ee bash -lc "tail -n 200 /var/log/odoo/cb_redis-test.log"
```

## Redis Session Store

### What It Does

When enabled, the addon replaces Odoo's filesystem session storage with a Redis-backed session store.

Current implementation details:

- configuration is read from `ir.config_parameter`
- the session store is patched at import time
- Redis initialization is lazy
- filesystem fallback remains available when Redis session storage is disabled

### Settings Fields

In `Settings -> General Settings`, configure:

| Field | Meaning |
|---|---|
| `Enable Redis Session Store` | master toggle for session storage |
| `Redis URL` | full URL override such as `redis://:password@redis:6379/1` |
| `Redis Host` | host used when URL is blank |
| `Redis Port` | port used when URL is blank |
| `Redis Password` | password used when URL is blank |
| `Redis DB Index` | Redis DB number used when URL is blank |
| `Key Prefix` | prefix prepended to session keys |
| `Session TTL` | expiry in seconds |
| `Use SSL` | enable TLS connection settings |

### Test Connection

Use the `Test Connection` button from Settings before saving.

The current implementation:

- uses the unsaved form values
- opens a Redis client directly
- returns an Odoo notification on success
- raises `UserError` on failure

### Verify Sessions in Redis

If the configured DB index is `1` and the prefix is `odoo:session:`, you can verify session keys with:

```bash
docker exec redis redis-cli -n 1 KEYS "odoo:session:*"
```

## Async Broker

### What It Does

The broker publishes `cb.async.task` records to Redis Streams and consumes them from an external worker.

Current implementation pieces:

- `.delayable()` on all recordsets through `_inherit = 'base'`
- `cb.async.channel` for queue metadata
- `cb.async.task` for payload and state
- `worker.py` for external execution

### Current Limitation

The broker enable flag is enforced server-side:

- `.delayable()` dispatch is blocked when `Enable Async Broker` is off
- manual `action_dispatch()` is blocked when `Enable Async Broker` is off
- `worker.py` exits immediately when the broker is disabled

### Settings Fields

| Field | Meaning |
|---|---|
| `Enable Async Broker` | UI toggle for Redis Streams broker usage |
| `Stream Prefix` | prefix used when computing `stream_key` from channel code |

## Channel Management

### Seeded Channel Codes

The seed data creates these codes:

| Name | Code | Example Stream Key with prefix `cb` |
|---|---|---|
| Default (Normal) | `jobs` | `cb:jobs` |
| High Priority | `jobs:high` | `cb:jobs:high` |
| I/O Heavy | `jobs:io` | `cb:jobs:io` |
| CPU Heavy | `jobs:cpu` | `cb:jobs:cpu` |
| Reports / Export | `jobs:report` | `cb:jobs:report` |

All seeded channels default to consumer group `cb-workers`.

### Admin Surface

The top-level `Redis Broker` menu is restricted to `base.group_system`.

## Developer API

### Basic Dispatch

Use the real seeded channel codes when targeting a specific queue:

```python
partner = self.env["res.partner"].browse(42)
partner.delayable(channel="jobs:high").action_heavy_computation()
```

If you omit `channel`, the default channel code is `jobs`.

### Retry Options

```python
partner.delayable(
    channel="jobs:cpu",
    max_retries=3,
    retry_delay=60,
).action_heavy_computation()
```

Important current behavior:

- `max_retries` and `retry_delay` are stored on the task
- failed tasks within retry limits are moved back to `pending`
- the next retry time is stored in `date_next_attempt`
- the worker re-dispatches retry-ready tasks when `date_next_attempt <= now`

### Chaining

The current `.then()` signature is:

```python
then(model_name, method_name, record_ids=None, args=None, kwargs=None)
```

A chaining example that matches the current code:

```python
partner = self.env["res.partner"].browse(42)
builder = partner.delayable(channel="jobs")
builder.task_a()
builder.then("res.partner", "task_b", record_ids=[partner.id])
builder.then("res.partner", "task_c", record_ids=[partner.id], kwargs={"notify": True})
```

Notes about the current implementation:

- `builder.task_a()` creates and dispatches the first task immediately
- `builder.then(...)` creates later tasks and links them through `next_task_id`
- chained tasks are dispatched only after the previous task succeeds
- task execution runs under the recorded requesting user when available

## Worker Deployment

### Current Worker Command

The worker entrypoint in this repository is:

```text
cb_redis/worker.py
```

In the local EE environment, after syncing the addon into the custom addons mount, the expected container path is:

```text
/mnt/addons/custom/cb_redis/worker.py
```

A matching local command is:

```bash
python3 /mnt/addons/custom/cb_redis/worker.py --config /etc/odoo/odoo.conf --database odoo19_ee
```

For a disposable validation database:

```bash
python3 /mnt/addons/custom/cb_redis/worker.py --config /etc/odoo/odoo.conf --database odoo19_ee_cb_redis_test
```

### Important Runtime Notes

- `worker.py` reads Redis connection settings from the database through `cb_redis.*` parameters
- the worker does not currently implement a `REDIS_URL` environment-variable override
- supported environment overrides currently used by the code are `WORKER_NAME`, `RECLAIM_INTERVAL`, and `RECLAIM_IDLE_MS`

### Example Worker Container Shape

If you run a separate worker container, make sure:

- the addon is mounted at the same path used by the command
- `/etc/odoo/odoo.conf` is mounted read-only
- the worker image has the `redis` Python package installed
- the worker can reach the same Postgres and Redis services as Odoo

## Configuration Reference

The addon currently uses these `ir.config_parameter` keys:

| Key | Meaning |
|---|---|
| `cb_redis.enable` | enable Redis session store |
| `cb_redis.url` | full Redis URL override |
| `cb_redis.host` | Redis hostname |
| `cb_redis.port` | Redis port |
| `cb_redis.password` | Redis password |
| `cb_redis.db_index` | Redis DB index |
| `cb_redis.key_prefix` | session key prefix |
| `cb_redis.session_ttl` | session TTL |
| `cb_redis.ssl` | SSL toggle |
| `cb_redis.broker_enable` | async broker toggle |
| `cb_redis.stream_prefix` | Redis Streams prefix |

## Troubleshooting

### `The 'redis' Python package is not installed`

Install it inside the Odoo runtime:

```bash
python3 -m pip install redis
```

If you use a separate worker runtime, install it there too.

### `cb_redis` does not appear in Apps

Check that the addon was copied to:

```text
C:\Projects\Odoo\odoo-instance\v19\ee\addons\custom\cb_redis
```

and that the container sees it at:

```text
/mnt/addons/custom/cb_redis
```

### Redis connection test fails

Check:

- Redis container is running
- Odoo can resolve the Redis hostname
- DB index and password are correct
- TLS settings match the server

### Async tasks stay in `pending` or `queued`

Check:

- worker is running against the correct Odoo config and database
- worker can import the addon from the mounted path
- Redis Streams consumer group exists for the target channel

### Retry delay is not respected

Check:

- the worker is running continuously
- the task has a populated `date_next_attempt`
- the task remains in `pending` until the scheduled time
- the worker can still reach Redis and the database
