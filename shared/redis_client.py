# shared/redis_client.py
# Centralized Redis connection management
import os
import redis.asyncio as redis

# Default Redis URL - use IP for host compatibility (dashboard runs outside Docker)
# Docker containers can also reach this IP via the bridge network
REDIS_URL = os.getenv("REDIS_URL", "redis://172.22.0.2:6379/0")

# Connection pool (singleton)
_pool = None

async def get_redis() -> redis.Redis:
    """Get a Redis client from the connection pool."""
    global _pool
    if _pool is None:
        _pool = redis.ConnectionPool.from_url(REDIS_URL, decode_responses=True)
    return redis.Redis(connection_pool=_pool)

async def get_redis_client() -> redis.Redis:
    """Alias for get_redis() - backwards compatibility."""
    return await get_redis()

def get_redis_sync() -> redis.Redis:
    """Get a synchronous Redis client (for scripts)."""
    return redis.from_url(REDIS_URL, decode_responses=True)
