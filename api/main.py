"""Application assembly for the Msimulizi API and MCP surface.

This module keeps the entry point lightweight: it provides a create_app()
factory, a small concurrent session manager, graceful optional Azure Speech
configuration, and an optional FastMCP integration.

Audio lifecycle:
    - AudioService is created during the FastAPI lifespan, not at import time.
    - renderer.tts keeps a compatibility facade that delegates to that service.
    - the existing session/pipeline and WebSocket wiring is preserved.
"""

from __future__ import annotations

import asyncio
import logging
import os
import pathlib
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Mapping

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from mcp.server.fastmcp import FastMCP

from pipeline.orchestrator import Orchestrator
from scripts.generate_bundle import load_bundle_narrations, seed_narration_cache


logger = logging.getLogger(__name__)


@dataclass
class SessionRecord:
    session_id: str
    created_at: float = field(default_factory=time.monotonic)
    last_seen: float = field(default_factory=time.monotonic)
    metadata: dict[str, Any] = field(default_factory=dict)


class SessionManager:
    """Manage concurrent replay sessions and enforce idle timeout cleanup."""

    def __init__(
        self,
        *,
        max_sessions: int = 8,
        idle_timeout_seconds: float = 600.0,
    ) -> None:
        self.max_sessions = max_sessions
        self.idle_timeout_seconds = idle_timeout_seconds
        self._sessions: dict[str, SessionRecord] = {}

    def create_session(self, *, metadata: dict[str, Any] | None = None) -> SessionRecord:
        self.cleanup()
        if len(self._sessions) >= self.max_sessions:
            raise HTTPException(429, "Session cap reached")
        session = SessionRecord(
            session_id=str(uuid.uuid4()),
            metadata=metadata or {},
        )
        self._sessions[session.session_id] = session
        return session

    def touch(self, session_id: str) -> SessionRecord | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        session.last_seen = time.monotonic()
        return session

    def get(self, session_id: str) -> SessionRecord | None:
        return self._sessions.get(session_id)

    def cleanup(self) -> None:
        now = time.monotonic()
        expired = [
            session_id
            for session_id, session in self._sessions.items()
            if (now - session.last_seen) > self.idle_timeout_seconds
        ]
        for session_id in expired:
            self._sessions.pop(session_id, None)

    @property
    def active(self) -> dict[str, SessionRecord]:
        self.cleanup()
        return self._sessions


def _load_session_limits() -> tuple[int, float]:
    max_sessions = int(os.getenv("MSIMULIZI_MAX_SESSIONS", "8"))
    idle_timeout = float(os.getenv("MSIMULIZI_IDLE_TIMEOUT_SECONDS", "600"))
    return max_sessions, idle_timeout


def _build_foundry_client() -> Any | None:
    """Construct a real FoundryClient from env vars, or None when unconfigured."""
    endpoint = os.getenv("FOUNDRY_ENDPOINT", "").strip()
    api_key = os.getenv("FOUNDRY_API_KEY", "").strip() or None
    if not endpoint:
        logger.warning(
            "[startup] FOUNDRY_ENDPOINT not set — LLM calls will use fallback templates"
        )
        return None
    try:
        from shared.foundry_client import FoundryClient

        return FoundryClient(endpoint=endpoint, api_key=api_key)
    except Exception as exc:  # pragma: no cover - depends on deployment configuration
        logger.warning("[startup] FoundryClient unavailable: %s", exc)
        return None


def _speech_configuration_present(env: Mapping[str, str] | None = None) -> bool:
    """Return True when either the new or legacy Speech environment is present.

    No Speech variables means TTS is disabled and the app can still start.
    Partial configuration is treated as a configuration error rather than
    silently disabling a service the operator appears to have configured.
    """
    values = os.environ if env is None else env
    names = (
        "AZURE_SPEECH_KEY",
        "AZURE_SPEECH_REGION",
        "AZURE_SPEECH_ENDPOINT",
        "SPEECH_API_KEY",  # legacy alias
        "SPEECH_ENDPOINT",  # legacy alias
    )
    return any(str(values.get(name, "")).strip() for name in names)


def _build_audio_settings(env: Mapping[str, str] | None = None) -> Any:
    """Build AudioSettings, translating the previous SPEECH_* names.

    New names take precedence:
        AZURE_SPEECH_KEY
        AZURE_SPEECH_REGION
        AZURE_SPEECH_ENDPOINT

    Legacy aliases remain accepted during migration:
        SPEECH_API_KEY
        SPEECH_ENDPOINT

    A legacy SPEECH_ENDPOINT containing a URL is treated as a custom endpoint;
    a plain value such as "westeurope" is treated as the Speech region.
    """
    from renderer.audio.config import AudioSettings

    values = dict(os.environ if env is None else env)

    if not str(values.get("AZURE_SPEECH_KEY", "")).strip():
        legacy_key = str(values.get("SPEECH_API_KEY", "")).strip()
        if legacy_key:
            values["AZURE_SPEECH_KEY"] = legacy_key

    has_new_endpoint = (
        str(values.get("AZURE_SPEECH_REGION", "")).strip()
        or str(values.get("AZURE_SPEECH_ENDPOINT", "")).strip()
    )
    if not has_new_endpoint:
        legacy_endpoint = str(values.get("SPEECH_ENDPOINT", "")).strip()
        if legacy_endpoint:
            if legacy_endpoint.startswith(("https://", "http://")):
                values["AZURE_SPEECH_ENDPOINT"] = legacy_endpoint
            else:
                values["AZURE_SPEECH_REGION"] = legacy_endpoint

    return AudioSettings.from_env(values)


