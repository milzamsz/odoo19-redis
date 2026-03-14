# Part of CB Redis. See LICENSE file for full copyright and licensing details.

from datetime import timedelta
import json
import logging
import traceback
import time

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class CbAsyncTask(models.Model):
    """Async job record dispatched to Redis Streams.

    Lifecycle:
        pending → queued → running → done | failed
                                     ↓
                                 (retry) → queued → …
    """

    _name = 'cb.async.task'
    _description = 'Async Broker Task'
    _order = 'date_queued desc, id desc'
    _rec_name = 'display_name'

    # -- Identification ----------------------------------------------------

    display_name = fields.Char(compute='_compute_display_name', store=True)
    channel_id = fields.Many2one(
        'cb.async.channel',
        string="Channel",
        required=True,
        default=lambda self: self._default_channel_id(),
        ondelete='restrict',
    )

    state = fields.Selection(
        selection=[
            ('pending', 'Pending'),
            ('queued', 'Queued'),
            ('running', 'Running'),
            ('done', 'Done'),
            ('failed', 'Failed'),
            ('cancelled', 'Cancelled'),
        ],
        default='pending',
        required=True,
        index=True,
    )

    # -- What to execute ---------------------------------------------------

    model_name = fields.Char(required=True, index=True)
    method_name = fields.Char(required=True)
    record_ids = fields.Char(
        default='[]',
        help="JSON list of record IDs to browse before calling the method.",
    )
    args_json = fields.Text(default='[]')
    kwargs_json = fields.Text(default='{}')
    requested_by_user_id = fields.Many2one(
        'res.users',
        string="Requested By",
        default=lambda self: self.env.user,
        readonly=True,
        index=True,
    )

    # -- Result / error ----------------------------------------------------

    result_json = fields.Text(readonly=True)
    error_message = fields.Text(readonly=True)
    traceback_text = fields.Text(readonly=True)

    # -- Retry policy ------------------------------------------------------

    max_retries = fields.Integer(default=3)
    retry_count = fields.Integer(default=0, readonly=True)
    retry_delay = fields.Integer(
        default=60,
        help="Seconds to wait before retrying a failed task.",
    )
    date_next_attempt = fields.Datetime(
        string="Next Attempt At",
        readonly=True,
        index=True,
    )

    # -- Chaining ----------------------------------------------------------

    next_task_id = fields.Many2one(
        'cb.async.task',
        string="Next Task (Chain)",
        ondelete='set null',
        help="Task to dispatch automatically after this one succeeds.",
    )
    parent_task_id = fields.Many2one(
        'cb.async.task',
        string="Parent Task",
        ondelete='set null',
    )

    # -- Redis metadata ----------------------------------------------------

    stream_message_id = fields.Char(readonly=True)
    priority = fields.Selection(related='channel_id.priority', store=True)

    # -- Dates & duration --------------------------------------------------

    date_queued = fields.Datetime(readonly=True)
    date_started = fields.Datetime(readonly=True)
    date_done = fields.Datetime(readonly=True)
    duration = fields.Float(
        compute='_compute_duration',
        string="Duration (s)",
        help="Execution duration in seconds.",
    )

    # -- Logs --------------------------------------------------------------

    log_ids = fields.One2many('cb.async.task.log', 'task_id', string="Logs")

    # ------------------------------------------------------------------
    # Defaults
    # ------------------------------------------------------------------

    def _default_channel_id(self):
        return self.env['cb.async.channel'].search(
            [('code', '=', 'jobs')], limit=1,
        )

    @api.model
    def _is_broker_enabled(self):
        icp = self.env['ir.config_parameter'].sudo()
        return icp.get_param('cb_redis.broker_enable', 'False') == 'True'

    @api.model
    def _ensure_broker_enabled(self):
        if self._is_broker_enabled():
            return
        raise UserError(
            "Async broker is disabled. Enable it in Settings before dispatching tasks."
        )

    @api.model
    def _claim_due_retry_task_ids(self, limit=50):
        """Claim retry-ready tasks without double-dispatching across workers."""
        self.env.cr.execute(
            f"""
                SELECT id
                  FROM {self._table}
                 WHERE state = %s
                   AND date_next_attempt IS NOT NULL
                   AND date_next_attempt <= %s
                 ORDER BY date_next_attempt, id
                 FOR UPDATE SKIP LOCKED
                 LIMIT %s
            """,
            ['pending', fields.Datetime.now(), limit],
        )
        return [row[0] for row in self.env.cr.fetchall()]

    # ------------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------------

    @api.depends('model_name', 'method_name')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = (
                f"[{rec.id or 'new'}] {rec.model_name}.{rec.method_name}"
            )

    @api.depends('date_started', 'date_done')
    def _compute_duration(self):
        for rec in self:
            if rec.date_started and rec.date_done:
                delta = rec.date_done - rec.date_started
                rec.duration = delta.total_seconds()
            else:
                rec.duration = 0.0

    def _check_public_method(self):
        self.ensure_one()
        if self.method_name.startswith('_'):
            raise UserError(
                f"Cannot dispatch private method '{self.method_name}'."
            )

    def _get_execution_user(self):
        self.ensure_one()
        return self.requested_by_user_id or self.create_uid or self.env.user

    def _get_execution_context(self):
        self.ensure_one()
        exec_user = self._get_execution_user()
        context = dict(self.env.context)
        if exec_user and exec_user.exists():
            context.setdefault('allowed_company_ids', exec_user.company_ids.ids)
            if exec_user.company_id:
                context.setdefault('company_id', exec_user.company_id.id)
        return context

    def _get_target_recordset(self):
        self.ensure_one()
        self._check_public_method()
        exec_user = self._get_execution_user()
        exec_context = self._get_execution_context()
        Model = self.env[self.model_name].with_context(exec_context)
        if exec_user:
            Model = Model.with_user(exec_user)
        record_ids = json.loads(self.record_ids or '[]')
        return Model.browse(record_ids).exists() if record_ids else Model

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_dispatch(self):
        """Publish this task to its Redis Stream channel."""
        self.ensure_one()
        self._ensure_broker_enabled()
        self._check_public_method()
        if self.state not in ('pending', 'failed'):
            raise UserError(
                f"Cannot dispatch task in state '{self.state}'. "
                "Only pending or failed tasks can be dispatched."
            )

        from ..async_broker import publish_task, ensure_consumer_group

        channel = self.channel_id
        ensure_consumer_group(channel.stream_key, channel.consumer_group)

        msg_id = publish_task(
            stream_key=channel.stream_key,
            task_id=self.id,
            task_data={
                'model': self.model_name,
                'method': self.method_name,
            },
        )
        self.write({
            'state': 'queued',
            'stream_message_id': msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id),
            'date_queued': fields.Datetime.now(),
            'date_next_attempt': False,
            'error_message': False,
            'traceback_text': False,
        })
        self._log('info', f"Dispatched to {channel.stream_key} (msg={self.stream_message_id})")

    def action_retry(self):
        """Reset a failed task and re-dispatch."""
        self.ensure_one()
        if self.state != 'failed':
            raise UserError("Only failed tasks can be retried.")
        if self.retry_count >= self.max_retries:
            raise UserError(
                f"Max retries ({self.max_retries}) reached. "
                "Increase the limit or investigate the root cause."
            )
        self.write({
            'state': 'pending',
            'retry_count': self.retry_count + 1,
            'date_next_attempt': False,
            'error_message': False,
            'traceback_text': False,
            'result_json': False,
        })
        self._log('info', f"Retry {self.retry_count}/{self.max_retries}")
        self.action_dispatch()

    def action_cancel(self):
        """Cancel a pending or queued task."""
        for rec in self:
            if rec.state in ('pending', 'queued', 'failed'):
                rec.write({
                    'state': 'cancelled',
                    'date_next_attempt': False,
                })
                rec._log('info', 'Task cancelled')

    def action_requeue(self):
        """Re-queue a cancelled or done task as a new dispatch."""
        self.ensure_one()
        self.write({
            'state': 'pending',
            'retry_count': 0,
            'error_message': False,
            'traceback_text': False,
            'result_json': False,
            'date_queued': False,
            'date_started': False,
            'date_done': False,
            'date_next_attempt': False,
        })
        self.action_dispatch()

    # ------------------------------------------------------------------
    # Execution (called by external worker)
    # ------------------------------------------------------------------

    def _execute(self):
        """Execute the task: call ``model.method(*args, **kwargs)``.

        Called by the worker process inside a proper Odoo environment.
        Handles success, failure, retry, and chaining.
        """
        self.ensure_one()
        self.write({
            'state': 'running',
            'date_started': fields.Datetime.now(),
            'date_next_attempt': False,
        })
        self._log('info', 'Execution started')

        try:
            args = json.loads(self.args_json or '[]')
            kwargs = json.loads(self.kwargs_json or '{}')
            target = self._get_target_recordset()
            if not hasattr(target, self.method_name):
                raise UserError(
                    f"Method '{self.method_name}' was not found on '{self.model_name}'."
                )
            result = getattr(target, self.method_name)(*args, **kwargs)

            # Serialize result if possible
            try:
                result_str = json.dumps(result, default=str)
            except (TypeError, ValueError):
                result_str = str(result)

            self.write({
                'state': 'done',
                'result_json': result_str,
                'date_done': fields.Datetime.now(),
            })
            self._log('info', 'Execution completed successfully')

            # Chaining
            try:
                self._handle_chain()
            except Exception as chain_exc:
                self._log('warning', f"Follow-up dispatch failed: {chain_exc}")
                _logger.exception(
                    "Task %s follow-up dispatch failed", self.id,
                )

        except Exception as exc:
            tb = traceback.format_exc()
            vals = {
                'state': 'failed',
                'error_message': str(exc),
                'traceback_text': tb,
                'date_done': fields.Datetime.now(),
            }
            self._log('error', f"Execution failed: {exc}")
            _logger.error("Task %s failed: %s\n%s", self.id, exc, tb)

            # Auto-retry if within limits
            if self.retry_count < self.max_retries:
                retry_seconds = max(self.retry_delay, 0)
                next_attempt = fields.Datetime.now() + timedelta(seconds=retry_seconds)
                vals.update({
                    'state': 'pending',
                    'retry_count': self.retry_count + 1,
                    'date_next_attempt': next_attempt,
                })
                self._log(
                    'warning',
                    f"Retry {vals['retry_count']}/{self.max_retries} scheduled for {next_attempt}",
                )
            else:
                vals['date_next_attempt'] = False

            self.write(vals)

    def _handle_chain(self):
        """Dispatch the next task in the chain if one is configured."""
        self.ensure_one()
        if self.next_task_id and self.next_task_id.state == 'pending':
            self._log('info', f"Chaining → task {self.next_task_id.id}")
            self.next_task_id.action_dispatch()

    # ------------------------------------------------------------------
    # Logging helper
    # ------------------------------------------------------------------

    def _log(self, level, message):
        """Write a log entry for this task."""
        self.ensure_one()
        self.env['cb.async.task.log'].sudo().create({
            'task_id': self.id,
            'level': level,
            'message': message,
        })
