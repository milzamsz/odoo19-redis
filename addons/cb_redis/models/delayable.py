# Part of CB Redis. See LICENSE file for full copyright and licensing details.

"""
Delayable API — developer-friendly mixin for async task dispatch.

Usage::

    # Dispatch a method call asynchronously via Redis Streams
    self.env['sale.order'].browse(42).delayable(channel='jobs:high').action_confirm()

    # With retry policy
    self.env['sale.order'].browse(ids).delayable(
        channel='jobs:cpu', max_retries=5, retry_delay=120,
    ).compute_heavy_report()

    # Chaining — execute tasks sequentially
    builder = self.env['sale.order'].browse(42).delayable()
    builder.action_confirm()
    builder.then('sale.order', 'action_done', record_ids=[42])
"""

import json
import logging

from odoo import models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class _DelayableCallBuilder:
    """Proxy that captures a method call and dispatches it as a task."""

    def __init__(self, recordset, channel_code='jobs', max_retries=3,
                 retry_delay=60, **options):
        self._recordset = recordset
        self._env = recordset.env
        self._channel_code = channel_code
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._options = options
        self._last_task = None

    def __getattr__(self, method_name):
        """Intercept any method call and turn it into a task dispatch."""
        if method_name.startswith('_'):
            raise AttributeError(
                f"Cannot delay private methods ('{method_name}'). "
                "Use a public method name."
            )

        def _dispatch(*args, **kwargs):
            return self._create_and_dispatch(method_name, args, kwargs)

        return _dispatch

    def _create_and_dispatch(self, method_name, args, kwargs):
        """Create a ``cb.async.task`` record and dispatch to Redis."""
        task_model = self._env['cb.async.task']
        task_model._ensure_broker_enabled()

        channel = self._env['cb.async.channel'].sudo().search(
            [('code', '=', self._channel_code)], limit=1,
        )
        if not channel:
            raise UserError(
                f"No async channel found with code '{self._channel_code}'. "
                "Check Settings → Redis Broker → Channels."
            )

        task_vals = {
            'channel_id': channel.id,
            'model_name': self._recordset._name,
            'method_name': method_name,
            'record_ids': json.dumps(self._recordset.ids),
            'args_json': json.dumps(args, default=str),
            'kwargs_json': json.dumps(kwargs, default=str),
            'max_retries': self._max_retries,
            'retry_delay': self._retry_delay,
            'requested_by_user_id': self._env.user.id,
        }

        # Link to previous task for chaining
        if self._last_task:
            task_vals['parent_task_id'] = self._last_task.id

        task = task_model.sudo().create(task_vals)

        # If chaining, set the previous task's next_task_id
        if self._last_task:
            self._last_task.write({'next_task_id': task.id})
            # Don't dispatch chained tasks — they auto-dispatch on success
            self._last_task = task
            return task.with_env(self._env)

        task.action_dispatch()
        self._last_task = task
        return task.with_env(self._env)

    def then(self, model_name, method_name, record_ids=None,
             args=None, kwargs=None):
        """Chain a follow-up task to run after the previous one succeeds.

        Returns self for further chaining::

            builder = records.delayable()
            builder.validate_data()
            builder.then('sale.order', 'action_confirm', record_ids=[42])
            builder.then('sale.order', 'send_notification', record_ids=[42])
        """
        if not self._last_task:
            raise UserError(
                "Cannot chain: no previous task. Call a method first."
            )

        self._env['cb.async.task']._ensure_broker_enabled()

        channel = self._env['cb.async.channel'].sudo().search(
            [('code', '=', self._channel_code)], limit=1,
        )
        if not channel:
            raise UserError(
                f"No async channel found with code '{self._channel_code}'."
            )

        task = self._env['cb.async.task'].sudo().create({
            'channel_id': channel.id,
            'model_name': model_name,
            'method_name': method_name,
            'record_ids': json.dumps(record_ids or []),
            'args_json': json.dumps(args or [], default=str),
            'kwargs_json': json.dumps(kwargs or {}, default=str),
            'max_retries': self._max_retries,
            'retry_delay': self._retry_delay,
            'parent_task_id': self._last_task.id,
            'requested_by_user_id': self._env.user.id,
        })
        self._last_task.write({'next_task_id': task.id})
        self._last_task = task
        return self


class CbAsyncDelayableMixin(models.AbstractModel):
    """Mixin injected into ``base`` so every recordset gets ``.delayable()``."""

    _inherit = 'base'

    def delayable(self, channel='jobs', max_retries=3, retry_delay=60, **kw):
        """Return a delayable builder that dispatches method calls as async tasks.

        :param channel: channel code (e.g. ``'high'``, ``'cpu'``, ``'jobs'``)
        :param max_retries: number of automatic retries on failure
        :param retry_delay: seconds between retries
        :returns: ``_DelayableCallBuilder`` proxy
        """
        return _DelayableCallBuilder(
            self,
            channel_code=channel,
            max_retries=max_retries,
            retry_delay=retry_delay,
            **kw,
        )
