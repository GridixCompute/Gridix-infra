"""Shared async Redis client and the job-queue key namespace."""

import redis.asyncio as redis

from app.config import get_settings

# Redis list acting as the FIFO job queue. Scheduler brpop/lpops; API rpushes.
JOB_QUEUE_KEY = "gridix:jobs:queue"

_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    """Return the process-wide async Redis client, created on first use."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = redis.from_url(settings.redis_url, decode_responses=True)
    return _client


async def enqueue_job(job_id: str) -> None:
    """Push a job id onto the tail of the FIFO queue for the scheduler to pick up."""
    await get_redis().rpush(JOB_QUEUE_KEY, job_id)


async def dequeue_job(timeout: int = 5) -> str | None:
    """Block up to ``timeout`` seconds for the next queued job id, or return None."""
    result = await get_redis().blpop([JOB_QUEUE_KEY], timeout=timeout)
    if result is None:
        return None
    _key, job_id = result
    return job_id


async def queue_depth() -> int:
    """Return the number of job ids currently waiting on the queue."""
    return int(await get_redis().llen(JOB_QUEUE_KEY))


async def close_redis() -> None:
    """Close the Redis client on shutdown."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
