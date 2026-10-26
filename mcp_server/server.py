"""
mcp_server/server.py — Msimulizi MCP server.

Exposes three typed tools via FastMCP:
    get_match_state(match_id, session_id?)
    list_key_moments(match_id, trigger_tags?, min_priority?, limit?)
    get_player_stats(match_id, player_name, session_id?)

Authentication: Bearer token in the ``Authorization`` header, validated
against the MCP_API_KEY environment variable (loaded from Key Vault in
production; falls back to the env var directly for local development).

Mounted at ``/mcp`` inside the main FastAPI app.

Requirements: 11.1 – 11.4
"""

from __future__ import annotations

import contextvars
import hmac
import os
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse

from shared.cosmos import CosmosRepositories
from shared.pubsub import PubSub

# ---------------------------------------------------------------------------
# Dependency injection placeholders
# These are replaced at startup by api/main.py via set_dependencies().
# ---------------------------------------------------------------------------

_repos: CosmosRepositories | None = None
_bus: PubSub | None = None


def set_dependencies(repos: CosmosRepositories, bus: PubSub) -> None:
    """Wire live repositories and pub/sub bus (called from api/main.py)."""
    global _repos, _bus
    _repos = repos
    _bus = bus


def _get_repos() -> CosmosRepositories:
    if _repos is None:
        raise RuntimeError("MCP server not initialised — call set_dependencies() first")
    return _repos


def _get_bus() -> PubSub:
    if _bus is None:
        raise RuntimeError("MCP server not initialised — call set_dependencies() first")
    return _bus


# ---------------------------------------------------------------------------
# API key validation
# ---------------------------------------------------------------------------

_MCP_API_KEY = os.environ.get("MCP_API_KEY", "")

# Set by the HTTP middleware after it validates the request's Bearer token.
# Tool calls from the mounted MCP transport therefore do not have to repeat the
# secret as a tool argument, while direct in-process calls still must.
_http_authenticated: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "mcp_http_authenticated", default=False
)


def mcp_auth_enabled() -> bool:
    """Return True when a bearer token is required for the MCP endpoint."""
    return bool(_MCP_API_KEY)


def _header_is_authorized(authorization: str | None) -> bool:
    if not _MCP_API_KEY:
        return True
    if not authorization:
        return False
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return False
    return hmac.compare_digest(token, _MCP_API_KEY)


def _validate_key(authorization: str | None) -> None:
    """
    Raise PermissionError when the Bearer token is missing or wrong.

    The key is not configured in dev/CI mode — all requests are allowed. A
    request that already passed the HTTP Bearer middleware is also allowed.
    """
    if not _MCP_API_KEY or _http_authenticated.get():
        return
    if not authorization:
        raise PermissionError("Missing Authorization header")
    if not _header_is_authorized(authorization):
        raise PermissionError("Invalid API key")


