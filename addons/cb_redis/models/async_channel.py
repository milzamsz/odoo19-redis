# Part of CB Redis. See LICENSE file for full copyright and licensing details.

import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class CbAsyncChannel(models.Model):
    """Configurable Redis Streams priority channel.

    Each channel maps to a Redis stream key and belongs to a consumer
    group.  Workers read from one or more channels based on their
    configuration.
    """

    _name = 'cb.async.channel'
    _description = 'Async Broker Channel'
    _order = 'sequence, id'

    name = fields.Char(required=True)
    code = fields.Char(
        string="Channel Code",
        required=True,
        help="Short identifier used in the delayable API (e.g. 'high', 'io').",
    )
    stream_key = fields.Char(
        string="Stream Key",
        compute='_compute_stream_key',
        help="Full Redis stream key (auto-computed from prefix + code).",
    )
    priority = fields.Selection(
        selection=[
            ('0', 'Critical'),
            ('5', 'High'),
            ('10', 'Normal'),
            ('15', 'Low (I/O)'),
            ('20', 'Low (CPU)'),
            ('25', 'Background'),
        ],
        default='10',
        required=True,
    )
    consumer_group = fields.Char(
        default='cb-workers',
        required=True,
        help="Redis consumer group name.  Workers sharing this group "
             "cooperatively consume the stream.",
    )
    max_workers = fields.Integer(
        default=0,
        help="Advisory: max concurrent workers for this channel (0 = unlimited).",
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    task_ids = fields.One2many('cb.async.task', 'channel_id', string="Tasks")
    task_count = fields.Integer(compute='_compute_task_count')
    _code_uniq = models.Constraint(
        'UNIQUE(code)',
        'Channel code must be unique.',
    )

    # ------------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------------

    @api.depends('code')
    def _compute_stream_key(self):
        prefix = self.env['ir.config_parameter'].sudo().get_param(
            'cb_redis.stream_prefix', 'cb',
        )
        for rec in self:
            rec.stream_key = f"{prefix}:{rec.code}" if rec.code else ''

    def _compute_task_count(self):
        for rec in self:
            rec.task_count = len(rec.task_ids)
