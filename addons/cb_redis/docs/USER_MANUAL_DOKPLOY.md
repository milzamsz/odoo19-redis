# CB Redis User Manual for Dokploy

This manual is for running `cb_redis` on Dokploy when your deployment is split into separate services for:

- Odoo app
- PostgreSQL database
- Redis
- optional async worker

`cb_redis` adds two Redis-backed features to Odoo:

- Redis session storage
- Redis Streams async jobs through `.delayable()` and `worker.py`

You can use only the session feature, or you can use both features together.

Ready-to-use deployment files in this repository:

- `cb_redis/docker-compose.yml`
- `cb_redis/Dockerfile`
- `cb_redis/.env.example`
- `cb_redis/postgres-init/01-enable-vector.sql`

## 1. What You Should Deploy

### Session-only deployment

Use these services:

- `odoo-app`
- `postgres`
- `redis`

### Session + async deployment

Use these services:

- `odoo-app`
- `postgres`
- `redis`
- `cb-redis-worker`

The worker is only needed if you want background jobs.

## 2. How `cb_redis` Fits a Split Dokploy Setup

With Dokploy, the clean model is:

- PostgreSQL stays your main Odoo database service
- Redis is a separate internal service
- the Odoo app uses Redis for sessions
- a second Odoo-based worker service consumes async jobs from Redis Streams

`cb_redis` does not replace PostgreSQL. Task records still live in PostgreSQL. Redis is used for:

- session key storage
- async stream transport

## 3. Pre-Deployment Checklist

Before enabling the module, make sure:

- the `cb_redis` addon is present in the Odoo image or mounted custom addons path
- the Python package `redis` is installed in the Odoo runtime
- the Odoo app can reach PostgreSQL
- the Odoo app can reach Redis
- if async is enabled, the worker uses the same code and same Odoo config as the app

## 4. Build the Odoo Image Correctly

The safest setup is to bake `cb_redis` and the Python dependency into your Odoo image.

Example Dockerfile:

```dockerfile
FROM odoo:19

USER root
RUN python3 -m pip install redis --break-system-packages

USER odoo
COPY ./cb_redis /mnt/addons/custom/cb_redis
```

Adjust `/mnt/addons/custom/cb_redis` to match the custom addons path in your own `odoo.conf`.

Important:

- use the same image for the app and the worker
- do not rely on manual `pip install` inside a running container for production
- if you mount the addon instead of baking it, keep the app and worker mounts identical

## 5. Deploy Redis as Its Own Dokploy Service

Create Redis as a separate internal service.

Example Compose service:

```yaml
services:
  redis:
    image: redis:8-alpine
    restart: unless-stopped
    command: redis-server --appendonly yes
    expose:
      - "6379"
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 5

volumes:
  redis_data:
```

Recommended Dokploy practice:

- keep Redis internal only
- do not expose Redis publicly unless you really need to
- use the service name `redis` as the hostname if it is in the same project/network
- use a named volume for Redis persistence unless you specifically need a host bind mount

## 6. Keep PostgreSQL As-Is

Because your app and database are already split, you do not need to change your PostgreSQL layout.

`cb_redis` expects:

- Odoo still uses PostgreSQL normally
- Redis is added beside PostgreSQL, not instead of it
- the worker connects to the same PostgreSQL database as the app

For Odoo 19 specifically:

- core Odoo requires PostgreSQL `13+`
- pgvector is needed for vector-based AI features, not for `cb_redis`
- the included Dokploy stack uses PostgreSQL 17 with pgvector preinstalled so you are covered for both Odoo 19 and AI/vector features

## 7. Ready-to-Import Dokploy Stack

The repository now includes a Dokploy-ready stack file at `cb_redis/docker-compose.yml`.

Use it like this:

1. copy `.env.example` to `.env`
2. edit the database password, admin password, and database name
3. import `cb_redis/docker-compose.yml` into Dokploy
4. if PostgreSQL already exists elsewhere, remove the `postgres` service and point `ODOO_DB_HOST` to the external database service

The compose stack:

- uses `redis:8-alpine`
- uses `pgvector/pgvector:pg17`
- enables `CREATE EXTENSION vector` during first PostgreSQL initialization
- builds the Odoo image from `cb_redis/Dockerfile`
- installs the Python `redis` package
- includes the addon
- uses the same image for both app and worker

