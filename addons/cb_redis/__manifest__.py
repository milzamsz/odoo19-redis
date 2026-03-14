{
    "name": "CB Redis (Session Store + Async Broker)",
    "version": "19.0.2.0.0",
    "depends": ["base_setup"],
    "author": "CB",
    "license": "LGPL-3",
    "description": """
CB Redis — Session Store & Async Broker
========================================

Unified Redis integration for Odoo:

1. **Session Store** — Store HTTP sessions in Redis for multi-server
   and containerized deployments.

2. **Async Broker** — Redis Streams message broker for executing
   heavy workloads asynchronously via an external worker process.

Features:
- Priority queue channels (high, normal, I/O, CPU, report)
- Job chaining (task A → task B → task C)
- Retry policy with configurable max retries and backoff
- Dead-job reclaim (XAUTOCLAIM for stalled consumers)
- Developer-friendly ``.delayable()`` API on every recordset
- Standalone worker process (Docker-ready)
""",
    "summary": "Redis session storage + async job broker with priority queues, chaining & retry",
    "category": "Tools",
    "auto_install": False,
    "installable": True,
    "application": True,
    "external_dependencies": {
        "python": ["redis"],
    },
    "data": [
        # Security (load first)
        "security/ir.model.access.csv",
        # Data
        "data/async_channel_data.xml",
        # Views
        "views/res_config_settings_views.xml",
        "views/async_channel_views.xml",
        "views/async_task_views.xml",
        "views/menu.xml",
    ],
}
