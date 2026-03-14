#!/usr/bin/env python3
"""
CB Redis Async Worker — Standalone Redis Streams consumer for Odoo.

Runs outside the Odoo HTTP server as a dedicated process.  Connects to
the same PostgreSQL database and Redis instance, creates an Odoo
environment, and processes tasks dispatched via ``cb.async.task``.

Usage::

    python worker.py --config /path/to/odoo.conf
    python worker.py -c /etc/odoo/odoo.conf -d mydb --streams cb:jobs,cb:jobs:high

Environment Variables (optional overrides)::

    REDIS_URL          Redis connection URL
    WORKER_NAME        Consumer name (default: hostname-pid)
    RECLAIM_INTERVAL   Seconds between reclaim sweeps (default: 30)
    RECLAIM_IDLE_MS    Min idle time before reclaiming a message (default: 60000)
"""

import argparse
import logging
import os
import signal
import socket
import sys
import time

_logger = logging.getLogger('cb_redis.worker')

# Graceful shutdown flag
_shutdown = False


def _handle_signal(signum, _frame):
    global _shutdown
    _logger.info("Received signal %s — shutting down gracefully", signum)
    _shutdown = True


def _dispatch_due_retry_tasks(db_name, batch_limit):
    """Re-dispatch retry-ready tasks whose scheduled time has arrived."""
    from odoo import SUPERUSER_ID, api
    from odoo.modules.registry import Registry

    dispatched = 0
    registry = Registry(db_name)
    with registry.cursor() as cr:
        env = api.Environment(cr, SUPERUSER_ID, {})
        task_model = env['cb.async.task']
        due_task_ids = task_model._claim_due_retry_task_ids(limit=batch_limit)
        if not due_task_ids:
            return 0

        for task in task_model.browse(due_task_ids):
            try:
                task.action_dispatch()
                dispatched += 1
            except Exception:
                _logger.exception("Failed to re-dispatch retry task %s", task.id)
        cr.commit()
    return dispatched


def main():
    parser = argparse.ArgumentParser(description='CB Redis Async Worker')
    parser.add_argument('-c', '--config', required=True,
                        help='Path to odoo.conf')
    parser.add_argument('-d', '--database', default=None,
                        help='Database name (overrides odoo.conf db_name)')
    parser.add_argument('--streams', default=None,
                        help='Comma-separated stream keys to consume '
                             '(default: all active channels from DB)')
    parser.add_argument('--group', default='cb-workers',
                        help='Consumer group name (default: cb-workers)')
    parser.add_argument('--consumer', default=None,
                        help='Consumer name (default: hostname-pid)')
    parser.add_argument('--batch', type=int, default=5,
                        help='Max messages per read (default: 5)')
    parser.add_argument('--block', type=int, default=5000,
                        help='Block timeout in ms (default: 5000)')
    parser.add_argument('--reclaim-interval', type=int, default=30,
                        help='Seconds between reclaim sweeps (default: 30)')
    parser.add_argument('--reclaim-idle', type=int, default=60000,
                        help='Min idle ms before reclaiming (default: 60000)')
    args = parser.parse_args()

    # ---- Bootstrap Odoo ------------------------------------------------
    module_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.dirname(module_dir))
    sys.path.insert(0, os.path.dirname(args.config))

    import odoo
    from odoo import SUPERUSER_ID, api
    from odoo.modules.registry import Registry
    from odoo.service import server
    from odoo.tools import config as odoo_config

    odoo_config.parse_config(['-c', args.config])

    if args.database:
        odoo_config['db_name'] = args.database

    # Preload registries
    db_name = odoo_config['db_name']
    if isinstance(db_name, str):
        db_name = db_name.split(',')[0].strip()
    elif isinstance(db_name, (list, tuple)):
        db_name = db_name[0]
    server.preload_registries([db_name])

    # ---- Setup logging --------------------------------------------------
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(name)s [%(levelname)s] %(message)s',
    )

    consumer_name = (
        args.consumer
        or os.environ.get('WORKER_NAME')
        or f"{socket.gethostname()}-{os.getpid()}"
    )

    # ---- Signal handlers ------------------------------------------------
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    # ---- Resolve streams -------------------------------------------------
    from odoo.addons.cb_redis.async_broker import (
        ensure_consumer_group,
        consume_tasks,
        ack_task,
        reclaim_pending,
    )

    registry = Registry(db_name)
    with registry.cursor() as cr:
        env = api.Environment(cr, SUPERUSER_ID, {})
        broker_enabled = (
            env['ir.config_parameter'].sudo().get_param(
                'cb_redis.broker_enable', 'False',
            ) == 'True'
        )
        if not broker_enabled:
            _logger.error(
                "Async broker is disabled. Enable it in Settings before starting the worker."
            )
            sys.exit(1)

        if args.streams:
            stream_keys = [s.strip() for s in args.streams.split(',')]
            group_name = args.group
        else:
            channels = env['cb.async.channel'].search([('active', '=', True)])
            stream_keys = [ch.stream_key for ch in channels if ch.stream_key]
            group_name = (
                channels[0].consumer_group if channels else args.group
            )

    if not stream_keys:
        _logger.error("No streams to consume. Configure channels or use --streams")
        sys.exit(1)

    # Ensure consumer groups exist
    for sk in stream_keys:
        ensure_consumer_group(sk, group_name)

    _logger.info(
        "[start] redis consumer=%s streams=%s",
        consumer_name,
        ','.join(stream_keys),
    )
    _logger.info("%d", len(stream_keys))

    # ---- Main loop -------------------------------------------------------
    last_reclaim = time.time()
    reclaim_interval = int(
        os.environ.get('RECLAIM_INTERVAL', args.reclaim_interval)
    )
    reclaim_idle_ms = int(
        os.environ.get('RECLAIM_IDLE_MS', args.reclaim_idle)
    )

    while not _shutdown:
        dispatched = _dispatch_due_retry_tasks(db_name, args.batch)
        if dispatched:
            _logger.info("Dispatched %d retry-ready task(s)", dispatched)

        # Build streams dict: {stream_key: '>'}
        streams_dict = {sk: '>' for sk in stream_keys}

        results = consume_tasks(
            streams=streams_dict,
            group_name=group_name,
            consumer_name=consumer_name,
            count=args.batch,
            block_ms=args.block,
        )

        for stream_key, messages in results:
            # stream_key may be bytes
            sk = stream_key.decode() if isinstance(stream_key, bytes) else stream_key
            for msg_id, fields_data in messages:
                _process_message(db_name, sk, group_name, msg_id, fields_data)

        # Periodic reclaim sweep
        now = time.time()
        if now - last_reclaim >= reclaim_interval:
            last_reclaim = now
            for sk in stream_keys:
                reclaimed = reclaim_pending(
                    sk, group_name, consumer_name, reclaim_idle_ms,
                )
                for msg_id, fields_data in reclaimed:
                    _process_message(db_name, sk, group_name, msg_id, fields_data)

    _logger.info("[shutdown] worker stopped")


