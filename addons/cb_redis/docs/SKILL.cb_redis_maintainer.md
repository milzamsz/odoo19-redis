---
name: cb-redis-maintainer
description: Maintain, harden, validate, and document the `cb_redis` Odoo 19 Enterprise addon in the local Docker environment. Use when working on Redis-backed session storage, Redis Streams async execution, `worker.py`, `cb.async.*` models, or the `cb_redis` deployment and validation flow.
---

# CB Redis Maintainer

Use this skill when the task is to inspect, fix, validate, or document `cb_redis`.

## What This Skill Covers

- Redis session-store behavior in `redis_session_store.py`
- Redis Streams broker behavior in `async_broker.py`
- Task, channel, and log models under `models/`
- External worker execution in `worker.py`
- Local Odoo 19 EE deployment and validation
- Documentation and operator guidance in `cb_redis/docs`

## Start Here

Read these files before changing architecture or workflow:

- `cb_redis/docs/CB_REDIS_ANALYSIS.md`
- `cb_redis/docs/PRD_cb_redis.md`
- `cb_redis/docs/setup_guide.md`

Read the reference addons only when needed:

- `smile_redis_session_store/redis_session_store.py`
- `open_redis_ormcache/modules/registry.py`

## Working Style

- Inspect the existing addon before editing.
- Keep `cb_redis` as one addon unless the user explicitly asks to split scope.
- Prefer small fixes driven by the next real failing behavior.
- Keep examples aligned with seeded channel codes:
  - `jobs`
  - `jobs:high`
  - `jobs:io`
  - `jobs:cpu`
  - `jobs:report`

## Known Sharp Edges

- `cb_redis.broker_enable` exists in Settings but is not yet enforced everywhere
- `retry_delay` is recorded on the task but not yet honored by real scheduling
- worker execution currently uses `SUPERUSER_ID`
- `stream_key` is stored even though it depends on `cb_redis.stream_prefix`
- the live `odoo19-ee` container currently lacks the `redis` Python package
- `cb_redis` is not yet copied into `/mnt/addons/custom`

## Local Environment

- Workspace root: `C:\Projects\Odoo\odoo-dev\redis`
- Addon path: `C:\Projects\Odoo\odoo-dev\redis\cb_redis`
- Host custom addons path: `C:\Projects\Odoo\odoo-instance\v19\ee\addons\custom`
- Container custom addons path: `/mnt/addons/custom`
- Odoo container: `odoo19-ee`
- DB container: `odoo19-db`
- Main database: `odoo19_ee`
- Test database: `odoo19_ee_cb_redis_test`
- Odoo config: `/etc/odoo/odoo.conf`
- Test log: `/var/log/odoo/cb_redis-test.log`

## Recommended Workflow

1. Inspect the target code path and compare it to the docs backlog.
2. Sync `cb_redis` into the mounted custom addons path.
3. Ensure `redis` is installed in `odoo19-ee`.
4. Run `python -m compileall` on `cb_redis`.
5. Drop the disposable database.
6. Install or update `cb_redis` with `--stop-after-init` and `--test-enable`.
7. Read the log and patch the next concrete failure.
8. Run a worker smoke test when async behavior changed.
9. Update docs if public behavior, setup steps, or API examples changed.

## Command Template

```powershell
robocopy "C:\Projects\Odoo\odoo-dev\redis\cb_redis" "C:\Projects\Odoo\odoo-instance\v19\ee\addons\custom\cb_redis" /E
python -m compileall "C:\Projects\Odoo\odoo-dev\redis\cb_redis"
docker exec odoo19-ee bash -lc "python3 -m pip install redis"
docker exec odoo19-db bash -lc "PGPASSWORD=odoo_dev_2024 dropdb -h localhost -U odoo --if-exists odoo19_ee_cb_redis_test"
docker exec odoo19-ee bash -lc "rm -f /var/log/odoo/cb_redis-test.log"
docker exec odoo19-ee bash -lc "odoo server -c /etc/odoo/odoo.conf -d odoo19_ee_cb_redis_test -i base,base_setup,cb_redis --without-demo=all --test-enable --test-tags /cb_redis --stop-after-init --no-http --logfile=/var/log/odoo/cb_redis-test.log --log-level=info --log-handler=:INFO"
docker exec odoo19-ee bash -lc "tail -n 200 /var/log/odoo/cb_redis-test.log"
docker exec odoo19-ee bash -lc "python3 /mnt/addons/custom/cb_redis/worker.py --config /etc/odoo/odoo.conf --database odoo19_ee_cb_redis_test"
```

## Good Outputs

- Hardened code with a clear explanation of the operational change
- Updated docs when behavior or setup changes
- A concise validation summary with exact commands run
- Clear residual risks when a deeper redesign is deferred

