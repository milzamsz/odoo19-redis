# Part of CB Redis. See LICENSE file for full copyright and licensing details.

import functools
import json
import logging
import threading
import time
from urllib.parse import urlparse

from odoo import http, tools

_logger = logging.getLogger(__name__)

SESSION_TIMEOUT = 60 * 60 * 24 * 7  # 1 week default

# Module-level signaling for live reconfiguration
_config_changed = threading.Event()

# How often (seconds) to re-check config from DB in multi-worker setups
_CONFIG_CHECK_INTERVAL = 60


# ---------------------------------------------------------------------------
# Config helpers — read ir.config_parameter via raw SQL (no ORM needed)
# ---------------------------------------------------------------------------

def _read_icp_value(cr, key):
    """Read a single value from ir_config_parameter using a raw cursor."""
    cr.execute("SELECT value FROM ir_config_parameter WHERE key = %s", [key])
    row = cr.fetchone()
    return row[0] if row else None


def _get_db_name():
    """Return the first configured database name, or None."""
    db_names = tools.config['db_name']
    if db_names:
        return db_names.split(',')[0].strip() if isinstance(db_names, str) else db_names[0]
    return None


def _load_config_from_db():
    """Read all cb_redis.* parameters from the database.

    Returns a dict of {key: value} or None if no database is available.
    """
    db_name = _get_db_name()
    if not db_name:
        return None

    try:
        from odoo.sql_db import db_connect
        db = db_connect(db_name)
        with db.cursor() as cr:
            config = {}
            for key in (
                'cb_redis.enable',
                'cb_redis.url',
                'cb_redis.host',
                'cb_redis.port',
                'cb_redis.password',
                'cb_redis.db_index',
                'cb_redis.key_prefix',
                'cb_redis.session_ttl',
                'cb_redis.ssl',
            ):
                config[key] = _read_icp_value(cr, key)
            return config
    except Exception:
        _logger.debug("Could not read Redis config from database", exc_info=True)
        return None


def _is_enabled(config):
    """Check if Redis is enabled in the config dict."""
    if config is None:
        return False
    return config.get('cb_redis.enable') == 'True'


def _parse_redis_url(url):
    """Parse a Redis URL into connection kwargs (no redis-py dependency)."""
    parsed = urlparse(url)
    kwargs = {}
    kwargs['host'] = parsed.hostname or 'localhost'
    kwargs['port'] = parsed.port or 6379
    if parsed.password:
        kwargs['password'] = parsed.password
    # Path is /0, /1, etc. — strip leading slash
    db_part = (parsed.path or '').lstrip('/')
    kwargs['db'] = int(db_part) if db_part.isdigit() else 0
    # rediss:// scheme means SSL
    if parsed.scheme == 'rediss':
        kwargs['ssl'] = True
        kwargs['ssl_cert_reqs'] = None
    return kwargs


def _build_redis_client(config):
    """Build and ping a redis.Redis client from the config dict."""
    import redis as redis_lib

    url = config.get('cb_redis.url')

    if url:
        kwargs = _parse_redis_url(url)
    else:
        kwargs = {
            'host': config.get('cb_redis.host') or 'localhost',
            'port': int(config.get('cb_redis.port') or 6379),
            'db': int(config.get('cb_redis.db_index') or 1),
            'password': config.get('cb_redis.password') or None,
        }

    # SSL from checkbox (only when not already set by rediss:// URL)
    if config.get('cb_redis.ssl') == 'True' and 'ssl' not in kwargs:
        kwargs['ssl'] = True
        kwargs['ssl_cert_reqs'] = None

    kwargs['socket_connect_timeout'] = 5
    client = redis_lib.Redis(**kwargs)
    client.ping()
    return client


def notify_config_changed():
    """Signal the session store to reload its Redis connection."""
    _config_changed.set()


# ---------------------------------------------------------------------------
# RedisSessionStore — lazy init, filesystem fallback, live reconfiguration
# ---------------------------------------------------------------------------

