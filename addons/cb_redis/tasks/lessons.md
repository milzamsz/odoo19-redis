# cb_redis — Lessons Learned

## Chicken-and-Egg: Session Store vs Database Config

**Problem:** `http.Application.session_store` is accessed on the first HTTP request (before DB authentication), but `ir.config_parameter` requires a database cursor.

**Solution:** Lazy initialization. The `RedisSessionStore.__init__()` does NOT connect to Redis. Instead, `_ensure_redis()` is called before every operation. On first call, it opens a standalone cursor via `odoo.sql_db.db_connect()` and reads config via raw SQL.

**Key insight:** `tools.config['db_name']` is a **list** (comma-separated in .conf), not a string. Always use `db_names[0]`.

## Monkey-Patching `cached_property` (Python 3.12+)

**Problem 1:** `http.Application.session_store` is a `@functools.cached_property`. Once materialized on an instance, the descriptor is bypassed — the instance attribute shadows it.

**Solution:** When replacing the descriptor, also delete the instance attribute from `http.root` (if it exists) so the new descriptor fires on next access.

**Problem 2:** Python 3.12 changed `functools.cached_property` to require `__set_name__` be called. When you dynamically assign a `cached_property` outside a class body (`MyClass.prop = cached_property(fn)`), it raises `TypeError: Cannot use cached_property instance without calling __set_name__ on it.`

**Solution:** After assigning, call `descriptor.__set_name__(OwnerClass, 'attr_name')` explicitly:
```python
http.Application.session_store = session_store
session_store.__set_name__(http.Application, 'session_store')
```

## `res.config.settings` Pattern

- Fields with `config_parameter='key'` auto-sync with `ir_config_parameter` table
- Booleans stored as string `'True'`/`'False'` — check with `== 'True'`
- Integers stored via `repr()` — e.g., `'6379'` as string
- `set_values()` override runs AFTER parent stores all params — safe to signal reload
- `type="object"` buttons on transient models test with **unsaved** form values

## Multi-Worker Config Propagation

`threading.Event` is per-process. In multi-worker (`--workers=N`), only the worker handling the Settings save request gets the immediate signal. Other workers rely on a time-based re-check interval (60 seconds). This is acceptable for config changes (infrequent, not latency-sensitive).

## Redis Session Store — No Silent Fallback

When Redis is enabled but goes down mid-operation, exceptions should propagate (not silently fall back to filesystem). Silent fallback creates split-brain: some sessions on disk, some in Redis, leading to authentication inconsistencies. Fail loudly so the admin fixes the root cause.
