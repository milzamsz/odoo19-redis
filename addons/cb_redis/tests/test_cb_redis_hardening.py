import json
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCbRedisHardening(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.icp = cls.env["ir.config_parameter"].sudo()
        cls.company = cls.env.company
        cls.channel = cls.env["cb.async.channel"].search([("code", "=", "jobs")], limit=1)
        cls.partner = cls.env["res.partner"].create({"name": "CB Redis Hardening Partner"})
        cls.internal_user = cls.env["res.users"].with_context(no_reset_password=True).create(
            {
                "name": "CB Redis Worker User",
                "login": "cb.redis.worker.user",
                "email": "cb.redis.worker.user@example.com",
                "company_id": cls.company.id,
                "company_ids": [(6, 0, [cls.company.id])],
                "group_ids": [(6, 0, [cls.env.ref("base.group_user").id])],
            }
        )

    def tearDown(self):
        self.icp.set_param("cb_redis.broker_enable", "False")
        self.icp.set_param("cb_redis.stream_prefix", "cb")
        self.env.invalidate_all()
        super().tearDown()

    def test_01_delayable_requires_enabled_broker(self):
        self.icp.set_param("cb_redis.broker_enable", "False")
        task_count = self.env["cb.async.task"].sudo().search_count([])

        with self.assertRaises(UserError):
            self.partner.delayable(channel="jobs").read()

        self.assertEqual(self.env["cb.async.task"].sudo().search_count([]), task_count)

    def test_02_delayable_records_requesting_user(self):
        self.icp.set_param("cb_redis.broker_enable", "True")
        existing_ids = set(self.env["cb.async.task"].sudo().search([]).ids)

        with patch("odoo.addons.cb_redis.async_broker.ensure_consumer_group"), patch(
            "odoo.addons.cb_redis.async_broker.publish_task", return_value=b"1-0"
        ):
            self.partner.with_user(self.internal_user).delayable(channel="jobs").read()

        task = self.env["cb.async.task"].sudo().search(
            [("id", "not in", list(existing_ids))],
            order="id desc",
            limit=1,
        )
        self.assertTrue(task)
        self.assertEqual(task.requested_by_user_id, self.internal_user)
        self.assertEqual(task.state, "queued")

    def test_03_action_dispatch_requires_enabled_broker(self):
        self.icp.set_param("cb_redis.broker_enable", "False")
        task = self.env["cb.async.task"].sudo().create(
            {
                "channel_id": self.channel.id,
                "model_name": "res.partner",
                "method_name": "read",
                "record_ids": json.dumps([self.partner.id]),
                "requested_by_user_id": self.internal_user.id,
            }
        )

        with self.assertRaises(UserError):
            task.action_dispatch()

    def test_04_stream_key_tracks_prefix_changes(self):
        self.icp.set_param("cb_redis.stream_prefix", "cb")
        self.channel.invalidate_recordset(["stream_key"])
        self.assertEqual(self.channel.stream_key, "cb:jobs")

        self.icp.set_param("cb_redis.stream_prefix", "cbhard")
        self.channel.invalidate_recordset(["stream_key"])
        self.assertEqual(self.channel.stream_key, "cbhard:jobs")

    def test_05_failed_execute_schedules_retry(self):
        task = self.env["cb.async.task"].sudo().create(
            {
                "channel_id": self.channel.id,
                "model_name": "res.partner",
                "method_name": "missing_method",
                "record_ids": json.dumps([self.partner.id]),
                "requested_by_user_id": self.internal_user.id,
                "max_retries": 2,
                "retry_delay": 120,
            }
        )

        task._execute()

        self.assertEqual(task.state, "pending")
        self.assertEqual(task.retry_count, 1)
        self.assertTrue(task.date_next_attempt)
        self.assertIn("missing_method", task.error_message)

    def test_06_execution_target_uses_requested_user(self):
        task = self.env["cb.async.task"].sudo().create(
            {
                "channel_id": self.channel.id,
                "model_name": "res.partner",
                "method_name": "read",
                "record_ids": json.dumps([self.partner.id]),
                "requested_by_user_id": self.internal_user.id,
            }
        )

        target = task._get_target_recordset()

        self.assertEqual(target.env.uid, self.internal_user.id)
        self.assertFalse(target.env.su)
        self.assertEqual(target.ids, self.partner.ids)

