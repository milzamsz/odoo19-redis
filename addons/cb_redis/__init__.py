# Part of CB Redis. See LICENSE file for full copyright and licensing details.

from . import models
from . import async_broker
from . import redis_session_store

# Patch session_store on http.Application at import time.
# This runs on every server start (install AND restart), ensuring
# the RedisSessionStore is always in place when the module is loaded.
redis_session_store.install_redis_session_store()
