# CB Redis Master Prompt

Use the following prompt when asking a coding agent to harden the existing `cb_redis` addon.

```text
You are an expert Odoo 19 Enterprise module developer and solution architect.

Harden the existing Odoo 19 Enterprise addon named `cb_redis`.

Before coding:
- Read the existing addon first instead of scaffolding a new module.
- Read these documents before making changes:
  - `cb_redis/docs/CB_REDIS_ANALYSIS.md`
  - `cb_redis/docs/PRD_cb_redis.md`
  - `cb_redis/docs/setup_guide.md`
- Preserve the addon boundary: keep `cb_redis` as one addon for Redis session storage plus async job execution.
- Do not merge `open_redis_ormcache` in this task.

Project goal:
- Turn `cb_redis` into a reliable, secure, Odoo 19 EE-ready Redis integration for shared HTTP sessions and Redis Streams background work.

Target users:
- Odoo system administrators
- Odoo backend developers
- Operators responsible for worker health and failed-task recovery

Current known gaps to address:
- `cb_redis` is not mounted in the local EE custom addons path
- the `redis` Python package is missing in `odoo19-ee`
- `cb_redis.broker_enable` is exposed in Settings but not enforced in dispatch or worker startup
- `retry_delay` is stored on tasks but not actually honored
- tasks execute in the worker under `SUPERUSER_ID`
- `cb.async.channel.stream_key` is stored even though it depends on mutable config
- docs and examples drift from the real channel codes and chaining API

Required deliverables:
- Hardened addon code in `cb_redis`
- Updated docs where behavior changed
- Tests for the main hardening scenarios
- Local Docker validation against Odoo 19 Enterprise
- Final summary of code changes, validation, and residual risks

Environment:
- Workspace root: `C:\Projects\Odoo\odoo-dev\redis`
- Addon path: `C:\Projects\Odoo\odoo-dev\redis\cb_redis`
- Odoo container: `odoo19-ee`
- DB container: `odoo19-db`
- Odoo config path: `/etc/odoo/odoo.conf`
- Host custom addons path: `C:\Projects\Odoo\odoo-instance\v19\ee\addons\custom`
- Mounted custom addons path: `/mnt/addons/custom`
- Disposable test database: `odoo19_ee_cb_redis_test`
- Test log path: `/var/log/odoo/cb_redis-test.log`

Reference modules:
- `smile_redis_session_store`
- `open_redis_ormcache`

Functional scope:
- Models involved:
  - `res.config.settings`
  - `cb.async.channel`
  - `cb.async.task`
  - `cb.async.task.log`
- Key fields involved:
  - `cb_redis.enable`
  - `cb_redis.broker_enable`
  - `cb_redis.stream_prefix`
  - `cb.async.task.state`
  - `cb.async.task.retry_count`
  - planned `requested_by_user_id`
  - planned `date_next_attempt`
- Required UI areas:
  - Settings -> General Settings
  - Redis Broker -> Async Tasks
  - Redis Broker -> Channels
- Required actions or automation:
  - `.delayable()` dispatch
  - manual dispatch and retry actions
  - external worker execution
- Required security behavior:
  - admin-only operational UI
  - task execution under the requesting user context
  - fail-fast broker gating
- Required audit behavior:
  - retain task logs
  - preserve clear state transitions for queue, run, retry, fail, and done

Technical constraints:
- Odoo version is exactly 19 Enterprise.
- Preserve existing project patterns unless the task explicitly requires redesign.
- Use `apply_patch` for manual file edits.
- Use `rg` for search when available.
- Validate in local Docker whenever the environment supports it.
- Keep iterating until the install path and targeted tests pass.

Odoo 19 compatibility checklist:
- Use `privilege_id` on `res.groups`.
- Use `group_ids` on `res.users`.
- Use `product_uom_id` on `sale.order.line`.
- Use `env.registry.clear_cache("templates")` for view-template cache invalidation.
- Flatten search-view group-by filters for Odoo 19.
- If dynamic selection values are introduced, handle both UI metadata and ORM write validation.

Implementation expectations:
1. Inspect the addon and compare it to the reference modules first.
2. Sync `cb_redis` into the mounted custom addons path before install tests.
3. Install `redis` in `odoo19-ee` before runtime validation.
4. Implement the change in small, testable slices.
5. Run `python -m compileall` on `cb_redis`.
6. Reset the disposable test database before full install or test cycles.
7. Run Odoo with `--stop-after-init`, `--test-enable`, and a dedicated log file.
8. Read the log, fix the next concrete error, and continue until green.
9. Run a worker smoke test if async execution paths changed.

Validation command pattern:
- `robocopy "C:\Projects\Odoo\odoo-dev\redis\cb_redis" "C:\Projects\Odoo\odoo-instance\v19\ee\addons\custom\cb_redis" /E`
- `python -m compileall "C:\Projects\Odoo\odoo-dev\redis\cb_redis"`
- `docker exec odoo19-ee bash -lc "python3 -m pip install redis"`
- `docker exec odoo19-db bash -lc "PGPASSWORD=odoo_dev_2024 dropdb -h localhost -U odoo --if-exists odoo19_ee_cb_redis_test"`
- `docker exec odoo19-ee bash -lc "rm -f /var/log/odoo/cb_redis-test.log"`
- `docker exec odoo19-ee bash -lc "odoo server -c /etc/odoo/odoo.conf -d odoo19_ee_cb_redis_test -i base,base_setup,cb_redis --without-demo=all --test-enable --test-tags /cb_redis --stop-after-init --no-http --logfile=/var/log/odoo/cb_redis-test.log --log-level=info --log-handler=:INFO"`
- `docker exec odoo19-ee bash -lc "tail -n 200 /var/log/odoo/cb_redis-test.log"`
- `docker exec odoo19-ee bash -lc "python3 /mnt/addons/custom/cb_redis/worker.py --config /etc/odoo/odoo.conf --database odoo19_ee_cb_redis_test"`

Quality bar:
- No placeholder logic left in the hardening path
- Broker gating is explicit
- Retry timing is real, not only recorded
- Task execution context is not silently elevated to superuser
- Stream prefix changes cannot leave stale stream names
- Tests cover the reference hardening scenarios
- Output explains code changes, validation, and residual risks
```

