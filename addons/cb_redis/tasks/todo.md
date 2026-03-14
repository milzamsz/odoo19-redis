# cb_redis — Task Tracker

## Implementation

- [x] Create directory structure and `__manifest__.py`
- [x] Create `redis_session_store.py` — core engine with lazy init, filesystem fallback, live reconfiguration
- [x] Create `models/res_config_settings.py` — settings fields (config_parameter), test connection button
- [x] Create `views/res_config_settings_views.xml` — General Settings UI with conditional visibility
- [x] Create `__init__.py` files — root (patch at import) + models
- [x] Copy icon from smile module

## Verification Checklist

- [ ] Install module — filesystem sessions still work (Redis disabled by default)
- [ ] Settings > General Settings > "Redis Session Store" section visible
- [ ] Enable Redis, fill connection details, click "Test Connection" — success toast
- [ ] Click Save — log shows "Redis session store: connected"
- [ ] Login/logout — sessions stored in Redis (`redis-cli KEYS '*'`)
- [ ] Change a setting, save — live reconfiguration (no restart)
- [ ] Disable Redis, save — fallback to filesystem

## Review

### Architecture Decisions
- **Lazy init via `_ensure_redis()`**: Solves chicken-and-egg (session store accessed before DB auth)
- **Raw SQL for config reads**: Same pattern as `ir_config_parameter._get_param()` — no ORM needed
- **`threading.Event` for config change signal**: Lightweight, thread-safe
- **60-second config re-check**: Ensures multi-worker convergence
- **Filesystem fallback**: Prevents misconfigured Redis from breaking Odoo
- **No per-method `RedisError` fallback**: Avoids split-brain session storage
- **Import-time patch in `__init__.py`**: Survives server restarts

### Known Limitations
- Existing sessions lost when switching filesystem ↔ Redis (users must re-login)
- Multi-worker: config changes propagate within ~60 seconds (not instant)
- Password stored in plaintext in `ir_config_parameter` (matches Odoo convention)