def create_app(
    *,
    orchestrator: Orchestrator | None = None,
    session_manager: SessionManager | None = None,
) -> Any:
    """Create and configure the application instance for the backend runtime."""
    max_sessions, idle_timeout = _load_session_limits()
    if session_manager is None:
        session_manager = SessionManager(
            max_sessions=max_sessions,
            idle_timeout_seconds=idle_timeout,
        )
    if orchestrator is None:
        orchestrator = Orchestrator()

    # Foundry retains the current configuration path. Speech clients are
    # created asynchronously in lifespan so HTTP clients and Blob credentials
    # are initialized and closed within the application lifecycle.
    app_foundry = _build_foundry_client()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        audio_service = None
        session_manager.cleanup()

        try:
            app.state.foundry_client = app_foundry
            app.state.audio_service = None
            app.state.audio_settings = None
            app.state.speech_client = None

            # Register/clear any previously registered singleton. This matters
            # for tests and application instances created repeatedly in-process.
            from renderer.tts import (
                AzureSpeechSynthesizer,
                clear_audio_service,
                set_audio_service,
            )

            clear_audio_service()

            if _speech_configuration_present():
                from renderer.audio.config import build_audio_service

                settings = _build_audio_settings()
                audio_service = await build_audio_service(settings)
                set_audio_service(audio_service, settings=settings)

                # Compatibility facade used by existing pipeline_runner code.
                # It delegates to the registered singleton and does not own a
                # second Speech or Blob client.
                app.state.audio_settings = settings
                app.state.audio_service = audio_service
                app.state.speech_client = AzureSpeechSynthesizer()
                logger.info(
                    "[startup] Azure Speech audio service ready; region=%s storage=%s",
                    settings.speech_region or "custom-endpoint",
                    "azure-blob" if settings.blob_account_url else "local-development",
                )
            else:
                logger.info(
                    "[startup] Azure Speech not configured — TTS disabled; captions remain available"
                )
                app.state.audio_service = None
                app.state.audio_settings = None
                app.state.speech_client = None

            logger.info(
                "[startup] foundry=%s speech=%s",
                "live" if app_foundry else "none",
                "live" if app.state.speech_client else "none",
            )

            # Seed the narration cache from the pre-generated bundle so that
            # bundle replay uses the cache-hit path (no LLM or TTS calls).
            try:
                bundle_cards = load_bundle_narrations()
                if bundle_cards:
                    seeded = seed_narration_cache(
                        app.state.narration_cache,
                        bundle_cards,
                    )
                    logger.info(
                        "[startup] bundle seeded %d cards into narration cache",
                        seeded,
                    )
                    app.state.bundle_cards = bundle_cards
                else:
                    app.state.bundle_cards = {}
            except Exception as exc:  # pragma: no cover - depends on runtime bundle
                logger.warning("[startup] bundle seeding failed: %s", exc)
                app.state.bundle_cards = {}

            yield

        finally:
            session_manager.cleanup()

            # Clear the module-level registry before closing clients so any
            # late task fails closed instead of reusing a closing service.
            try:
                from renderer.tts import clear_audio_service

                clear_audio_service(audio_service)
            except Exception:
                logger.warning(
                    "[shutdown] could not clear TTS singleton",
                    exc_info=True,
                )

            if audio_service is not None:
                try:
                    await audio_service.aclose()
                except Exception:
                    logger.warning(
                        "[shutdown] failed to close audio service cleanly",
                        exc_info=True,
                    )

    app = FastAPI(title="Msimulizi", version="0.1.0", lifespan=lifespan)
    app.state.orchestrator = orchestrator
    app.state.session_manager = session_manager
    app.state.foundry_client = app_foundry
    app.state.speech_client = None
    app.state.audio_service = None
    app.state.audio_settings = None
    app.state.cards_store = {}
    app.state.corrections_store = {}
    app.state.audit_store = {}
    app.state.narration_cache = {}  # in-memory cache seeded from bundle at startup
    app.state.bundle_cards = {}
    app.state.content_safety = None
    app.state.websocket_manager = None
    app.state.ip_buckets = {}

    allowed_origins = os.getenv(
        "MSIMULIZI_ALLOWED_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    ).split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin.strip() for origin in allowed_origins if origin.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "active_sessions": len(session_manager.active)}

    @app.post("/v1/sessions")
    async def create_session_endpoint(
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        metadata = payload or {}
        try:
            record = session_manager.create_session(metadata=metadata)
        except HTTPException:
            raise

        storyline = str(metadata.get("storyline", "comeback_from_two_down"))
        seed = int(metadata.get("seed", 42))
        speed = float(metadata.get("speed", 1.0))
        language = str(metadata.get("language", "en"))
        mode = str(metadata.get("mode", "casual"))
        resolved_match_id = str(metadata.get("match_id") or f"{storyline}-{seed}")

        app.state.orchestrator.create_session(
            session_id=record.session_id,
            match_id=resolved_match_id,
        )

        # Spawn the pipeline as a background asyncio task so the session starts
        # streaming immediately instead of waiting for the full match pipeline.
        try:
            from api.pipeline_runner import run_pipeline_session

            ws_mgr = getattr(app.state, "websocket_manager", None)
            fc = getattr(app.state, "foundry_client", None)
            sc = getattr(app.state, "speech_client", None)
            cs = getattr(app.state, "content_safety", None)
            nc = getattr(app.state, "narration_cache", None)
            bc = getattr(app.state, "bundle_cards", None)

            task = asyncio.create_task(
                run_pipeline_session(
                    record.session_id,
                    resolved_match_id,
                    storyline=storyline,
                    seed=seed,
                    speed=speed,
                    language=language,
                    mode=mode,
                    ws_mgr=ws_mgr,
                    foundry_client=fc,
                    tts_client=sc,
                    content_safety=cs,
                    narration_cache=nc,
                    bundle_cards=bc,
                ),
                name=f"pipeline-{record.session_id}",
            )

            if not hasattr(app.state, "pipeline_tasks"):
                app.state.pipeline_tasks = {}
            app.state.pipeline_tasks[record.session_id] = task

            logger.info(
                "[session] created session_id=%s match_id=%s storyline=%s seed=%d",
                record.session_id,
                resolved_match_id,
                storyline,
                seed,
            )
        except Exception as exc:  # pragma: no cover - depends on runner wiring
            logger.warning("[session] pipeline task spawn failed: %s", exc)

        return {
            "session_id": record.session_id,
            "status": "created",
            "match_id": resolved_match_id,
            "active_sessions": len(session_manager.active),
            "max_sessions": session_manager.max_sessions,
        }

    # Wire in the modular router implemented in api.routes.
    try:
        from .routes import router as v1_router

        app.include_router(v1_router)
    except Exception:
        logger.debug("Optional api.routes router was not mounted", exc_info=True)

    # Create and attach a WebSocket manager and route.
    try:
        from .websocket import WebSocketManager, websocket_endpoint

        ws_mgr = WebSocketManager()
        app.state.websocket_manager = ws_mgr

        async def websocket_route(websocket: WebSocket) -> None:
            await websocket_endpoint(websocket, ws_mgr, session_manager)

        app.websocket("/ws")(websocket_route)
    except Exception:
        logger.warning("WebSocket wiring failed; real-time push is disabled", exc_info=True)
        app.state.websocket_manager = None

    # Mount the frontend directory as static files so slice.html is reachable.
    frontend_dir = pathlib.Path(__file__).resolve().parents[1] / "frontend"
    if frontend_dir.exists():
        app.mount(
            "/static",
            StaticFiles(directory=str(frontend_dir), html=True),
            name="static",
        )
        logger.info("[startup] serving frontend from %s at /static", frontend_dir)

    if FastMCP is not None:
        mcp = FastMCP("msimulizi", mount_path="/mcp")

        @mcp.tool(name="get_match_state")
        def get_match_state_tool(
            match_id: str,
            session_id: str | None = None,
        ) -> dict[str, Any]:
            return {
                "match_id": match_id,
                "session_id": session_id,
                "state": {},
            }

        @mcp.tool(name="list_key_moments")
        def list_key_moments_tool(
            match_id: str,
            trigger_tags: list[str] | None = None,
            min_priority: int | None = None,
            limit: int = 20,
        ) -> dict[str, Any]:
            return {
                "match_id": match_id,
                "trigger_tags": trigger_tags or [],
                "min_priority": min_priority,
                "limit": limit,
                "moments": [],
            }

        @mcp.tool(name="get_player_stats")
        def get_player_stats_tool(
            match_id: str,
            player_name: str,
            session_id: str | None = None,
        ) -> dict[str, Any]:
            return {
                "match_id": match_id,
                "player_name": player_name,
                "session_id": session_id,
                "stats": {},
            }

        app.mount("/mcp", mcp.streamable_http_app())

    return app


app = create_app()

__all__ = [
    "SessionManager",
    "SessionRecord",
    "create_app",
    "app",
]
