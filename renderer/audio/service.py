
"""
Production audio orchestration for Msimulizi.

Responsibilities:
- Validate and normalize AudioRequest values.
- Build deterministic content-addressed cache keys.
- Reuse in-memory and persistent audio.
- Coalesce concurrent identical requests into one synthesis.
- Enforce concurrency limits and synthesis timeouts.
- Retry transient speech-engine errors.
- Apply a lightweight circuit breaker.
- Check the speech budget only before real synthesis.
- Publish audio_update without invalidating the overlay caption.
- Record audio metrics where the metrics backend supports them.

The service is independent of Azure: any implementation of SpeechEngine and
AudioStore can be injected for development, testing, or production.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time

from collections import OrderedDict
from dataclasses import replace
from typing import Any, Awaitable, Callable

from .contract import (
    AudioRequest,
    AudioResult,
    AudioStore,
    BudgetGuard,
    EMOTIONS,
    LANGUAGES,
    SpeechEngine,
    SpeechError,
    StoredAudio,
)
from .emotion import PROSODY_VERSION, clamp01
from .speech_text import TTS_TEXT_VERSION, prepare_tts_text
from .metrics import NullMetrics


logger = logging.getLogger("msimulizi.audio")


# Return signature for one shared in-flight render.
_ProduceResult = tuple[StoredAudio | None, str, str | None]


def cache_key(req: AudioRequest, engine: SpeechEngine) -> str:
    """
    Build a stable cache key containing every setting that can change speech.

    Intentionally excluded:
        narration_id, match_minute, priority

    These are event metadata and do not change the synthesized sound.

    Included:
        engine name/version, prosody and speech-text versions, language,
        voice, emotion, normalized intensity, and prepared speech text.
    """
    prepared_text = prepare_tts_text(req.text, req.language)

    identity = [
        engine.name,
        engine.cache_version,
        PROSODY_VERSION,
        TTS_TEXT_VERSION,
        req.language,
        req.voice_id,
        req.emotion,
        req.intensity,
        prepared_text,
    ]

    serialized = json.dumps(
        identity,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:40]


class AudioService:
    """
    Coordinates requests from the Renderer with a speech engine and audio store.

    `render()` returns an AudioResult rather than allowing ordinary synthesis
    or storage failures to escape into the caption pipeline.

    Instantiate one service per application process, normally during the
    existing FastAPI lifespan. Close it during application shutdown.
    """

    def __init__(
        self,
        engine: SpeechEngine,
        store: AudioStore,
        *,
        timeout_s: float = 8.0,
        max_concurrency: int = 4,
        retries: int = 1,
        retry_backoff_s: float = 0.25,
        breaker_threshold: int = 3,
        breaker_cooldown_s: float = 30.0,
        budget: BudgetGuard | None = None,
        metrics: Any | None = None,
        memo_size: int = 512,
        voice_for: Callable[[str], str] | None = None,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        if timeout_s <= 0:
            raise ValueError("timeout_s must be greater than zero")
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        if retries < 0:
            raise ValueError("retries cannot be negative")
        if retry_backoff_s < 0:
            raise ValueError("retry_backoff_s cannot be negative")
        if breaker_threshold < 1:
            raise ValueError("breaker_threshold must be at least 1")
        if breaker_cooldown_s < 0:
            raise ValueError("breaker_cooldown_s cannot be negative")
        if memo_size < 0:
            raise ValueError("memo_size cannot be negative")

        self.engine = engine
        self.store = store

        self.timeout_s = float(timeout_s)
        self.retries = retries
        self.retry_backoff_s = float(retry_backoff_s)

        self.breaker_threshold = breaker_threshold
        self.breaker_cooldown_s = float(breaker_cooldown_s)

        self.budget = budget
        self.metrics = metrics if metrics is not None else NullMetrics()
        self._voice_for = voice_for
        self._now = now

        self._sem = asyncio.Semaphore(max_concurrency)

        # LRU of recently used stored URLs/paths. The persistent store remains
        # the source of truth after process restarts.
        self._memo: OrderedDict[str, StoredAudio] = OrderedDict()
        self._memo_size = memo_size

        # A single synthesis task for each cache key. Identical callers share
        # this task instead of making duplicate Azure requests.
        self._inflight: dict[str, asyncio.Task[_ProduceResult]] = {}

        # Lightweight process-local circuit breaker.
        self._failures = 0
        self._open_until = 0.0

        self._closed = False

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def resolve_voice(self, language: str) -> str:
        """Return the configured Azure voice for a language/locale."""
        if self._voice_for is None:
            raise ValueError(
                "This AudioService was created without a voice resolver"
            )

        return self._voice_for(language)

    async def render(self, req: AudioRequest) -> AudioResult:
        """
        Render a request and return a success/failure result.

        Expected operational failures become AudioResult(success=False).
        Caller cancellation is allowed to propagate normally.
        """
        started = self._now()

        if self._closed:
            result = self._fail(req, "audio service is closed")
            self._record_metrics("closed", started, req)
            return result

        try:
            result, outcome = await self._render(req)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(
                "Unexpected audio service error for narration %s",
                getattr(req, "narration_id", "<unknown>"),
            )
            result = self._fail(req, f"unexpected audio error: {exc}")
            outcome = "internal_error"

        self._record_metrics(outcome, started, req)

        if outcome == "budget":
            self._metric("quota_exceeded", req)

        return result

    async def render_batch(
        self,
        reqs: list[AudioRequest],
    ) -> list[AudioResult]:
        """
        Render a batch in priority order.

        Lower priority values run first. Match minute breaks ties. Results are
        returned in that sorted order, not in the caller's original order.

        Each request still passes through the concurrency semaphore.
        """
        ordered = sorted(
            reqs,
            key=lambda request: (
                request.priority,
                request.match_minute,
            ),
        )

        return list(
            await asyncio.gather(
                *(self.render(request) for request in ordered)
            )
        )

    async def render_and_publish(
        self,
        req: AudioRequest,
        *,
        card_id: str,
        match_seconds: float,
        publish: Callable[[dict[str, Any]], Awaitable[None] | Any],
        existing_audio_url: str | None = None,
        existing_duration_ms: int | None = None,
        event_ts: float | None = None,
    ) -> AudioResult:
        """
        Render audio and publish the existing audio_update event shape.

        If a bundled/pre-generated URL is already available, synthesis is
        skipped. Publication still occurs.

        Publication failure is logged but does not turn a successful synthesis
        into a failed audio result or invalidate the caption.

        `event_ts`, when provided, must be Unix epoch time in seconds.
        """
        if existing_audio_url:
            result = AudioResult(
                narration_id=req.narration_id,
                audio_path=existing_audio_url,
                duration_ms=existing_duration_ms,
                success=True,
            )
            self._metric("record", "bundle_hit", 0.0, req)
        else:
            result = await self.render(req)

        payload = {
            "type": "audio_update",
            "card_id": card_id,
            "audio_url": result.audio_path if result.success else None,
            "duration_ms": result.duration_ms,
            "match_seconds": match_seconds,
        }

        # Only expose the spoken rewrite when it differs from the approved
        # caption. This keeps the normal payload stable while making the
        # audio-only script auditable and its Swahili gloss available.
        if (
            req.source_text
            and req.source_text.strip()
            and req.source_text.strip() != req.text.strip()
        ):
            payload["source_text"] = req.source_text
            payload["spoken_text"] = req.text
            if req.gloss_en:
                payload["spoken_gloss_en"] = req.gloss_en

        try:
            await _maybe_await(publish(payload))
        except Exception:
            logger.exception(
                "Could not publish audio_update for card %s",
                card_id,
            )

        if event_ts is not None:
            latency_ms = max(
                0.0,
                (time.time() - event_ts) * 1000.0,
            )
            self._metric("latency", latency_ms, req)

        return result

    async def warmup(self) -> None:
        """
        Optionally warm the engine.

        Azure's HTTP engine does not require model warmup. This hook is retained
        for compatible local engines and integration tests.
        """
        warmup = getattr(self.engine, "warmup", None)
        if callable(warmup):
            await warmup()

    async def aclose(self) -> None:
        """
        Wait for in-flight renders, then close the engine and storage backend.

        This avoids closing shared HTTP/storage clients while a render task
        still uses them. The engine's own timeout bounds ongoing synthesis.
        """
        if self._closed:
            return

        self._closed = True

        outstanding = list(self._inflight.values())
        if outstanding:
            await asyncio.gather(
                *outstanding,
                return_exceptions=True,
            )

        close_errors: list[Exception] = []

        for resource in (self.engine, self.store):
            try:
                await resource.aclose()
            except Exception as exc:
                close_errors.append(exc)
                logger.exception("Failed to close an audio resource")

        if close_errors:
            # Resources are attempted independently so a failure closing the
            # engine does not prevent an attempt to close storage.
            logger.warning(
                "Audio service closed with %d resource-close error(s)",
                len(close_errors),
            )

    # -----------------------------------------------------------------------
    # Metrics helpers
    # -----------------------------------------------------------------------

    def _metric(self, name: str, *args: Any) -> None:
        """Call a metrics method when available; metrics must not break audio."""
        function = getattr(self.metrics, name, None)

        if not callable(function):
            return

        try:
            function(*args)
        except Exception:
            logger.warning(
                "Metrics hook %s failed",
                name,
                exc_info=True,
            )

    def _record_metrics(
        self,
        outcome: str,
        started: float,
        req: AudioRequest,
    ) -> None:
        elapsed_ms = max(0.0, (self._now() - started) * 1000.0)
        self._metric("record", outcome, elapsed_ms, req)

    # -----------------------------------------------------------------------
    # Validation and results
    # -----------------------------------------------------------------------

    @staticmethod
    def _normalise(req: AudioRequest) -> AudioRequest:
        """Validate and normalize an AudioRequest before computing its key."""
        if not isinstance(req.text, str) or not req.text.strip():
            raise ValueError("empty narration text")

        if not isinstance(req.language, str):
            raise ValueError("language must be a string")

        language = req.language.strip().lower()
        if language not in LANGUAGES:
            raise ValueError(
                f"unsupported language {req.language!r}; "
                f"expected one of {LANGUAGES}"
            )

        if not isinstance(req.emotion, str):
            raise ValueError("emotion must be a string")

        emotion = req.emotion.strip().lower()
        if emotion not in EMOTIONS:
            raise ValueError(
                f"unsupported emotion {req.emotion!r}; "
                f"expected one of {EMOTIONS}"
            )

        if not isinstance(req.voice_id, str) or not req.voice_id.strip():
            raise ValueError("voice_id is required")

        if not isinstance(req.narration_id, str) or not req.narration_id.strip():
            raise ValueError("narration_id is required")

        try:
            minute = int(req.match_minute)
        except (TypeError, ValueError) as exc:
            raise ValueError("match_minute must be an integer") from exc

        try:
            priority = int(req.priority)
        except (TypeError, ValueError) as exc:
            raise ValueError("priority must be an integer") from exc

        # Quantization improves cache reuse for requests whose intensities
        # differ only by tiny floating-point amounts.
        intensity = round(clamp01(req.intensity) * 4) / 4

        return replace(
            req,
            narration_id=req.narration_id.strip(),
            text=req.text.strip(),
            language=language,
            emotion=emotion,
            intensity=intensity,
            voice_id=req.voice_id.strip(),
            match_minute=minute,
            priority=priority,
        )

    @staticmethod
    def _ok(req: AudioRequest, stored: StoredAudio) -> AudioResult:
        return AudioResult(
            narration_id=req.narration_id,
            audio_path=stored.url,
            duration_ms=stored.duration_ms,
            success=True,
        )

    @staticmethod
    def _fail(req: AudioRequest, error: str) -> AudioResult:
        return AudioResult(
            narration_id=getattr(req, "narration_id", "<unknown>"),
            audio_path=None,
            duration_ms=None,
            success=False,
            error=error,
        )

    # -----------------------------------------------------------------------
    # Main cache/single-flight path
    # -----------------------------------------------------------------------

    async def _render(
        self,
        req: AudioRequest,
    ) -> tuple[AudioResult, str]:
        try:
            normalized = self._normalise(req)
        except (TypeError, ValueError) as exc:
            return self._fail(req, str(exc)), "invalid"

        key = cache_key(normalized, self.engine)

        # Fast in-memory hit.
        if key in self._memo:
            stored = self._memo[key]
            self._memo.move_to_end(key)
            return self._ok(normalized, stored), "memo_hit"

        # Reuse an existing task for this key, or become the leader.
        task = self._inflight.get(key)
        leader = task is None

        if task is None:
            task = asyncio.create_task(
                self._produce(normalized, key),
                name=f"msimulizi-audio-{key[:12]}",
            )
            self._inflight[key] = task
            task.add_done_callback(
                lambda finished, cache_key_value=key:
                    self._drop_inflight(cache_key_value, finished)
            )

        try:
            # Cancelling one waiting caller must not cancel the shared render.
            stored, outcome, error = await asyncio.shield(task)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(
                "Shared audio render task failed for %s",
                normalized.narration_id,
            )
            return self._fail(normalized, str(exc)), "internal_error"

        if stored is None:
            return (
                self._fail(normalized, error or "audio synthesis failed"),
                outcome,
            )

        if not leader:
            outcome = "coalesced"

        return self._ok(normalized, stored), outcome

    def _drop_inflight(
        self,
        key: str,
        task: asyncio.Task[_ProduceResult],
    ) -> None:
        """Remove only the exact task registered for this key."""
        if self._inflight.get(key) is task:
            self._inflight.pop(key, None)

    async def _produce(
        self,
        req: AudioRequest,
        key: str,
    ) -> _ProduceResult:
        """
        Produce one audio object for a cache key.

        This method converts expected operational failures into result tuples,
        so ordinary synthesis failures do not escape into the caller.
        """
        try:
            stored = await self.store.get(key, self.engine.audio_ext)
        except asyncio.CancelledError:
            raise
        except Exception:
            # A cache read failure is treated as a miss. The subsequent write
            # must still succeed before a playable URL can be returned.
            logger.warning(
                "Audio store read failed for key %s",
                key,
                exc_info=True,
            )
            stored = None

        if stored is not None:
            self._remember(key, stored)
            return stored, "store_hit", None

        if self._now() < self._open_until:
            return None, "breaker_open", "speech circuit is open"

        if self.budget is not None:
            try:
                # Called only for actual synthesis, never a cache hit.
                self.budget(len(req.text))
            except Exception as exc:
                logger.info(
                    "Audio budget guard refused narration %s",
                    req.narration_id,
                )
                return None, "budget", f"budget exceeded: {exc}"

        try:
            # The timeout wraps the semaphore too, so time spent queueing for a
            # synthesis slot counts against the overall budget.
            async with asyncio.timeout(self.timeout_s):
                async with self._sem:
                    audio = await self._synthesize_with_retry(req)

        except asyncio.CancelledError:
            raise

        except TimeoutError:
            self._record_failure()
            logger.warning(
                "Audio synthesis timed out for narration %s",
                req.narration_id,
            )
            return (
                None,
                "timeout",
                f"audio synthesis timed out after {self.timeout_s}s",
            )

        except SpeechError as exc:
            if exc.transient:
                self._record_failure()

            logger.warning(
                "Speech engine error for narration %s: %s",
                req.narration_id,
                exc,
            )
            return None, "engine_error", str(exc)

        except Exception as exc:
            logger.exception(
                "Unexpected speech error for narration %s",
                req.narration_id,
            )
            return None, "engine_error", f"unexpected speech error: {exc}"

        if not audio.data:
            self._record_failure()
            return None, "engine_error", "speech engine returned empty audio"

        try:
            stored = await self.store.put(
                key,
                audio.data,
                audio.duration_ms,
                self.engine.audio_ext,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(
                "Could not store synthesized audio for narration %s",
                req.narration_id,
            )
            # Do not report success without a durable location/URL.
            return None, "store_error", f"audio storage failed: {exc}"

        self._failures = 0
        self._open_until = 0.0

        self._remember(key, stored)
        return stored, "synthesized", None

    async def _synthesize_with_retry(
        self,
        req: AudioRequest,
    ):
        """Retry only errors explicitly marked transient by the engine."""
        for attempt in range(self.retries + 1):
            try:
                return await self.engine.synthesize(req)

            except asyncio.CancelledError:
                raise

            except SpeechError as exc:
                last_attempt = attempt >= self.retries

                if not exc.transient or last_attempt:
                    raise

                delay = self.retry_backoff_s * (attempt + 1)

                logger.info(
                    "Retrying speech synthesis for %s after transient error "
                    "(attempt %d/%d)",
                    req.narration_id,
                    attempt + 1,
                    self.retries,
                )

                if delay > 0:
                    await asyncio.sleep(delay)

        # The loop must either return audio or raise; this protects static
        # analysis and unexpected future changes.
        raise SpeechError("speech retry loop ended without a result")

    # -----------------------------------------------------------------------
    # Circuit breaker and in-memory LRU
    # -----------------------------------------------------------------------

    def _record_failure(self) -> None:
        self._failures += 1

        if self._failures >= self.breaker_threshold:
            self._open_until = self._now() + self.breaker_cooldown_s

            # Require more than one later success to accumulate new failures
            # from zero; a failed post-cooldown probe can open it again.
            self._failures = self.breaker_threshold - 1

            logger.warning(
                "Audio circuit opened for %.1f seconds",
                self.breaker_cooldown_s,
            )

    def _remember(self, key: str, stored: StoredAudio) -> None:
        """Insert or refresh a persistent entry in the bounded LRU."""
        if self._memo_size == 0:
            return

        self._memo[key] = stored
        self._memo.move_to_end(key)

        while len(self._memo) > self._memo_size:
            self._memo.popitem(last=False)


async def _maybe_await(value: Any) -> Any:
    """Accept synchronous and asynchronous publication callbacks."""
    import inspect

    if inspect.isawaitable(value):
        return await value

    return value


__all__ = [
    "AudioService",
    "cache_key",
]

