"""
shared/pubsub.py — asyncio pub/sub bus for the Msimulizi pipeline.

Provides a single ``PubSub`` instance shared across the process.  Three
operations are supported:

* ``publish(topic, payload)``   — broadcast to all subscribers; retain as latest
* ``subscribe(topic)``          — async iterator that yields payloads as they arrive
* ``latest(topic)``             — return the most recent retained payload (for MCP)

Design notes
------------
- Each subscriber gets its own ``asyncio.Queue`` so slow consumers cannot
  block fast ones (fan-out by copy).
- ``latest`` stores the last payload per topic in a plain dict; it never
  blocks and is safe to call from synchronous code that has the event loop
  available.
- Subscriber cleanup: ``_Subscription`` implements the ``AsyncIterator``
  protocol directly (``__aiter__`` / ``__anext__`` / ``aclose``).  Cleanup runs
  via weakref.finalize, so it fires on aclose(), on shutdown, or as soon as the
  subscription is garbage collected (including after break in async for).
- All state is per-instance, making unit testing straightforward.
"""

from __future__ import annotations

import asyncio
import weakref
from collections import defaultdict
from typing import Any, AsyncIterator


# Internal sentinel: placed in a subscriber's queue to signal shutdown.
_STOP = object()


def _remove_queue(registry, topic, queue) -> None:
    try:
        registry[topic].remove(queue)
    except ValueError:
        pass


class _Subscription:
    def __init__(self, topic: str, registry: dict[str, list[asyncio.Queue]]) -> None:
        self._topic = topic
        self._queue: asyncio.Queue[Any] = asyncio.Queue()
        self._closed = False
        registry[topic].append(self._queue)
        # Runs at most once: on aclose(), on _STOP, or when this object is collected.
        self._finalizer = weakref.finalize(
            self, _remove_queue, registry, topic, self._queue
        )

    def __aiter__(self) -> AsyncIterator[Any]:
        return self  # type: ignore[return-value]

    async def __anext__(self) -> Any:
        if self._closed:
            raise StopAsyncIteration
        payload = await self._queue.get()
        if payload is _STOP:
            self._closed = True
            self._finalizer()
            raise StopAsyncIteration
        return payload

    async def aclose(self) -> None:
        self._closed = True
        self._finalizer()


class PubSub:
    """Lightweight asyncio pub/sub bus with retained latest-value per topic."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)
        self._latest: dict[str, Any] = {}

    async def publish(self, topic: str, payload: Any) -> None:
        """Broadcast *payload* to every current subscriber and retain as latest."""
        self._latest[topic] = payload
        for queue in list(self._subscribers[topic]):
            await queue.put(payload)

    def subscribe(self, topic: str) -> _Subscription:
        """Return a subscription that yields payloads published to *topic*."""
        return _Subscription(topic, self._subscribers)

    def latest(self, topic: str) -> Any:
        """Return the most recently published payload for *topic*, or ``None``."""
        return self._latest.get(topic)

    def subscriber_count(self, topic: str) -> int:
        """Return the number of active subscribers for *topic*."""
        return len(self._subscribers[topic])
