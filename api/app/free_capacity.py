"""Concurrency control for the free tier: a slot to hold, and a queue to wait in.

A GPU serves a bounded number of generations at once. Beyond that, more concurrent requests
do not produce more throughput — they produce the same throughput with worse latency for
everyone, and eventually an out-of-memory on the node.

So requests WAIT rather than fail. Streaming is what makes that acceptable: a caller who
waits three seconds for a slot then sees tokens immediately experiences a slow start, where
the same caller told "503, try again" experiences a broken product.

But an unbounded queue is just a slower way to fall over — it converts a load spike into
unbounded memory and a queue of callers who all left long ago. So the queue has a depth, and
past that depth the honest answer really is "come back later", with a Retry-After.

Per-process, like ``dispatch._inflight`` and for the same reason: a slot is held by a
coroutine in this process, so only this process knows. Across replicas each enforces its own
cap, which means the effective ceiling is cap x replicas — deliberately, since the point is
to bound what one process can push at a node, and the node enforces its own limit besides.
"""

import asyncio
from contextlib import asynccontextmanager


class CapacityFull(RuntimeError):
    """The queue is at depth. The caller should be told to come back, not left waiting."""


class FreeCapacity:
    """A semaphore with a bounded waiting room."""

    def __init__(self, *, slots: int, queue_depth: int) -> None:
        self._sem = asyncio.Semaphore(slots)
        self._slots = slots
        self._queue_depth = queue_depth
        self._waiting = 0

    @property
    def waiting(self) -> int:
        return self._waiting

    @property
    def slots(self) -> int:
        return self._slots

    @asynccontextmanager
    async def slot(self):
        """Hold a generation slot, queueing if necessary.

        The waiting count is incremented BEFORE the await and decremented in a finally, so a
        caller who disconnects while queued releases their place immediately rather than
        holding it until they are served. Without that, a burst of abandoned requests keeps
        the queue full against callers who are still there.
        """
        if self._waiting >= self._queue_depth:
            raise CapacityFull(f"{self._waiting} already waiting")
        self._waiting += 1
        try:
            await self._sem.acquire()
        finally:
            self._waiting -= 1
        try:
            yield
        finally:
            self._sem.release()


_capacity: FreeCapacity | None = None


def get_capacity(*, slots: int, queue_depth: int) -> FreeCapacity:
    """The process-wide capacity gate, built on first use from settings."""
    global _capacity
    if _capacity is None:
        _capacity = FreeCapacity(slots=slots, queue_depth=queue_depth)
    return _capacity


def reset_capacity() -> None:
    """Drop the gate so a test can build a fresh one. Nothing in production needs this."""
    global _capacity
    _capacity = None
