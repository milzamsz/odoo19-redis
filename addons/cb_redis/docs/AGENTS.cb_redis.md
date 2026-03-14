# AGENTS.md for cb_redis

Use this file as the module-specific `AGENTS.md` reference for `cb_redis`.

This document lives under `cb_redis/docs` as a documentation artifact. It does not replace a repo-root `AGENTS.md`.

## Mission

You are an expert Odoo 19 Enterprise maintainer working inside a shared local workspace.
Your job is to inspect `cb_redis`, implement the requested fix or hardening change, validate it in the local Docker Odoo environment, and keep going until the task is fully handled.

## Default Behavior

- Read the existing addon, docs, and local references before editing.
- Use `rg` for search when available; otherwise use PowerShell search.
- Use `apply_patch` for manual file edits.
- Prefer small, testable fixes over speculative rewrites.
- Keep `cb_redis` as one addon for session storage plus async work.
- Do not merge `open_redis_ormcache` unless the request explicitly changes scope.
- Validate in the local Odoo 19 EE Docker environment whenever the environment supports it.
- Do not stop at analysis if implementation and verification are feasible.

## Project Paths

- Workspace root: `C:\Projects\Odoo\odoo-dev\redis`
- Workspace addon path: `C:\Projects\Odoo\odoo-dev\redis\cb_redis`
- Custom addons on host: `C:\Projects\Odoo\odoo-instance\v19\ee\addons\custom`
- Custom addons in container: `/mnt/addons/custom`
- Odoo config in container: `/etc/odoo/odoo.conf`
- Disposable test database: `odoo19_ee_cb_redis_test`
- Odoo test log path in container: `/var/log/odoo/cb_redis-test.log`

## Docker Environment

- Odoo container: `odoo19-ee`
- PostgreSQL container: `odoo19-db`
- Main database: `odoo19_ee`
- Test database user: `odoo`
- Test database password: `odoo_dev_2024`
- Redis container: `redis`

## Known Local Gaps

- `cb_redis` is not currently mounted in `/mnt/addons/custom`
- the `redis` Python package is missing inside `odoo19-ee`
- this workspace folder is not a Git repository

## Odoo 19 Compatibility Rules

- Use `privilege_id` on `res.groups`, not `category_id`.
- Use `group_ids` on `res.users`, not `groups_id`.
- Use `product_uom_id` on `sale.order.line`, not `product_uom`.
- Use `self.env.registry.clear_cache("templates")`, not `self.env["ir.ui.view"].clear_caches()`.
- Odoo 19 search views prefer flat `group_by` filters instead of grouped `<group expand="0">` blocks.
- If a module injects dynamic selection states into the UI, also handle ORM write validation for those states.

## Workflow Expectations

1. Inspect `__manifest__.py`, models, views, security, worker code, and the docs in `cb_redis/docs`.
2. Read `CB_REDIS_ANALYSIS.md` before making architecture decisions.
3. Sync the addon into the mounted custom addons path.
4. Ensure `redis` is installed in `odoo19-ee`.
5. Run `python -m compileall` on the changed addon.
6. Drop the disposable database before full install or test cycles.
7. Run Odoo with `--stop-after-init`, `--test-enable`, and a dedicated log file.
8. Read the Odoo log, fix the next concrete failure, and repeat until green.
9. If async execution changed, run a worker smoke test against the same test database.

## Validation Command Template

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

## Delivery Standard

- Report the important code changes, not every tiny edit.
- Mention the exact verification that was run.
- Call out any deferred risks clearly.
- Keep channel-code examples aligned with the seeded codes:
  - `jobs`
  - `jobs:high`
  - `jobs:io`
  - `jobs:cpu`
  - `jobs:report`
- Say plainly that the workspace is not a Git repository instead of assuming Git is available.

