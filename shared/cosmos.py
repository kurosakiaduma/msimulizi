"""
shared/cosmos.py — typed Cosmos DB repositories for all six containers.

Design points:
- Each repository is a thin, typed wrapper around a ``CosmosContainer``
  interface so the same code runs against Azure Cosmos DB or the in-memory
  fake (``FakeCosmosContainer``) used by all tests.
- Writes use exponential backoff with 3 retries (base 0.5 s, cap 8 s).
- A background write buffer retries every 60 seconds for writes that fail
  all retries (Cosmos temporarily unavailable).
- ``AuditLogRepository`` is create-only; ``upsert`` raises ``PermissionError``
  to mirror the create-only RBAC role defined in the infra.
- ``OverlayCardRepository`` supports per-item TTL for spotlight cards.
"""

from __future__ import annotations

import asyncio
import copy
import dataclasses
import time
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import asdict
from typing import Any

from shared.models import (
    KeyMoment,
    MatchState,
    NarratorResponse,
    OverlayCard,
)


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _to_doc(obj: Any) -> dict[str, Any]:
    """Convert a dataclass (or plain dict) to a plain dict for storage."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    if isinstance(obj, dict):
        return dict(obj)
    raise TypeError(f"Cannot serialise {type(obj)!r} to a Cosmos document")


# ---------------------------------------------------------------------------
# Retry / backoff helpers
# ---------------------------------------------------------------------------

_BASE_DELAY = 0.5   # seconds
_MAX_DELAY = 8.0    # seconds
_MAX_RETRIES = 3


async def _with_backoff(coro_fn, *args, **kwargs):
    """
    Call ``coro_fn(*args, **kwargs)`` up to ``_MAX_RETRIES + 1`` times.

    Raises the last exception if every attempt fails.
    """
    delay = _BASE_DELAY
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return await coro_fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(delay)
                delay = min(delay * 2, _MAX_DELAY)
    raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Abstract container interface
# ---------------------------------------------------------------------------

class CosmosContainer(ABC):
    """Minimal interface for a single Cosmos DB container."""

    @abstractmethod
    async def upsert(self, doc: dict[str, Any]) -> None:
        """Create or replace a document (idempotent by id + partition key)."""

    @abstractmethod
    async def create(self, doc: dict[str, Any]) -> None:
        """Create a new document; raises ``ConflictError`` if id already exists."""

    @abstractmethod
    async def get(self, item_id: str, partition_key: str) -> dict[str, Any] | None:
        """Return the document or ``None`` if not found."""

    @abstractmethod
    async def query(
        self,
        query: str,
        parameters: list[dict[str, Any]] | None = None,
        partition_key: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return documents matching the query."""


class ConflictError(Exception):
    """Raised when a create operation targets an already-existing document."""


# ---------------------------------------------------------------------------
# In-memory fake (used by all tests — no Azure SDK needed)
# ---------------------------------------------------------------------------

class FakeCosmosContainer(CosmosContainer):
    """
    Thread-safe in-memory Cosmos DB container for offline, deterministic tests.

    ``fail_next_n`` can be set to make the next N write operations raise an
    exception so the buffer/retry logic can be exercised.
    """

    def __init__(self, *, create_only: bool = False) -> None:
        self._docs: dict[str, dict[str, Any]] = {}
        self.create_only = create_only
        self.fail_next_n: int = 0   # inject failures for tests

    def _check_inject_failure(self) -> None:
        if self.fail_next_n > 0:
            self.fail_next_n -= 1
            raise OSError("Simulated Cosmos failure")

    async def upsert(self, doc: dict[str, Any]) -> None:
        if self.create_only:
            raise PermissionError("Container is create-only; use create() instead")
        self._check_inject_failure()
        self._docs[doc["id"]] = copy.deepcopy(doc)

    async def create(self, doc: dict[str, Any]) -> None:
        self._check_inject_failure()
        if doc["id"] in self._docs:
            raise ConflictError(f"Document {doc['id']!r} already exists")
        self._docs[doc["id"]] = copy.deepcopy(doc)

    async def get(self, item_id: str, partition_key: str) -> dict[str, Any] | None:
        return copy.deepcopy(self._docs.get(item_id))

    async def query(
        self,
        query: str,
        parameters: list[dict[str, Any]] | None = None,
        partition_key: str | None = None,
    ) -> list[dict[str, Any]]:
        # Naive full-scan; sufficient for tests.
        params = {p["name"].lstrip("@"): p["value"] for p in (parameters or [])}
        docs = list(self._docs.values())

        # Filter by partition_key when supplied (checks "match_id" or "profile_key" fields).
        if partition_key is not None:
            docs = [
                d for d in docs
                if d.get("match_id") == partition_key
                or d.get("profile_key") == partition_key
            ]

        # Very basic parameter substitution for the subset of queries used internally.
        # For test correctness the fake checks only whether the param value
        # appears in the expected field rather than parsing the query string.
        for key, val in params.items():
            docs = [d for d in docs if d.get(key) == val]

        return [copy.deepcopy(d) for d in docs]

    # ------------------------------------------------------------------
    # Test helpers
    # ------------------------------------------------------------------

    @property
    def all_docs(self) -> list[dict[str, Any]]:
        """Return a snapshot of all stored documents (for assertions)."""
        return list(self._docs.values())

    def clear(self) -> None:
        self._docs.clear()


