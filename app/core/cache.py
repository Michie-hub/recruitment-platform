"""
Redis cache client — cache-aside pattern for read-heavy public endpoints.

Why cache-aside (check cache, fall through to DB on miss, populate cache)
rather than write-through: reads (browsing job listings) vastly outnumber
writes (posting a job) on a recruitment platform, so this workload is well
suited to it — most requests hit a fast Redis lookup instead of Postgres.
"""

import json
from typing import Any

import redis

from app.core.config import settings

_redis_client = redis.Redis(
    host=settings.redis_host, port=settings.redis_port, decode_responses=True
)

DEFAULT_TTL_SECONDS = 60


def get_json(key: str) -> Any | None:
    """Fetch and deserialize a cached value. Returns None on a cache miss."""
    raw = _redis_client.get(key)
    return json.loads(raw) if raw is not None else None


def set_json(key: str, value: Any, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
    """Serialize and cache a value with a TTL — the backstop for invalidation."""
    _redis_client.set(key, json.dumps(value), ex=ttl_seconds)


def get_list_version(namespace: str) -> int:
    """
    Returns the current version counter for a cache namespace.

    Every list-cache key in this namespace embeds the version; bumping it
    (on any write) instantly makes every previously-cached key variant
    unreachable, without needing to scan Redis and delete keys individually —
    old entries simply expire via TTL once nothing requests them anymore.
    """
    raw = _redis_client.get(f"{namespace}:version")
    return int(raw) if raw is not None else 0


def bump_list_version(namespace: str) -> None:
    """Invalidate every cached list-result variant in this namespace."""
    _redis_client.incr(f"{namespace}:version")
