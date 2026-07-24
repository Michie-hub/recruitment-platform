"""
Rate limiter configuration (slowapi, Redis-backed).

Redis-backed rather than in-memory: an in-memory counter lives inside a
single Python process, so it would under-enforce the moment more than one
app worker/instance is running (limit becomes limit x worker_count).
Redis-backed counters are shared across all instances.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

limiter = Limiter(key_func=get_remote_address, storage_uri=settings.redis_url)
