"""WebSocket gateway: manage connections and push real-time messages to viewers.

This module exposes a WebSocketManager that stores active connections per
session and provides helpers the renderer/orchestrator can call to push cards,
clock updates, and audio updates.

Protocol note:
- Cards are wrapped in a ``{"type": "card", ...}`` envelope.
- Clock updates are wrapped in a ``{"type": "clock_update", "clock": ...}``
  envelope, preserving the existing frontend contract.
- Audio updates are sent as their own top-level four-field message so clients
  can dispatch directly on ``type == "audio_update"``.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict

from fastapi import WebSocket


class WebSocketManager:
    def __init__(self) -> None:
        # session_id -> connection metadata. The current app contract keeps one
        # active WebSocket connection per session ID.
        self._connections: Dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._pinger_task: asyncio.Task | None = None

    def _connection_ws(self, connection: dict[str, Any] | WebSocket | None) -> WebSocket | None:
        if isinstance(connection, dict):
            return connection.get("ws")
        return connection

    async def connect(
        self,
        websocket: WebSocket,
        session_id: str | None = None,
        *,
        profile_key: str | None = None,
        match_id: str | None = None,
    ) -> str:
        await websocket.accept()
        sid = session_id or f"session-{int(time.time() * 1000)}"
        async with self._lock:
            # Existing routing semantics are preserved: a session ID identifies
            # one live connection. Reconnecting the same session replaces it.
            self._connections[sid] = {
                "session_id": sid,
                "ws": websocket,
                "profile_key": profile_key,
                "match_id": match_id,
            }

        if self._pinger_task is None or self._pinger_task.done():
            self._pinger_task = asyncio.create_task(self._pinger())

        await websocket.send_json({"type": "welcome", "session_id": sid})
        return sid

    async def disconnect(self, session_id: str) -> None:
        async with self._lock:
            entry = self._connections.pop(session_id, None)
            ws = self._connection_ws(entry)
            if ws is not None:
                try:
                    await ws.close()
                except Exception:
                    pass

    async def send(self, session_id: str, payload: dict[str, Any]) -> None:
        async with self._lock:
            entry = self._connections.get(session_id)
        ws = self._connection_ws(entry)
        if ws is None:
            return
        try:
            await ws.send_text(json.dumps(payload))
        except Exception:
            await self.disconnect(session_id)

    def _matches_target(
        self,
        entry: dict[str, Any],
        *,
        session_id: str | None = None,
        profile_key: str | None = None,
        match_id: str | None = None,
    ) -> bool:
        if session_id is not None and entry.get("session_id") != session_id:
            return False
        if profile_key is not None:
            connection_profile = entry.get("profile_key")
            if connection_profile != profile_key:
                return False
        if match_id is not None:
            connection_match = entry.get("match_id")
            if connection_match != match_id:
                return False
        return True

    async def broadcast_card(
        self,
        match_id: str,
        card: dict[str, Any],
        *,
        profile_key: str | None = None,
        session_id: str | None = None,
    ) -> None:
        payload = {"type": "card", "match_id": match_id, "card": card}
        async with self._lock:
            conns = list(self._connections.items())

        for sid, entry in conns:
            if not self._matches_target(
                entry,
                session_id=session_id,
                profile_key=profile_key,
                match_id=match_id,
            ):
                continue
            ws = entry.get("ws")
            try:
                await ws.send_text(json.dumps(payload))
            except Exception:
                await self.disconnect(sid)

    async def broadcast_clock(
        self,
        clock_payload: dict[str, Any],
        *,
        match_id: str | None = None,
        profile_key: str | None = None,
    ) -> None:
        """Send a payload using the existing clock_update envelope."""
        payload = {"type": "clock_update", "clock": clock_payload}
        async with self._lock:
            conns = list(self._connections.items())

        for sid, entry in conns:
            if not self._matches_target(
                entry,
                profile_key=profile_key,
                match_id=match_id,
            ):
                continue
            ws = entry.get("ws")
            try:
                await ws.send_text(json.dumps(payload))
            except Exception:
                await self.disconnect(sid)

    async def broadcast_audio_update(
        self,
        audio_payload: dict[str, Any],
        *,
        session_id: str | None = None,
        match_id: str | None = None,
        profile_key: str | None = None,
    ) -> None:
        """Send an audio_update as a top-level message, without clock wrapping.

        The frontend contract is intentionally exactly these four fields:
            type, card_id, audio_url, match_seconds

        When session_id is provided, that session is the primary routing key.
        If its connection has a match_id, a conflicting match_id is rejected;
        a missing connection match_id does not prevent delivery to the exact
        requested session. If no session_id is supplied, match/profile routing
        uses the same strict matching semantics as other broadcasts.
        """
        if not isinstance(audio_payload, dict):
            raise TypeError("audio_payload must be a dictionary")
        if audio_payload.get("type") != "audio_update":
            raise ValueError("audio_payload.type must be 'audio_update'")
        if not audio_payload.get("card_id"):
            raise ValueError("audio_update requires card_id")
        if "audio_url" not in audio_payload:
            raise ValueError("audio_update requires audio_url (URL or None)")
        if "match_seconds" not in audio_payload:
            raise ValueError("audio_update requires match_seconds")

        # Construct a clean, stable wire payload; do not expose internal audio
        # service fields (e.g. duration_ms) or routing metadata.
        payload = {
            "type": "audio_update",
            "card_id": str(audio_payload["card_id"]),
            "audio_url": audio_payload["audio_url"],
            "match_seconds": audio_payload["match_seconds"],
        }

        async with self._lock:
            if session_id is not None:
                entry = self._connections.get(session_id)
                conns = [(session_id, entry)] if entry is not None else []
            else:
                conns = list(self._connections.items())

        for sid, entry in conns:
            if entry is None:
                continue

            if session_id is not None:
                # Exact session routing is authoritative. Enforce a match ID
                # only when the connection has one recorded.
                connection_match = entry.get("match_id")
                if match_id is not None and connection_match is not None and connection_match != match_id:
                    continue
                if profile_key is not None and entry.get("profile_key") != profile_key:
                    continue
            elif not self._matches_target(
                entry,
                profile_key=profile_key,
                match_id=match_id,
            ):
                continue

            ws = entry.get("ws")
            if ws is None:
                continue
            try:
                # IMPORTANT: send the audio_update directly. Do not call
                # broadcast_clock(), which would wrap it as clock_update.clock.
                await ws.send_text(json.dumps(payload))
            except Exception:
                await self.disconnect(sid)

    async def _pinger(self) -> None:
        try:
            while True:
                await asyncio.sleep(30.0)
                async with self._lock:
                    conns = list(self._connections.items())
                ping = {"type": "ping", "ts": time.time()}
                for sid, entry in conns:
                    ws = entry.get("ws")
                    try:
                        await ws.send_text(json.dumps(ping))
                    except Exception:
                        await self.disconnect(sid)
        except asyncio.CancelledError:
            return


async def websocket_endpoint(
    websocket: WebSocket,
    manager: WebSocketManager,
    session_manager: Any,
) -> None:
    """Accept a viewer connection and process basic WebSocket commands."""
    session_id = websocket.query_params.get("session_id")
    profile_key = websocket.query_params.get("profile_key")
    match_id = websocket.query_params.get("match_id")

    sid = await manager.connect(
        websocket,
        session_id=session_id,
        profile_key=profile_key,
        match_id=match_id,
    )

    if session_manager is not None and getattr(session_manager, "touch", None):
        session_manager.touch(sid)

    try:
        while True:
            text = await websocket.receive_text()
            try:
                data = json.loads(text)
            except Exception:
                await websocket.send_text(
                    json.dumps({"type": "error", "message": "invalid_json"})
                )
                continue

            cmd = data.get("type")

            if cmd == "ping":
                await websocket.send_text(
                    json.dumps({"type": "pong", "ts": time.time()})
                )
                continue

            if cmd == "profile_update":
                meta = data.get("payload") or {}
                if session_manager is not None and getattr(session_manager, "get", None):
                    rec = session_manager.get(sid)
                    if rec is not None:
                        rec.metadata.update(meta)
                        session_manager.touch(sid)

                profile_key = meta.get("profile_key") or profile_key
                match_id = meta.get("match_id") or match_id

                async with manager._lock:
                    if sid in manager._connections:
                        manager._connections[sid]["profile_key"] = profile_key
                        manager._connections[sid]["match_id"] = match_id
                        manager._connections[sid]["session_id"] = sid

                await websocket.send_text(
                    json.dumps({"type": "ack", "cmd": "profile_update"})
                )
                continue

            if cmd == "speed":
                await websocket.send_text(
                    json.dumps({
                        "type": "ack",
                        "cmd": "speed",
                        "speed": data.get("speed"),
                    })
                )
                continue

            if cmd == "restart":
                await websocket.send_text(
                    json.dumps({"type": "ack", "cmd": "restart"})
                )
                continue

            await websocket.send_text(
                json.dumps({"type": "ack", "cmd": cmd})
            )

    except Exception:
        await manager.disconnect(sid)


__all__ = ["WebSocketManager", "websocket_endpoint"]
