"""Application assembly for the Msimulizi API and MCP surface.

This module keeps the entry point intentionally lightweight: it provides a
`create_app()` factory, a small concurrent session manager, and a graceful
optional integration with the Microsoft `FastMCP` server when the dependency is
installed.
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
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket
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
        logger.warning("[startup] FOUNDRY_ENDPOINT not set — LLM calls will use fallback templates")
        return None
    try:
        from shared.foundry_client import FoundryClient
        return FoundryClient(endpoint=endpoint, api_key=api_key)
    except Exception as exc:  # pragma: no cover
        logger.warning("[startup] FoundryClient unavailable: %s", exc)
        return None


async def _build_content_safety() -> Any | None:
    """Construct the Content Safety client (key locally, managed identity in Azure)."""
    endpoint = (
        os.getenv("CONTENT_SAFETY_ENDPOINT", "").strip()
        or os.getenv("AZURE_CONTENT_SAFETY_ENDPOINT", "").strip()
    )

    if not endpoint:
        logger.info("[startup] CONTENT_SAFETY_ENDPOINT not set — safety checks skipped")
        return None

    key = (
        os.getenv("CONTENT_SAFETY_API_KEY", "").strip()
        or os.getenv("AZURE_CONTENT_SAFETY_KEY", "").strip()
        or None
    )

    try:
        from shared.content_safety import ContentSafetyClient

        credential = None
        if key is None:
            from azure.identity.aio import DefaultAzureCredential

            credential = DefaultAzureCredential()

        return ContentSafetyClient(
            endpoint,
            key,
            credential=credential,
            close_credential=credential is not None,
        )
    except Exception as exc:
        logger.warning("[startup] Content Safety unavailable: %s", exc)
        return None


async def _build_audio_service() -> Any | None:
    """Construct the production audio service, or None when unconfigured.

    Uses a Speech key locally, or the Container App managed identity in Azure.
    Voice-catalogue verification runs at startup so a bad voice name fails
    early instead of producing silent cards during the demo.
    """
    if not (
        os.getenv("SPEECH_ENDPOINT", "").strip()
        or os.getenv("AZURE_SPEECH_ENDPOINT", "").strip()
        or os.getenv("AZURE_SPEECH_REGION", "").strip()
    ):
        logger.info("[startup] no Speech endpoint/region set — TTS disabled")
        return None

    try:
        from renderer.audio.config import AudioSettings, build_audio_service

        settings = AudioSettings.from_env()
        service = await build_audio_service(settings)
        logger.info(
            "[startup] audio service ready (managed_identity=%s, blob=%s)",
            settings.use_managed_identity,
            bool(settings.blob_account_url),
        )
        return service
    except Exception as exc:
        logger.warning("[startup] audio service unavailable: %s", exc)
        return None


def create_app(
    *,
    orchestrator: Orchestrator | None = None,
    session_manager: SessionManager | None = None,
) -> Any:
    """Create and configure the application instance for the backend runtime."""
    if FastAPI is None:
        raise RuntimeError(
            "FastAPI is not installed in the current environment. "
            "Install it with `uv pip install fastapi uvicorn`."
        )

    max_sessions, idle_timeout = _load_session_limits()
    if session_manager is None:
        session_manager = SessionManager(max_sessions=max_sessions, idle_timeout_seconds=idle_timeout)
    if orchestrator is None:
        orchestrator = Orchestrator()

    # Build the Foundry client now; the audio service is async and is created
    # inside the lifespan. Both degrade to None when unconfigured.
    foundry_client = _build_foundry_client()
    app_foundry = foundry_client

    @asynccontextmanager
    async def lifespan(_: Any):
        session_manager.cleanup()
        # Expose clients on app.state so request handlers and the pipeline runner
        # can reach them without re-constructing on every request.
        app.state.foundry_client = app_foundry
        audio_service = await _build_audio_service()
        app.state.audio_service = audio_service
        app.state.speech_client = audio_service
        safety_client = await _build_content_safety()
        app.state.content_safety = safety_client
        logger.info(
            "[startup] foundry=%s audio=%s content_safety=%s",
            "live" if app_foundry else "none",
            "live" if audio_service else "none",
            "live" if safety_client else "none",
        )

        # Seed the narration cache from the pre-generated bundle so that
        # bundle replay uses the cache-hit path (no LLM or TTS calls).
        try:
            bundle_cards = load_bundle_narrations()
            if bundle_cards:
                seeded = seed_narration_cache(app.state.narration_cache, bundle_cards)
                logger.info("[startup] bundle seeded %d cards into narration cache", seeded)
                app.state.bundle_cards = bundle_cards
            else:
                app.state.bundle_cards = {}
        except Exception as exc:  # pragma: no cover
            logger.warning("[startup] bundle seeding failed: %s", exc)
            app.state.bundle_cards = {}

        yield

        if audio_service is not None:
            try:
                await audio_service.aclose()
            except Exception as exc:  # pragma: no cover - shutdown best effort
                logger.warning("[shutdown] audio service close failed: %s", exc)

        if app_foundry is not None and hasattr(app_foundry, "aclose"):
            try:
                await app_foundry.aclose()
            except Exception as exc:  # pragma: no cover - shutdown best effort
                logger.warning("[shutdown] foundry client close failed: %s", exc)

        if safety_client is not None:
            try:
                await safety_client.aclose()
            except Exception as exc:  # pragma: no cover - shutdown best effort
                logger.warning("[shutdown] content safety close failed: %s", exc)

        session_manager.cleanup()

    app = FastAPI(title="Msimulizi", version="0.1.0", lifespan=lifespan)
    app.state.orchestrator = orchestrator
    app.state.session_manager = session_manager
    app.state.cards_store = {}
    app.state.corrections_store = {}
    app.state.audit_store = {}
    app.state.narration_cache = {}  # in-memory cache seeded from bundle at startup
    app.state.bundle_cards = {}
    app.state.content_safety = None
    app.state.websocket_manager = None
    app.state.ip_buckets = {}

    allowed_origins = os.getenv("MSIMULIZI_ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
    if CORSMiddleware is not None:
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
    async def create_session_endpoint(payload: dict[str, Any] | None = None) -> dict[str, Any]:
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

        # Spawn the pipeline as a background asyncio task so the session
        # starts streaming immediately without blocking the HTTP response.
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
                    ws_manager=ws_mgr,
                    foundry_client=fc,
                    audio_service=sc,
                    content_safety=cs,
                    narration_cache=nc,
                    bundle_cards=bc,
                ),
                name=f"pipeline-{record.session_id}",
            )
            # Store the task so callers can cancel it on session expiry.
            if not hasattr(app.state, "pipeline_tasks"):
                app.state.pipeline_tasks = {}
            app.state.pipeline_tasks[record.session_id] = task
            logger.info(
                "[session] created session_id=%s match_id=%s storyline=%s seed=%d",
                record.session_id, resolved_match_id, storyline, seed,
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("[session] pipeline task spawn failed: %s", exc)

        return {
            "session_id": record.session_id,
            "status": "created",
            "match_id": resolved_match_id,
            "active_sessions": len(session_manager.active),
            "max_sessions": session_manager.max_sessions,
        }

    # wire in the modular router implemented in api.routes
    try:
        from .routes import router as v1_router
        app.include_router(v1_router)
    except Exception:
        pass

    # Create and attach a WebSocket manager to app.state and register the websocket route
    try:
        from .websocket import WebSocketManager, websocket_endpoint

        ws_mgr = WebSocketManager()
        app.state.websocket_manager = ws_mgr

        async def websocket_route(websocket: WebSocket) -> None:
            await websocket_endpoint(websocket, ws_mgr, session_manager)

        app.websocket("/ws")(websocket_route)
    except Exception:
        # if websocket wiring fails, leave the app without real-time push
        app.state.websocket_manager = None

    # Mount the frontend directory as static files so slice.html is reachable.
    _frontend_dir = pathlib.Path(__file__).resolve().parents[1] / "frontend"
    if StaticFiles is not None and _frontend_dir.exists():
        app.mount("/static", StaticFiles(directory=str(_frontend_dir), html=True), name="static")
        logger.info("[startup] serving frontend from %s at /static", _frontend_dir)

    if FastMCP is not None:
        mcp = FastMCP("msimulizi", mount_path="/mcp")

        @mcp.tool(name="get_match_state")
        def get_match_state_tool(match_id: str, session_id: str | None = None) -> dict[str, Any]:
            return {"match_id": match_id, "session_id": session_id, "state": {}}

        @mcp.tool(name="list_key_moments")
        def list_key_moments_tool(match_id: str, trigger_tags: list[str] | None = None, min_priority: int | None = None, limit: int = 20) -> dict[str, Any]:
            return {
                "match_id": match_id,
                "trigger_tags": trigger_tags or [],
                "min_priority": min_priority,
                "limit": limit,
                "moments": [],
            }

        @mcp.tool(name="get_player_stats")
        def get_player_stats_tool(match_id: str, player_name: str, session_id: str | None = None) -> dict[str, Any]:
            return {"match_id": match_id, "player_name": player_name, "session_id": session_id, "stats": {}}

        app.mount("/mcp", mcp.streamable_http_app())

    return app


app = create_app() if FastAPI is not None else None

__all__ = [
    "SessionManager",
    "SessionRecord",
    "create_app",
    "app",
]