Notes:

- the worker should not expose HTTP ports
- the worker uses the same Odoo image as the app
- app and worker share the same `/var/lib/odoo` volume so worker-side jobs can access the same filestore
- the worker path in the stack matches the current module layout: `/mnt/addons/custom/cb_redis/worker.py`
- the `--database` value must match the exact Odoo database where `cb_redis` is installed
- the `vector` extension init script only runs automatically on first initialization of a fresh PostgreSQL data directory

## 8. Install the Module in Odoo

After the app container is running:

1. open Odoo as an administrator
2. go to `Apps`
3. update the Apps list if needed
4. install `CB Redis (Session Store + Async Broker)`

If the module does not appear:

- confirm the addon exists inside the container custom addons path
- confirm the addons path is included in `odoo.conf`
- restart the Odoo app service after changing the image or mount

## 9. Configure Session Storage

Open:

- `Settings -> General Settings`

Find the block:

- `Redis Session Store`

Recommended starting values for a Dokploy internal Redis service:

| Field | Recommended value |
|---|---|
| `Redis Session Store` | enabled |
| `Redis URL` | leave blank unless you prefer full URL form |
| `Redis Host` | `redis` |
| `Redis Port` | `6379` |
| `Redis Password` | blank unless your Redis service requires it |
| `Redis DB Index` | `1` |
| `Key Prefix` | `odoo:session:` |
| `Session TTL` | `604800` |
| `Use SSL` | off for internal Docker networking |

Then:

1. click `Test Connection`
2. confirm the success notification
3. click `Save`

Notes:

- if `Redis URL` is filled, it overrides host, port, password, and DB index
- session storage can be enabled without enabling the async broker

## 10. Verify Session Storage Works

After saving the settings:

1. log out of Odoo
2. log back in
3. check Redis for session keys

Example check from the Redis container:

```bash
redis-cli -n 1 KEYS "odoo:session:*"
```

Expected result:

- new keys appear in Redis
- your login session still works after app restart

If you only want Redis-backed sessions, you can stop here. You do not need the worker service.

## 11. Configure Async Broker

Only do this after the worker service is deployed.

Open:

- `Settings -> General Settings`

Find the block:

- `Redis Async Broker`

Recommended starting values:

| Field | Recommended value |
|---|---|
| `Async Broker (Redis Streams)` | enabled only after worker is ready |
| `Stream Prefix` | `cb` |

Then save the settings.

Important behavior in the current module:

- `.delayable()` is blocked when the broker is disabled
- manual task dispatch is blocked when the broker is disabled
- the worker exits immediately when the broker is disabled
- the worker reads Redis settings from the Odoo database, not from Dokploy env vars

## 12. Start the Worker Service

Use a separate Dokploy service for the worker.

Current worker command:

```bash
python3 /mnt/addons/custom/cb_redis/worker.py --config /etc/odoo/odoo.conf --database odoo_prod
```

Useful optional flags:

```bash
python3 /mnt/addons/custom/cb_redis/worker.py \
  --config /etc/odoo/odoo.conf \
  --database odoo_prod \
  --batch 10 \
  --block 5000
```

Supported environment variables for worker tuning:

- `WORKER_NAME`
- `RECLAIM_INTERVAL`
- `RECLAIM_IDLE_MS`

The worker must be able to reach:

- PostgreSQL
- Redis
- the same Odoo config and addon code used by the app

## 12A. Verify pgvector Is Enabled

If you use the bundled PostgreSQL service from the included stack, the `vector` extension is created automatically the first time the database volume is initialized.

To verify it manually:

```sql
SELECT extname, extversion
FROM pg_extension
WHERE extname = 'vector';
```

Expected result:

- one row for `vector`

If you are using an existing external PostgreSQL 17 service instead of the bundled one, run this once in the target Odoo database:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

## 13. Verify Async Jobs Work

After the worker is running:

1. open `Redis Broker -> Channels`
2. confirm at least one channel is active
3. open `Redis Broker -> Async Tasks`
4. trigger an async action from custom code or a business flow that uses `.delayable()`
5. check worker logs and task state changes

