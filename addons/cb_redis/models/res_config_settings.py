# Part of CB Redis. See LICENSE file for full copyright and licensing details.

import logging

from odoo import fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # -- Redis Session Store --------------------------------------------------

    cb_redis_enable = fields.Boolean(
        string="Enable Redis Session Store",
        config_parameter='cb_redis.enable',
    )
    cb_redis_url = fields.Char(
        string="Redis URL",
        config_parameter='cb_redis.url',
        help="Full Redis URL (e.g. redis://:password@host:6379/1). "
             "If set, overrides Host, Port, Password, and DB Index.",
    )
    cb_redis_host = fields.Char(
        string="Redis Host",
        config_parameter='cb_redis.host',
        default='localhost',
    )
    cb_redis_port = fields.Char(
        string="Redis Port",
        config_parameter='cb_redis.port',
        default='6379',
    )
    cb_redis_password = fields.Char(
        string="Redis Password",
        config_parameter='cb_redis.password',
    )
    cb_redis_db_index = fields.Char(
        string="Redis DB Index",
        config_parameter='cb_redis.db_index',
        default='1',
    )
    cb_redis_key_prefix = fields.Char(
        string="Key Prefix",
        config_parameter='cb_redis.key_prefix',
        help="Optional prefix for Redis keys (e.g. 'odoo:session:'). "
             "Useful when sharing a Redis instance across environments.",
    )
    cb_redis_session_ttl = fields.Integer(
        string="Session TTL (seconds)",
        config_parameter='cb_redis.session_ttl',
        default=604800,
        help="Time-to-live for sessions in Redis. Default: 604800 (7 days).",
    )
    cb_redis_ssl = fields.Boolean(
        string="Use SSL",
        config_parameter='cb_redis.ssl',
    )

    # -- Redis Async Broker ------------------------------------------------

    cb_redis_broker_enable = fields.Boolean(
        string="Enable Async Broker",
        config_parameter='cb_redis.broker_enable',
        help="Enable Redis Streams async broker for background job processing.",
    )
    cb_redis_stream_prefix = fields.Char(
        string="Stream Prefix",
        config_parameter='cb_redis.stream_prefix',
        default='cb',
        help="Prefix for Redis stream keys (e.g. 'cb' → 'cb:jobs:high').",
    )

    def set_values(self):
        """Save config and signal the session store to reload."""
        super().set_values()
        from ..async_broker import reset_broker_client
        from ..redis_session_store import notify_config_changed
        reset_broker_client()
        notify_config_changed()
        _logger.info("cb_redis: configuration saved, Redis clients will reload")

    def cb_redis_test_connection(self):
        """Test Redis connection using current (possibly unsaved) form values."""
        self.ensure_one()

        try:
            import redis as redis_lib
        except ImportError:
            raise UserError(
                "The 'redis' Python package is not installed.\n"
                "Run: pip install redis"
            )

        try:
            from ..redis_session_store import _parse_redis_url

            if self.cb_redis_url:
                kwargs = _parse_redis_url(self.cb_redis_url)
            else:
                kwargs = {
                    'host': self.cb_redis_host or 'localhost',
                    'port': int(self.cb_redis_port or 6379),
                    'db': int(self.cb_redis_db_index or 1),
                    'password': self.cb_redis_password or None,
                }

            if self.cb_redis_ssl and 'ssl' not in kwargs:
                kwargs['ssl'] = True
                kwargs['ssl_cert_reqs'] = None

            kwargs['socket_connect_timeout'] = 5
            client = redis_lib.Redis(**kwargs)
            client.ping()
            info = client.info('server')
            version = info.get('redis_version', 'unknown')
            client.close()
        except Exception as e:
            raise UserError(f"Redis connection failed:\n{e}")

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': "Redis Connection",
                'message': f"Connection successful! (Redis v{version})",
                'type': 'success',
                'sticky': False,
            },
        }