class RedisSessionStore(http.FilesystemSessionStore):
    """Session store that lazily connects to Redis based on ir.config_parameter.

    When Redis is not enabled or not reachable, all operations delegate to
    the parent FilesystemSessionStore transparently.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._redis = None
        self._redis_active = False
        self._expire = SESSION_TIMEOUT
        self._key_prefix = ''
        self._initialized = False
        self._last_config_check = 0.0
        self._lock = threading.Lock()

    def _ensure_redis(self):
        """Lazy init: connect to Redis if enabled, otherwise filesystem."""
        now = time.time()
        needs_check = (
            not self._initialized
            or _config_changed.is_set()
            or (now - self._last_config_check) > _CONFIG_CHECK_INTERVAL
        )
        if not needs_check:
            return

        with self._lock:
            # Double-check under lock
            now = time.time()
            needs_check = (
                not self._initialized
                or _config_changed.is_set()
                or (now - self._last_config_check) > _CONFIG_CHECK_INTERVAL
            )
            if not needs_check:
                return

            _config_changed.clear()
            self._last_config_check = now

            config = _load_config_from_db()

            if not _is_enabled(config):
                if self._redis_active:
                    _logger.info("Redis session store: disabled, switching to filesystem")
                self._redis = None
                self._redis_active = False
                self._initialized = True
                return

            try:
                self._redis = _build_redis_client(config)
                self._redis_active = True
                ttl = config.get('cb_redis.session_ttl')
                self._expire = int(ttl) if ttl else SESSION_TIMEOUT
                self._key_prefix = config.get('cb_redis.key_prefix') or ''
                self._initialized = True
                _logger.info(
                    "Redis session store: connected (prefix=%r, ttl=%ds)",
                    self._key_prefix, self._expire,
                )
            except Exception as e:
                self._redis = None
                self._redis_active = False
                self._initialized = True
                _logger.error("Redis session store: connection failed — %s", e)

    def _get_redis_key(self, sid):
        return (self._key_prefix + sid).encode('utf-8')

    # ------------------------------------------------------------------
    # Core session CRUD
    # ------------------------------------------------------------------

    def save(self, session):
        self._ensure_redis()
        if not self._redis_active:
            return super().save(session)
        key = self._get_redis_key(session.sid)
        data = json.dumps(dict(session))
        self._redis.setex(name=key, value=data, time=self._expire)

    def get(self, sid):
        self._ensure_redis()
        if not self._redis_active:
            return super().get(sid)

        if not self.is_valid_key(sid):
            return self.new()

        key = self._get_redis_key(sid)
        raw = self._redis.get(key)
        if raw:
            self._redis.expire(key, self._expire)
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                _logger.warning("Could not decode session %s from Redis", sid)
                data = {}
        else:
            if self.renew_missing:
                return self.new()
            data = {}
        return self.session_class(data, sid, False)

    def delete(self, session):
        self._ensure_redis()
        if not self._redis_active:
            return super().delete(session)
        key = self._get_redis_key(session.sid)
        self._redis.delete(key)

    # ------------------------------------------------------------------
    # Session rotation — Odoo 19 security (mirrors http.py:985-1017)
    # ------------------------------------------------------------------

    def rotate(self, session, env, soft=False):
        self._ensure_redis()
        if not self._redis_active:
            return super().rotate(session, env, soft=soft)

        from odoo.service import security
        from odoo.http import STORED_SESSION_BYTES, SESSION_DELETION_TIMER

        if soft:
            static = session.sid[:STORED_SESSION_BYTES]
            recent_session = self.get(session.sid)
            if 'next_sid' in recent_session:
                session.sid = recent_session['next_sid']
                return
            next_sid = static + self.generate_key()[STORED_SESSION_BYTES:]
            session['next_sid'] = next_sid
            session['deletion_time'] = time.time() + SESSION_DELETION_TIMER
            self.save(session)
            session['gc_previous_sessions'] = True
            session.sid = next_sid
            del session['deletion_time']
            del session['next_sid']
        else:
            self.delete(session)
            session.sid = self.generate_key()

        if session.uid:
            assert env, "saving this session requires an environment"
            session.session_token = security.compute_session_token(session, env)
        session.should_rotate = False
        session['create_time'] = time.time()
        self.save(session)

    # ------------------------------------------------------------------
    # Session cleanup
    # ------------------------------------------------------------------

    def delete_old_sessions(self, session):
        self._ensure_redis()
        if not self._redis_active:
            return super().delete_old_sessions(session)

        if 'gc_previous_sessions' in session:
            from odoo.http import SESSION_DELETION_TIMER, STORED_SESSION_BYTES
            if session.get('create_time', 0) + SESSION_DELETION_TIMER < time.time():
                self.delete_from_identifiers([session.sid[:STORED_SESSION_BYTES]])
                del session['gc_previous_sessions']
                self.save(session)

    def delete_from_identifiers(self, identifiers):
        self._ensure_redis()
        if not self._redis_active:
            return super().delete_from_identifiers(identifiers)

        for identifier in identifiers:
            pattern = self._get_redis_key(identifier + '*')
            cursor = 0
            while True:
                cursor, keys = self._redis.scan(
                    cursor=cursor, match=pattern, count=100,
                )
                if keys:
                    self._redis.delete(*keys)
                if cursor == 0:
                    break

    def get_missing_session_identifiers(self, identifiers):
        self._ensure_redis()
        if not self._redis_active:
            return super().get_missing_session_identifiers(identifiers)

        missing = set()
        for identifier in identifiers:
            pattern = self._get_redis_key(identifier + '*')
            cursor, keys = self._redis.scan(cursor=0, match=pattern, count=1)
            if not keys and cursor == 0:
                missing.add(identifier)
            elif not keys:
                found = False
                while cursor != 0:
                    cursor, keys = self._redis.scan(
                        cursor=cursor, match=pattern, count=100,
                    )
                    if keys:
                        found = True
                        break
                if not found:
                    missing.add(identifier)
        return missing

    def vacuum(self, max_lifetime=None):
        self._ensure_redis()
        if not self._redis_active:
            return super().vacuum(max_lifetime)
        # Redis handles expiry via TTL — no manual cleanup needed.


# ---------------------------------------------------------------------------
# Monkey-patch installer
# ---------------------------------------------------------------------------

def install_redis_session_store():
    """Replace http.Application.session_store with RedisSessionStore."""

    @functools.cached_property
    def session_store(self):
        _logger.info("Initializing cb_redis RedisSessionStore")
        return RedisSessionStore(
            path=tools.config.session_dir,
            session_class=http.Session,
            renew_missing=True,
        )

    # If a previous cached instance exists on the root app, clear it so
    # the new descriptor fires on next access.
    if hasattr(http, 'root') and http.root is not None:
        try:
            del http.root.session_store
        except AttributeError:
            pass

    http.Application.session_store = session_store
    # Python 3.12+ requires __set_name__ for cached_property to work
    # when assigned dynamically outside a class body.
    session_store.__set_name__(http.Application, 'session_store')
    _logger.info("cb_redis: session_store patched on http.Application")