Seeded channel codes in the current module:

- `jobs`
- `jobs:high`
- `jobs:io`
- `jobs:cpu`
- `jobs:report`

Use those exact codes in your code.

Example:

```python
self.env["res.partner"].browse(partner_id).delayable(channel="jobs:high").action_heavy_computation()
```

Expected result:

- task moves from `pending` to `queued`
- worker picks it up
- task ends in `done` or `failed`

## 14. What Users and Admins Should Know

For normal users:

- they should use business features that trigger async work
- they should not manually manage channels or tasks

For system administrators:

- `Redis Broker` menus are for admins
- admins can inspect channels, tasks, retries, and failures
- failed tasks can be retried from the task form

Current task execution behavior:

- the task records the requesting user
- the worker executes the target method under that user when possible
- retries wait until `date_next_attempt`

## 15. Day-to-Day Operations

### If you use only sessions

Monitor:

- Odoo app uptime
- PostgreSQL uptime
- Redis uptime
- Redis memory usage

### If you use sessions and async

Also monitor:

- worker uptime
- worker logs
- `Redis Broker -> Async Tasks`
- retry backlog
- failed tasks

## 16. Safe Rollout Order

For Dokploy with split app and database, use this rollout order:

1. confirm PostgreSQL is healthy
2. deploy Redis
3. deploy the Odoo image with `cb_redis` and the Python `redis` package
4. install `cb_redis` in Odoo
5. enable and verify session storage
6. deploy the worker service
7. enable the async broker
8. verify async tasks and worker logs

This order keeps session rollout separate from async rollout, which is easier to debug.

## 17. Safe Update Procedure

When updating `cb_redis`:

1. build the updated Odoo image
2. deploy the updated app service
3. deploy the same updated image to the worker service
4. upgrade the module in Odoo if needed
5. verify Redis session connection
6. verify worker logs and async task processing

Do not run different code versions in the app and worker for long periods.

## 18. Troubleshooting

### `Test Connection` fails

Check:

- the Redis service is up
- the Redis hostname is correct
- the app container can resolve `redis`
- the port is `6379`
- password and DB index are correct

### Session storage does not seem active

Check:

- `Redis Session Store` is enabled
- settings were saved
- Redis connection test succeeds
- the `redis` Python package is installed in the Odoo image

### Worker exits immediately

Check:

- `Async Broker (Redis Streams)` is enabled
- the worker uses the correct database name
- the worker can import `cb_redis`
- the worker image has the `redis` Python package installed

### Async tasks stay `pending`

Check:

- the worker service is running
- the worker can reach PostgreSQL and Redis
- the target channel is active
- broker is enabled in Odoo settings

### Async tasks fail repeatedly

Check:

- the delayed method is public and valid
- the requesting user has permission to perform the action
- the target record still exists
- Redis and PostgreSQL are stable

### Redis works for sessions but async jobs do not run

Check:

- the worker service exists and is running
- the worker uses the same database as the app
- the stream prefix matches the configured channels
- worker logs do not show connection errors

### AI or vector features fail because `vector` is missing

Check:

- you are using PostgreSQL 17 with pgvector installed, or another PostgreSQL 13+ server with the pgvector extension available
- `CREATE EXTENSION IF NOT EXISTS vector;` has been executed in the exact Odoo database
- if you use the included Dokploy stack, the database volume was fresh on first initialization so the init script could run

## 19. Recommended Variables

Dokploy variables are still useful for the Odoo app itself.

Typical examples:

| Variable | Example |
|---|---|
| `ODOO_DB_NAME` | `odoo_prod` |
| `ODOO_DB_HOST` | `postgres` |
| `ODOO_DB_USER` | `odoo` |
| `ODOO_DB_PASSWORD` | `your-password` |

For `cb_redis` specifically:

- Redis connection settings are stored in Odoo settings
- worker behavior is database-driven
- only worker tuning uses environment variables directly

## 20. Best-Practice Summary

- keep app, database, Redis, and worker as separate services
- use the same image for Odoo app and worker
- bake `cb_redis` and `redis` into the image
- keep Redis internal to the Dokploy project if possible
- enable session storage first
- enable async only after the worker is healthy
- use the seeded channel codes exactly as provided by the module
