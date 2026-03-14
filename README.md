# v19_redis

GitHub-ready Dokploy deployment repository for Odoo 19 with:

- `cb_redis` as a custom addon
- Redis 8 for session storage and async broker streams
- split app and database deployment
- optional PostgreSQL 17 + pgvector database stack

## Repository Layout

- `addons/cb_redis`: the Odoo addon code
- `docker-compose.yml`: main Dokploy stack for Odoo app, Redis, and worker
- `docker-compose.db.yml`: optional separate PostgreSQL 17 + pgvector stack
- `Dockerfile`: custom Odoo image with the addon and Python dependencies
- `docker-entrypoint-dokploy.sh`: runtime config generator for app and worker
- `postgres-init/01-enable-vector.sql`: enables the `vector` extension on first DB initialization
- `.env.example`: environment template for Dokploy

## Recommended Dokploy Topology

Deploy these as separate services:

1. PostgreSQL 17 with pgvector
2. Redis 8
3. Odoo app
4. cb_redis worker

This repo is already arranged for that model:

- `docker-compose.yml` is the app stack
- `docker-compose.db.yml` is a separate optional DB stack

## Main Stack

The main stack in `docker-compose.yml` contains:

- `redis`
- `odoo-app`
- `cb-redis-worker`

It assumes PostgreSQL is external and reachable through:

- `ODOO_DB_HOST`
- `ODOO_DB_PORT`
- `ODOO_DB_NAME`
- `ODOO_DB_USER`
- `ODOO_DB_PASSWORD`

## Database Options

### Option A: External Dokploy PostgreSQL service

Recommended for split app and database deployments.

Requirements:

- PostgreSQL 17 is recommended
- pgvector must be available
- run `CREATE EXTENSION IF NOT EXISTS vector;` in the target Odoo database

### Option B: Deploy the included DB stack

Use `docker-compose.db.yml` if you want this repo to manage the database stack too.

That stack uses:

- `pgvector/pgvector:pg17`
- `postgres-init/01-enable-vector.sql`

Important:

- the init script runs only on first initialization of a fresh database volume

## Environment Setup

1. Copy `.env.example` to `.env`
2. Set real values for:
   - `ODOO_DB_HOST`
   - `ODOO_DB_NAME`
   - `ODOO_DB_USER`
   - `ODOO_DB_PASSWORD`
   - `ODOO_ADMIN_PASSWORD`
3. Keep `ODOO_DB_HOST` pointed to your separate PostgreSQL service

If you deploy the included DB stack separately, set:

- `ODOO_DB_HOST=postgres`

or the actual hostname Dokploy gives that database service.

## Dokploy Deployment

### App stack

Use `docker-compose.yml` in Dokploy.

Set environment variables from `.env.example`.

The app stack will:

- build the custom Odoo image from GitHub
- include the `cb_redis` addon
- install the Python `redis` package
- run the Odoo app
- run the async worker
- provide Redis for sessions and streams

### Database stack

If needed, deploy `docker-compose.db.yml` as a separate Dokploy application.

## First-Time Odoo Setup

After the app is running:

1. install `CB Redis (Session Store + Async Broker)`
2. open `Settings -> General Settings`
3. configure `Redis Session Store`
4. click `Test Connection`
5. save
6. enable `Async Broker (Redis Streams)` only after the worker is running

Recommended starting values:

- `Redis Host = redis`
- `Redis Port = 6379`
- `Redis DB Index = 1`
- `Key Prefix = odoo:session:`
- `Stream Prefix = cb`

## GitHub Push Flow

Inside `C:\Projects\Odoo\odoo-instance\v19\v19_redis`:

```powershell
git init -b main
git config user.name "Your Name"
git config user.email "you@example.com"
git add .
git commit -m "Initial Dokploy deployment for Odoo 19 cb_redis"
```

Then either create the GitHub repo in the web UI or with GitHub CLI:

```powershell
gh repo create v19_redis --private --source . --remote origin --push
```

If you prefer a public repo, change `--private` to `--public`.

## Dokploy From GitHub

After the repository is on GitHub:

1. connect GitHub to Dokploy
2. create a new Compose application
3. point Dokploy to this repository
4. select `docker-compose.yml` as the compose path
5. set the environment variables from `.env.example`
6. deploy

If you also want the database from this repo:

1. create a second Dokploy Compose application
2. point it to the same GitHub repository
3. select `docker-compose.db.yml` as the compose path
4. deploy it first
5. point `ODOO_DB_HOST` in the app stack to that database service

## Verification Checklist

After deployment, verify:

- Odoo app opens successfully
- Redis is reachable from Odoo
- session keys are created in Redis
- worker is running
- async tasks move from `pending` to `done`
- `vector` extension exists in PostgreSQL if you use vector-based Odoo features