def _process_message(db_name, stream_key, group_name, msg_id, fields_data):
    """Process a single message from a Redis Stream."""
    from odoo.addons.cb_redis.async_broker import ack_task
    from odoo import SUPERUSER_ID, api
    from odoo.modules.registry import Registry

    # Decode fields
    task_id_raw = fields_data.get(b'task_id') or fields_data.get('task_id')
    if not task_id_raw:
        _logger.warning("Message %s has no task_id — skipping", msg_id)
        ack_task(stream_key, group_name, msg_id)
        return

    task_id = int(task_id_raw.decode() if isinstance(task_id_raw, bytes) else task_id_raw)

    try:
        registry = Registry(db_name)
        with registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            task = env['cb.async.task'].browse(task_id).exists()
            if not task:
                _logger.warning("Task %s not found in DB — acking", task_id)
                ack_task(stream_key, group_name, msg_id)
                return

            if task.state == 'cancelled':
                _logger.info("Task %s is cancelled — acking", task_id)
                ack_task(stream_key, group_name, msg_id)
                return

            ok = False
            try:
                task._execute()
                cr.commit()
                ok = task.state == 'done'
            except Exception:
                cr.rollback()
                _logger.exception("Task %s execution error", task_id)
                # Re-read task after rollback
                with registry.cursor() as cr2:
                    env2 = api.Environment(cr2, SUPERUSER_ID, {})
                    task2 = env2['cb.async.task'].browse(task_id)
                    task2.write({
                        'state': 'failed',
                        'error_message': 'Worker-level exception (see worker logs)',
                    })
                    cr2.commit()

            ack_task(stream_key, group_name, msg_id)
            _logger.info(
                "[done] stream=%s msg=%s ok=%s task_id=%s",
                stream_key, msg_id, ok, task_id,
            )

    except Exception:
        _logger.exception("Fatal error processing task %s", task_id)
        # Still ack to prevent infinite redelivery
        try:
            ack_task(stream_key, group_name, msg_id)
        except Exception:
            pass


if __name__ == '__main__':
    main()
