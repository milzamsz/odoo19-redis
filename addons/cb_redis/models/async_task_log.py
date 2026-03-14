# Part of CB Redis. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class CbAsyncTaskLog(models.Model):
    """Execution log entry for an async task."""

    _name = 'cb.async.task.log'
    _description = 'Async Task Log'
    _order = 'create_date desc, id desc'

    task_id = fields.Many2one(
        'cb.async.task',
        required=True,
        ondelete='cascade',
        index=True,
    )
    level = fields.Selection(
        selection=[
            ('info', 'Info'),
            ('warning', 'Warning'),
            ('error', 'Error'),
        ],
        default='info',
        required=True,
    )
    message = fields.Text()
