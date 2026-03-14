# Part of CB Redis. See LICENSE file for full copyright and licensing details.

"""
Redis Streams broker utilities.

Provides publish / consume / ack / reclaim primitives that wrap
the Redis Streams API (XADD, XREADGROUP, XACK, XAUTOCLAIM).

Thread-safe singleton client — reuses the connection config from
``redis_session_store`` (ir.config_parameter ``cb_redis.*``).
"""

import logging
import threading

_logger = logging.getLogger(__name__)

_broker_client = None
_broker_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Client management
# ---------------------------------------------------------------------------

def get_broker_client(force_new=False):
    """Return a shared Redis client for broker operations.

    Lazily created.  Reuses ``_build_redis_client`` from the session
    store module so connection params come from the same source of truth.
    """
    global _broker_client
    if _broker_client is not None and not force_new:
        return _broker_client

    with _broker_lock:
        if _broker_client is not None and not force_new:
            return _broker_client

        from .redis_session_store import _load_config_from_db, _build_redis_client

        config = _load_config_from_db()
        if config is None:
            raise RuntimeError(
                "Cannot initialise Redis broker: database config unavailable."
            )
        _broker_client = _build_redis_client(config)
        _logger.info("cb_redis broker: Redis client connected")
        return _broker_client


def reset_broker_client():
    """Force a reconnect on next ``get_broker_client()`` call."""
    global _broker_client
    with _broker_lock:
        _broker_client = None


# ---------------------------------------------------------------------------
# Consumer group helpers
# ---------------------------------------------------------------------------

def ensure_consumer_group(stream_key, group_name):
    """Idempotently create a consumer group on *stream_key*.

    If the stream does not exist yet, Redis creates it automatically
    when we pass ``mkstream=True``.
    """
    client = get_broker_client()
    try:
        client.xgroup_create(
            name=stream_key,
            groupname=group_name,
            id='0',
            mkstream=True,
        )
        _logger.info(
            "consumer group created: %s stream=%s", group_name, stream_key,
        )
    except Exception as exc:
        # "BUSYGROUP Consumer Group name already exists"
        if 'BUSYGROUP' in str(exc):
            pass
        else:
            raise


# ---------------------------------------------------------------------------
# Publish (XADD)
# ---------------------------------------------------------------------------

def publish_task(stream_key, task_id, task_data=None):
    """Add a message to *stream_key* for task *task_id*.

    Returns the Redis message ID (bytes).
    """
    client = get_broker_client()
    fields = {'task_id': str(task_id)}
    if task_data:
        fields.update(task_data)
    msg_id = client.xadd(stream_key, fields)
    _logger.debug("XADD %s → msg=%s task_id=%s", stream_key, msg_id, task_id)
    return msg_id


# ---------------------------------------------------------------------------
# Consume (XREADGROUP)
# ---------------------------------------------------------------------------

def consume_tasks(streams, group_name, consumer_name, count=1, block_ms=5000):
    """Read pending-but-undelivered messages from *streams*.

    ``streams`` is a dict of ``{stream_key: '>'}``.

    Returns a list of ``(stream_key, [(msg_id, fields), ...])`` or ``[]``.
    """
    client = get_broker_client()
    try:
        result = client.xreadgroup(
            groupname=group_name,
            consumername=consumer_name,
            streams=streams,
            count=count,
            block=block_ms,
        )
        return result or []
    except Exception:
        _logger.exception("XREADGROUP error")
        return []


# ---------------------------------------------------------------------------
# Acknowledge (XACK)
# ---------------------------------------------------------------------------

def ack_task(stream_key, group_name, message_id):
    """Acknowledge successful processing of *message_id*."""
    client = get_broker_client()
    client.xack(stream_key, group_name, message_id)
    _logger.debug("XACK %s group=%s msg=%s", stream_key, group_name, message_id)


# ---------------------------------------------------------------------------
# Reclaim stalled jobs (XAUTOCLAIM — Redis ≥ 6.2)
# ---------------------------------------------------------------------------

def reclaim_pending(stream_key, group_name, consumer_name, min_idle_ms=60000):
    """Reclaim messages idle longer than *min_idle_ms*.

    Uses ``XAUTOCLAIM`` (Redis 6.2+).  Returns a list of
    ``(message_id, fields)`` that have been reassigned to *consumer_name*.
    """
    client = get_broker_client()
    try:
        # XAUTOCLAIM returns (next_start_id, [(msg_id, fields), ...], deleted_ids)
        _next_id, messages, _deleted = client.xautoclaim(
            name=stream_key,
            groupname=group_name,
            consumername=consumer_name,
            min_idle_time=min_idle_ms,
            start_id='0-0',
        )
        if messages:
            _logger.info(
                "reclaimed %d stalled message(s) from %s",
                len(messages), stream_key,
            )
        return messages or []
    except Exception:
        _logger.exception("XAUTOCLAIM error on %s", stream_key)
        return []