class BearerAuthMiddleware:
    """ASGI middleware enforcing a Bearer token on the mounted MCP endpoint."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        if not _header_is_authorized(headers.get("authorization")):
            response = JSONResponse(
                {
                    "error": "Unauthorized",
                    "detail": "A valid Bearer token is required for /mcp",
                },
                status_code=401,
                headers={"WWW-Authenticate": 'Bearer realm="msimulizi-mcp"'},
            )
            await response(scope, receive, send)
            return

        token = _http_authenticated.set(True)
        try:
            await self.app(scope, receive, send)
        finally:
            _http_authenticated.reset(token)


def _transport_security() -> TransportSecuritySettings:
    """Allow deployments to opt into Host/Origin validation explicitly.

    The MCP SDK auto-enables localhost-only DNS-rebinding protection when it is
    constructed with its default host. That would reject the Azure Container
    Apps hostname, so the production mount defaults to Bearer auth only unless
    MCP_ALLOWED_HOSTS is supplied.
    """
    hosts = [
        value.strip()
        for value in os.getenv("MCP_ALLOWED_HOSTS", "").split(",")
        if value.strip()
    ]
    if not hosts:
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    origins = [
        value.strip()
        for value in os.getenv("MCP_ALLOWED_ORIGINS", "").split(",")
        if value.strip()
    ]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=origins,
    )


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class MatchStateResult(BaseModel):
    match_id: str
    session_id: str | None
    minute: int
    second: int
    score_home: int
    score_away: int
    team_home: str
    team_away: str
    possession_home: float
    field_tilt_home: float
    field_tilt_away: float
    xg_home: float
    xg_away: float
    momentum_home: float
    momentum_away: float
    pressure_rate_home: float
    pressure_rate_away: float
    tempo: float
    source: str  # "live" | "snapshot"


class KeyMomentResult(BaseModel):
    moment_id: str
    match_id: str
    trigger_event_id: str
    trigger_tags: list[str]
    priority_rank: int
    minute: int
    second: int
    reason: str | None
    theme: str | None


class PlayerStatsResult(BaseModel):
    player: str
    team: str
    match_id: str
    passes_attempted: int
    passes_completed: int
    pass_accuracy: float
    shots: int
    shots_on_target: int
    xg_total: float
    goals: int
    tackles_attempted: int
    tackles_won: int
    interceptions: int
    cards: int
    source: str  # "live" | "snapshot"


class ErrorResult(BaseModel):
    error: str
    detail: str


# ---------------------------------------------------------------------------
# Tool: get_match_state
# ---------------------------------------------------------------------------

async def get_match_state(
    match_id: Annotated[str, Field(description="The match identifier")],
    session_id: Annotated[
        str | None,
        Field(description="Optional live session ID; if provided, reads from the pub/sub bus first"),
    ] = None,
    authorization: Annotated[
        str | None,
        Field(description="Bearer <token> — required unless MCP_API_KEY is unset"),
    ] = None,
) -> MatchStateResult | ErrorResult:
    """
    Return the current (or most recent snapshot) match state for *match_id*.

    If *session_id* is provided the tool first checks the pub/sub bus for a
    live state update (latency < 1 s); otherwise it falls back to the most
    recent Cosmos snapshot.
    """
    try:
        _validate_key(authorization)
    except PermissionError as exc:
        return ErrorResult(error="Unauthorized", detail=str(exc))

    bus = _get_bus()
    repos = _get_repos()

    state: dict[str, Any] | None = None
    source = "snapshot"

    if session_id:
        live = bus.latest(f"match_state:{session_id}")
        if live is not None:
            state = live if isinstance(live, dict) else vars(live)
            source = "live"

    if state is None:
        state = await repos.match_state_snapshots.get_latest_snapshot(match_id)
        if state is not None:
            source = "snapshot"

    if state is None:
        return ErrorResult(
            error="NotFound",
            detail=f"No state available for match_id={match_id!r}",
        )

    return MatchStateResult(
        match_id=match_id,
        session_id=session_id,
        minute=state.get("minute", 0),
        second=state.get("second", 0),
        score_home=state.get("score_home", 0),
        score_away=state.get("score_away", 0),
        team_home=state.get("team_home", ""),
        team_away=state.get("team_away", ""),
        possession_home=state.get("possession_home", 0.5),
        field_tilt_home=state.get("field_tilt_home", 0.0),
        field_tilt_away=state.get("field_tilt_away", 0.0),
        xg_home=state.get("xg_home", 0.0),
        xg_away=state.get("xg_away", 0.0),
        momentum_home=state.get("momentum_home", 50.0),
        momentum_away=state.get("momentum_away", 50.0),
        pressure_rate_home=state.get("pressure_rate_home", 0.0),
        pressure_rate_away=state.get("pressure_rate_away", 0.0),
        tempo=state.get("tempo", 0.0),
        source=source,
    )


# ---------------------------------------------------------------------------
# Tool: list_key_moments
# ---------------------------------------------------------------------------

async def list_key_moments(
    match_id: Annotated[str, Field(description="The match identifier")],
    trigger_tags: Annotated[
        list[str] | None,
        Field(description="Filter by trigger tags, e.g. ['goal', 'lead_change']"),
    ] = None,
    min_priority: Annotated[
        int | None,
        Field(description="Return moments with priority_rank <= this value (1=highest)"),
    ] = None,
    limit: Annotated[
        int,
        Field(description="Maximum number of moments to return", ge=1, le=100),
    ] = 20,
    authorization: Annotated[
        str | None,
        Field(description="Bearer <token>"),
    ] = None,
) -> list[KeyMomentResult] | ErrorResult:
    """Return key moments for *match_id*, optionally filtered by tags and priority."""
    try:
        _validate_key(authorization)
    except PermissionError as exc:
        return ErrorResult(error="Unauthorized", detail=str(exc))

    repos = _get_repos()
    docs = await repos.key_moments.list_moments(
        match_id=match_id,
        trigger_tags=trigger_tags,
        min_priority=min_priority,
        limit=limit,
    )

    results: list[KeyMomentResult] = []
    for doc in docs:
        explanation = doc.get("structured_explanation") or {}
        results.append(KeyMomentResult(
            moment_id=doc.get("moment_id", doc.get("id", "")),
            match_id=doc.get("match_id", match_id),
            trigger_event_id=doc.get("trigger_event_id", ""),
            trigger_tags=doc.get("trigger_tags", []),
            priority_rank=doc.get("priority_rank", 5),
            minute=doc.get("minute", 0),
            second=doc.get("second", 0),
            reason=explanation.get("reason") if isinstance(explanation, dict) else None,
            theme=explanation.get("theme") if isinstance(explanation, dict) else None,
        ))
    return results


# ---------------------------------------------------------------------------
# Tool: get_player_stats
# ---------------------------------------------------------------------------

async def get_player_stats(
    match_id: Annotated[str, Field(description="The match identifier")],
    player_name: Annotated[str, Field(description="Exact player name as used in events")],
    session_id: Annotated[
        str | None,
        Field(description="Optional live session ID for sub-second latency"),
    ] = None,
    authorization: Annotated[
        str | None,
        Field(description="Bearer <token>"),
    ] = None,
) -> PlayerStatsResult | ErrorResult:
    """
    Return accumulated statistics for *player_name* in *match_id*.

    Reads from the live pub/sub state when *session_id* is provided,
    otherwise falls back to the most recent Cosmos snapshot.
    """
    try:
        _validate_key(authorization)
    except PermissionError as exc:
        return ErrorResult(error="Unauthorized", detail=str(exc))

    bus = _get_bus()
    repos = _get_repos()

    player_stats: dict[str, Any] | None = None
    source = "snapshot"

    if session_id:
        live = bus.latest(f"match_state:{session_id}")
        if live is not None:
            state = live if isinstance(live, dict) else vars(live)
            stats_map: dict = state.get("player_stats", {})
            if player_name in stats_map:
                raw = stats_map[player_name]
                player_stats = raw if isinstance(raw, dict) else vars(raw)
                source = "live"

    if player_stats is None:
        latest = await repos.match_state_snapshots.get_latest_snapshot(match_id)
        if latest is not None:
            stats_map = latest.get("player_stats", {})
            if player_name in stats_map:
                raw = stats_map[player_name]
                player_stats = raw if isinstance(raw, dict) else vars(raw)
                source = "snapshot"

    if player_stats is None:
        return ErrorResult(
            error="NotFound",
            detail=f"No stats found for player {player_name!r} in match {match_id!r}",
        )

    attempts = player_stats.get("passes_attempted", 0)
    completed = player_stats.get("passes_completed", 0)
    accuracy = (completed / attempts) if attempts > 0 else 0.0

    return PlayerStatsResult(
        player=player_stats.get("player", player_name),
        team=player_stats.get("team", ""),
        match_id=match_id,
        passes_attempted=attempts,
        passes_completed=completed,
        pass_accuracy=round(accuracy, 4),
        shots=player_stats.get("shots", 0),
        shots_on_target=player_stats.get("shots_on_target", 0),
        xg_total=player_stats.get("xg_total", 0.0),
        goals=player_stats.get("goals", 0),
        tackles_attempted=player_stats.get("tackles_attempted", 0),
        tackles_won=player_stats.get("tackles_won", 0),
        interceptions=player_stats.get("interceptions", 0),
        cards=player_stats.get("cards", 0),
        source=source,
    )


# ---------------------------------------------------------------------------
# FastMCP app factory
# ---------------------------------------------------------------------------

def create_mcp_app() -> FastMCP:
    """Build a fresh MCP server instance for one FastAPI application.

    A fresh instance is important for tests and workers: the Streamable HTTP
    session manager can only be started once per FastMCP instance.
    """
    app = FastMCP(
        name="msimulizi-mcp",
        instructions=(
            "Msimulizi MCP server. Provides real-time and historical football "
            "match intelligence: match state, key moments, and player stats. "
            "All tools require a valid Bearer token in the Authorization header."
        ),
        # Mounted at /mcp by the FastAPI app, so the inner route is the root.
        streamable_http_path="/",
        stateless_http=True,
        host="0.0.0.0",
        transport_security=_transport_security(),
    )
    app.tool()(get_match_state)
    app.tool()(list_key_moments)
    app.tool()(get_player_stats)
    return app


# Convenience instance for standalone use (e.g. `python -m mcp_server.server`).
mcp_app = create_mcp_app()