# ---------------------------------------------------------------------------
# Write buffer — retries every 60 s for permanently-failed writes
# ---------------------------------------------------------------------------

class WriteBuffer:
    """
    In-memory buffer for writes that fail all backoff retries.

    A background task (started once per process) flushes the buffer every
    ``retry_interval`` seconds.  Tests can call ``flush()`` directly.
    """

    def __init__(self, retry_interval: float = 60.0) -> None:
        self._queue: list[tuple[CosmosContainer, str, dict[str, Any]]] = []
        self._lock = asyncio.Lock()
        self._retry_interval = retry_interval
        self._task: asyncio.Task | None = None  # type: ignore[type-arg]

    def start(self) -> None:
        """Start the background flush loop (idempotent)."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()

    async def add(
        self,
        container: CosmosContainer,
        operation: str,   # "upsert" | "create"
        doc: dict[str, Any],
    ) -> None:
        async with self._lock:
            self._queue.append((container, operation, doc))

    async def flush(self) -> int:
        """
        Attempt to replay all buffered writes.

        Returns the number of items that still remain in the buffer after the
        flush (i.e. those that failed again).
        """
        async with self._lock:
            pending = list(self._queue)
            self._queue.clear()

        remaining: list[tuple[CosmosContainer, str, dict[str, Any]]] = []
        for container, operation, doc in pending:
            try:
                if operation == "upsert":
                    await container.upsert(doc)
                else:
                    await container.create(doc)
            except Exception:  # noqa: BLE001
                remaining.append((container, operation, doc))

        if remaining:
            async with self._lock:
                self._queue = remaining + self._queue

        return len(remaining)

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self._retry_interval)
            await self.flush()

    @property
    def pending_count(self) -> int:
        return len(self._queue)


# Shared buffer instance; imported by all repositories.
_buffer = WriteBuffer()


def get_write_buffer() -> WriteBuffer:
    return _buffer


# ---------------------------------------------------------------------------
# Base repository
# ---------------------------------------------------------------------------

class BaseRepository:
    """
    Common write helpers used by all repositories.

    On each write, ``_write_with_retry`` attempts the operation with
    exponential backoff.  If all retries are exhausted the document is
    added to the shared ``WriteBuffer`` for a later retry.
    """

    def __init__(self, container: CosmosContainer) -> None:
        self._container = container

    async def _write_with_retry(
        self,
        operation: str,
        doc: dict[str, Any],
    ) -> None:
        """
        Try ``operation`` (``"upsert"`` or ``"create"``) with backoff.

        Falls back to the write buffer on total failure.
        """
        try:
            if operation == "upsert":
                await _with_backoff(self._container.upsert, doc)
            else:
                await _with_backoff(self._container.create, doc)
        except Exception:  # noqa: BLE001
            await _buffer.add(self._container, operation, doc)

    async def get(self, item_id: str, partition_key: str) -> dict[str, Any] | None:
        return await self._container.get(item_id, partition_key)

    async def query(
        self,
        query: str,
        parameters: list[dict[str, Any]] | None = None,
        partition_key: str | None = None,
    ) -> list[dict[str, Any]]:
        return await self._container.query(query, parameters, partition_key)


# ---------------------------------------------------------------------------
# 1. MatchStateSnapshotRepository
# ---------------------------------------------------------------------------

class MatchStateSnapshotRepository(BaseRepository):
    """
    Upserts MatchState snapshots keyed by ``(match_id, sequence_number)``.

    Partition key: ``match_id``
    Document id:   ``"{match_id}:{sequence_number}"``

    Upserts are idempotent: re-writing the same (match_id, sequence_number)
    pair replaces the document with identical content.
    """

    async def upsert_snapshot(self, state: MatchState) -> None:
        doc = _to_doc(state)
        doc["id"] = f"{state.match_id}:{state.sequence_number}"
        # Cosmos partition key stored as a top-level field.
        doc.setdefault("match_id", state.match_id)
        await self._write_with_retry("upsert", doc)

    async def get_snapshot(
        self, match_id: str, sequence_number: int
    ) -> dict[str, Any] | None:
        return await self.get(f"{match_id}:{sequence_number}", match_id)


# ---------------------------------------------------------------------------
# 2. KeyMomentRepository
# ---------------------------------------------------------------------------

class KeyMomentRepository(BaseRepository):
    """
    Stores KeyMoment records.

    Partition key: ``match_id``
    Document id:   ``moment_id``
    """

    async def upsert_moment(self, moment: KeyMoment) -> None:
        doc = _to_doc(moment)
        doc["id"] = moment.moment_id
        doc.setdefault("match_id", moment.match_id)
        await self._write_with_retry("upsert", doc)

    async def get_moment(self, moment_id: str, match_id: str) -> dict[str, Any] | None:
        return await self.get(moment_id, match_id)

    async def list_moments(
        self,
        match_id: str,
        trigger_tags: list[str] | None = None,
        min_priority: int | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        docs = await self.query(
            "SELECT * FROM c WHERE c.match_id = @match_id",
            parameters=[{"name": "@match_id", "value": match_id}],
            partition_key=match_id,
        )
        if trigger_tags:
            docs = [
                d for d in docs
                if any(t in d.get("trigger_tags", []) for t in trigger_tags)
            ]
        if min_priority is not None:
            docs = [d for d in docs if d.get("priority_rank", 99) <= min_priority]
        return docs[:limit]


# ---------------------------------------------------------------------------
# 3. NarrationCacheRepository
# ---------------------------------------------------------------------------

class NarrationCacheRepository(BaseRepository):
    """
    Caches NarratorResponse records per Profile Key.

    Partition key: ``profile_key``
    Document id:   ``"{profile_key}:{moment_id}"``
    """

    async def upsert_response(self, response: NarratorResponse) -> None:
        doc = _to_doc(response)
        doc["id"] = f"{response.profile_key}:{response.moment_id}"
        doc.setdefault("profile_key", response.profile_key)
        await self._write_with_retry("upsert", doc)

    async def get_response(
        self, profile_key: str, moment_id: str
    ) -> dict[str, Any] | None:
        return await self.get(f"{profile_key}:{moment_id}", profile_key)


# ---------------------------------------------------------------------------
# 4. OverlayCardRepository  (TTL support for spotlight cards)
# ---------------------------------------------------------------------------

_TTL_SPOTLIGHT_SECONDS = 24 * 60 * 60   # 24 hours


class OverlayCardRepository(BaseRepository):
    """
    Stores OverlayCard records.

    Partition key: ``match_id``
    Document id:   ``card_id``

    Spotlight cards receive a per-item TTL of 24 hours via the
    ``ttl`` field; all other cards inherit the container default TTL
    (set to -1 = no expiry in the Bicep template).
    """

    async def upsert_card(self, card: OverlayCard, *, ttl: int | None = None) -> None:
        doc = _to_doc(card)
        doc["id"] = card.card_id
        doc.setdefault("match_id", card.match_id)
        if card.card_type == "player_spotlight":
            doc["ttl"] = _TTL_SPOTLIGHT_SECONDS
        elif ttl is not None:
            doc["ttl"] = ttl
        await self._write_with_retry("upsert", doc)

    async def get_card(self, card_id: str, match_id: str) -> dict[str, Any] | None:
        return await self.get(card_id, match_id)

    async def list_cards(
        self,
        match_id: str,
        profile_key: str | None = None,
        after_match_clock: dict | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        docs = await self.query(
            "SELECT * FROM c WHERE c.match_id = @match_id",
            parameters=[{"name": "@match_id", "value": match_id}],
            partition_key=match_id,
        )
        if profile_key:
            docs = [d for d in docs if d.get("profile_key") == profile_key]
        return docs[:limit]


# ---------------------------------------------------------------------------
# 5. AuditLogRepository  (create-only)
# ---------------------------------------------------------------------------

class AuditLogRepository(BaseRepository):
    """
    Append-only audit log.

    Partition key: ``match_id``
    Document id:   ``log_id`` (caller-supplied unique ID)

    ``upsert_entry`` is intentionally absent.  Callers must use
    ``create_entry``; any attempt to overwrite an existing entry raises
    ``ConflictError`` (mirrors the create-only RBAC role in Azure).
    """

    async def create_entry(self, entry: dict[str, Any]) -> None:
        """
        Append a new audit entry.

        ``entry`` must contain ``"id"`` and ``"match_id"``.
        Raises ``ConflictError`` if the id already exists.
        Raises ``PermissionError`` if the underlying container disallows upserts.
        """
        if "id" not in entry:
            raise ValueError("Audit entry must contain an 'id' field")
        if "match_id" not in entry:
            raise ValueError("Audit entry must contain a 'match_id' field")
        await self._write_with_retry("create", dict(entry))

    async def list_entries(
        self, match_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        return await self.query(
            "SELECT * FROM c WHERE c.match_id = @match_id",
            parameters=[{"name": "@match_id", "value": match_id}],
            partition_key=match_id,
        )

    # Explicitly block upsert at the Python level.
    async def _write_with_retry(self, operation: str, doc: dict[str, Any]) -> None:
        if operation == "upsert":
            raise PermissionError("AuditLogRepository is create-only")
        # ConflictError is a permanent error — don't catch it or buffer it.
        try:
            await _with_backoff(self._container.create, doc)
        except ConflictError:
            raise
        except Exception:  # noqa: BLE001
            await _buffer.add(self._container, "create", doc)


# ---------------------------------------------------------------------------
# 6. CorrectionsRepository
# ---------------------------------------------------------------------------

class CorrectionsRepository(BaseRepository):
    """
    Stores viewer correction submissions and reviewer approvals.

    Partition key: ``match_id``
    Document id:   caller-supplied ``id`` field
    """

    async def create_correction(self, correction: dict[str, Any]) -> None:
        if "id" not in correction:
            raise ValueError("Correction must contain an 'id' field")
        if "match_id" not in correction:
            raise ValueError("Correction must contain a 'match_id' field")
        await self._write_with_retry("create", dict(correction))

    async def update_correction(self, correction_id: str, match_id: str, patch: dict[str, Any]) -> None:
        doc = await self.get(correction_id, match_id)
        if doc is None:
            raise KeyError(f"Correction {correction_id!r} not found")
        doc.update(patch)
        await self._write_with_retry("upsert", doc)

    async def list_corrections(
        self, match_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        return await self.query(
            "SELECT * FROM c WHERE c.match_id = @match_id",
            parameters=[{"name": "@match_id", "value": match_id}],
            partition_key=match_id,
        )


# ---------------------------------------------------------------------------
# Repository factory  (wires real or fake containers)
# ---------------------------------------------------------------------------

class CosmosRepositories:
    """
    Container for all six typed repositories.

    Pass ``containers=None`` to use the in-memory fakes (default for tests).
    Pass a dict of ``CosmosContainer`` instances keyed by container name to
    use real Azure Cosmos DB clients.

    Container names:
        "match_state_snapshots", "key_moments", "narration_cache",
        "overlay_cards", "audit_log", "corrections"
    """

    CONTAINER_NAMES = (
        "match_state_snapshots",
        "key_moments",
        "narration_cache",
        "overlay_cards",
        "audit_log",
        "corrections",
    )

    def __init__(
        self,
        containers: dict[str, CosmosContainer] | None = None,
    ) -> None:
        if containers is None:
            containers = {name: FakeCosmosContainer() for name in self.CONTAINER_NAMES}
            # audit_log uses a create-only fake
            containers["audit_log"] = FakeCosmosContainer(create_only=True)

        self.match_state_snapshots = MatchStateSnapshotRepository(
            containers["match_state_snapshots"]
        )
        self.key_moments = KeyMomentRepository(containers["key_moments"])
        self.narration_cache = NarrationCacheRepository(containers["narration_cache"])
        self.overlay_cards = OverlayCardRepository(containers["overlay_cards"])
        self.audit_log = AuditLogRepository(containers["audit_log"])
        self.corrections = CorrectionsRepository(containers["corrections"])
